import numpy as np
import pytest

from mechkeys import engine as engine_mod
from mechkeys.engine import RepeatFilter, SoundEngine, volume_to_gain
from mechkeys.hook import KeyEvent
from mechkeys.settings import Settings
from mechkeys.soundpack import PackInfo, SoundPack

A = KeyEvent(vk=0x41, scan=0x1E, flags=0, is_down=True)
A_UP = A._replace(is_down=False)
CTRL = KeyEvent(vk=0xA2, scan=0x1D, flags=0, is_down=True)
ALT = KeyEvent(vk=0xA4, scan=0x38, flags=0, is_down=True)
M = KeyEvent(vk=0x4D, scan=0x32, flags=0, is_down=True)


class FakeMixer:
    samplerate, channels, master = 44100, 2, 1.0

    def __init__(self):
        self.played = []

    def play(self, samples, gain=1.0):
        self.played.append((samples, gain))


@pytest.fixture
def make_engine(monkeypatch):
    clock = {"now": 100.0}
    monkeypatch.setattr(engine_mod.time, "monotonic", lambda: clock["now"])

    def build(**settings):
        toggles = []
        eng = SoundEngine(Settings(**settings), on_mute_hotkey=lambda: toggles.append(1))
        eng.mixer = FakeMixer()
        sound = np.ones((100, 2), np.float32)
        release = np.full((40, 2), 0.5, np.float32)
        eng._pack = SoundPack(PackInfo("t", "T", None), {30: sound, 31: None}, (sound,),
                              {30: release, 31: None}, (release,))
        return eng, toggles, clock

    return build


def test_keypress_plays_sound(make_engine):
    eng, _, _ = make_engine(pitch_variation=0)
    eng._handle(A)
    assert len(eng.mixer.played) == 1 and eng.keystrokes == 1


def test_pitch_variation_resamples(make_engine):
    eng, _, _ = make_engine(pitch_variation=15)
    for _ in range(5):
        eng._handle(A)
        eng._handle(A_UP)
    assert any(len(samples) != 100 for samples, _ in eng.mixer.played)


def test_auto_repeat_is_ignored_until_release(make_engine):
    eng, _, clock = make_engine(release_volume=0)
    eng._handle(A)
    clock["now"] += 0.5
    eng._handle(A)
    assert len(eng.mixer.played) == 1
    eng._handle(A_UP)
    eng._handle(A)
    assert len(eng.mixer.played) == 2


def test_auto_repeat_plays_when_allowed(make_engine):
    eng, _, _ = make_engine(ignore_key_repeat=False)
    eng._handle(A)
    eng._handle(A)
    assert len(eng.mixer.played) == 2


def test_muted_counts_but_stays_silent(make_engine):
    eng, _, _ = make_engine(muted=True)
    eng._handle(A)
    assert eng.mixer.played == [] and eng.keystrokes == 1


def test_silent_key_plays_nothing(make_engine):
    eng, _, _ = make_engine()
    eng._handle(KeyEvent(vk=0x53, scan=31, flags=0, is_down=True))
    assert eng.mixer.played == []


def test_ctrl_alt_m_toggles_mute_once(make_engine):
    eng, toggles, _ = make_engine()
    for event in (CTRL, ALT, M, M):
        eng._handle(event)
    assert toggles == [1]


def test_mute_hotkey_can_be_disabled(make_engine):
    eng, toggles, _ = make_engine(mute_hotkey=False)
    for event in (CTRL, ALT, M):
        eng._handle(event)
    assert toggles == []


def test_apply_settings_sets_master_gain(make_engine):
    eng, _, _ = make_engine()
    eng.apply_settings(Settings(volume=100))
    assert eng.mixer.master == 1.0
    eng.apply_settings(Settings(volume=100, muted=True))
    assert eng.mixer.master == 0.0


def test_preview_uses_pack(make_engine):
    eng, _, _ = make_engine()
    eng.preview()
    assert len(eng.mixer.played) == 1


def test_volume_curve_is_monotonic_and_boosts_past_100():
    gains = [volume_to_gain(v) for v in range(0, 201, 10)]
    assert gains[0] == 0 and gains[10] == 1 and gains == sorted(gains)
    assert volume_to_gain(200) > 2.5
    assert volume_to_gain(999) == volume_to_gain(200)


def test_release_plays_softer_sound(make_engine):
    eng, _, _ = make_engine(pitch_variation=0, release_volume=50)
    eng._handle(A)
    eng._handle(A_UP)
    (press, press_gain), (release, release_gain) = eng.mixer.played
    assert len(release) == 40 and release_gain < press_gain
    assert eng.keystrokes == 1


def test_release_can_be_turned_off(make_engine):
    eng, _, _ = make_engine(release_volume=0)
    eng._handle(A)
    eng._handle(A_UP)
    assert len(eng.mixer.played) == 1


def test_release_silent_while_muted(make_engine):
    eng, _, _ = make_engine(muted=True)
    eng._handle(A_UP)
    assert eng.mixer.played == []


def test_hotkey_release_is_silent(make_engine):
    eng, toggles, _ = make_engine(pitch_variation=0)
    for event in (CTRL, ALT, M, M._replace(is_down=False)):
        eng._handle(event)
    assert toggles == [1]
    assert [len(samples) for samples, _ in eng.mixer.played] == [100, 100]  # Ctrl, Alt presses only


def test_stale_held_key_is_not_a_repeat():
    repeats = RepeatFilter(window_s=1.0)
    assert repeats.press(1, 0.0) is False
    assert repeats.press(1, 0.5) is True
    assert repeats.press(1, 5.0) is False


from mechkeys.mouse import LEFT, RIGHT, MouseEvent  # noqa: E402


def test_mouse_click_plays_press_and_release(make_engine):
    eng, _, _ = make_engine(pitch_variation=0, mouse_volume=50)
    eng._handle(MouseEvent(LEFT, True))
    eng._handle(MouseEvent(LEFT, False))
    (down, down_gain), (up, up_gain) = eng.mixer.played
    assert eng.clicks == 1 and eng.keystrokes == 0
    assert np.abs(up).max() < np.abs(down).max()
    assert 0.29 < down_gain <= volume_to_gain(50)


def test_mouse_volume_boosts_to_200(make_engine):
    eng, _, _ = make_engine(pitch_variation=0, mouse_volume=200)
    eng._handle(MouseEvent(LEFT, True))
    assert eng.mixer.played[0][1] > 2.5


def test_right_button_is_lower_pitched(make_engine):
    eng, _, _ = make_engine(pitch_variation=0)
    eng._handle(MouseEvent(LEFT, True))
    eng._handle(MouseEvent(RIGHT, True))
    left, right = (len(s) for s, _ in eng.mixer.played)
    assert right > left  # slower playback = longer = lower


def test_mouse_sounds_can_be_disabled_or_muted(make_engine):
    for settings in ({"mouse_sounds": False}, {"mouse_volume": 0}, {"muted": True}):
        eng, _, _ = make_engine(**settings)
        eng._handle(MouseEvent(LEFT, True))
        assert eng.mixer.played == [] and eng.clicks == 1


def test_mouse_listener_follows_setting(make_engine):
    eng, _, _ = make_engine(mouse_sounds=False)
    calls = []
    eng.mouse = type("FakeListener", (), {
        "running": False,
        "start": lambda self: calls.append("start") or True,
        "stop": lambda self: calls.append("stop"),
    })()
    eng.apply_settings(Settings(mouse_sounds=True))
    assert calls == []                      # engine not started yet: no listener thread
    eng._started = True
    eng.apply_settings(Settings(mouse_sounds=True))
    eng.mouse.running = True
    eng.apply_settings(Settings(mouse_sounds=False))
    assert calls == ["start", "stop"]


def test_mouse_style_change_regenerates_clicks(make_engine):
    eng, _, _ = make_engine()
    before = eng._mouse_clicks[0]
    eng.apply_settings(Settings(mouse_style="bubble"))
    assert not np.array_equal(before, eng._mouse_clicks[0])
    eng.preview_mouse()
    assert len(eng.mixer.played) == 2
