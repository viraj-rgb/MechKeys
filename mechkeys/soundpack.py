"""Load Mechvibes-format sound packs into ready-to-mix sample arrays.

A pack is a folder holding ``config.json`` plus audio files. Two layouts exist:

* ``multi``  - ``defines`` maps a key code to its own audio file (or null)
* ``single`` - ``defines`` maps a key code to ``[start_ms, length_ms]`` inside
  one shared ``sound`` file
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import wave
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Mapping

import numpy as np

from .dsp import make_release

log = logging.getLogger(__name__)

CONFIG_NAME = "config.json"
SILENCE_THRESHOLD = 0.01
PRE_ROLL_SECONDS = 0.002
MAX_PACK_BYTES = 200 * 1024 * 1024


class SoundPackError(Exception):
    """Raised when a pack cannot be read or imported."""


@dataclass(frozen=True)
class PackInfo:
    pack_id: str
    name: str
    path: Path


@dataclass(frozen=True)
class SoundPack:
    info: PackInfo
    sounds: Mapping[int, np.ndarray | None]
    fallback: tuple[np.ndarray, ...] = field(default_factory=tuple)
    releases: Mapping[int, np.ndarray | None] = field(default_factory=dict)
    release_fallback: tuple[np.ndarray, ...] = field(default_factory=tuple)

    def sound_for(self, code: int) -> np.ndarray | None:
        """Samples for a key code; unknown keys borrow a stable fallback sound."""
        return _lookup(self.sounds, self.fallback, code)

    def release_for(self, code: int) -> np.ndarray | None:
        """Key-release samples, paired with whatever ``sound_for`` returns."""
        return _lookup(self.releases, self.release_fallback, code)


def _lookup(table: Mapping[int, np.ndarray | None], fallback: tuple, code: int) -> np.ndarray | None:
    if code in table:
        return table[code]
    if not fallback:
        return None
    return fallback[code % len(fallback)]


def derive_releases(sounds: Mapping[int, np.ndarray | None], fallback: tuple[np.ndarray, ...]):
    """Build a release sound for every press sound, decoding each unique sample once."""
    cache: dict[int, np.ndarray] = {}

    def release(samples: np.ndarray | None) -> np.ndarray | None:
        if samples is None:
            return None
        if id(samples) not in cache:
            cache[id(samples)] = make_release(samples)
        return cache[id(samples)]

    releases = {code: release(samples) for code, samples in sounds.items()}
    return releases, tuple(release(samples) for samples in fallback)


# --------------------------------------------------------------------------- #
# Audio decoding
# --------------------------------------------------------------------------- #

def _decode_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())

    if width == 1:
        data = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    elif width == 3:
        bytes3 = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        ints = bytes3[:, 0] | (bytes3[:, 1] << 8) | (bytes3[:, 2] << 16)
        ints = np.where(ints & 0x800000, ints - 0x1000000, ints)
        data = ints.astype(np.float32) / 8388608.0
    elif width == 4:
        data = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648.0
    else:
        raise SoundPackError(f"Unsupported WAV sample width {width} in {path.name}")
    return data.reshape(-1, channels), rate


def _decode_other(path: Path) -> tuple[np.ndarray, int]:
    try:
        import soundfile  # optional: adds OGG/FLAC/float-WAV support
    except ImportError as exc:
        raise SoundPackError(
            f"{path.name}: only WAV files are supported (install 'soundfile' for OGG/FLAC)"
        ) from exc
    data, rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    return data, rate


def decode_audio(path: Path) -> tuple[np.ndarray, int]:
    """Decode an audio file into float32 frames shaped (n, channels)."""
    if not path.is_file():
        raise SoundPackError(f"Missing audio file: {path.name}")
    if path.suffix.lower() == ".wav":
        try:
            return _decode_wav(path)
        except wave.Error:
            return _decode_other(path)  # e.g. 32-bit float WAV
    return _decode_other(path)


def conform(data: np.ndarray, rate: int, target_rate: int, channels: int) -> np.ndarray:
    """Return a copy of ``data`` with the target channel count and sample rate."""
    if data.shape[1] == channels:
        shaped = data
    elif data.shape[1] == 1:
        shaped = np.repeat(data, channels, axis=1)
    elif channels == 1:
        shaped = data.mean(axis=1, keepdims=True)
    else:
        shaped = data[:, :channels]

    if rate == target_rate or len(shaped) < 2:
        return np.ascontiguousarray(shaped, dtype=np.float32)

    new_len = max(1, int(round(len(shaped) * target_rate / rate)))
    src_pos = np.linspace(0, len(shaped) - 1, new_len)
    src_idx = np.arange(len(shaped))
    resampled = np.column_stack([np.interp(src_pos, src_idx, shaped[:, c]) for c in range(channels)])
    return resampled.astype(np.float32)


def trim_leading_silence(data: np.ndarray, rate: int) -> np.ndarray:
    """Drop dead air before the click so the sound lands with the keypress."""
    loud = np.flatnonzero(np.abs(data).max(axis=1) > SILENCE_THRESHOLD)
    if loud.size == 0:
        return data
    start = max(0, int(loud[0]) - int(rate * PRE_ROLL_SECONDS))
    return data[start:]


# --------------------------------------------------------------------------- #
# Pack loading
# --------------------------------------------------------------------------- #

def read_config(pack_dir: Path) -> dict:
    config_path = pack_dir / CONFIG_NAME
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SoundPackError(f"{pack_dir.name}: no {CONFIG_NAME}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SoundPackError(f"{pack_dir.name}: {CONFIG_NAME} is not valid JSON") from exc
    if not isinstance(config, dict) or not isinstance(config.get("defines"), dict):
        raise SoundPackError(f"{pack_dir.name}: {CONFIG_NAME} has no 'defines' map")
    return config


def _parse_code(key: str) -> int | None:
    try:
        return int(key)
    except (TypeError, ValueError):
        return None


_RANGE = re.compile(r"\{(\d+)-(\d+)\}")
MAX_PATTERN_FILES = 64


def expand_pattern(name: str) -> list[str]:
    """Expand a Mechvibes v2 range: 'GENERIC_R{0-4}.mp3' -> GENERIC_R0.mp3 ... GENERIC_R4.mp3."""
    match = _RANGE.search(name)
    if not match:
        return [name]
    low, high = int(match[1]), int(match[2])
    if high < low or high - low >= MAX_PATTERN_FILES:
        return [name]
    return [f"{name[:match.start()]}{i}{name[match.end():]}" for i in range(low, high + 1)]


def pack_file(pack_dir: Path, relative: str) -> Path:
    """Resolve a pack-relative path, refusing anything that escapes the pack folder."""
    root = pack_dir.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise SoundPackError(f"{pack_dir.name}: path escapes the pack: {relative}")
    return target


class _SampleCache:
    """Decodes each referenced file once; missing files are skipped with a warning."""

    def __init__(self, pack_dir: Path, rate: int, channels: int):
        self._dir, self._rate, self._channels = pack_dir, rate, channels
        self._samples: dict[str, np.ndarray | None] = {}

    def get(self, relative: str) -> np.ndarray | None:
        if relative not in self._samples:
            self._samples[relative] = self._decode(relative)
        return self._samples[relative]

    def _decode(self, relative: str) -> np.ndarray | None:
        try:
            data, src_rate = decode_audio(pack_file(self._dir, relative))
        except SoundPackError as exc:
            log.warning("%s", exc)
            return None
        return trim_leading_silence(conform(data, src_rate, self._rate, self._channels), self._rate)

    def loaded(self) -> tuple[np.ndarray, ...]:
        return tuple(s for _, s in sorted(self._samples.items()) if s is not None)


@dataclass(frozen=True)
class _Loaded:
    sounds: dict
    fallback: tuple
    releases: dict = field(default_factory=dict)
    release_fallback: tuple | None = None   # None = derive from presses


def _load_multi(pack_dir: Path, config: dict, rate: int, channels: int) -> _Loaded:
    cache = _SampleCache(pack_dir, rate, channels)
    presses: dict[int, np.ndarray | None] = {}
    releases: dict[int, np.ndarray | None] = {}
    for key, filename in config["defines"].items():
        is_up = str(key).endswith("-up")
        code = _parse_code(str(key)[:-3] if is_up else key)
        if code is None:
            continue
        table = releases if is_up else presses
        if not filename:
            table[code] = None
            continue
        samples = cache.get(str(filename))
        if samples is not None:  # a missing file falls back to the generic sounds
            table[code] = samples

    # v2 packs name random generic press samples in 'sound'; v1 multi packs ignore it.
    generic_names = expand_pattern(str(config["sound"])) if config.get("version", 1) >= 2 and config.get("sound") else []
    generic = tuple(s for s in map(cache.get, generic_names) if s is not None)
    fallback = generic or cache.loaded()
    generic_up = cache.get(str(config["soundup"])) if config.get("soundup") else None
    if not releases and generic_up is None:
        return _Loaded(presses, fallback)

    silent = {code: None for code, samples in presses.items() if samples is None}
    release_fallback = (generic_up,) if generic_up is not None else None
    return _Loaded(presses, fallback, {**silent, **releases}, release_fallback)


def _load_single(pack_dir: Path, config: dict, rate: int, channels: int) -> _Loaded:
    sound_name = config.get("sound")
    if not sound_name:
        raise SoundPackError(f"{pack_dir.name}: single-sound pack has no 'sound' file")
    data, src_rate = decode_audio(pack_file(pack_dir, str(sound_name)))
    full = conform(data, src_rate, rate, channels)

    sounds: dict[int, np.ndarray | None] = {}
    slices: dict[tuple[int, int], np.ndarray] = {}
    for key, span in config["defines"].items():
        code = _parse_code(key)
        if code is None:
            continue
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            sounds[code] = None
            continue
        start = int(float(span[0]) * rate / 1000)
        end = start + int(float(span[1]) * rate / 1000)
        bounds = (start, end)
        if bounds not in slices:
            slices[bounds] = trim_leading_silence(full[start:end], rate)
        sounds[code] = slices[bounds] if len(slices[bounds]) else None
    fallback = tuple(s for _, s in sorted(slices.items()) if len(s))
    return _Loaded(sounds, fallback)


def load_pack(info: PackInfo, rate: int, channels: int = 2) -> SoundPack:
    config = read_config(info.path)
    if config.get("key_define_type", "single") == "multi":
        loaded = _load_multi(info.path, config, rate, channels)
    else:
        loaded = _load_single(info.path, config, rate, channels)
    if not loaded.fallback:
        raise SoundPackError(f"{info.name}: pack contains no playable sounds")

    derived, derived_fallback = derive_releases(loaded.sounds, loaded.fallback)
    if loaded.release_fallback is None and not loaded.releases:
        releases, release_fallback = derived, derived_fallback
    else:  # recorded releases: keys without their own fall back to the generic one
        releases = loaded.releases
        release_fallback = loaded.release_fallback or derived_fallback
    return SoundPack(info=info, sounds=loaded.sounds, fallback=loaded.fallback,
                     releases=releases, release_fallback=release_fallback)

def discover_packs(*roots: Path) -> list[PackInfo]:
    """Every folder with a valid config under ``roots``; earlier roots win on id clashes."""
    found: dict[str, PackInfo] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            if folder.name in found:
                continue
            try:
                config = read_config(folder)
            except SoundPackError:
                continue
            name = str(config.get("name") or folder.name)
            found[folder.name] = PackInfo(pack_id=folder.name, name=name, path=folder)
    return sorted(found.values(), key=lambda p: p.name.lower())


# --------------------------------------------------------------------------- #
# Importing
# --------------------------------------------------------------------------- #

def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "pack"


def _unique_dir(root: Path, base: str) -> Path:
    candidate = root / base
    suffix = 2
    while candidate.exists():
        candidate = root / f"{base}-{suffix}"
        suffix += 1
    return candidate


def _relative_parts(member: str, prefix: PurePosixPath) -> tuple[str, ...]:
    """Path parts of a zip member below `prefix`; empty if outside it or unsafe."""
    path = PurePosixPath(member)
    try:
        parts = path.relative_to(prefix).parts
    except ValueError:
        return ()
    if any(p in ("", ".", "..") or "\\" in p or ":" in p for p in parts):
        return ()
    return parts


def import_pack_zip(zip_path: Path, dest_root: Path) -> PackInfo:
    """Safely extract a Mechvibes pack zip into ``dest_root`` and return it."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise SoundPackError(f"{zip_path.name} is not a readable zip file") from exc

    with archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        configs = [m for m in members if PurePosixPath(m.filename).name == CONFIG_NAME]
        if not configs:
            raise SoundPackError(f"{zip_path.name} has no {CONFIG_NAME}")
        config_member = min(configs, key=lambda m: len(PurePosixPath(m.filename).parts))
        prefix = PurePosixPath(config_member.filename).parent

        chosen = [m for m in members if _relative_parts(m.filename, prefix)]
        if sum(m.file_size for m in chosen) > MAX_PACK_BYTES:
            raise SoundPackError(f"{zip_path.name} is larger than {MAX_PACK_BYTES // 2**20} MB")

        try:
            config = json.loads(archive.read(config_member).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SoundPackError(f"{zip_path.name}: {CONFIG_NAME} is not valid JSON") from exc
        name = str(config.get("name") or zip_path.stem) if isinstance(config, dict) else zip_path.stem

        dest_root.mkdir(parents=True, exist_ok=True)
        target = _unique_dir(dest_root, _slug(name))
        target.mkdir()
        for member in chosen:
            out = target.joinpath(*_relative_parts(member.filename, prefix))
            if not out.resolve().is_relative_to(target.resolve()):
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(archive.read(member))

    try:
        read_config(target)  # fail fast if the imported config is unusable
    except SoundPackError:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return PackInfo(pack_id=target.name, name=name, path=target)
