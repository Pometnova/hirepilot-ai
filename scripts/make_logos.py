"""One-off: cut assets/logo_dark.png into assets/logo_sidebar.png (full logo, margins removed) and assets/logo_icon.png
(icon only, no text). The dark background becomes transparent, so the logo sits on the sidebar colour without a visible box.
Also prints the background colour (median of the border pixels), which is the sidebar colour in web/theme.py.

    .venv/bin/python -I scripts/make_logos.py
The source image is only read. Free: no network, no API.
"""
from pathlib import Path

import numpy as np
from PIL import Image

ASSETS = Path(__file__).resolve().parents[1] / "assets"
SRC = ASSETS / "logo_dark.png"
PAD, DISPLAY_WIDTH, ICON_HEIGHT = 10, 170, 220
SIDEBAR_WIDTH = 2 * DISPLAY_WIDTH                           # web/theme.py LOGO_WIDTH; exported at 2x for retina screens


def background(rgb):
    frame = np.concatenate([rgb[:40].reshape(-1, 3), rgb[-40:].reshape(-1, 3), rgb[:, :40].reshape(-1, 3), rgb[:, -40:].reshape(-1, 3)])
    return np.median(frame, axis=0)


def cut(rgba, dist, box):
    x0, y0, x1, y1 = box
    out = rgba[y0:y1, x0:x1].copy()
    out[:, :, 3] = (np.clip((dist[y0:y1, x0:x1] - 14) / 20, 0, 1) * 255).astype(np.uint8)       # soft edge, background fades out
    return Image.fromarray(out, "RGBA")


def main():
    rgba = np.array(Image.open(SRC).convert("RGBA"))
    rgb = rgba[:, :, :3].astype(float)
    bg = background(rgb)
    dist = np.sqrt(((rgb - bg) ** 2).sum(axis=2))
    content = dist > 40
    ys, xs = np.where(content)
    full = (max(xs.min() - PAD, 0), max(ys.min() - PAD, 0), min(xs.max() + PAD, rgba.shape[1]), min(ys.max() + PAD, rgba.shape[0]))

    cols = (dist > 80).sum(axis=0) > 3                                  # first wide run of empty columns after the icon = the gap before the text
    start = int(np.argmax(cols))
    gap, run = start, 0
    for x in range(start, len(cols)):
        run = 0 if cols[x] else run + 1
        if run >= 20:
            gap = x - run + 1
            break
    rows = np.where(content[:, :gap].any(axis=1))[0]
    icon = (max(start - PAD, 0), max(int(rows.min()) - PAD, 0), gap, min(int(rows.max()) + PAD, rgba.shape[0]))

    sidebar = cut(rgba, dist, full)
    sidebar = sidebar.resize((SIDEBAR_WIDTH, round(sidebar.height * SIDEBAR_WIDTH / sidebar.width)), Image.LANCZOS)
    sidebar.save(ASSETS / "logo_sidebar.png", optimize=True)
    ic = cut(rgba, dist, icon)
    ic = ic.resize((round(ic.width * ICON_HEIGHT / ic.height), ICON_HEIGHT), Image.LANCZOS)
    ic.save(ASSETS / "logo_icon.png", optimize=True)
    print("background", "#%02X%02X%02X" % tuple(int(v) for v in bg))
    print("sidebar logo", sidebar.size, "icon", ic.size, "icon crop box", icon)


if __name__ == "__main__":
    main()
