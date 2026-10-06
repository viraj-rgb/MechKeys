import numpy as np
import pytest
from conftest import FakeStream

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
    mixer._stream = FakeStream()
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
    import sounddevice as sd

    class Status:
        output_underflow = False

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



def test_sounds_are_dropped_while_no_stream_is_open():
    mixer = Mixer()
    mixer.play(np.ones((10, 2), np.float32))
    assert mixer._voices == []


def test_needs_restart_only_for_a_dead_stream():
    mixer = Mixer()
    assert not mixer.needs_restart()                 # nothing open: not "dead", just not started
    mixer._stream = FakeStream(active=True)
    assert not mixer.needs_restart()
    mixer._stream = FakeStream(active=False)
    assert mixer.needs_restart()                     # died on its own (device unplugged)
    mixer._paused = True
    assert not mixer.needs_restart()                 # idle pause is healthy
    mixer._paused = False

    class Broken:
        @property
        def active(self):
            raise OSError("device gone")

    mixer._stream = Broken()
    assert mixer.needs_restart()


def test_resume_is_skipped_while_stream_is_being_reopened():
    mixer = Mixer()
    stream = mixer._stream = FakeStream()
    mixer._paused = True
    with mixer._stream_lock:                          # reopen in progress (here: another thread)
        import threading
        worker = threading.Thread(target=mixer._resume)
        worker.start()
        worker.join(timeout=1)
    assert not worker.is_alive() and stream.calls == []   # returned at once, did not touch the stream
    mixer._resume()
    assert stream.calls == ["stop", "start"]


def test_reopen_devices_rescans_and_updates_rate(monkeypatch):
    import mechkeys.mixer as mixer_mod

    events = []
    monkeypatch.setattr(mixer_mod.sd, "_terminate", lambda: events.append("terminate"))
    monkeypatch.setattr(mixer_mod.sd, "_initialize", lambda: events.append("initialize"))
    monkeypatch.setattr(mixer_mod, "pick_output", lambda: (7, 44100))
    mixer = Mixer()
    stream = mixer._stream = FakeStream()
    mixer.samplerate = 48000
    mixer.reopen_devices()
    assert stream.calls == ["stop", "close"] and mixer._stream is None
    assert events == ["terminate", "initialize"]
    assert (mixer.device, mixer.samplerate) == (7, 44100)


def test_falling_back_to_the_default_device_is_flagged_as_degraded(monkeypatch):
    import mechkeys.mixer as mixer_mod

    attempts = []

    def open_stream(self, device):
        attempts.append(device)
        if device is not None:
            raise OSError("format not supported by this device")
        return FakeStream()

    monkeypatch.setattr(mixer_mod.Mixer, "_open", open_stream)
    mixer = Mixer()
    mixer.device = 5
    assert mixer.start() and attempts == [5, None] and mixer.degraded
    attempts.clear()
    mixer.device = None                      # no fast path exists at all: not "degraded"
    assert mixer.start() and not mixer.degraded
