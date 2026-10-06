"""Notice when Windows switches its default audio output, so MechKeys can follow it.

A PortAudio/WASAPI stream stays on the device it was opened on. Without this,
switching from speakers to a headset (or plugging one in) leaves MechKeys playing
into the old device until it is restarted.

Windows is asked for the default output endpoint through COM (a couple of vtable
calls; no extra dependency) from a tiny background thread that wakes twice a second.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
import uuid
from ctypes import POINTER, WINFUNCTYPE, byref, c_long, c_void_p, wintypes
from typing import Callable, Protocol, Sequence

log = logging.getLogger(__name__)

COINIT_MULTITHREADED = 0
CLSCTX_ALL = 0x17
E_RENDER = 0
ROLES = (0, 1)                       # eConsole, eMultimedia: the two roles apps play through
STGM_READ = 0
VT_LPWSTR = 31

POLL_S = 0.5
SETTLE_S = 0.2                       # Windows can flip the default twice in a row; wait it out
RETRY_S = 5.0                        # when audio is down, try to bring it back this often...
RETRY_MAX_S = 30.0                   # ...backing off to this

_ole32 = ctypes.WinDLL("ole32")  # not OleDLL: failures come back as HRESULT numbers, not exceptions
_com_threads = threading.local()


def ensure_com() -> None:
    """WASAPI needs COM on whichever thread touches a stream; worker threads lack it."""
    if getattr(_com_threads, "ready", False):
        return
    # S_OK, S_FALSE (already on) and RPC_E_CHANGED_MODE (on, other model) all leave COM usable.
    _ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
    _com_threads.ready = True


class GUID(ctypes.Structure):
    _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]


def _guid(text: str) -> GUID:
    return GUID.from_buffer_copy(uuid.UUID(text).bytes_le)


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", wintypes.WORD), ("r1", wintypes.WORD), ("r2", wintypes.WORD), ("r3", wintypes.WORD),
                ("value", c_void_p), ("pad", c_void_p)]


_CLSID_ENUMERATOR = _guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
_IID_ENUMERATOR = _guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
_PKEY_FRIENDLY_NAME = PROPERTYKEY(_guid("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 14)


def _method(obj: c_void_p, index: int, *argtypes):
    """Bind vtable slot ``index`` of a COM object; the call returns a signed HRESULT."""
    vtable = ctypes.cast(ctypes.cast(obj, POINTER(c_void_p))[0], POINTER(c_void_p))
    return WINFUNCTYPE(c_long, c_void_p, *argtypes)(vtable[index])


def _release(obj: c_void_p) -> None:
    _method(obj, 2)(obj)


class EndpointReader:
    """Reads the default output endpoint. Create and use it on one thread only."""

    def __init__(self):
        ensure_com()
        enumerator = c_void_p()
        hr = _ole32.CoCreateInstance(byref(_CLSID_ENUMERATOR), None, CLSCTX_ALL, byref(_IID_ENUMERATOR),
                                     byref(enumerator))
        if hr < 0 or not enumerator:
            raise OSError(f"Cannot create the audio device enumerator (HRESULT {hr & 0xFFFFFFFF:#x})")
        self._enumerator = enumerator

    def _default_device(self, role: int) -> c_void_p | None:
        device = c_void_p()
        get_default = _method(self._enumerator, 4, wintypes.DWORD, wintypes.DWORD, POINTER(c_void_p))
        if get_default(self._enumerator, E_RENDER, role, byref(device)) < 0 or not device:
            return None  # no output device at all
        return device

    def default_ids(self) -> tuple[str | None, ...]:
        """Endpoint id for each watched role; None where no output device exists."""
        ids = []
        for role in ROLES:
            device = self._default_device(role)
            if device is None:
                ids.append(None)
                continue
            try:
                text = c_void_p()
                _method(device, 5, POINTER(c_void_p))(device, byref(text))
                ids.append(ctypes.wstring_at(text.value) if text else None)
                _ole32.CoTaskMemFree(text)
            finally:
                _release(device)
        return tuple(ids)

    def default_name(self) -> str:
        """Friendly name of the default output, e.g. 'Speakers (HyperX Cloud Stinger 2)'."""
        device = self._default_device(ROLES[0])
        if device is None:
            return "no output device"
        store = c_void_p()
        try:
            if _method(device, 4, wintypes.DWORD, POINTER(c_void_p))(device, STGM_READ, byref(store)) < 0:
                return "unknown device"
            value = PROPVARIANT()
            get_value = _method(store, 5, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))
            try:
                if get_value(store, byref(_PKEY_FRIENDLY_NAME), byref(value)) < 0 or value.vt != VT_LPWSTR:
                    return "unknown device"
                return ctypes.wstring_at(value.value)
            finally:
                _ole32.PropVariantClear(byref(value))
                _release(store)
        finally:
            _release(device)


class Reader(Protocol):
    def default_ids(self) -> Sequence[str | None]: ...
    def default_name(self) -> str: ...


class DeviceWatcher:
    """Calls ``on_change(reason)`` when the default output changes or audio has died.

    ``on_change`` runs on the watcher thread, so it should only hand work to another
    thread. While audio stays down it is called again after a growing delay, which also
    covers starting at login before the sound device is ready.
    """

    def __init__(self, on_change: Callable[[str], None], is_audio_dead: Callable[[], bool],
                 reader_factory: Callable[[], Reader] = EndpointReader, poll_s: float = POLL_S,
                 settle_s: float = SETTLE_S, retry_s: float = RETRY_S, retry_max_s: float = RETRY_MAX_S):
        self._on_change = on_change
        self._is_audio_dead = is_audio_dead
        self._reader_factory = reader_factory
        self._poll_s, self._settle_s = poll_s, settle_s
        self._retry_s, self._retry_max_s = retry_s, retry_max_s
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Begin watching; returns once the starting device has been recorded."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="audio-device-watcher", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2)

    def _open_reader(self) -> Reader | None:
        try:
            return self._reader_factory()
        except (OSError, AttributeError) as exc:
            log.error("Audio device changes will not be detected: %s", exc)
            return None

    @staticmethod
    def _read(reader: Reader | None, fallback):
        if reader is None:
            return fallback
        try:
            return tuple(reader.default_ids())
        except Exception as exc:  # a COM hiccup must never kill the watcher
            log.warning("Reading the default audio output failed: %s", exc)
            return fallback

    @staticmethod
    def _describe(reader: Reader | None) -> str:
        try:
            return reader.default_name() if reader is not None else "?"
        except Exception:
            return "?"

    def _run(self) -> None:
        reader = self._open_reader()
        last = self._read(reader, None)
        self._ready.set()
        retry_delay = self._retry_s
        retry_at = time.monotonic() + retry_delay
        while not self._stop.wait(self._poll_s):
            now = time.monotonic()
            current = self._read(reader, last)
            if current != last:
                if self._stop.wait(self._settle_s):
                    return
                settled = self._read(reader, last)
                if settled != last:
                    last = settled
                    log.info("Default audio output is now '%s'", self._describe(reader))
                    retry_delay = self._retry_s
                    retry_at = now + retry_delay
                    self._on_change("default output changed")
                continue
            if not self._is_audio_dead():
                retry_delay = self._retry_s
                retry_at = now + retry_delay
            elif now >= retry_at:
                retry_delay = min(retry_delay * 2, self._retry_max_s)
                retry_at = now + retry_delay
                self._on_change("audio stream stopped")
