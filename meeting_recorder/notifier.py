"""Desktop notifications with action buttons via libnotify (gi.repository.Notify).

Action callbacks are delivered on the GLib main loop that the daemon already runs.
Falls back to `notify-send` (no buttons) if the Notify typelib is unavailable.
"""

from __future__ import annotations

import subprocess
from typing import Callable

from .utils import LOG

_APP_NAME = "Smart Meeting Recorder"

try:
    import gi
    gi.require_version("Notify", "0.7")
    from gi.repository import Notify  # type: ignore
    _HAVE_NOTIFY = True
except (ImportError, ValueError):  # pragma: no cover - depends on system typelibs
    _HAVE_NOTIFY = False

# How long transient info notifications stay before auto-closing (ms).
_INFO_TIMEOUT_MS = 2000


class Notifier:
    def __init__(self) -> None:
        self._ready = False
        if _HAVE_NOTIFY:
            try:
                Notify.init(_APP_NAME)
                self._ready = True
            except Exception:  # pragma: no cover
                LOG.exception("Notify.init failed; using notify-send fallback")
        # Keep a reference so the notification isn't GC'd before the user acts.
        self._active = None
        self._live: set = set()  # notifications still awaiting a click/close

    # -- fallback -----------------------------------------------------------
    @staticmethod
    def _fallback(summary: str, body: str) -> None:
        try:
            # -t lets the banner expire on its own; no -e, so it stays in the
            # notification centre.
            subprocess.run(["notify-send", "-a", _APP_NAME,
                            "-t", str(_INFO_TIMEOUT_MS), summary, body],
                           timeout=5, check=False)
        except (subprocess.SubprocessError, FileNotFoundError):
            LOG.info("[notify] %s — %s", summary, body)

    # -- simple info -------------------------------------------------------
    def info(self, summary: str, body: str = "", icon: str = "media-record",
             on_click: Callable[[], None] | None = None,
             click_label: str = "Open", persistent: bool = False) -> None:
        """Show a notification that stays in the notification centre.

        `persistent=False` (default) lets the banner slide away after ~2s;
        `persistent=True` keeps it on screen until the user acts — use it for
        actionable notifications so the click target doesn't disappear.

        We deliberately never set the 'transient' hint or call close() — either
        would drop the notification from the centre. `on_click` becomes a named
        action, which the shell renders as a button on the notification.
        """
        if not self._ready:
            self._fallback(summary, body)
            return
        note = Notify.Notification.new(summary, body, icon)
        if persistent:
            # CRITICAL urgency is what makes GNOME hold the banner open.
            note.set_urgency(Notify.Urgency.CRITICAL)
            note.set_timeout(Notify.EXPIRES_NEVER)
        else:
            note.set_timeout(_INFO_TIMEOUT_MS)
        if on_click is not None:
            # A named (non-"default") action renders as a button. "default" would
            # instead make the whole banner clickable with no visible button.
            note.add_action("open-folder", click_label,
                            lambda _n, _a: self._invoke(on_click))
        # Hold a reference until it closes, otherwise the action callback dies.
        self._live.add(note)
        note.connect("closed", lambda n: self._live.discard(n))
        try:
            note.show()
        except Exception:  # pragma: no cover
            self._live.discard(note)
            self._fallback(summary, body)

    @staticmethod
    def _invoke(cb: Callable[[], None]) -> None:
        try:
            cb()
        except Exception:  # pragma: no cover - never let a click kill the daemon
            LOG.exception("notification click handler failed")

    # -- prompt with Record / Ignore ---------------------------------------
    def prompt_record(self, app_name: str, timeout_seconds: int,
                      on_record: Callable[[], None],
                      on_ignore: Callable[[], None]) -> None:
        """Show 'Meeting detected. Start recording?' with two action buttons."""
        summary = "Meeting detected"
        body = f"{app_name} call in progress. Start recording?"
        if not self._ready:
            # Without action support, default to *not* recording (privacy-first).
            self._fallback(summary, body + " (enable the tray/GUI for one-click record)")
            on_ignore()
            return

        note = Notify.Notification.new(summary, body, "camera-video")
        note.set_urgency(Notify.Urgency.CRITICAL)  # keep it on screen until answered
        note.set_timeout(timeout_seconds * 1000)

        def _record(_n, _action):
            on_record()

        def _ignore(_n, _action):
            on_ignore()

        note.add_action("record", "Record", _record)
        note.add_action("ignore", "Ignore", _ignore)
        note.connect("closed", lambda _n: None)
        self._active = note
        try:
            note.show()
        except Exception:  # pragma: no cover
            self._fallback(summary, body)
            on_ignore()

    def close_active(self) -> None:
        if self._active is not None:
            try:
                self._active.close()
            except Exception:  # pragma: no cover
                pass
            self._active = None
