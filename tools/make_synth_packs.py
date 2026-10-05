"""Generate the synthesized sound packs (typewriter, bubble, etc.) into sounds/.

Each pack is written in the Mechvibes v2 layout - press/ and release/ WAV files
plus config.json - so the app loads them exactly like recorded packs.

Usage: python tools/make_synth_packs.py
"""

from __future__ import annotations

import json
import shutil
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

RATE = 44100
VARIANTS = 5
DEST = Path(__file__).resolve().parent.parent / "sounds"
SPECIAL_KEYS = {"BACKSPACE": 14, "ENTER": 28, "SPACE": 57}


# --------------------------------------------------------------------------- #
# Building blocks
# --------------------------------------------------------------------------- #

def timeline(seconds: float) -> np.ndarray:
    return np.arange(int(RATE * seconds)) / RATE


def ring(t: np.ndarray, freq: float, decay: float, level: float = 1.0) -> np.ndarray:
    """A struck resonance: sine with exponential decay."""
    return level * np.sin(2 * np.pi * freq * t) * np.exp(-t / decay)


def burst(t: np.ndarray, decay: float, seed: int, bright: bool = True) -> np.ndarray:
    noise = np.random.default_rng(seed).standard_normal(len(t)) * np.exp(-t / decay)
    return np.diff(noise, prepend=0.0) if bright else noise


def lowpass(signal: np.ndarray, cutoff: float) -> np.ndarray:
    alpha = 1 - np.exp(-2 * np.pi * cutoff / RATE)
    out = np.empty_like(signal)
    acc = 0.0
    for i, x in enumerate(signal):
        acc += alpha * (x - acc)
        out[i] = acc
    return out


def sweep(t: np.ndarray, start: float, end: float, decay: float) -> np.ndarray:
    """Sine gliding from ``start`` to ``end`` Hz: the 'pop' of a bubble."""
    freq = end + (start - end) * np.exp(-t / (decay * 0.6))
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    return np.sin(phase) * np.exp(-t / decay)


def square(t: np.ndarray, freq: float, decay: float) -> np.ndarray:
    return np.sign(np.sin(2 * np.pi * freq * t)) * np.exp(-t / decay)


def delayed(signal: np.ndarray, seconds: float, length: int) -> np.ndarray:
    out = np.zeros(length)
    shift = int(RATE * seconds)
    take = max(0, min(len(signal), length - shift))
    out[shift:shift + take] = signal[:take]
    return out


def normalize(signal: np.ndarray, peak: float) -> np.ndarray:
    fade = min(len(signal), int(RATE * 0.004))
    shaped = signal.copy()
    shaped[-fade:] *= np.linspace(1, 0, fade)  # no click at the end
    return shaped * (peak / max(1e-9, np.abs(shaped).max()))


# --------------------------------------------------------------------------- #
# Styles: each returns (press, release) for a variant index and key kind
# --------------------------------------------------------------------------- #

Kind = str  # "GENERIC" | "SPACE" | "ENTER" | "BACKSPACE"


def typewriter(i: int, kind: Kind) -> tuple[np.ndarray, np.ndarray]:
    p = 1 + 0.035 * (i - 2)
    t = timeline(0.16 if kind != "ENTER" else 0.9)
    clack = (ring(t, 2300 * p, 0.012, 0.6) + ring(t, 4700 * p, 0.006, 0.35)
             + ring(t, 160 * p, 0.03, 0.5) + 0.5 * burst(t, 0.0015, 10 + i))
    clack += 0.45 * delayed(ring(t, 1900 * p, 0.008) + burst(t, 0.001, 30 + i), 0.018, len(t))  # typebar hits platen
    if kind == "SPACE":
        clack = ring(t, 120, 0.04, 0.9) + ring(t, 900, 0.02, 0.4) + 0.4 * burst(t, 0.003, 50, bright=False)
    if kind == "ENTER":  # carriage-return bell
        clack += ring(t, 1760, 0.35, 0.55) + ring(t, 3520, 0.18, 0.25)
    up_t = timeline(0.06)
    release = ring(up_t, 3100 * p, 0.004, 0.5) + 0.3 * burst(up_t, 0.0008, 70 + i)
    return normalize(clack, 0.32 if kind == "GENERIC" else 0.36), normalize(release, 0.1)


def bubble(i: int, kind: Kind) -> tuple[np.ndarray, np.ndarray]:
    base = {"GENERIC": 520 + 70 * i, "SPACE": 300, "ENTER": 380, "BACKSPACE": 460}[kind]
    t = timeline(0.09)
    press = sweep(t, base * 0.55, base * 1.7, 0.022) + 0.15 * burst(t, 0.0006, 80 + i)
    up_t = timeline(0.05)
    release = sweep(up_t, base * 1.1, base * 2.4, 0.01)
    return normalize(press, 0.3), normalize(release, 0.12)


def laptop(i: int, kind: Kind) -> tuple[np.ndarray, np.ndarray]:
    p = 1 + 0.04 * (i - 2)
    t = timeline(0.07 if kind == "GENERIC" else 0.1)
    press = lowpass(burst(t, 0.004, 90 + i, bright=False), 2200) * 3 + ring(t, 520 * p, 0.008, 0.6)
    if kind == "SPACE":
        press += ring(t, 260, 0.02, 0.7) + 0.6 * delayed(ring(t, 340, 0.01), 0.006, len(t))
    up_t = timeline(0.04)
    release = lowpass(burst(up_t, 0.002, 110 + i, bright=False), 1800) * 3
    return normalize(press, 0.2), normalize(release, 0.06)


def thock(i: int, kind: Kind) -> tuple[np.ndarray, np.ndarray]:
    p = 1 + 0.03 * (i - 2)
    low = {"GENERIC": 330, "SPACE": 190, "ENTER": 240, "BACKSPACE": 260}[kind]
    t = timeline(0.14)
    press = (ring(t, low * p, 0.022, 1.0) + ring(t, low * 2.7 * p, 0.009, 0.35)
             + 0.6 * lowpass(burst(t, 0.002, 130 + i, bright=False), 3000))
    up_t = timeline(0.06)
    release = ring(up_t, low * 1.9 * p, 0.008, 0.6) + 0.3 * lowpass(burst(up_t, 0.001, 150 + i, False), 4000)
    return normalize(press, 0.34), normalize(release, 0.1)


def arcade(i: int, kind: Kind) -> tuple[np.ndarray, np.ndarray]:
    notes = (659.3, 784.0, 880.0, 987.8, 1046.5)
    freq = {"GENERIC": notes[i % len(notes)], "SPACE": 330.0, "ENTER": 1318.5, "BACKSPACE": 440.0}[kind]
    t = timeline(0.07 if kind != "ENTER" else 0.14)
    press = square(t, freq, 0.025)
    if kind == "ENTER":
        press += delayed(square(t, freq * 1.5, 0.03), 0.05, len(t))
    up_t = timeline(0.03)
    release = square(up_t, freq * 2, 0.008)
    return normalize(lowpass(press, 6000), 0.13), normalize(lowpass(release, 6000), 0.04)


@dataclass(frozen=True)
class Style:
    pack_id: str
    name: str
    make: Callable[[int, Kind], tuple[np.ndarray, np.ndarray]]


STYLES = (
    Style("synth-typewriter", "Typewriter (synth)", typewriter),
    Style("synth-bubble", "Bubble Pop (synth)", bubble),
    Style("synth-laptop", "Laptop Keyboard (synth)", laptop),
    Style("synth-thock", "Deep Thock (synth)", thock),
    Style("synth-arcade", "Arcade Blips (synth)", arcade),
)


# --------------------------------------------------------------------------- #
# Writing packs
# --------------------------------------------------------------------------- #

def write_wav(path: Path, signal: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(signal, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm.tobytes())


def build(style: Style) -> Path:
    folder = DEST / style.pack_id
    shutil.rmtree(folder, ignore_errors=True)
    defines: dict[str, str] = {}
    for i in range(VARIANTS):
        press, release = style.make(i, "GENERIC")
        write_wav(folder / "press" / f"GENERIC_R{i}.wav", press)
        if i == 0:
            write_wav(folder / "release" / "GENERIC.wav", release)
    for kind, code in SPECIAL_KEYS.items():
        press, release = style.make(2, kind)
        write_wav(folder / "press" / f"{kind}.wav", press)
        write_wav(folder / "release" / f"{kind}.wav", release)
        defines[str(code)] = f"press/{kind}.wav"
        defines[f"{code}-up"] = f"release/{kind}.wav"
    config = {
        "id": style.pack_id, "name": style.name, "key_define_type": "multi", "version": 2,
        "sound": f"press/GENERIC_R{{0-{VARIANTS - 1}}}.wav", "soundup": "release/GENERIC.wav",
        "defines": defines,
    }
    (folder / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return folder


if __name__ == "__main__":
    for style in STYLES:
        print("wrote", build(style).name)
