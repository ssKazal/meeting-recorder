"""GTK settings window for Smart Meeting Recorder.

Edits the same ~/.config/meeting-recorder/config.json the daemon reads. Only a
curated subset of keys is exposed; everything else (e.g. the allowlist) is loaded
and written back untouched. Launch with:  python -m meeting_recorder settings
"""

from __future__ import annotations

import shutil
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .config import load_raw_config, save_user_config, user_config_path
from .utils import LOG, expand_path

CONTAINERS = ["mkv", "mp4"]
# (config value, display label)
CAPTURE_MODES = [("fullscreen", "Full screen"),
                 ("window", "Current window"),
                 ("area", "Selected area")]


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

        # --- Storage ------------------------------------------------------
        self._section(grid, "Storage")
        self.output_chooser = Gtk.FileChooserButton(
            title="Recording folder", action=Gtk.FileChooserAction.SELECT_FOLDER)
        self.output_chooser.set_filename(str(expand_path(self.data.get("output_dir", "~"))))
        self._field(grid, "Save folder", self.output_chooser)

        self.format_combo = Gtk.ComboBoxText()
        for c in CONTAINERS:
            self.format_combo.append_text(c)
        cur = self.data.get("container", "mkv")
        self.format_combo.set_active(CONTAINERS.index(cur) if cur in CONTAINERS else 0)
        self._field(grid, "File format", self.format_combo)

        # --- Video --------------------------------------------------------
        self._section(grid, "Video")
        self.screen_switch = self._switch(self.data.get("record_screen", True))
        self._field(grid, "Record screen", self.screen_switch)

        self.capture_combo = Gtk.ComboBoxText()
        for _val, label in CAPTURE_MODES:
            self.capture_combo.append_text(label)
        cur_mode = self.data.get("capture_mode", "fullscreen")
        idx = next((i for i, (v, _l) in enumerate(CAPTURE_MODES) if v == cur_mode), 0)
        self.capture_combo.set_active(idx)
        self.capture_combo.connect("changed", self._on_capture_mode_changed)
        self._field(grid, "Capture area", self.capture_combo)

        # Region row (only for "Selected area"): an x,y,w,h entry + drag-select button.
        region_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.region_entry = Gtk.Entry()
        self.region_entry.set_placeholder_text("x,y,w,h")
        self.region_entry.set_text(self.data.get("capture_region", ""))
        self.region_entry.set_hexpand(True)
        self.select_btn = Gtk.Button(label="Select…")
        self.select_btn.connect("clicked", self._on_select_area)
        region_box.pack_start(self.region_entry, True, True, 0)
        region_box.pack_start(self.select_btn, False, False, 0)
        self._field(grid, "Region", region_box)

        self.fps_spin = Gtk.SpinButton.new_with_range(5, 60, 1)
        self.fps_spin.set_value(int(self.data.get("framerate", 30)))
        self._field(grid, "Frame rate (fps)", self.fps_spin)
        self._on_capture_mode_changed(self.capture_combo)  # set initial sensitivity

        # --- Audio --------------------------------------------------------
        self._section(grid, "Audio")
        self.mic_switch = self._switch(self.data.get("record_mic", True))
        self._field(grid, "Record microphone", self.mic_switch)

        self.sys_switch = self._switch(self.data.get("record_system_audio", True))
        self._field(grid, "Record system audio", self.sys_switch)

        self.mic_vol = self._volume_scale(self.data.get("mic_volume", 1.0))
        self._field(grid, "Mic volume", self.mic_vol)

        self.sys_vol = self._volume_scale(self.data.get("system_volume", 1.0))
        self._field(grid, "System volume", self.sys_vol)

        self.normalize_switch = self._switch(self.data.get("normalize_voice", True))
        self._field(grid, "Equalize voices (normalize)", self.normalize_switch)

        self.noise_switch = self._switch(self.data.get("noise_cancellation", True))
        self._field(grid, "Noise cancellation", self.noise_switch)

        # --- Behavior -----------------------------------------------------
        self._section(grid, "Behavior")
        self.auto_switch = self._switch(self.data.get("auto_record", False))
        self._field(grid, "Auto-record (skip popup)", self.auto_switch)

        self.timeout_spin = Gtk.SpinButton.new_with_range(5, 120, 1)
        self.timeout_spin.set_value(int(self.data.get("prompt_timeout_seconds", 30)))
        self._field(grid, "Popup timeout (s)", self.timeout_spin)

        self.stop_spin = Gtk.SpinButton.new_with_range(0.5, 15, 0.5)
        self.stop_spin.set_digits(1)
        self.stop_spin.set_value(float(self.data.get("stop_debounce_seconds", 2.0)))
        self._field(grid, "Stop delay after call (s)", self.stop_spin)

        # --- Buttons ------------------------------------------------------
        self.status = Gtk.Label(label="", xalign=0)
        outer.pack_start(self.status, False, False, 0)

        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btns.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label="Close")
        cancel.connect("clicked", lambda _b: self.close())
        save = Gtk.Button(label="Save")
        save.connect("clicked", lambda _b: self._save(restart=False))
        save_restart = Gtk.Button(label="Save & Apply")
        save_restart.get_style_context().add_class("suggested-action")
        save_restart.connect("clicked", lambda _b: self._save(restart=True))
        for b in (cancel, save, save_restart):
            btns.pack_start(b, False, False, 0)
        outer.pack_start(btns, False, False, 0)

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

    @staticmethod
    def _volume_scale(value: float) -> Gtk.Scale:
        adj = Gtk.Adjustment(value=float(value), lower=0.0, upper=3.0,
                             step_increment=0.1, page_increment=0.5)
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
        scale.set_digits(1)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        for mark in (0.0, 1.0, 2.0, 3.0):
            scale.add_mark(mark, Gtk.PositionType.BOTTOM, None)
        return scale

    # -- capture-area handlers --------------------------------------------
    def _current_capture_mode(self) -> str:
        return CAPTURE_MODES[self.capture_combo.get_active()][0]

    def _on_capture_mode_changed(self, _combo: Gtk.ComboBoxText) -> None:
        is_area = self._current_capture_mode() == "area"
        self.region_entry.set_sensitive(is_area)
        self.select_btn.set_sensitive(is_area and shutil.which("slop") is not None)
        if is_area and shutil.which("slop") is None:
            self.select_btn.set_tooltip_text("Install 'slop' to drag-select a region")

    def _on_select_area(self, _btn: Gtk.Button) -> None:
        """Use `slop` to drag-select a screen region, then fill the entry."""
        if not shutil.which("slop"):
            self.status.set_text("Install 'slop' (sudo apt install slop) to drag-select.")
            return
        try:
            out = subprocess.run(["slop", "-f", "%x,%y,%w,%h"],
                                 capture_output=True, text=True, timeout=60)
            region = out.stdout.strip()
            if region:
                self.region_entry.set_text(region)
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            LOG.warning("slop failed: %s", exc)

    # -- save --------------------------------------------------------------
    def _save(self, restart: bool) -> None:
        folder = self.output_chooser.get_filename()
        self.data.update({
            "output_dir": folder or self.data.get("output_dir", "~/Videos/MeetingRecorder"),
            "container": CONTAINERS[self.format_combo.get_active()],
            "record_screen": self.screen_switch.get_active(),
            "capture_mode": self._current_capture_mode(),
            "capture_region": self.region_entry.get_text().strip(),
            "framerate": int(self.fps_spin.get_value()),
            "record_mic": self.mic_switch.get_active(),
            "record_system_audio": self.sys_switch.get_active(),
            "mic_volume": round(self.mic_vol.get_value(), 2),
            "system_volume": round(self.sys_vol.get_value(), 2),
            "normalize_voice": self.normalize_switch.get_active(),
            "noise_cancellation": self.noise_switch.get_active(),
            "auto_record": self.auto_switch.get_active(),
            "prompt_timeout_seconds": int(self.timeout_spin.get_value()),
            "stop_debounce_seconds": round(self.stop_spin.get_value(), 1),
        })
        path = save_user_config(self.data)
        msg = f"Saved to {path}"
        if restart:
            ok = _restart_service()
            msg += "  •  service restarted" if ok else "  •  saved (restart the app to apply)"
        self.status.set_markup(f"<span foreground='#2e7d32'>{msg}</span>")
        LOG.info(msg)


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
