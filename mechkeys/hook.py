"""System-wide keyboard listener using a Win32 low-level keyboard hook.

The hook only observes keys - it never blocks or alters them. The callback
must return quickly (Windows silently drops slow hooks), so it just hands each
event to a consumer callable which should queue it.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes
from typing import Callable, NamedTuple

log = logging.getLogger(__name__)

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

_DOWN_MESSAGES = frozenset({WM_KEYDOWN, WM_SYSKEYDOWN})
_UP_MESSAGES = frozenset({WM_KEYUP, WM_SYSKEYUP})

ULONG_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KeyEvent(NamedTuple):
    vk: int
    scan: int
    flags: int
    is_down: bool


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
_user32.SetWindowsHookExW.restype = wintypes.HHOOK
_user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
_user32.CallNextHookEx.restype = LRESULT
_user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
_user32.UnhookWindowsHookEx.restype = wintypes.BOOL
_user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
_user32.GetMessageW.restype = wintypes.BOOL
_user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostThreadMessageW.restype = wintypes.BOOL
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class KeyboardHook:
    """Runs the hook and its message loop on a dedicated daemon thread."""

    def __init__(self, on_event: Callable[[KeyEvent], None]):
        self._on_event = on_event
        self._proc = HOOKPROC(self._hook_proc)  # keep a reference: ctypes won't
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self.error: str | None = None

    def start(self) -> bool:
        self._thread = threading.Thread(target=self._run, name="keyboard-hook", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)
        return self.error is None

    def stop(self) -> None:
        if self._thread and self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(timeout=2)
        self._thread = None

    def _hook_proc(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code == 0 and (w_param in _DOWN_MESSAGES or w_param in _UP_MESSAGES):
            info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            try:
                self._on_event(KeyEvent(info.vkCode, info.scanCode, info.flags, w_param in _DOWN_MESSAGES))
            except Exception:  # never let an exception escape into Windows
                log.exception("Key event consumer failed")
        return _user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _run(self) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()
        hook = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, _kernel32.GetModuleHandleW(None), 0)
        if not hook:
            self.error = f"SetWindowsHookEx failed (error {ctypes.get_last_error()})"
            log.error(self.error)
            self._ready.set()
            return
        log.info("Keyboard hook installed")
        self._ready.set()

        msg = wintypes.MSG()
        try:
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                pass
        finally:
            _user32.UnhookWindowsHookEx(hook)
