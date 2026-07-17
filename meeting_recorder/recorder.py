"""Screen + audio recording via ffmpeg.

Two-stage design:

1. **Live capture** (`build_ffmpeg_cmd`) writes a segment with the video plus the
   mic and system audio as two *separate, unprocessed* tracks. No audio filters
   run live, so there is no filter latency — segments can be any length and
   nothing is lost when one ends.
2. **Finalize** (`build_finalize_cmd`) concatenates the segments and does all the
   audio work in one pass: denoise, per-source loudness normalization (so both
   voices end up equal), mixing and limiting. The video is stream-copied, so this
   is fast even for a long meeting.

That split is what makes Pause exact: pausing ends a segment and resuming starts
a new one, so paused time never reaches the file. (Normalizing live is not an
option — loudnorm buffers ~3s, which both truncates recordings and makes a clean
pause boundary impossible.)

The command builders are pure functions and are unit-tested; `Recorder` owns the
subprocess lifecycle.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import audio
from .config import Config
from .utils import LOG, expand_path

_LIMITER = "alimiter=limit=0.95"
_LOUDNORM = "loudnorm=I=-23:TP=-2"


def screen_resolution(default: str = "1920x1080") -> str:
    """Current X11 resolution via xrandr, e.g. '1920x1080'. Falls back on failure."""
    try:
        out = subprocess.run(["xrandr", "--current"], capture_output=True,
                             text=True, timeout=5, check=True)
        for line in out.stdout.splitlines():
            if "*" in line:  # the active mode is starred
                return line.split()[0]
    except (subprocess.SubprocessError, FileNotFoundError, IndexError) as exc:
        LOG.debug("xrandr failed, using default resolution: %s", exc)
    return default


def _even(n: int) -> int:
    """x264/yuv420p needs even dimensions."""
    return n - (n % 2)


def active_window_geometry() -> tuple[int, int, int, int] | None:
    """(x, y, w, h) of the currently focused window via xprop + xwininfo."""
    try:
        wid_out = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                                 capture_output=True, text=True, timeout=3, check=True)
        wid = wid_out.stdout.split()[-1]
        if wid in ("0x0", "0x00000000"):
            return None
        info = subprocess.run(["xwininfo", "-id", wid], capture_output=True,
                              text=True, timeout=3, check=True).stdout
        x = int(re.search(r"Absolute upper-left X:\s*(-?\d+)", info).group(1))
        y = int(re.search(r"Absolute upper-left Y:\s*(-?\d+)", info).group(1))
        w = int(re.search(r"Width:\s*(\d+)", info).group(1))
        h = int(re.search(r"Height:\s*(\d+)", info).group(1))
        return x, y, w, h
    except (subprocess.SubprocessError, FileNotFoundError, AttributeError,
            ValueError, IndexError) as exc:
        LOG.warning("Could not read active window geometry: %s", exc)
        return None


def parse_region(text: str) -> tuple[int, int, int, int] | None:
    """Parse a 'x,y,w,h' region string into ints, or None if invalid."""
    try:
        x, y, w, h = (int(p) for p in text.split(","))
        if w > 0 and h > 0:
            return x, y, w, h
    except (ValueError, AttributeError):
        pass
    return None


def video_geometry(cfg: Config) -> tuple[int, int, str]:
    """Resolve (x_offset, y_offset, 'WxH') for the chosen capture_mode.

    Falls back to full screen if a window/area can't be determined.
    """
    if cfg.capture_mode == "window":
        geo = active_window_geometry()
        if geo:
            x, y, w, h = geo
            return x, y, f"{_even(w)}x{_even(h)}"
        LOG.warning("Window capture unavailable; using full screen")
    elif cfg.capture_mode == "area":
        geo = parse_region(cfg.capture_region)
        if geo:
            x, y, w, h = geo
            return x, y, f"{_even(w)}x{_even(h)}"
        LOG.warning("No valid capture_region; using full screen")
    return 0, 0, screen_resolution()


@dataclass
class CaptureDevices:
    display: str          # e.g. ":0"
    video_size: str       # "WxH" of the capture rectangle
    video_x: int          # left offset on the X display
    video_y: int          # top offset on the X display
    mic_source: str
    monitor_source: str


def resolve_devices(cfg: Config) -> CaptureDevices:
    import os
    x, y, size = video_geometry(cfg)
    return CaptureDevices(
        display=os.environ.get("DISPLAY", ":0"),
        video_size=size,
        video_x=x,
        video_y=y,
        mic_source=audio.default_source(),
        monitor_source=audio.monitor_source(),
    )


def audio_roles(cfg: Config) -> list[str]:
    """Audio track roles, in the order they are recorded into each segment."""
    roles = []
    if cfg.record_mic:
        roles.append("mic")
    if cfg.record_system_audio:
        roles.append("system")
    return roles


# ---------------------------------------------------------------------------
# Stage 1: live capture (no audio filters -> no latency)
# ---------------------------------------------------------------------------


def build_ffmpeg_cmd(cfg: Config, output_path: Path, dev: CaptureDevices) -> list[str]:
    """Live capture: video + each audio source as its own untouched track."""
    cmd: list[str] = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y"]

    # Large input queues so a busy encoder never starves screen capture (this is
    # what prevents a frozen black screen at the start of a recording).
    tqs = ["-thread_queue_size", "1024"]
    next_index = 0

    if cfg.record_screen:
        cmd += tqs + ["-f", "x11grab", "-framerate", str(cfg.framerate),
                      "-video_size", dev.video_size,
                      "-i", f"{dev.display}+{dev.video_x},{dev.video_y}"]
        next_index += 1  # video occupies input 0

    audio_indices: list[int] = []
    if cfg.record_mic:
        cmd += tqs + ["-f", "pulse", "-i", dev.mic_source]
        audio_indices.append(next_index)
        next_index += 1
    if cfg.record_system_audio:
        cmd += tqs + ["-f", "pulse", "-i", dev.monitor_source]
        audio_indices.append(next_index)
        next_index += 1

    # 'zerolatency' disables x264 lookahead/B-frames so frames are emitted
    # immediately (no startup stall); -g sets a ~2s keyframe interval.
    if cfg.record_screen:
        cmd += ["-map", "0:v", "-c:v", cfg.video_codec,
                "-preset", cfg.video_preset, "-pix_fmt", "yuv420p",
                "-g", str(cfg.framerate * 2)]
        if "264" in cfg.video_codec or "265" in cfg.video_codec:
            cmd += ["-tune", "zerolatency"]

    for idx in audio_indices:
        cmd += ["-map", f"{idx}:a"]
    if audio_indices:
        cmd += ["-c:a", "aac", "-b:a", "160k"]

    cmd.append(str(output_path))
    return cmd


# ---------------------------------------------------------------------------
# Stage 2: finalize (all the audio processing, video stream-copied)
# ---------------------------------------------------------------------------


def _mic_chain(cfg: Config) -> list[str]:
    chain = ["highpass=f=90"]
    if cfg.noise_cancellation:
        model = expand_path(cfg.noise_model_path) if cfg.noise_model_path else None
        if model and model.is_file():
            chain.append(f"arnndn=m={model}")
        else:
            chain.append("afftdn=nr=20:nf=-30:tn=1")
    if cfg.normalize_voice:
        chain.append(_LOUDNORM)
    chain.append(f"volume={cfg.mic_volume}")
    return chain


def _system_chain(cfg: Config) -> list[str]:
    chain: list[str] = []
    if cfg.normalize_voice:
        chain.append(_LOUDNORM)
    chain.append(f"volume={cfg.system_volume}")
    return chain


def _chain_for(cfg: Config, role: str) -> list[str]:
    return _mic_chain(cfg) if role == "mic" else _system_chain(cfg)


def build_finalize_cmd(cfg: Config, listfile: Path, dest: Path,
                       roles: list[str], duration: float | None = None) -> list[str]:
    """Concat segments, process audio, copy video. Both sources are normalized to
    the same loudness target so the two voices come out equal.

    `duration` caps the output length — used to trim the tail that was recorded
    while the detector waited out its stop debounce.
    """
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
           "-f", "concat", "-safe", "0", "-i", str(listfile)]
    if duration is not None and duration > 0:
        cmd += ["-t", f"{duration:.3f}"]

    if roles:
        if len(roles) == 1:
            chain = _chain_for(cfg, roles[0]) + [_LIMITER]
            graph = "[0:a:0]" + ",".join(chain) + "[aout]"
        else:
            stages = ["[0:a:%d]" % n + ",".join(_chain_for(cfg, r)) + f"[a{n}]"
                      for n, r in enumerate(roles)]
            labels = "".join(f"[a{n}]" for n in range(len(roles)))
            mix = f"amix=inputs={len(roles)}:normalize=0:dropout_transition=0"
            graph = ";".join(stages) + ";" + labels + f"{mix},{_LIMITER}[aout]"
        cmd += ["-filter_complex", graph, "-map", "[aout]",
                "-c:a", "aac", "-b:a", "160k"]

    if cfg.record_screen:
        cmd += ["-map", "0:v", "-c:v", "copy"]

    cmd.append(str(dest))
    return cmd


class Recorder:
    """Records as one or more segments; pause ends a segment, resume starts one.

    On stop the segments are concatenated and the audio is processed in a single
    finalize pass (video stream-copied), so paused time never reaches the file.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._proc: subprocess.Popen | None = None
        self._final_path: Path | None = None
        self._parts: list[Path] = []
        self._accum: float = 0.0        # active seconds from finished segments
        self._run_start: float = 0.0    # monotonic start of the live segment
        self._paused: bool = False
        # Finalize runs in the background (loudnorm is ~45x realtime, so an hour
        # of meeting takes minutes) — the daemon must stay responsive.
        self._fin_proc: subprocess.Popen | None = None
        self._fin_target: Path | None = None
        self._fin_parts: list[Path] = []
        self._fin_list: Path | None = None

    @property
    def is_recording(self) -> bool:
        """True for the whole session, including while paused."""
        return self._final_path is not None

    @property
    def is_paused(self) -> bool:
        return self._paused

    def start(self, output_path: Path) -> None:
        if self.is_recording:
            LOG.warning("start() ignored: already recording")
            return
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._final_path = output_path
        self._parts = []
        self._accum = 0.0
        self._paused = False
        LOG.info("Recording -> %s", output_path)
        self._start_segment()

    def pause(self) -> None:
        if not self.is_recording or self._paused:
            return
        self._accum += time.monotonic() - self._run_start
        self._stop_proc()
        self._paused = True
        LOG.info("Recording paused (%.0fs recorded)", self._accum)

    def resume(self) -> None:
        if not self.is_recording or not self._paused:
            return
        self._paused = False
        self._start_segment()
        LOG.info("Recording resumed")

    def stop(self, discard: bool = False, trim_end: float = 0.0) -> bool:
        """Stop capture and kick off the finalize pass in the background.

        `trim_end` drops that many seconds from the end of the saved file — the
        detector uses it to remove the tail recorded during its stop debounce.
        Returns True if a finalize was started — poll it with poll_finalize().
        """
        if not self.is_recording:
            return False
        if not self._paused:
            self._accum += time.monotonic() - self._run_start
        self._stop_proc()
        final, parts = self._final_path, self._parts
        self._final_path, self._parts, self._paused = None, [], False

        parts = [p for p in parts if p.exists() and p.stat().st_size > 0]
        if discard or not parts or final is None:
            if not parts:
                LOG.warning("Recording stopped but no output was produced")
            for p in parts:
                p.unlink(missing_ok=True)
            return False
        duration = None
        if trim_end > 0:
            duration = max(0.5, self._accum - trim_end)
            LOG.info("Trimming %.1fs of post-call tail (keeping %.1fs)",
                     trim_end, duration)
        try:
            self._start_finalize(parts, final, duration)
        except OSError as exc:
            LOG.error("Could not start finalize: %s", exc)
            for p in parts:
                p.unlink(missing_ok=True)
            return False
        return True

    @property
    def is_finalizing(self) -> bool:
        return self._fin_proc is not None

    def poll_finalize(self) -> tuple[bool, Path | None]:
        """Return (done, saved_path). While running: (False, None)."""
        if self._fin_proc is None:
            return True, None
        if self._fin_proc.poll() is None:
            return False, None
        rc = self._fin_proc.returncode
        self._fin_proc = None
        for p in self._fin_parts:
            p.unlink(missing_ok=True)
        if self._fin_list:
            self._fin_list.unlink(missing_ok=True)
        final = self._fin_target
        self._fin_target, self._fin_parts, self._fin_list = None, [], None
        if rc == 0 and final and final.exists() and final.stat().st_size > 0:
            LOG.info("Saved recording: %s (%.1f MB)", final,
                     final.stat().st_size / 1e6)
            return True, final
        LOG.error("Finalize failed (exit %s)", rc)
        return True, None

    def wait_finalize(self, timeout: float = 900) -> Path | None:
        """Block until finalize completes — used on daemon shutdown."""
        if self._fin_proc is None:
            return None
        try:
            self._fin_proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            LOG.error("Finalize timed out; killing")
            self._fin_proc.kill()
        return self.poll_finalize()[1]

    def elapsed(self) -> float:
        """Total active recorded seconds, excluding paused time."""
        if not self.is_recording or self._paused:
            return self._accum
        return self._accum + (time.monotonic() - self._run_start)

    # -- internals ---------------------------------------------------------
    def _start_segment(self) -> None:
        assert self._final_path is not None
        part = self._final_path.with_name(
            f".{self._final_path.stem}.part{len(self._parts)}{self._final_path.suffix}")
        dev = resolve_devices(self.cfg)
        cmd = build_ffmpeg_cmd(self.cfg, part, dev)
        LOG.debug("capture cmd: %s", " ".join(cmd))
        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._parts.append(part)
        self._run_start = time.monotonic()

    def _stop_proc(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None or proc.poll() is not None:
            return
        try:
            if proc.stdin:
                proc.stdin.write(b"q")
                proc.stdin.flush()
                proc.stdin.close()
            proc.wait(timeout=8)
        except (subprocess.TimeoutExpired, BrokenPipeError, OSError):
            LOG.warning("ffmpeg did not quit cleanly; terminating")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _start_finalize(self, parts: list[Path], dest: Path,
                        duration: float | None = None) -> None:
        listfile = dest.with_name(f".{dest.stem}.concat.txt")
        listfile.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts),
                            encoding="utf-8")
        cmd = build_finalize_cmd(self.cfg, listfile, dest, audio_roles(self.cfg),
                                 duration)
        LOG.info("Finalizing %d segment(s) -> %s", len(parts), dest.name)
        LOG.debug("finalize cmd: %s", " ".join(cmd))
        self._fin_proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._fin_target = dest
        self._fin_parts = parts
        self._fin_list = listfile
