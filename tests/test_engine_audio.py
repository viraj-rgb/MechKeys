import numpy as np
import pytest

from mechkeys.engine import SoundEngine
from mechkeys.settings import Settings
from mechkeys.soundpack import PackInfo, SoundPack, SoundPackError


class FakeMixer:
    channels = 2
    master = 1.0

    def __init__(self, new_rate=48000):
        self.samplerate = 48000
        self.new_rate = new_rate
        self.calls = []
        self.start_result = True
        self.running = True
        self.degraded = False

    def needs_restart(self):
        return False

    def reopen_devices(self):
        self.calls.append("reopen")
        self.samplerate = self.new_rate

    def start(self):
        self.calls.append("start")
        return self.start_result

    def stop(self):
        self.calls.append("stop")


@pytest.fixture
def engine():
    states, posted = [], []

    def build(new_rate=48000, post=None):
        eng = SoundEngine(Settings(), on_mute_hotkey=lambda: None,
                          post=post or (lambda action: (posted.append(action), action())),
                          on_audio_state=states.append)
        eng.mixer = FakeMixer(new_rate)
        sound = np.ones((100, 2), np.float32)
        eng._pack = SoundPack(PackInfo("t", "T", None), {30: sound}, (sound,))
        return eng

    return build, states, posted


def test_restart_rescans_then_starts(engine):
    build, _, _ = engine
    eng = build()
    assert eng.restart_audio() is True
    assert eng.mixer.calls == ["reopen", "start"]


def test_sample_rate_change_reloads_before_the_stream_reopens(engine, monkeypatch):
    build, _, _ = engine
    eng = build(new_rate=44100)
    seen = []
    monkeypatch.setattr(eng, "load_pack",
                        lambda info: seen.append((eng.mixer.samplerate, tuple(eng.mixer.calls))))
    before = eng._mouse_clicks
    eng.restart_audio()
    assert seen == [(44100, ("reopen",))]                 # reloaded at the new rate, stream still closed
    assert eng.mixer.calls == ["reopen", "start"]
    assert eng._mouse_clicks is not before


def test_same_sample_rate_keeps_the_loaded_pack(engine, monkeypatch):
    build, _, _ = engine
    eng = build(new_rate=48000)
    monkeypatch.setattr(eng, "load_pack", lambda info: pytest.fail("pack should not be reloaded"))
    eng.restart_audio()


def test_pack_reload_failure_leaves_silence_not_wrong_pitch(engine, monkeypatch):
    build, _, _ = engine
    eng = build(new_rate=44100)

    def boom(info):
        raise SoundPackError("decode failed")

    monkeypatch.setattr(eng, "load_pack", boom)
    assert eng.restart_audio() is True
    assert eng.pack is None


def test_device_change_restarts_on_the_ui_thread_and_reports(engine):
    build, states, posted = engine
    eng = build()
    eng._request_audio_restart("default output changed")
    assert len(posted) == 1 and eng.mixer.calls == ["reopen", "start"]
    assert states == [True]


def test_failed_restart_reports_no_audio(engine):
    build, states, _ = engine
    eng = build()
    eng.mixer.start_result = False
    eng._request_audio_restart("audio stream stopped")
    assert states == [False]


def test_requests_are_deduplicated_until_the_restart_runs(engine):
    build, states, _ = engine
    queued = []
    eng = build(post=queued.append)
    for _ in range(5):
        eng._request_audio_restart("default output changed")
    assert len(queued) == 1
    queued[0]()
    eng._request_audio_restart("default output changed")
    assert len(queued) == 2                               # allowed again once the first ran


def test_an_exception_during_restart_does_not_wedge_future_restarts(engine):
    build, states, _ = engine
    eng = build()

    def boom():
        raise RuntimeError("driver crashed")

    eng.mixer.reopen_devices = boom
    eng._request_audio_restart("x")
    assert states == [False]
    eng.mixer.reopen_devices = lambda: None
    eng._request_audio_restart("x")
    assert states == [False, True]


def test_slow_fallback_path_is_retried_a_few_times_then_left_alone(engine):
    build, states, _ = engine
    eng = build()
    eng.mixer.degraded = True                       # the fast path keeps failing on this device
    attempts = 0
    while eng._audio_needs_attention():
        eng._request_audio_restart("audio stream stopped")
        attempts += 1
        assert attempts < 10
    assert attempts == 3 and len(states) == 3


def test_getting_back_onto_the_fast_path_stops_the_retries(engine):
    build, _, _ = engine
    eng = build()
    eng.mixer.degraded = True
    eng._request_audio_restart("audio stream stopped")
    eng.mixer.degraded = False
    eng._request_audio_restart("audio stream stopped")
    assert not eng._audio_needs_attention() and eng._fast_path_tries == 0


def test_a_new_device_resets_the_retry_budget(engine):
    build, _, _ = engine
    eng = build()
    eng.mixer.degraded = True
    for _ in range(3):
        eng._request_audio_restart("audio stream stopped")
    assert not eng._audio_needs_attention()
    eng._request_audio_restart("default output changed")
    assert eng._fast_path_tries == 1                # reset to 0, then this restart was degraded too


def test_dead_or_not_running_audio_always_needs_attention(engine):
    build, _, _ = engine
    eng = build()
    eng.mixer.running = False
    assert eng._audio_needs_attention()
    eng.mixer.running = True
    eng.mixer.needs_restart = lambda: True
    assert eng._audio_needs_attention()
