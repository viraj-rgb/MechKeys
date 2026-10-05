"""Draws the keycap icon used for the window, the tray and the .exe."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

CAP_SIDE = (176, 150, 118, 255)
CAP_TOP = (236, 222, 196, 255)
CAP_TOP_MUTED = (120, 116, 110, 255)
CAP_SIDE_MUTED = (78, 75, 71, 255)
LEGEND = (92, 70, 52, 255)
SLASH = (226, 84, 70, 255)
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def keycap_image(size: int = 64, muted: bool = False) -> Image.Image:
    """A cream keycap seen from above, with a red slash when muted."""
    scale = 4  # draw large, then downsample for smooth edges
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    side = CAP_SIDE_MUTED if muted else CAP_SIDE
    top = CAP_TOP_MUTED if muted else CAP_TOP
    pad = int(s * 0.06)
    draw.rounded_rectangle([pad, pad, s - pad, s - pad], radius=int(s * 0.2), fill=side)
    inset = int(s * 0.17)
    draw.rounded_rectangle(
        [inset, int(s * 0.12), s - inset, s - int(s * 0.25)], radius=int(s * 0.14), fill=top
    )

    # small legend bar, like the bump on an F/J key
    bar_w, bar_h = int(s * 0.22), int(s * 0.05)
    cx, cy = s // 2, int(s * 0.55)
    draw.rounded_rectangle([cx - bar_w // 2, cy, cx + bar_w // 2, cy + bar_h], radius=bar_h // 2, fill=LEGEND)

    if muted:
        width = int(s * 0.09)
        draw.line([int(s * 0.18), int(s * 0.82), int(s * 0.82), int(s * 0.18)], fill=SLASH, width=width)

    return img.resize((size, size), Image.LANCZOS)


def write_ico(path: Path) -> None:
    keycap_image(256).save(path, format="ICO", sizes=ICO_SIZES)


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "assets" / "mechkeys.ico"
    target.parent.mkdir(exist_ok=True)
    write_ico(target)
    print(f"wrote {target}")
