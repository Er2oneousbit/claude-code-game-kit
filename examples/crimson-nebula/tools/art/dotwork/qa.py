#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# qa.py
# Purpose : automatic checks and clean-ups for generated frames: head-signature turn detection, ping-pong trim,
#           ground shadow and blue-puddle removal, palette lock, specks, height drift, trapped white background.
# Usage   : imported by the lanes
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import numpy as np
from PIL import Image

import engine

N4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])


def _rgba(img):
    return np.array(img.convert("RGBA"))


def facing(img, head_frac=0.35):
    """Skin (warm, r>g>b) in the head rows: offset of its centroid vs the head's centroid. Back views have
    little skin. Returns ('left'|'right'|'front'|'back', skin_count)."""
    a = _rgba(img)
    op = a[..., 3] > 127
    ys, xs = np.nonzero(op)
    if not len(ys):
        return "none", 0
    head = ys.min() + (ys.max() - ys.min()) * head_frac
    r, g, b = (a[..., k].astype(int) for k in range(3))
    skin = op & (r > 150) & (r > g + 15) & (g > b) & (np.arange(a.shape[0])[:, None] < head)
    sy, sx = np.nonzero(skin)
    if len(sx) < 6:
        return "back", int(len(sx))
    off = sx.mean() - xs[ys < head].mean()
    if abs(off) < 1.5:
        return "front", int(len(sx))
    return ("right" if off > 0 else "left"), int(len(sx))


OPPOSITE = {"s": "n", "n": "s", "e": "w", "w": "e"}


def _sig(img, frac=0.3, size=(12, 8)):
    """Head signature: the top `frac` of the figure, cropped around the head's median column (so swinging arms
    and legs don't dominate), in premultiplied color. Face vs back-of-head is a big color change; a whole-body
    grayscale signature (v1) was swamped by pose changes and missed a real turn-around."""
    im = img.convert("RGBA")
    bb = im.getbbox()
    if not bb:
        return np.zeros((size[1], size[0], 3), np.float32)
    h = max(4, int((bb[3] - bb[1]) * frac))
    a = np.array(im)[bb[1]:bb[1] + h, bb[0]:bb[2]]
    ys, xs = np.nonzero(a[..., 3] > 127)
    cx = int(np.median(xs)) if len(xs) else a.shape[1] // 2
    w = max(8, h)
    c = Image.fromarray(a).crop((max(0, cx - w // 2), 0, cx + w // 2, h)).resize(size, Image.BOX)
    x = np.array(c).astype(np.float32) / 255
    return x[..., :3] * x[..., 3:4]


def turned_any(frames, own, refs, margin=0.9):
    """v3: first frame index (two in a row) whose head matches ANY other direction's sprite better than its own.
    v2 compared only against the opposite direction and missed side-view punches that turned to face the camera.
    refs: {direction: PIL image}; own: this clip's direction."""
    sigs = {d: _sig(im) for d, im in refs.items()}
    flags = []
    for f in frames:
        sf = _sig(f)
        dist = {d: np.abs(sf - s).mean() for d, s in sigs.items()}
        best_other = min(v for d, v in dist.items() if d != own)
        flags.append(best_other < dist[own] * margin)
    for i in range(len(flags) - 1):
        if flags[i] and flags[i + 1]:
            return i
    return None


def turned_around(frames, ref_same, ref_opposite, margin=0.9):
    """v2 (character-agnostic): first frame index that looks more like the OPPOSITE direction's sprite than its
    own direction's sprite (Wan turns characters around at the end of attacks). v1 used skin color to tell
    facing and failed on characters with skin-colored hair or brass. None if the clip is consistent."""
    s_same, s_opp = _sig(ref_same), _sig(ref_opposite)
    flags = []
    for f in frames:
        sf = _sig(f)
        flags.append(np.abs(sf - s_opp).mean() < np.abs(sf - s_same).mean() * margin)
    # a real turn persists: require two flagged frames in a row (a single head bob flagged walk_S frame 1)
    for i in range(len(flags) - 1):
        if flags[i] and flags[i + 1]:
            return i
    return None


def ping_pong_trim(frames, bad):
    """Keep frames[:bad], then replay them backward so the clip returns to its rest pose (kick_N fix)."""
    keep = frames[:max(2, bad)]
    return keep + keep[-2:0:-1]


def hard_alpha(img):
    a = _rgba(img)[..., 3]
    n = int(((a > 0) & (a < 255)).sum())
    return n == 0, f"{n} semi-transparent px"


def on_palette(img, pal_set):
    a = _rgba(img)
    cols = {tuple(c) for c in a[a[..., 3] == 255][:, :3].tolist()}
    off = cols - pal_set
    return not off, f"{len(off)} off-palette colors"


def height_ok(frames, ref_h, tol=0.15):
    hs = [f.getbbox()[3] - f.getbbox()[1] for f in frames if f.getbbox()]
    lo, hi = min(hs), max(hs)
    ok = lo >= ref_h * (1 - tol) and hi <= ref_h * (1 + tol)
    return ok, f"height {lo}-{hi} vs ref {ref_h}"


def deshadow(img, band=8, lookup=3, dark=0.7):
    """v3: 'support' comes only from the `lookup` rows just above the band (the shins/boots). v2 looked 8 rows up,
    where a wide coat counted as support, so the ground ellipse under the body survived."""
    a = _rgba(img)
    op = a[..., 3] == 255
    rows = np.nonzero(op.any(1))[0]
    if not len(rows):
        return img, 0
    bottom = rows.max()
    y0 = max(0, bottom - band + 1)
    above = op[max(0, y0 - lookup):y0].any(0)
    support = above | np.roll(above, 1) | np.roll(above, -1)
    rgb = a[..., :3].astype(np.float32) / 255
    luma = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    kill = np.zeros_like(op)
    kill[y0:bottom + 1] = op[y0:bottom + 1] & ~support[None, :] & (luma[y0:bottom + 1] < dark)
    a[kill, 3] = 0
    return Image.fromarray(a), int(kill.sum())


def deblue(img, band=6):
    a = _rgba(img)
    op = a[..., 3] == 255
    rows = np.nonzero(op.any(1))[0]
    if not len(rows):
        return img, 0
    y0 = max(0, rows.max() - band + 1)
    r, g, b = (a[..., k].astype(int) for k in range(3))
    kill = op & (b > r + 18) & (b >= g)
    kill[:y0] = False
    a[kill, 3] = 0
    return Image.fromarray(a), int(kill.sum())


def palette_of(img):
    a = _rgba(img)
    return np.unique(a[a[..., 3] == 255][:, :3], axis=0)


def deshadow_offpalette(img, pal, band=12, max_sat=0.35, max_luma=0.6, dist=30):
    """For clips rendered WITHOUT SpriteKiln's palette lock: in the bottom `band` rows, remove pixels that are
    neutral/dark (shadow-like) AND far from every color of the character's own palette (RGB distance > dist)."""
    a = _rgba(img)
    op = a[..., 3] == 255
    rows = np.nonzero(op.any(1))[0]
    if not len(rows):
        return img, 0
    b = rows.max()
    rgb = a[..., :3].astype(np.float32)
    mx, mn = rgb.max(2), rgb.min(2)
    sat = (mx - mn) / np.maximum(mx, 1)
    luma = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]) / 255
    band_m = np.zeros_like(op)
    band_m[max(0, b - band + 1):b + 1] = True
    cand = op & band_m & (sat < max_sat) & (luma < max_luma)
    ys, xs = np.nonzero(cand)
    kill = np.zeros_like(op)
    if len(ys):
        px = rgb[ys, xs]
        d = np.sqrt(((px[:, None, :] - pal[None].astype(np.float32)) ** 2).sum(-1)).min(1)
        far = d > dist
        kill[ys[far], xs[far]] = True
    a[kill, 3] = 0
    return Image.fromarray(a), int(kill.sum())


def deshadow_blob(img, band=12):
    """For clips rendered WITHOUT SpriteKiln's palette lock, where Wan's ground shadow is still a neutral grey:
    find a neutral mid-dark blob in the bottom rows that touches the bottom, is wide (>= 35% of the figure) and
    flat (w > 1.5 h); remove it and grow into touching shadow-like pixels (never into saturated boots).
    Removes most of the shadow; a thin strip right under the boots can remain (flag for review)."""
    a = _rgba(img)
    op = a[..., 3] == 255
    ys, xs = np.nonzero(op)
    if not len(ys):
        return img, 0
    b, fw = ys.max(), xs.max() - xs.min() + 1
    rgb = a[..., :3].astype(np.float32) / 255
    mx, mn = rgb.max(2), rgb.min(2)
    sat = (mx - mn) / np.maximum(mx, 1e-6)
    luma = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    inband = np.zeros_like(op)
    inband[max(0, b - band + 1):] = True
    core = op & inband & (sat < 0.2) & (luma > 0.1) & (luma < 0.62)
    lab, n = engine.label(core, 8)
    kill = np.zeros_like(op)
    for i in range(1, n + 1):
        m = lab == i
        yy, xx = np.nonzero(m)
        w, h = xx.max() - xx.min() + 1, yy.max() - yy.min() + 1
        if yy.max() >= b - 1 and w >= 0.35 * fw and w > 1.5 * h:
            kill |= m
    if kill.any():
        grow = op & inband & (sat < 0.32) & (luma < 0.62)
        for _ in range(6):
            nk = engine.dilate(kill, 8) & grow
            if not (nk & ~kill).any():
                break
            kill |= nk
    a[kill, 3] = 0
    return Image.fromarray(a), int(kill.sum())


def lock_palette(img, pal):
    """Nearest-color lock to the character's palette (RGB; the palette is small and already curated)."""
    a = _rgba(img)
    op = a[..., 3] == 255
    px = a[op][:, :3].astype(np.float32)
    if len(px):
        idx = ((px[:, None, :] - pal[None].astype(np.float32)) ** 2).sum(-1).argmin(1)
        a[op, :3] = pal[idx]
    return Image.fromarray(a)


def drop_islands(img, min_px=6):
    a = _rgba(img)
    op = a[..., 3] == 255
    lab, n = engine.label(op, 8)
    if n > 1:
        sizes = np.bincount(lab.ravel())
        a[np.isin(lab, np.where(sizes < min_px)[0]) & op, 3] = 0
    return Image.fromarray(a)




def white_pockets(im, min_area=10, max_frac=0.15, force=None):
    """Background trapped inside a sprite (between legs, inside a curled tail): the white-background flood fill
    only reaches from the borders. Removes enclosed, flat, near-white components of >= min_area px.
    Guard: if the pockets would cover more than max_frac of the sprite, the subject is probably white (a frost bear
    had 23% flagged, 2026-10-29) and nothing is removed. force=True removes anyway, force=False never removes.
    Returns (image, removed_px, note)."""
    a = np.array(im.convert("RGBA"))
    rgb = a[..., :3].astype(int)
    op = a[..., 3] > 0
    white = op & (rgb.min(2) >= 236) & ((rgb.max(2) - rgb.min(2)) <= 10)
    lab, n = engine.label(white, 4)
    kill = np.zeros_like(white)
    for i in range(1, n + 1):
        comp = lab == i
        if comp.sum() >= min_area and len(np.unique(rgb[comp].reshape(-1, 3), axis=0)) <= 2:
            kill |= comp
    k = int(kill.sum())
    if force is False or k == 0:
        return im, 0, None
    if force is not True and k > max_frac * max(1, int(op.sum())):
        return im, 0, f"white pockets skipped: {k} px ({k / op.sum():.0%}) looks like a white subject"
    a[kill] = 0
    return Image.fromarray(a), k, f"white background pockets removed: {k} px"
