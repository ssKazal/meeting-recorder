# CLAUDE.md — Smart Meeting Recorder

Context primer for AI assistants. Read this first; open source files only as needed.

## Don't

- **Never `git push`.** The maintainer pushes manually, after reviewing the diff. Never push to
  `main`, never push tags, never `--force`. This applies even when a task seems to imply it
  ("release it", "ship it") — prepare the work and stop.
- **Never commit without asking first.** Show what changed (`git status` / `git diff`) and wait for
  an explicit go-ahead so the maintainer can review it. Staging is fine; committing is not.
- **Never add a `Co-Authored-By: Claude ...` trailer** (or any similar attribution line) to commit
  messages. Write the message as the maintainer would; no tool attribution.
- **Never create GitHub releases, or publish to the APT repo / any distribution channel.**
- **Don't run `sudo`** — hand the maintainer the exact command instead.
- **Don't delete recordings, `~/.config/meeting-recorder/`, or anything under
  `~/Videos/MeetingRecorder/`** without explicit permission. Build artifacts and `/tmp` scratch are
  fine to clean.

The working loop is: make the change → verify it → **report and wait**. The maintainer reviews,
commits and pushes.

## Idea
Lightweight Linux background daemon that auto-detects online meetings/calls (Zoom, Meet,
Teams, Discord, Slack, browsers), shows a **permission popup**, and on one click records
screen + mic + optional system audio — stopping automatically when the call ends. Privacy-first:
never records without consent.

## Concept / how it works
- **Detection = microphone capture by a known app.** PipeWire/PulseAudio exposes each active
  mic stream as a *source-output* tagged with the owning app. We poll `pactl list source-outputs`
  and match `application.name`/`binary` against an editable allowlist. Monitor (system-audio)
  streams are ignored so only real mic use triggers.
- **Debounce** avoids flapping: ~3s sustained presence to start, ~5s absence to stop.
- **Popup** via libnotify (`gi.repository.Notify`) with Record/Ignore buttons.
- **Recording is two-stage** (this is the core design — don't put audio filters back in the live path):
  1. *Live capture*: `x11grab` video + mic and system audio as **separate, unfiltered** tracks.
     No filters ⇒ no latency ⇒ segments can be any length.
  2. *Finalize* (`build_finalize_cmd`): concat segments, then denoise + per-source `loudnorm`
     + `amix` + limiter, **video stream-copied**. Runs as a **background** Popen polled from the
     GLib loop (loudnorm is only ~45x realtime ⇒ ~4.6 min for a 1h meeting); daemon stays responsive.
- **Pause/resume** ends/starts a segment, so paused time never reaches the file.
  (`SIGSTOP` does NOT work — input queues keep buffering and the paused span gets encoded on resume.)
- **Why loudnorm can't run live**: it buffers ~3s, which (a) silently truncated the last ~3s of every
  recording and (b) makes a clean pause boundary impossible. Output `.mkv` named `<App>_<timestamp>`.
- **Startup stall fix**: `-tune zerolatency` + `-thread_queue_size 1024` (otherwise x11grab starves
  and the first ~3s is a frozen black screen).
- Everything runs on one **GLib main loop**; ships as a `systemctl --user` service.

## Environment assumptions
Ubuntu 24.04, **X11** (uses x11grab; Wayland is a TODO), GNOME, **PipeWire**. Runs on system
`python3` using system PyGObject — **no pip dependencies**. Requires apt: `ffmpeg`,
`pulseaudio-utils`, `gir1.2-notify-0.7`, `x11-xserver-utils`.

## Structure (`meeting_recorder/`)
| File | Responsibility |
|------|----------------|
| `__main__.py` | CLI (`run`/`record`/`status`/`config`); wires everything on the GLib loop |
| `config.py` | Load `config/default_config.json` + user `~/.config/meeting-recorder/config.json` |
| `detector.py` | **Core.** Parse pactl, allowlist match, `DebounceMachine`, `MeetingDetector` poller |
| `audio.py` | Resolve default mic source + sink monitor via pactl |
| `recorder.py` | `build_ffmpeg_cmd` (pure) + `Recorder` process lifecycle |
| `notifier.py` | libnotify popup with action buttons (+ `notify-send` fallback); info notifications auto-dismiss ~2s |
| `recording_widget.py` | Floating top-right GTK3 pill: blinking dot, timer, pause/resume/stop |
| `settings_gui.py` | GTK3 settings window (`settings` subcommand); edits user config |
| `controller.py` | State machine IDLE→PROMPTING→RECORDING→IDLE; owns the widget + elapsed timer |
| `utils.py` | paths, filenames, logging |

`tests/` — zero-dep runner: `python3 tests/run_tests.py` (no pytest needed). Pure functions
(`parse_source_outputs`, `match_meeting_app`, `DebounceMachine`, `build_ffmpeg_cmd`) are the
unit-test surface. `systemd/`, `scripts/install.sh` handle packaging.

## Conventions
- Keep it dependency-free (stdlib + system `gi` only). No pip packages.
- Detection/recording logic must stay in pure, testable functions; subprocess/GLib at the edges.
- Config is flat JSON; add keys to `default_config.json` and `Config` together.
- Never record without an explicit user Record click unless `auto_record` is set.
