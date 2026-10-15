/**
 * prefs.js — Discord PTT Extension Preferences
 *
 * GTK4 + Libadwaita preferences window.
 * Compatible with GNOME Shell 45–50 (ExtensionPreferences API).
 *
 * No device selection needed — the daemon listens on ALL /dev/input/ devices.
 */

import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';
import Adw from 'gi://Adw';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

// ─────────────────────────────────────────────────────────────────────────────
// evdev keycode → human-readable name
// Raw kernel keycodes from /usr/include/linux/input-event-codes.h
// NOT the GDK/XKB keycodes (those are evdev + 8).
// ─────────────────────────────────────────────────────────────────────────────

const EVDEV_KEY_NAMES = {
    1:   'ESC',          2:   '1',            3:   '2',            4:   '3',
    5:   '4',            6:   '5',            7:   '6',            8:   '7',
    9:   '8',            10:  '9',            11:  '0',            14:  'Backspace',
    15:  'Tab',          28:  'Enter',        29:  'Left Ctrl',    42:  'Left Shift',
    54:  'Right Shift',  56:  'Left Alt',     57:  'Space',        58:  'Caps Lock',
    59:  'F1',           60:  'F2',           61:  'F3',           62:  'F4',
    63:  'F5',           64:  'F6',           65:  'F7',           66:  'F8',
    67:  'F9',           68:  'F10',          87:  'F11',          88:  'F12',
    97:  'Right Ctrl',   100: 'Right Alt',    111: 'Delete',       119: 'Pause',
    125: 'Left Meta',    126: 'Right Meta',   127: 'Menu',
    183: 'F13',          184: 'F14',          185: 'F15',          186: 'F16',
    272: 'Left Click',   273: 'Right Click',  274: 'Middle Click',
    275: 'Side Button',  276: 'Extra Button',
};

function evdevKeyName(code) {
    return EVDEV_KEY_NAMES[code] ?? `Key ${code}`;
}

function formatKeySubtitle(code) {
    return `${evdevKeyName(code)}  ·  evdev code ${code}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Key capture dialog
//
// Captures a key from ANY connected device via the Wayland compositor.
// Conversion: GDK hardware_keycode → evdev keycode
//   GDK hardware_keycode = evdev_code + 8  (XKB offset, same on X11 and Wayland)
//   evdev_code = hardware_keycode - 8
// ─────────────────────────────────────────────────────────────────────────────

function showKeyCaptureDialog(parentWindow, onCapture) {
    const dialog = new Gtk.Window({
        title: 'Press a key',
        modal: true,
        transient_for: parentWindow,
        default_width: 360,
        default_height: 200,
        resizable: false,
        destroy_with_parent: true,
    });

    const box = new Gtk.Box({
        orientation: Gtk.Orientation.VERTICAL,
        spacing: 16,
        margin_top: 36,
        margin_bottom: 36,
        margin_start: 36,
        margin_end: 36,
        halign: Gtk.Align.CENTER,
        valign: Gtk.Align.CENTER,
    });

    box.append(new Gtk.Image({
        icon_name: 'input-keyboard-symbolic',
        pixel_size: 48,
        opacity: 0.55,
    }));

    box.append(new Gtk.Label({
        label: '<span size="large"><b>Press any key or mouse button</b></span>',
        use_markup: true,
        justify: Gtk.Justification.CENTER,
    }));

    box.append(new Gtk.Label({
        label: 'Works with any keyboard, mouse, or controller\nPress <b>Escape</b> to cancel',
        use_markup: true,
        justify: Gtk.Justification.CENTER,
        opacity: 0.55,
    }));

    dialog.set_child(box);

    const controller = new Gtk.EventControllerKey();
    dialog.add_controller(controller);

    controller.connect('key-pressed', (_ctrl, _keyval, keycode, _state) => {
        const evdevCode = keycode - 8;
        if (evdevCode === 1) { // ESC → cancel
            dialog.close();
            return true;
        }
        onCapture(evdevCode);
        dialog.close();
        return true;
    });

    // Capture mouse buttons as well as keyboard keys.
    const mouse = new Gtk.GestureClick();
    mouse.set_button(0);
    mouse.set_propagation_phase(Gtk.PropagationPhase.CAPTURE);

    mouse.connect('pressed', (gesture, _nPress, _x, _y) => {
        const button = gesture.get_current_button();

        // GTK button numbers → Linux evdev button codes.
        const buttonCodes = {
            1: 272, // Left
            2: 274, // Middle
            3: 273, // Right
            8: 275, // Side button (back, if reported as GTK 8)
            9: 276, // Extra button (forward, confirmed on your system)
        };

        const evdevCode = buttonCodes[button];
        if (evdevCode === undefined)
            return;

        onCapture(evdevCode);
        dialog.close();
    });

    dialog.add_controller(mouse);

    dialog.present();
}

// ─────────────────────────────────────────────────────────────────────────────
// Extension preferences
// ─────────────────────────────────────────────────────────────────────────────

export default class DiscordPttPreferences extends ExtensionPreferences {

    fillPreferencesWindow(window) {
        const settings = this.getSettings();

        const page = new Adw.PreferencesPage({
            title: 'General',
            icon_name: 'preferences-system-symbolic',
        });
        window.add(page);

        // ── Group: Push-to-Talk Key ───────────────────────────────────────
        const keyGroup = new Adw.PreferencesGroup({
            title: 'Push-to-Talk Key',
            description: 'Detected from any connected keyboard, mouse, or controller',
        });
        page.add(keyGroup);

        const currentCode = settings.get_int('ptt-key-code');
        const keyRow = new Adw.ActionRow({
            title: 'PTT Key',
            subtitle: formatKeySubtitle(currentCode),
            activatable: false,
        });

        const captureBtn = new Gtk.Button({
            label: 'Capture Key',
            valign: Gtk.Align.CENTER,
            css_classes: ['suggested-action'],
        });

        captureBtn.connect('clicked', () => {
            showKeyCaptureDialog(window, (evdevCode) => {
                settings.set_int('ptt-key-code', evdevCode);
            });
        });

        keyRow.add_suffix(captureBtn);
        keyGroup.add(keyRow);

        settings.connect('changed::ptt-key-code', () => {
            keyRow.subtitle = formatKeySubtitle(settings.get_int('ptt-key-code'));
        });

        // ── Group: Control ────────────────────────────────────────────────
        const controlGroup = new Adw.PreferencesGroup({
            title: 'Control',
        });
        page.add(controlGroup);

        const activeRow = new Adw.SwitchRow({
            title: 'Enable PTT',
            subtitle: 'Start the push-to-talk daemon',
        });
        settings.bind('is-active', activeRow, 'active', Gio.SettingsBindFlags.DEFAULT);
        controlGroup.add(activeRow);

        const soundRow = new Adw.SwitchRow({
            title: 'PTT Click Sound',
            subtitle: 'Play a click sound on key press and release',
        });
        settings.bind('ptt-sound-enabled', soundRow, 'active', Gio.SettingsBindFlags.DEFAULT);
        controlGroup.add(soundRow);
    }
}
