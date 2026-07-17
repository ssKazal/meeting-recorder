# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use
[Semantic Versioning](https://semver.org/).

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
