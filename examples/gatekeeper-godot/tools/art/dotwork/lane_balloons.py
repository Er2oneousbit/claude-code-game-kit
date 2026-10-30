#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_balloons.py
# Purpose : emote balloons (! ? ... heart note sweat star) drawn in code at sprite scale with a coloured glyph, plus
#           a 2-frame pop SpriteFrames.
# Usage   : pack spec "balloons": [{"name": "exclaim", "symbol": "!", "color": "d83a3a"}]
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import numpy as np
from PIL import Image

import fcore as core
import godot
import lane_fonts

FILL, INK = (246, 246, 250, 255), (34, 32, 46, 255)


def bubble(w, h, tail=3):
    """w x (h + tail) RGBA: rounded box (corners cut 2 px), 1 px dark outline, tail pointing down-left."""
    a = np.zeros((h + tail, w, 4), np.uint8)
    box = np.zeros((h, w), bool)
    box[:, :] = True
    for y, cut in ((0, 2), (1, 1), (h - 2, 1), (h - 1, 2)):
        box[y, :cut] = box[y, w - cut:] = False
    full = np.zeros((h + tail, w), bool)
    full[:h] = box
    for k in range(tail):  # tail: a small wedge under the left third
        x0 = w // 4
        full[h + k, x0:x0 + tail - k] = True
    edge = full & ~(np.roll(full, 1, 0) & np.roll(full, -1, 0) & np.roll(full, 1, 1) & np.roll(full, -1, 1))
    edge[0, :] |= full[0, :]
    edge[:, 0] |= full[:, 0]
    edge[:, -1] |= full[:, -1]
    a[full] = FILL
    a[edge] = INK
    return a


def run(entries, pack, man, conf):
    art = core.art(conf, "ui", "balloons")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/ui/balloons'
    meta, glyphs = lane_fonts.parse(os.path.join(core.HERE, "glyphs", "symbols.txt"))
    _, dia = lane_fonts.parse(os.path.join(core.HERE, "glyphs", "dialogue.txt"))
    man.drop_owned(art, ("ui_balloon_", "balloon_"))   # a shared folder
    for e in entries:
        name = core.snake(e["name"])
        g = glyphs.get(e["symbol"]) if e["symbol"] in glyphs else dia[e["symbol"]]
        ys, xs = np.nonzero(g)
        g = g[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        gh, gw = g.shape
        w, h = max(14, gw + 8), max(12, gh + 6)
        big = bubble(w, h)
        col = np.array([int(e.get("color", "22202e")[i:i + 2], 16) for i in (0, 2, 4)] + [255], np.uint8)
        oy, ox = (h - gh) // 2, (w - gw) // 2
        big[oy:oy + gh, ox:ox + gw][g] = col
        # pop frame: the same balloon squashed to 2/3 height, sitting on the same tail tip
        small = np.array(Image.fromarray(big).resize((w, max(4, (h + 3) * 2 // 3)), Image.NEAREST))
        pop = np.zeros_like(big)
        pop[-small.shape[0]:] = small
        f0 = core.save_clean(Image.fromarray(pop), os.path.join(art, f"ui_balloon_{name}_pop.png"))
        f1 = core.save_clean(Image.fromarray(big), os.path.join(art, f"ui_balloon_{name}.png"))
        man.add(f1, "ui_balloon", symbol=e["symbol"], size=[w, h + 3], scale=1, anchor="tail_tip_bottom_left_third",
                routes=(), workflow="Dotwork balloon (drawn in code + authored glyph)")
        man.add(f0, "frame", animation="pop", size=[w, h + 3])
        tres = godot.sprite_frames(os.path.join(art, f"balloon_{name}_frames.tres"), res,
                                   {"pop": ([os.path.basename(f0), os.path.basename(f1)], 10, False)})
        man.add(tres, "sprite_frames", animations=["pop"], node="AnimatedSprite2D")
        core.log(f"balloon {name}: {w}x{h + 3}")
