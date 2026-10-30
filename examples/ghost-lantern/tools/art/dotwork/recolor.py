#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# recolor.py
# Purpose : palette swaps, the classic way a 16-bit bestiary grows (a green hound, a frost hound, a fire hound from
#           one sprite): turn the hue of a sprite's coloured ramps, keep its outline and greys, and snap every new
#           colour back into the game's palette. One colour map serves every frame given, so an animation recolours
#           consistently.
# Usage   : pack spec "enemies": [{"name": "hound", "prompt": "..."}, {"name": "frost_hound", "recolor_of": "hound",
#           "hue": 150}]      or      python dotwork.py recolor --source "assets/art/props/barrel/*.png" --hue 120
#           --out assets/art/props/barrel_green
# Notes   : hue turns in degrees (OKLCh, so 180 is the opposite colour at the same lightness); "to": "#3a6ea5" turns
#           the sprite's main hue to that colour's instead. saturation scales chroma, lightness adds to OKLab L
#           (-0.2 .. 0.2 is a useful range). "hues": [lo, hi] limits the swap to source hues in that range (the red
#           cloak only), min_chroma (OKLab chroma, default 0.02) keeps near-greys (outlines, steel) untouched; 0.04
#           also keeps dark browns and muted tones (a swap of the trim only). keep_skin true leaves skin tones alone
#           (OKLCh hue 20-70, lightness >= 0.45, chroma <= 0.13; tan leather in that range stays too): the NPC lane's
#           default, so a variant townsperson does not get a green face.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import os

import numpy as np
from PIL import Image

import fcore as core
from engine import load_hex, oklab

M1_INV = np.array([[1.0, 0.3963377774, 0.2158037573], [1.0, -0.1055613458, -0.0638541728],
                   [1.0, -0.0894841775, -1.2914855480]])
M2_INV = np.array([[4.0767416621, -3.3077115913, 0.2309699292], [-1.2684380046, 2.6097574011, -0.3413193965],
                   [-0.0041960863, -0.7034186147, 1.7076147010]])
REUSE_PENALTY = 0.03   # OKLab distance added to a palette colour another source colour already took (keeps ramps)
TWIN = 0.02            # closer than this (OKLab) is one shade: may share (twins 0.004-0.012, ramp steps 0.026+)


def to_rgb(lab):
    """OKLab (N, 3) -> sRGB uint8 (N, 3), clipped into gamut."""
    lms = (lab @ M1_INV.T) ** 3
    lin = np.clip(lms @ M2_INV.T, 0, 1)
    c = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return np.clip(np.round(c * 255), 0, 255).astype(np.uint8)


def lch(rgb):
    """sRGB (N, 3) -> (L, C, h degrees) arrays."""
    lab = oklab(np.asarray(rgb).reshape(-1, 3))
    return lab[:, 0], np.hypot(lab[:, 1], lab[:, 2]), np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360


def in_hues(h, hues):
    """Hue mask for a [lo, hi] range in degrees; lo > hi wraps through 0 (reds: [330, 30])."""
    if not hues:
        return np.ones(len(h), bool)
    lo, hi = float(hues[0]) % 360, float(hues[1]) % 360
    return (h >= lo) & (h <= hi) if lo <= hi else (h >= lo) | (h <= hi)


def main_hue(rgb, counts, mask):
    """Count-weighted circular mean hue of the masked colours, chroma-weighted so vivid colours lead."""
    _, c, h = lch(rgb[mask])
    w = counts[mask] * c
    if w.sum() == 0:
        return None
    r = np.radians(h)
    return float(np.degrees(np.arctan2((w * np.sin(r)).sum(), (w * np.cos(r)).sum())) % 360)


SKIN = (20.0, 70.0, 0.45, 0.13)   # OKLCh hue range, lightness floor, chroma ceiling of skin tones (keep_skin)


def plan(colors, counts, pal, hue=0.0, saturation=1.0, lightness=0.0, hues=None, to=None, min_chroma=0.02,
         keep_skin=False):
    """{source RGB tuple: palette RGB tuple} for every colour that changes.

    colors (N, 3) uint8 unique source colours with pixel counts; pal (P, 3) uint8 the game palette. Colours below
    min_chroma (outline, greys, steel) and outside `hues` keep their value. The most-used colours pick first and a
    palette colour a *different* source colour already took costs REUSE_PENALTY more, so a 4-step ramp stays 4 steps
    instead of collapsing onto one palette entry. Near-twins (closer than TWIN: an animation's many almost-equal shades
    of one cap) are not pushed apart: the penalty used to send them to different palette colours, and a variant's cap
    came out navy from the front and green from the side (2026-10-30)."""
    colors = np.asarray(colors, np.uint8).reshape(-1, 3)
    counts = np.asarray(counts, np.float64).reshape(-1)
    L, C, H = lch(colors)
    move = (C >= min_chroma) & in_hues(H, hues)
    if keep_skin:
        lo, hi, lmin, cmax = SKIN
        move &= ~((H >= lo) & (H <= hi) & (L >= lmin) & (C <= cmax))
    if not move.any():
        return {}
    turn = float(hue)
    if to:
        t = to.lstrip("#")
        if len(t) != 6:
            raise core.ToolError(f"recolor: \"to\" must be a #RRGGBB colour, not {to!r}")
        target = lch(np.array([[int(t[i:i + 2], 16) for i in (0, 2, 4)]], np.uint8))[2][0]
        src = main_hue(colors, counts, move)
        turn = (target - src) if src is not None else 0.0
    h2 = np.radians(H + turn)
    c2 = C * float(saturation)
    lab2 = np.stack([np.clip(L + float(lightness), 0, 1), c2 * np.cos(h2), c2 * np.sin(h2)], axis=1)
    want = oklab(to_rgb(lab2))   # back through sRGB: the in-gamut colour the shift asks for
    pl = oklab(np.asarray(pal, np.uint8))
    src = oklab(colors)
    holders = {}   # palette index -> OKLab of the source colours that hold it (unchanged colours hold their own)
    for i in np.nonzero(~move)[0]:
        hit = np.nonzero((pal == colors[i]).all(1))[0]
        if len(hit):
            holders.setdefault(int(hit[0]), []).append(src[i])
    out = {}
    for i in np.argsort(-counts):
        if not move[i]:
            continue
        taken = np.array([j in holders and min(np.sqrt(((np.array(holders[j]) - src[i]) ** 2).sum(-1))) > TWIN
                          for j in range(len(pal))])
        d = np.sqrt(((pl - want[i]) ** 2).sum(-1)) + REUSE_PENALTY * taken
        j = int(np.argmin(d))
        holders.setdefault(j, []).append(src[i])
        out[tuple(int(v) for v in colors[i])] = tuple(int(v) for v in pal[j])
    return out


def apply(img, mapping):
    """Recolour one RGBA image with a plan() map (alpha untouched)."""
    a = np.array(img.convert("RGBA"))
    if mapping:
        flat = a.reshape(-1, 4)
        keys = flat[:, 0].astype(np.int64) << 16 | flat[:, 1].astype(np.int64) << 8 | flat[:, 2]
        for s, d in mapping.items():
            m = keys == (s[0] << 16 | s[1] << 8 | s[2])
            flat[m, :3] = d
    return Image.fromarray(a, "RGBA")


def colours_of(images):
    """(unique RGB, counts) over the opaque pixels of every image: one map for a whole frame set."""
    px = [np.asarray(im.convert("RGBA")).reshape(-1, 4) for im in images]
    px = np.concatenate([p[p[:, 3] >= 128, :3] for p in px]) if px else np.zeros((0, 3), np.uint8)
    if not len(px):
        return np.zeros((0, 3), np.uint8), np.zeros(0)
    return np.unique(px, axis=0, return_counts=True)


def recolor(images, pal, **kw):
    """(recoloured images, map) for a list of RGBA images sharing one colour map."""
    cols, counts = colours_of(images)
    mapping = plan(cols, counts, pal, **kw)
    return [apply(im, mapping) for im in images], mapping


def options(e):
    """The swap settings of a spec entry (or the command line, as a dict)."""
    o = {"hue": float(e.get("hue", 0)), "saturation": float(e.get("saturation", 1.0)),
         "lightness": float(e.get("lightness", 0.0)), "hues": e.get("hues"), "to": e.get("to"),
         "min_chroma": float(e.get("min_chroma", 0.02)), "keep_skin": bool(e.get("keep_skin", False))}
    if o["hues"] is not None and (not isinstance(o["hues"], (list, tuple)) or len(o["hues"]) != 2):
        raise core.ToolError(f"{e.get('name', 'recolor')}: \"hues\" is [lo, hi] in degrees, e.g. [330, 30] for reds")
    if not (o["hue"] or o["to"] or o["saturation"] != 1.0 or o["lightness"]):
        raise core.ToolError(f"{e.get('name', 'recolor')}: a palette swap needs hue, to, saturation or lightness")
    return o


def cmd(a, s):
    """dotwork.py recolor: every PNG matching --source, recoloured with one shared map, into --out (inside the game),
    plus a before / after review sheet in the work folder."""
    import engine as lib
    srcs = sorted({os.path.normpath(p) for g in a.source for p in glob.glob(core.project_path(g))})
    srcs = [p for p in srcs if p.lower().endswith(".png")]
    if not srcs:
        raise core.ToolError(f"recolor: no PNG files match {' '.join(a.source)} (paths are relative to the game)")
    for p in srcs:   # a glob can still reach a symlink that leads out; check every match
        core.project_path(os.path.relpath(p, s.project))
    out = core.project_path(a.out)
    names = [os.path.basename(p) for p in srcs]
    if len({os.path.normcase(n) for n in names}) != len(names):   # Lamp.png / lamp.png: one file on Windows
        raise core.ToolError("recolor: two sources share a file name; recolour one folder at a time")
    pal = load_hex(a.palette if a.palette not in ("obj", "env") else
                   s.conf["fixed"]["env_palette" if a.palette == "env" else "palette"])
    ims, mapping = recolor([Image.open(p) for p in srcs],
                           pal, **options({"name": "recolor", "hue": a.hue, "saturation": a.saturation,
                                           "lightness": a.lightness, "hues": a.hues, "to": a.to,
                                           "min_chroma": a.min_chroma}))
    os.makedirs(out, exist_ok=True)
    done = [core.save_clean(im, os.path.join(out, n)) for im, n in zip(ims, names)]
    sheet = os.path.join(core.WORK, "recolor", f"{core.snake(os.path.basename(out))}_review.png")
    lib.sheet([("before", srcs[:8]), ("after", done[:8])], sheet, scale=3)
    core.log(f"recolor: {len(done)} files -> {os.path.relpath(out, s.project)} ({len(mapping)} colours moved); "
             f"review {sheet}")
    return 0
