"""The settings window."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Protocol

from PIL import ImageTk

from .dsp import MOUSE_STYLES
from .icon import keycap_image
from .settings import MAX_VOLUME, Settings
from .soundpack import PackInfo
from .widgets import THEME, FlatButton, Slider, Toggle

BASE_WIDTH = 760
MARGIN = 18
GAP = 12


class Controller(Protocol):
    settings: Settings
    packs: list[PackInfo]

    def status(self) -> tuple[str, str]: ...
    def keystrokes(self) -> int: ...
    def clicks(self) -> int: ...
    def set_mouse_volume(self, percent: int) -> None: ...
    def set_mouse_style(self, style: str) -> None: ...
    def set_volume(self, volume: int) -> None: ...
    def toggle_mute(self) -> None: ...
    def set_pitch(self, percent: int) -> None: ...
    def set_release_volume(self, percent: int) -> None: ...
    def select_pack(self, pack_id: str) -> None: ...
    def import_pack(self) -> None: ...
    def preview(self) -> None: ...
    def set_option(self, name: str, value: bool) -> None: ...
    def hide_window(self) -> None: ...
    def quit(self) -> None: ...


def _pick_family(root: tk.Tk, *candidates: str) -> str:
    available = set(tkfont.families(root))
    return next((c for c in candidates if c in available), "TkDefaultFont")


class MainWindow:
    def __init__(self, root: tk.Tk, controller: Controller):
        self.root = root
        self.c = controller
        self.s = root.winfo_fpixels("1i") / 96.0
        family = _pick_family(root, "Segoe UI Variable Text", "Segoe UI")
        display = _pick_family(root, "Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI")
        self.fonts = {
            "title": (display, 17, "bold"),
            "big": (display, 26, "bold"),
            "section": (family, 9, "bold"),
            "body": (family, 10),
            "small": (family, 9),
            "button": (family, 9, "bold"),
        }
        self._icon_images = [ImageTk.PhotoImage(keycap_image(n)) for n in (16, 32, 64)]
        self._header_icon = ImageTk.PhotoImage(keycap_image(int(40 * self.s)))
        self._configure_root()
        self._build()
        self.refresh()
        self.center()

    # -- setup ------------------------------------------------------------ #
    def _configure_root(self) -> None:
        r = self.root
        r.title("MechKeys")
        r.configure(bg=THEME.bg)
        r.iconphoto(True, *self._icon_images)
        r.resizable(False, False)
        style = ttk.Style(r)
        style.theme_use("clam")
        style.configure("Pack.TCombobox", fieldbackground=THEME.button, background=THEME.button,
                        foreground=THEME.text, arrowcolor=THEME.accent, bordercolor=THEME.card_border,
                        lightcolor=THEME.button, darkcolor=THEME.button, padding=int(5 * self.s))
        style.map("Pack.TCombobox", fieldbackground=[("readonly", THEME.button)],
                  foreground=[("readonly", THEME.text)], selectbackground=[("readonly", THEME.button)],
                  selectforeground=[("readonly", THEME.text)])
        r.option_add("*TCombobox*Listbox.background", THEME.card)
        r.option_add("*TCombobox*Listbox.foreground", THEME.text)
        r.option_add("*TCombobox*Listbox.selectBackground", THEME.accent)
        r.option_add("*TCombobox*Listbox.selectForeground", THEME.bg)
        r.option_add("*TCombobox*Listbox.font", self.fonts["body"])

    def _px(self, value: float) -> int:
        return int(value * self.s)

    def _card(self, parent, title: str, expand: bool = False) -> tk.Frame:
        outer = tk.Frame(parent, bg=THEME.card_border)
        outer.pack(fill="both", expand=expand, pady=(0, self._px(GAP)))
        inner = tk.Frame(outer, bg=THEME.card, padx=self._px(16), pady=self._px(12))
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(inner, text=title.upper(), font=self.fonts["section"], fg=THEME.subtle,
                 bg=THEME.card, anchor="w").pack(fill="x", pady=(0, self._px(6)))
        return inner

    def _build(self) -> None:
        self.toggles: dict[str, Toggle] = {}
        body = tk.Frame(self.root, bg=THEME.bg, padx=self._px(MARGIN), pady=self._px(16))
        body.pack(fill="both", expand=True)
        column_width = (BASE_WIDTH - 2 * MARGIN - GAP) / 2
        slider_width = self._px(column_width - 34)

        self._build_header(body)

        columns = tk.Frame(body, bg=THEME.bg)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure((0, 1), weight=1, uniform="column", minsize=self._px(column_width))
        columns.rowconfigure(0, weight=1)
        left = tk.Frame(columns, bg=THEME.bg)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, self._px(GAP / 2)))
        right = tk.Frame(columns, bg=THEME.bg)
        right.grid(row=0, column=1, sticky="nsew", padx=(self._px(GAP / 2), 0))

        self._build_volume(left, slider_width)
        self._build_pack(left)
        self._build_feel(right, slider_width)
        self._build_behaviour(right)
        self._build_footer(body)

    def center(self) -> None:
        r = self.root
        r.update_idletasks()
        w, h = r.winfo_reqwidth(), r.winfo_reqheight()
        x = max(0, (r.winfo_screenwidth() - w) // 2)
        y = max(0, (r.winfo_screenheight() - h) // 2 - self._px(20))
        r.geometry(f"+{x}+{y}")

    def _build_header(self, body) -> None:
        header = tk.Frame(body, bg=THEME.bg)
        header.pack(fill="x", pady=(0, self._px(14)))
        tk.Label(header, image=self._header_icon, bg=THEME.bg).pack(side="left")
        titles = tk.Frame(header, bg=THEME.bg)
        titles.pack(side="left", padx=(self._px(10), 0))
        tk.Label(titles, text="MechKeys", font=self.fonts["title"], fg=THEME.text, bg=THEME.bg,
                 anchor="w").pack(fill="x")
        tk.Label(titles, text="Mechanical keyboard sounds, everywhere", font=self.fonts["small"],
                 fg=THEME.subtle, bg=THEME.bg, anchor="w").pack(fill="x")
        self.status = tk.Label(header, font=self.fonts["button"], bg=THEME.card, padx=self._px(10),
                               pady=self._px(4))
        self.status.pack(side="right")

    def _build_volume(self, body, width: int) -> None:
        card = self._card(body, "Volume")
        row = tk.Frame(card, bg=THEME.card)
        row.pack(fill="x")
        self.volume_label = tk.Label(row, font=self.fonts["big"], fg=THEME.text, bg=THEME.card, anchor="w")
        self.volume_label.pack(side="left")
        self.mute_button = FlatButton(row, text="Mute", command=self.c.toggle_mute, fonts=self.fonts,
                                      scale=self.s)
        self.mute_button.pack(side="right")
        self.volume = Slider(card, minimum=0, maximum=MAX_VOLUME, value=self.c.settings.volume,
                             on_change=self.c.set_volume, width=width, scale=self.s, step=5, mark=100)
        self.volume.pack(fill="x", pady=(self._px(4), 0))

        mouse = Toggle(card, title="Mouse click sounds", detail="Left, right, middle and side buttons.",
                       value=self.c.settings.mouse_sounds,
                       on_change=lambda v: self.c.set_option("mouse_sounds", v), fonts=self.fonts, scale=self.s)
        mouse.pack(fill="x", pady=(self._px(14), 0))
        self.toggles["mouse_sounds"] = mouse
        mouse_row = tk.Frame(card, bg=THEME.card)
        mouse_row.pack(fill="x", pady=(self._px(8), 0))
        self.mouse_label = tk.Label(mouse_row, font=self.fonts["small"], fg=THEME.subtle, bg=THEME.card, anchor="w")
        self.mouse_label.pack(side="left")
        self._mouse_style_ids = list(MOUSE_STYLES)
        self.mouse_style_box = ttk.Combobox(mouse_row, state="readonly", style="Pack.TCombobox", width=20,
                                            font=self.fonts["small"],
                                            values=[s.name for s in MOUSE_STYLES.values()])
        self.mouse_style_box.pack(side="right")
        self.mouse_style_box.bind("<<ComboboxSelected>>", self._on_mouse_style_selected)
        self.mouse_volume = Slider(card, minimum=0, maximum=MAX_VOLUME, value=self.c.settings.mouse_volume,
                                   on_change=self.c.set_mouse_volume, width=width, scale=self.s, step=5, mark=100)
        self.mouse_volume.pack(fill="x")

    def _build_pack(self, body) -> None:
        card = self._card(body, "Sound pack", expand=True)
        self.pack_var = tk.StringVar()
        self.pack_box = ttk.Combobox(card, textvariable=self.pack_var, state="readonly", height=18,
                                     style="Pack.TCombobox", font=self.fonts["body"])
        self.pack_box.pack(fill="x")
        self.pack_box.bind("<<ComboboxSelected>>", self._on_pack_selected)
        buttons = tk.Frame(card, bg=THEME.card)
        buttons.pack(fill="x", pady=(self._px(10), 0))
        FlatButton(buttons, text="Preview", command=self.c.preview, fonts=self.fonts,
                   scale=self.s, primary=True).pack(side="left")
        FlatButton(buttons, text="Import pack (.zip)…", command=self.c.import_pack, fonts=self.fonts,
                   scale=self.s).pack(side="left", padx=(self._px(8), 0))

        tk.Label(card, text="TRY IT", font=self.fonts["section"], fg=THEME.subtle, bg=THEME.card,
                 anchor="w").pack(fill="x", pady=(self._px(16), self._px(6)))
        self.try_box = tk.Entry(card, font=self.fonts["body"], bg=THEME.button, fg=THEME.text,
                                insertbackground=THEME.accent, relief="flat", highlightthickness=1,
                                highlightbackground=THEME.card_border, highlightcolor=THEME.accent_deep)
        self.try_box.pack(fill="x", ipady=self._px(6))
        self.try_box.insert(0, "Type here, or anywhere else…")
        self.try_box.bind("<FocusIn>", lambda _e: self.try_box.select_range(0, "end"))

    def _build_feel(self, body, width: int) -> None:
        card = self._card(body, "Feel")
        self.pitch_label = tk.Label(card, font=self.fonts["body"], fg=THEME.text, bg=THEME.card, anchor="w")
        self.pitch_label.pack(fill="x")
        tk.Label(card, text="Slight random pitch shift so repeated keys don't sound robotic.",
                 font=self.fonts["small"], fg=THEME.subtle, bg=THEME.card, anchor="w").pack(fill="x")
        self.pitch = Slider(card, minimum=0, maximum=15, value=self.c.settings.pitch_variation,
                            on_change=self.c.set_pitch, width=width, scale=self.s)
        self.pitch.pack(fill="x", pady=(self._px(4), 0))

        self.release_label = tk.Label(card, font=self.fonts["body"], fg=THEME.text, bg=THEME.card, anchor="w")
        self.release_label.pack(fill="x", pady=(self._px(10), 0))
        tk.Label(card, text="The softer “clack” when a key comes back up.",
                 font=self.fonts["small"], fg=THEME.subtle, bg=THEME.card, anchor="w").pack(fill="x")
        self.release = Slider(card, minimum=0, maximum=100, value=self.c.settings.release_volume,
                              on_change=self.c.set_release_volume, width=width, scale=self.s, step=5)
        self.release.pack(fill="x", pady=(self._px(4), 0))

    def _build_behaviour(self, body) -> None:
        card = self._card(body, "Behaviour", expand=True)
        rows = [
            ("ignore_key_repeat", "One click per press", "Holding a key won't machine-gun clicks."),
            ("mute_hotkey", "Ctrl + Alt + M to mute", "Toggle sound from any app."),
            ("start_with_windows", "Launch at startup", "Start quietly in the tray when you sign in."),
            ("close_to_tray", "Close to tray", "The X button hides the window instead of quitting."),
        ]
        for index, (name, title, detail) in enumerate(rows):
            toggle = Toggle(card, title=title, detail=detail, value=getattr(self.c.settings, name),
                            on_change=lambda v, n=name: self.c.set_option(n, v), fonts=self.fonts,
                            scale=self.s)
            toggle.pack(fill="x", pady=(0 if index == 0 else self._px(8), 0))
            self.toggles[name] = toggle

    def _build_footer(self, body) -> None:
        footer = tk.Frame(body, bg=THEME.bg)
        footer.pack(fill="x", pady=(self._px(4), 0))
        self.counter = tk.Label(footer, font=self.fonts["small"], fg=THEME.subtle, bg=THEME.bg, anchor="w")
        self.counter.pack(side="left")
        FlatButton(footer, text="Quit", command=self.c.quit, fonts=self.fonts,
                   scale=self.s).pack(side="right")
        FlatButton(footer, text="Hide to tray", command=self.c.hide_window, fonts=self.fonts,
                   scale=self.s).pack(side="right", padx=(0, self._px(8)))

    # -- updates ---------------------------------------------------------- #
    def _on_pack_selected(self, _event) -> None:
        index = self.pack_box.current()
        if 0 <= index < len(self.c.packs):
            self.c.select_pack(self.c.packs[index].pack_id)
        self.pack_box.selection_clear()

    def _on_mouse_style_selected(self, _event) -> None:
        index = self.mouse_style_box.current()
        if 0 <= index < len(self._mouse_style_ids):
            self.c.set_mouse_style(self._mouse_style_ids[index])
        self.mouse_style_box.selection_clear()

    def refresh(self) -> None:
        settings = self.c.settings
        self.volume.set(settings.volume)
        boosted = settings.volume > 100
        self.volume_label.configure(text=f"{settings.volume}%" + ("  boost" if boosted else ""),
                                    fg=THEME.subtle if settings.muted else THEME.accent if boosted else THEME.text)
        self.mute_button.set_text("Unmute" if settings.muted else "Mute")
        self.pitch.set(settings.pitch_variation)
        variation = settings.pitch_variation
        self.pitch_label.configure(text=f"Pitch variation  ±{variation}%" if variation else "Pitch variation  off")
        self.mouse_volume.set(settings.mouse_volume)
        self.mouse_style_box.current(self._mouse_style_ids.index(settings.mouse_style))
        mouse_boost = "  boost" if settings.mouse_volume > 100 else ""
        self.mouse_label.configure(text=f"Volume  {settings.mouse_volume}%{mouse_boost}" if settings.mouse_sounds
                                   else "Volume  (off)", fg=THEME.accent if mouse_boost else THEME.subtle)
        self.release.set(settings.release_volume)
        release = settings.release_volume
        self.release_label.configure(text=f"Key release sound  {release}%" if release else "Key release sound  off")
        for name, toggle in self.toggles.items():
            toggle.set(getattr(settings, name))

        names = [p.name for p in self.c.packs]
        self.pack_box.configure(values=names)
        ids = [p.pack_id for p in self.c.packs]
        if settings.pack_id in ids:
            self.pack_box.current(ids.index(settings.pack_id))

        text, color = self.c.status()
        self.status.configure(text=f"●  {text}", fg=color)
        self.tick()

    def tick(self) -> None:
        keys, clicks = self.c.keystrokes(), self.c.clicks()
        self.counter.configure(text=f"{keys:,} keystroke{'s' if keys != 1 else ''}  ·  "
                                    f"{clicks:,} click{'s' if clicks != 1 else ''} this session")
