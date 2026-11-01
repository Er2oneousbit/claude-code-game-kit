#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_spells.py
# Purpose : battle spells drawn in code for additive blending: a fire burst, ice shards, a lightning strike, a healing
#           ring with rising sparkles, a wind swirl, an explosion burst (one-shots), and a projectile orb and a power
#           aura (seamless loops). Every frame is exact and repeatable: no model, no GPU, no particle turning into a
#           face (the limit of the Wan effects lane).
# Usage   : pack spec "spells": [{"name": "fire"}, {"name": "frost", "kind": "ice"}, {"name": "zap", "kind": "bolt",
#           "color": "#ffe070"}]
#           keys: kind (default: the name; one of KINDS), size (canvas px), frames, fps, color (#RRGGBB: a ramp from
#           dark to white around it), colors (a list of 2-6 #RRGGBB, dark to light, used as given), seed.
# Notes   : Godot: spell_<name>.tscn is an AnimatedSprite2D with the additive material (mat_additive.tres) that
#           autoplays; one-shots stop on their last frame (connect animation_finished to free the node), loops repeat.
#           Centre the node on the target (bolt and heal stand on the target's feet: put the node there and offset it
#           up by half the canvas). Other engines: frames, a sheet + JSON; draw them with additive blending.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import json
import math
import os

import numpy as np
from PIL import Image, ImageDraw

import fcore as core
import godot

RAMPS = {   # dark -> light; intensity picks a step, the lowest step is checker-dithered
    "fire": ("5a1408", "b8300f", "e8701c", "ffc040", "fff3c0"),
    "ice": ("18306a", "2e6cc0", "7ab8ee", "c8ecff", "ffffff"),
    "bolt": ("1e2a6a", "4a66d8", "a8c4ff", "ffffff"),
    "heal": ("14502e", "2f9a50", "88e07a", "e8ffd0"),
    "wind": ("1e5040", "4a9e7c", "a8e8c8", "f4fff8"),
    "burst": ("5a1608", "c04012", "f89a2c", "ffe488", "ffffff"),
    "orb": ("2e1050", "6a30c0", "b884ff", "f4e8ff"),
    "aura": ("5a3a08", "c08a18", "f8d860", "fff8d8"),
}


def _ease(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def _grid(s):
    yy, xx = np.mgrid[0:s, 0:s].astype(np.float32)
    return xx, yy


def _disk(xx, yy, cx, cy, r, sx=1.0, sy=1.0):
    """1 at the centre, 0 at radius r (sx / sy stretch it sideways / up)."""
    if r <= 0:
        return np.zeros_like(xx)
    return np.clip(1 - np.hypot((xx - cx) / sx, (yy - cy) / sy) / r, 0, 1)


def _ring(xx, yy, cx, cy, rx, ry, w):
    """A band of half-width w pixels along an ellipse."""
    if rx <= 0 or ry <= 0:
        return np.zeros_like(xx)
    d = np.abs(np.hypot((xx - cx) / rx, (yy - cy) / ry) - 1) * min(rx, ry)
    return np.clip(1 - d / max(w, 0.5), 0, 1)


def _glint(img, x, y, arm, level=1.0):
    """A plus-shaped twinkle: the centre at level, the arms a step lower."""
    s = img.shape[0]
    x, y = int(round(x)), int(round(y))
    for dx, dy, v in [(0, 0, level)] + [(k * sx, k * sy, level * 0.75) for k in range(1, arm + 1)
                                         for sx, sy in ((1, 0), (-1, 0), (0, 1), (0, -1))]:
        if 0 <= x + dx < s and 0 <= y + dy < s:
            img[y + dy, x + dx] = max(img[y + dy, x + dx], v)


# -------------------------------------------------- one drawing per kind: (t in [0, 1], size, seed) -> intensity
def fire(t, s, seed):
    """Flame tongues erupt from a hot bed at the bottom, rise, shrink and die out; embers fly off."""
    rng = np.random.default_rng(seed)
    xx, yy = _grid(s)
    cx, base = (s - 1) / 2, s - 3
    bed = _ease((t + 0.1) / 0.25) * (1 - _ease((t - 0.55) / 0.35))   # frame 0 already shows the spark of it
    out = _disk(xx, yy, cx, base, s * 0.22 * (0.6 + 0.4 * bed), sx=1.7, sy=0.7) * bed
    for _ in range(20):
        b, life, x0, r0 = rng.uniform(-0.1, 0.5), rng.uniform(0.35, 0.55), rng.normal(0, s * 0.1), rng.uniform(.11, .18)
        rise, sway = rng.uniform(0.65, 0.95), rng.uniform(-1, 1) * s * 0.08
        a = (t - b) / life
        if 0 <= a < 1:
            x = cx + x0 * (1 - 0.4 * a) + sway * a * a
            out = np.maximum(out, _disk(xx, yy, x, base - a * s * rise, r0 * s * (1 - a) ** 0.6, 0.8, 1.35)
                             * (1 - a * a))
    for _ in range(6):   # embers: single bright pixels that outrun the flames
        b, ang, v = rng.uniform(0.15, 0.6), rng.uniform(-2.4, -0.7), rng.uniform(0.45, 0.7)
        a = (t - b) / 0.35
        if 0 <= a < 1:
            _glint(out, cx + math.cos(ang) * a * s * v * 0.6, base + math.sin(ang) * a * s * v, 0, 0.95)
    return out


def ice(t, s, seed):
    """Sharp crystals grow out of the centre with a lit edge, glint, then break into pieces and fade."""
    rng = np.random.default_rng(seed)
    xx, yy = _grid(s)
    c = (s - 1) / 2
    grow, shatter = _ease((t + 0.12) / 0.5), _ease((t - 0.68) / 0.32)
    out = _disk(xx, yy, c, c, s * 0.09 * grow) * (1 - shatter)
    k = 7
    base = rng.uniform(0, 2 * math.pi)
    tips = []
    for i in range(k):
        ang = base + 2 * math.pi * i / k + rng.uniform(-0.25, 0.25)
        ln, wm = s * rng.uniform(0.28, 0.45) * grow, s * rng.uniform(0.06, 0.09)
        if ln < 1:
            continue
        ca, sa = math.cos(ang), math.sin(ang)
        push = shatter * s * 0.14
        u = (xx - c) * ca + (yy - c) * sa - push
        v = -(xx - c) * sa + (yy - c) * ca
        w = wm * np.minimum(u / ln * 3, 1) * (1 - u / ln)
        inside = (u >= 0) & (u <= ln) & (np.abs(v) < w)
        if shatter > 0:   # broken: every other piece along the shard is gone
            inside &= (u // 3) % 2 == 0
        out = np.maximum(out, inside * np.where(v < 0, 1.0, 0.62) * (1 - 0.85 * shatter))
        tips.append((c + ca * (ln + push), c + sa * (ln + push)))
    if 0.3 <= t <= 0.75:
        for j, (x, y) in enumerate(tips[::3]):
            _glint(out, x, y, 1 + (int(t * 10) + j) % 2)
    return out


def bolt(t, s, seed):
    """A lightning strike from the top: a leader, the full bolt with branches and an impact flash, a flicker, then
    sparks and a fading ring where it hit."""
    rng = np.random.default_rng(seed)
    c, ground = (s - 1) / 2, s - 5

    def path(r, x0):
        pts, y, x = [(x0, 0.0)], 0.0, x0
        while y < ground:
            y = min(ground, y + r.uniform(4, 7))
            x = float(np.clip(x + r.uniform(-3.5, 3.5) + (c - x) * 0.25, 3, s - 4))
            pts.append((x, y))
        pts[-1] = (c, ground)
        return pts

    main = path(rng, c + rng.uniform(-0.15, 0.15) * s)
    flick = path(np.random.default_rng(seed + 1), main[0][0])
    branches = []
    for _ in range(2):
        j = int(rng.integers(1, max(2, len(main) - 2)))
        x, y = main[j]
        side = rng.choice((-1, 1))
        br = [(x, y)]
        for _ in range(3):
            x, y = float(np.clip(x + side * rng.uniform(3, 6), 2, s - 3)), y + rng.uniform(3, 6)
            br.append((x, y))
        branches.append(br)
    img = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(img)

    def line(pts, width, level):
        d.line([(round(x), round(y)) for x, y in pts], fill=int(255 * level), width=width)

    if t < 0.15:
        half = [p for p in main if p[1] <= ground * 0.55]
        line(half, 1, 0.7)
    elif t < 0.5:
        for br in branches if t >= 0.3 else []:
            line(br, 1, 0.75)
        line(main, 3, 0.5)
        line(main, 1, 1.0)
    elif t < 0.75:
        line(flick, 3, 0.35)
        line(flick, 1, 0.8)
    out = np.asarray(img, np.float32) / 255
    xx, yy = _grid(s)
    if 0.15 <= t < 0.75:
        out = np.maximum(out, _disk(xx, yy, c, ground, s * (0.16 if t < 0.5 else 0.11), 1.5, 0.8))
    if t >= 0.4:
        a = _ease((t - 0.4) / 0.6)
        out = np.maximum(out, _ring(xx, yy, c, ground, s * 0.42 * a, s * 0.14 * a, 1.0) * (1 - a) * 0.9)
    if t >= 0.6:
        for _ in range(6):
            ang, v = rng.uniform(math.pi, 2 * math.pi), rng.uniform(0.2, 0.4)
            a = (t - 0.6) / 0.4
            _glint(out, c + math.cos(ang) * a * s * v, ground + math.sin(ang) * a * s * v * 0.6, 0, 1 - 0.5 * a)
    return out


def heal(t, s, seed):
    """A ring of light opens on the ground under the target, a soft pillar rises, and twinkling sparkles float up."""
    rng = np.random.default_rng(seed)
    xx, yy = _grid(s)
    c, gy = (s - 1) / 2, s * 0.8
    grow, fade = _ease(t / 0.5), 1 - _ease((t - 0.6) / 0.4)
    rx = s * 0.42 * (0.35 + 0.65 * grow)
    out = _ring(xx, yy, c, gy, rx, rx * 0.36, 1.2) * fade * 0.95
    glow = math.sin(math.pi * min(1.0, t / 0.85))
    out = np.maximum(out, np.clip(1 - np.abs(xx - c) / (s * 0.2), 0, 1) * np.clip(1 - (gy - yy) / (s * 0.75), 0, 1)
                     * (yy < gy) * 0.38 * glow)
    for i in range(10):
        x0, b, sway = c + rng.uniform(-0.38, 0.38) * s, rng.uniform(0, 0.5), rng.uniform(0, 2 * math.pi)
        a = (t - b) / 0.45
        if 0 <= a < 1:
            _glint(out, x0 + math.sin(sway + a * 5) * 2, gy - a * s * 0.62, 1 + (int(t * 16) + i) % 2, 1 - 0.3 * a)
    return out


def wind(t, s, seed):
    """Three tapered crescents whirl round the centre, widening, with a few leaves of light thrown out."""
    rng = np.random.default_rng(seed)
    xx, yy = _grid(s)
    c = (s - 1) / 2
    ang = np.degrees(np.arctan2(yy - c, xx - c))
    r = np.hypot(yy - c, xx - c)
    env = _ease((t + 0.08) / 0.2) * (1 - _ease((t - 0.7) / 0.3))   # the first frame already shows a wisp
    out = np.zeros_like(xx)
    for k, (rad, ph) in enumerate(((0.18, 0.0), (0.3, 130.0), (0.42, 250.0))):
        head = ph + 400.0 * t
        rel = (head - ang) % 360.0                      # degrees behind the head
        prog = np.clip(1 - rel / 140.0, 0, 1)           # 1 at the head, 0 at the tail end
        thick = 0.6 + 2.0 * np.sin(np.pi * prog)
        band = np.abs(r - s * rad * (0.85 + 0.2 * t)) < thick
        out = np.maximum(out, band * (rel < 140.0) * (0.3 + 0.7 * prog) * env)
    for _ in range(5):
        a0, sp = rng.uniform(0, 2 * math.pi), rng.uniform(0.25, 0.45)
        a = a0 + 5.0 * t
        rr = s * sp * (0.3 + 0.7 * t)
        _glint(out, c + math.cos(a) * rr, c + math.sin(a) * rr, 0, 0.9 * env)
    return out


def burst(t, s, seed):
    """An explosion: a white-hot core swells and dies, a shock ring races outward and thins, debris flies off."""
    rng = np.random.default_rng(seed)
    xx, yy = _grid(s)
    c = (s - 1) / 2
    core_ = _disk(xx, yy, c, c, s * (0.1 + 0.2 * _ease(t / 0.3))) * (1 - _ease((t - 0.2) / 0.45))
    rr = s * 0.47 * _ease(t / 0.75)
    out = np.maximum(core_, _ring(xx, yy, c, c, rr, rr, 2.5 * (1 - t) + 0.7) * (1 - _ease((t - 0.35) / 0.65)))
    for _ in range(12):
        ang, v = rng.uniform(0, 2 * math.pi), rng.uniform(0.6, 1.0)
        dist = s * 0.48 * v * (1 - (1 - t) ** 2)
        _glint(out, c + math.cos(ang) * dist, c + math.sin(ang) * dist, 1 if t < 0.5 else 0, 1 - 0.6 * t)
    return out


def orb(t, s, seed):
    """A projectile loop: a pulsing core travelling right, a flickering tail behind it, three sparks circling it."""
    t %= 1.0   # a loop: t = 1 is exactly t = 0
    xx, yy = _grid(s)
    cx, cy = s * 0.6, (s - 1) / 2
    ph = 2 * math.pi * t
    out = _disk(xx, yy, cx, cy, s * 0.2 * (1 + 0.12 * math.sin(ph)))
    tail = _disk(xx, yy, cx - s * 0.22, cy, s * 0.2, 2.2, 0.55) * (0.7 + 0.3 * np.sin(xx * 0.9 + 2 * ph)) * 0.55
    out = np.maximum(out, tail)
    for k in range(3):
        a = ph + 2 * math.pi * k / 3
        _glint(out, cx + math.cos(a) * s * 0.32, cy + math.sin(a) * s * 0.16, 0, 1.0)
    return out


def aura(t, s, seed):
    """A power-up loop: a hollow band of light hugs the character's outline and flickers upward; a glow at the feet.
    Hollow, so the character stays visible: put the node behind or in front of the sprite."""
    t %= 1.0
    xx, yy = _grid(s)
    cx, cy, rx, ry = (s - 1) / 2, s * 0.55, s * 0.34, s * 0.42
    band = _ring(xx, yy, cx, cy, rx, ry, 2.6)
    licks = np.clip(np.sin(2 * math.pi * (yy / (s * 0.2) + 2 * t) + 2.2 * np.sin(xx * 0.55)), 0, 1)   # wavy, rising
    up = band * (0.4 + 0.6 * licks) * np.clip(1.2 - (yy - cy + ry) / (2 * ry) * 0.6, 0.4, 1)
    flames = (np.abs(np.hypot((xx - cx) / rx, (yy - cy) / ry) - 1.08) < 0.12) * (yy < cy) * licks * 0.7
    feet = _ring(xx, yy, cx, cy + ry * 0.95, rx * 0.9, ry * 0.18, 1.2) * (0.6 + 0.3 * math.sin(2 * math.pi * t))
    return np.maximum(np.maximum(up, flames), feet)


KINDS = {   # drawing, default size, frames, loops
    "fire": (fire, 48, 8, False), "ice": (ice, 48, 8, False), "bolt": (bolt, 56, 6, False),
    "heal": (heal, 48, 8, False), "wind": (wind, 48, 8, False), "burst": (burst, 56, 7, False),
    "orb": (orb, 24, 6, True), "aura": (aura, 48, 6, True),
}


def ramp_of(e, kind):
    """The colour steps for an entry: its own colors list, a ramp around its color, or the kind's ramp."""
    if e.get("colors"):
        cols = [str(h).lstrip("#") for h in e["colors"]]
        if not 2 <= len(cols) <= 6:
            raise core.ToolError(f"spells {e['name']}: colors takes 2 to 6 #RRGGBB values, dark to light")
    elif e.get("color"):
        c = np.array([int(str(e["color"]).lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)], np.float32)
        return np.array([c * 0.35, c * 0.7, c, c + (255 - c) * 0.5, np.full(3, 255.0)], np.float32)
    else:
        cols = RAMPS[kind]
    try:
        return np.array([[int(h[i:i + 2], 16) for i in (0, 2, 4)] for h in cols], np.float32)
    except ValueError:
        raise core.ToolError(f"spells {e['name']}: colors must be #RRGGBB values") from None


def paint(level, ramp):
    """Intensity (0..1) to RGBA: k + 1 flat bands (the lowest transparent), the first colour step checker-dithered,
    so a frame holds only the ramp's colours like a hand-made effect."""
    k = len(ramp)
    step = np.clip(np.floor(level * (k + 1)), 0, k).astype(int)
    yy, xx = np.mgrid[0:level.shape[0], 0:level.shape[1]]
    alpha = np.where(step >= 2, 255, np.where((step == 1) & ((yy + xx) % 2 == 0), 255, 0)).astype(np.uint8)
    rgb = ramp[np.clip(step - 1, 0, k - 1)].astype(np.uint8)
    return np.dstack([rgb, alpha])


def frames(kind, size, n, seed, ramp):
    draw, _, _, loop = KINDS[kind]
    return [paint(draw(i / n if loop else i / max(1, n - 1), size, seed), ramp) for i in range(n)]


def run(entries, pack, man, conf):
    base = core.art(conf, "fx", "spells")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/fx/spells'
    plan = []
    for e in entries:   # check every entry before anything is written
        name = core.snake(e["name"])
        kind = e.get("kind", name)
        if kind not in KINDS:
            raise core.ToolError(f"spells {name}: kind {kind!r} is not one of {', '.join(KINDS)}")
        _, size0, n0, loop = KINDS[kind]
        size, n = int(e.get("size", size0)), int(e.get("frames", n0))
        fps = int(e.get("fps", 10 if loop else 12))
        if not 16 <= size <= 128 or not 2 <= n <= 32:
            raise core.ToolError(f"spells {name}: size 16 .. 128 and frames 2 .. 32")
        plan.append((name, kind, size, n, fps, loop, core.seed_of(e, 7000), ramp_of(e, kind)))
    if not plan:
        return
    mat = godot.additive_material(os.path.join(base, "mat_additive.tres"))
    man.add(mat, "material", blend_mode="add")
    review = []
    for name, kind, size, n, fps, loop, seed, ramp in plan:
        out = os.path.join(base, name)
        man.drop_dir(out)
        files = []
        sheet = Image.new("RGBA", (size * n, size), (0, 0, 0, 0))
        for i, a in enumerate(frames(kind, size, n, seed, ramp)):
            fn = f"spr_spell_{name}_{i:02d}.png"
            im = Image.fromarray(a)
            p = core.save_clean(im, os.path.join(out, fn))
            sheet.alpha_composite(im, (i * size, 0))
            man.add(p, "fx_frame", animation=name, canvas=[size, size], anchor="center", blend="add", routes=(),
                    workflow=f"Dotwork spells {kind} (drawn in code)")
            files.append(fn)
        sp = core.save_clean(sheet, os.path.join(out, f"spell_{name}_sheet.png"))
        meta = os.path.join(out, f"spell_{name}_sheet.json")
        core.write_text(meta, json.dumps({"frame_w": size, "frame_h": size, "frames": n, "fps": fps, "loop": loop,
                                          "anchor": "centre", "blend": "add"}, indent=1) + "\n")
        man.add(sp, "sheet", frames=n, fps=fps, loop=loop, blend="add", workflow="Dotwork spells (drawn in code)")
        man.add(meta, "sheet_json")
        tres = godot.sprite_frames(os.path.join(out, f"spell_{name}_frames.tres"), f"{res}/{name}",
                                   {"play": (files, fps, loop)})
        man.add(tres, "sprite_frames", animations=["play"], blend="add")
        scn = godot.effect_scene(os.path.join(out, f"spell_{name}.tscn"), f"{res}/{name}/spell_{name}_frames.tres",
                                 f"{res}/mat_additive.tres", "play", node_name="Spell" + name.title().replace("_", ""))
        man.add(scn, "scene", node="AnimatedSprite2D", material="mat_additive.tres", autoplay="play")
        review.append((name, [os.path.join(out, f) for f in files]))
        core.log(f"spells {name}: {kind}, {n} frames at {fps} fps, {size} px" + (" (loop)" if loop else ""))
    import engine as lib
    lib.sheet(review, core.src(conf, "art", "fx", "spells_review.png"), scale=3, bg=(16, 14, 22))
