"""Ties detector -> notifier -> recorder together as a small state machine.

States: IDLE -> PROMPTING -> RECORDING -> IDLE.
- Meeting detected  : prompt the user (or auto-record if configured).
- User clicks Record: start the recorder.
- Meeting ends      : stop + save, notify, return to IDLE.
An ignored session is remembered so we don't re-prompt for the same call.
"""

from __future__ import annotations

import enum

from .config import Config
from .notifier import Notifier
from .recorder import Recorder
from .utils import LOG, build_output_path, open_folder


class State(enum.Enum):
    IDLE = "idle"
    PROMPTING = "prompting"
    RECORDING = "recording"


class Controller:
    def __init__(self, cfg: Config, notifier: Notifier, recorder: Recorder):
        self.cfg = cfg
        self.notifier = notifier
        self.recorder = recorder
        self.state = State.IDLE
        self._app: str | None = None
        self._ignored_session = False
        self._widget = None          # floating RecordingWidget (if display present)
        self._timer_source = None    # GLib timeout id for the elapsed-time updates

    # -- called by the detector --------------------------------------------
    def on_meeting_start(self, app_name: str) -> None:
        if self.state is not State.IDLE:
            return
        self._app = app_name
        self._ignored_session = False
        if self.cfg.auto_record:
            self._begin_recording()
            return
        self.state = State.PROMPTING
        self.notifier.prompt_record(
            app_name, self.cfg.prompt_timeout_seconds,
            on_record=self._on_user_record,
            on_ignore=self._on_user_ignore,
        )

    def on_meeting_stop(self, overshoot: float = 0.0) -> None:
        """`overshoot` = seconds recorded after the call's audio actually ended
        (the detector's debounce wait); it gets trimmed off the saved file.
        """
        self.notifier.close_active()
        if self.state is State.RECORDING:
            self._finish_recording(trim_end=overshoot)
        self.state = State.IDLE
        self._app = None

    # -- notification callbacks --------------------------------------------
    def _on_user_record(self) -> None:
        if self.state is State.PROMPTING:
            self._begin_recording()

    def _on_user_ignore(self) -> None:
        if self.state is State.PROMPTING:
            LOG.info("User declined recording for %s", self._app)
            self._ignored_session = True
            self.state = State.IDLE

    # -- recording helpers -------------------------------------------------
    def _begin_recording(self) -> None:
        app = self._app or "Meeting"
        path = build_output_path(self.cfg.output_dir, app, self.cfg.container)
        self.recorder.start(path)
        self.state = State.RECORDING
        self._show_widget()
        if self._widget is None:
            # No tray icon / pill to show status, so a notification is the only
            # signal that recording began. With controls visible it's redundant.
            self.notifier.info("Recording started", f"{app} — saving to {path.name}")

    def _finish_recording(self, trim_end: float = 0.0) -> None:
        self._close_widget()
        too_short = self.recorder.elapsed() - trim_end < self.cfg.min_recording_seconds
        if too_short:
            self.recorder.stop(discard=True)
            self.notifier.info("Recording discarded", "Call was too short to save.")
            return
        if not self.recorder.stop(trim_end=trim_end):
            self.notifier.info("Recording stopped", "No file was saved.")
            return
        # Finalize (denoise + normalize + mix) runs in the background so the
        # daemon stays responsive; poll it and notify when the file is ready.
        self.notifier.info("Processing recording…", "Balancing audio — almost done.")
        try:
            from gi.repository import GLib
            GLib.timeout_add(1000, self._poll_finalize)
        except Exception:  # pragma: no cover - no GLib: fall back to blocking
            path = self.recorder.wait_finalize()
            self._notify_finalized(path)

    def _poll_finalize(self) -> bool:
        done, path = self.recorder.poll_finalize()
        if not done:
            return True  # keep polling
        self._notify_finalized(path)
        return False

    def _notify_finalized(self, path) -> None:
        # These stay on screen until dismissed: "saved" is clickable (opening the
        # folder), and a failure needs to be seen.
        if path is None:
            self.notifier.info("Recording failed", "Could not finalize the file.",
                               persistent=True)
        else:
            self.notifier.info(
                "Recording saved", path.name,
                icon="folder-videos",
                on_click=lambda p=path: open_folder(p),
                click_label="📁 Open Folder",
                persistent=True,
            )

    # -- recording controls (tray icon, or floating pill fallback) ---------
    def _show_widget(self) -> None:
        self._widget = self._build_controls()
        if self._widget is None:
            return
        try:
            from gi.repository import GLib
            self._widget.show()
            self._timer_source = GLib.timeout_add(500, self._tick_widget)
        except Exception:  # pragma: no cover
            LOG.debug("could not show recording controls", exc_info=True)
            self._widget = None

    def _build_controls(self):
        """Prefer the top-bar tray icon; fall back to the floating pill."""
        kwargs = dict(on_pause=self.recorder.pause,
                      on_resume=self.recorder.resume,
                      on_stop=self._on_widget_stop)
        try:
            from .tray_indicator import RecordingTray
            return RecordingTray(output_dir=self.cfg.output_dir, **kwargs)
        except Exception:
            LOG.debug("tray indicator unavailable; trying floating widget",
                      exc_info=True)
        try:
            from .recording_widget import RecordingWidget
            return RecordingWidget(**kwargs)
        except Exception:  # no display / GTK missing — record without controls
            LOG.debug("recording controls unavailable", exc_info=True)
            return None

    def _tick_widget(self) -> bool:
        if self.state is not State.RECORDING or self._widget is None:
            return False
        self._widget.update_time(self.recorder.elapsed())
        return True

    def _on_widget_stop(self) -> None:
        if self.state is State.RECORDING:
            LOG.info("User stopped recording from the widget")
            self._finish_recording()
            self.state = State.IDLE

    def _close_widget(self) -> None:
        if self._timer_source is not None:
            try:
                from gi.repository import GLib
                GLib.source_remove(self._timer_source)
            except Exception:  # pragma: no cover
                pass
            self._timer_source = None
        if self._widget is not None:
            self._widget.close()
            self._widget = None

    # -- shutdown ----------------------------------------------------------
    def shutdown(self) -> None:
        if self.recorder.is_recording:
            self._finish_recording()
        if self.recorder.is_finalizing:
            # Block on exit so an in-flight recording is never lost.
            LOG.info("Waiting for finalize to finish before exiting…")
            self._notify_finalized(self.recorder.wait_finalize())
