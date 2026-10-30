#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# connectors.py
# Purpose : fences, iron railings, steam pipes and rail tracks drawn in code from each blob tile's side connections
#           (straight, elbow, tee, cross, dead end), with collision bands along the line.
# Usage   : used by lane_ground for overlays with "style": "fence_wood" | "fence_iron" | "pipe" | "rail"
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import numpy as np

RAMPS = {
    "fence_wood": {"ink": "2a1a10", "dark": "5a3a22", "mid": "8a5a32", "light": "b88048"},
    "fence_iron": {"ink": "0c0c12", "dark": "2a2c36", "mid": "4a4e5c", "light": "8a90a4"},
    "pipe": {"ink": "2a1608", "dark": "8e5a1e", "mid": "c8902e", "light": "f6d264"},
    "rail": {"ink": "1a120c", "dark": "5a3a22", "mid": "7c5634", "light": "b8c0cc", "steel": "8a90a4"},
}
STYLES = tuple(RAMPS)
SHADOW = (0, 0, 0, 80)


def _c(h):
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)] + [255], np.uint8)


def sides(m):
    return {"N": bool(m & 1), "E": bool(m & 4), "S": bool(m & 16), "W": bool(m & 64)}


def _rect(img, x0, y0, x1, y1, col):
    img[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = col


def _shadow(img, dy=2):
    """Drop shadow of everything drawn, dy px down, under the drawing (on transparent pixels only)."""
    a = img[..., 3] > 0
    sh = np.zeros_like(a)
    sh[dy:] = a[:-dy]
    sh &= ~a
    img[sh] = SHADOW


def fence_wood(m, T, R):
    s, c = sides(m), T // 2
    img = np.zeros((T, T, 4), np.uint8)
    for y0 in (T * 11 // 32, T * 19 // 32):  # two horizontal rails toward E / W
        h = max(2, T // 11)
        if s["W"]:
            _rect(img, 0, y0, c, y0 + h, R["mid"])
            _rect(img, 0, y0, c, y0 + 1, R["light"])
            _rect(img, 0, y0 + h, c, y0 + h + 1, R["ink"])
        if s["E"]:
            _rect(img, c, y0, T, y0 + h, R["mid"])
            _rect(img, c, y0, T, y0 + 1, R["light"])
            _rect(img, c, y0 + h, T, y0 + h + 1, R["ink"])
    w = max(3, T // 8)  # N / S runs: the rail tops seen from above, a narrow vertical band
    if s["N"]:
        _rect(img, c - w // 2, 0, c + w - w // 2, c, R["mid"])
        _rect(img, c - w // 2, 0, c - w // 2 + 1, c, R["light"])
    if s["S"]:
        _rect(img, c - w // 2, c, c + w - w // 2, T, R["mid"])
        _rect(img, c - w // 2, c, c - w // 2 + 1, T, R["light"])
    pw = max(4, T * 6 // 32)  # post at the centre, always
    x0, y0, y1 = c - pw // 2, T * 7 // 32, T * 27 // 32
    _rect(img, x0 - 1, y0 - 1, x0 + pw + 1, y1 + 1, R["ink"])
    _rect(img, x0, y0, x0 + pw, y1, R["mid"])
    _rect(img, x0, y0, x0 + 1, y1, R["light"])
    _rect(img, x0 + pw - 1, y0, x0 + pw, y1, R["dark"])
    _rect(img, x0, y0, x0 + pw, y0 + 2, R["light"])  # post cap
    _shadow(img)
    return img


def fence_iron(m, T, R):
    s, c = sides(m), T // 2
    img = np.zeros((T, T, 4), np.uint8)
    top, bot = T * 8 // 32, T * 23 // 32
    for side, xs in (("W", range(0, c)), ("E", range(c, T))):
        if not s[side]:
            continue
        xs = list(xs)
        _rect(img, xs[0], top, xs[-1] + 1, top + 2, R["mid"])
        _rect(img, xs[0], bot, xs[-1] + 1, bot + 2, R["mid"])
        for x in xs:
            if x % 4 == 1:  # pickets with spear tips
                _rect(img, x, top - 3, x + 1, bot + 4, R["dark"])
                _rect(img, x, top - 4, x + 1, top - 3, R["light"])
    for side, ys in (("N", (0, c)), ("S", (c, T))):
        if s[side]:
            _rect(img, c - 1, ys[0], c + 1, ys[1], R["mid"])
            for y in range(ys[0], ys[1]):
                if y % 4 == 1:
                    _rect(img, c - 2, y, c + 2, y + 1, R["dark"])
    _rect(img, c - 3, top - 5, c + 3, bot + 5, R["ink"])  # square pillar
    _rect(img, c - 2, top - 4, c + 2, bot + 4, R["mid"])
    _rect(img, c - 2, top - 4, c - 1, bot + 4, R["light"])
    _rect(img, c - 3, top - 7, c + 3, top - 5, R["dark"])  # pillar cap
    _shadow(img)
    return img


def pipe(m, T, R):
    s, c = sides(m), T // 2
    img = np.zeros((T, T, 4), np.uint8)
    r = T * 6 // 32  # half thickness
    def h_seg(x0, x1):
        _rect(img, x0, c - r - 1, x1, c + r + 1, R["ink"])
        _rect(img, x0, c - r, x1, c + r, R["mid"])
        _rect(img, x0, c - r, x1, c - r + 2, R["light"])
        _rect(img, x0, c + r - 3, x1, c + r, R["dark"])
    def v_seg(y0, y1):
        _rect(img, c - r - 1, y0, c + r + 1, y1, R["ink"])
        _rect(img, c - r, y0, c + r, y1, R["mid"])
        _rect(img, c - r, y0, c - r + 2, y1, R["light"])
        _rect(img, c + r - 3, y0, c + r, y1, R["dark"])
    if s["W"]:
        h_seg(0, c)
        _rect(img, 0, c - r - 2, 2, c + r + 2, R["dark"])  # flange at the tile edge
    if s["E"]:
        h_seg(c, T)
        _rect(img, T - 2, c - r - 2, T, c + r + 2, R["dark"])
    if s["N"]:
        v_seg(0, c)
        _rect(img, c - r - 2, 0, c + r + 2, 2, R["dark"])
    if s["S"]:
        v_seg(c, T)
        _rect(img, c - r - 2, T - 2, c + r + 2, T, R["dark"])
    n = sum(s.values())
    straight = (s["E"] and s["W"] and not s["N"] and not s["S"]) or (s["N"] and s["S"] and not s["E"] and not s["W"])
    if not straight:  # elbow / tee / cross / cap: a bolted junction box
        b = r + 3
        _rect(img, c - b - 1, c - b - 1, c + b + 1, c + b + 1, R["ink"])
        _rect(img, c - b, c - b, c + b, c + b, R["mid"])
        _rect(img, c - b, c - b, c + b, c - b + 2, R["light"])
        _rect(img, c - b, c + b - 2, c + b, c + b, R["dark"])
        for bx, by in ((c - b + 2, c - b + 3), (c + b - 3, c - b + 3), (c - b + 2, c + b - 4), (c + b - 3, c + b - 4)):
            _rect(img, bx, by, bx + 1, by + 1, R["light"])
        if n == 0:  # isolated: a valve wheel on top
            _rect(img, c - 3, c - 3, c + 3, c + 3, R["dark"])
    _shadow(img)
    return img


def rail(m, T, R):
    s, c = sides(m), T // 2
    img = np.zeros((T, T, 4), np.uint8)
    g = T * 5 // 32  # half gauge
    steel, tie, tie_l = _c(RAMPS["rail"]["steel"]), R["mid"], R["dark"]
    def ties_h(x0, x1):
        for x in range(x0, x1):
            if x % 8 in (2, 3, 4):
                _rect(img, x, c - g - 4, x + 1, c + g + 5, tie if x % 8 != 4 else tie_l)
    def ties_v(y0, y1):
        for y in range(y0, y1):
            if y % 8 in (2, 3, 4):
                _rect(img, c - g - 4, y, c + g + 5, y + 1, tie if y % 8 != 4 else tie_l)
    def rails_h(x0, x1):
        for yy in (c - g, c + g):
            _rect(img, x0, yy, x1, yy + 2, steel)
            _rect(img, x0, yy, x1, yy + 1, R["light"])
    def rails_v(y0, y1):
        for xx in (c - g, c + g):
            _rect(img, xx, y0, xx + 2, y1, steel)
            _rect(img, xx, y0, xx + 1, y1, R["light"])
    turns = [(a, b) for a, b in (("N", "E"), ("E", "S"), ("S", "W"), ("W", "N")) if s[a] and s[b]]
    straight_h, straight_v = s["E"] and s["W"], s["N"] and s["S"]
    if turns and not straight_h and not straight_v:
        # curve: quarter-circle rails around the tile corner between the two open sides
        a, b = turns[0]
        cx = T if "E" in (a, b) else 0
        cy = 0 if "N" in (a, b) else T
        yy, xx = np.mgrid[0:T, 0:T] + 0.5
        d = np.hypot(xx - cx, yy - cy)
        for rr in range(T // 2 - g - 4, T // 2 + g + 5):
            ring = np.abs(d - rr) < 0.5
            ang = np.degrees(np.arctan2(yy - cy, xx - cx)) % 360
            tie_mask = ring & ((ang.astype(int) // 9) % 3 == 0)
            img[tie_mask] = tie
        for rr in (T // 2 - g, T // 2 + g):
            img[np.abs(d - rr) < 1.0] = steel
    else:
        if s["W"] or s["E"] or not (s["N"] or s["S"]):
            x0 = 0 if s["W"] else c - 4
            x1 = T if s["E"] else c + 4
            ties_h(x0, x1)
            rails_h(x0, x1)
        if s["N"] or s["S"]:
            y0 = 0 if s["N"] else c - 4
            y1 = T if s["S"] else c + 4
            ties_v(y0, y1)
            rails_v(y0, y1)
    if sum(s.values()) == 1:  # dead end: a buffer stop
        _rect(img, c - g - 4, c - 3, c + g + 6, c + 3, R["ink"])
        _rect(img, c - g - 3, c - 2, c + g + 5, c + 2, _c("b83a2a"))
    return img


DRAW = {"fence_wood": fence_wood, "fence_iron": fence_iron, "pipe": pipe, "rail": rail}


def ramp(style, colors=None):
    r = dict(RAMPS[style])
    r.update(colors or {})
    return {k: _c(v) for k, v in r.items()}


def tile(m, T, style, colors=None):
    return DRAW[style](m, T, ramp(style, colors))


def solid_rects(m, T, style):
    """Collision along the drawn line (tile-centre coords): thin bands toward each connected side + the centre."""
    if style == "rail":
        return None
    h, k = T // 2, (3 if style.startswith("fence") else T * 6 // 32)
    s = sides(m)
    rects = [(-k, -k, k, k)]
    if s["W"]:
        rects.append((-h, -k, 0, k))
    if s["E"]:
        rects.append((0, -k, h, k))
    if s["N"]:
        rects.append((-k, -h, k, 0))
    if s["S"]:
        rects.append((-k, 0, k, h))
    return rects
