"""Small Windows integrations: autostart entry, single-instance guard, DPI."""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import winreg
from ctypes import wintypes
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "MechKeys"
MUTEX_NAME = "Local\\MechKeys.SingleInstance"
SHOW_EVENT_NAME = "Local\\MechKeys.ShowWindow"
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenEventW.restype = wintypes.HANDLE
_kernel32.SetEvent.argtypes = [wintypes.HANDLE]
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


# -- autostart ------------------------------------------------------------- #

def launch_command() -> str:
    """Command line that starts this app hidden in the tray."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    package_root = Path(__file__).resolve().parent.parent
    return f'"{interpreter}" "{package_root / "MechKeys.pyw"}" --minimized'


def set_autostart(enabled: bool) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, launch_command())
            return
        try:
            winreg.DeleteValue(key, RUN_VALUE)
        except FileNotFoundError:
            pass


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
            return True
    except FileNotFoundError:
        return False


# -- single instance ------------------------------------------------------- #

class SingleInstance:
    """Holds a named mutex; a second launch pings the first to show itself."""

    def __init__(self):
        self._mutex = _kernel32.CreateMutexW(None, False, MUTEX_NAME)
        self.is_primary = ctypes.get_last_error() != ERROR_ALREADY_EXISTS
        self._event = _kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME) if self.is_primary else None

    def notify_primary(self) -> None:
        handle = _kernel32.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False, SHOW_EVENT_NAME)
        if handle:
            _kernel32.SetEvent(handle)
            _kernel32.CloseHandle(handle)

    def listen(self, on_show: Callable[[], None]) -> None:
        if not self._event:
            return

        def wait_loop():
            while _kernel32.WaitForSingleObject(self._event, INFINITE) == WAIT_OBJECT_0:
                on_show()

        threading.Thread(target=wait_loop, name="instance-listener", daemon=True).start()


# -- display --------------------------------------------------------------- #

def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            log.debug("DPI awareness unavailable")
