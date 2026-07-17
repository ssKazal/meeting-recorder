"""Meeting detection via active microphone capture streams.

A meeting is inferred when a *known* app (allowlist) holds a PulseAudio/PipeWire
source-output — i.e. it is actively capturing the microphone. We poll
`pactl list source-outputs` on a timer and run the result through a debounce
state machine so brief blips (mutes, renegotiation) don't start/stop recording.

The parsing and debounce logic are pure functions/classes so they are unit-tested
without a live audio server (see tests/).
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from .config import AllowEntry
from .utils import LOG

# ---------------------------------------------------------------------------
# Pure parsing / matching
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceOutput:
    """A single active capture stream reported by pactl."""
    index: int
    app_name: str          # application.name property (e.g. "Firefox")
    binary: str            # application.process.binary property (e.g. "firefox")
    source: str            # the source it records from (mic vs *.monitor)

    @property
    def is_monitor(self) -> bool:
        return self.source.endswith(".monitor") or "monitor" in self.source.lower()


_HEADER_RE = re.compile(r"^Source Output #(\d+)", re.MULTILINE)


def _prop(block: str, key: str) -> str:
    m = re.search(rf'^\s*{re.escape(key)}\s*=\s*"?(.*?)"?\s*$', block, re.MULTILINE)
    return m.group(1) if m else ""


def parse_source_outputs(text: str) -> list[SourceOutput]:
    """Parse `pactl list source-outputs` text output into SourceOutput records."""
    outputs: list[SourceOutput] = []
    starts = [(m.start(), int(m.group(1))) for m in _HEADER_RE.finditer(text)]
    for i, (pos, index) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        block = text[pos:end]
        app_name = _prop(block, "application.name")
        binary = _prop(block, "application.process.binary")
        # 'Source:' line gives the device index/name; prefer the readable field.
        src = _prop(block, "device.name") or _prop(block, "node.name")
        if not src:
            sm = re.search(r"^\s*Source:\s*(.*?)\s*$", block, re.MULTILINE)
            src = sm.group(1) if sm else ""
        outputs.append(SourceOutput(index=index, app_name=app_name,
                                    binary=binary, source=src))
    return outputs


def match_meeting_app(outputs: list[SourceOutput],
                      allowlist: list[AllowEntry]) -> str | None:
    """Return the friendly app name of the first allowlisted mic-capturing stream.

    Monitor captures (system-audio taps, incl. our own recorder) are ignored so
    we only trigger on genuine *microphone* use.
    """
    for out in outputs:
        if out.is_monitor:
            continue
        haystack = f"{out.app_name} {out.binary}".lower()
        for entry in allowlist:
            if entry.match and entry.match in haystack:
                return entry.app
    return None


# ---------------------------------------------------------------------------
# Debounce state machine
# ---------------------------------------------------------------------------


class DebounceMachine:
    """Convert a stream of (matched_app | None, timestamp) samples into
    'start(app)' / 'stop()' events, requiring sustained presence/absence.
    """

    def __init__(self, start_debounce: float, stop_debounce: float):
        self.start_debounce = start_debounce
        self.stop_debounce = stop_debounce
        self.in_meeting = False
        self.current_app: str | None = None
        self._candidate_app: str | None = None
        self._candidate_since: float | None = None
        self._absent_since: float | None = None
        # Seconds we kept recording after the audio actually stopped (i.e. the
        # debounce wait). The recorder trims this off the end so the file stops
        # when the call did, without having to shorten the debounce.
        self.stop_overshoot: float = 0.0

    def update(self, matched_app: str | None, now: float) -> tuple[str, str | None] | None:
        """Feed one sample; return ('start', app) or ('stop', None) when a
        transition is confirmed, else None.
        """
        if not self.in_meeting:
            if matched_app is None:
                self._candidate_app = None
                self._candidate_since = None
                return None
            # A candidate meeting app is present.
            if self._candidate_app != matched_app:
                self._candidate_app = matched_app
                self._candidate_since = now
            if now - self._candidate_since >= self.start_debounce:
                self.in_meeting = True
                self.current_app = matched_app
                self._candidate_app = None
                self._candidate_since = None
                self._absent_since = None
                return ("start", matched_app)
            return None
        # Currently in a meeting.
        if matched_app is not None:
            self._absent_since = None  # still active
            return None
        if self._absent_since is None:
            self._absent_since = now
        if now - self._absent_since >= self.stop_debounce:
            self.in_meeting = False
            self.current_app = None
            # How long we over-recorded past the real end of the call.
            self.stop_overshoot = now - self._absent_since
            self._absent_since = None
            return ("stop", None)
        return None


# ---------------------------------------------------------------------------
# Live poller
# ---------------------------------------------------------------------------


def query_source_outputs() -> list[SourceOutput]:
    """Run pactl and parse the current capture streams."""
    try:
        out = subprocess.run(
            ["pactl", "list", "source-outputs"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return parse_source_outputs(out.stdout)
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        LOG.debug("pactl list source-outputs failed: %s", exc)
        return []


class MeetingDetector:
    """Polls capture streams and invokes callbacks on debounced transitions.

    on_start(app_name) and on_stop() are called from the polling context
    (the GLib main loop when driven by MeetingDetector.tick via a timeout).
    """

    def __init__(self, allowlist: list[AllowEntry],
                 start_debounce: float, stop_debounce: float,
                 on_start: Callable[[str], None],
                 on_stop: Callable[[float], None]):
        self.allowlist = allowlist
        self.machine = DebounceMachine(start_debounce, stop_debounce)
        self.on_start = on_start
        self.on_stop = on_stop

    def tick(self) -> bool:
        """One poll cycle. Returns True so it can be used as a GLib timeout source."""
        outputs = query_source_outputs()
        app = match_meeting_app(outputs, self.allowlist)
        event = self.machine.update(app, time.monotonic())
        if event is None:
            return True
        kind, name = event
        try:
            if kind == "start" and name is not None:
                LOG.info("Meeting detected: %s", name)
                self.on_start(name)
            elif kind == "stop":
                LOG.info("Meeting ended")
                self.on_stop(self.machine.stop_overshoot)
        except Exception:  # never let a callback kill the poll loop
            LOG.exception("detector callback failed")
        return True
