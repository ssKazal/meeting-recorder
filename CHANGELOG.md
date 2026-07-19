# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use
[Semantic Versioning](https://semver.org/).

## [0.3.1] — 2026-07-19

### Changed
- **Settings that 0.3.0 trimmed too aggressively are back**: file format
  (mkv/mp4), microphone and system-audio volume, and the capture area
  (full screen / current window / selected area) with its `x,y,w,h` region.
  Drag-select still needs `slop`, which is X11-only, so on Wayland the button is
  disabled with a tooltip and the region is typed instead.
- **`stop_debounce_seconds` now defaults to 3s** rather than the 60s introduced
  in 0.3.0, and the spinner steps by 1s. 60s left the recorder visibly running
  for a minute after every call. The consequence is unchanged: because muting
  releases the microphone, this delay is also the longest mute that will not end
  a recording, so raise it if you mute for long stretches.

### Fixed
- The settings window's action buttons sat in two stacked rows, so "Record now"
  and "Reset to defaults" did not share a baseline with "Cancel" and "Save".
  They are now one row.
- The APT repository stopped updating after v0.2.1. It publishes on
  `release: published`, but GitHub suppresses workflow-triggering events for
  anything created with the default `GITHUB_TOKEN` — so once releases were
  published by CI rather than by hand, `apt install meeting-recorder` silently
  kept serving 0.2.1 while newer releases sat on the releases page. The release
  workflow now calls the APT publish directly.

## [0.3.0] — 2026-07-19

### Added
- **Record now** button in the settings window: starts a recording immediately
  without waiting for a meeting to be detected. It runs the `record` subcommand,
  so it reuses the tray icon, timer, pause/resume and the Wayland portal
  handshake rather than reimplementing capture.
- **Reset to defaults** button, with a confirmation. Nothing is written until
  Save, so it can still be backed out by closing the window.

### Changed
- **The settings window is now minimal.** It shows only what changes the result:
  save folder, what to record (screen / microphone / system audio), noise
  cancellation, auto-record, and how long to keep recording after a call ends.
  Nothing was removed from the app — the daemon still reads every key, so file
  format, frame rate, capture mode/region, the volume sliders, normalization and
  the popup timeout remain editable in `~/.config/meeting-recorder/config.json`.
  Capture region in particular was a fixed rectangle that did not follow the
  window, and its drag-select needs `slop`, which is X11-only; on Wayland the
  portal already asks which screen or window to share.
- **"Save" and "Save & Apply" are now one "Save".** The daemon reads its config
  once at startup, so saving without restarting left the new settings silently
  inert. Save now writes, restarts the service and closes the window — staying
  open only if the restart fails.
- **`stop_debounce_seconds` now defaults to 3s** (was 5s) and the settings cap
  rose from 15s to 300s. Because muting releases the microphone, this delay is
  also the longest mute that will not end the recording — raise it if you mute
  for long stretches. The wait is trimmed off the saved file, so a larger value
  costs nothing but a recorder that keeps running after the call.

## [0.2.2] — 2026-07-19

### Fixed
- **The tray icon was white instead of red.** 0.2.1 made it visible by switching
  to `media-record-symbolic`, but gnome-shell recolours every `*-symbolic` icon
  to the panel foreground, so the indicator no longer read as "recording". It
  now ships two non-symbolic panel icons — a red dot while recording, amber
  pause bars while paused — keeping the symbolic names as a fallback for source
  checkouts. (The app icon can't be reused here: its thin dark screen outline
  disappears against a dark panel at 22px.)
- The release workflow hardcoded `Smart Meeting Recorder <tag>` as the release
  title and runs after the tag push, so it renamed releases after the fact. The
  title is now the bare tag.

### Changed
- Release notes no longer repeat the requirements block. It duplicated the
  README on every release and drifted out of date — it still claimed Wayland was
  unsupported on the release that added Wayland support. Requirements now live
  only in the README.

## [0.2.1] — 2026-07-19

### Fixed
- **The tray icon never appeared in the GNOME panel.** The indicator asked for
  `media-record`, which the Yaru theme does not ship — it has only
  `media-record-symbolic`. GTK still resolved the name through the legacy
  Humanity theme, so it looked correct to every local check, but the panel is
  drawn by gnome-shell, which resolves against its own theme, found nothing and
  drew an invisible icon. It now prefers the symbolic names (present in Yaru and
  Adwaita) and falls back to the bundled `meeting-recorder` icon in hicolor.
- The release footer, issue templates and apt landing page still said Wayland
  was unsupported and told users to log in with "Ubuntu on Xorg". The footer is
  appended to every GitHub release, so the 0.2.0 notes contradicted the release
  they were describing.

## [0.2.0] — 2026-07-19

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

[0.3.1]: https://github.com/ssKazal/meeting-recorder/releases/tag/v0.3.1
[0.3.0]: https://github.com/ssKazal/meeting-recorder/releases/tag/v0.3.0
[0.2.2]: https://github.com/ssKazal/meeting-recorder/releases/tag/v0.2.2
[0.2.1]: https://github.com/ssKazal/meeting-recorder/releases/tag/v0.2.1
[0.2.0]: https://github.com/ssKazal/meeting-recorder/releases/tag/v0.2.0
[0.1.2]: https://github.com/ssKazal/meeting-recorder/releases/tag/v0.1.2
[0.1.1]: https://github.com/ssKazal/meeting-recorder/releases/tag/v0.1.1
[0.1.0]: https://github.com/ssKazal/meeting-recorder/releases/tag/v0.1.0
