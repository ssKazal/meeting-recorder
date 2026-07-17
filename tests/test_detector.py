"""Unit tests for parsing, allowlist matching, and debounce logic."""

from pathlib import Path

from meeting_recorder.config import AllowEntry
from meeting_recorder.detector import (
    DebounceMachine,
    match_meeting_app,
    parse_source_outputs,
)

FIXTURES = Path(__file__).parent / "fixtures"

ALLOW = [
    AllowEntry(match="zoom", app="Zoom"),
    AllowEntry(match="firefox", app="Firefox"),
    AllowEntry(match="chrome", app="Chrome"),
]


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_extracts_streams_and_props():
    outs = parse_source_outputs(_read("source_outputs_firefox.txt"))
    assert len(outs) == 2
    ff = outs[0]
    assert ff.index == 42
    assert ff.app_name == "Firefox"
    assert ff.binary == "firefox"
    assert not ff.is_monitor
    # Second stream records from a .monitor source.
    assert outs[1].is_monitor


def test_match_hits_allowlisted_mic_stream():
    outs = parse_source_outputs(_read("source_outputs_firefox.txt"))
    assert match_meeting_app(outs, ALLOW) == "Firefox"


def test_monitor_only_music_does_not_match():
    # Spotify capturing the sink monitor is NOT a meeting (mic isn't used).
    outs = parse_source_outputs(_read("source_outputs_music.txt"))
    assert match_meeting_app(outs, ALLOW) is None


def test_empty_input_matches_nothing():
    assert match_meeting_app(parse_source_outputs(""), ALLOW) is None


def test_debounce_start_requires_sustained_presence():
    m = DebounceMachine(start_debounce=3.0, stop_debounce=5.0)
    assert m.update("Zoom", 0.0) is None          # candidate begins
    assert m.update("Zoom", 2.9) is None          # not long enough
    assert m.update("Zoom", 3.0) == ("start", "Zoom")
    assert m.in_meeting is True


def test_debounce_brief_blip_does_not_start():
    m = DebounceMachine(start_debounce=3.0, stop_debounce=5.0)
    m.update("Zoom", 0.0)
    assert m.update(None, 1.0) is None            # gone before debounce
    assert m.in_meeting is False


def test_debounce_stop_requires_sustained_absence():
    m = DebounceMachine(start_debounce=1.0, stop_debounce=5.0)
    m.update("Zoom", 0.0)
    m.update("Zoom", 1.0)                          # -> start
    assert m.in_meeting is True
    assert m.update(None, 3.0) is None            # brief mute
    assert m.update("Zoom", 4.0) is None          # came back, timer reset
    assert m.update(None, 5.0) is None
    assert m.update(None, 10.0) == ("stop", None)
    assert m.in_meeting is False


def test_debounce_app_change_resets_candidate():
    m = DebounceMachine(start_debounce=3.0, stop_debounce=5.0)
    m.update("Zoom", 0.0)
    m.update("Firefox", 2.0)                       # different app resets timer
    assert m.update("Firefox", 4.0) is None       # only 2s for Firefox
    assert m.update("Firefox", 5.0) == ("start", "Firefox")


def test_debounce_reports_stop_overshoot():
    """The machine records how long it over-recorded past the real call end."""
    m = DebounceMachine(start_debounce=1.0, stop_debounce=2.0)
    m.update("Zoom", 0.0)
    m.update("Zoom", 1.0)                      # -> start
    assert m.update(None, 10.0) is None        # audio actually stopped at t=10
    assert m.update(None, 12.0) == ("stop", None)
    # We kept recording from 10.0 -> 12.0, so 2s must be trimmed.
    assert m.stop_overshoot == 2.0
