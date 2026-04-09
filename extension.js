/**
 * extension.js — Discord Push-to-Talk GNOME Shell Extension
 *
 * Top-bar indicator that spawns a Python evdev daemon to handle PTT.
 * Compatible with GNOME Shell 45–50 (ESM module syntax).
 *
 * The daemon listens on ALL /dev/input/ devices simultaneously, so no
 * device selection is needed — any keyboard, mouse, or controller works.
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

// ─────────────────────────────────────────────────────────────────────────────
// Panel indicator widget
// ─────────────────────────────────────────────────────────────────────────────

const DiscordPttIndicator = GObject.registerClass(
    {GTypeName: 'DiscordPttIndicator'},
    class DiscordPttIndicator extends PanelMenu.Button {

        _init(extension) {
            super._init(0.0, 'Discord PTT');

            this._ext = extension;
            this._settings = extension.getSettings();
            this._daemon = null;
            this._restartIdle = 0;

            // ── Panel icon ────────────────────────────────────────────────
            this._icon = new St.Icon({
                icon_name: 'audio-input-microphone-symbolic',
                style_class: 'system-status-icon',
            });
            this.add_child(this._icon);

            // ── Popup menu ────────────────────────────────────────────────
            const settingsItem = new PopupMenu.PopupMenuItem('Settings');
            settingsItem.connect('activate', () => this._ext.openPreferences());
            this.menu.addMenuItem(settingsItem);

            this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

            this._toggleItem = new PopupMenu.PopupSwitchMenuItem(
                'Enable PTT',
                this._settings.get_boolean('is-active')
            );
            this._toggleItem.connect('toggled', (_item, state) => {
                this._settings.set_boolean('is-active', state);
            });
            this.menu.addMenuItem(this._toggleItem);

            // ── Watch settings ────────────────────────────────────────────
            this._settings.connectObject(
                'changed::is-active',         () => this._syncState(),
                'changed::ptt-key-code',      () => this._restartIfActive(),
                'changed::ptt-sound-enabled', () => this._restartIfActive(),
                this
            );

            this._syncState();
        }

        // ── State management ──────────────────────────────────────────────

        _syncState() {
            const active = this._settings.get_boolean('is-active');

            if (this._toggleItem.state !== active)
                this._toggleItem.setToggleState(active);

            this._icon.icon_name = active
                ? 'audio-input-microphone-symbolic'
                : 'audio-input-microphone-muted-symbolic';

            if (active)
                this._spawnDaemon();
            else {
                if (this._restartIdle) {
                    GLib.source_remove(this._restartIdle);
                    this._restartIdle = 0;
                }
                this._killDaemon();
            }
        }

        _restartIfActive() {
            if (!this._settings.get_boolean('is-active'))
                return;
            this._killDaemon();
            if (this._restartIdle)
                GLib.source_remove(this._restartIdle);
            this._restartIdle = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 300, () => {
                this._restartIdle = 0;
                if (this._settings.get_boolean('is-active'))
                    this._spawnDaemon();
                return GLib.SOURCE_REMOVE;
            });
        }

        // ── Daemon lifecycle ──────────────────────────────────────────────

        _spawnDaemon() {
            if (this._restartIdle) {
                GLib.source_remove(this._restartIdle);
                this._restartIdle = 0;
            }
            this._killDaemon();

            const keyCode      = this._settings.get_int('ptt-key-code');
            const soundEnabled = this._settings.get_boolean('ptt-sound-enabled');

            const daemonPath   = GLib.build_filenamev([this._ext.path, 'daemon', 'discord_ptt.py']);
            const soundOnPath  = GLib.build_filenamev([this._ext.path, 'sounds', 'ptt_on.wav']);
            const soundOffPath = GLib.build_filenamev([this._ext.path, 'sounds', 'ptt_off.wav']);

            // Daemon listens on ALL devices — no --device arg needed
            const argv = [
                'python3', daemonPath,
                '--key',       String(keyCode),
                '--sound-on',  soundOnPath,
                '--sound-off', soundOffPath,
            ];

            if (!soundEnabled)
                argv.push('--no-sound');

            try {
                this._daemon = Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);

                this._daemon.wait_async(null, (proc, result) => {
                    try {
                        proc.wait_finish(result);
                    } catch (_e) {
                        return;
                    }
                    if (this._daemon === proc) {
                        this._daemon = null;
                        const code = proc.get_exit_status();
                        console.warn(`[discord-ptt] Daemon exited unexpectedly (exit code ${code}) — disabling PTT`);
                        this._settings.set_boolean('is-active', false);
                    }
                });

                console.log(`[discord-ptt] Daemon started (PID ${this._daemon.get_identifier()})`);
            } catch (e) {
                console.error(`[discord-ptt] Failed to start daemon: ${e.message}`);
                this._settings.set_boolean('is-active', false);
            }
        }

        _killDaemon() {
            if (!this._daemon)
                return;

            const proc = this._daemon;
            this._daemon = null;

            if (proc.get_if_exited() || proc.get_if_signaled())
                return;

            proc.send_signal(2); // SIGINT → Python cleanup handler

            GLib.timeout_add(GLib.PRIORITY_DEFAULT, 2000, () => {
                if (!proc.get_if_exited() && !proc.get_if_signaled())
                    proc.force_exit();
                return GLib.SOURCE_REMOVE;
            });
        }

        destroy() {
            if (this._restartIdle) {
                GLib.source_remove(this._restartIdle);
                this._restartIdle = 0;
            }
            this._killDaemon();
            super.destroy();
        }
    }
);

// ─────────────────────────────────────────────────────────────────────────────
// Extension entry point
// ─────────────────────────────────────────────────────────────────────────────

export default class DiscordPttExtension extends Extension {
    enable() {
        this._indicator = new DiscordPttIndicator(this);
        Main.panel.addToStatusArea(this.uuid, this._indicator);
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
