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


def face_side(img, head_frac=0.4, min_px=4, margin=0.08):
    """Which way a side or quarter view faces, from where the face sits across the head: ('right' | 'left' | 'front',
    offset as a share of the head's width, skin pixels), or (None, 0, n) when no face shows (back views, helmets,
    machines). Stricter than facing(): skin must be light and warm (r - b 35-120), because a bow's tan tip and a
    white fur hood both passed facing()'s test, and the head is the run of columns around the widest one, so a
    bow or a staff (a few pixels per column) does not drag the head's middle. Measured 2026-10-30 on 6 rotations
    (14 side and front-quarter views): every visible face judged right, offsets 0.14-0.39."""
    a = _rgba(img).astype(int)
    op = a[..., 3] > 127
    ys, xs = np.nonzero(op)
    if not len(ys):
        return None, 0.0, 0
    top = ys.min()
    rows = slice(top, top + max(4, int((ys.max() - top + 1) * head_frac)))
    head = op[rows]
    prof = head.sum(0)
    wide = prof >= 0.35 * prof.max()
    x0 = x1 = int(np.argmax(prof))
    while x0 > 0 and wide[x0 - 1]:
        x0 -= 1
    while x1 < len(wide) - 1 and wide[x1 + 1]:
        x1 += 1
    r, g, b = (a[rows][..., k] for k in range(3))
    skin = head & (r >= 200) & (g >= 130) & (b >= 100) & (r > g) & (g > b) & (r - b >= 35) & (r - b <= 120)
    skin[:, :x0] = False
    skin[:, x1 + 1:] = False
    sx = np.nonzero(skin)[1]
    if len(sx) < min_px:
        return None, 0.0, int(len(sx))
    off = float((sx.mean() - (x0 + x1) / 2) / (x1 - x0 + 1))
    return ("right" if off > margin else "left" if off < -margin else "front"), round(off, 3), int(len(sx))


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


def _near_white(a):
    rgb = a[..., :3].astype(int)
    return (a[..., 3] == 255) & (rgb.min(2) >= 228) & ((rgb.max(2) - rgb.min(2)) <= 12)


def edge_white(a):
    """Near-white pixels connected (through near-white) to transparency, in an RGBA array."""
    nw = _near_white(a)
    lab, n = engine.label(nw, 4)
    touch = np.unique(lab[engine.dilate(a[..., 3] == 0, 4) & nw])
    return np.isin(lab, touch[touch > 0])


def matte_seed(raw):
    """In an unlocked clip frame, the edge-white pieces that are the generator's flat background: one colour covers
    >= 90 % of the piece and it is near pure white (min channel >= 250). Measured 2026-10-30: the duelist's matte is
    (254, 254, 254) at 95-100 %; the baker's white sleeve edge is (251, 251, 252) with 3 shades at 54-75 %."""
    a = np.array(raw.convert("RGBA"))
    lab, n = engine.label(edge_white(a), 4)
    seed = np.zeros(a.shape[:2], bool)
    for i in range(1, n + 1):
        c = lab == i
        v, k = np.unique(a[c][:, :3], axis=0, return_counts=True)
        if k.max() >= 0.9 * k.sum() and int(v[k.argmax()].min()) >= 250:
            seed |= c
    return seed


def dematte(frames, ref, tol_px=6, raw=None):
    """Light background matte left in clip frames (2026-10-30 art audit D1, issue #22): the keyer removed the
    generator's exact white, but a (240, 240, 241) shade enclosed by limbs survived, and the shadow pass later opened
    it to the outside. Removes it, plus its light-grey rim, in every frame. raw: the clip's unlocked frames, where
    the matte is still the generator's flat white (matte_seed), so a white shirt at the silhouette edge is told apart
    (after the palette lock both are the sprite's own white); without raw, every edge white is a seed. Nothing is
    removed when the direction's own sprite has more than tol_px of white at its edge (a white coat drawn without an
    outline). Returns (frames, removed_px, note)."""
    ra = np.array(ref.convert("RGBA"))
    ref_px = int(edge_white(ra).sum())
    if ref_px > tol_px:
        return frames, 0, f"matte pass skipped: {ref_px} px of white at the sprite's own edge look intentional"
    op = ra[..., 3] == 255
    share = float((op & (ra[..., :3].astype(int).min(2) >= 235)).sum() / max(1, op.sum()))
    if share >= 0.05:   # a white-clothed design (baker 9-14 %, others 0-3 %): its flat white apron looked like matte
        return frames, 0, f"matte pass skipped: the sprite is {share:.0%} white, so matte and clothing look alike"
    out, total = [], 0
    for k, f in enumerate(frames):
        a = np.array(f.convert("RGBA"))
        m = (matte_seed(raw[k]) & (a[..., 3] == 255)) if raw is not None else edge_white(a)
        if m.any():
            rgb = a[..., :3].astype(int)
            rim = (a[..., 3] == 255) & (rgb.min(2) >= 170) & ((rgb.max(2) - rgb.min(2)) <= 16)
            for _ in range(2):   # the matte's light-grey rim, where it faded into the figure
                m |= rim & engine.dilate(m, 4)
            a[m, 3] = 0
            a = engine.drop_islands(a, 3)
        total += int(m.sum())
        out.append(Image.fromarray(a))
    return out, total, (f"light background matte removed: {total} px" if total else None)


def shadow_colours(frames):
    """The colours deshadow_blob removes anywhere in a clip, kept only when shadow-like (low saturation, blue >= red,
    mid luminance): the per-frame pass also takes some dark boot pixels, and a boot colour here would strip boots."""
    cols = []
    for f in frames:
        a = np.array(f.convert("RGBA"))
        g, n = deshadow_blob(f)
        if n:
            cols.append(a[(a[..., 3] == 255) & (np.array(g)[..., 3] == 0)][:, :3])
    if not cols:
        return np.zeros((0, 3), np.uint8)
    c = np.unique(np.concatenate(cols), axis=0).astype(int)
    mx, mn = c.max(1), c.min(1)
    sat = (mx - mn) / np.maximum(mx, 1)
    luma = (0.299 * c[:, 0] + 0.587 * c[:, 1] + 0.114 * c[:, 2]) / 255
    return c[(sat < 0.3) & (c[:, 2] >= c[:, 0] + 4) & (luma > 0.12) & (luma < 0.72)].astype(np.uint8)


def clip_deshadow(frames, band_frac=0.3, tol=14):
    """One shadow decision for a whole clip (2026-10-30 art audit D4, issue #25): the per-frame pass caught the
    shadow in some frames and not in others, so it blinked at 8 fps. Learns the clip's shadow colours from the
    frames where the per-frame pass worked, then removes pieces of those colours in the bottom band of every frame
    when at least half of each piece lies under the figure's lowest pixel in its column (under the feet), so dark
    trousers in the same blue-grey stay. Returns (frames, removed_px)."""
    C = shadow_colours(frames).astype(int)
    if not len(C):
        return frames, 0
    out, total = [], 0
    for f in frames:
        a = np.array(f.convert("RGBA"))
        op = a[..., 3] == 255
        ys = np.nonzero(op.any(1))[0]
        if not len(ys):
            out.append(f)
            continue
        top, b = ys.min(), ys.max()
        band = np.zeros_like(op)
        band[b - int((b - top + 1) * band_frac) + 1:] = True
        d = np.abs(a[..., :3].astype(int)[..., None, :] - C[None, None]).max(-1).min(-1)
        cand = op & band & (d <= tol)
        figure = op & ~cand & band
        rows = np.arange(a.shape[0])[:, None]
        lowest = np.where(figure.any(0), np.where(figure, rows, -1).max(0), -1)
        under = cand & (rows > lowest[None, :])
        lab, n = engine.label(cand, 8)
        kill = np.zeros_like(op)
        for i in range(1, n + 1):
            m = lab == i
            if (m & under).sum() >= 0.5 * m.sum():
                kill |= m
        a[kill, 3] = 0
        total += int(kill.sum())
        out.append(Image.fromarray(a))
    return out, total


MIRROR_DIR = {"e": "w", "w": "e"}


def _colour_counts(img):
    """{16-level colour key: pixel count}, opaque pixel total. 16 levels: an unlocked clip frame and its sprite
    differ by a shade at most."""
    a = np.array(img.convert("RGBA"))
    q = (a[a[..., 3] == 255][:, :3] >> 4).astype(np.int64)
    k = (q[:, 0] << 8) | (q[:, 1] << 4) | q[:, 2]
    v, c = np.unique(k, return_counts=True)
    return dict(zip(v.tolist(), c.tolist())), len(k)


def foreign_px(frames, own, refs, own_max=0.001, other_min=0.004):
    """Per frame: pixels in colours another direction's sprite has (>= other_min of it) and this direction's sprite
    lacks (<= own_max): a staff that is not in the side view, a beak in a back view. The mirror twin (e for w) has the
    same colours and is left out."""
    ho, no = _colour_counts(refs[own])
    fset = set()
    for d, im in refs.items():
        if d in (own, MIRROR_DIR.get(own)):
            continue
        h, n = _colour_counts(im)
        fset |= {k for k, c in h.items() if c / n >= other_min and ho.get(k, 0) / no <= own_max}
    return [sum(c for k, c in _colour_counts(f)[0].items() if k in fset) for f in frames]


def drifted(frames, own, refs, share=0.04, floor=8):
    """First frame of a clip drifting into another direction's design (2026-10-30 art audit D3, issue #24), or None: two
    frames in a row whose foreign-colour pixels exceed floor, 3x the clip's first frame (its start pose) and `share`
    of the figure. Run on the unlocked frames (the palette lock maps foreign colours onto the sprite's own). Catches
    a new object or a turned body (a staff the side view lacks: 14-19 % of the figure); a small feature (a beak,
    about 1 %) stays a review job, like the head-signature note."""
    c = foreign_px(frames, own, refs)
    fig = [int((np.array(f.convert("RGBA"))[..., 3] == 255).sum()) for f in frames]
    lim = [max(floor, 3 * c[0], share * n) for n in fig]   # frame 0 only: a drift can start at frame 1
    for i in range(1, len(c) - 1):
        if c[i] > lim[i] and c[i + 1] > lim[i + 1]:
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


def deslab(img, band_frac=0.2, max_frac=0.2):
    """A baked ground shadow drawn as a light grey slab under the feet (the palette has no dark neutral, so the
    model's soft shadow snaps to light grey: 2026-10-30 art audit D6 / issue #28). Finds light, low-saturation
    pieces in the bottom band that reach the figure's bottom; together (the feet split a slab into pieces) they must
    be wide (>= 20 % of the figure) and flat (width >= 2x height), and at least half of their columns must have
    nothing or a dark outline right above them: a slab sits under the figure, while white feet, steel or snow have
    more figure above. Removes them and then the outline ring left floating where the slab was. Guard: more than
    max_frac of the sprite is a light subject, not a slab. Returns (image, removed_px, note)."""
    a = np.array(img.convert("RGBA"))
    op = a[..., 3] == 255
    ys, xs = np.nonzero(op)
    if not len(ys):
        return img, 0, None
    top, b = ys.min(), ys.max()
    fw = xs.max() - xs.min() + 1
    band = max(4, int((b - top + 1) * band_frac))
    rgb = a[..., :3].astype(np.float32) / 255
    mx, mn = rgb.max(2), rgb.min(2)
    sat = (mx - mn) / np.maximum(mx, 1e-6)
    luma = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    inband = np.zeros_like(op)
    inband[b - band + 1:] = True
    lab, n = engine.label(op & inband & (sat < 0.16) & (luma > 0.45), 8)
    keep = np.zeros_like(op)
    for i in range(1, n + 1):
        m = lab == i
        if np.nonzero(m)[0].max() >= b - 4 and m.sum() >= 4:   # pieces reaching the figure's bottom
            keep |= m
    if not keep.any():
        return img, 0, None
    yy, xx = np.nonzero(keep)
    w, h = xx.max() - xx.min() + 1, yy.max() - yy.min() + 1
    if w < 0.2 * fw or w < 2 * h:
        return img, 0, None
    cols = np.unique(xx)
    tops = np.maximum(np.array([yy[xx == c].min() for c in cols]) - 1, 0)
    exposed = (a[tops, cols, 3] == 0) | (luma[tops, cols] < 0.12)
    if exposed.mean() < 0.5:
        return img, 0, None
    k = int(keep.sum())
    if k > max_frac * op.sum():
        return img, 0, f"ground slab skipped: {k} px ({k / op.sum():.0%}) looks like part of a light subject"
    a[keep, 3] = 0
    removed = keep.copy()
    for _ in range(3):   # peel the dark ring that framed the slab and now touches only air
        op = a[..., 3] == 255
        dark = op & inband & (luma < 0.12)
        floating = dark & engine.dilate(removed, 8) & ~engine.dilate(op & ~dark, 4)
        if not floating.any():
            break
        a[floating, 3] = 0
        removed |= floating
    return Image.fromarray(a), int(removed.sum()), f"ground slab removed: {int(removed.sum())} px"


def contact_shadow(img, band_frac=0.15):
    """(shadow RGBA image, x offset of its centre from the canvas centre) for a sprite standing on its bottom row: a
    dark dithered ellipse 80 % as wide as the figure's lowest band (the feet), a third as tall."""
    a = np.array(img.convert("RGBA"))
    op = a[..., 3] == 255
    ys, xs = np.nonzero(op)
    if not len(ys):
        return None, 0
    top, b = ys.min(), ys.max()
    band = op[max(top, b - max(2, int((b - top + 1) * band_frac))):b + 1].any(0)
    cols = np.nonzero(band)[0]
    w = max(8, int((cols.max() - cols.min() + 1) * 0.8))
    h = max(4, w // 3)
    yy, xx = np.mgrid[0:h, 0:w]
    inside = ((xx - (w - 1) / 2) / (w / 2)) ** 2 + ((yy - (h - 1) / 2) / (h / 2)) ** 2 <= 1
    core_ = ((xx - (w - 1) / 2) / (w / 2.6)) ** 2 + ((yy - (h - 1) / 2) / (h / 2.6)) ** 2 <= 1
    alpha = np.where(core_, 120, np.where(inside & ((xx + yy) % 2 == 0), 120, 0)).astype(np.uint8)
    sh = np.dstack([np.full((h, w, 3), 12, np.uint8), alpha])
    return Image.fromarray(sh), int(round((cols.min() + cols.max()) / 2 - (a.shape[1] - 1) / 2))


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




def _pockets(a, min_area=10):
    """Mask of enclosed, flat (at most 2 colours), near-white components of >= min_area px in an RGBA array.
    Enclosed: a component that touches the image edge or a transparent pixel is part of the silhouette's edge (a
    white glove, a lit rim), not background trapped inside the figure; it never counted before (2026-10-30 Kimi
    audit), so white edges of enemies were deleted."""
    rgb = a[..., :3].astype(int)
    white = (a[..., 3] > 0) & (rgb.min(2) >= 236) & ((rgb.max(2) - rgb.min(2)) <= 10)
    outside = engine.dilate(a[..., 3] == 0, 4)
    lab, n = engine.label(white, 4)
    kill = np.zeros_like(white)
    for i in range(1, n + 1):
        comp = lab == i
        edge = comp[0].any() or comp[-1].any() or comp[:, 0].any() or comp[:, -1].any()
        if (comp.sum() >= min_area and not edge and not (comp & outside).any()
                and len(np.unique(rgb[comp].reshape(-1, 3), axis=0)) <= 2):
            kill |= comp
    return kill


def pocket_report(im, min_area=10):
    """Flag, never remove: [(x, y, w, h, px)] boxes of white pockets that could be trapped background. Props keep
    them by default because flat white paper, clock faces and lamp glass look the same (2026-10-30 audit D7)."""
    lab, n = engine.label(_pockets(np.array(im.convert("RGBA")), min_area), 4)
    out = []
    for i in range(1, n + 1):
        ys, xs = np.nonzero(lab == i)
        out.append((int(xs.min()), int(ys.min()), int(np.ptp(xs) + 1), int(np.ptp(ys) + 1), int(len(ys))))
    return out


def white_pockets(im, min_area=10, max_frac=0.15, force=None):
    """Background trapped inside a sprite (between legs, inside a curled tail): the white-background flood fill
    only reaches from the borders. Removes enclosed, flat, near-white components of >= min_area px.
    Guard: if the pockets would cover more than max_frac of the sprite, the subject is probably white (a frost bear
    had 23% flagged, 2026-10-29) and nothing is removed. force=True removes anyway, force=False never removes.
    Returns (image, removed_px, note)."""
    a = np.array(im.convert("RGBA"))
    op = a[..., 3] > 0
    kill = _pockets(a, min_area)
    k = int(kill.sum())
    if force is False or k == 0:
        return im, 0, None
    if force is not True and k > max_frac * max(1, int(op.sum())):
        return im, 0, f"white pockets skipped: {k} px ({k / op.sum():.0%}) looks like a white subject"
    a[kill] = 0
    return Image.fromarray(a), k, f"white background pockets removed: {k} px"
