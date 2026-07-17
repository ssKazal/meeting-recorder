
### Install

```bash
sudo apt install ./meeting-recorder___VERSION___all.deb
```

`apt` pulls in ffmpeg and the other dependencies automatically. The background service is enabled and starts at your next login; to start it now:

```bash
meeting-recorder start
```

### ⚠️ Requirements

- **X11 only.** Screen capture uses `x11grab`; **Wayland is not supported yet**. Ubuntu 24.04 defaults to Wayland — check your session with `echo $XDG_SESSION_TYPE` (it must print `x11`). If it prints `wayland`, log out and pick **"Ubuntu on Xorg"** from the gear menu on the login screen.
- Debian/Ubuntu (built and tested on Ubuntu 24.04), GNOME, PipeWire or PulseAudio.

**Full documentation:** [README](https://github.com/ssKazal/meeting-recorder#readme) · **Changelog:** [CHANGELOG.md](https://github.com/ssKazal/meeting-recorder/blob/main/CHANGELOG.md)
