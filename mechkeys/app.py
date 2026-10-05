"""Application controller: owns settings and wires engine, window and tray."""

from __future__ import annotations

import logging
import queue
import sys
import tkinter as tk
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

from . import settings as settings_store
from . import winutil
from .engine import SoundEngine
from .settings import Settings, app_data_dir
from .soundpack import PackInfo, SoundPackError, discover_packs, import_pack_zip
from .tray import Tray
from .ui import MainWindow
from .widgets import THEME

log = logging.getLogger("mechkeys")

TASK_POLL_MS = 30           # while the window is open
TASK_POLL_HIDDEN_MS = 120   # in the tray: fewer wakeups, still snappy for menu clicks
TICK_MS = 400
SAVE_DELAY_MS = 500
LOG_BYTES = 256 * 1024


def resource_root() -> Path:
    """Folder holding bundled assets, both from source and inside the .exe."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def setup_logging(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(data_dir / "mechkeys.log", maxBytes=LOG_BYTES, backupCount=1,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


class App:
    def __init__(self, start_hidden: bool):
        self.data_dir = app_data_dir()
        self.settings_path = self.data_dir / "settings.json"
        self.user_packs_dir = self.data_dir / "packs"
        self.start_hidden = start_hidden
        self.settings = self._sync_autostart(settings_store.load(self.settings_path))
        self.packs = self._discover()
        self._tasks: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._save_job: str | None = None
        self._audio_ok = True
        self._hook_ok = True
        self._told_about_tray = False
        self._closing = False

        self.engine = SoundEngine(self.settings, on_mute_hotkey=lambda: self.post(self._hotkey_mute))
        self.root = tk.Tk()
        self.root.withdraw()
        self._load_initial_pack()
        self.window = MainWindow(self.root, self)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.tray = Tray(self, self.post, on_open=self.show_window, on_restart_audio=self.restart_audio)

    # -- startup ---------------------------------------------------------- #
    def _sync_autostart(self, settings: Settings) -> Settings:
        """The registry is the source of truth; refresh the command if enabled."""
        try:
            enabled = winutil.autostart_enabled()
            if enabled:
                winutil.set_autostart(True)
        except OSError as exc:
            log.warning("Could not read autostart entry: %s", exc)
            return settings
        return settings.with_changes(start_with_windows=enabled)

    def _discover(self) -> list[PackInfo]:
        return discover_packs(resource_root() / "sounds", self.user_packs_dir)

    def _load_initial_pack(self) -> None:
        preferred = [p for p in self.packs if p.pack_id == self.settings.pack_id]
        others = [p for p in self.packs if p.pack_id != self.settings.pack_id]
        for info in preferred + others:
            try:
                self.engine.load_pack(info)
            except SoundPackError as exc:
                log.error("Pack %s failed to load: %s", info.pack_id, exc)
                continue
            self.settings = self.settings.with_changes(pack_id=info.pack_id)
            return
        messagebox.showerror("MechKeys", "No usable sound pack was found.\n"
                             "Import a Mechvibes pack (.zip) from the settings window.")

    def run(self) -> None:
        self._audio_ok, self._hook_ok = self.engine.start()
        self.tray.start()
        self.tray.refresh()
        if not self.start_hidden or not (self._audio_ok and self._hook_ok):
            self.show_window()
        self.root.after(TASK_POLL_MS, self._pump)
        self.root.after(TICK_MS, self._tick)
        self.root.mainloop()

    # -- threading -------------------------------------------------------- #
    def post(self, action: Callable[[], None]) -> None:
        """Queue work for the Tk thread; safe to call from any thread."""
        self._tasks.put(action)

    def _pump(self) -> None:
        while not self._tasks.empty():
            action = self._tasks.get_nowait()
            try:
                action()
            except Exception:
                log.exception("UI action failed")
        if not self._closing:
            self.root.after(self._poll_interval(), self._pump)

    def _poll_interval(self) -> int:
        return TASK_POLL_HIDDEN_MS if self._hidden() else TASK_POLL_MS

    def _hidden(self) -> bool:
        return self.root.state() == "withdrawn"

    def _tick(self) -> None:
        if self._closing:
            return
        if not self._hidden():
            self.window.tick()
        self.root.after(TICK_MS, self._tick)

    # -- state ------------------------------------------------------------ #
    def status(self) -> tuple[str, str]:
        if not self._hook_ok:
            return "Keyboard hook failed", THEME.danger
        if not self._audio_ok:
            return "No audio output", THEME.danger
        if self.settings.muted:
            return "Muted", THEME.subtle
        return "Active", THEME.ok

    def keystrokes(self) -> int:
        return self.engine.keystrokes

    def clicks(self) -> int:
        return self.engine.clicks

    def _update(self, **changes) -> None:
        updated = self.settings.with_changes(**changes)
        if updated == self.settings:
            return
        self.settings = updated
        self.engine.apply_settings(updated)
        self._schedule_save()
        self.window.refresh()
        self.tray.refresh()

    def _schedule_save(self) -> None:
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(SAVE_DELAY_MS, self._save)

    def _save(self) -> None:
        self._save_job = None
        try:
            settings_store.save(self.settings_path, self.settings)
        except OSError as exc:
            log.error("Saving settings failed: %s", exc)

    # -- actions (called on the Tk thread) -------------------------------- #
    def set_volume(self, volume: int) -> None:
        self._update(volume=volume, muted=False)

    def toggle_mute(self) -> None:
        self._update(muted=not self.settings.muted)

    def _hotkey_mute(self) -> None:
        self.toggle_mute()
        if self._hidden():
            self.tray.notify("Muted" if self.settings.muted else f"Sound on — {self.settings.volume}%")

    def set_pitch(self, percent: int) -> None:
        self._update(pitch_variation=percent)

    def set_mouse_volume(self, percent: int) -> None:
        self._update(mouse_volume=percent, mouse_sounds=percent > 0 or self.settings.mouse_sounds)

    def set_mouse_style(self, style: str) -> None:
        self._update(mouse_style=style, mouse_sounds=True)
        self.engine.preview_mouse()

    def set_release_volume(self, percent: int) -> None:
        self._update(release_volume=percent)

    def select_pack(self, pack_id: str) -> None:
        info = next((p for p in self.packs if p.pack_id == pack_id), None)
        if info is None:
            return
        try:
            self.engine.load_pack(info)
        except SoundPackError as exc:
            messagebox.showerror("MechKeys", f"Couldn't load “{info.name}”:\n{exc}")
            self.window.refresh()
            return
        self._update(pack_id=pack_id)
        self.engine.preview()

    def import_pack(self) -> None:
        chosen = filedialog.askopenfilename(
            parent=self.root, title="Import a Mechvibes sound pack",
            filetypes=[("Sound pack", "*.zip"), ("All files", "*.*")])
        if not chosen:
            return
        try:
            info = import_pack_zip(Path(chosen), self.user_packs_dir)
        except (SoundPackError, OSError) as exc:
            messagebox.showerror("MechKeys", f"Import failed:\n{exc}")
            return
        self.packs = self._discover()
        self.window.refresh()
        self.select_pack(info.pack_id)

    def preview(self) -> None:
        self.engine.preview()

    def set_option(self, name: str, value: bool) -> None:
        if name == "start_with_windows":
            try:
                winutil.set_autostart(value)
            except OSError as exc:
                messagebox.showerror("MechKeys", f"Couldn't change the startup setting:\n{exc}")
                self.window.refresh()
                return
        self._update(**{name: value})

    def restart_audio(self) -> None:
        try:
            self._audio_ok = self.engine.restart_audio()
        except SoundPackError as exc:
            log.error("Reloading pack after audio restart failed: %s", exc)
        self.window.refresh()
        self.tray.refresh()
        self.tray.notify("Audio restarted" if self._audio_ok else "Still no audio output device")

    def show_window(self) -> None:
        self.window.refresh()
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.focus_force()
        self.root.after(200, lambda: self.root.attributes("-topmost", False))

    def hide_window(self) -> None:
        self.root.withdraw()
        if not self._told_about_tray:
            self._told_about_tray = True
            self.tray.notify("Still clicking away in the tray. Right-click the keycap for options.")

    def _on_close(self) -> None:
        if self.settings.close_to_tray:
            self.hide_window()
        else:
            self.quit()

    def quit(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save()
        self.engine.stop()
        self.tray.stop()
        self.root.destroy()


def run(start_hidden: bool, instance: winutil.SingleInstance) -> None:
    """Start the full app; ``launcher.main`` has already claimed single-instance."""
    setup_logging(app_data_dir())
    winutil.enable_dpi_awareness()
    try:
        app = App(start_hidden=start_hidden)
        instance.listen(lambda: app.post(app.show_window))
        app.run()
    except Exception:
        log.exception("MechKeys crashed")
        raise