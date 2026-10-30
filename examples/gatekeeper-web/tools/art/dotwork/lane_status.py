#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_status.py
# Purpose : status-effect loops drawn in code, the small animated marks a 16-bit battle or field sprite wears: poison
#           bubbles, sleep Zs, haste / slow chevrons, a stop clock, blind smoke, regen sparkles, a berserk vein,
#           confusion stars, a silence bubble, a doom skull, burn flames, freeze crystals, protect / shell rings,
#           petrify flakes. Seamless loops, palette colours, the shared dark outline.
# Usage   : pack spec "status": [{"name": "poison"}, {"name": "zzz", "kind": "sleep"}, {"name": "haste"}]
#           keys: kind (default: the name), size (canvas px, default 32), frames (default 8), fps (default 8),
#           color (#RRGGBB main colour instead of the kind's own).
# Notes   : Godot: status_<name>.tscn is an AnimatedSprite2D that autoplays the loop, centred on its node: put it at
#           the character's head (rings and smoke circle the node; poison, Zs and sparkles rise from it).
#           Other engines: the frames and a sheet + JSON ship; play them looped at fps.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import json
import math
import os

import numpy as np
from PIL import Image

import fcore as core
import godot
from engine import load_hex, oklab

OUTLINE = (5, 4, 7)   # engine.finish's outline colour, shared by every Dotwork sprite

GLYPHS = {   # small bitmaps: '#' main colour, '+' highlight, '-' shade
    "z": ["####", "..#.", ".#..", "####"],
    "z_small": ["###", ".#.", "###"],
    "star": ["..+..", ".###.", "#####", ".###.", "..#.."],
    "sparkle": [".+.", "+#+", ".+."],
    "plus": [".#.", "###", ".#."],
    "up": ["..+..", ".#.#.", "#...#"],
    "down": ["#...#", ".#.#.", "..-.."],
    "skull": [".###.", "#####", "#.#.#", "#####", ".#.#."],
    "bubble": [".##.", "#+.#", "#..#", ".##."],
    "vein": ["#.#", ".#.", "#.#"],
    "flame0": ["..+..", ".+#..", ".###.", "#####", ".###."],
    "flame1": [".+...", "..#+.", ".###.", "#####", ".###."],
    "crystal": [".+.", "+##", "###", "##-", ".-."],
    "flake": ["#-", "-."],
    "silence": [".#######.", "#.......#", "#..#.#..#", "#...#...#", "#..#.#..#", "#.......#", ".###.###.",
                "....#...."],
}
KINDS = {   # main colour hint, drawing
    "poison": ("8ad048", "rise_bubbles"), "sleep": ("d8e4ff", "rise_z"), "haste": ("f8d040", "chevrons_up"),
    "slow": ("6aa0f0", "chevrons_down"), "stop": ("c8ccd8", "clock"), "blind": ("6a6478", "smoke"),
    "regen": ("78e080", "rise_sparkles"), "berserk": ("e83a30", "vein"), "confuse": ("f8e070", "orbit_stars"),
    "silence": ("e8e8f0", "silence"), "doom": ("b090d0", "skull"), "burn": ("f08a30", "flames"),
    "freeze": ("a0e0f8", "crystals"), "protect": ("70a8ff", "ring"), "shell": ("80e098", "ring"),
    "petrify": ("a8a4a0", "fall_flakes"),
}


class Canvas:
    def __init__(self, size, pal, main):
        self.n, self.pal = size, pal
        self.a = np.zeros((size, size, 4), np.uint8)
        self.main = self.snap(main)
        lab = oklab(self.main[None])[0]
        self.hi = self.snap_lab(lab + np.array([0.14, 0, 0]))
        self.lo = self.snap_lab(lab - np.array([0.14, 0, 0]))

    def snap(self, hexrgb):
        c = np.array([[int(hexrgb[i:i + 2], 16) for i in (0, 2, 4)]], np.uint8)
        return self.snap_lab(oklab(c)[0])

    def snap_lab(self, lab):
        return self.pal[np.argmin(((oklab(self.pal) - lab) ** 2).sum(-1))]

    def px(self, x, y, c):
        x, y = int(round(x)), int(round(y))
        if 0 <= x < self.n and 0 <= y < self.n:
            self.a[y, x, :3] = c
            self.a[y, x, 3] = 255

    def glyph(self, name, cx, cy, colour=None):
        rows = GLYPHS[name]
        h, w = len(rows), len(rows[0])
        x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
        main = self.main if colour is None else colour
        for j, row in enumerate(rows):
            for i, ch in enumerate(row):
                if ch != ".":
                    self.px(x0 + i, y0 + j, {"#": main, "+": self.hi, "-": self.lo}[ch])

    def outline(self):
        """1 px dark outline around everything drawn, so a mark reads over any sprite."""
        op = self.a[..., 3] == 255
        grow = op.copy()
        grow[1:] |= op[:-1]
        grow[:-1] |= op[1:]
        grow[:, 1:] |= op[:, :-1]
        grow[:, :-1] |= op[:, 1:]
        edge = grow & ~op
        self.a[edge, :3] = OUTLINE
        self.a[edge, 3] = 255


def frame(kind, t, size, pal, main):
    """One frame at loop phase t in [0, 1): everything is periodic in t, so frame n wraps to frame 0."""
    c = Canvas(size, pal, main)
    n, cx, cy = size, size / 2, size / 2
    draw = KINDS[kind][1]
    if draw == "rise_bubbles":
        for k, x in enumerate((cx - 6, cx + 1, cx + 7)):
            ph = (t + k / 3) % 1
            c.glyph("bubble" if ph < 0.85 else "sparkle", x + math.sin(ph * 6.28) * 1.5, n - 4 - ph * (n - 8))
    elif draw == "rise_z":
        for k in range(2):
            ph = (t + k / 2) % 1
            c.glyph("z" if ph > 0.45 else "z_small", cx - 5 + ph * 10, n - 6 - ph * (n - 12))
    elif draw in ("chevrons_up", "chevrons_down"):
        up = draw == "chevrons_up"
        for k in range(2):
            ph = (t + k / 2) % 1
            y = (n - 5 - ph * (n - 10)) if up else (5 + ph * (n - 10))
            for dx in (-5, 5):
                c.glyph("up" if up else "down", cx + dx, y)
    elif draw == "clock":
        r = n * 0.32
        for a in np.linspace(0, 2 * math.pi, 48, endpoint=False):
            c.px(cx + math.cos(a) * r, cy + math.sin(a) * r, c.main)
        for h in range(4):
            a = h * math.pi / 2
            c.px(cx + math.cos(a) * (r - 2), cy + math.sin(a) * (r - 2), c.hi)
        hand = -math.pi / 2 + math.floor(t * 8) / 8 * 2 * math.pi   # ticks in eight steps
        for s in np.linspace(0, r - 2, 12):
            c.px(cx + math.cos(hand) * s, cy + math.sin(hand) * s, c.lo)
    elif draw == "smoke":
        for k in range(3):
            a = (t + k / 3) * 2 * math.pi
            x, y = cx + math.cos(a) * n * 0.32, cy + math.sin(a) * n * 0.14
            for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1), (-1, 0), (0, -1), (2, 1), (-1, 1)):
                c.px(x + dx, y + dy, c.main if (dx + dy) % 2 == 0 else c.lo)
    elif draw == "rise_sparkles":
        for k, x in enumerate((cx - 7, cx, cx + 6)):
            ph = (t + k / 3) % 1
            c.glyph("sparkle" if (k + int(t * 8)) % 2 else "plus", x, n - 4 - ph * (n - 8))
    elif draw == "vein":   # always shown, throbbing: the arms grow for half the loop
        c.glyph("vein", cx + 4, cy - 4)
        if math.sin(t * 2 * math.pi) > 0:
            for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                c.px(cx + 4 + dx * 2, cy - 4 + dy * 2, c.hi)
    elif draw == "orbit_stars":
        for k in range(3):
            a = (t + k / 3) * 2 * math.pi
            front = math.sin(a) > 0
            c.glyph("star" if front else "sparkle", cx + math.cos(a) * n * 0.33, cy + math.sin(a) * n * 0.12)
    elif draw == "silence":
        c.glyph("silence", cx, cy - 1 + round(math.sin(t * 2 * math.pi)))
    elif draw == "skull":
        c.glyph("skull", cx, cy + round(math.sin(t * 2 * math.pi) * 1.5))
    elif draw == "flames":
        for k, x in enumerate((cx - 7, cx, cx + 7)):
            c.glyph("flame0" if (int(t * 8) + k) % 2 else "flame1", x, n - 6 - (k == 1) * 2)
    elif draw == "crystals":
        for k, (x, y) in enumerate(((cx - 8, cy + 4), (cx + 7, cy - 2), (cx, cy - 8), (cx + 3, cy + 8))):
            if (t * 4 + k * 0.6) % 2 < 1.4:
                c.glyph("crystal" if (int(t * 8) + k) % 3 else "sparkle", x, y)
    elif draw == "ring":
        r = 4 + t * (n * 0.42)
        for a in np.linspace(0, 2 * math.pi, int(12 + r * 4), endpoint=False):
            if t < 0.75 or (int(a * 6) % 2 == 0):   # breaks up as it fades
                c.px(cx + math.cos(a) * r, cy + math.sin(a) * r * 0.5, c.main if math.sin(a) > 0 else c.hi)
    elif draw == "fall_flakes":
        for k, x in enumerate((cx - 8, cx - 2, cx + 5, cx + 9)):
            ph = (t + k / 4) % 1
            c.glyph("flake", x + math.sin(ph * 6.28) * 1.2, 4 + ph * (n - 8))
    c.outline()
    return c.a


def scene(path, frames_res, anim, node):
    text = (f'[gd_scene load_steps=2 format=3]\n\n'
            f'[ext_resource type="SpriteFrames" path="{frames_res}" id="1_frames"]\n\n'
            f'[node name="{node}" type="AnimatedSprite2D"]\n'
            f'texture_filter = 1\nsprite_frames = ExtResource("1_frames")\nanimation = &"{anim}"\nautoplay = "{anim}"\n')
    return godot._write(path, text)


def run(entries, pack, man, conf):
    pal = load_hex(conf["fixed"]["palette"])
    base = core.art(conf, "fx", "status")
    res_base = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/fx/status'
    review = []
    for e in entries:
        name = core.snake(e["name"])
        kind = e.get("kind", name)
        if kind not in KINDS:
            raise core.ToolError(f"status {name}: kind {kind!r} is not one of {', '.join(KINDS)}")
        size, n, fps = int(e.get("size", 32)), int(e.get("frames", 8)), int(e.get("fps", 8))
        if not 16 <= size <= 96 or not 2 <= n <= 32:
            raise core.ToolError(f"status {name}: size 16 .. 96 and frames 2 .. 32")
        main = (e.get("color") or KINDS[kind][0]).lstrip("#")
        out = os.path.join(base, name)
        man.drop_dir(out)
        files = []
        for i in range(n):
            fn = f"spr_status_{name}_{i:02d}.png"
            p = core.save_clean(Image.fromarray(frame(kind, i / n, size, pal, main)), os.path.join(out, fn))
            man.add(p, "frame", animation=name, canvas=[size, size], anchor="centre (the head)",
                    workflow="Dotwork status loops (drawn in code)")
            files.append(fn)
        sheet = Image.new("RGBA", (size * n, size), (0, 0, 0, 0))
        for i, fn in enumerate(files):
            with Image.open(os.path.join(out, fn)) as im:
                sheet.alpha_composite(im.convert("RGBA"), (i * size, 0))
        sp = core.save_clean(sheet, os.path.join(out, f"status_{name}_sheet.png"))
        meta = os.path.join(out, f"status_{name}_sheet.json")
        core.write_text(meta, json.dumps({"frame_w": size, "frame_h": size, "frames": n, "fps": fps, "loop": True,
                                          "anchor": "centre"}, indent=1) + "\n")
        man.add(sp, "sheet", frames=n, fps=fps, loop=True, workflow="Dotwork status loops (drawn in code)")
        man.add(meta, "sheet_json")
        tres = godot.sprite_frames(os.path.join(out, f"status_{name}_frames.tres"), f"{res_base}/{name}",
                                   {name: (files, fps, True)})
        man.add(tres, "sprite_frames", animations=[name])
        scn = scene(os.path.join(out, f"status_{name}.tscn"), f"{res_base}/{name}/status_{name}_frames.tres", name,
                    "Status" + name.title().replace("_", ""))
        man.add(scn, "scene", node="AnimatedSprite2D (autoplay loop)", anchor="put the node at the head")
        review.append((name, [os.path.join(out, f) for f in files]))
        core.log(f"status {name}: {kind}, {n} frames at {fps} fps, {size} px")
    if review:
        import engine as lib
        lib.sheet(review, core.src(conf, "art", "fx", "status_review.png"), scale=3)
