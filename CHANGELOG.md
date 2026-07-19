# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Wayland screen capture.** Sessions are detected automatically: X11 keeps using
  `x11grab`, Wayland captures through the `xdg-desktop-portal` ScreenCast API.
  Because ffmpeg has no PipeWire input device, a small `gst-launch-1.0
  pipewiresrc` pump feeds raw frames into the *same* ffmpeg process that records
  the audio — so there is one process, one clock, and the two-stage
  capture/finalize design (and exact pause/resume) is unchanged.
- The portal permission is requested once and stored as `wayland_restore_token`,
  so later recordings do not re-prompt and Record stays one click.
- `MEETING_RECORDER_CAPTURE=portal|x11` forces a capture backend. The portal path
  also works on GNOME/X11, which makes it testable without changing sessions.

### Fixed
- **Background noise is no longer amplified.** `loudnorm` ran after denoising,
  so it applied whatever gain reached -23 LUFS and lifted room tone up with the
  voice — measured on a silent room, the mic chain came out *9 dB louder* than
  the raw input, leaving the background about as loud as the speaker. A noise
  gate now runs before `loudnorm` (and `afftdn` is slightly stronger): on the
  same mic, room tone drops 26 dB while speech changes 1.5 dB and keeps
  identical peaks.
- `meeting-recorder record` now shows the tray icon, live timer and
  pause/resume controls. It built a bare `Recorder` instead of going through the
  Controller, so a manual recording had no controls at all — on X11 as well as
  Wayland. It now drives the same Controller the daemon uses, and stopping from
  the tray ends the command just like Ctrl-C.
- The tray icon now appears the moment Record is pressed, instead of only after
  capture starts. On Wayland the portal handshake runs first, so the controls
  were missing for the whole handshake — and never appeared at all if the portal
  stalled or crashed, making Record look like it had done nothing.
- A manual `record` is no longer discarded for being shorter than
  `min_recording_seconds`; that rule exists to drop false-positive meeting
  detections, and a manual recording was asked for explicitly.
- The ScreenCast handshake now gives up after 120s instead of hanging forever
  when the dialog is never answered or the portal stops responding.

### Changed
- **Far fewer notifications.** Only two remain: the Record/Ignore prompt, and the
  clickable "saved" result. The "Recording started", "Processing recording…",
  "Recording discarded", "Recording stopped", "Recording audio only",
  "Preparing screen capture…" and service-startup popups are gone — they
  interrupted the call they were reporting on. Live status is the tray icon's
  job; the removed messages are still in the log.
- Denying the screen-share prompt now records audio only instead of failing.
- `.deb` dependencies gained `xdg-desktop-portal` and the GStreamer PipeWire
  plugins; `x11-utils`/`x11-xserver-utils` moved to `Recommends`, as they are
  only needed for the X11 capture path.

### Known limitations
- On Wayland the compositor positions the floating control pill: clients cannot
  place their own windows, and Mutter has no layer-shell protocol.
- Drag-to-select a capture region still needs X11 (`slop`).

## [0.1.2] — 2026-07-17

### Fixed
- `meeting-recorder record` now produces a file. It treated the boolean from
  `stop()` as the saved path and exited immediately, so the background finalize
  pass (concat + denoise + normalize) was killed by the same Ctrl-C that stopped
  capture — leaving orphaned segment files and no output. It now waits for
  finalize to finish and reports the real saved path.

### Internal
- CI builds the `debian/` source package (adds `build-essential`), keeping the
  Launchpad packaging path from drifting from `packaging/build-deb.sh`.

## [0.1.1] — 2026-07-17

### Added
- `meeting-recorder start`, `stop`, `restart` and `logs` — wrappers around
  `systemctl --user` / `journalctl --user`, so the `--user` flag is never needed
  for day-to-day use.

### Changed
- `meeting-recorder status` now reports the background service state (active,
  inactive, failed, or not-installed) alongside the active capture streams and
  the meeting match.
- README and man page explain why this must be a *user* service rather than a
  system one: it needs the caller's X display for screen capture, PulseAudio
  session for audio, and D-Bus session for notifications and the tray icon —
  the same reason `pipewire` is a user service.

## [0.1.0] — 2026-07-17

First release.

### Added
- **Automatic meeting detection** — watches PipeWire/PulseAudio capture streams and
  triggers when a known app (Zoom, Google Meet, Teams, Discord, Slack, Webex, or a
  browser) starts using the microphone. Editable allowlist; debounced to avoid
  false triggers.
- **Permission popup** — "Meeting detected. Start recording?" with Record / Ignore.
  Never records without consent (unless `auto_record` is enabled).
- **Recording** of screen + microphone + optional system audio to `.mkv`, named
  `<App>_<YYYY-MM-DD_HH-MM-SS>`.
- **Automatic stop** when the call ends, with the post-call tail trimmed off so the
  file ends when the call did.
- **Tray controls** — a system-tray icon with a live timer, Pause / Resume,
  Stop & Save, Open recordings folder and Settings. Falls back to a floating
  on-screen pill if the tray is unavailable.
- **Pause excludes paused time** — pausing ends a recording segment and resuming
  starts a new one, so a 20-minute call paused for 5 minutes saves as 15 minutes.
- **Balanced audio** — mic and system audio are each normalized to the same
  loudness target (EBU R128) at finalize, so your voice and the caller's match.
- **Noise cancellation** on the microphone (`afftdn`, or RNNoise via `arnndn` with
  an optional model).
- **Capture area** — full screen, current window, or a selected region.
- **Settings GUI** (`meeting-recorder settings`) for save folder, format, frame
  rate, volumes, normalization, noise cancellation and behavior.
- **Background service** via systemd, idling at a few MB of RAM. `meeting-recorder
  start|stop|restart|logs|status` wrap `systemctl --user`, so the `--user` flag is
  never needed (it must be a *user* service: it needs your X display, audio and
  D-Bus session).
- Debian/Ubuntu `.deb` package.

### Notes / known limitations
- **X11 only.** Screen capture uses `x11grab`; Wayland sessions are not yet
  supported. Log in with "Ubuntu on Xorg" to use this release.
- Window/region capture records a fixed rectangle — moving the window mid-call does
  not move the capture.
- Audio is processed when the recording is saved, so changes to volume settings
  apply to new recordings only.
- Drag-selecting a capture region needs the optional `slop` package.

[0.1.2]: https://github.com/ssKazal/meeting-recorder/releases/tag/v0.1.2
[0.1.1]: https://github.com/ssKazal/meeting-recorder/releases/tag/v0.1.1
[0.1.0]: https://github.com/ssKazal/meeting-recorder/releases/tag/v0.1.0
