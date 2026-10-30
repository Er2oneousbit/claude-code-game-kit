#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_windows.py
# Purpose : window skins drawn in code: 9-slice PNG + NinePatchRect scene (classic blue, brass, iron, or custom fill
#           / frame colours).
# Usage   : pack spec "windows": [{"name": "classic", "style": "classic"}]
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import numpy as np
from PIL import Image

import fcore as core
from lane_ui import scene

STYLES = {
    "classic": {"fill": ["3048d8", "1a2a9c", "0c1660"], "frame": ["0a0a18", "f0f2fa", "c4cae0", "6a7298"], "rivets": False},
    "brass": {"fill": ["3a3446", "221e2c", "14121c"], "frame": ["1a0e08", "fff2b8", "e2aa3c", "c0842a", "6e4418"],
              "rivets": True},
    "iron": {"fill": ["3c4450", "262c34", "161a20"], "frame": ["0c0e12", "c8d4e0", "9aa8b8", "5a6676", "2a3038"],
             "rivets": True},
}


def _rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


def draw(fill, frame, rivets, size=24):
    """size x size skin at 1x: gradient fill, frame rings (outer first), corners cut by one pixel per ring."""
    n = len(frame)
    img = np.zeros((size, size, 4), np.uint8)
    stops = [_rgb(c) for c in fill]
    for y in range(size):
        t = y / (size - 1) * (len(stops) - 1)
        i = min(int(t), len(stops) - 2)
        c = stops[i] * (1 - (t - i)) + stops[i + 1] * (t - i)
        img[y, :, :3] = c.astype(np.uint8)
        img[y, :, 3] = 255
    for k, col in enumerate(frame):  # ring k: the k-th pixel in from the edge
        c = _rgb(col).astype(np.uint8)
        img[k, k:size - k, :3] = c
        img[size - 1 - k, k:size - k, :3] = c
        img[k:size - k, k, :3] = c
        img[k:size - k, size - 1 - k, :3] = c
    # cut corners: rounded look (transparent outside, frame colours follow the diagonal)
    for y in range(2):
        for x in range(2 - y):
            for (yy, xx) in ((y, x), (y, size - 1 - x), (size - 1 - y, x), (size - 1 - y, size - 1 - x)):
                img[yy, xx] = 0
    if rivets:  # 2x2 bright rivet with a dark fleck in each corner of the frame
        hi, lo = _rgb(frame[1]).astype(np.uint8), _rgb(frame[0]).astype(np.uint8)
        r = max(2, n // 2)
        for cy, cx in ((r, r), (r, size - r - 2), (size - r - 2, r), (size - r - 2, size - r - 2)):
            img[cy:cy + 2, cx:cx + 2, :3] = hi
            img[cy + 1, cx + 1, :3] = lo
    return img, n + 2  # patch margin: frame rings + rivet room


def run(entries, pack, man, conf):
    art = core.art(conf, "ui", "windows")
    src = core.src(conf, "art", "ui", "windows")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/ui/windows'
    os.makedirs(src, exist_ok=True)
    for e in entries:
        name = core.snake(e["name"])
        st = dict(STYLES.get(e.get("style", "classic"), STYLES["classic"]))
        st.update({k: e[k] for k in ("fill", "frame", "rivets") if k in e})
        scale = int(e.get("scale", 2))
        img, m = draw(st["fill"], st["frame"], st["rivets"], int(e.get("size", 24)))
        big = np.kron(img, np.ones((scale, scale, 1), np.uint8))
        p = core.save_clean(Image.fromarray(big), os.path.join(art, f"ui_window_{name}.png"))
        mm = {k: m * scale for k in ("left", "top", "right", "bottom")}
        scn = scene(os.path.join(art, f"ui_window_{name}.tscn"), f"{res}/ui_window_{name}.png", mm, big.shape[0])
        man.add(p, "ui_window", style=e.get("style", "custom"), scale=scale, patch_margins=mm, routes=(),
                workflow="Dotwork window skin (drawn in code)")
        man.add(scn, "scene", node="NinePatchRect", patch_margins=mm)
        core.log(f"window {name}: {big.shape[1]}x{big.shape[0]}, margins {m * scale}")
