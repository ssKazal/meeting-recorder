"""Resolve PulseAudio/PipeWire devices used for recording.

Uses `pactl` (provided by pulseaudio-utils, backed by pipewire-pulse). All calls
degrade gracefully to the special names 'default' / '@DEFAULT_SINK@' so recording
can still proceed if introspection fails.
"""

from __future__ import annotations

import subprocess

from .utils import LOG


def _pactl(*args: str) -> str:
    try:
        out = subprocess.run(
            ["pactl", *args], capture_output=True, text=True, timeout=5, check=True
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        LOG.debug("pactl %s failed: %s", " ".join(args), exc)
        return ""


def default_source() -> str:
    """Default microphone source name (falls back to 'default')."""
    return _pactl("get-default-source") or "default"


def default_sink() -> str:
    """Default output sink name (falls back to '@DEFAULT_SINK@')."""
    return _pactl("get-default-sink") or "@DEFAULT_SINK@"


def monitor_source() -> str:
    """Monitor source of the default sink — this is what captures *system audio*."""
    sink = default_sink()
    if sink == "@DEFAULT_SINK@":
        # Special sink token has no derivable monitor name; use the generic monitor.
        return "@DEFAULT_MONITOR@"
    return f"{sink}.monitor"
