import numpy as np

from mechkeys.dsp import vary_pitch
from mechkeys.mixer import MAX_VOICES, Mixer, Voice, mix_block


def test_mix_sums_voices_and_applies_master():
    a = Voice(np.full((4, 2), 0.25, np.float32), gain=1.0)
    b = Voice(np.full((2, 2), 0.25, np.float32), gain=2.0)
    out, alive = mix_block([a, b], frames=4, channels=2, master=0.5)
    np.testing.assert_allclose(out[:2], 0.375)
    np.testing.assert_allclose(out[2:], 0.125)
    assert alive == []


def test_mix_keeps_unfinished_voices_and_limits():
    loud = Voice(np.full((10, 2), 0.9, np.float32), gain=3.0)
    out, alive = mix_block([loud], frames=4, channels=2, master=1.0)
    assert 0.95 < out.max() <= 1.0
    assert alive == [loud] and loud.pos == 4


def test_vary_pitch_changes_length():
    samples = np.random.default_rng(0).random((1000, 2)).astype(np.float32)
    assert len(vary_pitch(samples, 1.25)) == 800
    assert len(vary_pitch(samples, 0.8)) == 1250
    assert vary_pitch(samples, 1.0) is samples


def test_play_caps_voice_count():
    mixer = Mixer()
    for _ in range(MAX_VOICES + 5):
        mixer.play(np.zeros((10, 2), np.float32))
    assert len(mixer._voices) == MAX_VOICES


def test_idle_callback_outputs_silence_without_mixing():
    class Status:
        output_underflow = False

    mixer = Mixer()
    out = np.ones((4, 2), np.float32)
    mixer._callback(out, 4, None, Status())
    assert not out.any()


def test_numpy_thread_pool_is_capped():
    import os

    import mechkeys  # noqa: F401

    assert os.environ["OPENBLAS_NUM_THREADS"] == "1"



def test_pauses_after_silence_and_resumes_on_play():
    import pytest
    import sounddevice as sd

    class Status:
        output_underflow = False

    class FakeStream:
        def __init__(self):
            self.calls = []

        def stop(self):
            self.calls.append("stop")

        def start(self):
            self.calls.append("start")

    mixer = Mixer()
    mixer.samplerate = 100  # 5 s of idle = 500 frames
    mixer._stream = FakeStream()
    out = np.zeros((100, 2), np.float32)
    for _ in range(4):
        mixer._callback(out, 100, None, Status())
    assert not mixer.paused
    with pytest.raises(sd.CallbackStop):
        mixer._callback(out, 100, None, Status())
    assert mixer.paused

    mixer.play(np.ones((10, 2), np.float32))
    assert mixer._stream.calls == ["stop", "start"] and not mixer.paused
    mixer.play(np.ones((10, 2), np.float32))
    assert mixer._stream.calls == ["stop", "start"]  # already running: no restart
    mixer._stream = None

