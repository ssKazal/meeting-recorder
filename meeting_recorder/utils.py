"""Small shared helpers: paths, filenames, logging."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger("meeting_recorder")


def setup_logging(verbose: bool = False) -> None:
    """Configure root logging for the daemon."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def expand_path(path: str) -> Path:
    """Expand ~ and environment variables in a path string."""
    return Path(os.path.expandvars(os.path.expanduser(path)))


def sanitize_app_name(name: str) -> str:
    """Turn an app label into a filesystem-safe token (e.g. 'Google Chrome' -> 'Google_Chrome')."""
    token = re.sub(r"[^\w.-]+", "_", name.strip())
    token = token.strip("_.")
    return token or "Meeting"


def _show_in_file_manager(target: Path) -> bool:
    """Ask the file manager to reveal `target` over D-Bus. True if it accepted.

    Preferred over spawning `nautilus --select`, which does nothing visible
    when a window for that folder is already open: it neither re-selects the
    file nor raises the window, and on Wayland a client cannot raise itself at
    all without an activation token. FileManager1 is the freedesktop interface
    for exactly this, and the file manager does the focusing itself.
    """
    try:
        import gi
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync(
            "org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
            "org.freedesktop.FileManager1", "ShowItems",
            GLib.Variant("(ass)", ([target.absolute().as_uri()], "")),
            None, Gio.DBusCallFlags.NONE, 5000, None)
        return True
    except Exception as exc:  # no gi, no session bus, no file manager
        LOG.debug("FileManager1 unavailable (%s); falling back", exc)
        return False


def open_folder(path: Path) -> None:
    """Reveal `path` in the file manager, raising an already-open window.

    Selects the file itself where possible, otherwise opens the containing
    directory.
    """
    p = Path(path)
    folder = p.parent if p.suffix else p
    if p.exists() and _show_in_file_manager(p):
        return
    # Fallbacks: a file manager without FileManager1, or no D-Bus at all.
    if p.is_file() and shutil.which("nautilus"):
        cmd = ["nautilus", "--select", str(p)]
    else:
        cmd = ["xdg-open", str(folder)]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        LOG.warning("Could not open %s: %s", folder, exc)


def build_output_path(output_dir: Path, app_name: str, container: str,
                      now: datetime | None = None) -> Path:
    """Return '<output_dir>/<App>_<YYYY-MM-DD_HH-MM-SS>.<container>'."""
    now = now or datetime.now()
    stamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    ext = container.lstrip(".")
    return output_dir / f"{sanitize_app_name(app_name)}_{stamp}.{ext}"
