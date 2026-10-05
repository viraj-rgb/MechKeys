"""Translate Windows low-level keyboard events into Mechvibes key codes.

Mechvibes sound packs key their ``defines`` by libuiohook virtual codes, which
are the PC/AT set-1 scan code with a prefix for extended keys:

* the four arrow keys use ``0xE000 | scan``
* every other extended key uses ``0x0E00 | scan``
* Pause and Num Lock share scan ``0x45`` and are told apart by virtual key
"""

LLKHF_EXTENDED = 0x01

VK_PAUSE = 0x13
VK_NUMLOCK = 0x90

_ARROW_SCANS = frozenset({0x48, 0x4B, 0x4D, 0x50})
_PAUSE_CODE = 0x0E45
_NUMLOCK_CODE = 0x45


def to_mechvibes_code(vk: int, scan: int, flags: int) -> int:
    """Return the Mechvibes/uiohook code for one keyboard hook event."""
    if vk == VK_PAUSE:
        return _PAUSE_CODE
    if vk == VK_NUMLOCK:
        return _NUMLOCK_CODE

    scan &= 0xFF
    if not flags & LLKHF_EXTENDED:
        return scan
    if scan in _ARROW_SCANS:
        return 0xE000 | scan
    return 0x0E00 | scan
