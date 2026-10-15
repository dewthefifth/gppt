# GPPT — Push-to-Talk for Discord / Vesktop (GNOME, Wayland)

*Русский: [README.ru.md](README.ru.md)*

A **GNOME Shell 45–50** extension: while the key is **not** held, Discord / Vesktop microphone capture is forced **muted** via PipeWire/PulseAudio; while you hold the key, it is **unmuted**. Works on **Wayland** by reading **evdev** events from `/dev/input/*`, not through an X11/Wayland grab.

**Extension UUID:** `discord-ptt@vimax.example.com`

---

## How it works

| Layer | Role |
|--------|------|
| **Extension** (`extension.js`) | Panel icon, PTT on/off menu, starts/stops the daemon, reacts to GSettings |
| **Preferences** (`prefs.js`) | Settings UI: key capture (any keyboard/mouse), click sounds, master switch |
| **Daemon** (`daemon/discord_ptt.py`) | Async process: listens on **all** accessible input devices, uses the configured evdev keycode, calls `pactl set-source-output-mute` on Discord / Vesktop (and related) streams |

Notes:

- The daemon does not talk to the shell over a socket: config is passed as **CLI arguments**; changing settings **restarts** the daemon (with a short delay).
- **Multiple keyboards/devices** are handled: the mic is muted only when the key is released on **every** device where it was pressed; unplugging a USB device clears the “held” state for that device.
- When PTT is off in the menu, the daemon is not running; unmute on exit is done in the daemon’s signal handler.
- Keyboards or mice that show up **after** startup (common with **Bluetooth**) are picked up on a short interval (~1.5s) and wired the same as built-in devices.

Developer-oriented details: [CLAUDE.md](CLAUDE.md).

---

## Requirements

- **GNOME Shell** 45–50 (Wayland or X11 — the daemon still uses evdev).
- **Python 3** and **python-evdev** (the `evdev` module).
- **PipeWire** or PulseAudio with **`pactl`** and **`paplay`**.
- Access to input devices: user in the **`input`** group or suitable **udev** rules (otherwise the daemon cannot open `/dev/input/...`).

---

## System dependencies

**Arch / CachyOS:**

```bash
sudo pacman -S python-evdev pipewire-pulse
```

**Debian / Ubuntu:**

```bash
sudo apt install python3-evdev pipewire-pulseaudio
```

Python module only (alternative):

```bash
pip install --user evdev
```

---

## Prepare / “build”

There is no separate compile step: generate click sounds once (they may already exist under `sounds/`) and compile the GSettings schema.

```bash
cd /path/to/gppt

# Press/release click WAVs (once; stdlib only)
python3 daemon/generate_sounds.py

# Compile settings schema (required after changes to schemas/*.xml)
glib-compile-schemas schemas/
```

---

## Install the extension

```bash
cp -r /path/to/gppt ~/.local/share/gnome-shell/extensions/discord-ptt@vimax.example.com/
glib-compile-schemas ~/.local/share/gnome-shell/extensions/discord-ptt@vimax.example.com/schemas/
```

Enable it:

```bash
gnome-extensions enable discord-ptt@vimax.example.com
```

Or use the **Extensions** app → **Discord Push-to-Talk** → On.

If the icon does not show, log out and back in (on Wayland a full session restart is sometimes needed).

---

## First-time setup

> [!NOTE]
> For Bazzite and other atomic operating systems, there may be additional steps. See [add-user-to-group](https://docs.bazzite.gg/Advanced/add-user-to-group/)

1. **`input` group** (if the daemon reports no access to devices):

   ```bash
   sudo usermod -aG input "$USER"
   ```

   Then **log out and log in again**.


2. In the extension menu (microphone icon on the panel), turn **Enable PTT** on.

3. **Settings** → **Capture Key** — press the key or mouse button you want. The code is stored as **evdev** (internally: GDK `hardware_keycode − 8`).

4. Run **Discord** or **Vesktop** and join a **voice channel** — otherwise PipeWire may not create the `source-output` the daemon needs.

5. Optionally toggle **PTT Click Sound** in settings.

---

## Updating

Copy the project over the installed folder again (same as install), run `glib-compile-schemas` in the extension directory, then reload:

```bash
gnome-extensions disable discord-ptt@vimax.example.com
gnome-extensions enable discord-ptt@vimax.example.com
```

Toggling **Enable PTT** in the indicator menu only restarts the daemon; after changing **JS** files you still need disable/enable of the extension or a new session.

---

## Debugging

**GNOME Shell** logs (extension errors, daemon spawn):

```bash
journalctl -f /usr/bin/gnome-shell
```

Run the daemon manually (verbose):

```bash
python3 ~/.local/share/gnome-shell/extensions/discord-ptt@vimax.example.com/daemon/discord_ptt.py \
  --key 58 \
  --sound-on .../sounds/ptt_on.wav \
  --sound-off .../sounds/ptt_off.wav \
  -v
```

`--key` is the evdev scancode (settings often default to **58**, Caps Lock).

---

## Limitations

- Voice streams are detected from PipeWire properties (`application.name`, binary path, etc.). Unusual builds or other clients may need tweaks in `daemon/discord_ptt.py`.
- **`kill -9`** on the daemon skips the unmute handler — prefer turning PTT off from the menu or using `SIGINT`/`SIGTERM`.
