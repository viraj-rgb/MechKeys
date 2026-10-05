"""Notification-area (system tray) icon and its menu."""

from __future__ import annotations

import logging
from typing import Callable

import pystray
from pystray import Menu, MenuItem

from .dsp import MOUSE_STYLES
from .icon import keycap_image
from .ui import Controller

log = logging.getLogger(__name__)

VOLUME_PRESETS = (25, 50, 75, 100, 150, 200)


class Tray:
    """Menu callbacks arrive on pystray's thread, so every action goes
    through ``post`` to run on the Tk thread."""

    def __init__(self, controller: Controller, post: Callable[[Callable[[], None]], None],
                 on_open: Callable[[], None], on_restart_audio: Callable[[], None]):
        self.c = controller
        self._post = post
        self._images = {False: keycap_image(64), True: keycap_image(64, muted=True)}
        self._icon = pystray.Icon("MechKeys", self._images[False], "MechKeys", menu=Menu(
            MenuItem("Open MechKeys", self._run(on_open), default=True),
            Menu.SEPARATOR,
            MenuItem("Mute", self._run(self.c.toggle_mute), checked=lambda _i: self.c.settings.muted),
            MenuItem("Mouse click sounds", self._run(lambda: self.c.set_option("mouse_sounds", not self.c.settings.mouse_sounds)),
                     checked=lambda _i: self.c.settings.mouse_sounds),
            MenuItem("Mouse sound", Menu(lambda: self._mouse_items())),
            MenuItem("Volume", Menu(lambda: self._volume_items())),
            MenuItem("Sound pack", Menu(lambda: self._pack_items())),
            MenuItem("Restart audio", self._run(on_restart_audio)),
            Menu.SEPARATOR,
            MenuItem("Quit", self._run(self.c.quit)),
        ))

    def _run(self, action: Callable[[], None]):
        return lambda _icon=None, _item=None: self._post(action)

    def _volume_items(self):
        for level in VOLUME_PRESETS:
            yield MenuItem(f"{level}%", self._run(lambda v=level: self.c.set_volume(v)),
                           checked=lambda _i, v=level: self.c.settings.volume == v, radio=True)

    def _mouse_items(self):
        for style_id, style in MOUSE_STYLES.items():
            yield MenuItem(style.name, self._run(lambda s=style_id: self.c.set_mouse_style(s)),
                           checked=lambda _i, s=style_id: self.c.settings.mouse_style == s, radio=True)

    def _pack_items(self):
        for pack in self.c.packs:
            yield MenuItem(pack.name, self._run(lambda p=pack.pack_id: self.c.select_pack(p)),
                           checked=lambda _i, p=pack.pack_id: self.c.settings.pack_id == p, radio=True)

    def start(self) -> None:
        self._icon.run_detached()

    def refresh(self) -> None:
        settings = self.c.settings
        self._icon.icon = self._images[settings.muted]
        state = "muted" if settings.muted else f"{settings.volume}%"
        self._icon.title = f"MechKeys — {state}"
        try:
            self._icon.update_menu()
        except Exception as exc:  # the icon may not be visible yet
            log.debug("Tray menu refresh skipped: %s", exc)

    def notify(self, message: str) -> None:
        try:
            self._icon.notify(message, "MechKeys")
        except Exception as exc:
            log.debug("Tray notification failed: %s", exc)

    def stop(self) -> None:
        self._icon.stop()
