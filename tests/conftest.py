import sys
import wave
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BUNDLED_PACK = ROOT / "sounds" / "nk-cream"


def write_wav(path: Path, samples: np.ndarray, rate: int = 44100, width: int = 2) -> Path:
    """Write float samples shaped (n, channels) as an integer PCM WAV."""
    frames = np.atleast_2d(samples.T).T
    if width == 2:
        raw = (np.clip(frames, -1, 1) * 32767).astype("<i2").tobytes()
    elif width == 1:
        raw = (np.clip(frames, -1, 1) * 127 + 128).astype(np.uint8).tobytes()
    else:
        raise ValueError(width)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(frames.shape[1])
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(raw)
    return path


@pytest.fixture
def click() -> np.ndarray:
    """20 ms of silence then a 50 ms decaying click, stereo."""
    rate = 44100
    silence = np.zeros((int(rate * 0.02), 2), np.float32)
    t = np.arange(int(rate * 0.05)) / rate
    tone = (0.8 * np.sin(2 * np.pi * 900 * t) * np.exp(-t * 60)).astype(np.float32)
    return np.vstack([silence, np.column_stack([tone, tone])])
