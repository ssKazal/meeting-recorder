"""Drag-to-select a screen region with the mouse.

Replaces the `slop` helper, which is X11-only: on Wayland the drag-select
button was permanently disabled and the region had to be typed as x,y,w,h.
This draws its own full-screen overlay with GTK, so the same code works on
both session types and adds no packaging dependency.

Usage:

    region = select_region()      # "x,y,w,h", or None if cancelled
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from .utils import LOG  # noqa: E402

_MIN_SIZE = 8  # px; below this a drag is almost certainly a stray click


class _RegionOverlay(Gtk.Window):
    """A dim full-screen window that reports the rectangle you drag on it."""

    def __init__(self) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.region: tuple[int, int, int, int] | None = None
        self._start: tuple[float, float] | None = None
        self._current: tuple[float, float] | None = None

        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        # Transparency needs an RGBA visual; without a compositor the overlay
        # still works, it just paints opaque grey instead of dimming.
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
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

    # -- drawing -----------------------------------------------------------
    def _on_draw(self, _widget, cr) -> bool:
        width, height = self.get_size()
        cr.set_source_rgba(0, 0, 0, 0.45)
        cr.paint()

        rect = self._rect()
        if rect is None:
            self._draw_hint(cr, width, height)
            return False

        x, y, w, h = rect
        # Punch the selection out of the dim layer so it shows true colours.
        cr.set_operator(1)  # CLEAR
        cr.rectangle(x, y, w, h)
        cr.fill()
        cr.set_operator(2)  # OVER

        cr.set_source_rgba(0.90, 0.30, 0.24, 1.0)
        cr.set_line_width(2)
        cr.rectangle(x + 1, y + 1, max(0, w - 2), max(0, h - 2))
        cr.stroke()

        label = f"{int(w)} × {int(h)}"
        cr.select_font_face("Sans")
        cr.set_font_size(14)
        ext = cr.text_extents(label)
        # Keep the readout inside the screen when selecting near an edge.
        tx = min(max(x, 4), width - ext.width - 12)
        ty = y - 8 if y > 24 else y + h + 20
        cr.set_source_rgba(0, 0, 0, 0.75)
        cr.rectangle(tx - 4, ty - ext.height - 4, ext.width + 10, ext.height + 10)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 1)
        cr.move_to(tx, ty)
        cr.show_text(label)
        return False

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
            self._finish()
        return True

    def _to_screen(self, rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """Offset a window-relative rect by the monitor's position.

        Events are relative to this window; the capture geometry the recorder
        needs is relative to the whole desktop, which differs on a multi-monitor
        setup where a monitor does not start at 0,0.
        """
        x, y, w, h = rect
        try:
            gdk_window = self.get_window()
            monitor = self.get_display().get_monitor_at_window(gdk_window)
            geo = monitor.get_geometry()
            return x + geo.x, y + geo.y, w, h
        except Exception:  # pragma: no cover - best effort
            LOG.debug("could not offset region by monitor origin", exc_info=True)
            return rect

    def _finish(self) -> None:
        self.hide()
        Gtk.main_quit()


def select_region() -> str | None:
    """Show the overlay and return the dragged region as "x,y,w,h".

    Returns None if the user pressed Escape or barely moved the mouse. Runs a
    nested GTK loop, so it can be called from a handler inside another window.
    """
    try:
        overlay = _RegionOverlay()
        overlay.show_all()
        # Grab focus so Escape reaches us rather than the window underneath.
        overlay.present()
        Gtk.main()
        overlay.destroy()
    except Exception as exc:  # pragma: no cover - no display
        LOG.warning("Region selection failed: %s", exc)
        return None
    if overlay.region is None:
        return None
    x, y, w, h = overlay.region
    return f"{x},{y},{w},{h}"
