#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_vfx.py
# Purpose : small game effects drawn in code: projectiles (an arrow, an energy bolt, an orb) with a looping flight
#           animation and a trail that fades along its length; ground puffs (dust, a footstep, a wide landing ring), a
#           pickup twinkle and a level-up burst (one-shots); and GPUParticles2D emitters (dust, sparkles, embers) with a
#           tiny particle texture and a ParticleProcessMaterial whose colours step through the ramp. Every frame is
#           exact and repeatable: no model, no GPU.
# Usage   : pack spec "vfx": [{"name": "arrow"}, {"name": "spark_bolt", "kind": "bolt", "trail": "line"},
#           {"name": "step", "kind": "footstep"}, {"name": "forge_embers", "kind": "ember_particles", "amount": 24}]
#           keys: kind (default: the name; one of KINDS), size (canvas px; for particle kinds the width of the area
#           they start from), frames, fps, color (#RRGGBB: a ramp from dark to white around it), colors (a list of 2-6
#           #RRGGBB, dark to light, used as given), seed. Projectiles: trail (sprite / line / particles; default
#           sprite for the arrow and the bolt, particles for the orb). Particle kinds: amount (1 .. 256), one_shot
#           (true / false; a one-shot bursts out at once, a loop streams).
# Notes   : Godot: vfx_<name>.tscn. Projectiles are a Node2D (a Trail child behind a Body AnimatedSprite2D) pointing
#           right: set the root's rotation to the flight direction and move it. Puffs and bursts are an autoplaying
#           AnimatedSprite2D that stops on its last (empty) frame (connect animation_finished to free it); ground kinds
#           put the node origin on the ground line. Particle kinds are a GPUParticles2D; a one-shot bursts when it
#           enters the tree (its "Start" AnimationPlayer arms it, see STARTER), `finished` says when it is done and
#           restart() replays it. Glowing kinds use mat_additive.tres; dust and the arrow's body blend normally.
#           Other engines: frames, sheets + JSON, and vfx_<name>_particles.json with the emitter settings and the
#           colour steps over a particle's life.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import json
import math
import os
import re

import numpy as np
from PIL import Image

import fcore as core
import godot
from lane_spells import RAMPS as SPELL_RAMPS, _disk, _ease, _grid, _ring
from lane_spells import paint as glow_paint

DUST = ("4e4236", "7c6a54", "a89272", "d2c2a0")
SPARKLE = ("5a4410", "c0962c", "f8dc78", "ffffff")
RAMPS = {   # dark -> light, as in lane_spells; the bolt, orb, level-up and ember ramps are the spells' own
    "arrow": ("2e2620", "5c4430", "8c6a48", "b4b4b0", "f2f2ec"),   # dark, dark wood, wood, iron, glint
    "bolt": SPELL_RAMPS["bolt"], "orb": SPELL_RAMPS["orb"],
    "dust": DUST, "footstep": DUST, "landing": DUST, "dust_particles": DUST,
    "pickup_sparkle": SPARKLE, "sparkle_particles": SPARKLE,
    "level_up": SPELL_RAMPS["aura"], "ember_particles": SPELL_RAMPS["fire"],
}
TRAILS = ("sprite", "line", "particles")
HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")


def _dot(img, x, y, arm, level):
    """A plus-shaped glint on a canvas of any shape (lane_spells._glint assumes a square one)."""
    h, w = img.shape
    x, y = int(round(x)), int(round(y))
    for dx, dy, v in [(0, 0, level)] + [(k * sx, k * sy, level * 0.75) for k in range(1, arm + 1)
                                         for sx, sy in ((1, 0), (-1, 0), (0, 1), (0, -1))]:
        if 0 <= x + dx < w and 0 <= y + dy < h:
            img[y + dy, x + dx] = max(img[y + dy, x + dx], v)


def solid_paint(level, ramp):
    """Intensity to RGBA for an object with no glow (the arrow): every step solid, so its darkest colour can outline
    it. Level (0, 1] picks ramp step ceil(level * k) - 1 (draw mid-band: 0.1, 0.3 .. for 5 steps); 0 is transparent."""
    k = len(ramp)
    idx = np.clip(np.ceil(level * k) - 1, 0, k - 1).astype(int)
    alpha = np.where(level > 0, 255, 0).astype(np.uint8)
    return np.dstack([ramp[idx].astype(np.uint8), alpha])


# -------------------------------------------------- projectiles: flight loops (t in [0, 1), size, seed) -> intensity
def _arrow_parts(s):
    """Where an arrow of canvas s sits: nock x, tip x, centre row, head length."""
    u = s / 16.0
    return int(round(u)), s - 1 - int(round(u)), s // 2, max(3, int(round(4 * u)))


def arrow(t, s, seed):
    """An arrow flying right: a wooden shaft, an iron broadhead with a glint running along its edge, and fletching
    that flutters (loop). Levels sit mid-band for solid_paint (steps of a 5-colour ramp): 0.1 dark, 0.3 / 0.5 wood,
    0.7 iron, 0.9 glint."""
    t %= 1.0
    out = np.zeros((s, s), np.float32)
    x0, x1, cy, hl = _arrow_parts(s)
    u = s / 16.0
    th = max(1, int(round(u)))                                   # shaft thickness
    top = cy - (th - 1) // 2
    out[top:top + th, x0 + 1:x1 - hl + 2] = 0.5                  # the shaft
    if th > 1:
        out[top + th - 1, x0 + 1:x1 - hl + 2] = 0.3              # its shaded underside
    hh = max(1, int(round(1.5 * u)))                             # the head: widest at its base (the barbs)
    half = {x: int(round(hh * (x1 - x) / (hl - 1))) for x in range(x1 - hl + 1, x1 + 1)}
    for x, hx in half.items():
        out[cy - hx:cy + hx + th, x] = 0.7
        if hx > 0:
            out[cy + hx + th - 1, x] = 0.1                       # dark lower edge
    cols = sorted(half, reverse=True)                            # the glint runs from the tip to the barbs and back
    gx = cols[int(math.floor((1 - abs(2 * t - 1)) * (len(cols) - 1) + 0.5))]
    out[cy - half[gx], gx] = 0.9
    f = math.sin(2 * math.pi * t)
    d = 1 if f > 0.5 else (-1 if f < -0.5 else 0)                # flutter: one feather lifts, then the other
    fl, fh = max(2, int(round(3 * u))), max(1, int(round(1.5 * u)))
    for j in range(fl):
        x = x0 + 1 + j
        h = max(1, fh - (j * fh) // fl)
        up, dn = h + (max(d, 0) if j == 0 else 0), h + (max(-d, 0) if j == 0 else 0)
        out[max(0, top - up):top, x] = np.maximum(out[max(0, top - up):top, x], 0.9)
        out[top + th:min(s, top + th + dn), x] = np.maximum(out[top + th:min(s, top + th + dn), x], 0.7)
    out[top:top + th, x0] = 0.1                                  # the nock
    return out


def bolt(t, s, seed):
    """An energy bolt flying right: a white-hot lance with a halo pushed ahead of it and two crackling filaments that
    writhe along it, pinched at both ends (loop)."""
    t %= 1.0
    rng = np.random.default_rng(seed)
    xx, yy = _grid(s)
    cx, cy = s * 0.58, (s - 1) / 2
    ph = 2 * math.pi * t
    out = _disk(xx, yy, cx, cy, s * 0.18, sx=2.2, sy=0.55) * (0.92 + 0.08 * math.sin(2 * ph))
    out = np.maximum(out, _disk(xx, yy, cx + s * 0.06, cy, s * 0.22, sx=1.9, sy=0.9) * 0.5)
    x0, x1 = int(s * 0.14), int(s * 0.94)
    for k in range(2):
        p0 = rng.uniform(0, 2 * math.pi)
        for x in range(x0, x1 + 1):
            v = (x - x0) / max(1, x1 - x0)                       # 0 at the tail, 1 at the head
            y = cy + s * 0.14 * math.sin(math.pi * v) * math.sin(x * 0.8 + p0 + (k + 1) * ph) * math.cos(x * 0.31 - ph)
            yi = int(round(y))
            if 0 <= yi < s:
                out[yi, x] = max(out[yi, x], 0.45 + 0.5 * v)
    return out


def orb(t, s, seed):
    """A magic orb flying right: a pulsing core, a flickering rim and three sparks circling it (loop). Unlike the
    spells orb it carries no tail of its own: the trail is a separate strip, line or emitter."""
    t %= 1.0
    xx, yy = _grid(s)
    c = (s - 1) / 2
    ph = 2 * math.pi * t
    r = s * 0.24 * (1 + 0.1 * math.sin(ph))
    rim = _ring(xx, yy, c, c, r * 1.2, r * 1.2, 1.0) * (0.55 + 0.15 * math.sin(2 * ph))
    out = np.maximum(_disk(xx, yy, c, c, r), rim)
    for k in range(3):
        a = ph + 2 * math.pi * k / 3
        _dot(out, c + math.cos(a) * s * 0.4, c + math.sin(a) * s * 0.2, 0, 1.0)
    return out


# -------------------------------------------------- trails: (t, width, height, seed) -> intensity, head on the right
def _fade(w, h):
    """1 at the head (right edge), falling to 0 past the tail (left edge)."""
    return np.broadcast_to((np.arange(w, dtype=np.float32) + 1) / w, (h, w))


def arrow_trail(t, w, h, seed):
    """Air streaks behind an arrow: a faint line on the shaft and dashes above and below it scrolling back."""
    t %= 1.0
    fade = _fade(w, h)
    out = np.zeros((h, w), np.float32)
    cy = h // 2
    out[cy] = 0.8 * fade[cy]
    shift = int(round(t * 6)) % 6                                # dashes of 3 on, 3 off: 6 px repeat per loop
    on = ((np.arange(w) + shift) // 3) % 2 == 0
    for y in (cy - 2, cy + 2):
        if 0 <= y < h:
            out[y] = np.where(on, 0.65 * fade[y], 0)
    return out


def bolt_trail(t, w, h, seed):
    """A crackling streak behind an energy bolt: a beam that tapers and flickers toward the tail, a filament that
    writhes along it and sparks shed backward."""
    t %= 1.0
    rng = np.random.default_rng(seed + 1)
    fade = _fade(w, h)
    xx, yy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    cy, ph = (h - 1) / 2, 2 * math.pi * t
    beam = np.clip(1 - np.abs(yy - cy) / (h * 0.1 * (0.3 + 0.7 * fade)), 0, 1)
    out = beam * fade * (0.8 + 0.2 * np.sin(xx * 0.7 - 2 * ph))
    p0 = rng.uniform(0, 2 * math.pi)
    for x in range(w):
        f = (x + 1) / w
        yi = int(round(cy + h * 0.14 * f * math.sin(x * 0.9 + p0 + 3 * ph)))
        if 0 <= yi < h:
            out[yi, x] = max(out[yi, x], 0.85 * f)
    for _ in range(4):
        x0, dy = rng.uniform(0, w), rng.uniform(-0.25, 0.25) * h
        x = (x0 - t * w) % w                                     # drifts back one strip length per loop
        _dot(out, x, cy + dy, 0, 0.95 * (x + 1) / w)
    return out


def orb_trail(t, w, h, seed):
    """Motes shed by an orb: a soft tapering wake with blobs drifting back and shrinking."""
    t %= 1.0
    rng = np.random.default_rng(seed + 1)
    fade = _fade(w, h)
    xx, yy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    cy = (h - 1) / 2
    out = np.clip(1 - np.abs(yy - cy) / (h * 0.22 * fade + 0.5), 0, 1) * fade * 0.7
    for k in range(5):
        x0, dy = (k + rng.uniform(0, 0.6)) * w / 5, rng.uniform(-0.15, 0.15) * h
        x = (x0 - t * w) % w
        f = (x + 1) / w
        out = np.maximum(out, _disk(xx, yy, x, cy + dy, max(0.6, h * 0.16 * f)) * f)
    return out


# -------------------------------------------------- puffs and bursts: one-shots that end on an empty frame
def dust(t, s, seed):
    """A small ground puff: three lumps kick up from the feet, spread, rise a little and break up into grains."""
    rng = np.random.default_rng(seed)
    xx, yy = _grid(s)
    c, gy = (s - 1) / 2, s - 2
    a = _ease((t + 0.15) / 0.7)                                  # frame 0 is already a puff
    out = np.zeros_like(xx)
    for side, r0, lift in ((0, 0.2, 0.1), (-1, 0.15, 0.04), (1, 0.15, 0.04)):
        r = s * r0 * (0.7 + 0.5 * a)
        x, y = c + side * s * (0.1 + 0.2 * a), gy - r * 0.8 - s * lift * a
        out = np.maximum(out, _disk(xx, yy, x, y, r, 1.2, 0.85))
    grain = rng.random((s, s))
    return out * (grain >= _ease((t - 0.3) / 0.7)) * (yy <= gy)  # all grains gone at t = 1


def footstep(t, s, seed):
    """A tiny puff for a footstep: two wisps kicked sideways from the foot that fade into grains."""
    rng = np.random.default_rng(seed)
    xx, yy = _grid(s)
    c, gy = (s - 1) / 2, s - 1
    a = _ease((t + 0.25) / 0.8)
    out = np.zeros_like(xx)
    for side in (-1, 1):
        r = s * (0.14 + 0.08 * a)
        out = np.maximum(out, _disk(xx, yy, c + side * s * (0.1 + 0.24 * a), gy - r * 0.7 - s * 0.06 * a, r, 1.3, 0.8))
    grain = rng.random((s, s))
    return out * (grain >= _ease((t - 0.2) / 0.8)) * (yy <= gy)


def landing(t, s, seed):
    """A wide ring puff for a landing: a flat dust ring races out along the ground with lumps riding on it, kicked
    highest at the sides, then it breaks up."""
    rng = np.random.default_rng(seed)
    xx, yy = _grid(s)
    c, gy = (s - 1) / 2, s - 2
    a = _ease((t + 0.12) / 0.75)
    rx = s * (0.12 + 0.34 * a)
    ry = rx * 0.28
    cy = gy - ry
    out = _ring(xx, yy, c, cy, rx, ry, 1.6) * 0.7
    for k in range(10):
        ang = 2 * math.pi * k / 10 + rng.uniform(-0.2, 0.2)
        lift = s * 0.12 * a * abs(math.cos(ang))
        r = s * 0.075 * (1 + 0.6 * a)
        out = np.maximum(out, _disk(xx, yy, c + math.cos(ang) * rx, cy + math.sin(ang) * ry - lift, r, 1.2, 0.9)
                         * (1.0 if math.sin(ang) > 0 else 0.8))
    grain = rng.random((s, s))
    return out * (grain >= _ease((t - 0.35) / 0.65)) * (yy <= gy)


def pickup_sparkle(t, s, seed):
    """A twinkle: a four-point star flares from the centre with long thin arms, adds short diagonals at its peak and
    shrinks away; two small glints pop beside it."""
    rng = np.random.default_rng(seed)
    out = np.zeros((s, s), np.float32)
    ci = s // 2
    g = max(0.0, math.sin(math.pi * min(1.0, (t + 0.12) / 1.12)))
    g = g if g > 1e-6 else 0.0                                   # sin(pi) is not exactly 0
    arm = int(round(g * s * 0.45))
    for d in range(-arm, arm + 1):
        v = math.sqrt(g) * (1 - 0.6 * abs(d) / max(arm, 1))     # the root keeps a small star above the first step
        for x, y in ((ci + d, ci), (ci, ci + d)):
            if 0 <= x < s and 0 <= y < s:
                out[y, x] = max(out[y, x], v)
    diag = int(round(max(0.0, g - 0.6) * s * 0.4))
    for d in range(1, diag + 1):
        for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            if 0 <= ci + sx * d < s and 0 <= ci + sy * d < s:
                out[ci + sy * d, ci + sx * d] = max(out[ci + sy * d, ci + sx * d], g * 0.7)
    for _ in range(2):
        b, x, y = rng.uniform(0.1, 0.45), ci + rng.uniform(-0.38, 0.38) * s, ci + rng.uniform(-0.38, 0.38) * s
        a = (t - b) / 0.4
        if 0 <= a < 1:
            _dot(out, x, y, 1 if a < 0.5 else 0, math.sin(math.pi * a) * 0.9)
    return out


def level_up(t, s, seed):
    """A level-up burst: a ring of light flashes open at the feet, columns of light shoot up from it one after another,
    and sparkles rise past them; everything thins out and is gone on the last frame."""
    rng = np.random.default_rng(seed)
    xx, yy = _grid(s)
    c, gy = (s - 1) / 2, s - 4
    rr = s * (0.12 + 0.3 * _ease((t + 0.1) / 0.4))
    out = _ring(xx, yy, c, gy, rr, rr * 0.3, 1.3) * (1 - _ease((t - 0.3) / 0.45))
    for k in range(6):
        x, w = c + (k - 2.5) * s * 0.11 + rng.uniform(-1, 1), rng.uniform(0.8, 1.8)
        b, hgt = rng.uniform(0, 0.3), s * rng.uniform(0.55, 0.85)
        top = gy - hgt * _ease((t - b + 0.08) / 0.3)             # shoots up
        fade = (1 - _ease((t - b - 0.25) / (0.75 - b))) ** 0.5    # thins out, gone at t = 1 whatever its start
        along = 0.55 + 0.45 * np.clip(1 - (yy - top) / (hgt * 0.6), 0, 1)   # brightest at the leading top
        col = np.clip(1 - np.abs(xx - x) / w, 0, 1) * (yy <= gy) * (yy >= top)
        out = np.maximum(out, col * along * fade)
    for k in range(10):
        b, x0, v = rng.uniform(0.1, 0.55), c + rng.uniform(-0.4, 0.4) * s, rng.uniform(0.5, 0.8)
        a = (t - b) / 0.45                                       # the last sparkle ends exactly at t = 1
        if 0 <= a < 1:
            _dot(out, x0 + math.sin(a * 6 + k) * 1.5, gy - a * s * v, 1 if a < 0.5 else 0, 1 - 0.5 * a)
    return out


# -------------------------------------------------- kinds
# sprite kinds: drawing, default size, frames, loops, blend, anchor, trail drawing, where the trail joins (canvas px)
KINDS = {
    "arrow": (arrow, 16, 4, True, "mix", "center", arrow_trail, lambda s: _arrow_parts(s)[0] + 1),
    "bolt": (bolt, 24, 4, True, "add", "center", bolt_trail, lambda s: int(s * 0.2)),
    "orb": (orb, 20, 6, True, "add", "center", orb_trail, lambda s: s // 2),
    "dust": (dust, 24, 6, False, "mix", "bottom", None, None),
    "footstep": (footstep, 12, 4, False, "mix", "bottom", None, None),
    "landing": (landing, 40, 7, False, "mix", "bottom", None, None),
    "pickup_sparkle": (pickup_sparkle, 16, 6, False, "add", "center", None, None),
    "level_up": (level_up, 48, 10, False, "add", "bottom", None, None),
}
PROJECTILES = ("arrow", "bolt", "orb")
DEFAULT_TRAIL = {"arrow": "sprite", "bolt": "sprite", "orb": "particles"}

# particle textures: white masks (rows of "#"), tinted by the colour steps of the process material's ramp
MASKS = {"blob": (".##.", "####", "####", ".##."), "plus": ("..#..", "..#..", "#####", "..#..", "..#.."),
         "plus3": (".#.", "###", ".#."), "dot": ("##", "##"), "dash": ("##",)}
# particle kinds: mask, blend, default area (size), amount, lifetime, one_shot, burst explosiveness, randomness,
# emission (shape, extents as fractions of the area), direction, spread (deg), speed (px/s at the default area),
# gravity (px/s^2), damping
PARTICLES = {
    "dust_particles": dict(mask="blob", blend="mix", size=16, amount=10, lifetime=0.6, one_shot=True, burst=0.9,
                           randomness=0.5, shape="box", extents=(0.45, 0.06), direction=(0, -1), spread=80.0,
                           speed=(20.0, 42.0), gravity=(0, 40), damping=(40.0, 60.0)),
    "sparkle_particles": dict(mask="plus", blend="add", size=16, amount=8, lifetime=0.9, one_shot=False, burst=0.7,
                              randomness=0.5, shape="sphere", extents=(0.5, 0.5), direction=(0, -1), spread=180.0,
                              speed=(2.0, 6.0), gravity=(0, -6), damping=(0.0, 0.0)),
    "ember_particles": dict(mask="dot", blend="add", size=24, amount=16, lifetime=1.4, one_shot=False, burst=0.6,
                            randomness=0.4, shape="box", extents=(0.5, 0.08), direction=(0, -1), spread=20.0,
                            speed=(12.0, 28.0), gravity=(0, -12), damping=(2.0, 6.0)),
}
# a projectile's particle trail: mask, amount, lifetime, speed backward (px/s); it starts at the join point
TRAIL_PARTICLES = {"arrow": ("dash", 10, 0.25, (4.0, 8.0)), "bolt": ("dot", 16, 0.3, (6.0, 14.0)),
                   "orb": ("plus3", 14, 0.35, (4.0, 10.0))}


def ramp_of(e, kind):
    """The colour steps for an entry: its own colors list, a ramp around its color (the spells formula), or the kind's
    ramp. Whole numbers, so the PNGs, the gradients and the tests agree on every step."""
    name = e["name"]
    if e.get("colors") is not None:
        cols = e["colors"]
        if not isinstance(cols, list) or not 2 <= len(cols) <= 6 or not all(HEX.match(str(h)) for h in cols):
            raise core.ToolError(f"vfx {name}: colors takes a list of 2 to 6 #RRGGBB values, dark to light")
        cols = [str(h).lstrip("#") for h in cols]
    elif e.get("color") is not None:
        if not HEX.match(str(e["color"])):
            raise core.ToolError(f"vfx {name}: color must be one #RRGGBB value")
        c = np.array([int(str(e["color"]).lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)], np.float32)
        return np.floor(np.array([c * 0.35, c * 0.7, c, c + (255 - c) * 0.5, np.full(3, 255.0)], np.float32))
    else:
        cols = RAMPS[kind]
    return np.array([[int(h[i:i + 2], 16) for i in (0, 2, 4)] for h in cols], np.float32)


def paint(kind, level, ramp):
    return solid_paint(level, ramp) if kind == "arrow" else glow_paint(level, ramp)


def frames(kind, size, n, seed, ramp):
    """The animation: loops sample t = i / n (the frame after the last is the first), one-shots t = i / (n - 1) (the
    last frame is t = 1: empty)."""
    draw, _, _, loop = KINDS[kind][:4]
    return [paint(kind, draw(i / n if loop else i / max(1, n - 1), size, seed), ramp) for i in range(n)]


def trail_frames(kind, size, n, seed, ramp):
    """A projectile's trail strip: twice the canvas wide, the head on the right where it meets the body."""
    draw = KINDS[kind][6]
    return [glow_paint(draw(i / n, 2 * size, size, seed), ramp) for i in range(n)]


def trail_join(kind, size):
    """Body-local x (Godot, the body centred on the origin) where the trail meets the body."""
    return KINDS[kind][7](size) - size // 2


def mask(name):
    rows = MASKS[name]
    a = np.zeros((len(rows), len(rows[0]), 4), np.uint8)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == "#":
                a[y, x] = (255, 255, 255, 255)
    return a


def life_gradient(ramp):
    """Colour steps over a particle's life: light to dark through the ramp, then gone (alpha 0) for the last step.
    Offsets j / (k + 1); constant interpolation in Godot, so each step is one ramp colour."""
    k = len(ramp)
    cols = [tuple(ramp[k - 1 - j]) + (1.0,) for j in range(k)] + [tuple(ramp[0]) + (0.0,)]
    return [j / (k + 1) for j in range(k + 1)], cols


def trail_gradient(ramp):
    """Colour steps along a Line2D trail, tail (offset 0) to head (offset 1): transparent, then dark to light."""
    k = len(ramp)
    cols = [tuple(ramp[0]) + (0.0,)] + [tuple(ramp[j]) + (1.0,) for j in range(k)]
    return [j / (k + 1) for j in range(k + 1)], cols


# -------------------------------------------------- Godot text (probed against Godot 4.7.2)
def _f(x):
    s = f"{float(x):.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def _gradient(gid, offsets, cols):
    return [f'[sub_resource type="Gradient" id="{gid}"]', "interpolation_mode = 1",
            f"offsets = PackedFloat32Array({', '.join(_f(o) for o in offsets)})",
            "colors = PackedColorArray(" + ", ".join(", ".join([_f(r / 255), _f(g / 255), _f(b / 255), _f(a)])
                                                     for r, g, b, a in cols) + ")", ""]


def _emitter(sid, p, area, ramp):
    """Sub-resources (life gradient, its texture, the ParticleProcessMaterial) and the GPUParticles2D property lines
    for one emitter. p: a PARTICLES-style dict with amount, lifetime, one_shot and explosiveness filled in."""
    k = area / p["size"]                                          # speeds and the emission area scale with size
    offs, cols = life_gradient(ramp)
    subs = _gradient(f"Gradient_{sid}", offs, cols) + [
        f'[sub_resource type="GradientTexture1D" id="GradientTexture1D_{sid}"]',
        f'gradient = SubResource("Gradient_{sid}")', "",
        f'[sub_resource type="ParticleProcessMaterial" id="ParticleProcessMaterial_{sid}"]',
        "particle_flag_disable_z = true"]
    ex, ey = p["extents"]
    if p["shape"] == "sphere":
        subs += ["emission_shape = 1", f"emission_sphere_radius = {_f(max(0.5, area * ex))}"]
    else:
        subs += ["emission_shape = 3", f"emission_box_extents = Vector3({_f(max(0.5, area * ex))}, "
                                       f"{_f(max(0.5, area * ey))}, 0)"]
    dx, dy = p["direction"]
    subs += [f"direction = Vector3({_f(dx)}, {_f(dy)}, 0)", f"spread = {_f(p['spread'])}",
             f"initial_velocity_min = {_f(p['speed'][0] * k)}", f"initial_velocity_max = {_f(p['speed'][1] * k)}",
             f"gravity = Vector3({_f(p['gravity'][0] * k)}, {_f(p['gravity'][1] * k)}, 0)",
             f"damping_min = {_f(p['damping'][0] * k)}", f"damping_max = {_f(p['damping'][1] * k)}",
             f'color_ramp = SubResource("GradientTexture1D_{sid}")', ""]
    props = [f"amount = {p['amount']}", f"lifetime = {_f(p['lifetime'])}",
             f"one_shot = {'true' if p['one_shot'] else 'false'}", f"explosiveness = {_f(p['explosiveness'])}",
             f"randomness = {_f(p['randomness'])}", "local_coords = false",
             f'process_material = SubResource("ParticleProcessMaterial_{sid}")']
    return subs, props


def _scene_text(ext, subs, nodes):
    ids = sum(1 for line in ext + subs if line.startswith(("[ext_resource", "[sub_resource")))
    return "\n".join([f"[gd_scene load_steps={ids + 1} format=3]", "", *ext, "", *subs, *nodes])


# A one-shot GPUParticles2D that starts emitting from the scene file stops after one frame without bursting or sending
# `finished` (Godot 4.7.2, probed 2026-11-01: emitting is already true when one_shot is set, so the cycle is never
# armed). So one-shots are saved with emitting = false and a "Start" AnimationPlayer whose autoplay sets emitting on
# entering the tree: the burst plays on spawn and `finished` fires after it, with no script.
STARTER = ['[sub_resource type="Animation" id="Animation_start"]', "length = 0.1", 'tracks/0/type = "value"',
           "tracks/0/imported = false", "tracks/0/enabled = true", 'tracks/0/path = NodePath(".:emitting")',
           "tracks/0/interp = 1", "tracks/0/loop_wrap = true", "tracks/0/keys = {", '"times": PackedFloat32Array(0),',
           '"transitions": PackedFloat32Array(1),', '"update": 1,', '"values": [true]', "}", "",
           '[sub_resource type="AnimationLibrary" id="AnimationLibrary_start"]', "_data = {",
           '&"start": SubResource("Animation_start")', "}", ""]


def particle_scene(path, node, tex_res, mat_res, p, area, ramp):
    ext = [f'[ext_resource type="Texture2D" path="{tex_res}" id="1_tex"]']
    if mat_res:
        ext.append(f'[ext_resource type="Material" path="{mat_res}" id="2_mat"]')
    subs, props = _emitter("1", p, area, ramp)
    nodes = [f'[node name="{node}" type="GPUParticles2D"]', "texture_filter = 1"]
    nodes += ['material = ExtResource("2_mat")'] if mat_res else []
    nodes += ['texture = ExtResource("1_tex")'] + props + [""]
    if p["one_shot"]:
        subs += STARTER
        nodes.insert(nodes.index("one_shot = true") + 1, "emitting = false")
        nodes += ['[node name="Start" type="AnimationPlayer" parent="."]', "libraries = {",
                  '&"": SubResource("AnimationLibrary_start")', "}", 'autoplay = &"start"', ""]
    return godot._write(path, _scene_text(ext, subs, nodes))


def sprite_scene(path, node, frames_res, mat_res, anim, offset=(0, 0)):
    """An autoplaying AnimatedSprite2D (puffs and bursts); offset puts a ground kind's origin on the ground line."""
    ext = [f'[ext_resource type="SpriteFrames" path="{frames_res}" id="1_frames"]']
    if mat_res:
        ext.append(f'[ext_resource type="Material" path="{mat_res}" id="2_mat"]')
    nodes = [f'[node name="{node}" type="AnimatedSprite2D"]', "texture_filter = 1"]
    nodes += ['material = ExtResource("2_mat")'] if mat_res else []
    nodes += [f"offset = Vector2({offset[0]}, {offset[1]})"] if offset != (0, 0) else []
    nodes += ['sprite_frames = ExtResource("1_frames")', f'animation = &"{anim}"', f'autoplay = "{anim}"', ""]
    return godot._write(path, _scene_text(ext, [], nodes))


def projectile_scene(path, node, kind, size, mode, frames_res, mat_res, body_add, ramp, trail_tex_res=None):
    """Node2D root pointing right: a Trail child (strip / Line2D / world-space GPUParticles2D) drawn behind a Body that
    plays the flight loop. Rotate the root to the flight direction and move it."""
    ext = [f'[ext_resource type="SpriteFrames" path="{frames_res}" id="1_frames"]',
           f'[ext_resource type="Material" path="{mat_res}" id="2_mat"]']
    node_type = {"sprite": "AnimatedSprite2D", "line": "Line2D", "particles": "GPUParticles2D"}[mode]
    subs, trail = [], [f'[node name="Trail" type="{node_type}" parent="."]', "texture_filter = 1",
                       'material = ExtResource("2_mat")']
    join = trail_join(kind, size)
    if mode == "sprite":                                          # the strip's right edge on the join point
        trail += [f"position = Vector2({join - size + 1}, 0)", 'sprite_frames = ExtResource("1_frames")',
                  'animation = &"trail"', 'autoplay = "trail"']
    elif mode == "line":
        offs, cols = trail_gradient(ramp)
        width = {"arrow": max(1.0, size / 16), "bolt": size * 0.2, "orb": size * 0.4}[kind]
        subs += _gradient("Gradient_trail", offs, cols) + [
            '[sub_resource type="Curve" id="Curve_taper"]',
            "_data = [Vector2(0, 0.25), 0.0, 0.0, 0, 0, Vector2(1, 1), 0.0, 0.0, 0, 0]", "point_count = 2", ""]
        trail += [f"points = PackedVector2Array({join + 1 - 2 * size}, 0, {join + 1}, 0)", f"width = {_f(width)}",
                  'width_curve = SubResource("Curve_taper")', 'gradient = SubResource("Gradient_trail")']
    else:
        ext.append(f'[ext_resource type="Texture2D" path="{trail_tex_res}" id="3_tex"]')
        m, amount, life, speed = TRAIL_PARTICLES[kind]
        p = dict(size=size, amount=amount, lifetime=life, one_shot=False, explosiveness=0.0, randomness=0.3,
                 shape="sphere", extents=(0.1, 0.1), direction=(-1, 0), spread=20.0, speed=speed, gravity=(0, 0),
                 damping=(0.0, 0.0))
        es, props = _emitter("trail", p, size, ramp)
        subs += es
        trail += [f"position = Vector2({join}, 0)", 'texture = ExtResource("3_tex")'] + props
    body = ['[node name="Body" type="AnimatedSprite2D" parent="."]', "texture_filter = 1"]
    body += ['material = ExtResource("2_mat")'] if body_add else []
    body += ['sprite_frames = ExtResource("1_frames")', 'animation = &"fly"', 'autoplay = "fly"', ""]
    nodes = [f'[node name="{node}" type="Node2D"]', ""] + trail + [""] + body
    return godot._write(path, _scene_text(ext, subs, nodes))


# -------------------------------------------------- review previews (work folder only; Godot runs the real thing)
def simulate(p, area, ramp, tex, times, canvas, origin, seed, drift=(0.0, 0.0)):
    """Frames of an emitter as the review sheet shows them: every particle starts in the emission shape at its own
    time, flies with gravity and damping, takes the colour step of its age and is stamped as its mask. drift adds a
    velocity to every particle (a moving projectile seen from its body). An approximation for review only."""
    rng = np.random.default_rng(seed)
    k = area / p["size"]
    n, life = p["amount"], p["lifetime"]
    offs, cols = life_gradient(ramp)
    ex, ey = p["extents"]
    parts = []
    for i in range(n):
        if p["shape"] == "sphere":
            a, r = rng.uniform(0, 2 * math.pi), area * ex * math.sqrt(rng.uniform())
            pos = (math.cos(a) * r, math.sin(a) * r)
        else:
            pos = (rng.uniform(-1, 1) * area * ex, rng.uniform(-1, 1) * area * ey)
        ang = math.atan2(p["direction"][1], p["direction"][0]) + math.radians(rng.uniform(-p["spread"], p["spread"]))
        sp = rng.uniform(*p["speed"]) * k
        damp = rng.uniform(*p["damping"]) * k
        born = (i / n) * life * (1 - p["explosiveness"])
        parts.append((pos, (math.cos(ang) * sp, math.sin(ang) * sp), damp, born))
    w, h = canvas
    out = []
    for T in times:
        img = np.zeros((h, w, 3), np.float32)
        hit = np.zeros((h, w), bool)
        for pos, vel, damp, born in parts:
            age = T - born
            if not p["one_shot"]:
                age %= life
            if age < 0 or age >= life:
                continue
            x, y = pos
            vx, vy = vel
            for _ in range(int(age * 60)):                       # 60 steps a second, as the engine ticks
                vx, vy = vx + p["gravity"][0] * k / 60, vy + p["gravity"][1] * k / 60
                spd = math.hypot(vx, vy)
                if damp and spd > 0:
                    f = max(0.0, spd - damp / 60) / spd
                    vx, vy = vx * f, vy * f
                x, y = x + (vx + drift[0]) / 60, y + (vy + drift[1]) / 60
            j = max(i for i, o in enumerate(offs) if o <= age / life)
            r, g, b, al = cols[j]
            if al <= 0:
                continue
            px, py = int(round(origin[0] + x)) - tex.shape[1] // 2, int(round(origin[1] + y)) - tex.shape[0] // 2
            for yy, xx in zip(*np.nonzero(tex[..., 3])):
                X, Y = px + xx, py + yy
                if 0 <= X < w and 0 <= Y < h:
                    c = np.array([r, g, b], np.float32) * al
                    img[Y, X] = np.minimum(255, img[Y, X] + c) if p["blend"] == "add" else c
                    hit[Y, X] = True
        out.append(np.dstack([img.astype(np.uint8), np.where(hit, 255, 0).astype(np.uint8)]))
    return out


def _line_strip(kind, size, ramp):
    """The Line2D trail rasterised for review: a band that tapers toward the tail, coloured in the gradient's steps."""
    w, h = 2 * size, size
    offs, cols = trail_gradient(ramp)
    width = {"arrow": max(1.0, size / 16), "bolt": size * 0.2, "orb": size * 0.4}[kind]
    a = np.zeros((h, w, 4), np.uint8)
    for x in range(w):
        v = x / max(1, w - 1)
        half = width * (0.25 + 0.75 * v) / 2
        j = max(i for i, o in enumerate(offs) if o <= v)
        r, g, b, al = cols[j]
        if al <= 0:
            continue
        for y in range(h):
            if abs(y + 0.5 - h / 2) <= max(0.5, half):
                a[y, x] = (int(r), int(g), int(b), 255)
    return a


def composite(kind, size, mode, body, strip, ramp, seed, n):
    """Body + trail as the projectile scene places them, one image per frame (review only)."""
    w = 3 * size
    out = []
    join = KINDS[kind][7](size)                                  # canvas px of the join, body at x = 2 * size
    if mode == "particles":
        m, amount, life, speed = TRAIL_PARTICLES[kind]
        p = dict(size=size, amount=amount, lifetime=life, one_shot=False, explosiveness=0.0, randomness=0.3,
                 shape="sphere", extents=(0.1, 0.1), direction=(-1, 0), spread=20.0, speed=speed, gravity=(0, 0),
                 damping=(0.0, 0.0), blend="add")
        sims = simulate(p, size, ramp, mask(m), [life * 2 + i * life / n for i in range(n)], (w, size),
                        (2 * size + join, size / 2), seed, drift=(-2 * size / life / 2, 0))
    for i in range(n):
        im = Image.new("RGBA", (w, size), (0, 0, 0, 0))
        if mode == "sprite":
            im.alpha_composite(Image.fromarray(strip[i]), (join + 1, 0))
        elif mode == "line":
            im.alpha_composite(Image.fromarray(_line_strip(kind, size, ramp)), (join + 1, 0))
        else:
            im.alpha_composite(Image.fromarray(sims[i]))
        im.alpha_composite(Image.fromarray(body[i]), (2 * size, 0))
        out.append(im)
    return out


# -------------------------------------------------- the lane
def _whole(name, key, v, lo, hi):
    """A whole-number spec value inside lo .. hi (24 and 24.0 both pass; "24", true and 24.5 do not)."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise core.ToolError(f"vfx {name}: {key} is a whole number, {lo} .. {hi} (got {v!r})")
    return v


def _plan(e):
    """Check one entry and return what to build; raises ToolError (exit 2) before anything is written."""
    name = core.snake(e["name"])
    kind = e.get("kind", name)
    if kind not in KINDS and kind not in PARTICLES:
        raise core.ToolError(f"vfx {name}: kind {kind!r} is not one of {', '.join(list(KINDS) + list(PARTICLES))}")
    ramp = ramp_of(dict(e, name=name), kind)
    seed = core.seed_of(e, 7600)
    if kind in PARTICLES:
        for key in ("frames", "fps", "trail"):
            if e.get(key) is not None:
                raise core.ToolError(f"vfx {name}: {key} is not used by the particle kind {kind}")
        p = dict(PARTICLES[kind])
        area = _whole(name, "size", e.get("size", p["size"]), 4, 256)
        amount = _whole(name, "amount", e.get("amount", p["amount"]), 1, 256)
        one_shot = e.get("one_shot", p["one_shot"])
        if not isinstance(one_shot, bool):
            raise core.ToolError(f"vfx {name}: one_shot is true or false")
        p.update(amount=amount, one_shot=one_shot, explosiveness=p["burst"] if one_shot else 0.0)
        return dict(name=name, kind=kind, ramp=ramp, seed=seed, particles=p, area=area)
    for key in ("amount", "one_shot"):
        if e.get(key) is not None:
            raise core.ToolError(f"vfx {name}: {key} is for the particle kinds ({', '.join(PARTICLES)})")
    draw, size0, n0, loop, blend, anchor = KINDS[kind][:6]
    size, n = e.get("size", size0), e.get("frames", n0)
    fps = e.get("fps", 12)
    size, n, fps = (_whole(name, key, v, lo, hi) for key, v, lo, hi in
                    (("size", size, 8, 128), ("frames", n, 2, 32), ("fps", fps, 1, 60)))
    trail = e.get("trail")
    if trail is not None and kind not in PROJECTILES:
        raise core.ToolError(f"vfx {name}: trail is for the projectiles ({', '.join(PROJECTILES)})")
    if kind in PROJECTILES:
        trail = DEFAULT_TRAIL[kind] if trail is None else trail
        if trail not in TRAILS:
            raise core.ToolError(f"vfx {name}: trail {trail!r} is not one of {', '.join(TRAILS)}")
    return dict(name=name, kind=kind, ramp=ramp, seed=seed, size=size, n=n, fps=fps, loop=loop, blend=blend,
                anchor=anchor, trail=trail)


def _sheet(out, stem, imgs, w, h, meta, man, kind):
    sheet = Image.new("RGBA", (w * len(imgs), h), (0, 0, 0, 0))
    for i, a in enumerate(imgs):
        sheet.alpha_composite(Image.fromarray(a), (i * w, 0))
    sp = core.save_clean(sheet, os.path.join(out, f"{stem}_sheet.png"))
    mp = core.write_text(os.path.join(out, f"{stem}_sheet.json"), json.dumps(meta, indent=1) + "\n")
    man.add(sp, "sheet", frames=len(imgs), fps=meta["fps"], loop=meta["loop"], blend=meta["blend"],
            workflow=f"Dotwork vfx {kind} (drawn in code)")
    man.add(mp, "sheet_json")


def _sprite_entry(pl, base, res, man, mat_res):
    name, kind, size, n, fps, loop, ramp = (pl[k] for k in ("name", "kind", "size", "n", "fps", "loop", "ramp"))
    out = os.path.join(base, name)
    man.drop_dir(out)
    body = frames(kind, size, n, pl["seed"], ramp)
    anim = "fly" if kind in PROJECTILES else "play"
    files = {anim: [], "trail": []}
    for i, a in enumerate(body):
        fn = f"spr_vfx_{name}_{i:02d}.png"
        man.add(core.save_clean(Image.fromarray(a), os.path.join(out, fn)), "fx_frame", animation=name,
                canvas=[size, size], anchor=pl["anchor"], blend=pl["blend"],
                workflow=f"Dotwork vfx {kind} (drawn in code)")
        files[anim].append(fn)
    meta = {"frame_w": size, "frame_h": size, "frames": n, "fps": fps, "loop": loop, "anchor": pl["anchor"],
            "blend": pl["blend"]}
    strip = None
    if kind in PROJECTILES:
        strip = trail_frames(kind, size, n, pl["seed"], ramp)
        for i, a in enumerate(strip):
            fn = f"spr_vfx_{name}_trail_{i:02d}.png"
            man.add(core.save_clean(Image.fromarray(a), os.path.join(out, fn)), "fx_frame", animation=f"{name}_trail",
                    canvas=[2 * size, size], anchor="right", blend="add",
                    workflow=f"Dotwork vfx {kind} trail (drawn in code)")
            files["trail"].append(fn)
        tmeta = {"frame_w": 2 * size, "frame_h": size, "frames": n, "fps": fps, "loop": True, "anchor": "right",
                 "blend": "add", "join_x": trail_join(kind, size) + size // 2}
        _sheet(out, f"vfx_{name}_trail", strip, 2 * size, size, tmeta, man, kind)
        meta["trail"] = {"sheet": f"vfx_{name}_trail_sheet.png", "scene_trail": pl["trail"],
                         "join_x": tmeta["join_x"]}   # canvas px of the body where the strip's right edge goes
    _sheet(out, f"vfx_{name}", body, size, size, meta, man, kind)
    anims = {anim: (files[anim], fps, loop)}
    if strip is not None:
        anims["trail"] = (files["trail"], fps, True)
    tres = godot.sprite_frames(os.path.join(out, f"vfx_{name}_frames.tres"), f"{res}/{name}", anims)
    man.add(tres, "sprite_frames", animations=list(anims), blend=pl["blend"])
    node = "Vfx" + name.title().replace("_", "")
    frames_res = f"{res}/{name}/vfx_{name}_frames.tres"
    scn_path = os.path.join(out, f"vfx_{name}.tscn")
    if kind in PROJECTILES:
        tex_res = None
        if pl["trail"] == "particles":
            m = TRAIL_PARTICLES[kind][0]
            tp = core.save_clean(Image.fromarray(mask(m)), os.path.join(out, f"vfx_{name}_trail_particle.png"))
            man.add(tp, "particle_texture", mask=m, usage="white mask, tinted by the trail emitter's colour steps",
                    workflow="Dotwork vfx (drawn in code)")
            tex_res = f"{res}/{name}/vfx_{name}_trail_particle.png"
        scn = projectile_scene(scn_path, node, kind, size, pl["trail"], frames_res, mat_res, pl["blend"] == "add", ramp,
                               tex_res)
        man.add(scn, "scene", node="Node2D > Trail + Body", trail=pl["trail"], autoplay="fly")
    else:
        off = (0, -(size // 2)) if pl["anchor"] == "bottom" else (0, 0)
        scn = sprite_scene(scn_path, node, frames_res, mat_res if pl["blend"] == "add" else None, "play", off)
        man.add(scn, "scene", node="AnimatedSprite2D", autoplay="play", blend=pl["blend"], anchor=pl["anchor"])
    core.log(f"vfx {name}: {kind}, {n} frames at {fps} fps, {size} px" + (" (loop)" if loop else "")
             + (f", trail {pl['trail']}" if kind in PROJECTILES else ""))
    if kind in PROJECTILES:
        shots = composite(kind, size, pl["trail"], body, strip, ramp, pl["seed"], n)
    else:
        shots = [Image.fromarray(a) for a in body]
    paths = []
    for i, im in enumerate(shots):
        paths.append(core.work("vfx", f"{name}_review_{i:02d}.png"))
        im.save(paths[-1])
    return (f"{name} ({kind})", paths)


def _particle_entry(pl, base, res, man, mat_res):
    name, kind, p, area, ramp = (pl[k] for k in ("name", "kind", "particles", "area", "ramp"))
    out = os.path.join(base, name)
    man.drop_dir(out)
    tex = mask(p["mask"])
    tp = core.save_clean(Image.fromarray(tex), os.path.join(out, f"vfx_{name}_particle.png"))
    man.add(tp, "particle_texture", mask=p["mask"], usage="white mask, tinted by the emitter's colour steps",
            workflow=f"Dotwork vfx {kind} (drawn in code)")
    offs, cols = life_gradient(ramp)
    k = area / p["size"]
    meta = {"texture": f"vfx_{name}_particle.png", "amount": p["amount"], "lifetime": p["lifetime"],
            "one_shot": p["one_shot"], "explosiveness": p["explosiveness"], "randomness": p["randomness"],
            "blend": p["blend"],
            "emission": {"shape": p["shape"], "extents_px": [round(area * e, 2) for e in p["extents"]]},
            "direction": list(p["direction"]), "spread_deg": p["spread"],
            "speed_px_s": [round(v * k, 2) for v in p["speed"]],
            "gravity_px_s2": [round(v * k, 2) for v in p["gravity"]],
            "damping": [round(v * k, 2) for v in p["damping"]],
            "colour_steps": [{"from_life": round(o, 4), "rgba": [int(c[0]), int(c[1]), int(c[2]), c[3]]}
                             for o, c in zip(offs, cols)]}
    mp = core.write_text(os.path.join(out, f"vfx_{name}_particles.json"), json.dumps(meta, indent=1) + "\n")
    man.add(mp, "particles_json", usage="emitter settings for engines without GPUParticles2D")
    scn = particle_scene(os.path.join(out, f"vfx_{name}.tscn"), "Vfx" + name.title().replace("_", ""),
                         f"{res}/{name}/vfx_{name}_particle.png", mat_res if p["blend"] == "add" else None, p, area,
                         ramp)
    man.add(scn, "scene", node="GPUParticles2D", amount=p["amount"], one_shot=p["one_shot"],
            explosiveness=p["explosiveness"], blend=p["blend"])
    core.log(f"vfx {name}: {kind}, {p['amount']} particles over {p['lifetime']} s"
             + (" (one-shot)" if p["one_shot"] else " (loop)"))
    life = p["lifetime"]
    times = ([life * i / 5 for i in range(6)] if p["one_shot"] else [life * (2 + i / 6) for i in range(6)])
    canvas = (max(32, area * 3), max(32, area * 3))
    org = (canvas[0] / 2, canvas[1] * (0.75 if p["direction"][1] < 0 and p["shape"] == "box" else 0.5))
    paths = []
    for i, a in enumerate(simulate(p, area, ramp, tex, times, canvas, org, pl["seed"])):
        paths.append(core.work("vfx", f"{name}_review_{i:02d}.png"))
        Image.fromarray(a).save(paths[-1])
    return (f"{name} ({kind})", paths)


def run(entries, pack, man, conf):
    base = core.art(conf, "fx", "vfx")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/fx/vfx'
    plan = [_plan(e) for e in entries]   # every entry is checked before anything is written
    if not plan:
        return
    mat = godot.additive_material(os.path.join(base, "mat_additive.tres"))
    man.add(mat, "material", blend_mode="add")
    mat_res = f"{res}/mat_additive.tres"
    review = [(_particle_entry if "particles" in pl else _sprite_entry)(pl, base, res, man, mat_res) for pl in plan]
    import engine as lib
    lib.sheet(review, core.src(conf, "art", "fx", "vfx_review.png"), scale=3, bg=(16, 14, 22))
