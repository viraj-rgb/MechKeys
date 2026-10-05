"""Low-latency polyphonic mixer on top of a PortAudio output stream.

The stream pauses itself after a few seconds of silence, so an idle MechKeys
costs no CPU and lets the audio device sleep. Resuming takes about 1 ms.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

from .dsp import soft_clip

log = logging.getLogger(__name__)

SAMPLE_RATE = 44100
CHANNELS = 2
MAX_VOICES = 24
IDLE_PAUSE_S = 5.0
COINIT_MULTITHREADED = 0x0

_com_threads = threading.local()


def ensure_com() -> None:
    """WASAPI needs COM on whichever thread starts a stream; worker threads lack it."""
    if getattr(_com_threads, "ready", False):
        return
    # S_OK, S_FALSE (already on) and RPC_E_CHANGED_MODE (on, other model) all leave COM usable.
    ctypes.windll.ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
    _com_threads.ready = True


@dataclass
class Voice:
    samples: np.ndarray
    gain: float
    pos: int = 0


def mix_block(voices: list[Voice], frames: int, channels: int, master: float) -> tuple[np.ndarray, list[Voice]]:
    """Sum one block of audio; returns the block and the voices still playing."""
    out = np.zeros((frames, channels), dtype=np.float32)
    alive = []
    for voice in voices:
        chunk = voice.samples[voice.pos:voice.pos + frames]
        out[: len(chunk)] += chunk * voice.gain
        voice.pos += len(chunk)
        if voice.pos < len(voice.samples):
            alive.append(voice)
    out *= master
    return soft_clip(out), alive


def pick_output() -> tuple[int | None, int]:
    """Prefer the WASAPI default output: ~10 ms latency versus ~100 ms on MME.

    WASAPI shared mode only accepts the device's own mix rate, so return it too.
    """
    try:
        for api in sd.query_hostapis():
            device = api.get("default_output_device", -1)
            if "WASAPI" in api["name"] and device >= 0:
                return device, int(sd.query_devices(device)["default_samplerate"])
    except Exception as exc:  # PortAudio raises a variety of error types
        log.warning("Could not query WASAPI devices: %s", exc)
    return None, SAMPLE_RATE


class Mixer:
    """Plays overlapping one-shot sounds. ``play`` is safe from any thread."""

    def __init__(self, channels: int = CHANNELS):
        self.device, self.samplerate = pick_output()
        self.channels = channels
        self.master = 0.7
        self._voices: list[Voice] = []
        self._lock = threading.Lock()          # guards voices and pause state
        self._resume_lock = threading.Lock()   # serialises stream restarts
        self._stream = None
        self._idle_frames = 0
        self._paused = False
        self.last_error: str | None = None

    # -- stream lifecycle ------------------------------------------------- #
    def start(self) -> bool:
        """Open the preferred device, falling back to the system default."""
        self.stop()
        for device in dict.fromkeys([self.device, None]):
            try:
                self._stream = self._open(device)
            except Exception as exc:  # PortAudio raises a variety of error types
                self.last_error = str(exc)
                log.warning("Audio output on device %s failed: %s", device, exc)
                continue
            self.last_error = None
            return True
        log.error("No audio output could be started")
        return False

    def _open(self, device: int | None):
        stream = sd.OutputStream(
            device=device,
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="float32",
            latency="low",
            callback=self._callback,
        )
        stream.start()
        name = sd.query_devices(stream.device)["name"]
        log.info("Audio started on '%s' at %d Hz (latency %.1f ms)", name, self.samplerate,
                 stream.latency * 1000)
        return stream

    def restart(self) -> bool:
        """Reopen on the current default device (after plugging in headphones, etc.).

        The sample rate may change; callers must reload sounds if it does.
        """
        self.stop()
        try:
            sd._terminate()
            sd._initialize()
        except Exception as exc:
            log.warning("PortAudio re-init failed: %s", exc)
        self.device, self.samplerate = pick_output()
        return self.start()

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception as exc:
            log.warning("Closing audio stream failed: %s", exc)
        with self._lock:
            self._voices = []
            self._paused = False
            self._idle_frames = 0

    @property
    def running(self) -> bool:
        return self._stream is not None

    @property
    def paused(self) -> bool:
        return self._paused

    # -- playback --------------------------------------------------------- #
    def play(self, samples: np.ndarray, gain: float = 1.0) -> None:
        with self._lock:
            if len(self._voices) >= MAX_VOICES:
                self._voices = self._voices[1:]
            self._voices = [*self._voices, Voice(samples, gain)]
            self._idle_frames = 0
            needs_resume = self._paused
        if needs_resume:
            self._resume()

    def _resume(self) -> None:
        with self._resume_lock:
            stream = self._stream
            if not self._paused or stream is None:
                return
            try:
                ensure_com()
                stream.stop()   # waits for the self-stopped stream to finish draining
                stream.start()
            except Exception as exc:  # PortAudio raises a variety of error types
                log.warning("Resuming audio failed: %s", exc)
                return
            with self._lock:
                self._paused = False

    def _callback(self, outdata, frames, _time, status) -> None:
        if status.output_underflow:
            log.debug("Audio underflow")
        with self._lock:
            voices = self._voices
            if not voices:  # idle: most callbacks, so skip all allocation
                outdata.fill(0)
                self._idle_frames += frames
                if self._idle_frames >= self.samplerate * IDLE_PAUSE_S:
                    self._paused = True
                    raise sd.CallbackStop
                return
            self._idle_frames = 0
            block, alive = mix_block(voices, frames, self.channels, self.master)
            self._voices = alive
        outdata[:] = block
