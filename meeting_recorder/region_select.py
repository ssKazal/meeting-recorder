"""Drag-to-select a screen region with the mouse.

Prefers the desktop's own area picker (`org.gnome.Shell.Screenshot.SelectArea`),
which is the same selector GNOME's screenshot tool uses — so it looks exactly
like the rest of the system and needs no styling from us. Only when that is
unavailable (a non-GNOME desktop) do we draw our own overlay.

Neither path uses `slop`, which was X11-only and left Wayland users typing
coordinates by hand.

Usage:

    region = select_region()      # "x,y,w,h", or None if cancelled
"""

from __future__ import annotations

import cairo
import gi

gi.require_version("Gtk", "3.0")
# Gdk must be pinned too, not just Gtk: imported on its own (before anything
# has pulled in Gtk 3), PyGObject would otherwise default to Gdk 4 and the
# import fails with a version clash.
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from .utils import LOG  # noqa: E402

_MIN_SIZE = 8  # px; below this a drag is almost certainly a stray click
# The user has to drag before this returns, so it must outlast a moment's
# hesitation — but not hang the settings window forever if the shell goes away.
_PICKER_TIMEOUT_MS = 120_000


def _gnome_select_area() -> tuple[int, int, int, int] | None:
    """GNOME's built-in area picker. None if unavailable or cancelled."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync(
            "org.gnome.Shell.Screenshot", "/org/gnome/Shell/Screenshot",
            "org.gnome.Shell.Screenshot", "SelectArea", None,
            GLib.VariantType("(iiii)"), Gio.DBusCallFlags.NONE,
            _PICKER_TIMEOUT_MS, None)
        x, y, w, h = reply.unpack()
        return (x, y, w, h) if w > 0 and h > 0 else None
    except GLib.Error as exc:
        # Cancelling the picker also lands here, which is why this is not an
        # error: both "no GNOME" and "user pressed Escape" mean "no region".
        LOG.debug("GNOME SelectArea unavailable or cancelled: %s", exc.message)
        return None


class _RegionOverlay(Gtk.Window):
    """Fallback picker: a dimmed full-screen window you drag a rectangle on."""

    def __init__(self) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.region: tuple[int, int, int, int] | None = None
        self.cancelled = False
        self._start: tuple[float, float] | None = None
        self._current: tuple[float, float] | None = None

        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        # Transparency needs an RGBA visual *and* compositing. Without one the
        # overlay would paint solid, hiding the very screen being selected.
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        self._can_dim = visual is not None and screen.is_composited()
        if visual is not None:
            self.set_visual(visual)
        self.fullscreen()

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK
                        | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK
                        | Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("draw", self._on_draw)
        self.connect("button-press-event", self._on_press)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("button-release-event", self._on_release)
        self.connect("key-press-event", self._on_key)

    def _accent(self) -> tuple[float, float, float]:
        """The theme's selection colour, so the marquee matches the desktop."""
        found, colour = self.get_style_context().lookup_color(
            "theme_selected_bg_color")
        if found:
            return colour.red, colour.green, colour.blue
        return 0.21, 0.52, 0.89

    # -- drawing -----------------------------------------------------------
    def _on_draw(self, _widget, cr) -> bool:
        width, height = self.get_size()

        # SOURCE, not the default OVER: this replaces the surface contents
        # including its alpha. Compositing 45% black OVER GTK's opaque backing
        # just yields black, which is what made the overlay a solid screen.
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0.45 if self._can_dim else 1.0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        rect = self._rect()
        if rect is None:
            self._draw_hint(cr, width, height)
            return False

        x, y, w, h = rect
        if self._can_dim:
            # Punch the selection out of the dim layer so it shows the real
            # screen underneath. CLEAR is 0 — the previous code passed 1, which
            # is SOURCE, so nothing was ever cleared.
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.rectangle(x, y, w, h)
            cr.fill()
            cr.set_operator(cairo.OPERATOR_OVER)

        r, g, b = self._accent()
        cr.set_source_rgba(r, g, b, 1.0)
        cr.set_line_width(2)
        cr.rectangle(x + 1, y + 1, max(0, w - 2), max(0, h - 2))
        cr.stroke()

        self._draw_size(cr, x, y, w, h, width)
        return False

    def _draw_size(self, cr, x, y, w, h, screen_width) -> None:
        label = f"{int(w)} × {int(h)}"
        cr.select_font_face("Sans")
        cr.set_font_size(14)
        ext = cr.text_extents(label)
        # Keep the readout on screen when selecting against an edge.
        tx = min(max(x, 4), max(4, screen_width - ext.width - 12))
        ty = y - 8 if y > 24 else y + h + 20
        cr.set_source_rgba(0, 0, 0, 0.75)
        cr.rectangle(tx - 4, ty - ext.height - 4, ext.width + 10, ext.height + 10)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 1)
        cr.move_to(tx, ty)
        cr.show_text(label)

    def _draw_hint(self, cr, width: int, height: int) -> None:
        text = "Drag to select a region  ·  Esc to cancel"
        cr.select_font_face("Sans")
        cr.set_font_size(18)
        ext = cr.text_extents(text)
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.move_to((width - ext.width) / 2, height / 2)
        cr.show_text(text)

    # -- interaction -------------------------------------------------------
    def _rect(self) -> tuple[int, int, int, int] | None:
        if self._start is None or self._current is None:
            return None
        x0, y0 = self._start
        x1, y1 = self._current
        return (int(min(x0, x1)), int(min(y0, y1)),
                int(abs(x1 - x0)), int(abs(y1 - y0)))

    def _on_press(self, _w, event) -> bool:
        self._start = (event.x, event.y)
        self._current = (event.x, event.y)
        self.queue_draw()
        return True

    def _on_motion(self, _w, event) -> bool:
        if self._start is not None:
            self._current = (event.x, event.y)
            self.queue_draw()
        return True

    def _on_release(self, _w, event) -> bool:
        self._current = (event.x, event.y)
        rect = self._rect()
        if rect and rect[2] >= _MIN_SIZE and rect[3] >= _MIN_SIZE:
            self.region = self._to_screen(rect)
        self._finish()
        return True

    def _on_key(self, _w, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.region = None
            self.cancelled = True
            self._finish()
        return True

    def _to_screen(self, rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """Offset a window-relative rect by the monitor's position.

        Events are relative to this window; the recorder needs coordinates
        relative to the whole desktop, which differ on a multi-monitor setup
        where a monitor does not start at 0,0.
        """
        x, y, w, h = rect
        try:
            monitor = self.get_display().get_monitor_at_window(self.get_window())
            geo = monitor.get_geometry()
            return x + geo.x, y + geo.y, w, h
        except Exception:  # pragma: no cover - best effort
            LOG.debug("could not offset region by monitor origin", exc_info=True)
            return rect

    def _finish(self) -> None:
        self.hide()
        Gtk.main_quit()


def _overlay_select_area() -> tuple[int, int, int, int] | None:
    """Our own picker, for desktops without a native one."""
    try:
        overlay = _RegionOverlay()
        overlay.show_all()
        overlay.present()
        Gtk.main()          # nested: callable from inside another window
        region = overlay.region
        overlay.destroy()
        return region
    except Exception as exc:  # pragma: no cover - no display
        LOG.warning("Region selection failed: %s", exc)
        return None


def select_region() -> str | None:
    """Pick a screen region and return it as "x,y,w,h" (None if cancelled)."""
    region = _gnome_select_area()
    if region is None:
        region = _overlay_select_area()
    if region is None:
        return None
    x, y, w, h = region
    return f"{x},{y},{w},{h}"
