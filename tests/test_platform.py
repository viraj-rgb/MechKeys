import numpy as np
from conftest import FakeStream

from mechkeys import winutil
from mechkeys.icon import keycap_image, write_ico
from mechkeys.mixer import Mixer


def test_keycap_icon_sizes_and_mute_variant(tmp_path):
    normal, muted = keycap_image(32), keycap_image(32, muted=True)
    assert normal.size == (32, 32) and normal.mode == "RGBA"
    assert normal.tobytes() != muted.tobytes()
    write_ico(tmp_path / "x.ico")
    assert (tmp_path / "x.ico").stat().st_size > 0


def test_autostart_command_launches_minimized():
    command = winutil.launch_command()
    assert command.endswith("--minimized")
    assert "MechKeys.pyw" in command


def test_mixer_callback_writes_mixed_audio():
    class Status:
        output_underflow = False

    mixer = Mixer()
    mixer._stream = FakeStream()
    mixer.master = 1.0
    mixer.play(np.full((8, 2), 0.5, np.float32))
    out = np.zeros((4, 2), np.float32)
    mixer._callback(out, 4, None, Status())
    np.testing.assert_allclose(out, 0.5)
    assert len(mixer._voices) == 1
