#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# demo_attack.py
# Purpose : composite an attack with its effect from the game's Dotwork art (the caster's east clip, the projectile
#           launched at the weapon tip on the pose's peak frame, the impact); GIF + strip for review.
# Usage   : dotwork.py preview attack --char mage --anim cast_e --projectile fireball --impact explosion [--tile PNG]
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import argparse
import glob
import os
import sys

import numpy as np
from PIL import Image

import fcore as core


def frames(pattern):
    fs = sorted(glob.glob(pattern))
    if not fs:
        raise core.ToolError(f"no frames match {pattern} (pass --char / --anim for art this game has; see --help)")
    return [Image.open(f).convert("RGBA") for f in fs]


def peak(fr):
    """Frame whose upper 70% reaches furthest right (east-facing caster: staff fully extended) + that tip."""
    best = None
    for i, f in enumerate(fr):
        a = np.array(f)[..., 3] > 127
        ys, xs = np.nonzero(a)
        bb = f.getbbox()
        up = ys < bb[1] + (bb[3] - bb[1]) * 0.7
        j = int(np.argmax(xs[up]))
        if best is None or xs[up][j] > best[0]:
            best = (int(xs[up][j]), i, (int(xs[up][j]), int(ys[up][j])))
    return best[1], best[2]


def street(tile, w, h, dim=0.55):
    if not tile:
        return np.full((h, w, 3), (46, 40, 38), np.float32)
    t = Image.open(tile).convert("RGB")
    bg = Image.new("RGB", (w, h))
    for y in range(0, h, t.height):
        for x in range(0, w, t.width):
            bg.paste(t, (x, y))
    return np.array(bg).astype(np.float32) * dim


def paste(base, spr, x, y):
    s = np.array(spr).astype(np.float32)
    h, w = s.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(base.shape[1], x + w), min(base.shape[0], y + h)
    ss = s[y0 - y:y1 - y, x0 - x:x1 - x]
    m = (ss[..., 3:4] > 127).astype(np.float32)
    base[y0:y1, x0:x1] = base[y0:y1, x0:x1] * (1 - m) + ss[..., :3] * m


def add_fx(base, fx, x, y):
    f = np.array(fx).astype(np.float32)
    h, w = f.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(base.shape[1], x + w), min(base.shape[0], y + h)
    if x0 >= x1 or y0 >= y1:
        return
    fs = f[y0 - y:y1 - y, x0 - x:x1 - x]
    base[y0:y1, x0:x1] = np.minimum(255, base[y0:y1, x0:x1] + fs[..., :3] * (fs[..., 3:4] / 255))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dotwork.py preview attack", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--char", required=True, help="the character to animate (a name from the characters lane)")
    ap.add_argument("--anim", default="cast_e")
    ap.add_argument("--projectile", default="fireball")
    ap.add_argument("--impact", default="explosion")
    ap.add_argument("--tile", help="ground tile PNG for the backdrop (default: plain dark ground)")
    ap.add_argument("--hold", type=int, default=6)
    ap.add_argument("--speed", type=int, default=18)
    a = ap.parse_args(argv)
    conf = core.cfg()
    art = core.art(conf)
    cast = frames(os.path.join(art, "characters", a.char, "frames", f"spr_{a.char}_{a.anim}_*.png"))
    fb = frames(os.path.join(art, "fx", a.projectile, f"spr_fx_{a.projectile}_*.png"))
    ex = frames(os.path.join(art, "fx", a.impact, f"spr_fx_{a.impact}_*.png"))
    pk, (tx, ty) = peak(cast)
    W, H, floor, x0 = 320, 112, 100, 16
    seq = []

    def bg_with(f):
        b = street(a.tile, W, H)
        paste(b, f, x0, floor - f.height)
        return b

    for f in cast[:pk]:
        seq.append(bg_with(f))
    peak_f = cast[pk]
    ox, oy = x0 + tx, floor - peak_f.height + ty
    rest = cast[pk + 1:] or [cast[-1]]
    steps = max(8, (W - ox - 40) // a.speed)
    for k in range(steps):
        pose = peak_f if k < a.hold else rest[min(k - a.hold, len(rest) - 1)]
        b = bg_with(pose)
        f = fb[k % len(fb)]
        add_fx(b, f, ox + 2 + k * a.speed, oy - f.height // 2)
        seq.append(b)
    hit_x = min(ox + 2 + (steps - 1) * a.speed + fb[0].width - 8, W - max(f.width for f in ex) // 2 - 4)
    for f in ex:
        b = bg_with(rest[-1])
        add_fx(b, f, hit_x - f.width // 2, oy - f.height // 2)
        seq.append(b)
    for _ in range(4):
        seq.append(bg_with(rest[-1]))
    out_dir = core.src(conf, "preview")
    os.makedirs(out_dir, exist_ok=True)
    gif = os.path.join(out_dir, f"demo_{a.char}_{a.projectile}.gif")
    ims = [Image.fromarray(s.astype(np.uint8)).resize((W * 3, H * 3), Image.NEAREST).convert("P", palette=Image.ADAPTIVE)
           for s in seq]
    ims[0].save(gif, save_all=True, append_images=ims[1:], duration=90, loop=0, disposal=2)
    pick = [seq[i] for i in np.linspace(0, len(seq) - 1, 8).astype(int)]
    strip = Image.new("RGB", (W * 4, H * 2))
    for i, s in enumerate(pick):
        strip.paste(Image.fromarray(s.astype(np.uint8)), ((i % 4) * W, (i // 4) * H))
    sp = gif[:-4] + "_strip.png"
    strip.resize((strip.width * 2, strip.height * 2), Image.NEAREST).save(sp)
    print(f"[+] {gif} ({len(seq)} frames, peak frame {pk}, tip {tx},{ty})\n[+] {sp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
