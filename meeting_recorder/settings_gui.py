"""GTK settings window for Smart Meeting Recorder.

Edits the same ~/.config/meeting-recorder/config.json the daemon reads. Only a
curated subset of keys is exposed; everything else (e.g. the allowlist) is loaded
and written back untouched. Launch with:  python -m meeting_recorder settings
"""

from __future__ import annotations

import shutil
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .config import load_defaults, load_raw_config, save_user_config
from .utils import LOG, expand_path



class SettingsWindow(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title="Meeting Recorder — Settings")
        self.set_default_size(600, 660)
        self.set_border_width(16)
        self.data = load_raw_config()

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add(outer)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        # Give the scrollbar its own gutter so it never overlaps the controls.
        scroller.set_overlay_scrolling(False)
        outer.pack_start(scroller, True, True, 0)

        grid = Gtk.Grid(row_spacing=10, column_spacing=14)
        grid.set_column_homogeneous(False)
        grid.set_margin_end(12)   # keep right-aligned widgets clear of the scrollbar
        grid.set_margin_start(2)
        scroller.add(grid)
        self._row = 0

        # Deliberately minimal. Everything else the daemon understands stays
        # editable in ~/.config/meeting-recorder/config.json — hiding a knob
        # here does not remove the feature, it just stops the window from
        # presenting a decision most people should not have to make.
        # Not shown, and why:
        #   container      mkv survives an interrupted recording; mp4 does not
        #   framerate      30 is right for a meeting; 60 only doubles the size
        #   capture_mode   full screen is the meeting case, and on Wayland the
        #   capture_region portal already asks which screen or window to share
        #   mic/system     volume  loudnorm already equalises both sources, so
        #                  these fight the normaliser
        #   normalize_voice  equalising the two voices should just be on
        #   prompt_timeout_seconds  30s needs no tuning

        # --- Storage ------------------------------------------------------
        self._section(grid, "Storage")
        self.output_chooser = Gtk.FileChooserButton(
            title="Recording folder", action=Gtk.FileChooserAction.SELECT_FOLDER)
        self._field(grid, "Save folder", self.output_chooser)

        # --- What to record -------------------------------------------------
        self._section(grid, "What to record")
        self.screen_switch = self._switch(True)
        self._field(grid, "Screen", self.screen_switch)

        self.mic_switch = self._switch(True)
        self._field(grid, "Microphone", self.mic_switch)

        self.sys_switch = self._switch(True)
        self._field(grid, "System audio (the other people)", self.sys_switch)

        self.noise_switch = self._switch(True)
        self._field(grid, "Noise cancellation", self.noise_switch)

        # --- Behavior -----------------------------------------------------
        self._section(grid, "Behavior")
        self.auto_switch = self._switch(False)
        self._field(grid, "Auto-record (skip the popup)", self.auto_switch)

        # Apps release the mic while you are muted, which looks identical to
        # leaving the call — this delay is what stops a mute from ending the
        # recording. The wait is trimmed off the saved file, so a generous
        # value costs nothing but disk.
        self.stop_spin = Gtk.SpinButton.new_with_range(0.5, 300, 5)
        self.stop_spin.set_digits(1)
        self._field(grid, "Keep recording after the call ends (s)", self.stop_spin)

        self._load_into_widgets()

        # --- Buttons ------------------------------------------------------
        self.status = Gtk.Label(label="", xalign=0)
        outer.pack_start(self.status, False, False, 0)

        left = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        left.set_halign(Gtk.Align.START)
        self.record_btn = Gtk.Button(label="● Record now")
        self.record_btn.set_tooltip_text(
            "Start recording immediately, without waiting for a meeting to be "
            "detected. Stop it from the tray icon.")
        self.record_btn.connect("clicked", self._on_record_now)
        left.pack_start(self.record_btn, False, False, 0)
        # Reset sits apart from Save/Close so it is not clicked by accident.
        reset = Gtk.Button(label="Reset to defaults")
        reset.connect("clicked", self._on_reset)
        left.pack_start(reset, False, False, 0)
        outer.pack_start(left, False, False, 0)

        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btns.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _b: self.close())
        # One button, not "Save" and "Save & Apply": saving without applying
        # leaves the daemon running the old values with no sign that anything
        # is stale, which is a trap rather than a choice worth offering.
        save = Gtk.Button(label="Save")
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", lambda _b: self._save())
        for b in (cancel, save):
            btns.pack_start(b, False, False, 0)
        outer.pack_start(btns, False, False, 0)

    # -- load ---------------------------------------------------------------
    def _load_into_widgets(self) -> None:
        """Push self.data into every field. Used at startup and by Reset."""
        d = self.data
        self.output_chooser.set_filename(str(expand_path(d.get("output_dir", "~"))))
        self.screen_switch.set_active(bool(d.get("record_screen", True)))
        self.mic_switch.set_active(bool(d.get("record_mic", True)))
        self.sys_switch.set_active(bool(d.get("record_system_audio", True)))
        self.noise_switch.set_active(bool(d.get("noise_cancellation", True)))
        self.auto_switch.set_active(bool(d.get("auto_record", False)))
        self.stop_spin.set_value(float(d.get("stop_debounce_seconds", 60.0)))

    # -- widget helpers ----------------------------------------------------
    def _section(self, grid: Gtk.Grid, title: str) -> None:
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup(f"<b>{title}</b>")
        lbl.set_margin_top(8)
        grid.attach(lbl, 0, self._row, 2, 1)
        self._row += 1

    def _field(self, grid: Gtk.Grid, label: str, widget: Gtk.Widget) -> None:
        lbl = Gtk.Label(label=label, xalign=0)
        lbl.set_hexpand(True)
        grid.attach(lbl, 0, self._row, 1, 1)
        widget.set_halign(Gtk.Align.END if not isinstance(widget, Gtk.Scale)
                          else Gtk.Align.FILL)
        if isinstance(widget, (Gtk.Scale, Gtk.FileChooserButton)):
            widget.set_hexpand(True)
            widget.set_size_request(260, -1)
        grid.attach(widget, 1, self._row, 1, 1)
        self._row += 1

    @staticmethod
    def _switch(active: bool) -> Gtk.Switch:
        sw = Gtk.Switch()
        sw.set_active(bool(active))
        sw.set_halign(Gtk.Align.END)
        return sw

    # -- record now ---------------------------------------------------------
    def _on_record_now(self, _btn: Gtk.Button) -> None:
        """Start a manual recording in its own process.

        Spawns the `record` subcommand rather than recording in-process: that
        path already owns the tray icon, timer, pause/resume and the Wayland
        portal handshake, and this window must not start a second GLib loop.
        Detached, so the recording outlives the settings window.
        """
        exe = shutil.which("meeting-recorder")
        cmd = [exe, "record"] if exe else [sys.executable, "-m",
                                           "meeting_recorder", "record"]
        try:
            subprocess.Popen(cmd, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            LOG.warning("Could not start a manual recording: %s", exc)
            self.status.set_markup(
                f"<span foreground='#c62828'>Could not start recording: {exc}</span>")
            return
        self.status.set_markup(
            "<span foreground='#2e7d32'>Recording — stop it from the tray icon."
            "</span>")

    # -- reset -------------------------------------------------------------
    def _on_reset(self, _btn: Gtk.Button) -> None:
        """Put every field back to the shipped defaults, after confirming.

        Nothing is written until Save: the user can still close the window to
        back out. The allowlist and any keys this window does not expose are
        reset too — that is the point of "defaults" — so it is worth a prompt.
        """
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Reset all settings to their defaults?")
        dialog.format_secondary_text(
            "This also restores the meeting app allowlist and clears the saved "
            "screen-sharing permission. Nothing is written until you press Save.")
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return

        self.data = load_defaults()
        self._load_into_widgets()
        self.status.set_markup(
            "<span foreground='#b26a00'>Defaults loaded — press Save to apply."
            "</span>")

    # -- save --------------------------------------------------------------
    def _save(self) -> None:
        """Write the config, restart the daemon so it takes effect, and close.

        The restart is not optional: the daemon reads its config once at
        startup, so a saved-but-not-restarted setting silently does nothing.
        The window stays open only if the restart fails, so the user finds out.
        """
        folder = self.output_chooser.get_filename()
        # self.data came from load_raw_config(), so keys this window does not
        # expose (allowlist, framerate, capture_mode, ...) are written back
        # exactly as they were.
        self.data.update({
            "output_dir": folder or self.data.get("output_dir", "~/Videos/MeetingRecorder"),
            "record_screen": self.screen_switch.get_active(),
            "record_mic": self.mic_switch.get_active(),
            "record_system_audio": self.sys_switch.get_active(),
            "noise_cancellation": self.noise_switch.get_active(),
            "auto_record": self.auto_switch.get_active(),
            "stop_debounce_seconds": round(self.stop_spin.get_value(), 1),
        })
        path = save_user_config(self.data)
        LOG.info("Saved settings to %s", path)
        if _restart_service():
            self.close()
            return
        # Saved, but the running daemon still has the old values — say so
        # instead of closing on a half-applied change.
        self.status.set_markup(
            "<span foreground='#b26a00'>Saved, but the background service could "
            "not be restarted — run <tt>meeting-recorder restart</tt> to apply."
            "</span>")


def _restart_service() -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "restart", "meeting-recorder.service"],
            capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        LOG.warning("Could not restart service: %s", exc)
        return False


def run() -> int:
    win = SettingsWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
    return 0
