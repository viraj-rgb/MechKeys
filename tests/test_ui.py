import tkinter as tk
from types import SimpleNamespace

import pytest

from mechkeys.settings import Settings
from mechkeys.soundpack import PackInfo
from mechkeys.ui import MainWindow


class FakeController:
    def __init__(self):
        self.settings = Settings()
        self.packs = [PackInfo("a", "Alpha", None), PackInfo("nk-cream", "NK Cream", None)]
        self.calls = []

    def status(self):
        return "Active", "#00ff00"

    def keystrokes(self):
        return 1

    def clicks(self):
        return 2

    def __getattr__(self, name):
        def record(*args):
            self.calls.append((name, *args))
            if name == "set_volume":
                self.settings = self.settings.with_changes(volume=args[0])
            if name == "toggle_mute":
                self.settings = self.settings.with_changes(muted=not self.settings.muted)
        return record


@pytest.fixture(scope="module")
def tk_root():
    # One interpreter per module: repeatedly creating Tk() is flaky on Windows.
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def window(tk_root):
    top = tk.Toplevel(tk_root)
    top.withdraw()
    controller = FakeController()
    win = MainWindow(top, controller)
    top.update_idletasks()
    yield win, controller
    top.destroy()


def test_window_reflects_settings(window):
    win, ctl = window
    assert win.volume_label.cget("text") == "70%"
    assert win.pack_box.get() == "NK Cream"
    assert win.counter.cget("text") == "1 keystroke  ·  2 clicks this session"
    assert "Active" in win.status.cget("text")


def test_slider_drag_and_keys_report_values(window):
    win, ctl = window
    width = win.volume.winfo_reqwidth()
    win.volume._seek(SimpleNamespace(x=width))
    assert ("set_volume", 200) in ctl.calls
    win.volume._nudge(-5)
    assert ("set_volume", 195) in ctl.calls
    win.volume._wheel(SimpleNamespace(delta=-120))
    win.volume._set_hover(True)
    win.volume._set_focus(True)


def test_mute_button_and_refresh(window):
    win, ctl = window
    win.mute_button._command()
    win.refresh()
    assert win.mute_button.cget("text") == "Unmute"


def test_toggle_reports_option(window):
    win, ctl = window
    win.toggles["close_to_tray"]._toggle()
    assert ("set_option", "close_to_tray", False) in ctl.calls


def test_pack_selection(window):
    win, ctl = window
    win.pack_box.current(0)
    win._on_pack_selected(None)
    assert ("select_pack", "a") in ctl.calls


def test_volume_boost_and_release_controls(window):
    win, ctl = window
    win.volume._seek(SimpleNamespace(x=win.volume.winfo_reqwidth()))
    assert ("set_volume", 200) in ctl.calls
    win.refresh()
    assert win.volume_label.cget("text") == "200%  boost"
    win.release._nudge(5)
    assert ("set_release_volume", 65) in ctl.calls
    assert win.release_label.cget("text").endswith("60%")


def test_mouse_controls(window):
    win, ctl = window
    win.toggles["mouse_sounds"]._toggle()
    assert ("set_option", "mouse_sounds", False) in ctl.calls
    win.mouse_volume._nudge(-5)
    assert ("set_mouse_volume", 65) in ctl.calls
    assert win.mouse_label.cget("text").endswith("70%")


def test_mouse_style_selection(window):
    win, ctl = window
    assert win.mouse_style_box.get() == "Classic micro-switch"
    win.mouse_volume._seek(SimpleNamespace(x=win.mouse_volume.winfo_reqwidth()))
    assert ("set_mouse_volume", 200) in ctl.calls
    win.mouse_style_box.current(4)
    win._on_mouse_style_selected(None)
    assert ("set_mouse_style", "bubble") in ctl.calls


def test_pitch_label_when_off(window):
    win, ctl = window
    ctl.settings = ctl.settings.with_changes(pitch_variation=0)
    win.refresh()
    assert win.pitch_label.cget("text").endswith("off")
