#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# battle_mock.py
# Purpose : compose a 640x360 battle screen from the game's own Dotwork art (background, enemies, a party pose,
#           windows, fonts, ATB bar, damage numbers) to judge a set together; a preview, not a shipped asset.
# Usage   : dotwork.py preview battle --char guard --bg mine --enemies hound rat --pose ready [--window classic]
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import argparse
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fcore as core  # noqa: E402
import lane_fonts  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def nine(path, w, h, m):
    """9-slice a window skin to w x h (corners kept, edges + centre stretched with nearest)."""
    s = Image.open(path).convert("RGBA")
    S = s.width
    out = Image.new("RGBA", (w, h))
    xs, ys = [0, m, S - m, S], [0, m, S - m, S]
    tx, ty = [0, m, w - m, w], [0, m, h - m, h]
    for i in range(3):
        for j in range(3):
            part = s.crop((xs[j], ys[i], xs[j + 1], ys[i + 1]))
            out.paste(part.resize((tx[j + 1] - tx[j], ty[i + 1] - ty[i]), Image.NEAREST), (tx[j], ty[i]))
    return out


class Font:
    def __init__(self, glyphs, scale=2, effect="shadow", gradient=None, caps_only=False):
        self.meta, g = lane_fonts.parse(os.path.join(HERE, "glyphs", glyphs))
        if caps_only:
            for c in "abcdefghijklmnopqrstuvwxyz":
                g.setdefault(c, g.get(c.upper()))
        self.g = {c: a for c, a in g.items() if a is not None}
        self.scale = scale
        self.r = {c: lane_fonts.render_glyph(a, scale, effect, gradient, self.meta["height"]) for c, a in self.g.items()}

    def draw(self, img, text, x, y):
        for c in text:
            if c in self.r:
                im, lead = self.r[c]
                img.alpha_composite(Image.fromarray(im), (x - lead * self.scale, y - lead * self.scale))
                x += (self.g[c].shape[1] + self.meta["spacing"]) * self.scale
            else:
                x += self.meta["space"] * self.scale
        return x


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dotwork.py preview battle", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bg", default="mine_cave")
    ap.add_argument("--enemies", nargs="+", default=["guard_hound", "imperial_soldier", "steam_rat"])
    ap.add_argument("--pose", default="ready")
    ap.add_argument("--window", default="classic")
    ap.add_argument("--damage", default="248")
    ap.add_argument("--char", required=True, help="party character with battle poses (characters/<char>/frames)")
    ap.add_argument("--out", help="PNG to write (default <src_dir>/preview/battle_mock.png)")
    a = ap.parse_args(argv)
    conf = core.cfg()
    a.out = a.out or core.src(conf, "preview", "battle_mock.png")
    B = core.art(conf, "battle")
    scr = Image.new("RGBA", (640, 360), (0, 0, 0, 255))
    bg = Image.open(os.path.join(B, "bg", f"spr_bg_{a.bg}.png")).convert("RGBA")
    scr.alpha_composite(bg.resize((640, 256), Image.NEAREST), (0, 0))
    # enemies: left half, feet on a staggered line, like the 16-bit layouts
    ground = [228, 206, 246, 218]
    x = 40
    spots = []
    for i, n in enumerate(a.enemies):
        im = Image.open(os.path.join(B, "enemies", f"spr_enemy_{n}.png")).convert("RGBA")
        bb = im.getbbox()
        im = im.crop(bb)
        y = ground[i % len(ground)] - im.height
        scr.alpha_composite(im, (x, y))
        spots.append((n, x, y, im.width))
        x += im.width + 18
    # party: the party member's battle pose on the right, facing left
    P = core.art(conf, "characters", a.char, "frames")
    pose = Image.open(os.path.join(P, f"spr_{a.char}_{a.pose}_w_00.png")).convert("RGBA")
    pose = pose.crop(pose.getbbox())
    scr.alpha_composite(pose, (520, 224 - pose.height))
    # windows + text
    W = core.art(conf, "ui", "windows", f"ui_window_{a.window}.png")
    m = 12 if a.window == "classic" else 14
    scr.alpha_composite(nine(W, 236, 104, m), (0, 256))
    scr.alpha_composite(nine(W, 404, 104, m), (236, 256))
    txt = Font("dialogue.txt")
    names = {}
    for n, *_ in spots:
        label = n.replace("_", " ").title()
        names[label] = names.get(label, 0) + 1
    for i, (label, k) in enumerate(names.items()):
        txt.draw(scr, label + (f" x{k}" if k > 1 else ""), 18, 270 + i * 24)
    txt.draw(scr, a.char.replace("_", " ").title(), 256, 270)
    txt.draw(scr, "HP  412/ 530", 400, 270)
    txt.draw(scr, "MP   38/  45", 400, 294)
    # ATB gauge: frame + fill (code-drawn, like the window)
    bar = np.zeros((10, 120, 4), np.uint8)
    bar[...] = (12, 12, 24, 255)
    bar[2:-2, 2:-2] = (40, 40, 60, 255)
    bar[2:-2, 2:2 + 82] = (250, 214, 90, 255)
    bar[2:4, 2:2 + 82] = (255, 244, 190, 255)
    scr.alpha_composite(Image.fromarray(bar), (256, 300))
    Font("title_brass.txt", effect="outline", gradient="brass", caps_only=True).draw(scr, "Fight", 256, 322)
    # damage number over the first enemy, MISS over the second
    dmg = Font("damage.txt", effect="outline")
    n, ex, ey, ew = spots[0]
    dmg.draw(scr, a.damage, ex + ew // 2 - 18, ey - 6)
    if len(spots) > 1:
        n, ex, ey, ew = spots[1]
        dmg.draw(scr, "MISS", ex + ew // 2 - 26, ey - 6)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    scr.convert("RGB").save(a.out)
    scr.convert("RGB").resize((1280, 720), Image.NEAREST).save(a.out[:-4] + "_2x.png")
    print(f"[+] {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
