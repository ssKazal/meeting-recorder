"""Unit tests for the two-stage capture/finalize ffmpeg command construction."""

from pathlib import Path

from meeting_recorder.config import load_config
from meeting_recorder.recorder import (
    CaptureDevices,
    audio_roles,
    build_ffmpeg_cmd,
    build_finalize_cmd,
    parse_region,
    video_geometry,
)

DEV = CaptureDevices(
    display=":0",
    video_size="1920x1080",
    video_x=0,
    video_y=0,
    mic_source="mic_src",
    monitor_source="sink.monitor",
)
OUT = Path("/tmp/out.mkv")
LIST = Path("/tmp/list.txt")


def _cfg(**over):
    cfg = load_config()
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


# -- stage 1: live capture ------------------------------------------------

def test_capture_records_raw_separate_audio_tracks():
    """Live capture must have NO audio filters (latency would break pause)."""
    cmd = build_ffmpeg_cmd(
        _cfg(record_screen=True, record_mic=True, record_system_audio=True), OUT, DEV)
    joined = " ".join(cmd)
    assert "x11grab" in cmd
    assert cmd.count("-f") == 3            # x11grab + 2 pulse inputs
    assert "mic_src" in cmd and "sink.monitor" in cmd
    # Two separate audio tracks, unprocessed.
    assert "-map 1:a -map 2:a" in joined
    for f in ("loudnorm", "amix", "afftdn", "highpass", "filter_complex"):
        assert f not in joined, f"{f} must not run during live capture"
    assert cmd[-1] == str(OUT)


def test_capture_startup_stall_flags():
    cmd = build_ffmpeg_cmd(_cfg(record_screen=True), OUT, DEV)
    joined = " ".join(cmd)
    assert "-thread_queue_size 1024" in joined
    assert "-tune zerolatency" in joined


def test_capture_fullscreen_offset_and_area_offset():
    assert "-i :0+0,0" in " ".join(build_ffmpeg_cmd(_cfg(record_screen=True), OUT, DEV))
    dev = CaptureDevices(display=":0", video_size="800x600", video_x=100,
                         video_y=50, mic_source="m", monitor_source="s")
    joined = " ".join(build_ffmpeg_cmd(_cfg(record_screen=True), OUT, dev))
    assert "-video_size 800x600" in joined and "-i :0+100,50" in joined


def test_capture_screen_only_has_no_audio():
    cmd = build_ffmpeg_cmd(
        _cfg(record_screen=True, record_mic=False, record_system_audio=False), OUT, DEV)
    assert "-c:a" not in cmd and "-c:v" in cmd


def test_capture_audio_only_has_no_video():
    cmd = build_ffmpeg_cmd(
        _cfg(record_screen=False, record_mic=True, record_system_audio=False), OUT, DEV)
    joined = " ".join(cmd)
    assert "x11grab" not in cmd
    assert "-map 0:a" in joined            # mic becomes input 0


def test_audio_roles_order():
    assert audio_roles(_cfg(record_mic=True, record_system_audio=True)) == ["mic", "system"]
    assert audio_roles(_cfg(record_mic=False, record_system_audio=True)) == ["system"]
    assert audio_roles(_cfg(record_mic=True, record_system_audio=False)) == ["mic"]
    assert audio_roles(_cfg(record_mic=False, record_system_audio=False)) == []


# -- stage 2: finalize ----------------------------------------------------

def test_finalize_normalizes_both_sources_and_copies_video():
    cmd = build_finalize_cmd(
        _cfg(record_screen=True, mic_volume=1.0, system_volume=1.0,
             normalize_voice=True, noise_cancellation=True),
        LIST, OUT, ["mic", "system"])
    joined = " ".join(cmd)
    assert "-f concat -safe 0 -i /tmp/list.txt" in joined
    # Mic: highpass -> denoise -> loudnorm -> volume
    assert ("[0:a:0]highpass=f=90,afftdn=nr=20:nf=-30:tn=1,"
            "loudnorm=I=-23:TP=-2,volume=1.0[a0]") in joined
    # System: loudnorm -> volume (same target => equal voices)
    assert "[0:a:1]loudnorm=I=-23:TP=-2,volume=1.0[a1]" in joined
    assert "amix=inputs=2:normalize=0:dropout_transition=0,alimiter=limit=0.95[aout]" in joined
    # Video is copied, never re-encoded (keeps finalize fast).
    assert "-map 0:v -c:v copy" in joined
    assert cmd[-1] == str(OUT)


def test_finalize_single_mic_track_gets_limiter():
    cmd = build_finalize_cmd(_cfg(record_screen=True, mic_volume=1.0,
                                  normalize_voice=True), LIST, OUT, ["mic"])
    joined = " ".join(cmd)
    assert "amix" not in joined
    assert "alimiter=limit=0.95[aout]" in joined
    assert "-map [aout]" in joined


def test_finalize_normalization_can_be_disabled():
    cmd = build_finalize_cmd(_cfg(record_screen=True, mic_volume=2.0,
                                  system_volume=0.5, normalize_voice=False),
                             LIST, OUT, ["mic", "system"])
    joined = " ".join(cmd)
    assert "loudnorm" not in joined
    assert "volume=2.0[a0]" in joined and "volume=0.5[a1]" in joined


def test_finalize_noise_cancellation_toggle():
    on = " ".join(build_finalize_cmd(_cfg(noise_cancellation=True), LIST, OUT, ["mic"]))
    off = " ".join(build_finalize_cmd(_cfg(noise_cancellation=False), LIST, OUT, ["mic"]))
    assert "afftdn=nr=20:nf=-30:tn=1" in on
    assert "afftdn" not in off


def test_finalize_without_audio_just_copies_video():
    cmd = build_finalize_cmd(_cfg(record_screen=True), LIST, OUT, [])
    joined = " ".join(cmd)
    assert "-filter_complex" not in joined
    assert "-map 0:v -c:v copy" in joined


# -- geometry helpers -----------------------------------------------------

def test_parse_region():
    assert parse_region("100,50,800,600") == (100, 50, 800, 600)
    assert parse_region("") is None
    assert parse_region("1,2,3") is None
    assert parse_region("0,0,0,600") is None      # zero width rejected


def test_video_geometry_fullscreen_and_bad_area_fallback():
    x, y, size = video_geometry(_cfg(capture_mode="fullscreen"))
    assert (x, y) == (0, 0) and "x" in size
    x, y, size = video_geometry(_cfg(capture_mode="area", capture_region=""))
    assert (x, y) == (0, 0)
    x, y, size = video_geometry(_cfg(capture_mode="area", capture_region="10,20,801,601"))
    assert (x, y) == (10, 20) and size == "800x600"


# -- pause/resume segmenting ----------------------------------------------

def test_pause_resume_creates_segments_and_tracks_elapsed():
    """Pause ends a segment, resume starts a new one (no real ffmpeg)."""
    import meeting_recorder.recorder as rec

    class FakeProc:
        def __init__(self, *a, **k):
            self.stdin = None
            self._alive = True

        def poll(self):
            return None if self._alive else 0

        def wait(self, timeout=None):
            self._alive = False
            return 0

    orig = (rec.subprocess.Popen, rec.resolve_devices, rec.build_ffmpeg_cmd)
    rec.subprocess.Popen = FakeProc
    rec.resolve_devices = lambda cfg: None
    rec.build_ffmpeg_cmd = lambda cfg, out, dev: ["true"]
    try:
        r = rec.Recorder(load_config())
        r.start(Path("/tmp/seg.mkv"))
        assert r.is_recording and not r.is_paused
        assert len(r._parts) == 1
        r.pause()
        assert r.is_paused and len(r._parts) == 1      # no new segment while paused
        r.resume()
        assert not r.is_paused and len(r._parts) == 2  # resume opened segment 1
        # Segment files are hidden siblings of the final path.
        assert r._parts[0].name == ".seg.part0.mkv"
        assert r._parts[1].name == ".seg.part1.mkv"
    finally:
        (rec.subprocess.Popen, rec.resolve_devices, rec.build_ffmpeg_cmd) = orig


def test_finalize_trims_tail_when_duration_given():
    cmd = build_finalize_cmd(_cfg(record_screen=True), LIST, OUT, ["mic"],
                             duration=12.5)
    assert "-t 12.500" in " ".join(cmd)


def test_finalize_no_trim_by_default():
    assert "-t " not in " ".join(build_finalize_cmd(_cfg(), LIST, OUT, ["mic"]))
