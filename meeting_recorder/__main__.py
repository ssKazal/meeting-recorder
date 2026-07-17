"""CLI entry point.

  python -m meeting_recorder run       # start the detection daemon (default)
  python -m meeting_recorder record    # manual one-off recording (Ctrl-C to stop)
  python -m meeting_recorder status    # print detected capture streams once
  python -m meeting_recorder settings  # open the GTK settings window
  python -m meeting_recorder config    # write a user config file to edit
"""

from __future__ import annotations

import argparse
import signal
import sys

from . import __version__
from .config import load_config, write_default_user_config
from .utils import LOG, build_output_path, setup_logging


def _cmd_run(cfg) -> int:
    import gi
    gi.require_version("GLib", "2.0")
    from gi.repository import GLib

    from .controller import Controller
    from .detector import MeetingDetector
    from .notifier import Notifier
    from .recorder import Recorder

    notifier = Notifier()
    recorder = Recorder(cfg)
    controller = Controller(cfg, notifier, recorder)
    detector = MeetingDetector(
        allowlist=cfg.allowlist,
        start_debounce=cfg.start_debounce_seconds,
        stop_debounce=cfg.stop_debounce_seconds,
        on_start=controller.on_meeting_start,
        on_stop=controller.on_meeting_stop,
    )

    loop = GLib.MainLoop()
    interval_ms = max(250, int(cfg.poll_interval_seconds * 1000))
    GLib.timeout_add(interval_ms, detector.tick)

    def _shutdown(*_a):
        LOG.info("Shutting down")
        controller.shutdown()
        loop.quit()
        return False

    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, _shutdown)
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, _shutdown)

    LOG.info("Smart Meeting Recorder %s running (polling every %.1fs). "
             "Watching for: %s", __version__, cfg.poll_interval_seconds,
             ", ".join(sorted({e.app for e in cfg.allowlist})))
    notifier.info("Meeting Recorder active",
                  "Watching for meetings in the background.")
    loop.run()
    return 0


def _cmd_record(cfg) -> int:
    """Record immediately until Ctrl-C — useful for testing capture end-to-end."""
    from .recorder import Recorder

    recorder = Recorder(cfg)
    path = build_output_path(cfg.output_dir, "Manual", cfg.container)
    recorder.start(path)
    print(f"Recording to {path} — press Ctrl-C to stop.")
    try:
        signal.pause()
    except KeyboardInterrupt:
        pass
    saved = recorder.stop()
    print(f"Saved: {saved}" if saved else "No file saved.")
    return 0


def _cmd_status(cfg) -> int:
    from .detector import match_meeting_app, query_source_outputs

    outputs = query_source_outputs()
    if not outputs:
        print("No active capture streams (or pactl unavailable).")
    for o in outputs:
        tag = " [monitor]" if o.is_monitor else ""
        print(f"  #{o.index} app={o.app_name!r} binary={o.binary!r} "
              f"source={o.source!r}{tag}")
    app = match_meeting_app(outputs, cfg.allowlist)
    print(f"\nMeeting match: {app or '(none)'}")
    return 0


def _cmd_config(_cfg) -> int:
    path = write_default_user_config()
    print(f"User config: {path}")
    return 0


def _cmd_settings(_cfg) -> int:
    """Open the GTK settings window."""
    from .settings_gui import run
    return run()


def main(argv: list[str] | None = None) -> int:
    # -v/--verbose accepted before OR after the subcommand via a shared parent.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true")

    parser = argparse.ArgumentParser(prog="meeting-recorder",
                                     description="Smart Meeting Recorder for Linux",
                                     parents=[common])
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    for name in ("run", "record", "status", "config", "settings"):
        sub.add_parser(name, parents=[common])

    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    cfg = load_config()

    command = args.command or "run"
    handler = {
        "run": _cmd_run,
        "record": _cmd_record,
        "status": _cmd_status,
        "config": _cmd_config,
        "settings": _cmd_settings,
    }[command]
    return handler(cfg)


if __name__ == "__main__":
    sys.exit(main())
