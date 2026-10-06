"""User settings: an immutable dataclass persisted as JSON in %APPDATA%."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

from .dsp import DEFAULT_MOUSE_STYLE, MOUSE_STYLES

log = logging.getLogger(__name__)

APP_NAME = "MechKeys"
DEFAULT_PACK = "nk-cream"
MAX_VOLUME = 200                 # percent; above 100 is a boost


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_NAME


@dataclass(frozen=True)
class Settings:
    volume: int = 70                 # 0-MAX_VOLUME
    muted: bool = False
    pack_id: str = DEFAULT_PACK
    pitch_variation: int = 3         # percent, 0-15
    release_volume: int = 60         # key-release loudness, percent of press; 0 = off
    mouse_sounds: bool = True        # click sounds for mouse buttons
    mouse_volume: int = 70           # 0-MAX_VOLUME, on top of the main volume
    mouse_style: str = DEFAULT_MOUSE_STYLE
    ignore_key_repeat: bool = True   # held keys click once
    mute_hotkey: bool = True         # Ctrl+Alt+M toggles mute anywhere
    close_to_tray: bool = True
    start_with_windows: bool = False

    def with_changes(self, **changes) -> "Settings":
        return validate(replace(self, **changes))


def _clamp(value, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def validate(settings: Settings) -> Settings:
    """Return a copy with every field coerced into its legal range."""
    defaults = Settings()
    return Settings(
        volume=_clamp(settings.volume, 0, MAX_VOLUME, defaults.volume),
        muted=bool(settings.muted),
        pack_id=str(settings.pack_id or defaults.pack_id),
        pitch_variation=_clamp(settings.pitch_variation, 0, 15, defaults.pitch_variation),
        release_volume=_clamp(settings.release_volume, 0, 100, defaults.release_volume),
        mouse_sounds=bool(settings.mouse_sounds),
        mouse_volume=_clamp(settings.mouse_volume, 0, MAX_VOLUME, defaults.mouse_volume),
        mouse_style=settings.mouse_style if settings.mouse_style in MOUSE_STYLES else defaults.mouse_style,
        ignore_key_repeat=bool(settings.ignore_key_repeat),
        mute_hotkey=bool(settings.mute_hotkey),
        close_to_tray=bool(settings.close_to_tray),
        start_with_windows=bool(settings.start_with_windows),
    )


def _backup_path(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


def _pending_path(path: Path) -> Path:
    return path.with_name(path.name + ".tmp")


def _parse(path: Path) -> Settings | None:
    """Settings from one file, or None when it is missing, unreadable or not a settings object."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        log.warning("Cannot read settings file %s: %s", path, exc)
        return None
    if not isinstance(raw, dict):
        log.warning("Settings file %s is not a JSON object", path)
        return None
    known = {f.name for f in fields(Settings)}
    return validate(Settings(**{k: v for k, v in raw.items() if k in known}))


def _quarantine(path: Path) -> None:
    """Move an unreadable settings file aside so the next save can never silently destroy it."""
    if not path.exists():
        return
    target = path.with_name(path.stem + ".corrupt" + path.suffix)
    try:
        os.replace(path, target)
        log.warning("Moved unreadable settings to %s", target)
    except OSError as exc:
        log.warning("Could not set aside %s: %s", path, exc)


def load(path: Path) -> Settings:
    """Load settings, surviving a crash at any point of a save.

    A completed save leaves ``path``. A save interrupted mid-way leaves a finished
    ``.tmp`` (newest) or only the ``.bak`` copy of the previous version, so those
    are tried too, newest first.
    """
    for candidate in (_pending_path(path), path, _backup_path(path)):
        settings = _parse(candidate)
        if settings is None:
            if candidate == path:
                _quarantine(path)  # no-op when the file is merely missing
            continue
        if candidate != path:
            log.warning("Recovered settings from %s", candidate.name)
        return settings
    return Settings()


def save(path: Path, settings: Settings) -> None:
    """Write settings so that no instant of the sequence can lose them.

    New content goes to ``.tmp`` and is flushed to disk first; the previous file is
    kept as ``.bak`` until the new one is in place.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = _pending_path(path)
    with open(pending, "w", encoding="utf-8") as out:
        out.write(json.dumps(asdict(settings), indent=2))
        out.flush()
        os.fsync(out.fileno())
    if path.exists():
        os.replace(path, _backup_path(path))
    os.replace(pending, path)