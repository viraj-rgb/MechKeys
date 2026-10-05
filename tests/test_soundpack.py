import json
import zipfile

import numpy as np
import pytest
from conftest import BUNDLED_PACK, write_wav

from mechkeys.soundpack import (
    PackInfo,
    SoundPackError,
    conform,
    decode_audio,
    discover_packs,
    import_pack_zip,
    load_pack,
    trim_leading_silence,
)


def make_multi_pack(folder, click, defines=None):
    folder.mkdir(parents=True)
    write_wav(folder / "a.wav", click)
    write_wav(folder / "b.wav", click * 0.5)
    config = {"name": "Test Pack", "key_define_type": "multi",
              "defines": defines or {"30": "a.wav", "48": "b.wav", "91": None}}
    (folder / "config.json").write_text(json.dumps(config))
    return PackInfo("test", "Test Pack", folder)


def test_bundled_pack_loads_every_defined_key():
    pack = load_pack(PackInfo("nk-cream", "NK Cream", BUNDLED_PACK), rate=44100)
    assert pack.sound_for(30) is not None          # A
    assert pack.sound_for(57) is not None          # Space
    assert pack.sound_for(91) is None              # explicitly silent
    assert pack.sound_for(999_999) is not None     # unknown key borrows a sound
    assert all(s.shape[1] == 2 and s.dtype == np.float32 for s in pack.fallback)
    assert pack.release_for(30) is not None and pack.release_for(91) is None
    assert len(pack.release_for(30)) < len(pack.sound_for(30))
    assert len(pack.release_fallback) == len(pack.fallback)


def test_multi_pack_shares_decoded_files(tmp_path, click):
    info = make_multi_pack(tmp_path / "p", click, {"1": "a.wav", "2": "a.wav", "3": "b.wav"})
    pack = load_pack(info, rate=44100)
    assert pack.sounds[1] is pack.sounds[2]
    assert pack.releases[1] is pack.releases[2]
    assert len(pack.fallback) == 2


def test_single_pack_slices_one_file(tmp_path, click):
    folder = tmp_path / "single"
    folder.mkdir()
    write_wav(folder / "sound.wav", np.vstack([click, click]))
    config = {"key_define_type": "single", "sound": "sound.wav",
              "defines": {"30": [0, 70], "31": [70, 70], "32": [0, 0], "33": None, "x": [0, 1]}}
    (folder / "config.json").write_text(json.dumps(config))
    pack = load_pack(PackInfo("s", "S", folder), rate=44100)
    assert pack.sound_for(30) is not None and pack.sound_for(31) is not None
    assert pack.sound_for(32) is None and pack.sound_for(33) is None


def test_missing_audio_file_raises(tmp_path, click):
    info = make_multi_pack(tmp_path / "p", click, {"1": "missing.wav"})
    with pytest.raises(SoundPackError):
        load_pack(info, rate=44100)


def test_pack_without_sounds_raises(tmp_path, click):
    info = make_multi_pack(tmp_path / "p", click, {"1": None})
    with pytest.raises(SoundPackError):
        load_pack(info, rate=44100)


def test_bad_config_raises(tmp_path):
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "config.json").write_text("{oops")
    with pytest.raises(SoundPackError):
        load_pack(PackInfo("bad", "Bad", folder), rate=44100)


def test_trim_removes_leading_silence(click):
    trimmed = trim_leading_silence(click, 44100)
    assert len(trimmed) < len(click) - 700
    silent = np.zeros((50, 2), np.float32)
    assert trim_leading_silence(silent, 44100) is silent


def test_conform_resamples_and_upmixes():
    mono = np.linspace(-1, 1, 22050, dtype=np.float32).reshape(-1, 1)
    out = conform(mono, 22050, 44100, 2)
    assert out.shape == (44100, 2)
    stereo = np.zeros((10, 2), np.float32)
    assert conform(stereo, 44100, 44100, 1).shape == (10, 1)


def test_decodes_8_bit_wav(tmp_path, click):
    path = write_wav(tmp_path / "x.wav", click, width=1)
    data, rate = decode_audio(path)
    assert rate == 44100 and data.shape == click.shape
    assert np.abs(data).max() <= 1.0


def test_discover_skips_invalid_and_duplicate_folders(tmp_path, click):
    builtin, user = tmp_path / "builtin", tmp_path / "user"
    make_multi_pack(builtin / "alpha", click)
    make_multi_pack(user / "alpha", click)
    (user / "junk").mkdir()
    found = discover_packs(builtin, user, tmp_path / "missing")
    assert [p.path for p in found] == [builtin / "alpha"]


def test_import_zip_with_nested_folder(tmp_path, click):
    src = tmp_path / "src"
    make_multi_pack(src, click)
    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for f in src.iterdir():
            zf.write(f, f"My Pack/{f.name}")
        zf.writestr("readme.txt", "ignored")
    info = import_pack_zip(archive, tmp_path / "packs")
    assert info.name == "Test Pack" and info.pack_id == "test-pack"
    assert sorted(p.name for p in info.path.iterdir()) == ["a.wav", "b.wav", "config.json"]
    again = import_pack_zip(archive, tmp_path / "packs")
    assert again.pack_id == "test-pack-2"


def test_import_cannot_escape_destination(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("config.json", json.dumps({"name": "../../evil", "defines": {}}))
        zf.writestr("../outside.wav", b"x")
    info = import_pack_zip(archive, tmp_path / "packs")
    assert info.path.parent == tmp_path / "packs"
    assert not (tmp_path / "outside.wav").exists()


def test_import_rejects_non_packs(tmp_path):
    not_zip = tmp_path / "x.zip"
    not_zip.write_text("hello")
    with pytest.raises(SoundPackError):
        import_pack_zip(not_zip, tmp_path / "packs")

    no_config = tmp_path / "empty.zip"
    with zipfile.ZipFile(no_config, "w") as zf:
        zf.writestr("a.wav", b"x")
    with pytest.raises(SoundPackError):
        import_pack_zip(no_config, tmp_path / "packs")

    bad_config = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad_config, "w") as zf:
        zf.writestr("config.json", json.dumps({"name": "bad"}))
    with pytest.raises(SoundPackError):
        import_pack_zip(bad_config, tmp_path / "packs")
    assert list((tmp_path / "packs").iterdir()) == []
