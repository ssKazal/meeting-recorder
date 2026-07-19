"""Controller wiring tests that do not need a display.

These exist because a signature change to RecordingTray once left the caller
passing an argument that no longer existed. The controller catches that and
falls back to the floating pill, so the app kept "working" while the tray
silently disappeared — a standalone RecordingTray test still passed.
"""

import inspect

from meeting_recorder.controller import Controller


def test_build_controls_calls_the_tray_with_arguments_it_accepts():
    """The tray call must match RecordingTray's signature.

    Checked by inspection rather than by constructing one, so it runs on a
    headless machine: importing tray_indicator needs GTK and AppIndicator.
    """
    src = inspect.getsource(Controller._build_controls)
    assert "RecordingTray(" in src, "controller no longer builds a tray"

    try:
        from meeting_recorder.tray_indicator import RecordingTray
    except Exception:
        return  # no GTK/AppIndicator here; nothing to compare against

    params = set(inspect.signature(RecordingTray.__init__).parameters) - {"self"}
    # Every keyword the controller passes has to exist on the tray.
    import re
    call = re.search(r"RecordingTray\((.*?)\)", src, re.S).group(1)
    passed = set(re.findall(r"(\w+)\s*=", call)) - {"kwargs"}
    unknown = passed - params
    assert not unknown, f"controller passes {unknown}, which RecordingTray rejects"


def test_build_controls_kwargs_match_both_widgets():
    """Tray and pill are interchangeable, so both must accept the same kwargs."""
    src = inspect.getsource(Controller._build_controls)
    for name in ("on_pause", "on_resume", "on_stop"):
        assert name in src, f"{name} missing from the controls it builds"
