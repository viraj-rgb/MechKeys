"""System-wide mouse-button listener using Win32 Raw Input.

Raw Input is used instead of a low-level mouse hook on purpose: a hook sits in
the path of every cursor movement, so any Python/GIL hiccup would make the
cursor stutter. Raw Input only delivers copies of events to our own hidden
window, so input is never delayed.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes
from typing import Callable, NamedTuple

log = logging.getLogger(__name__)

LEFT, RIGHT, MIDDLE, BACK, FORWARD = range(5)

WM_INPUT = 0x00FF
WM_QUIT = 0x0012
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RIDEV_INPUTSINK = 0x00000100
RIDEV_REMOVE = 0x00000001
HWND_MESSAGE = wintypes.HWND(-3)
USAGE_PAGE_GENERIC = 0x01
USAGE_MOUSE = 0x02
ERROR_CLASS_ALREADY_EXISTS = 1410
CLASS_NAME = "MechKeysRawMouse"

# usButtonFlags bit -> (button, is_down)
_BUTTON_BITS = (
    (0x0001, LEFT, True), (0x0002, LEFT, False),
    (0x0004, RIGHT, True), (0x0008, RIGHT, False),
    (0x0010, MIDDLE, True), (0x0020, MIDDLE, False),
    (0x0040, BACK, True), (0x0080, BACK, False),
    (0x0100, FORWARD, True), (0x0200, FORWARD, False),
)
_ANY_BUTTON = 0x03FF


class MouseEvent(NamedTuple):
    button: int
    is_down: bool


def decode_buttons(flags: int) -> list[MouseEvent]:
    """Translate RAWMOUSE.usButtonFlags into button events (moves give none)."""
    if not flags & _ANY_BUTTON:
        return []
    return [MouseEvent(button, down) for bit, button, down in _BUTTON_BITS if flags & bit]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]


class RAWMOUSE(ctypes.Structure):
    # In C the button fields sit in a ULONG-aligned union, hence the padding.
    _fields_ = [("usFlags", wintypes.USHORT), ("_pad", wintypes.USHORT),
                ("usButtonFlags", wintypes.USHORT), ("usButtonData", wintypes.USHORT),
                ("ulRawButtons", wintypes.ULONG), ("lLastX", wintypes.LONG),
                ("lLastY", wintypes.LONG), ("ulExtraInformation", wintypes.ULONG)]


class RAWINPUTMOUSE(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
                ("hIconSm", wintypes.HICON)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.DefWindowProcW.restype = LRESULT
_user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
_user32.RegisterClassExW.restype = wintypes.ATOM
_user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
_user32.RegisterRawInputDevices.restype = wintypes.BOOL
_user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID,
                                    ctypes.POINTER(wintypes.UINT), wintypes.UINT]
_user32.GetRawInputData.restype = wintypes.UINT
_user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
_user32.GetMessageW.restype = wintypes.BOOL
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class MouseListener:
    """Owns a hidden message-only window on a daemon thread; start/stop at will."""

    def __init__(self, on_event: Callable[[MouseEvent], None]):
        self._on_event = on_event
        self._wndproc = WNDPROC(self._window_proc)  # keep a reference: ctypes won't
        self._buffer = RAWINPUTMOUSE()
        self._buffer_size = wintypes.UINT(ctypes.sizeof(RAWINPUTMOUSE))
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.running:
            return True
        self.error = None
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="mouse-listener", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)
        return self.error is None

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        if self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        thread.join(timeout=2)
        self._thread = None
        self._thread_id = 0

    def _window_proc(self, hwnd, msg, w_param, l_param):
        if msg == WM_INPUT:
            try:
                self._read(l_param)
            except Exception:  # never let an exception escape into Windows
                log.exception("Raw mouse input failed")
        return _user32.DefWindowProcW(hwnd, msg, w_param, l_param)

    def _read(self, handle: int) -> None:
        size = wintypes.UINT(self._buffer_size.value)
        got = _user32.GetRawInputData(handle, RID_INPUT, ctypes.byref(self._buffer), ctypes.byref(size),
                                      ctypes.sizeof(RAWINPUTHEADER))
        if got == 0xFFFFFFFF or self._buffer.header.dwType != RIM_TYPEMOUSE:
            return
        flags = self._buffer.mouse.usButtonFlags
        if flags & _ANY_BUTTON:  # cheap exit for the flood of movement events
            for event in decode_buttons(flags):
                self._on_event(event)

    def _create_window(self) -> int:
        instance = _kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=self._wndproc,
                         hInstance=instance, lpszClassName=CLASS_NAME)
        if not _user32.RegisterClassExW(ctypes.byref(wc)):
            if ctypes.get_last_error() != ERROR_CLASS_ALREADY_EXISTS:
                raise OSError(f"RegisterClassEx failed ({ctypes.get_last_error()})")
        return _user32.CreateWindowExW(0, CLASS_NAME, "MechKeys mouse", 0, 0, 0, 0, 0,
                                       HWND_MESSAGE, None, instance, None)

    def _register(self, hwnd, flags: int) -> bool:
        device = RAWINPUTDEVICE(USAGE_PAGE_GENERIC, USAGE_MOUSE, flags, hwnd)
        return bool(_user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(RAWINPUTDEVICE)))

    def _run(self) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()
        try:
            hwnd = self._create_window()
        except OSError as exc:
            hwnd, self.error = None, str(exc)
        if not hwnd or not self._register(hwnd, RIDEV_INPUTSINK):
            self.error = self.error or f"Raw input registration failed ({ctypes.get_last_error()})"
            log.error(self.error)
            if hwnd:
                _user32.DestroyWindow(hwnd)
            self._ready.set()
            return
        log.info("Mouse listener started")
        self._ready.set()

        msg = wintypes.MSG()
        try:
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                _user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._register(None, RIDEV_REMOVE)
            _user32.DestroyWindow(hwnd)
            log.info("Mouse listener stopped")
