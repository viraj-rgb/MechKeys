"""Settings must survive every way the app can stop: saved file layout, crashes, odd files."""
import json

from mechkeys import settings as store
from mechkeys.settings import Settings

CUSTOM = Settings(volume=185, muted=True, pack_id="synth-bubble", pitch_variation=11, release_volume=35,
                  mouse_sounds=False, mouse_volume=160, mouse_style="crisp", ignore_key_repeat=False,
                  mute_hotkey=False, close_to_tray=False, start_with_windows=True)


def test_every_field_survives_a_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    store.save(path, CUSTOM)
    assert store.load(path) == CUSTOM


def test_save_keeps_previous_version_as_backup(tmp_path):
    path = tmp_path / "settings.json"
    store.save(path, Settings(volume=40))
    store.save(path, Settings(volume=90))
    assert store.load(path).volume == 90
    assert json.loads((tmp_path / "settings.json.bak").read_text())["volume"] == 40
    assert not (tmp_path / "settings.json.tmp").exists()


def test_corrupt_file_falls_back_to_backup_and_is_set_aside(tmp_path):
    path = tmp_path / "settings.json"
    store.save(path, Settings(volume=40))
    store.save(path, Settings(volume=90))
    path.write_text("{ garbage")
    assert store.load(path).volume == 40                  # the last good copy, not defaults
    assert (tmp_path / "settings.corrupt.json").read_text() == "{ garbage"
    assert not path.exists()                              # never overwritten silently


def test_corrupt_file_without_backup_is_kept_not_destroyed(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ garbage")
    assert store.load(path) == Settings()
    assert (tmp_path / "settings.corrupt.json").exists()


def test_crash_between_the_two_renames_loses_nothing(tmp_path):
    path = tmp_path / "settings.json"
    store.save(path, Settings(volume=40))
    # Dying mid-save: the new content is complete in .tmp, the old file already moved to .bak.
    (tmp_path / "settings.json.tmp").write_text(json.dumps({"volume": 120}))
    path.rename(tmp_path / "settings.json.bak")
    assert store.load(path).volume == 120


def test_half_written_tmp_is_ignored(tmp_path):
    path = tmp_path / "settings.json"
    store.save(path, Settings(volume=55))
    (tmp_path / "settings.json.tmp").write_text('{"volume": 1')   # died while writing
    assert store.load(path).volume == 55


def test_settings_from_an_older_version_gain_defaults_for_new_fields(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"volume": 150, "pack_id": "nk-cream", "retired_option": True}))
    loaded = store.load(path)
    assert loaded.volume == 150
    assert loaded.mouse_style == Settings().mouse_style
