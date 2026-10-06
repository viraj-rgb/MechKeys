"""Glue between the keyboard hook, the active sound pack and the mixer."""

from __future__ import annotations

import logging
import queue
import random
import threading
import time
from typing import Callable

from .audiodevice import DeviceWatcher
from .dsp import make_mouse_clicks, vary_pitch
from .hook import KeyboardHook, KeyEvent
from .keycodes import to_mechvibes_code
from .mixer import Mixer
from .mouse import BACK, FORWARD, LEFT, MIDDLE, RIGHT, MouseEvent, MouseListener
from .settings import MAX_VOLUME, Settings
from .soundpack import PackInfo, SoundPack, SoundPackError, load_pack

log = logging.getLogger(__name__)

VK_M = 0x4D
CTRL_VKS = frozenset({0x11, 0xA2, 0xA3})
ALT_VKS = frozenset({0x12, 0xA4, 0xA5})
MAX_FAST_PATH_RETRIES = 3     # tries to get back onto low-latency audio after falling back to the slow path
REPEAT_WINDOW_S = 1.1        # longer than Windows' max initial auto-repeat delay
GAIN_JITTER = (0.9, 1.0)
# Bigger buttons sound a little lower, like on a real mouse.
MOUSE_BUTTON_PITCH = {LEFT: 1.0, RIGHT: 0.94, MIDDLE: 0.86, BACK: 1.08, FORWARD: 1.1}
VOLUME_CURVE = 1.6           # perceptual taper; 100% = unity, 200% ~= 3x (+9.6 dB)


def volume_to_gain(volume: int) -> float:
    return (max(0, min(MAX_VOLUME, volume)) / 100.0) ** VOLUME_CURVE


class RepeatFilter:
    """Tells a fresh keypress apart from Windows auto-repeat of a held key."""

    def __init__(self, window_s: float = REPEAT_WINDOW_S):
        self._window = window_s
        self._held: dict[int, float] = {}

    def press(self, code: int, now: float) -> bool:
        """Record a key-down; returns True when it is an auto-repeat."""
        last = self._held.get(code)
        self._held = {**self._held, code: now}
        return last is not None and now - last < self._window

    def release(self, code: int) -> None:
        self._held = {k: v for k, v in self._held.items() if k != code}


class SoundEngine:
    def __init__(self, settings: Settings, on_mute_hotkey: Callable[[], None],
                 post: Callable[[Callable[[], None]], None] | None = None,
                 on_audio_state: Callable[[bool], None] | None = None):
        """`post` runs a callable on the main (UI) thread - audio devices must be re-scanned
        there. `on_audio_state(ok)` is told whether audio came back after a device change."""
        self._settings = settings
        self._on_mute_hotkey = on_mute_hotkey
        self._post = post or (lambda action: action())
        self._on_audio_state = on_audio_state or (lambda ok: None)
        self._restart_pending = False
        self._restart_lock = threading.Lock()
        self._fast_path_tries = 0
        self._pack: SoundPack | None = None
        self._events: queue.SimpleQueue[KeyEvent | MouseEvent | None] = queue.SimpleQueue()
        self._repeats = RepeatFilter()
        self._vks_down: frozenset[int] = frozenset()
        self._swallowed: frozenset[int] = frozenset()   # keys whose release stays silent
        self._rng = random.Random()
        self.mixer = Mixer()
        self.hook = KeyboardHook(self._events.put)
        self.mouse = MouseListener(self._events.put)
        self._watcher = DeviceWatcher(on_change=self._request_audio_restart,
                                      is_audio_dead=self._audio_needs_attention)
        self._mouse_style = settings.mouse_style
        self._mouse_clicks = self._make_clicks()
        self._started = False
        self._worker = threading.Thread(target=self._work, name="sound-worker", daemon=True)
        self.keystrokes = 0
        self.clicks = 0
        self.apply_settings(settings)

    # -- lifecycle -------------------------------------------------------- #
    def start(self) -> tuple[bool, bool]:
        """Start audio and the hook; returns (audio_ok, hook_ok)."""
        self._watcher.start()  # records the current output device before the stream opens on it
        audio_ok = self.mixer.start()
        self._worker.start()
        hook_ok = self.hook.start()
        self._started = True
        self._sync_mouse()
        return audio_ok, hook_ok

    def restart_audio(self) -> bool:
        """Reopen audio on the current default device. Call on the main thread.

        Sounds are resampled for the new device when its sample rate differs; until
        the stream is reopened, key presses are dropped rather than played too fast
        or too slow.
        """
        old_rate = self.mixer.samplerate
        self.mixer.reopen_devices()
        if self.mixer.samplerate != old_rate:
            self._mouse_clicks = self._make_clicks()
            if self._pack is not None:
                try:
                    self.load_pack(self._pack.info)
                except SoundPackError as exc:
                    log.error("Could not reload '%s' at %d Hz: %s", self._pack.info.name,
                              self.mixer.samplerate, exc)
                    self._pack = None  # silence beats sounds at the wrong pitch
        return self.mixer.start()

    def _audio_needs_attention(self) -> bool:
        """Watcher thread: is audio down, or stuck on the slow fallback path with retries left?"""
        mixer = self.mixer
        if not mixer.running or mixer.needs_restart():
            return True
        return mixer.degraded and self._fast_path_tries < MAX_FAST_PATH_RETRIES

    def _request_audio_restart(self, reason: str) -> None:
        """Watcher thread: ask the main thread to reopen audio (once, however often asked)."""
        with self._restart_lock:
            if self._restart_pending:
                return
            self._restart_pending = True
        if reason == "default output changed":
            self._fast_path_tries = 0
        log.info("Reopening audio: %s", reason)
        self._post(self._restart_audio_now)

    def _restart_audio_now(self) -> None:
        try:
            ok = self.restart_audio()
        except Exception:
            log.exception("Reopening audio failed")
            ok = False
        finally:
            with self._restart_lock:
                self._restart_pending = False
        self._fast_path_tries = self._fast_path_tries + 1 if self.mixer.degraded else 0
        self._on_audio_state(ok)
    def stop(self) -> None:
        self._started = False
        self._watcher.stop()
        self.mouse.stop()
        self.hook.stop()
        self._events.put(None)
        self.mixer.stop()

    # -- configuration ---------------------------------------------------- #
    def apply_settings(self, settings: Settings) -> None:
        self._settings = settings
        self.mixer.master = 0.0 if settings.muted else volume_to_gain(settings.volume)
        if settings.mouse_style != self._mouse_style:
            self._mouse_style = settings.mouse_style
            self._mouse_clicks = self._make_clicks()
        self._sync_mouse()

    def _make_clicks(self):
        return make_mouse_clicks(self.mixer.samplerate, self.mixer.channels, self._mouse_style)

    def _sync_mouse(self) -> None:
        """Run the mouse listener only while mouse sounds are on (it costs CPU per move)."""
        if not self._started:
            return
        if self._settings.mouse_sounds and not self.mouse.running:
            if not self.mouse.start():
                log.error("Mouse sounds unavailable: %s", self.mouse.error)
        elif not self._settings.mouse_sounds and self.mouse.running:
            self.mouse.stop()

    def load_pack(self, info: PackInfo) -> SoundPack:
        pack = load_pack(info, self.mixer.samplerate, self.mixer.channels)
        self._pack = pack
        log.info("Loaded pack '%s' (%d sounds)", info.name, len(pack.fallback))
        return pack

    @property
    def pack(self) -> SoundPack | None:
        return self._pack

    def preview(self) -> None:
        """Play a random key from the current pack (silent while muted)."""
        pack = self._pack
        if pack is None or not pack.fallback:
            return
        self._play(self._rng.choice(pack.fallback))

    def preview_mouse(self) -> None:
        """Play one left click in the current mouse style."""
        down, up = self._mouse_clicks
        scale = volume_to_gain(self._settings.mouse_volume)
        self._play(down, scale)
        self._play(up, scale)

    # -- event handling --------------------------------------------------- #
    def _work(self) -> None:
        while True:
            event = self._events.get()
            if event is None:
                return
            try:
                self._handle(event)
            except Exception:
                log.exception("Failed to handle key event %s", event)

    def _handle(self, event: KeyEvent | MouseEvent) -> None:
        if isinstance(event, MouseEvent):
            self._handle_mouse(event)
            return
        code = to_mechvibes_code(event.vk, event.scan, event.flags)
        if not event.is_down:
            self._repeats.release(code)
            self._vks_down = self._vks_down - {event.vk}
            if code in self._swallowed:
                self._swallowed = self._swallowed - {code}
                return
            self._play_release(code)
            return

        is_repeat = self._repeats.press(code, time.monotonic())
        self._vks_down = self._vks_down | {event.vk}
        settings = self._settings

        if settings.mute_hotkey and event.vk == VK_M and self._mute_chord_held():
            self._swallowed = self._swallowed | {code}
            if not is_repeat:
                self._on_mute_hotkey()
            return
        if is_repeat and settings.ignore_key_repeat:
            return

        self.keystrokes += 1
        if settings.muted or settings.volume == 0 or self._pack is None:
            return
        samples = self._pack.sound_for(code)
        if samples is not None:
            self._play(samples)

    def _handle_mouse(self, event: MouseEvent) -> None:
        if event.is_down:
            self.clicks += 1
        s = self._settings
        if s.muted or s.volume == 0 or not s.mouse_sounds or s.mouse_volume == 0:
            return
        down, up = self._mouse_clicks
        self._play(down if event.is_down else up, volume_to_gain(s.mouse_volume),
                   MOUSE_BUTTON_PITCH.get(event.button, 1.0))

    def _mute_chord_held(self) -> bool:
        return bool(self._vks_down & CTRL_VKS) and bool(self._vks_down & ALT_VKS)

    def _play_release(self, code: int) -> None:
        settings = self._settings
        if settings.muted or settings.volume == 0 or settings.release_volume == 0 or self._pack is None:
            return
        samples = self._pack.release_for(code)
        if samples is not None:
            self._play(samples, settings.release_volume / 100.0)

    def _play(self, samples, scale: float = 1.0, pitch: float = 1.0) -> None:
        spread = self._settings.pitch_variation / 100.0
        ratio = pitch * (1.0 + self._rng.uniform(-spread, spread)) if spread else pitch
        self.mixer.play(vary_pitch(samples, ratio), scale * self._rng.uniform(*GAIN_JITTER))
