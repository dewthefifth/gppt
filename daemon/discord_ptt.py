#!/usr/bin/env python3
"""
Discord Push-to-Talk Daemon for GNOME Shell Extension.

Listens on ALL available /dev/input/ devices simultaneously.
No device selection needed — works with any keyboard, mouse, or controller.

When the PTT key is pressed on ANY device:
  → unmutes Discord/Vesktop microphone via pactl (PipeWire/PulseAudio)
  → plays a click sound via paplay (optional)

On key release:
  → mutes the microphone again
  → plays a release click sound (optional)
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

try:
    import evdev
    from evdev import ecodes
except ImportError:
    print(
        'Error: python-evdev is not installed.\n'
        '  sudo pacman -S python-evdev        (Arch / CachyOS)\n'
        '  sudo apt install python3-evdev     (Debian / Ubuntu)\n'
        '  pip install evdev',
        file=sys.stderr,
    )
    sys.exit(1)

IDLE_MUTE_INTERVAL_SEC = 1.0
HOTPLUG_SCAN_INTERVAL_SEC = 1.5

log = logging.getLogger('discord_ptt')

# ─────────────────────────────────────────────────────────────────────────────
# PulseAudio / PipeWire helpers
# ─────────────────────────────────────────────────────────────────────────────

def _prop_text(props: dict, key: str) -> str:
    v = props.get(key)
    if v is None:
        return ''
    if isinstance(v, list):
        return ' '.join(str(x) for x in v)
    return str(v)


def is_discord_voice_source(props: dict) -> bool:
    name = _prop_text(props, 'application.name').lower()
    binary = _prop_text(props, 'application.process.binary').lower()
    media = _prop_text(props, 'media.name').lower()
    hay = f'{name} {binary} {media}'

    if 'vesktop' in hay:
        return True
    if 'webcord' in hay or 'legcord' in hay:
        return True
    if 'discord' in binary or '/discord' in binary:
        return True
    if name == 'discord' or name.startswith('discord '):
        return True
    if 'discord' in name and ('electron' in binary or 'discord' in binary):
        return True
    if 'webrtc voiceengine' in hay and 'discord' in hay:
        return True
    return False


def find_discord_source_outputs() -> list[int]:
    try:
        result = subprocess.run(
            ['pactl', '--format=json', 'list', 'source-outputs'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            log.warning('pactl list source-outputs failed (rc=%d): %s',
                        result.returncode, result.stderr.strip())
            return []

        out: list[int] = []
        for row in json.loads(result.stdout):
            props = row.get('properties', {})
            if not is_discord_voice_source(props):
                continue
            idx = row['index']
            log.debug('Discord source-output: index=%d, app=%s',
                      idx, props.get('application.name', '?'))
            out.append(idx)

        if not out:
            log.debug('No Discord source-output found (not in a voice channel?)')
        return sorted(set(out))

    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        log.warning('find_discord_source_outputs error: %s', e)
        return []


def set_mute(source_output_id: int, muted: bool) -> bool:
    """Mute or unmute a PipeWire source-output. Returns True on success."""
    try:
        result = subprocess.run(
            ['pactl', 'set-source-output-mute', str(source_output_id), '1' if muted else '0'],
            capture_output=True, timeout=3,
        )
        if result.returncode != 0:
            log.warning('set-source-output-mute failed for id=%d (rc=%d)',
                        source_output_id, result.returncode)
            return False
        log.debug('source-output %d → muted=%s', source_output_id, muted)
        return True
    except (subprocess.TimeoutExpired, Exception) as e:
        log.warning('set_mute error: %s', e)
        return False


def apply_mute_to_outputs(ids: list[int], muted: bool) -> bool:
    ok = True
    for oid in ids:
        if not set_mute(oid, muted):
            ok = False
    return ok

# ─────────────────────────────────────────────────────────────────────────────
# Push-to-Talk controller
# ─────────────────────────────────────────────────────────────────────────────

class PushToTalkController:
    """
    Opens ALL /dev/input/ devices and listens on them concurrently via asyncio.
    When the PTT key is detected on any device, toggles Discord mute via pactl.
    """

    def __init__(self, ptt_keycode: int, sound_on: str | None,
                 sound_off: str | None, sound_enabled: bool) -> None:
        self.ptt_keycode = ptt_keycode
        self.sound_on    = sound_on  if sound_enabled and sound_on  and Path(sound_on).exists()  else None
        self.sound_off   = sound_off if sound_enabled and sound_off and Path(sound_off).exists() else None

        if sound_enabled:
            if sound_on  and not self.sound_on:  log.warning('Sound file not found: %s', sound_on)
            if sound_off and not self.sound_off: log.warning('Sound file not found: %s', sound_off)

        self._cached_output_ids: list[int] | None = None
        self._devices_holding: set[str] = set()
        self._running   = True
        self._loop: asyncio.AbstractEventLoop | None = None
        self._guard_task: asyncio.Task | None = None
        self._hotplug_task: asyncio.Task | None = None
        self._mute_lock: asyncio.Lock | None = None
        self._opened_paths: set[str] = set()
        self._device_tasks: set[asyncio.Task] = set()

    def _spawn_listener(self, device: evdev.InputDevice) -> None:
        path = device.path
        if path in self._opened_paths:
            try:
                device.close()
            except Exception:
                pass
            return
        self._opened_paths.add(path)
        t = asyncio.create_task(self._listen_device(device))
        self._device_tasks.add(t)
        t.add_done_callback(lambda fut: self._device_tasks.discard(fut))

    def _discover_outputs(self) -> list[int]:
        ids = find_discord_source_outputs()
        self._cached_output_ids = ids if ids else None
        return ids

    def _apply_mute_worker(self, muted: bool) -> None:
        ids = self._cached_output_ids
        if not ids:
            ids = self._discover_outputs()
        if not ids:
            if muted:
                log.debug('Discord not in a voice channel — skip mute')
            return
        if not apply_mute_to_outputs(ids, muted):
            log.info('pactl mute failed — re-discovering source-outputs')
            self._cached_output_ids = None
            ids = self._discover_outputs()
            if ids:
                apply_mute_to_outputs(ids, muted)

    async def _apply_mute_async(self, muted: bool) -> None:
        lock = self._mute_lock
        if lock is None:
            await asyncio.to_thread(self._apply_mute_worker, muted)
            return
        async with lock:
            await asyncio.to_thread(self._apply_mute_worker, muted)

    def _idle_mute_enforce(self) -> None:
        if not self._running:
            return
        ids = find_discord_source_outputs()
        if not self._running:
            return
        self._cached_output_ids = ids if ids else None
        if not ids:
            return
        for oid in ids:
            if not self._running:
                return
            set_mute(oid, True)

    async def _idle_mute_guard(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(IDLE_MUTE_INTERVAL_SEC)
                if not self._running:
                    break
                lock = self._mute_lock
                if lock is None:
                    continue
                async with lock:
                    if not self._running:
                        break
                    if self._devices_holding:
                        await asyncio.to_thread(self._apply_mute_worker, False)
                    else:
                        await asyncio.to_thread(self._idle_mute_enforce)
        except asyncio.CancelledError:
            raise

    async def _hotplug_loop(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(HOTPLUG_SCAN_INTERVAL_SEC)
                if not self._running:
                    break
                for path in evdev.list_devices():
                    if path in self._opened_paths:
                        continue
                    try:
                        d = evdev.InputDevice(path)
                    except (PermissionError, FileNotFoundError, OSError):
                        continue
                    log.info('New input device: %s (%s)', d.name, path)
                    self._spawn_listener(d)
        except asyncio.CancelledError:
            raise

    # ── Sound ─────────────────────────────────────────────────────────────────

    async def _play_sound(self, sound_path: str | None) -> None:
        if not sound_path:
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                'paplay', '--property=media.role=event', sound_path,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            asyncio.create_task(proc.wait())
        except FileNotFoundError:
            log.warning('paplay not found — disabling sounds')
            self.sound_on = self.sound_off = None
        except Exception as e:
            log.debug('Sound error: %s', e)

    # ── Signal handling ───────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Called on SIGINT/SIGTERM — unmutes Discord and stops the loop."""
        log.info('Shutting down — unmuting Discord')
        self._running = False
        if self._guard_task and not self._guard_task.done():
            self._guard_task.cancel()
        if self._hotplug_task and not self._hotplug_task.done():
            self._hotplug_task.cancel()
        for oid in find_discord_source_outputs():
            set_mute(oid, False)

        if self._loop and self._loop.is_running():
            self._loop.stop()

    def _ptt_press(self, path: str, name: str) -> None:
        if path in self._devices_holding:
            return
        self._devices_holding.add(path)
        if len(self._devices_holding) == 1:
            log.debug('PTT DOWN on "%s" → unmuting', name)
            loop = asyncio.get_running_loop()
            loop.create_task(self._play_sound(self.sound_on))
            loop.create_task(self._apply_mute_async(False))

    def _ptt_release(self, path: str, name: str, play_sound: bool) -> None:
        if path not in self._devices_holding:
            return
        self._devices_holding.discard(path)
        if len(self._devices_holding) == 0:
            log.debug('PTT UP on "%s" → muting', name)
            loop = asyncio.get_running_loop()
            loop.create_task(self._apply_mute_async(True))
            if play_sound:
                loop.create_task(self._play_sound(self.sound_off))

    async def _listen_device(self, device: evdev.InputDevice) -> None:
        path = device.path
        try:
            async for event in device.async_read_loop():
                if not self._running:
                    break
                if event.type != ecodes.EV_KEY or event.code != self.ptt_keycode:
                    continue
                if event.value == 1:
                    self._ptt_press(path, device.name)
                elif event.value == 0:
                    self._ptt_release(path, device.name, True)
        except OSError as e:
            log.debug('Device "%s" disconnected: %s', device.name, e)
        except asyncio.CancelledError:
            raise
        finally:
            self._opened_paths.discard(path)
            if self._running:
                self._ptt_release(path, device.name, False)
            else:
                self._devices_holding.discard(path)
            try:
                device.close()
            except Exception:
                pass

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._mute_lock = asyncio.Lock()

        paths = evdev.list_devices()
        if not paths:
            log.error('No /dev/input event devices found.')
            sys.exit(1)

        opened: list[evdev.InputDevice] = []
        skipped = 0
        for path in paths:
            try:
                opened.append(evdev.InputDevice(path))
            except (PermissionError, FileNotFoundError, OSError):
                skipped += 1

        if not opened:
            log.warning(
                'Could not open any input device yet (%d skipped — permissions or timing). '
                'Will attach Bluetooth/USB keyboards when they appear. '
                'If this persists: sudo usermod -aG input %s  (then log out and in)',
                skipped, os.getenv('USER', '$USER'),
            )

        for d in opened:
            log.debug('  → %s (%s)', d.path, d.name)
            self._spawn_listener(d)

        log.info('Listening for keycode %d — %d device(s) now, %d skipped, hotplug every %.1fs',
                 self.ptt_keycode, len(opened), skipped, HOTPLUG_SCAN_INTERVAL_SEC)

        await self._apply_mute_async(True)

        self._guard_task = asyncio.create_task(self._idle_mute_guard())
        self._hotplug_task = asyncio.create_task(self._hotplug_loop())
        try:
            await asyncio.gather(self._guard_task, self._hotplug_task)
        finally:
            if self._guard_task:
                self._guard_task.cancel()
                try:
                    await self._guard_task
                except asyncio.CancelledError:
                    pass
                self._guard_task = None
            if self._hotplug_task:
                self._hotplug_task.cancel()
                try:
                    await self._hotplug_task
                except asyncio.CancelledError:
                    pass
                self._hotplug_task = None
            for t in list(self._device_tasks):
                t.cancel()
            if self._device_tasks:
                await asyncio.gather(*self._device_tasks, return_exceptions=True)
            self._device_tasks.clear()
            if self._devices_holding:
                log.info('Key held at exit — ensuring Discord is unmuted')
                await self._apply_mute_async(False)

# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Discord PTT daemon — listens on ALL /dev/input/ devices',
    )
    parser.add_argument('--key', required=True, type=int, metavar='CODE',
                        help='Linux evdev keycode for PTT (raw kernel code, not XKB)')
    parser.add_argument('--sound-on',  metavar='PATH', default=None,
                        help='WAV file to play on PTT key press')
    parser.add_argument('--sound-off', metavar='PATH', default=None,
                        help='WAV file to play on PTT key release')
    parser.add_argument('--no-sound', action='store_true',
                        help='Disable all PTT click sounds')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose (DEBUG) logging')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        stream=sys.stderr,
    )

    controller = PushToTalkController(
        ptt_keycode=args.key,
        sound_on=args.sound_on,
        sound_off=args.sound_off,
        sound_enabled=not args.no_sound,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.add_signal_handler(signal.SIGINT,  controller.cleanup)
    loop.add_signal_handler(signal.SIGTERM, controller.cleanup)

    try:
        loop.run_until_complete(controller.run())
    except RuntimeError as e:
        if 'stop' not in str(e).lower():
            raise
    finally:
        loop.close()
        log.info('Discord PTT daemon stopped')


if __name__ == '__main__':
    main()
