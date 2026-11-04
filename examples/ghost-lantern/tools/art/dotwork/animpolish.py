#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# animpolish.py
# Purpose : animation polish for character clips, all drawn or timed in code and all opt-in: frame holds (per-frame
#           durations in the SpriteFrames: a wind-up held longer, a hit-stop on the impact), a smear on the frame of
#           peak motion (the moving part dragged back along its motion, in the frame's own colours), and the game's
#           sprite shaders: the hit flash (the hitfx lane's damage flash, reused) and a pixel-art dissolve, each a
#           .gdshader + ShaderMaterial in <art>/fx/shaders.
# Usage   : character entry keys (lane_character reads them, this module does the work):
#           "holds": true | ["attack"] | {"attack": true, "cast_w": [1, 1, 2, 1, 3, 1, 1, 1],
#                    "shoot": {"windup": 3, "impact": 1.5}, "walk": {"3": 2.0}}
#           "smear": true | ["attack", "cast"] | {"attack_e": true}
#           "shaders": true | ["flash", "dissolve"]
#           (true covers the strikes: attack, cast and shoot; "anticipation" is pose.py's, checked here too)
# Notes   : The peak frame is measured, not assumed: between the frame before and the frame after each frame (a
#           central difference), with the body aligned, the silhouette pixels that moved clear of the old outline times
#           how far they went; so it works the same on a free Wan clip and on a skeleton-driven one, ignores the export
#           re-centring a frame and a generator redrawing its outline. The smear REPLACES the peak frame instead of adding one: the frame count, the loop
#           timing, the sheet layout and every hold index stay as they were, and in hand animation the smear is the
#           in-between itself, not an extra frame. Holds default to the frame before the peak (the wind-up) and the
#           frame after it (the impact); a skeleton strike uses the skeleton's strike frame (pose.STRIKE, lane_character)
#           instead. Frame numbers count from 0, as in the file names (_00 first).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import math
import os

import numpy as np
from PIL import Image

import engine
import fcore as core
import godot
import pose

STRIKES = ("attack", "cast", "shoot")   # what true covers for holds and smear
# "holds": true: (wind-up frame, impact frame) durations around the peak frame. An attack holds its wind-up a beat
# and freezes on the hit (hit-stop); a cast gathers, then holds the release; a shot holds the aim, the recoil is quick
HOLDS = {"attack": (2.0, 3.0), "cast": (2.0, 2.0), "shoot": (3.0, 1.5)}
HOLD_ANY = (2.0, 2.0)   # an action outside HOLDS named with true
MAX_HOLD = 20.0
SMEAR_MAX = 24          # px: the longest smear (a fast swing can move further than that between two frames)
SMEAR_MIN_PX = 6        # px that must arrive and leave between two frames before a smear is drawn
# #187: what a smear may drag. The body is the figure's thick mass (torso, coat, legs: BODY_PX across or more, a
# morphological opening); blades and thin limbs are narrower. Measured 2026-11-04 on the showcase duelist's real
# strike frames (72 px): the lunges that smeared the coat had 55-66 % of their moved pixels in the body, the
# blade swings 0-4 %, a front-view cast 8-14 %. The feet are the bottom FEET_SHARE of the figure: a step moves them
SMEAR_BODY = 0.5        # share of the moved pixels in the body at which the smear is skipped (a step or a lunge)
BODY_PX = 7             # px: thinner than this is a part (a blade, an arm), not the body
FEET_SHARE = 0.12       # the bottom share of the figure's height that is feet, never a part to smear
PART_GAP = 3            # px between two pieces of one moving part (a blade split by the hand that holds it)
REACH = 12              # px: how far align() looks for the body between two frames
CLEAR = 2               # px from the old silhouette before a change counts as motion (outline redraws do not)
DIRS = ("s", "se", "e", "ne", "n", "nw", "w", "sw")


# -------------------------------------------------- spec keys
def _covered(value, what, actions):
    """The action / clip names a polish key's value names: true -> None (the key's default set), a list of actions,
    or a dict keyed by action or clip ("attack_w"). Unknown names are typos: refused before any render."""
    if value is True:
        return None
    if isinstance(value, (list, tuple)):
        names = [str(v) for v in value]
    elif isinstance(value, dict):
        names = [str(k) for k in value]
    else:
        raise core.ToolError(f"{what}: true, a list of actions or an object by action / clip, not {value!r}")
    for n in names:
        act, _, d = n.rpartition("_")
        if n not in actions and not (act in actions and d in DIRS):
            raise core.ToolError(f"{what}: {n!r} is not one of the character's actions ({', '.join(actions)}) or a "
                                 "clip of one (attack_w)")
    return names


def _number(v, what, lo=0.0, hi=MAX_HOLD):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo < float(v) <= hi:
        raise core.ToolError(f"{what}: {v!r} must be a number above {lo:g} and at most {hi:g}")
    return float(v)


def check(name, e, actions, skeleton):
    """Every polish key of a character entry checked before anything renders; returns the anticipation amount per
    skeleton action ({action: 0 < a <= 1}, only the ones that get it)."""
    if e.get("holds") not in (None, False):
        names = _covered(e["holds"], f"character {name}: holds", actions)
        for k in (names if isinstance(e["holds"], dict) else []):
            rule, what = e["holds"][k], f"character {name}: holds {k}"
            if rule is True or rule is False:
                continue
            if isinstance(rule, (list, tuple)):
                if not rule:
                    raise core.ToolError(f"{what}: an empty list")
                for v in rule:
                    _number(v, what)
            elif isinstance(rule, dict):
                pair = set(rule) <= {"windup", "impact"}
                for fk, v in rule.items():
                    if not pair and not str(fk).lstrip("-").isdigit():
                        raise core.ToolError(f"{what}: keys are frame numbers (\"3\") or windup / impact, not {fk!r}")
                    _number(v, what)
            else:
                raise core.ToolError(f"{what}: true, a list of durations, {{\"windup\", \"impact\"}} or "
                                     f"{{frame: duration}}, not {rule!r}")
    if e.get("smear") not in (None, False):
        _covered(e["smear"], f"character {name}: smear", actions)
    if e.get("shaders") not in (None, False):
        kinds = list(SHADERS) if e["shaders"] is True else e["shaders"]
        if not isinstance(kinds, (list, tuple)) or not kinds or any(k not in SHADERS for k in kinds):
            raise core.ToolError(f"character {name}: shaders is true or a list of {', '.join(SHADERS)}")
    wind = {}
    v = e.get("anticipation")
    if v in (None, False):
        return wind
    names = _covered(v, f"character {name}: anticipation", actions)
    for a in (names if names is not None else [a for a in skeleton if a in pose.ANTICIPATE]):
        if a not in pose.ANTICIPATE or a not in skeleton:
            raise core.ToolError(f"character {name}: anticipation {a!r}: only skeleton actions among "
                                 f"{', '.join(pose.ANTICIPATE)} get a wind-up (list it in \"skeleton\" too)")
        amt = v.get(a, True) if isinstance(v, dict) else True
        if amt is not False:
            wind[a] = 1.0 if amt is True else _number(amt, f"character {name}: anticipation {a}", 0.0, 1.0)
    return wind


def pick(value, action, direction):
    """What a polish key says for one clip: None when it does not cover it, else True or the clip's / action's own
    setting (the clip's "attack_w" wins over the action's "attack")."""
    if value in (None, False):
        return None
    if value is True:
        return True if action in STRIKES else None
    if isinstance(value, (list, tuple)):
        return True if action in value else None
    got = value.get(f"{action}_{direction}", value.get(action))
    return None if got in (None, False) else got


# -------------------------------------------------- measuring motion
def _rgba(img):
    return np.array(img.convert("RGBA"))


def opaque(img):
    return _rgba(img)[..., 3] >= 128


def _keys(a):
    """One int per pixel: its colour (r << 16 | g << 8 | b), -1 where it is transparent."""
    k = (a[..., 0].astype(np.int64) << 16) | (a[..., 1].astype(np.int64) << 8) | a[..., 2]
    return np.where(a[..., 3] >= 128, k, -1)


def _grow(mask, r=1):
    """mask dilated by r px (8 neighbours)."""
    out = mask.copy()
    for _ in range(r):
        p = np.pad(out, 1)
        out = np.zeros_like(mask)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                out |= p[1 + dy:1 + dy + mask.shape[0], 1 + dx:1 + dx + mask.shape[1]]
    return out


def _shift(a, dy, dx, fill):
    """a moved dy rows down and dx columns right; what comes in is fill."""
    out = np.full_like(a, fill)
    h, w = a.shape[:2]
    out[max(0, dy):h + min(0, dy), max(0, dx):w + min(0, dx)] = \
        a[max(0, -dy):h - max(0, dy), max(0, -dx):w - max(0, dx)]
    return out


def align(prev, cur, reach=REACH):
    """(dy, dx) that lays the body of prev on the body of cur: the shift (up to reach px sideways, half that up or down)
    with the most pixels of the same colour; the smallest shift wins a tie. The export centres each frame on its own
    bounding box, so a sword that sticks out moves the whole body sideways in that frame: without this, the body's
    jump counted as motion and the smear dragged the hat."""
    pk, ck = _keys(prev), _keys(cur)
    best, at = -1, (0, 0)
    shifts = sorted(((dy, dx) for dy in range(-reach // 2, reach // 2 + 1) for dx in range(-reach, reach + 1)),
                    key=lambda d: (abs(d[0]) + abs(d[1]), d))
    for dy, dx in shifts:
        score = int(((_shift(pk, dy, dx, -1) == ck) & (ck >= 0)).sum())
        if score > best:
            best, at = score, (dy, dx)
    return at


def _moved(prev, cur):
    """(arrived, left, every arrived pixel) between two RGBA arrays with the body aligned. arrived: opaque in cur and
    at least CLEAR px from the aligned prev's silhouette (the moving part out in space); left: the same the other way
    round (where it was and is no more). A generator redraws the outline a pixel in or out on every frame; those rims
    are within CLEAR px of the old silhouette, so they never count as motion. A thin blade out in space still does
    (an opening would erase it)."""
    dy, dx = align(prev, cur)
    was = _shift(prev[..., 3] >= 128, dy, dx, False)
    now = cur[..., 3] >= 128
    new = now & ~was
    return new & ~_grow(was, CLEAR), was & ~now & ~_grow(now, CLEAR), new


def _step(arrived, left):
    """(vy, vx): from the centre of where the part was to the centre of where it is now; (0, 0) when either is empty."""
    if not arrived.any() or not left.any():
        return 0.0, 0.0
    ay, ax = np.nonzero(arrived)
    ly, lx = np.nonzero(left)
    return float(ay.mean() - ly.mean()), float(ax.mean() - lx.mean())


def _dist(mask, upto):
    """Steps (8 neighbours) from mask to every pixel, up to `upto`; upto + 1 beyond that."""
    d = np.full(mask.shape, upto + 1, np.int32)
    d[mask] = 0
    reach = mask.copy()
    for r in range(1, upto + 1):
        grown = _grow(reach)
        d[grown & ~reach] = r
        reach = grown
    return d


def _main_part(arrived):
    """The largest piece of what arrived, with the pieces within PART_GAP px of it (a blade the hand splits in two).
    A boot or a coat hem that moved on its own, somewhere else on the figure, is not part of it."""
    lab, n = engine.label(arrived, 8)
    if n < 2:
        return arrived
    main = lab == 1 + int(np.argmax(np.bincount(lab[lab > 0])[1:]))
    return arrived & np.isin(lab, np.unique(lab[_grow(main, PART_GAP) & arrived]))


def _nearest(left, part):
    """The pieces of what left that lie nearest the part (within PART_GAP px of the nearest one): where the part was.
    The body's own edges elsewhere left too, and paired with the part they bent its motion across the body."""
    lab, n = engine.label(left, 8)
    if n < 2:
        return left
    d = _dist(part, 4 * SMEAR_MAX)
    near = [int(d[lab == i].min()) for i in range(1, n + 1)]
    return np.isin(lab, [i + 1 for i, v in enumerate(near) if v <= min(near) + PART_GAP])


def _body(mask):
    """The thick mass of a silhouette: what survives an opening BODY_PX wide (torso, coat, legs). A blade, a staff or
    a thin arm is narrower and drops out."""
    r = BODY_PX // 2
    mass = mask.copy()
    for _ in range(r):
        mass = engine.erode(mass, 8)
    return _grow(mass, r) & mask


def _feet(mask):
    """The rows of the bottom FEET_SHARE of a silhouette (its feet and boot soles)."""
    out = np.zeros_like(mask)
    ys = np.nonzero(mask.any(1))[0]
    if len(ys):
        out[int(ys.max() + 1 - FEET_SHARE * (ys.max() - ys.min() + 1)):] = True
    return out


def speeds(frames, loop):
    """Motion per frame, between the frame before and the frame after (a central difference, so the speed belongs to
    the frame itself), the body aligned: how many pixels moved clear of the old silhouette times how far they went.
    The count alone stops growing once a part travels further than its own size (a sword 6 px deep moved 9 or 17 px
    scored the same); the distance tells the fast frame from the slow one. A one-shot's first and last frames have no
    neighbour on one side: 0. A loop wraps."""
    a = [_rgba(f) for f in frames]
    n = len(a)
    out = [0] * n
    for i in range(n):
        if n < 3 or (not loop and i in (0, n - 1)):
            continue
        arrived, left, _ = _moved(a[(i - 1) % n], a[(i + 1) % n])
        out[i] = int(round((arrived.sum() + left.sum()) / 2 * max(1.0, math.hypot(*_step(arrived, left)))))
    return out


def peak(frames, loop):
    """The frame of peak motion (the first one on a tie), or None (fewer than 3 frames, or nothing moves)."""
    v = speeds(frames, loop)
    k = int(np.argmax(v)) if v else 0
    return k if v and v[k] > 0 else None


# -------------------------------------------------- smear
def smear(frames, k, max_len=SMEAR_MAX, min_px=SMEAR_MIN_PX):
    """Frame k with a smear drawn on it: (image, info) or (None, why not).
    The moving part is what arrived since the frame before, clear of the old silhouette with the body aligned (_moved),
    grown back into its base; its motion is the step from the centre of where it was to the centre of where it is (a
    part that came out of the body left nothing clear behind: then from the centre of everything that left, the body's
    middle). Only a part moves: when the body itself made most of the change (a step or a lunge reshapes it: SMEAR_BODY
    of the moved pixels in its thick mass, _body) there is no smear; otherwise the body's mass and the feet are left
    out, the part is the largest piece that is left (_main_part) and where it was is the nearest piece that left
    (_nearest), so a boot or a coat hem that moved elsewhere on the figure is neither smeared nor bends the motion.
    Copies of the part are stamped back along that
    motion, 1 px at a time up to its length (SMEAR_MAX at most), into empty pixels only: the body stays as drawn and
    only the space the part swept through fills in. The copies leave out the frame's outline colour (its darkest) when
    the part has other colours, so the smear reads as the part's own colours dragged, not as dark streaks; the far half
    thins to a checker, so it tapers. Every new pixel copies one of the frame's own pixels: no colour outside its
    palette, no partial alpha."""
    n = len(frames)
    prev, cur = _rgba(frames[(k - 1) % n]), _rgba(frames[k])
    now = cur[..., 3] >= 128
    arrived, left, new = _moved(prev, cur)
    if arrived.sum() < min_px:
        return None, f"under {min_px} px moved clear of the body between frames {(k - 1) % n} and {k}"
    # #187: a lunge changes the body's shape, which the alignment cannot undo: the coat's back edge and the boots
    # arrived, its front edge left. Those pieces joined the part, the step ran between them across the body, and the
    # stamps left a checker trail behind the coat and at the feet. Mostly body: no smear. Otherwise only a part
    # moves: the body's thick mass and the feet are taken out, then one piece is the part and the nearest piece that
    # left is where it was
    dy, dx = align(prev, cur)
    was = _shift(prev[..., 3] >= 128, dy, dx, False)
    body_now, body_was = _body(now), _body(was)
    share = ((arrived & body_now).sum() + (left & body_was).sum()) / max(1, arrived.sum() + left.sum())
    if share >= SMEAR_BODY:
        return None, (f"what moved between frames {(k - 1) % n} and {k} is mostly the body ({share:.0%}: a step or "
                      "a lunge, not a part swinging clear of it)")
    feet = _feet(now)
    arrived, left, new = arrived & ~body_now & ~feet, left & ~body_was & ~feet, new & ~body_now & ~feet
    if arrived.sum() < min_px:
        return None, (f"under {min_px} px of a part moved clear of the body between frames {(k - 1) % n} and {k} "
                      "(the rest is the body or the feet)")
    arrived = _main_part(arrived)
    if left.sum() < min_px:
        left = was & ~now & ~body_was & ~feet
        if not left.any():
            return None, f"nothing left its place between frames {(k - 1) % n} and {k}"
    left = _nearest(left, arrived)
    for _ in range(CLEAR):   # back into the part's base, through the pixels that are new in this frame
        arrived = _grow(arrived) & new
    vy, vx = _step(arrived, left)
    length = math.hypot(vx, vy)
    if length < 2:
        return None, f"the moving part moved {length:.1f} px (under 2)"
    part = arrived & (cur[..., 3] == 255)
    keys = _keys(cur)
    solid = keys[cur[..., 3] == 255]
    luma = (299 * (solid >> 16) + 587 * ((solid >> 8) & 255) + 114 * (solid & 255)) if len(solid) else solid
    if len(solid):
        fill = part & (keys != solid[int(np.argmin(luma))])   # the outline colour stays out of the smear
        part = fill if fill.sum() >= min_px else part
    py, px = np.nonzero(part)
    cols = cur[py, px]
    steps = int(round(min(length, max_len)))
    uy, ux = vy / length, vx / length
    out, filled = cur.copy(), now.copy()
    h, w = now.shape
    for j in range(1, steps + 1):   # nearest copies first: a pixel already filled keeps the nearer copy
        ty, tx = py + int(round(-uy * j)), px + int(round(-ux * j))
        ok = (ty >= 0) & (ty < h) & (tx >= 0) & (tx < w)
        ty, tx, c = ty[ok], tx[ok], cols[ok]
        free = ~filled[ty, tx]
        if j > steps / 2:
            free &= (ty + tx) % 2 == 0
        ty, tx, c = ty[free], tx[free], c[free]
        out[ty, tx] = c
        filled[ty, tx] = True
    added = int((filled & ~now).sum())
    if not added:
        return None, "the smear had no empty pixels to fill (the part moved over the body)"
    return Image.fromarray(out), {"frame": k, "vector": (round(float(vx), 1), round(float(vy), 1)), "length": steps,
                                  "px": added}


# -------------------------------------------------- holds
def durations(n, k, rule, action, loop, at="the peak frame"):
    """(one relative duration per frame, a note) for a clip of n frames whose peak frame is k (or None; at: what the
    note calls k, "the strike frame" for a skeleton strike).
    rule: True (HOLDS for the action: the frame before the peak is the wind-up, the frame after it the impact),
    {"windup": w, "impact": i} (the same with its own numbers), a list (one per frame; padded with 1.0 or cut when the
    clip has another count, said in the note), or {"<frame>": duration} (only those frames). (None, why) when a
    peak-based rule finds no peak."""
    d = [1.0] * n
    if rule is True or (isinstance(rule, dict) and rule and set(rule) <= {"windup", "impact"}):
        w, im = HOLDS.get(action, HOLD_ANY) if rule is True else (float(rule.get("windup", 1.0)),
                                                                  float(rule.get("impact", 1.0)))
        if k is None:
            return None, "holds skipped: no frame of peak motion (under 3 frames, or nothing moves)"
        marks = []
        for idx, val, what in ((k - 1, w, "wind-up"), (k + 1, im, "impact")):
            idx = idx % n if loop else idx
            if 0 <= idx < n and val != 1.0:
                d[idx] = val
                marks.append(f"frame {idx} x{val:g} ({what})")
        return d, f"holds around {at} {k}: " + (", ".join(marks) or "none fit the clip")
    if isinstance(rule, (list, tuple)):
        vals = [float(v) for v in rule][:n]
        fit = "cut" if len(rule) > n else "padded with 1.0"
        note = "" if len(rule) == n else f" ({len(rule)} values for {n} frames: {fit})"
        d[:len(vals)] = vals
        return d, "holds as listed" + note
    marks, out = [], []
    for fk, v in rule.items():
        i = int(fk)
        if -n <= i < n:
            d[i] = float(v)
            marks.append(f"frame {i % n} x{float(v):g}")
        else:
            out.append(str(fk))
    return d, "holds: " + (", ".join(marks) or "none") + (f" (frames {', '.join(out)} are past the clip's {n})"
                                                          if out else "")


# -------------------------------------------------- shaders
DISSOLVE = """shader_type canvas_item;
// Dotwork dissolve: the sprite breaks up in noise order as "progress" goes 0 -> 1 (tween it over about 0.6 s for a
// defeat or a teleport; 1 -> 0 brings it back), with a band of edge_color on the pixels about to go. Pixel-art safe:
// the noise is worked out per whole texel (blocks of pixel_size texels), so the sprite falls apart along its own pixel
// grid with hard edges and no partial alpha, and every pixel reads its texel's centre whatever the node's texture
// filter. No noise texture: seed picks another order.
uniform float progress : hint_range(0.0, 1.0) = 0.0;
uniform float edge_width : hint_range(0.0, 0.5) = 0.1;
uniform vec4 edge_color : source_color = vec4(1.0, 0.85, 0.4, 1.0);
uniform float noise_scale : hint_range(1.0, 32.0) = 5.0;
uniform float pixel_size : hint_range(1.0, 8.0) = 1.0;
uniform float seed = 0.0;

varying vec4 tint;

float hash(vec2 p) {
	return fract(sin(dot(p + vec2(seed, seed * 1.7), vec2(127.1, 311.7))) * 43758.5453);
}

float blob(vec2 p) {   // value noise: smooth blobs between hashed lattice corners
	vec2 i = floor(p);
	vec2 f = fract(p);
	f = f * f * (3.0 - 2.0 * f);
	float a = hash(i);
	float b = hash(i + vec2(1.0, 0.0));
	float c = hash(i + vec2(0.0, 1.0));
	float d = hash(i + vec2(1.0, 1.0));
	return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

void vertex() {
	tint = COLOR;   // modulate and self_modulate
}

void fragment() {
	vec2 texel = floor(UV / TEXTURE_PIXEL_SIZE);              // this pixel's whole-texel coordinate
	vec2 cell = floor(texel / max(1.0, floor(pixel_size)));   // snapped to the dissolve block
	vec4 c = texture(TEXTURE, (texel + 0.5) * TEXTURE_PIXEL_SIZE) * tint;
	// blobs with a ragged rim, stretched over 0 .. 1 (the mix bunches round 0.5), so progress reads evenly
	float n = clamp((0.7 * blob(cell / noise_scale) + 0.3 * hash(cell) - 0.12) / 0.76, 0.0, 0.999);
	float cut = progress * (1.0 + edge_width) - edge_width;   // 0: nothing goes, 1: everything (edge too) has gone
	if (n < cut) {
		c.a = 0.0;
	} else if (n < cut + edge_width) {
		c.rgb = edge_color.rgb;
	}
	COLOR = c;
}
"""

FLASH_FILE, DISSOLVE_FILE = "damage_flash", "dissolve"
# name: (file stem, material parameters in the order written, how to use it). "flash" is the damage flash the hitfx
# lane writes (lane_hitfx.FLASH_SHADER, the same two files byte for byte), so a game has one flash shader whichever
# lane asked for it; "dissolve" sits next to it in the same folder, written the same way
SHADERS = {
    "flash": (FLASH_FILE, (("flash", "0.0"), ("flash_color", "Color(1, 1, 1, 1)")),
              "set as the sprite's material; tween shader_parameter/flash 1 -> 0 over ~0.15 s on hit"),
    "dissolve": (DISSOLVE_FILE, (("progress", "0.0"), ("edge_width", "0.1"), ("edge_color", "Color(1, 0.85, 0.4, 1)"),
                                 ("noise_scale", "5.0"), ("pixel_size", "1.0"), ("seed", "0.0")),
                 "set as the sprite's material; tween shader_parameter/progress 0 -> 1 over ~0.6 s (1 -> 0 to appear)"),
}


def material_text(shader_res, params):
    """A ShaderMaterial .tres in the hitfx lane's layout (mat_damage_flash.tres comes out byte-identical). One material
    file is shared by every node that uses it: give each sprite its own copy (material.duplicate(), or Local To Scene
    in the inspector), or one hit flashes them all."""
    return "\n".join(['[gd_resource type="ShaderMaterial" load_steps=2 format=3]', "",
                      f'[ext_resource type="Shader" path="{shader_res}" id="1_sh"]', "",
                      "[resource]", 'shader = ExtResource("1_sh")']
                     + [f"shader_parameter/{k} = {v}" for k, v in params] + [""])


def write_shaders(conf, man, kinds):
    """<art>/fx/shaders/<stem>.gdshader + mat_<stem>.tres for each kind, where the hitfx lane keeps its damage flash
    (shared by every character that asks, like the spells' mat_additive.tres). Returns the files written; --engine none
    writes nothing (Godot shaders)."""
    if not godot.ENABLED:
        core.log(f"shaders {', '.join(kinds)}: skipped (--engine none: they are Godot shaders)")
        return []
    import lane_hitfx   # the flash shader's one source
    art = core.art(conf, "fx", "shaders")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/fx/shaders'   # as lane_hitfx writes it
    made = []
    for kind in kinds:
        stem, params, usage = SHADERS[kind]
        code = lane_hitfx.FLASH_SHADER if kind == "flash" else DISSOLVE
        sp = godot._write(os.path.join(art, f"{stem}.gdshader"), code)
        mp = godot._write(os.path.join(art, f"mat_{stem}.tres"), material_text(f"{res}/{stem}.gdshader", params))
        man.add(sp, "shader", uniforms=[k for k, _ in params], routes=(), usage=usage,
                workflow="Dotwork " + ("hitfx" if kind == "flash" else "animpolish") + " (written in code)")
        man.add(mp, "material", shader=f"{stem}.gdshader")
        made += [sp, mp]
    core.log(f"shaders: {', '.join(kinds)} (fx/shaders: " + ", ".join(SHADERS[k][0] for k in kinds) + ")")
    return made
