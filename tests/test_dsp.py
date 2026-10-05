import numpy as np

from mechkeys.dsp import LIMIT_KNEE, RELEASE_GAIN, make_release, soft_clip


def test_soft_clip_is_transparent_below_knee():
    block = np.full((4, 2), LIMIT_KNEE - 0.01, np.float32)
    assert soft_clip(block) is block


def test_soft_clip_keeps_peaks_inside_unit_range_and_order():
    block = np.array([[0.5], [0.9], [1.5], [3.0], [-3.0]], np.float32)
    out = soft_clip(block)
    assert np.all(np.abs(out) <= 1.0)
    assert out[0, 0] == 0.5
    assert out[1, 0] < out[2, 0] <= out[3, 0]
    assert out[4, 0] == -out[3, 0]


def test_release_is_shorter_quieter_and_fades_out():
    rng = np.random.default_rng(1)
    press = (rng.random((1000, 2), dtype=np.float32) - 0.5)
    release = make_release(press)
    assert len(release) < len(press) * 0.6
    assert np.abs(release).max() <= np.abs(press).max() * RELEASE_GAIN + 1e-6
    assert np.allclose(release[-1], 0.0)
    assert release.dtype == np.float32


def test_mouse_clicks_are_short_and_quiet():
    from mechkeys.dsp import MOUSE_STYLES, make_mouse_clicks

    MOUSE_DOWN_PEAK = MOUSE_STYLES["classic"].down_peak

    down, up = make_mouse_clicks(48000)
    assert down.shape[1] == 2 and down.dtype == np.float32
    assert len(down) <= 48000 * 0.06
    assert np.isclose(np.abs(down).max(), MOUSE_DOWN_PEAK, atol=1e-3)
    assert np.abs(up).max() < np.abs(down).max()
    mono_down, _ = make_mouse_clicks(44100, channels=1)
    assert mono_down.shape[1] == 1


def test_every_mouse_style_is_distinct_and_bounded():
    from mechkeys.dsp import MOUSE_STYLES, make_mouse_clicks

    renders = {k: make_mouse_clicks(48000, style=k)[0] for k in MOUSE_STYLES}
    assert all(np.abs(r).max() <= 0.25 and np.isfinite(r).all() for r in renders.values())
    as_bytes = {r.tobytes() for r in renders.values()}
    assert len(as_bytes) == len(MOUSE_STYLES)
    unknown = make_mouse_clicks(48000, style="nope")[0]
    assert np.array_equal(unknown, renders["classic"])
