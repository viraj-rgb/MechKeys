import pytest

from mechkeys.keycodes import LLKHF_EXTENDED, VK_NUMLOCK, VK_PAUSE, to_mechvibes_code


@pytest.mark.parametrize(
    "vk, scan, flags, expected",
    [
        (0x41, 0x1E, 0, 30),                        # A
        (0x20, 0x39, 0, 57),                        # Space
        (0x0D, 0x1C, 0, 28),                        # Enter
        (0x0D, 0x1C, LLKHF_EXTENDED, 3612),         # numpad Enter
        (0xA3, 0x1D, LLKHF_EXTENDED, 3613),         # right Ctrl
        (0x26, 0x48, LLKHF_EXTENDED, 57416),        # arrow Up
        (0x25, 0x4B, LLKHF_EXTENDED, 57419),        # arrow Left
        (0x27, 0x4D, LLKHF_EXTENDED, 57421),        # arrow Right
        (0x28, 0x50, LLKHF_EXTENDED, 57424),        # arrow Down
        (0x68, 0x48, 0, 72),                        # numpad 8 is not an arrow
        (0x2E, 0x53, LLKHF_EXTENDED, 3667),         # Delete
        (0x5B, 0x5B, LLKHF_EXTENDED, 3675),         # left Windows
        (VK_PAUSE, 0x45, 0, 3653),
        (VK_NUMLOCK, 0x45, LLKHF_EXTENDED, 69),
    ],
)
def test_maps_windows_events_to_mechvibes_codes(vk, scan, flags, expected):
    assert to_mechvibes_code(vk, scan, flags) == expected


def test_ignores_high_scan_bits():
    assert to_mechvibes_code(0x41, 0x11E, 0) == 30
