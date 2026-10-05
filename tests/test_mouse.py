from mechkeys.mouse import BACK, FORWARD, LEFT, MIDDLE, RIGHT, MouseEvent, decode_buttons


def test_movement_only_gives_no_events():
    assert decode_buttons(0) == []
    assert decode_buttons(0x0400) == []  # wheel


def test_each_button_bit_decodes():
    assert decode_buttons(0x0001) == [MouseEvent(LEFT, True)]
    assert decode_buttons(0x0002) == [MouseEvent(LEFT, False)]
    assert decode_buttons(0x0004 | 0x0020) == [MouseEvent(RIGHT, True), MouseEvent(MIDDLE, False)]
    assert decode_buttons(0x0040) == [MouseEvent(BACK, True)]
    assert decode_buttons(0x0200) == [MouseEvent(FORWARD, False)]