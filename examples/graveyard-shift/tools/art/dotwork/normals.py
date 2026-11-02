#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# normals.py
# Purpose : normal maps for pixel art on the CPU (numpy only: no model, no ComfyUI): a height field from the distance
#           to the clear pixels (a rounded bevel a few px wide) plus a small luminance detail term, Sobel slopes,
#           OpenGL encoding. Atlas mode lights each tile on its own (the detail wraps inside the tile, the bevel only
#           follows clear pixels inside it). Also a Lambert lit preview, and the silhouette outline (marching squares
#           + Douglas-Peucker) that lane_lighting turns into an OccluderPolygon2D.
# Usage   : import normals; nm = normals.normal_map(rgba, bevel=3, detail=1)            # one sprite
#           nm = normals.normal_map(atlas, bevel=2, cells=[(0, 0, 32, 32), (32, 0, 32, 32)])  # an atlas
# Notes   : OpenGL convention (green = up, +Y), what Godot 4 expects: its canvas shader decodes the normal texture as
#           xy * (2, -2) - (1, -1), flipping green into the y-down canvas itself (read from the 4.7.2 binary).
#           Clear pixels (alpha < 128) are flat (128, 128, 255). Deterministic: the same pixels give the same bytes,
#           so a still pose repeated across frames gets identical maps.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import numpy as np

FLAT = (128, 128, 255)                                   # (0, 0, 1) encoded: faces the camera
LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)    # Rec. 709 weights on the stored values: a height cue, not colour science
SQ2 = 1.41421356
MIN_Z = 0.1                                              # the steepest tilt kept: z never drops below this (no edge-on normals)
STEPS8 = ((-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
          (-1, -1, SQ2), (-1, 1, SQ2), (1, -1, SQ2), (1, 1, SQ2))


# ---- height ------------------------------------------------------------------------
def _rgba(a):
    """uint8 HxWx4 from RGBA, RGB or grey input (no alpha = fully opaque)."""
    a = np.asarray(a)
    if a.ndim == 2:
        a = np.dstack([a, a, a])
    if a.shape[2] == 3:
        a = np.dstack([a, np.full(a.shape[:2], 255, np.uint8)])
    return a.astype(np.uint8)


def edge_distance(mask, cap, outside="clear"):
    """Chamfer distance (steps of 1 and sqrt 2) from each opaque pixel to the nearest clear one; correct up to cap,
    larger beyond. outside: what lies past the array edge. "clear" for a sprite (its canvas edge is open air);
    "edge" for an atlas tile (the border pixels continue into the next tile, so an opaque tile is never near a clear
    pixel and gets no rim at its border)."""
    d = np.where(mask, float(cap) + 2.0, 0.0).astype(np.float32)
    mode = "constant" if outside == "clear" else "edge"
    H, W = d.shape
    for _ in range(int(np.ceil(cap)) + 1):   # each pass carries the distance one pixel further in
        p = np.pad(d, 1, mode=mode)           # constant pad is 0: clear beyond the canvas
        best = d
        for dy, dx, step in STEPS8:
            best = np.minimum(best, p[1 + dy:1 + dy + H, 1 + dx:1 + dx + W] + step)
        d = np.where(mask, best, 0.0).astype(np.float32)
    return d


def _fill_clear(v, mask, rounds=2):
    """v with clear pixels set to the mean of their opaque 8-neighbours, `rounds` rings out from the silhouette, so a
    slope taken at the rim never sees whatever colour the clear pixels happen to hold."""
    v = np.where(mask, v, 0.0).astype(np.float32)
    m = mask.astype(np.float32)
    H, W = v.shape
    for _ in range(rounds):
        pv, pm = np.pad(v * m, 1), np.pad(m, 1)
        s = np.zeros_like(v)
        c = np.zeros_like(v)
        for dy, dx, _step in STEPS8:
            s += pv[1 + dy:1 + dy + H, 1 + dx:1 + dx + W]
            c += pm[1 + dy:1 + dy + H, 1 + dx:1 + dx + W]
        grow = (m == 0) & (c > 0)
        v = np.where(grow, s / np.maximum(c, 1.0), v)
        m = np.where(grow, 1.0, m)
    return v


def heights(rgba, bevel=3.0, detail=1.0, outside="clear"):
    """(bevel height, detail height) in pixels, kept apart because their slopes are taken with different borders.
    Bevel: 0 on clear pixels, rising on a rounded profile (45 degrees at the rim, flat from `bevel` px in) to
    bevel / 2. Detail: luminance (0..1) times `detail`, so a black outline next to a white highlight is a step of
    `detail` px; clear pixels borrow their neighbours' value (no step at the rim)."""
    a = _rgba(rgba)
    mask = a[..., 3] >= 128
    if bevel > 0:
        t = np.clip(edge_distance(mask, bevel, outside) / float(bevel), 0.0, 1.0)
        hb = (0.5 * bevel * (1.0 - (1.0 - t) ** 2)).astype(np.float32)
    else:
        hb = np.zeros(mask.shape, np.float32)
    lum = (a[..., :3].astype(np.float32) @ LUMA) / 255.0
    hl = (detail * _fill_clear(lum, mask)).astype(np.float32)
    return hb, hl, mask


# ---- slopes and normals ------------------------------------------------------------
def tile_pad(h, mask):
    """h with a 1 px border taken from the opposite side of the tile (wrap), except where that opposite pixel is
    clear: there the tile's own edge pixel is repeated. An overlay tile clear on its left and opaque on its right
    must not see its clear side across the right border; the opaque side runs on into the next tile."""
    p = np.pad(h, 1, mode="wrap")
    keep = np.pad(mask, 1, mode="wrap")
    keep[1:-1, 1:-1] = True
    return np.where(keep, p, np.pad(h, 1, mode="edge"))


def sobel(h, mode, mask=None):
    """(gx, gy): the slope in height px per px, x to the right and y down, from the 3x3 Sobel kernels / 8 (a plain
    ramp gives its true slope). mode: np.pad mode for the border ("wrap" tiles, "edge", "constant" = 0); with a mask,
    "wrap" falls back to "edge" where the wrapped-in pixel is clear (tile_pad)."""
    p = tile_pad(h, mask) if (mode == "wrap" and mask is not None) else np.pad(h, 1, mode=mode)
    tl, tc, tr = p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:]
    ml, mr = p[1:-1, :-2], p[1:-1, 2:]
    bl, bc, br = p[2:, :-2], p[2:, 1:-1], p[2:, 2:]
    gx = ((tr + 2 * mr + br) - (tl + 2 * ml + bl)) / 8.0
    gy = ((bl + 2 * bc + br) - (tl + 2 * tc + tr)) / 8.0
    return gx, gy


def from_slopes(gx, gy, strength=1.0):
    """Unit normals (x right, y UP, z toward the viewer) of a height field with image slopes gx, gy. The surface
    z = h(x, y_img) has the normal (-dh/dx, -dh/dY, 1) with Y = -y_img, so (-gx, +gy, 1): the left rim of a sprite
    (height rising to the right) points left, its top rim points up. The tilt is capped so z >= MIN_Z."""
    nx = -gx * strength
    ny = gy * strength
    tilt = np.sqrt(nx * nx + ny * ny)
    cap = np.sqrt(1.0 - MIN_Z ** 2) / MIN_Z
    k = np.where(tilt > cap, cap / np.maximum(tilt, 1e-9), 1.0)
    nx, ny = nx * k, ny * k
    inv = 1.0 / np.sqrt(nx * nx + ny * ny + 1.0)
    return np.dstack([nx * inv, ny * inv, inv]).astype(np.float32)


def encode(n):
    """Unit normals -> uint8 RGB, OpenGL convention: r = x right, g = y up, b = z toward the viewer."""
    return np.clip(np.round((n * 0.5 + 0.5) * 255.0), 0, 255).astype(np.uint8)


def decode(rgb):
    """uint8 RGB normal map -> float normals (not renormalised: 8-bit rounding shows as |n| slightly off 1)."""
    return np.asarray(rgb)[..., :3].astype(np.float32) / 255.0 * 2.0 - 1.0


def _one(a, bevel, detail, strength, tile):
    """Encoded normals of one sprite (tile False) or one atlas tile (tile True)."""
    hb, hl, mask = heights(a, bevel, detail, "edge" if tile else "clear")
    # the bevel is 0 beyond a sprite (constant pad) and continues beyond a tile (edge pad); the detail wraps inside
    # a tile (a seamless tile gives a seamless map) and is held at the border of a sprite
    bx, by = sobel(hb, "edge" if tile else "constant")
    lx, ly = sobel(hl, "wrap" if tile else "edge", mask if tile else None)
    enc = encode(from_slopes(bx + lx, by + ly, strength))
    enc[~mask] = FLAT
    return enc


def normal_map(rgba, bevel=3.0, detail=1.0, strength=1.0, cells=None):
    """HxWx3 uint8 normal map (OpenGL) of an image.
    cells None: one sprite, clear beyond its canvas. cells [(x, y, w, h), ...]: an atlas, each rect lit as its own
    tile: the detail wraps inside the rect and the bevel follows only clear pixels inside it, so an opaque tile has
    no rim along its border and a seamless tile stays seamless. Pixels outside every rect are flat."""
    a = _rgba(rgba)
    out = np.empty(a.shape[:2] + (3,), np.uint8)
    out[:] = FLAT
    if cells is None:
        out[:] = _one(a, bevel, detail, strength, False)
        return out
    H, W = a.shape[:2]
    for x, y, w, h in cells:
        w, h = min(w, W - x), min(h, H - y)   # a ragged atlas edge: light what is there
        if w > 0 and h > 0:
            out[y:y + h, x:x + w] = _one(a[y:y + h, x:x + w], bevel, detail, strength, True)
    return out


# ---- lit preview (review sheets only: Godot does the real lighting) -----------------
def shade(rgba, nmap, light, ambient=0.3):
    """Lambert preview: rgb * (ambient + (1 - ambient) * max(0, n . l)). light: direction TO the light in the
    normal map's space (x right, y up, z toward the viewer), e.g. (-1, 1, 1) from the top left. Alpha kept."""
    a = _rgba(rgba)
    n = decode(nmap)
    n /= np.maximum(np.linalg.norm(n, axis=2, keepdims=True), 1e-6)
    l = np.asarray(light, np.float32)
    l = l / np.linalg.norm(l)
    lam = np.clip(n @ l, 0.0, 1.0)
    k = ambient + (1.0 - ambient) * lam
    rgb = np.clip(a[..., :3].astype(np.float32) * k[..., None], 0, 255).astype(np.uint8)
    return np.dstack([rgb, a[..., 3]])


# ---- silhouette outline (for LightOccluder2D) --------------------------------------
# Marching squares on the pixel corners: the state of corner (x, y) is its four pixels, UL 1, UR 2, LL 4, LR 8.
# The walk keeps the silhouette on its left; the two saddles (6, 9) split diagonal neighbours (4-connected).
_UP, _RIGHT, _DOWN, _LEFT = (0, -1), (1, 0), (0, 1), (-1, 0)
_STEP = {1: _UP, 2: _RIGHT, 3: _RIGHT, 4: _LEFT, 5: _UP, 7: _RIGHT, 8: _DOWN, 10: _DOWN, 11: _DOWN, 12: _LEFT,
         13: _UP, 14: _LEFT}


def trace_outline(mask):
    """Outer boundary of the 4-connected region holding the top-most, left-most True pixel, as pixel-corner points
    [(x, y), ...] (a corner (x, y) is the top-left of pixel (x, y)), one closed loop without the repeated start.
    Every point lies on the region's edge. [] for an empty mask."""
    m = np.pad(np.asarray(mask, bool), 1)           # a clear ring, so the walk never leaves the array
    ys, xs = np.nonzero(m)
    if not len(ys):
        return []
    y0 = int(ys.min())
    x0 = int(xs[ys == y0].min())
    x, y, prev = x0, y0, None
    pts = []
    for _ in range(4 * m.size + 8):                 # a closed loop is shorter than this; the cap only guards bugs
        s = int(m[y - 1, x - 1]) + 2 * int(m[y - 1, x]) + 4 * int(m[y, x - 1]) + 8 * int(m[y, x])
        if s == 6:
            step = _LEFT if prev == _UP else _RIGHT
        elif s == 9:
            step = _UP if prev == _RIGHT else _DOWN
        else:
            step = _STEP.get(s)
            if step is None:                        # 0 or 15: not on an edge (cannot happen from a valid start)
                raise ValueError(f"outline walk left the edge at {x - 1},{y - 1}")
        if step != prev:                            # keep only the turns: straight runs add no shape
            pts.append((x - 1, y - 1))
        prev = step
        x, y = x + step[0], y + step[1]
        if (x, y) == (x0, y0):
            break
    else:
        raise ValueError("outline walk did not close")
    return pts


def _seg_dist(p, a, b):
    """Distance from point p to segment ab."""
    p, a, b = (np.asarray(v, np.float64) for v in (p, a, b))
    ab = b - a
    L = float(ab @ ab)
    t = 0.0 if L == 0 else min(1.0, max(0.0, float((p - a) @ ab) / L))
    return float(np.linalg.norm(p - (a + t * ab)))


def _dp(pts, eps):
    """Douglas-Peucker on an open chain (keeps both ends)."""
    if len(pts) < 3:
        return list(pts)
    d = [_seg_dist(p, pts[0], pts[-1]) for p in pts[1:-1]]
    i = int(np.argmax(d)) + 1
    if d[i - 1] <= eps:
        return [pts[0], pts[-1]]
    return _dp(pts[:i + 1], eps)[:-1] + _dp(pts[i:], eps)


def _orient(a, b, c):
    v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (v > 0) - (v < 0)


def _on_seg(a, b, c):
    """c, collinear with ab, lies within its bounding box."""
    return min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= c[1] <= max(a[1], b[1])


def _seg_hit(p1, p2, p3, p4):
    """True when segments p1p2 and p3p4 cross or touch."""
    o1, o2, o3, o4 = _orient(p1, p2, p3), _orient(p1, p2, p4), _orient(p3, p4, p1), _orient(p3, p4, p2)
    if o1 != o2 and o3 != o4:
        return True
    return ((o1 == 0 and _on_seg(p1, p2, p3)) or (o2 == 0 and _on_seg(p1, p2, p4))
            or (o3 == 0 and _on_seg(p3, p4, p1)) or (o4 == 0 and _on_seg(p3, p4, p2)))


def is_simple(pts):
    """True when the closed polygon's edges meet only at shared corners (no crossing, no touching)."""
    n = len(pts)
    if n < 3 or len(set(pts)) < n:
        return False
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):   # neighbouring edges share a corner
                continue
            if _seg_hit(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]):
                return False
    return True


def convex_hull(pts):
    """Convex hull corners (monotone chain), in the outline's own winding sense; the corners are input points."""
    p = sorted(set(pts))
    if len(p) < 3:
        return p

    def half(seq):
        h = []
        for q in seq:
            while len(h) >= 2 and _orient(h[-2], h[-1], q) <= 0:
                h.pop()
            h.append(q)
        return h

    hull = half(p)[:-1] + half(p[::-1])[:-1]
    return hull[::-1] if polygon_area(hull) * polygon_area(pts) < 0 else hull


def simplify(loop, max_points=12, eps=1.0):
    """A closed outline cut to at most max_points corners (Douglas-Peucker, tolerance grown by 1.5x until it fits;
    never fewer than 3). The kept corners are a subset of the input, so they stay on the silhouette's edge.
    Douglas-Peucker can fold a deeply concave outline (a wolf's legs) into a self-crossing polygon, which Godot
    cannot shadow sensibly: then the convex hull of the outline is simplified instead (convex stays simple)."""
    if len(loop) <= 3:
        return list(loop)
    out = _fit(loop, max_points, eps)
    if is_simple(out):
        return out
    hull = convex_hull(loop)
    return _fit(hull, max_points, eps) if len(hull) > max(3, max_points) else hull


def _fit(loop, max_points, eps):
    far = max(range(len(loop)), key=lambda k: (loop[k][0] - loop[0][0]) ** 2 + (loop[k][1] - loop[0][1]) ** 2)
    a, b = loop[:far + 1], loop[far:] + loop[:1]    # split at the start and the corner farthest from it
    while True:
        out = _dp(a, eps)[:-1] + _dp(b, eps)[:-1]
        if len(out) <= max(3, max_points) or eps > 1e4:
            break
        eps *= 1.5
    if len(out) < 3:                                # a sliver: keep the three corners farthest apart
        out = [loop[0], loop[far], loop[(far + len(loop)) // 2 % len(loop)]]
    return out


def polygon_area(pts):
    """Signed shoelace area (positive = clockwise on a y-down screen)."""
    if len(pts) < 3:
        return 0.0
    p = np.asarray(pts, np.float64)
    x, y = p[:, 0], p[:, 1]
    return float(0.5 * (np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)))
