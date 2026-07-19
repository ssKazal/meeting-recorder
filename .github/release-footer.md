
### Install

```bash
sudo apt install ./meeting-recorder___VERSION___all.deb
```

`apt` pulls in ffmpeg and the other dependencies automatically. The background service is enabled and starts at your next login; to start it now:

```bash
meeting-recorder start
```

### ⚠️ Requirements

- **X11 and Wayland.** The backend is chosen automatically: X11 captures with `x11grab`, Wayland through the `xdg-desktop-portal` ScreenCast API. On Wayland your desktop asks permission to share the screen the first time — the choice is remembered, so recording stays one click.
- Debian/Ubuntu (built and tested on Ubuntu 24.04), GNOME, PipeWire or PulseAudio.

**Full documentation:** [README](https://github.com/ssKazal/meeting-recorder#readme) · **Changelog:** [CHANGELOG.md](https://github.com/ssKazal/meeting-recorder/blob/main/CHANGELOG.md)
