"""System-tray recording control (AppIndicator3).

Shows an icon in the GNOME top bar while recording; clicking it opens a menu with
Pause/Resume, Stop & Save, Open folder and Settings. Requires the
`ubuntu-appindicators` shell extension (enabled by default on Ubuntu GNOME).

Preferred over the floating pill widget; the caller falls back to
recording_widget.RecordingWidget if this can't be created.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AppIndicator3", "0.1")
from gi.repository import AppIndicator3, Gtk  # noqa: E402

from .recording_widget import _fmt  # noqa: E402  (shared MM:SS formatter)
from .utils import LOG  # noqa: E402

_ID = "meeting-recorder"
# Symbolic names, and our own icon as the last resort. The panel is drawn by
# gnome-shell, which resolves icons against the *shell's* theme (Yaru here) —
# not GTK's search path. Yaru ships only `media-record-symbolic`, so the plain
# `media-record` name resolved for GTK (via the legacy Humanity theme) while
# the shell found nothing and drew an invisible icon. `meeting-recorder` lives
# in hicolor, which every theme inherits.
_ICON_RECORDING = ("media-record-symbolic", "meeting-recorder")
_ICON_PAUSED = ("media-playback-pause-symbolic", "meeting-recorder")


def _icon_name(candidates: tuple[str, ...]) -> str:
    """First candidate the icon theme actually has, else our bundled icon."""
    try:
        theme = Gtk.IconTheme.get_default()
        for name in candidates:
            if theme.has_icon(name):
                return name
    except Exception:  # pragma: no cover - no theme (headless)
        LOG.debug("icon theme lookup failed", exc_info=True)
    return candidates[-1]


class RecordingTray:
    """Tray icon + menu mirroring the RecordingWidget interface."""

    def __init__(self, on_pause: Callable[[], None],
                 on_resume: Callable[[], None],
                 on_stop: Callable[[], None],
                 output_dir: Path | None = None) -> None:
        self.on_pause = on_pause
        self.on_resume = on_resume
        self.on_stop = on_stop
        self.output_dir = output_dir
        self.paused = False

        self.ind = AppIndicator3.Indicator.new(
            _ID, _icon_name(_ICON_RECORDING),
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS)
        self.ind.set_status(AppIndicator3.IndicatorStatus.PASSIVE)

        self.menu = Gtk.Menu()

        # Live status line, e.g. "● Recording — 01:23"
        self.header = Gtk.MenuItem(label="● Recording — 00:00")
        self.header.set_sensitive(False)
        self._add(self.header)
        self._add(Gtk.SeparatorMenuItem())

        self.pause_item = Gtk.MenuItem(label="Pause")
        self.pause_item.connect("activate", self._on_pause_activate)
        self._add(self.pause_item)

        self.stop_item = Gtk.MenuItem(label="Stop & Save")
        self.stop_item.connect("activate", lambda _i: self.on_stop())
        self._add(self.stop_item)

        self._add(Gtk.SeparatorMenuItem())

        self.folder_item = Gtk.MenuItem(label="Open recordings folder")
        self.folder_item.connect("activate", self._on_open_folder)
        self._add(self.folder_item)

        self.settings_item = Gtk.MenuItem(label="Settings…")
        self.settings_item.connect("activate", self._on_open_settings)
        self._add(self.settings_item)

        self.menu.show_all()
        self.ind.set_menu(self.menu)

    def _add(self, item: Gtk.MenuItem) -> None:
        self.menu.append(item)
        item.show()

    # -- lifecycle (same surface as RecordingWidget) -----------------------
    def show(self) -> None:
        self.paused = False
        self._refresh()
        self.ind.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

    def close(self) -> None:
        self.ind.set_status(AppIndicator3.IndicatorStatus.PASSIVE)

    def update_time(self, seconds: float) -> None:
        state = "Paused" if self.paused else "● Recording"
        self.header.set_label(f"{state} — {_fmt(seconds)}")
        # Some shells render a label next to the icon; harmless if ignored.
        self.ind.set_label(f" {_fmt(seconds)}", "00:00")

    # -- menu actions ------------------------------------------------------
    def _on_pause_activate(self, _item: Gtk.MenuItem) -> None:
        if self.paused:
            self.paused = False
            self.on_resume()
        else:
            self.paused = True
            self.on_pause()
        self._refresh()

    def _refresh(self) -> None:
        self.pause_item.set_label("Resume" if self.paused else "Pause")
        self.ind.set_icon_full(
            _icon_name(_ICON_PAUSED if self.paused else _ICON_RECORDING),
            "Paused" if self.paused else "Recording")

    def _on_open_folder(self, _item: Gtk.MenuItem) -> None:
        target = str(self.output_dir or Path.home())
        try:
            subprocess.Popen(["xdg-open", target],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            LOG.warning("Could not open %s: %s", target, exc)

    def _on_open_settings(self, _item: Gtk.MenuItem) -> None:
        # Spawn a separate process: the daemon runs a GLib loop and must not
        # start a nested Gtk.main(). Prefer the installed console script, and
        # fall back to the module (source checkouts).
        exe = shutil.which("meeting-recorder")
        cmd = [exe, "settings"] if exe else [sys.executable, "-m",
                                             "meeting_recorder", "settings"]
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            LOG.warning("Could not open settings: %s", exc)
