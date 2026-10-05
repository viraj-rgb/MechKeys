# MechKeys

Mechanical keyboard and mouse sounds for every key you press and every button you click, in any app on Windows. It runs
in the system tray and ships with 17 keyboard packs and 5 mouse click styles.

## Sounds

| Keyboard pack | Source |
|---|---|
| NK Cream, NK Cream (Full Travel), Cherry MX Blue / Brown / Red / Black, Topre Purple Hybrid, EG Crystal Purple, EG Oreo, Holy Pandas, Turquoise, MX Blue (Full Travel) | Recorded, from [Mechvibes](https://github.com/hainguyents13/mechvibes) (MIT) |
| Typewriter, Bubble Pop, Laptop Keyboard, Deep Thock, Arcade Blips | Synthesized by `tools/make_synth_packs.py` |

**Mouse styles** are synthesized in `dsp.py`: Classic micro-switch, Crisp gaming, Soft / silent switch, Retro clacky, Bubble pop.

You pick the pack and the mouse style from the window or from the tray menu. Each new choice plays a short preview.

## Download

Get **`MechKeys-Windows.zip`** from the [latest release](../../releases/latest), unzip it anywhere, and run `MechKeys.exe`. Windows 10/11, 64-bit; nothing to install.

> **Windows may warn you.** The app is not code-signed, so SmartScreen can show "Windows protected your PC" (click *More info*, then *Run anyway*), and some antivirus tools are suspicious of any program that listens to the keyboard. MechKeys only listens for key and mouse-button *presses* to play sounds. It never records, stores or sends what you type, and it makes no network connections. The source is all in this repo if you'd like to check or build it yourself.

## Run it

- **Packaged:** unzip the download and double-click `MechKeys.exe`. Keep the `_internal` folder next to it.
- **From source:** `pip install -r requirements.txt`, then double-click `MechKeys.pyw`
  (or run `python -m mechkeys`).

Add `--minimized` to start hidden in the tray.

## Features

| | |
|---|---|
| System-wide | A low-level keyboard hook hears keys in every app. It only listens and never blocks or changes your input. |
| Low latency | WASAPI shared-mode output (about 10–25 ms), with MME as the fallback. |
| Per-key sounds | Each key plays its own sample from the pack's `config.json`, including arrows, numpad and modifiers. |
| Volume and mute | 0–200%. Anything above 100% is a boost (about 3× at 200%), and a soft limiter keeps loud chords from crackling. A slider in the window, presets in the tray menu, and **Ctrl+Alt+M** from anywhere. |
| Key release sound | Plays a softer, brighter `clack` when a key comes back up. It's made from each key's press sample, and its loudness is adjustable (0 turns it off). |
| Natural feel | Optional random pitch shift (±0–15%), a little gain jitter, and leading silence trimmed so each click lands on time. |
| One click per press | Holding a key down doesn't machine-gun clicks. You can turn this off. |
| Tray | Left-click opens the window. Right-click gives mute, volume, sound pack, restart audio and quit. |
| Close to tray | The X button hides the window, and launching it again brings the window back (single instance). |
| Launch at startup | Adds or removes a per-user `Run` registry entry. No admin rights needed. |
| Mouse clicks | Left, right, middle and side buttons each get a press and a release sound in your chosen style, with their own volume. Raw Input is used rather than a hook, so the cursor is never delayed. |
| More packs | **Import pack (.zip)** accepts any Mechvibes pack, v1 or v2, in WAV, OGG or MP3. |

Windows 11 hides new tray icons in the `^` overflow at first. To keep it visible, drag
the keycap onto the taskbar, or turn it on under *Settings › Personalization › Taskbar ›
Other system tray icons*.

## Resource use

Measured in the tray on a 24-core PC:

| | |
|---|---|
| Memory | About 49 MB private, 77 MB working set |
| CPU, idle | About 0.4% of one core. The audio stream pauses after 5 s of silence and resumes in about 1 ms on the next key. |
| CPU, typing 8 keys/s | About 2.4% of one core |
| Startup | About 0.8 s cold. A second launch hands off to the running copy in about 0.3 s. |

## Files

- Settings: `%APPDATA%\MechKeys\settings.json`
- Imported packs: `%APPDATA%\MechKeys\packs\`
- Log: `%APPDATA%\MechKeys\mechkeys.log`

## Development

```powershell
pip install -r requirements-dev.txt
python -m pytest --cov=mechkeys      # tests
.\build.ps1                          # tests, then dist\MechKeys\MechKeys.exe
```

| Module | Role |
|---|---|
| `hook.py` | Win32 `WH_KEYBOARD_LL` hook on its own message-loop thread |
| `mouse.py` | Raw Input mouse-button listener on a hidden message-only window |
| `keycodes.py` | Windows scan code to Mechvibes/uiohook key code |
| `soundpack.py` | Pack discovery, WAV decoding, resampling, safe zip import |
| `mixer.py` | Polyphonic numpy mixer on a `sounddevice` stream |
| `dsp.py` | Pitch shift, soft limiter, release-sound derivation |
| `engine.py` | Hook to pack to mixer; repeat filter, hotkey, pitch shift |
| `app.py` | Controller: settings, threading, window and tray wiring |
| `ui.py`, `widgets.py` | Tk settings window and custom dark widgets |
| `tray.py` | `pystray` icon and menu |
| `winutil.py` | Autostart, single instance, DPI awareness |

Recorded packs come from the Mechvibes project (MIT). Run `python tools/fetch_mechvibes_packs.py` to download them again.

## License

MIT, see [LICENSE](LICENSE). Sound pack credits are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
