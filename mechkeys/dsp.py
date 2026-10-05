"""Small sample-processing helpers shared by the pack loader and the mixer."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

LIMIT_KNEE = 0.8          # below this the limiter is transparent
RELEASE_PITCH = 1.2       # upstrokes sound brighter...
RELEASE_KEEP = 0.6        # ...shorter...
RELEASE_GAIN = 0.6        # ...and quieter than the downstroke
RELEASE_FADE = 0.4        # fraction of the kept tail that fades out


def vary_pitch(samples: np.ndarray, ratio: float) -> np.ndarray:
    """Resample so playback is ``ratio`` times faster (higher pitch when > 1)."""
    if abs(ratio - 1.0) < 1e-3 or len(samples) < 2:
        return samples
    new_len = max(1, int(len(samples) / ratio))
    src_pos = np.minimum(np.arange(new_len) * ratio, len(samples) - 1)
    src_idx = np.arange(len(samples))
    cols = [np.interp(src_pos, src_idx, samples[:, c]) for c in range(samples.shape[1])]
    return np.column_stack(cols).astype(np.float32)


def soft_clip(block: np.ndarray) -> np.ndarray:
    """Limit peaks above the knee smoothly into (-1, 1) instead of hard clipping."""
    over = np.abs(block) > LIMIT_KNEE
    if not over.any():
        return block
    headroom = 1.0 - LIMIT_KNEE
    excess = (np.abs(block[over]) - LIMIT_KNEE) / headroom
    limited = block.copy()
    limited[over] = np.sign(block[over]) * (LIMIT_KNEE + headroom * np.tanh(excess))
    return limited


MOUSE_CLICK_S = 0.06


@dataclass(frozen=True)
class MouseStyle:
    """Recipe for a synthesized mouse click."""
    name: str
    resonances: tuple[tuple[float, float, float], ...]  # (frequency Hz, decay s, level)
    noise: float = 0.35          # level of the high-passed transient "tick"
    noise_decay: float = 0.0007
    down_peak: float = 0.16      # keyboard samples peak around 0.1-0.3
    up_peak: float = 0.09
    up_pitch: float = 1.15
    bounce_s: float = 0.0016     # micro-switch contacts bounce once (0 = no bounce)
    sweep: float = 0.0           # >0: pitch glides upward by this factor (bubble pop)


MOUSE_STYLES = {
    "classic": MouseStyle("Classic micro-switch",
                          ((3100, 0.0035, 0.55), (5400, 0.0018, 0.30), (1250, 0.0060, 0.25))),
    "crisp": MouseStyle("Crisp gaming",
                        ((4200, 0.0022, 0.6), (7000, 0.0012, 0.35), (1800, 0.003, 0.2)),
                        noise=0.5, down_peak=0.18, up_peak=0.11, bounce_s=0.0),
    "soft": MouseStyle("Soft / silent switch", ((900, 0.004, 0.6), (1600, 0.003, 0.3)),
                       noise=0.08, down_peak=0.07, up_peak=0.035, up_pitch=1.05, bounce_s=0.0),
    "retro": MouseStyle("Retro clacky",
                        ((2200, 0.006, 0.55), (3800, 0.004, 0.3), (700, 0.012, 0.35)),
                        down_peak=0.17, up_peak=0.11, bounce_s=0.003),
    "bubble": MouseStyle("Bubble pop", ((600, 0.02, 1.0),), noise=0.05,
                         down_peak=0.2, up_peak=0.1, up_pitch=1.4, bounce_s=0.0, sweep=2.6),
}
DEFAULT_MOUSE_STYLE = "classic"


def _mouse_tick(rate: int, style: MouseStyle, pitch: float, peak: float, bounce: bool, seed: int) -> np.ndarray:
    t = np.arange(int(rate * MOUSE_CLICK_S)) / rate
    if style.sweep:
        bend = 1 + (style.sweep - 1) * (1 - np.exp(-t / 0.008))
        phases = [2 * np.pi * np.cumsum(f * pitch * bend) / rate for f, _, _ in style.resonances]
    else:
        phases = [2 * np.pi * f * pitch * t for f, _, _ in style.resonances]
    body = sum(level * np.sin(phase) * np.exp(-t / decay)
               for phase, (_, decay, level) in zip(phases, style.resonances))
    noise = np.random.default_rng(seed).standard_normal(len(t)) * np.exp(-t / style.noise_decay)
    tick = body + style.noise * np.diff(noise, prepend=0.0)  # differencing = crude high-pass: crisp
    if bounce and style.bounce_s:
        shift = int(rate * style.bounce_s)
        tick[shift:] += 0.35 * tick[: len(tick) - shift]
    fade = int(rate * 0.004)
    tick[-fade:] *= np.linspace(1, 0, fade)
    tick *= peak / np.abs(tick).max()
    return np.column_stack([tick, tick]).astype(np.float32)


def make_mouse_clicks(rate: int, channels: int = 2, style: str = DEFAULT_MOUSE_STYLE) -> tuple[np.ndarray, np.ndarray]:
    """Synthesize (press, release) mouse clicks in the given style; no sample files needed."""
    recipe = MOUSE_STYLES.get(style, MOUSE_STYLES[DEFAULT_MOUSE_STYLE])
    down = _mouse_tick(rate, recipe, 1.0, recipe.down_peak, bounce=True, seed=7)
    up = _mouse_tick(rate, recipe, recipe.up_pitch, recipe.up_peak, bounce=False, seed=11)
    if channels == 1:
        return down[:, :1].copy(), up[:, :1].copy()
    return down, up

def make_release(samples: np.ndarray) -> np.ndarray:
    """Derive a key-release sound from a keypress sample."""
    pitched = vary_pitch(samples, RELEASE_PITCH)
    keep = max(1, int(len(pitched) * RELEASE_KEEP))
    fade = max(1, int(keep * RELEASE_FADE))
    envelope = np.ones(keep, np.float32)
    envelope[-fade:] = np.linspace(1.0, 0.0, fade, dtype=np.float32)
    return (pitched[:keep] * envelope[:, None] * RELEASE_GAIN).astype(np.float32)
