import json

from mechkeys import settings as store
from mechkeys.settings import Settings


def test_missing_file_gives_defaults(tmp_path):
    assert store.load(tmp_path / "nope.json") == Settings()


def test_round_trip(tmp_path):
    path = tmp_path / "s" / "settings.json"
    original = Settings(volume=33, muted=True, pack_id="x", pitch_variation=7)
    store.save(path, original)
    assert store.load(path) == original


def test_out_of_range_values_are_clamped(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"volume": 500, "pitch_variation": -4, "release_volume": 300, "unknown": 1}))
    loaded = store.load(path)
    assert loaded.volume == 200
    assert loaded.pitch_variation == 0
    assert loaded.release_volume == 100


def test_garbage_values_fall_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"volume": "loud", "pack_id": ""}))
    loaded = store.load(path)
    assert loaded.volume == Settings().volume
    assert loaded.pack_id == Settings().pack_id


def test_corrupt_json_gives_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert store.load(path) == Settings()
    path.write_text("[1, 2]")
    assert store.load(path) == Settings()


def test_with_changes_returns_new_validated_copy():
    base = Settings()
    changed = base.with_changes(volume=-10)
    assert changed.volume == 0
    assert base.volume == Settings().volume


def test_unknown_mouse_style_falls_back(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"mouse_style": "laser"}))
    assert store.load(path).mouse_style == Settings().mouse_style
    assert Settings().with_changes(mouse_style="crisp").mouse_style == "crisp"
    assert Settings().with_changes(mouse_volume=200).mouse_volume == 200
    assert Settings().with_changes(mouse_volume=999).mouse_volume == 200
