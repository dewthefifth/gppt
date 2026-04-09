#!/usr/bin/env python3
"""
Generate PTT click sound files for the Discord PTT GNOME extension.

No external dependencies — uses Python stdlib only (wave, math, struct).

Generates two WAV files in the ../sounds/ directory (relative to this script):
  ptt_on.wav  — "key press" click: high-to-low frequency sweep + percussive envelope
  ptt_off.wav — "key release" click: low-to-high frequency sweep, slightly softer

Usage:
  python3 daemon/generate_sounds.py

You only need to run this once. After that the extension uses the WAV files directly.
"""

import math
import os
import struct
import wave

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_RATE = 44100  # Hz — standard CD quality, widely supported by paplay


# ─────────────────────────────────────────────────────────────────────────────
# Synthesis
# ─────────────────────────────────────────────────────────────────────────────

def make_click(
    freq_start: float,
    freq_end: float,
    duration_ms: int,
    amplitude: float = 0.55,
    attack_ms: int = 3,
    decay_exponent: float = 6.0,
) -> list[int]:
    """
    Synthesise a short percussive click sound.

    Parameters:
        freq_start     — Starting frequency in Hz
        freq_end       — Ending frequency in Hz (linear sweep)
        duration_ms    — Total duration in milliseconds
        amplitude      — Peak amplitude (0.0–1.0). Keep below ~0.7 to avoid clipping.
        attack_ms      — Duration of the linear amplitude rise (ms)
        decay_exponent — Controls how quickly the sound fades out.
                         Higher = faster decay. 6.0 ≈ Discord-like snap.

    Returns:
        List of signed 16-bit PCM samples.
    """
    n_total  = int(SAMPLE_RATE * duration_ms / 1000)
    n_attack = int(SAMPLE_RATE * attack_ms  / 1000)

    samples = []
    phase   = 0.0  # accumulated phase for continuous sine (avoids clicks from phase resets)

    for i in range(n_total):
        progress = i / n_total

        # ── Frequency sweep (linear interpolation) ──────────────────────
        freq  = freq_start + (freq_end - freq_start) * progress
        phase += 2.0 * math.pi * freq / SAMPLE_RATE
        wave_sample = math.sin(phase)

        # ── Amplitude envelope ────────────────────────────────────────────
        if i < n_attack:
            # Linear attack
            env = i / max(n_attack, 1)
        else:
            # Exponential decay
            decay_ratio = (i - n_attack) / max(n_total - n_attack, 1)
            env = math.exp(-decay_exponent * decay_ratio)

        samples.append(int(amplitude * env * wave_sample * 32767))

    return samples


def write_wav(path: str, samples: list[int]) -> None:
    """Write signed 16-bit mono PCM samples to a WAV file at the given path."""
    with wave.open(path, 'w') as wf:
        wf.setnchannels(1)           # mono
        wf.setsampwidth(2)           # 16-bit (2 bytes per sample)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(struct.pack(f'<{len(samples)}h', *samples))

    duration_ms = len(samples) * 1000 // SAMPLE_RATE
    file_kb     = os.path.getsize(path) // 1024
    print(f'  ✓  {path}  ({duration_ms} ms, {file_kb} KB)')


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    # Output goes to ../sounds/ relative to this script's location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sounds_dir = os.path.join(os.path.dirname(script_dir), 'sounds')
    os.makedirs(sounds_dir, exist_ok=True)

    print(f'Generating PTT sounds in: {sounds_dir}')
    print()

    # ── PTT ON — key press: high → low sweep ──────────────────────────────
    # Resembles the "click down" of a physical button.
    # 1100 Hz → 480 Hz, 75 ms, punchy attack + fast decay
    ptt_on_samples = make_click(
        freq_start     = 1100,
        freq_end       = 480,
        duration_ms    = 75,
        amplitude      = 0.55,
        attack_ms      = 3,
        decay_exponent = 6.5,
    )
    write_wav(os.path.join(sounds_dir, 'ptt_on.wav'), ptt_on_samples)

    # ── PTT OFF — key release: low → high sweep ───────────────────────────
    # Resembles the "click up" when releasing a button.
    # 480 Hz → 900 Hz, 55 ms, slightly softer and shorter
    ptt_off_samples = make_click(
        freq_start     = 480,
        freq_end       = 900,
        duration_ms    = 55,
        amplitude      = 0.45,
        attack_ms      = 2,
        decay_exponent = 7.0,
    )
    write_wav(os.path.join(sounds_dir, 'ptt_off.wav'), ptt_off_samples)

    print()
    print('Done! You can preview the sounds with:')
    print(f'  paplay {os.path.join(sounds_dir, "ptt_on.wav")}')
    print(f'  paplay {os.path.join(sounds_dir, "ptt_off.wav")}')
    print()
    print('To regenerate with different parameters, edit the values in this script.')


if __name__ == '__main__':
    main()
