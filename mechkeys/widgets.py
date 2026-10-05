"""Flat, dark custom Tk widgets: slider, toggle switch and button."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Theme:
    bg: str = "#141317"
    card: str = "#1e1c22"
    card_border: str = "#2a272f"
    text: str = "#efe8dc"
    subtle: str = "#8e8880"
    track: str = "#34313a"
    accent: str = "#e6d3b1"
    accent_deep: str = "#c9a878"
    knob: str = "#fbf6ec"
    danger: str = "#e2685a"
    ok: str = "#8fc98a"
    button: str = "#2b2830"
    button_hover: str = "#38343e"


THEME = Theme()


class Slider(tk.Canvas):
    """Horizontal slider with click-to-seek, drag, wheel and arrow keys."""

    def __init__(self, master, *, minimum: int, maximum: int, value: int,
                 on_change: Callable[[int], None], width: int, scale: float, step: int = 1,
                 mark: int | None = None):
        self._s = scale
        height = int(26 * scale)
        super().__init__(master, width=width, height=height, bg=THEME.card,
                         highlightthickness=0, bd=0, takefocus=1, cursor="hand2")
        self._min, self._max, self._step = minimum, maximum, step
        self._mark = mark  # optional reference tick, e.g. 100% on a boostable volume
        self._value = value
        self._on_change = on_change
        self._hover = False
        self._focused = False
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._seek)
        self.bind("<B1-Motion>", self._seek)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Left>", lambda _e: self._nudge(-step))
        self.bind("<Right>", lambda _e: self._nudge(step))
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<FocusIn>", lambda _e: self._set_focus(True))
        self.bind("<FocusOut>", lambda _e: self._set_focus(False))
        self._draw()

    @property
    def value(self) -> int:
        return self._value

    def set(self, value: int) -> None:
        """Update the displayed value without firing the callback."""
        self._value = max(self._min, min(self._max, int(value)))
        self._draw()

    def _commit(self, value: int) -> None:
        clamped = max(self._min, min(self._max, int(round(value))))
        if clamped != self._value:
            self._value = clamped
            self._draw()
            self._on_change(clamped)

    def _pad(self) -> int:
        return int(10 * self._s)

    def _seek(self, event) -> None:
        self.focus_set()
        usable = max(1, self.winfo_width() - 2 * self._pad())
        frac = (event.x - self._pad()) / usable
        self._commit(self._min + frac * (self._max - self._min))

    def _wheel(self, event) -> None:
        self._nudge(self._step if event.delta > 0 else -self._step)

    def _nudge(self, delta: int) -> None:
        self._commit(self._value + delta)

    def _set_hover(self, hover: bool) -> None:
        self._hover = hover
        self._draw()

    def _set_focus(self, focused: bool) -> None:
        self._focused = focused
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        s, pad = self._s, self._pad()
        w, h = max(self.winfo_width(), int(self["width"])), int(self["height"])
        cy = h // 2
        track_h = max(4, int(6 * s))
        frac = (self._value - self._min) / max(1, self._max - self._min)
        x = pad + frac * (w - 2 * pad)

        self._pill(pad, cy - track_h / 2, w - pad, cy + track_h / 2, THEME.track)
        if x > pad:
            self._pill(pad, cy - track_h / 2, x, cy + track_h / 2, THEME.accent)
        if self._mark is not None:
            mark_frac = (self._mark - self._min) / max(1, self._max - self._min)
            mx = pad + mark_frac * (w - 2 * pad)
            tick = track_h * 1.6
            self.create_line(mx, cy - tick, mx, cy + tick, fill=THEME.subtle, width=max(1, int(2 * s)))
        r = (9 if self._hover or self._focused else 8) * s
        if self._focused:
            self.create_oval(x - r - 3 * s, cy - r - 3 * s, x + r + 3 * s, cy + r + 3 * s,
                             outline=THEME.accent_deep, width=max(1, int(1.5 * s)))
        self.create_oval(x - r, cy - r, x + r, cy + r, fill=THEME.knob, outline="")

    def _pill(self, x0, y0, x1, y1, color) -> None:
        r = (y1 - y0) / 2
        self.create_oval(x0, y0, x0 + 2 * r, y1, fill=color, outline="")
        self.create_oval(x1 - 2 * r, y0, x1, y1, fill=color, outline="")
        if x1 - x0 > 2 * r:
            self.create_rectangle(x0 + r, y0, x1 - r, y1, fill=color, outline="")


class Toggle(tk.Frame):
    """A labelled on/off switch row. Click anywhere on the row, or Space."""

    def __init__(self, master, *, title: str, detail: str, value: bool,
                 on_change: Callable[[bool], None], fonts: dict, scale: float):
        super().__init__(master, bg=THEME.card, cursor="hand2", takefocus=1)
        self._s = scale
        self._value = value
        self._on_change = on_change
        text = tk.Frame(self, bg=THEME.card)
        text.pack(side="left", fill="x", expand=True)
        self._title = tk.Label(text, text=title, font=fonts["body"], fg=THEME.text, bg=THEME.card, anchor="w")
        self._title.pack(fill="x")
        self._detail = tk.Label(text, text=detail, font=fonts["small"], fg=THEME.subtle, bg=THEME.card,
                                anchor="w", justify="left")
        self._detail.pack(fill="x")
        self._switch = tk.Canvas(self, width=int(40 * scale), height=int(22 * scale),
                                 bg=THEME.card, highlightthickness=0, bd=0)
        self._switch.pack(side="right", padx=(int(12 * scale), 0))
        for widget in (self, text, self._title, self._detail, self._switch):
            widget.bind("<Button-1>", self._toggle)
        self.bind("<space>", self._toggle)
        self.bind("<FocusIn>", lambda _e: self._title.configure(fg=THEME.accent))
        self.bind("<FocusOut>", lambda _e: self._title.configure(fg=THEME.text))
        self._draw()

    def set(self, value: bool) -> None:
        self._value = bool(value)
        self._draw()

    def _toggle(self, _event=None) -> None:
        self.focus_set()
        self._value = not self._value
        self._draw()
        self._on_change(self._value)

    def _draw(self) -> None:
        c, s = self._switch, self._s
        c.delete("all")
        w, h = int(c["width"]), int(c["height"])
        color = THEME.accent if self._value else THEME.track
        c.create_oval(0, 0, h, h, fill=color, outline="")
        c.create_oval(w - h, 0, w, h, fill=color, outline="")
        c.create_rectangle(h / 2, 0, w - h / 2, h, fill=color, outline="")
        inset = 3 * s
        x = w - h + inset if self._value else inset
        knob = THEME.bg if self._value else THEME.subtle
        c.create_oval(x, inset, x + h - 2 * inset, h - inset, fill=knob, outline="")


class FlatButton(tk.Label):
    def __init__(self, master, *, text: str, command: Callable[[], None], fonts: dict,
                 scale: float, primary: bool = False):
        self._normal = THEME.accent if primary else THEME.button
        self._hover = THEME.knob if primary else THEME.button_hover
        fg = THEME.bg if primary else THEME.text
        super().__init__(master, text=text, font=fonts["button"], fg=fg, bg=self._normal,
                         padx=int(14 * scale), pady=int(6 * scale), cursor="hand2", takefocus=1)
        self._command = command
        self.bind("<Button-1>", lambda _e: self._command())
        self.bind("<Return>", lambda _e: self._command())
        self.bind("<space>", lambda _e: self._command())
        self.bind("<Enter>", lambda _e: self.configure(bg=self._hover))
        self.bind("<Leave>", lambda _e: self.configure(bg=self._normal))
        self.bind("<FocusIn>", lambda _e: self.configure(bg=self._hover))
        self.bind("<FocusOut>", lambda _e: self.configure(bg=self._normal))

    def set_text(self, text: str) -> None:
        self.configure(text=text)
