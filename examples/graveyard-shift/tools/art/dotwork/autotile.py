#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# autotile.py
# Purpose : corner-based (wang16) autotile pixels for the two-terrain pair lane (lane_tiles): smooth corner coverage
#           with a border-safe wobble, a dark rim on the upper terrain, a soft shadow on the lower one, and a demo map.
# Usage   : imported by lane_tiles (not run directly)
# Notes   : Coverage wobble is zero on tile borders, so any two neighbouring tiles agree on their shared edge.
#           New maps should prefer the layered blob ground (lane_ground); this keeps the pair lane working.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import random

import numpy as np
from PIL import Image


def luma(c):
    c = np.asarray(c, np.float32)
    return 0.299 * c[..., 0] + 0.587 * c[..., 1] + 0.114 * c[..., 2]


def ramp(tex):
    """Darkest / lightest frequent colors of a texture: used for rim and highlight so they stay on-palette."""
    cols, cnt = np.unique(tex.reshape(-1, 3), axis=0, return_counts=True)
    order = np.argsort(luma(cols))
    common = [c for c in cols[order] if cnt[(cols == c).all(1)][0] >= 2] or list(cols[order])
    return np.array(common[0]), np.array(common[-1]), np.array(common[len(common) // 2])


def coverage(bits, T, wobble, seed):
    nw, ne, sw, se = (bits >> 0) & 1, (bits >> 1) & 1, (bits >> 2) & 1, (bits >> 3) & 1
    v = (np.arange(T) + 0.5) / T
    yy, xx = np.meshgrid(v, v, indexing="ij")
    f = nw * (1 - xx) * (1 - yy) + ne * xx * (1 - yy) + sw * (1 - xx) * yy + se * xx * yy
    f = f * f * (3 - 2 * f)  # smoothstep: rounder corners, flatter straight edges
    # wobble: zero on all tile borders (sin envelopes) so any two neighbouring tiles agree on the boundary
    rng = np.random.default_rng(seed)
    ph1, ph2 = rng.uniform(0, 2 * np.pi, 2)
    env = np.sin(np.pi * xx) * np.sin(np.pi * yy)
    w = env * (np.sin(2 * np.pi * xx * 2 + ph1) + np.sin(2 * np.pi * yy * 2 + ph2)) * 0.5
    return f + w * (wobble / T)


def build_tile(bits, A, B, T, wobble, rim, shadow, seed, colors=None):
    """A/B are the T x T texture patches this tile shows. colors = (rim, highlight, shadow) RGB, from the
    FULL textures so every variant uses the same edge colors."""
    if bits == 15:
        return A.copy()
    if bits == 0:
        return B.copy()
    mask = coverage(bits, T, wobble, seed) >= 0.5
    out = np.where(mask[..., None], A, B).copy()
    a_dark, a_light, b_dark = colors if colors is not None else (ramp(A)[0], ramp(A)[1], ramp(B)[0])
    # rim: A pixels within `rim` px of the boundary (4-neighbour distance)
    edge = np.zeros_like(mask)
    m = mask.copy()
    for _ in range(rim):
        inner = m.copy()
        inner[1:, :] &= m[:-1, :]
        inner[:-1, :] &= m[1:, :]
        inner[:, 1:] &= m[:, :-1]
        inner[:, :-1] &= m[:, 1:]
        edge |= m & ~inner
        m = inner
    out[edge] = a_dark
    # highlight: one A pixel just inside the rim on the top-left facing side
    hl = m & ~np.roll(m, 1, 0) | m & ~np.roll(m, 1, 1)
    hl &= ~edge
    out[hl & np.roll(edge, 1, 0)] = a_light
    # shadow: B pixels directly below / right of A get darkened (light from the top-left)
    sh = np.zeros_like(mask)
    for k in range(1, shadow + 1):
        sh |= np.roll(mask, k, 0) & ~mask
    sh[:shadow, :] &= False  # don't wrap the shadow from the tile above
    out[sh] = (out[sh].astype(np.float32) * 0.5 + b_dark * 0.5).astype(np.uint8)
    return out


def edge_colors(Afull, Bfull, rim_dark=0.55, shadow_dark=0.45):
    """Explicit rim/highlight/shadow: darkened/lightened texture medians (v1 used the texture's own darkest
    color, which was too close to the base and barely showed)."""
    am = np.median(Afull.reshape(-1, 3), axis=0)
    bm = np.median(Bfull.reshape(-1, 3), axis=0)
    rim_c = (am * rim_dark).astype(np.uint8)
    hl_c = np.clip(am * 1.25 + 12, 0, 255).astype(np.uint8)
    sh_c = (bm * shadow_dark).astype(np.uint8)
    return rim_c, hl_c, sh_c


def build_variants(Afull, Bfull, T, wobble, rim, shadow, seed):
    """Big seamless textures (e.g. 128) -> tiles[(ox, oy)][bits]: each T-px tile shows the texture patch at its
    map position modulo the texture size, so detail survives and the texture stays continuous across tiles."""
    n = Afull.shape[0] // T
    cols = edge_colors(Afull, Bfull)
    out = {}
    for oy in range(n):
        for ox in range(n):
            sl = (slice(oy * T, (oy + 1) * T), slice(ox * T, (ox + 1) * T))
            out[(ox, oy)] = [build_tile(b, Afull[sl], Bfull[sl], T, wobble, rim, shadow, seed + b, cols)
                             for b in range(16)]
    return out, n


def sheet(tiles, T):
    s = np.zeros((4 * T, 4 * T, 3), np.uint8)
    for i, t in enumerate(tiles):
        s[(i // 4) * T:(i // 4 + 1) * T, (i % 4) * T:(i % 4 + 1) * T] = t
    return s


def demo(tiles, T, w, h, seed, variants=None, n=1):
    """Random-but-smooth terrain on the corner grid, rendered with the 16 tiles: proves edges join.
    With variants, tile (x, y) uses offset (x % n, y % n) so a big texture stays continuous."""
    rng = random.Random(seed)
    cw, ch = w + 1, h + 1
    # blobby field: a few random discs of terrain A on B
    corner = np.zeros((ch, cw), np.uint8)
    yy, xx = np.mgrid[0:ch, 0:cw]
    for _ in range(max(3, (w * h) // 40)):
        cx, cy, r = rng.uniform(0, cw), rng.uniform(0, ch), rng.uniform(1.5, 4.5)
        corner[(xx - cx) ** 2 + ((yy - cy) * 1.1) ** 2 < r * r] = 1
    img = np.zeros((h * T, w * T, 3), np.uint8)
    for y in range(h):
        for x in range(w):
            b = corner[y, x] | corner[y, x + 1] << 1 | corner[y + 1, x] << 2 | corner[y + 1, x + 1] << 3
            src = variants[(x % n, y % n)] if variants else tiles
            img[y * T:(y + 1) * T, x * T:(x + 1) * T] = src[b]
    return img
