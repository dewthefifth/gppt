# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**GPPT** — GNOME Shell extension providing Discord/Vesktop push-to-talk on Wayland. It listens to raw input events via `evdev` from a Python daemon, then mutes/unmutes the Discord microphone via `pactl`.

Extension UUID: `discord-ptt@vimax.example.com`  
Supported GNOME Shell: 45–50

## Setup & Installation

```bash
# Generate audio click sounds (one-time, uses only stdlib)
python3 daemon/generate_sounds.py

# Install extension
cp -r . ~/.local/share/gnome-shell/extensions/discord-ptt@vimax.example.com/

# Compile GSettings schema after schema changes
glib-compile-schemas schemas/

# Reload extension during development
gnome-extensions disable discord-ptt@vimax.example.com
gnome-extensions enable discord-ptt@vimax.example.com

# View extension logs
journalctl -f /usr/bin/gnome-shell
```

## Runtime Dependencies

- GNOME Shell 45+ (GTK4, Libadwaita, ESM module syntax)
- Python 3 + `python-evdev` (`pip install evdev` or `pacman -S python-evdev`)
- `pactl` and `paplay` (from PipeWire/PulseAudio)

## Architecture

Two-layer design: a GNOME Shell extension (JavaScript) manages lifecycle, while a Python daemon handles input and audio control.

### JavaScript Layer (`extension.js`, `prefs.js`)

- `extension.js`: Panel indicator with popup menu; spawns/kills the daemon subprocess; watches GSettings for config changes (restarts daemon with 300ms delay on change)
- `prefs.js`: GTK4/Libadwaita preferences UI; key capture dialog translates GDK `hardware_keycode → evdev code` via `keycode - 8`
- Settings bind directly to UI widgets via GSettings

### Python Daemon (`daemon/discord_ptt.py`)

Runs as an independent asyncio process. Key behaviors:
- Opens **all** accessible `/dev/input/` devices concurrently, each in its own coroutine
- Listens for the configured evdev keycode (not XKB — the offset is `hardware_keycode - 8 = evdev_code`)
- On keypress: calls `find_discord_source_output()` → `pactl set-source-output-mute 0`; on release: mute
- `find_discord_source_output()` uses `pactl --format=json list source-outputs` to find Discord/Vesktop/Electron voice engine; re-discovers automatically if mute fails
- Plays click sounds via `paplay` (non-blocking)
- SIGINT/SIGTERM handler: unmutes mic before exit

### GSettings Schema (`schemas/`)

Key settings in `org.gnome.shell.extensions.discord-ptt.gschema.xml`:
- `ptt-key-code` (int, default 58): **evdev** keycode (CapsLock=58, not XKB)
- `is-active` (bool): master switch, toggled from popup menu
- `ptt-sound-enabled` (bool): click sound toggle
- `device-path` (string, deprecated): kept for schema compatibility only — daemon now listens on all devices

After editing the schema XML, always recompile: `glib-compile-schemas schemas/`

## Key Conventions

- JS files use ESM (`import`/`export`), not CommonJS — required for GNOME Shell 45+
- The daemon receives config as CLI arguments, not via IPC; config changes always restart the daemon
- `evdev` keycodes = XKB/GDK hardware keycodes − 8 (hardcoded offset, applies everywhere)
- The daemon opens `/dev/input/` devices directly; user must be in the `input` group or have appropriate udev rules
