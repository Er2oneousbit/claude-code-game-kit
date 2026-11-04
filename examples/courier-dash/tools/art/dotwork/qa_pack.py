#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# qa_pack.py
# Purpose : `dotwork.py qa pack`: a style-consistency check across a game's whole Dotwork asset set, read from its
#           manifests (so every file's lane and kind are known): effective pixel scale, off-palette colours (each lane's
#           own lock rule, README "Palettes and style references"), outline colour and thickness, light direction,
#           figure height in tiles, contrast against the ground tiles, and colour-blind separation of colours that
#           must stay apart (gauge fills, status marks, button states, palette-swap variants). Optionally a lineup PNG:
#           every character and prop at game scale standing on a ground tile, labelled, for a by-eye check.
# Usage   : python tools/art/dotwork/dotwork.py qa pack [--project GAME] [--json OUT] [--lineup OUT.png]
# Notes   : Read only: it opens the manifests and the PNGs they list and writes nothing but --json / --lineup.
#           Exit 0 clean, 1 findings, 2 usage. Every threshold is a named constant below, with the measurement that
#           set it (calibrated on a 1114-PNG rehearsal game, 2026-11-01).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import json
import math
import os
import re
import time
from collections import Counter, defaultdict

import numpy as np
from PIL import Image, ImageDraw

from engine import erode, load_hex, oklab

DIRS = ("s", "se", "e", "ne", "n", "nw", "w", "sw")
OUTLINE = (5, 4, 7)   # engine.finish's outline colour; not in the palette files (pxclean adds it to the lock the same way)

# ---- thresholds ------------------------------------------------------------------------------
# 1. pixel scale
MIN_RUNS = 12            # runs per axis before a scale is trusted: a 1x sprite shows hundreds, a flat gauge fill 8
SCALE_MAX_SHARE = 8      # an upscaled pixel wider than 1/8 of the short side is too little detail to tell (focus ring)
# 2. palette
HITFX_MAX = 6            # README: "about 4 per frame" for code-drawn sparks and slashes (measured 2-4); 6 allows "about"
EFFECT_MAX = 16          # README: effects are reduced to 16 colours (measured 10-16 per frame)
TOOLS_EXTRA = 12         # README: tools keep the source's colours plus palette, "source count + 12"
# 3. outline
OUTLINE_TOL = 0.04       # OKLab distance still read as the pack's outline: (5,4,5) in clip frames vs (5,4,7) is 0.01
OUTLINE_MIN_SHARE = 0.5  # share of the silhouette edge in the outline colour; real props 0.81-1.00 (holes cut later)
OUTLINE_THICK = 0.5      # share of the second ring in the outline colour (2 px outline); real max 0.22 (a glyph)
# 4. light
LIGHT_MIN_PX = 60        # interior pixels before a light direction is trusted (a 16 px icon has about 80)
LIGHT_VOTE = 0.10        # |vx| an asset needs to vote for the pack's light side
LIGHT_CONSENSUS = 0.70   # share of the voters on one side before the pack has a light side at all
LIGHT_FLAG = 0.20        # |vx| on BOTH estimators, opposite the pack, to flag: the barrel, side-lit at a glance, is 0.23
MAT_AB_GAP = 0.06        # OKLab chroma-plane step that still continues a material (3 just-noticeable steps)
# 5. height
HEIGHT_MIN_CLASS = 3     # a class needs this many members before it has a usual height
HEIGHT_CHAR = 1.5        # characters: ratio to the class median either way (every one is drawn at fig_height)
HEIGHT_PROP = 4.0        # props: ratio to the class median either way (a barrel to a lamp post is about 2x)
HEIGHT_ASKED = 0.25      # a prop within 25 % of the size its canvas says it was asked for is as intended
# 6. contrast
CONTRAST_DE = 0.06       # OKLab distance under which a pixel melts into the ground colour (3 just-noticeable steps)
CONTRAST_SHARE = 0.5     # severe: at least half the silhouette edge AND half the body melt into a ground
# 7. colour-blind separation
CVD_NORMAL = 0.12        # pairs at least this far apart in normal vision are told apart by colour (OKLab)
CVD_SIM = 0.06           # ... and flagged when a simulated dichromat sees them closer than this

CHECKS = ("scale", "palette", "outline", "light", "height", "contrast", "colourblind")


# ---- colour science ---------------------------------------------------------------------------
def _linear(rgb):
    c = np.asarray(rgb, np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _srgb8(lin):
    lin = np.clip(lin, 0.0, 1.0)
    c = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    return np.clip(np.round(c * 255), 0, 255)


# Machado, Oliveira & Fernandes 2009, "A Physiologically-based Model for Simulation of Color Vision Deficiency",
# severity 1.0 (full dichromacy). The matrices act on linear RGB.
MACHADO = {
    "protanopia": np.array([[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216],
                            [-0.003882, -0.048116, 1.051998]]),
    "deuteranopia": np.array([[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413],
                              [-0.011820, 0.042940, 0.968881]]),
    "tritanopia": np.array([[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602],
                            [0.004733, 0.691367, 0.303900]]),
}


def simulate(rgb, kind):
    """sRGB colours (N x 3, 0-255) as a dichromat of `kind` sees them, back in sRGB 0-255."""
    return _srgb8(_linear(np.atleast_2d(rgb)) @ MACHADO[kind].T)


def de_ok(a, b):
    """OKLab distance between sRGB colours (0-255; rows broadcast). About 0.02 is a just-noticeable step side by side."""
    return np.sqrt(((oklab(np.atleast_2d(a)) - oklab(np.atleast_2d(b))) ** 2).sum(-1))


def cvd_pair(c1, c2):
    """(normal-vision distance, worst simulated distance, the deficiency that gave it) for two sRGB colours."""
    worst = min(((float(de_ok(simulate(c1, k), simulate(c2, k))[0]), k) for k in MACHADO))
    return float(de_ok(c1, c2)[0]), worst[0], worst[1]


# ---- image helpers --------------------------------------------------------------------------
def rgba(path):
    return np.array(Image.open(path).convert("RGBA"))


def opaque(a):
    return a[..., 3] == 255


def colours(a, mask=None):
    """(unique RGB rows, counts) of the opaque pixels (or of mask)."""
    m = opaque(a) if mask is None else mask
    if not m.any():
        return np.zeros((0, 3), np.uint8), np.zeros(0, np.int64)
    return np.unique(a[m][:, :3], axis=0, return_counts=True)


def _keys(rgb):
    rgb = np.asarray(rgb).astype(np.int64)
    return (rgb[..., 0] << 16) | (rgb[..., 1] << 8) | rgb[..., 2]


def keyset(a, mask=None):
    return set(_keys(colours(a, mask)[0]).tolist())


def _hex(k):
    return "#%06x" % int(k)


def _runs_gcd(k):
    """(gcd of the runs inside, their count, gcd of every run) of equal values along axis 1 of k. A run cut by the
    image border may be cut short, so only the inner runs measure a sprite placed at any offset; the gcd of every run
    (borders as boundaries) is the scale of an image upscaled as a whole (np.kron, phase 0)."""
    g, n, g_all = 0, 0, 0
    W = k.shape[1]
    for row in k[:, 1:] != k[:, :-1]:
        b = np.nonzero(row)[0] + 1          # index where a new run starts
        g_all = int(np.gcd.reduce(np.append(np.diff(np.concatenate(([0], b, [W]))), g_all)))
        if len(b) < 2:
            continue
        r = np.diff(b)
        n += len(r)
        g = int(np.gcd.reduce(np.append(r, g)))
    return g, n, g_all


def pixel_scale(a):
    """Whole-number upscale of an RGBA image: (scale, runs measured). Every run of one colour (transparent counts as
    one colour) along rows and along columns is a multiple of `scale`. The runs inside the image decide, when there
    are at least MIN_RUNS of them on each axis and their gcd is at most 1/SCALE_MAX_SHARE of the image's short side;
    a plain shape (a hollow focus ring: every inner run 28 px) leaves the gcd of every run, borders included, to
    decide. With too few runs the scale cannot be told and 1 is returned."""
    k = np.where(a[..., 3] > 0, _keys(a[..., :3]) | (a[..., 3].astype(np.int64) << 24), -1)
    gx, nx, ax = _runs_gcd(k)
    gy, ny, ay = _runs_gcd(k.T)
    if nx < MIN_RUNS or ny < MIN_RUNS:
        return 1, min(nx, ny)
    g = math.gcd(gx, gy)
    if g * SCALE_MAX_SHARE > min(a.shape[:2]):
        g = math.gcd(g, math.gcd(ax, ay))
    return max(1, g), min(nx, ny)


def rings(op):
    """(edge, ring2): opaque pixels touching transparency (4-neighbours; the image border counts as transparent), and
    the next layer in."""
    e1 = erode(op, 4)
    return op & ~e1, e1 & ~erode(e1, 4)


def _interior(a, outline=OUTLINE):
    """Pixels the light estimators read: inside the silhouette (its edge ring left out), not the outline colour."""
    op = opaque(a)
    inner = op & erode(op, 4) if not op.all() else op.copy()
    return inner & ~np.all(a[..., :3] == np.array(outline, np.uint8), axis=-1)


def _centroid_shift(x, y, L, w, h):
    """Light-weighted minus dark-weighted centroid of L over pixels (x, y), in units of a w x h box."""
    d = L - L.mean()
    wl, wd = np.clip(d, 0, None), np.clip(-d, 0, None)
    if wl.sum() <= 0 or wd.sum() <= 0:
        return 0.0, 0.0
    return (float(((x * wl).sum() / wl.sum() - (x * wd).sum() / wd.sum()) / w),
            float(((y * wl).sum() / wl.sum() - (y * wd).sum() / wd.sum()) / h))


def light_vector(a, outline=OUTLINE):
    """Shading direction, estimator 1: from the dark-weighted to the light-weighted centroid of OKLab L over the
    interior, in bbox units (x right, y down). (vx, vy, pixels used); (0, 0, n) under LIGHT_MIN_PX pixels."""
    op = opaque(a)
    if not op.any():
        return 0.0, 0.0, 0
    ys, xs = np.nonzero(op)
    yy, xx = np.nonzero(_interior(a, outline))
    if len(yy) < LIGHT_MIN_PX:
        return 0.0, 0.0, int(len(yy))
    vx, vy = _centroid_shift(xx, yy, oklab(a[yy, xx, :3])[:, 0], np.ptp(xs) + 1, np.ptp(ys) + 1)
    return vx, vy, int(len(yy))


def materials(lab):
    """A material id per OKLab pixel. Greys (chroma under 0.04) are one material; coloured pixels are linked when
    their colours sit within MAT_AB_GAP of each other in the chroma plane (a, b; lightness ignored), through any
    chain of such steps. A ramp changes mostly in lightness, and a hue-shifted one (warm highlight to cool shadow)
    walks the chroma plane in small steps, so it stays one material; a new material jumps. Fixed 30 degree hue
    sectors cut a wood ramp into one-shade pieces and read no shading in it at all (a test barrel lit from the left
    measured 0.00)."""
    chroma = np.hypot(lab[:, 1], lab[:, 2])
    mat = np.full(len(lab), -1)
    ch = chroma >= 0.04
    if ch.any():
        ab, inv = np.unique(np.round(lab[ch, 1:] * 1000).astype(np.int64), axis=0, return_inverse=True)
        ab = ab / 1000.0
        near = ((ab[:, None, :] - ab[None]) ** 2).sum(-1) <= MAT_AB_GAP ** 2
        comp = np.full(len(ab), -1)
        for i in range(len(ab)):   # connected components of the "near" graph (single linkage)
            if comp[i] >= 0:
                continue
            comp[i], todo = i, [i]
            while todo:
                j = todo.pop()
                for k in np.nonzero(near[j] & (comp < 0))[0]:
                    comp[k] = i
                    todo.append(k)
        mat[ch] = comp[np.asarray(inv).reshape(-1)]
    return mat


def light_vector_materials(a, outline=OUTLINE, min_px=12):
    """Shading direction, estimator 2: the same centroid shift inside each material (materials()), each in its own
    box, weighted by how much L varies in it. A light material on one side of a dark one (red cloth on a brown pole)
    moves estimator 1 although nothing is lit; inside one material only the shading is left. (vx, vy)."""
    yy, xx = np.nonzero(_interior(a, outline))
    if len(yy) < LIGHT_MIN_PX:
        return 0.0, 0.0
    lab = oklab(a[yy, xx, :3])
    mat = materials(lab)
    vx = vy = wsum = 0.0
    for m in np.unique(mat):
        sel = mat == m
        if sel.sum() < min_px:
            continue
        x, y, L = xx[sel], yy[sel], lab[sel, 0]
        cx, cy = _centroid_shift(x, y, L, np.ptp(x) + 1, np.ptp(y) + 1)
        wt = float(np.abs(L - L.mean()).sum())
        vx, vy, wsum = vx + cx * wt, vy + cy * wt, wsum + wt
    return (vx / wsum, vy / wsum) if wsum else (0.0, 0.0)


def key_colour(a, mask=None, skip_dark=True):
    """The colour that names a mark: the most-used opaque colour (in mask), the outline and near-blacks left out."""
    cols, cnt = colours(a, mask)
    if skip_dark and len(cols):
        keep = oklab(cols)[:, 0] > 0.2
        if keep.any():
            cols, cnt = cols[keep], cnt[keep]
    return tuple(int(v) for v in cols[cnt.argmax()]) if len(cnt) else None


# ---- what a game holds ----------------------------------------------------------------------
class Asset:
    """One shipped PNG from a manifest row, with the lane that made it and its place in a set: group (the character,
    animated prop, effect, widget set ...), anim and direction for frames."""

    def __init__(self, project, pack, row):
        self.pack, self.row, self.file, self.kind = pack, row, row["file"], row["kind"]
        self.path = os.path.join(project, *self.file.split("/"))
        self.lane, self.group = lane_of(row)
        self.anim = row.get("animation") or ""
        tail = self.anim.rsplit("_", 1)
        self.direction = tail[1] if len(tail) == 2 and tail[1] in DIRS else ""
        self.scale = int(row.get("scale") or 1)   # widgets, windows and font pages ship at their own scale
        self._a = None

    @property
    def a(self):
        if self._a is None:
            self._a = rgba(self.path)
        return self._a


def lane_of(row):
    """(lane, group) for a manifest row, from its kind, folder and workflow (the rows do not name their lane).
    lane None: not art a style check applies to (sheets repeat their frames; shadows, rule maps, normal maps are data;
    store art, the game icon and the boot splash are scaled up by whole numbers on purpose)."""
    f, k, wf = row["file"], row["kind"], row.get("workflow") or ""
    parts = f.split("/")
    name = os.path.splitext(parts[-1])[0]
    if k in ("sheet", "sheet_data", "sheet_json", "transition_rule", "normal_map", "shadow", "store_art", "game_icon",
             "boot_splash") or not f.endswith(".png"):
        return None, ""
    if "/characters/" in f and k == "frame":
        return "characters", parts[parts.index("characters") + 1]
    if k == "prop":
        return "props", name[4:] if name.startswith("spr_") else name
    if "/props/anim/" in f:
        return "animprops", parts[parts.index("anim") + 1]
    if "/vehicles/" in f:
        return "vehicles", parts[parts.index("vehicles") + 1]
    if k == "enemy":
        return "enemies", name
    if k == "icon":
        return "icons", re.sub(r"_\d+$", "", name)
    if k == "portrait":
        return "portraits", name
    if k == "tile_atlas":
        pair = str(row.get("layout", "")).startswith("8x4")   # lane_tiles: two wang16 blocks
        return ("connectors" if "connector" in wf else "tiles" if pair else "ground"), name
    if k == "tileset_atlas":
        return ("iso" if "/iso/" in f else "platforms"), name
    if k in ("battle_bg", "battle_bg_layer"):
        return "battle_bgs", name
    if k == "scene_backdrop":
        return "scenes", name
    if k == "scene":
        return "img2px", name
    if k == "background":
        return "platforms", name
    if k == "fx_frame":
        return ("effects" if "effect lane" in wf else "hitfx" if "hitfx" in wf else "spells"), parts[-2]
    if "/fx/status/" in f:
        return "status", parts[-2]
    if k == "weather_tile":
        return "weather", name
    if k in ("edit", "inpaint"):
        return "tools", parts[-2]
    if k in ("font_page", "ui_symbol"):
        return "fonts", name
    if k.startswith("ui_") or "/ui/balloons/" in f:
        return "ui", parts[-2]
    return "other", name


def collect(project, src):
    """(assets, manifest assumption lines, listed files missing on disk) for every PNG the game's manifests list."""
    assets, notes, missing = [], [], []
    for p in sorted(glob.glob(os.path.join(src, "dotwork", "manifest_*.json"))):
        with open(p, encoding="utf-8") as f:
            m = json.load(f)
        notes += m.get("assumptions") or []
        for row in m.get("assets", []):
            if not row["file"].endswith(".png"):
                continue
            a = Asset(project, m.get("pack", ""), row)
            if os.path.exists(a.path):
                assets.append(a)
            else:
                missing.append(a.file)
    return assets, notes, missing


class Ctx:
    """Everything the checks share: the assets, the palettes, the tile size, the source folder (rot sprites, tool
    sources), and the findings and measurements so far."""

    def __init__(self, project, src, palette, env_palette, tile_px=None):
        self.project, self.src = project, src
        self.assets, self.notes, self.missing = collect(project, src)
        self.obj = set(_keys(load_hex(palette)).tolist())
        self.env = set(_keys(load_hex(env_palette)).tolist())
        self.outline_key = int(_keys(np.array(OUTLINE)))
        # art rows only: a lit TileSet's normal map (data, lane None) gives its atlas region as a [w, h] list
        tiles = Counter(int(a.row["tile_px"]) for a in self.assets if a.lane and a.row.get("tile_px"))
        self.tile_px = tile_px or (tiles.most_common(1)[0][0] if tiles else 32)
        self.findings, self.measured = [], defaultdict(dict)
        self.checked = Counter()
        self._cache = {}

    def lane(self, *lanes):
        return [a for a in self.assets if a.lane in lanes]

    def firsts(self, *lanes):
        """One asset per group: a character's first south idle frame (else its first frame), an animated prop's or a
        vehicle's first frame, every prop and icon."""
        out = {}
        for a in self.lane(*lanes):
            k = (a.lane, a.group)
            prefer = a.lane == "characters" and a.anim == "idle_s" or a.lane == "vehicles" and a.direction == "s"
            if k not in out or (prefer and not out[k][1]):
                out[k] = (a, prefer)
        return [v[0] for v in out.values()]

    def image(self, path):
        if path not in self._cache:
            self._cache[path] = rgba(path) if os.path.exists(path) else None
        return self._cache[path]

    def find(self, check, a, detail, value=None, limit=None, file=None):
        self.findings.append({"check": check, "lane": a.lane if a else "", "group": a.group if a else "",
                              "file": file or (a.file if a else ""), "detail": detail, "value": value, "limit": limit})


def _rnd(v, n=3):
    return None if v is None else round(float(v), n)


# ---- 1. effective pixel scale ---------------------------------------------------------------------
def check_scale(ctx):
    """Dotwork art is one real pixel per pixel (widgets, windows and font pages at their manifest `scale`): an image
    whose every run of colour is a multiple of 2 or more beyond that, on both axes, was upscaled."""
    for a in ctx.assets:
        if a.lane is None:
            continue
        g, n = pixel_scale(a.a)
        ctx.checked["scale"] += 1
        ctx.measured[a.file]["scale"] = g
        if g >= 2 * a.scale and g % a.scale == 0:
            ctx.find("scale", a, f"every run of colour is a multiple of {g} px: a {g // a.scale}x upscale "
                                 f"(expected {a.scale}x){'' if a.scale == 1 else ' per the manifest'}", g, a.scale)


# ---- 2. off-palette colours ------------------------------------------------------------------------
def _rot_colours(ctx, a):
    """The colours a character frame may use: its direction sprite's (rot_<dir>.png in the character's source folder),
    else the union of the character's direction sprites; None when the game has none."""
    d = os.path.join(ctx.src, "art", "characters", a.group)
    own = ctx.image(os.path.join(d, f"rot_{a.direction}.png")) if a.direction else None
    if own is not None:
        return keyset(own), f"rot_{a.direction}.png"
    k = ("rot_union", a.group)
    if k not in ctx._cache:
        ims = [ctx.image(p) for p in sorted(glob.glob(os.path.join(d, "rot_*.png")))]
        ctx._cache[k] = set().union(*[keyset(i) for i in ims]) if ims else None
    return ctx._cache[k], "rot_*.png"


def palette_rule(ctx, a):
    """(allowed colour keys or None, colour cap or None, what the rule is, file to read instead of the asset or None)
    for one asset, per the README palette table. (None, None, None, None): the lane locks to no palette."""
    out = {ctx.outline_key}
    name = os.path.basename(a.file)
    if a.lane in ("props", "animprops", "vehicles"):
        return ctx.obj | out, None, "object palette + outline", None   # "palette": "env" entries use a subset of it
    if a.lane == "ground":
        if name.startswith("overlay_"):
            # the lane locks the overlay's texture, then draws relief, rims and roof shading on the blob tiles in code
            # (lane_ground blob_tile / structure_tile): the texture it locked sits beside the atlas
            tex = os.path.join(os.path.dirname(a.path), "spr_tile_" + name[len("overlay_"):])
            return (ctx.env, None, "environment palette (the overlay's texture)", tex) if os.path.exists(tex) else \
                (None, None, None, None)
        return ctx.env | out, None, "environment palette", None
    if a.lane == "tiles":
        return ctx.env, None, "environment palette", None
    if a.lane in ("battle_bgs", "scenes"):
        return ctx.env, None, "environment palette", None
    if a.lane == "img2px":
        return ctx.obj, None, "environment palette (object palette when the entry asks)", None
    if a.lane == "enemies":
        pal = ctx.obj if a.row.get("recolor_of") else ctx.env   # palette swaps snap to the object palette
        return pal | out, None, ("object" if a.row.get("recolor_of") else "environment") + " palette + outline", None
    if a.lane == "effects":
        return None, EFFECT_MAX, f"at most {EFFECT_MAX} colours per frame", None
    if a.lane == "hitfx":
        return None, HITFX_MAX, f"a short ramp (about 4 colours) per frame", None
    if a.lane == "tools":
        src = a.row.get("source") or "/".join(["assets_src", "art", "tools", a.group, "source.png"])
        im = ctx.image(os.path.join(ctx.project, *src.split("/")))
        if im is None:
            return None, None, None, None
        sk = keyset(im)
        return sk | ctx.obj | out, len(sk) + TOOLS_EXTRA, "the source sprite's colours + object palette", None
    if a.lane == "characters":
        allowed, what = _rot_colours(ctx, a)
        return (allowed, None, f"the colours of its direction sprite ({what})", None) if allowed else \
            (None, None, None, None)
    return None, None, None, None   # icons, portraits, UI, fonts, spells, status, weather: no palette lock


def check_palette(ctx):
    seen_tex = set()
    for a in ctx.assets:
        if a.lane is None:
            continue
        allowed, cap, what, instead = palette_rule(ctx, a)
        if allowed is None and cap is None:
            continue
        if instead:
            if instead in seen_tex:   # one texture per overlay; animated overlays list it once too
                continue
            seen_tex.add(instead)
        img = ctx.image(instead) if instead else a.a
        cols, cnt = colours(img)
        ctx.checked["palette"] += 1
        k = _keys(cols)
        rel = os.path.relpath(instead, ctx.project).replace(os.sep, "/") if instead else a.file
        if allowed is not None:
            off = np.array([x not in allowed for x in k.tolist()], bool)
            share = float(cnt[off].sum() / max(1, cnt.sum()))
            ctx.measured[rel]["off_palette"] = _rnd(share, 4)
            if off.any():
                ex = ", ".join(_hex(x) for x in k[off][np.argsort(-cnt[off])][:3])
                n = int(off.sum())
                ctx.find("palette", a, f"{n} colour{'s' if n != 1 else ''} ({share:.1%} of its pixels) outside {what}, "
                                       f"e.g. {ex}",
                         _rnd(share, 4), 0, file=rel)
        if cap is not None and len(cols) > cap:
            ctx.find("palette", a, f"{len(cols)} colours, over the cap of {cap} ({what})", len(cols), cap, file=rel)


# ---- 3. outline colour and thickness ---------------------------------------------------------------
OUTLINE_LANES = ("props", "icons", "enemies", "status", "animprops", "portraits")


def _outline_lane(a):
    """Lanes whose sprites Dotwork outlines in code (engine.finish, derive_small, lane_status) and keeps outlined; a
    portrait only in its neutral sprite-lane render (expressions are model edits of the face)."""
    return a.lane in OUTLINE_LANES and (a.lane != "portraits" or "sprite lane" in (a.row.get("workflow") or ""))


def outline_stats(a, colour):
    """(share of the silhouette edge within OUTLINE_TOL of colour, share of the second ring, dominant edge colour,
    its share) for an RGBA array. Edge pixels on the image border are left out: a bust cut by the canvas, a tile."""
    op = opaque(a)
    e1, e2 = rings(op)
    border = np.zeros_like(op)
    border[0], border[-1], border[:, 0], border[:, -1] = True, True, True, True
    e1 &= ~border
    if e1.sum() < 8:
        return None
    near = np.zeros(op.shape, bool)
    near[op] = de_ok(a[op][:, :3], np.array(colour)) <= OUTLINE_TOL
    cols, cnt = colours(a, e1)
    return (float((near & e1).sum() / e1.sum()), float((near & e2).sum() / max(1, e2.sum())),
            tuple(int(v) for v in cols[cnt.argmax()]), float(cnt.max() / cnt.sum()))


def check_outline(ctx):
    """The pack's outline colour is the most common dominant edge colour of the outlined lanes (OUTLINE when that is
    how they were made); each outlined asset must wear it on most of its silhouette, 1 px thick."""
    cands = [a for a in ctx.assets if _outline_lane(a)]
    doms = Counter()
    for a in cands:
        op = opaque(a.a)
        if op.any() and not op.all():
            cols, cnt = colours(a.a, rings(op)[0])
            if len(cnt):
                doms[tuple(int(v) for v in cols[cnt.argmax()])] += 1
    pack = doms.most_common(1)[0][0] if doms else OUTLINE
    ctx.pack_outline = pack
    for a in cands:
        st = outline_stats(a.a, pack)
        if st is None:
            continue
        share, thick, dom, dshare = st
        ctx.checked["outline"] += 1
        ctx.measured[a.file].update(outline_share=_rnd(share), outline_ring2=_rnd(thick))
        if share < OUTLINE_MIN_SHARE:
            other = dshare >= OUTLINE_MIN_SHARE and float(de_ok(dom, pack)[0]) > OUTLINE_TOL
            ctx.find("outline", a, (f"its silhouette edge is mostly {_hex(_keys(np.array(dom)))} ({dshare:.0%}), not the "
                                    f"pack outline {_hex(_keys(np.array(pack)))}") if other else
                     f"only {share:.0%} of its silhouette edge wears the pack outline {_hex(_keys(np.array(pack)))}",
                     _rnd(share), OUTLINE_MIN_SHARE)
        elif thick > OUTLINE_THICK:
            ctx.find("outline", a, f"outline about 2 px thick: {thick:.0%} of the second ring is outline colour",
                     _rnd(thick), OUTLINE_THICK)


# ---- 4. light direction --------------------------------------------------------------------------------
def _light_samples(ctx):
    """(asset, label, RGBA array) for every light reference: props, icons, an animated prop's first frame, and each
    variant tile of a base ground texture. Characters, vehicles and enemies are left out: their west views are
    mirrors of the east ones (and an enemy may be flipped), so half of them are lit from the other side by design."""
    out = []
    for a in ctx.firsts("props", "animprops", "icons"):
        out.append((a, a.file, a.a))
    seen = set()
    for a in ctx.lane("ground", "tiles"):
        if os.path.basename(a.file).startswith("base_") and a.row.get("sha256") not in seen:
            seen.add(a.row.get("sha256"))   # several maps share one texture: weigh it once
            T = ctx.tile_px
            for i in range(a.a.shape[1] // T):
                out.append((a, f"{a.file} tile {i}", a.a[:T, i * T:(i + 1) * T]))
    return out


def check_light(ctx):
    rows = []
    for a, label, arr in _light_samples(ctx):
        vx, vy, n = light_vector(arr)
        mx, my = light_vector_materials(arr)
        if n < LIGHT_MIN_PX:
            continue
        rows.append((a, label, vx, vy, mx, my))
        ctx.checked["light"] += 1
        ctx.measured[label].update(light=[_rnd(vx), _rnd(vy)], light_materials=[_rnd(mx), _rnd(my)])
    votes = [np.sign(mx) for _, _, vx, _, mx, _ in rows if abs(mx) >= LIGHT_VOTE and np.sign(vx) == np.sign(mx)]
    left, right = sum(1 for v in votes if v < 0), sum(1 for v in votes if v > 0)
    side = -1 if left >= LIGHT_CONSENSUS * len(votes) and left else 1 if right >= LIGHT_CONSENSUS * len(votes) and right \
        else 0
    ctx.pack_light = {"left": left, "right": right, "side": {-1: "left", 1: "right", 0: "no consensus"}[side]}
    if not side:
        return
    for a, label, vx, vy, mx, my in rows:
        if np.sign(vx) == np.sign(mx) == -side and min(abs(vx), abs(mx)) >= LIGHT_FLAG:
            ctx.find("light", a, f"lit from the {'right' if side < 0 else 'left'} (shading {vx:+.2f} / {mx:+.2f} of its "
                                 f"width), the pack is lit from the {ctx.pack_light['side']} ({max(left, right)} of "
                                 f"{len(votes)} assets)", _rnd(min(abs(vx), abs(mx))), LIGHT_FLAG, file=label)


# ---- 5. figure height in tiles -------------------------------------------------------------------------
def _height(a):
    ys = np.nonzero(opaque(a.a).any(1))[0]
    return int(ys.max() - ys.min() + 1) if len(ys) else 0


def _asked(ctx, a):
    """The longest side a prop was asked for, when its canvas says so: the props lane grows the canvas past its
    default (design.prop.canvas, 64) to size + 16 rounded up to 8, so a bigger canvas carries the requested size."""
    size = a.row.get("size") or a.row.get("canvas")
    if a.lane != "props" or not size or int(size[0]) <= 64:
        return None
    return int(size[0]) - 16


def check_height(ctx):
    classes = defaultdict(list)
    for a in ctx.firsts("characters", "props", "animprops", "vehicles", "enemies"):
        cls = {"characters": "character", "enemies": "boss" if a.row.get("boss") else "enemy"}.get(a.lane, "prop")
        h = _height(a)
        if h:
            classes[cls].append((a, h))
    ctx.class_height = {}
    for cls, items in classes.items():
        med = float(np.median([h for _, h in items]))
        ctx.class_height[cls] = {"median_px": med, "median_tiles": _rnd(med / ctx.tile_px, 2), "members": len(items)}
        if len(items) < HEIGHT_MIN_CLASS:
            continue
        lim = HEIGHT_CHAR if cls in ("character", "enemy", "boss") else HEIGHT_PROP
        for a, h in items:
            ctx.checked["height"] += 1
            ctx.measured[a.file]["height_tiles"] = _rnd(h / ctx.tile_px, 2)
            r = h / med
            if 1 / lim <= r <= lim:
                continue
            asked = _asked(ctx, a)
            if asked:
                bb = np.nonzero(opaque(a.a))
                longest = max(np.ptp(bb[0]), np.ptp(bb[1])) + 1
                if abs(longest - asked) <= HEIGHT_ASKED * asked:
                    continue   # the size its spec asked for (a 160 px inn): a big prop, not a wrong scale
            ctx.find("height", a, f"{h / ctx.tile_px:.2f} tiles tall, {r:.2f}x the usual {cls} "
                                  f"({med / ctx.tile_px:.2f} tiles over {len(items)})", _rnd(r, 2), lim)


# ---- 6. contrast against the ground ----------------------------------------------------------------------
GROUND_SHARE = 0.02      # a colour covering 2 % of a ground texture is one of its colours (a 32 px tile: 20 px)


def _grounds(ctx):
    """{pack: [(name, the colours of a base ground texture)]}: every colour covering GROUND_SHARE of it. A ground is
    a texture, so a figure painted in the ground's own colours melts in even where no pixel matches its average."""
    out = defaultdict(list)
    for a in ctx.lane("ground", "tiles"):
        if os.path.basename(a.file).startswith("base_"):
            cols, cnt = colours(a.a)
            out[a.pack].append((os.path.basename(a.file), cols[cnt >= GROUND_SHARE * cnt.sum()]))
    return out


def check_contrast(ctx):
    grounds = _grounds(ctx)
    every = [g for gs in grounds.values() for g in gs]
    if not every:
        return
    for a in ctx.firsts("characters", "props", "animprops", "vehicles"):
        op = opaque(a.a)
        if not op.any():
            continue
        e1, _ = rings(op)
        body = op & ~e1
        ctx.checked["contrast"] += 1
        worst = None
        for gname, gcols in (grounds.get(a.pack) if a.lane != "characters" and grounds.get(a.pack) else every):
            de = np.zeros(op.shape)
            de[op] = np.sqrt(((oklab(a.a[op][:, :3])[:, None, :] - oklab(gcols)[None]) ** 2).sum(-1)).min(1)
            edge = float((de[e1] < CONTRAST_DE).mean())
            inner = float((de[body] < CONTRAST_DE).mean()) if body.any() else edge
            if worst is None or min(edge, inner) > min(worst[1], worst[2]):
                worst = (gname, edge, inner)
        ctx.measured[a.file]["ground_melt"] = [worst[0], _rnd(worst[1]), _rnd(worst[2])]
        if worst[1] >= CONTRAST_SHARE and worst[2] >= CONTRAST_SHARE:
            ctx.find("contrast", a, f"melts into {worst[0]}: {worst[1]:.0%} of its edge and {worst[2]:.0%} of its body "
                                    f"within {CONTRAST_DE} (OKLab) of the ground's colours", _rnd(min(worst[1:])),
                     CONTRAST_SHARE)


# ---- 7. colour-blind separation ---------------------------------------------------------------------------
def _variant_groups(ctx):
    """{set name: {member: (RGBA, file)}}: palette swaps and their base (manifest assumption "X: palette variant of Y"
    for characters, their south direction sprites; recolor_of for enemies), compared where the swap changed pixels."""
    groups = defaultdict(dict)
    for line in ctx.notes:
        m = re.match(r"(\w+): palette variant of (\w+)", line)
        if m:
            for who in m.groups():
                p = os.path.join(ctx.src, "art", "characters", who, "rot_s.png")
                if os.path.exists(p):
                    groups[f"characters {m.group(2)}"][who] = (ctx.image(p), os.path.relpath(p, ctx.project).replace(
                        os.sep, "/"))
    by_name = {a.group: a for a in ctx.lane("enemies")}
    for a in ctx.lane("enemies"):
        base = by_name.get(f"spr_enemy_{a.row.get('recolor_of')}")
        if base is not None:
            groups[f"enemies {base.group[len('spr_enemy_'):]}"][base.group[len("spr_enemy_"):]] = (base.a, base.file)
            groups[f"enemies {base.group[len('spr_enemy_'):]}"][a.group[len("spr_enemy_"):]] = (a.a, a.file)
    return groups


def colour_sets(ctx):
    """{set name: {member: (key colour, file)}} of colours that must stay apart: gauge fills of one widget set,
    button states of one set (focus is a ring drawn over a state, so it is left out), status loops, status icons
    (one size), and palette-swap variants."""
    sets = defaultdict(dict)
    for a in ctx.lane("ui"):
        if a.kind == "ui_gauge" and a.row.get("part") == "fill":
            sets[f"gauge fills {a.group}"][a.row.get("gauge")] = (key_colour(a.a, skip_dark=False), a.file)
        elif a.kind == "ui_button" and a.row.get("state") not in (None, "focus"):
            h, w = a.a.shape[:2]
            centre = np.zeros(a.a.shape[:2], bool)
            centre[h // 3:h - h // 3, w // 3:w - w // 3] = True
            sets[f"button states {a.group}"][a.row["state"]] = (key_colour(a.a, centre & opaque(a.a), False), a.file)
    status = defaultdict(list)
    for a in ctx.lane("status"):
        status[a.group].append(a)
    for g, frames in status.items():
        stack = np.concatenate([f.a for f in frames], axis=1)
        sets["status loops"][g] = (key_colour(stack), frames[0].file)
    icons = [a for a in ctx.lane("icons") if a.group.startswith("ui_icon_status_")]
    if icons:
        big = max(a.a.shape[0] for a in icons)
        for a in icons:
            if a.a.shape[0] == big:
                sets["status icons"][a.group[len("ui_icon_status_"):]] = (key_colour(a.a), a.file)
    for gname, members in _variant_groups(ctx).items():
        ims = [im for im, _ in members.values()]
        if len({i.shape for i in ims}) != 1:
            continue
        diff = np.zeros(ims[0].shape[:2], bool)
        for im in ims[1:]:
            diff |= np.any(im != ims[0], axis=-1)
        diff &= opaque(ims[0])
        if diff.sum() < 8:
            continue
        for who, (im, f) in members.items():
            sets[f"palette swaps {gname}"][who] = (key_colour(im, diff), f)
    return sets


def check_colourblind(ctx):
    ctx.cvd = []
    for sname, members in colour_sets(ctx).items():
        items = [(k, v) for k, v in sorted(members.items()) if v[0] is not None]
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (n1, (c1, f1)), (n2, (c2, f2)) = items[i], items[j]
                normal, sim, kind = cvd_pair(c1, c2)
                ctx.checked["colourblind"] += 1
                ctx.cvd.append({"set": sname, "pair": [n1, n2], "colours": [_hex(_keys(np.array(c1))),
                                _hex(_keys(np.array(c2)))], "normal": _rnd(normal), "worst": _rnd(sim), "as": kind})
                if normal >= CVD_NORMAL and sim < CVD_SIM:
                    ctx.findings.append({"check": "colourblind", "lane": "", "group": sname, "file": f1,
                                         "detail": f"{n1} {_hex(_keys(np.array(c1)))} and {n2} "
                                                   f"{_hex(_keys(np.array(c2)))} are {normal:.2f} apart, but {sim:.2f} "
                                                   f"under {kind} (Machado 2009, OKLab)",
                                         "value": _rnd(sim), "limit": CVD_SIM, "pair_file": f2})


# ---- lineup -----------------------------------------------------------------------------------------------
def _font():
    try:
        from PIL import ImageFont
        return ImageFont.load_default()
    except Exception:  # noqa: BLE001
        return None


def lineup(ctx, out, zoom=2, max_w=900):
    """Every character and prop at game scale (1x, then the whole sheet zoomed by `zoom`) standing on a strip of a
    base ground texture, its name under it; rows wrap at max_w game pixels."""
    figs = sorted(ctx.firsts("characters", "props", "animprops", "vehicles"),
                  key=lambda a: (a.lane != "characters", a.lane, a.group))
    T = ctx.tile_px
    base = next((a for a in ctx.lane("ground") if os.path.basename(a.file).startswith("base_")), None)
    tile = base.a[:T, :T] if base is not None else np.full((T, T, 4), (96, 120, 80, 255), np.uint8)
    crops = []
    for a in figs:
        im = Image.fromarray(a.a)
        bb = im.getbbox()
        if bb:
            crops.append((a, im.crop(bb)))
    rows, cur, x = [], [], 0
    for a, im in crops:
        w = max(im.width, 40) + 8
        if cur and x + w > max_w:
            rows.append(cur)
            cur, x = [], 0
        cur.append((a, im, x, w))
        x += w
    if cur:
        rows.append(cur)
    label_h = 12
    heights = [max(im.height for _, im, _, _ in r) + T + label_h + 6 for r in rows]
    W = max_w
    sheet = Image.new("RGBA", (W, sum(heights) + 4), (40, 40, 48, 255))
    y = 0
    for r, h in zip(rows, heights):
        ground_y = y + h - label_h - T - 4           # a row of ground tiles; the feet stand halfway into it
        strip = Image.fromarray(np.ascontiguousarray(np.tile(tile, (1, W // T + 1, 1))[:, :W]))
        sheet.alpha_composite(strip, (0, ground_y))
        for a, im, x0, w in r:
            sheet.alpha_composite(im, (x0 + (w - im.width) // 2, ground_y - im.height + T // 2))
        y += h
    big = sheet.resize((sheet.width * zoom, sheet.height * zoom), Image.NEAREST)
    d = ImageDraw.Draw(big)
    font = _font()
    y = 0
    for r, h in zip(rows, heights):
        for a, im, x0, w in r:
            d.text(((x0 + 2) * zoom, (y + h - label_h - 2) * zoom), a.group[:14], fill=(240, 220, 160), font=font)
        y += h
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    big.save(out)
    return len(crops)


# ---- run --------------------------------------------------------------------------------------------------
CHECK_FN = {"scale": check_scale, "palette": check_palette, "outline": check_outline, "light": check_light,
            "height": check_height, "contrast": check_contrast, "colourblind": check_colourblind}


def analyse(project, src, palette, env_palette, tile_px=None):
    """A Ctx with every check run (the tests call this directly)."""
    ctx = Ctx(project, src, palette, env_palette, tile_px)
    for name in CHECKS:
        CHECK_FN[name](ctx)
    return ctx


def report(ctx, seconds):
    """The summary lines: one per check, then the findings, grouped (a clip's frames make one line)."""
    lanes = Counter(a.lane for a in ctx.assets if a.lane)
    lines = [f"[qa] {len(ctx.assets)} PNGs from the manifests ({len([a for a in ctx.assets if a.lane])} checked; "
             f"{', '.join(f'{k} {v}' for k, v in sorted(lanes.items()))}); tile {ctx.tile_px} px; {seconds:.1f} s"]
    if ctx.missing:
        lines.append(f"[warn] {len(ctx.missing)} manifest files missing on disk, e.g. {ctx.missing[0]}")
    per = Counter(f["check"] for f in ctx.findings)
    extra = {"outline": f"pack outline {_hex(_keys(np.array(getattr(ctx, 'pack_outline', OUTLINE))))}",
             "light": "pack light: {left} left / {right} right -> {side}".format(**getattr(ctx, "pack_light", {
                 "left": 0, "right": 0, "side": "none"})),
             "height": ", ".join(f"{k} {v['median_tiles']} tiles ({v['members']})"
                                 for k, v in sorted(getattr(ctx, "class_height", {}).items())) or "no figures"}
    for c in CHECKS:
        lines.append(f"  {c:<12} {per.get(c, 0):>3} findings over {ctx.checked.get(c, 0):>4} checked"
                     + (f"   ({extra[c]})" if c in extra else ""))
    groups = defaultdict(list)
    for f in ctx.findings:
        groups[(f["check"], f["lane"], f["group"], f["detail"] if f["check"] == "colourblind" else "")].append(f)
    for (check, lane, group, _), fs in sorted(groups.items()):
        # the worst file of a group stands for it: the lowest value for shares that must stay high, else the highest
        low = check in ("outline", "colourblind") and "thick" not in fs[0]["detail"]
        head = sorted(fs, key=lambda f: (f["value"] if low else -(f["value"] or 0)) if f["value"] is not None else 0)[0]
        many = f" ({len(fs)} files, the worst shown)" if len(fs) > 1 else ""
        where = " ".join(x for x in (lane, group) if x)
        lines.append(f"[FIND] {check} {where}{many}: {head['detail']}  -> {head['file']}")
    return lines


def run(settings, a):
    """dotwork.py qa pack: exit 0 clean, 1 findings (2 comes from a ToolError raised before)."""
    import fcore as core
    if a.what != "pack":
        raise core.ToolError(f"qa {a.what!r}: only `qa pack` exists")
    if not glob.glob(os.path.join(settings.src, "dotwork", "manifest_*.json")):
        raise core.ToolError(f"no Dotwork manifests in {os.path.join(settings.src, 'dotwork')}: build a pack first "
                             "(dotwork.py pack --spec ...)")
    t0 = time.time()
    fx = settings.conf["fixed"]
    ctx = analyse(settings.project, settings.src, fx["palette"], fx["env_palette"])
    seconds = time.time() - t0
    for line in report(ctx, seconds):
        print(line)
    if a.lineup:
        n = lineup(ctx, a.lineup)
        print(f"[ OK ] lineup of {n} characters and props: {a.lineup}")
    if a.json:
        data = {"game": settings.project, "seconds": round(seconds, 2), "tile_px": ctx.tile_px,
                "thresholds": {k: v for k, v in globals().items() if k.isupper() and isinstance(v, (int, float))},
                "pack_outline": _hex(_keys(np.array(getattr(ctx, "pack_outline", OUTLINE)))),
                "pack_light": getattr(ctx, "pack_light", None), "class_height": getattr(ctx, "class_height", None),
                "checked": dict(ctx.checked), "findings": ctx.findings, "colour_pairs": getattr(ctx, "cvd", []),
                "measured": ctx.measured, "missing": ctx.missing}
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        with open(a.json, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        print(f"[ OK ] report: {a.json}")
    if ctx.findings:
        print(f"[FAIL] {len(ctx.findings)} findings: look at each file (README: qa pack)")
        return 1
    print("[ OK ] the pack is consistent")
    return 0
