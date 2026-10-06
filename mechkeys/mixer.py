"""Low-latency polyphonic mixer on top of a PortAudio output stream.

The stream pauses itself after a few seconds of silence, so an idle MechKeys
costs no CPU and lets the audio device sleep. Resuming takes about 1 ms.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

from .audiodevice import ensure_com
from .dsp import soft_clip

log = logging.getLogger(__name__)

SAMPLE_RATE = 44100
CHANNELS = 2
MAX_VOICES = 24
IDLE_PAUSE_S = 5.0


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
    """Plays overlapping one-shot sounds. ``play`` is safe from any thread.

    Sounds are dropped, not queued, while no stream is open (audio down, or being
    switched to another device), so nothing stale plays in a burst afterwards.
    """

    def __init__(self, channels: int = CHANNELS):
        self.device, self.samplerate = pick_output()
        self.channels = channels
        self.master = 0.7
        self._voices: list[Voice] = []
        self._lock = threading.Lock()           # guards voices and pause state
        self._stream_lock = threading.RLock()   # serialises everything that opens/closes/resumes the stream
        self._stream = None
        self._idle_frames = 0
        self._paused = False
        self.degraded = False   # running on the slow fallback path although a fast one exists
        self.last_error: str | None = None

    # -- stream lifecycle ------------------------------------------------- #
    def start(self) -> bool:
        """Open the preferred device, falling back to the system default."""
        with self._stream_lock:
            self.stop()
            ensure_com()
            for device in dict.fromkeys([self.device, None]):
                try:
                    self._stream = self._open(device)
                except Exception as exc:  # PortAudio raises a variety of error types
                    self.last_error = str(exc)
                    log.warning("Audio output on device %s failed: %s", device, exc)
                    continue
                self.last_error = None
                self.degraded = device is None and self.device is not None
                if self.degraded:
                    log.warning("Using the slower default audio path (about 100 ms delay)")
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

    def reopen_devices(self) -> None:
        """Close the stream and re-scan the audio devices, ready for ``start``.

        PortAudio only learns about newly plugged-in devices, and renumbers the rest,
        when it is re-initialised. That must happen on the thread that first
        initialised it (the main thread), because COM setup is per thread. The sample
        rate follows the new default device, so callers must reload sounds if it
        changed.
        """
        with self._stream_lock:
            self.stop()
            try:
                sd._terminate()
                sd._initialize()
            except Exception as exc:
                log.warning("PortAudio re-init failed: %s", exc)
            self.device, self.samplerate = pick_output()

    def stop(self) -> None:
        with self._stream_lock:
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

    def needs_restart(self) -> bool:
        """True when a stream exists but has died on its own (device unplugged, driver reset).

        A stream that paused itself after idling is healthy, not dead."""
        stream = self._stream
        if stream is None or self._paused:
            return False
        try:
            return not stream.active
        except Exception:
            return True

    # -- playback --------------------------------------------------------- #
    def play(self, samples: np.ndarray, gain: float = 1.0) -> None:
        if self._stream is None:
            return
        with self._lock:
            if len(self._voices) >= MAX_VOICES:
                self._voices = self._voices[1:]
            self._voices = [*self._voices, Voice(samples, gain)]
            self._idle_frames = 0
            needs_resume = self._paused
        if needs_resume:
            self._resume()

    def _resume(self) -> None:
        if not self._stream_lock.acquire(blocking=False):
            return  # the stream is being reopened; this one sound is not worth waiting for
        try:
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
        finally:
            self._stream_lock.release()

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
