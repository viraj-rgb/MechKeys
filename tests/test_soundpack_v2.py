"""Mechvibes v2 packs, pattern expansion, path safety, and every bundled pack."""
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
from conftest import ROOT, write_wav

from mechkeys.soundpack import (
    PackInfo,
    SoundPackError,
    discover_packs,
    expand_pattern,
    import_pack_zip,
    load_pack,
    pack_file,
)


def make_v2_pack(folder: Path, click: np.ndarray) -> PackInfo:
    for i in range(3):
        write_wav(folder / "press" / f"G{i}.wav", click * (0.5 + 0.1 * i))
    write_wav(folder / "press" / "SPACE.wav", click)
    write_wav(folder / "release" / "GENERIC.wav", click * 0.2)
    write_wav(folder / "release" / "SPACE.wav", click * 0.3)
    config = {
        "name": "V2", "key_define_type": "multi", "version": 2,
        "sound": "press/G{0-2}.wav", "soundup": "release/GENERIC.wav",
        "defines": {"57": "press/SPACE.wav", "57-up": "release/SPACE.wav",
                    "28": "press/MISSING.wav", "91": None},
    }
    (folder / "config.json").write_text(json.dumps(config))
    return PackInfo("v2", "V2", folder)


def test_expand_pattern():
    assert expand_pattern("R{0-2}.mp3") == ["R0.mp3", "R1.mp3", "R2.mp3"]
    assert expand_pattern("plain.wav") == ["plain.wav"]
    assert expand_pattern("R{5-1}.wav") == ["R{5-1}.wav"]
    assert expand_pattern("R{0-9999}.wav") == ["R{0-9999}.wav"]


def test_pack_file_blocks_escapes(tmp_path):
    assert pack_file(tmp_path, "press/a.wav") == (tmp_path / "press" / "a.wav").resolve()
    with pytest.raises(SoundPackError):
        pack_file(tmp_path, "../outside.wav")


def test_v2_pack_uses_generics_and_recorded_releases(tmp_path, click):
    pack = load_pack(make_v2_pack(tmp_path / "v2", click), rate=44100)
    assert len(pack.fallback) == 3                       # generic R0-R2 only
    assert pack.sound_for(57) is not pack.fallback[0]    # space has its own sample
    assert pack.sound_for(28) is not None                # missing file -> generic
    assert pack.sound_for(91) is None and pack.release_for(91) is None
    space_up, generic_up = pack.release_for(57), pack.release_for(30)
    assert np.abs(space_up).max() > np.abs(generic_up).max()   # recorded, not derived
    assert pack.release_for(28) is generic_up


def test_import_keeps_subfolders(tmp_path, click):
    src = tmp_path / "src"
    make_v2_pack(src, click)
    archive = tmp_path / "v2.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for f in src.rglob("*"):
            if f.is_file():
                zf.write(f, f"pack/{f.relative_to(src).as_posix()}")
        zf.writestr("pack/../../evil.wav", b"x")
    info = import_pack_zip(archive, tmp_path / "packs")
    assert (info.path / "press" / "G0.wav").is_file()
    assert (info.path / "release" / "SPACE.wav").is_file()
    assert not (tmp_path / "evil.wav").exists()
    assert load_pack(info, 44100).release_for(57) is not None


def test_every_bundled_pack_loads():
    packs = discover_packs(ROOT / "sounds")
    assert len(packs) >= 17
    for info in packs:
        pack = load_pack(info, 48000)
        assert pack.sound_for(30) is not None, info.name
        assert pack.release_for(30) is not None, info.name