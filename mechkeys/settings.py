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


def load(path: Path) -> Settings:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Settings()
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        log.warning("Ignoring unreadable settings file %s: %s", path, exc)
        return Settings()
    if not isinstance(raw, dict):
        return Settings()
    known = {f.name for f in fields(Settings)}
    return validate(Settings(**{k: v for k, v in raw.items() if k in known}))


def save(path: Path, settings: Settings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    os.replace(tmp, path)
