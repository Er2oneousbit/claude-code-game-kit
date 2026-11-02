#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_uikit.py
# Purpose : a whole menu UI kit drawn in code, in a window-skin style: one Godot Theme that styles every Control a
#           settings or pause menu uses (buttons, check boxes, switches, sliders, option buttons, popup menus, scroll
#           bars, tabs, line edits, spin boxes, tooltips, item lists, progress bars, labels, panels, separators) in
#           every state, input prompt glyphs (keyboard keycaps, mouse buttons, generic gamepad shapes), a pointer
#           and a pointing-hand cursor, and a preview scene with the focus chain wired top to bottom.
# Usage   : pack spec "uikit": [{"name": "menu", "style": "iron"}]
#           style: classic / brass / iron (lane_windows.STYLES) or "fill" / "frame" hex lists like a window entry;
#           focus: hex colour of the focus ring (default per style); scale (default 2); font: a .fnt / .ttf in the
#           game for the Theme's default font; keys: extra key names to draw as keycaps ("minus", "f13", "kp_1").
# Notes   : Theme: <assets_dir>/ui/theme_<name>.tres (the kit's shell loads the first assets/ui/theme_*.tres);
#           textures under <assets_dir>/art/ui/uikit/<name>/. Glyphs: <assets_dir>/ui/glyphs/<glyph name>.png at 1x,
#           16 px tall (wide keys grow in width), and glyphs.json {name: {"w", "h"}}; the names follow the kit's
#           glyph_name() (key_space, mouse_left, xbox_a, ps_cross, pad_south, xbox_dpad_up, ps_lstick, unknown).
#           Gamepad glyphs are generic drawn shapes, never a maker's logo. Focus is a ring in its own colour drawn
#           outside the control, so it never reads like hover (gamepad play). Godot's Slider draws one highlight
#           for both hover and focus, so a theme cannot split those two on a slider (see README).
#           verify runs the preview scene's focus walk (ui_down / ui_up) in a headless SceneTree.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import json
import os
import re

import numpy as np
from PIL import Image

import fcore as core
import godot
import lane_fonts
from lane_widgets import button as widget_button
from lane_windows import STYLES, _rgb, draw

FOCUS = {"classic": "ffd84a", "brass": "6ae0ff", "iron": "ffc838"}   # focus ring colour per style
FOCUS_DEFAULT = "ffd84a"
GLYPH_H = 16                                                        # every prompt glyph is 16 px tall at 1x
FONT_FILE = os.path.join(core.HERE, "glyphs", "dialogue.txt")      # keycap labels
HAND_FILE = os.path.join(core.HERE, "glyphs", "symbols.txt")       # the pointing hand (char U+261E)

# ---- glyph names (the kit's glyph_name(): key_ + Godot key name, mouse_, xbox_ / ps_ / pad_ + position name)
XBOX = {"south": "a", "east": "b", "west": "x", "north": "y", "l1": "lb", "r1": "rb", "l2": "lt", "r2": "rt",
        "start": "menu", "select": "view"}
PLAYSTATION = {"south": "cross", "east": "circle", "west": "square", "north": "triangle", "start": "options",
               "select": "share"}
PAD = ("south", "east", "west", "north", "l1", "r1", "l2", "r2", "start", "select", "dpad_up", "dpad_down",
       "dpad_left", "dpad_right", "lstick", "rstick", "l3", "r3", "guide")
KEYS = (["space", "escape", "enter", "up", "down", "left", "right", "shift", "tab", "backspace", "ctrl", "alt"]
        + [chr(c) for c in range(ord("a"), ord("z") + 1)] + [str(d) for d in range(10)]
        + [f"f{n}" for n in range(1, 13)])
MOUSE = ("left", "right", "middle")
# keycap text for Godot key names that are not their own label
KEY_LABELS = {"space": "SPACE", "escape": "ESC", "enter": "ENTER", "shift": "SHIFT", "tab": "TAB", "backspace": "BKSP",
              "ctrl": "CTRL", "alt": "ALT", "minus": "-", "equal": "=", "comma": ",", "period": ".", "slash": "/",
              "backslash": "\\", "semicolon": ";", "apostrophe": "'", "bracketleft": "[", "bracketright": "]",
              "quoteleft": "`", "delete": "DEL", "insert": "INS", "home": "HOME", "end": "END", "pageup": "PGUP",
              "pagedown": "PGDN", "capslock": "CAPS", "kp_enter": "ENTER", "meta": "META", "menu": "MENU",
              "unknown": "?"}
WIDE = {"space": 40, "enter": 30, "shift": 32, "tab": 26, "backspace": 34}   # minimum keycap width, 1x px
ARROWS = ("up", "down", "left", "right")

# glyph colours: neutral, the same for every style (glyphs are shared by every theme in the game)
OUT = (20, 18, 28)
CAP_HI, CAP_TOP, CAP_SIDE, CAP_LOW = (255, 255, 255), (238, 238, 244), (170, 174, 190), (128, 132, 150)
INK = (34, 32, 46)
BODY, RING, PAD_INK, DIM = (58, 60, 74), (150, 154, 172), (240, 240, 246), (96, 100, 118)
LIT = (255, 204, 64)


def glyph_names(extra=()):
    """Every prompt glyph this lane ships: the kit's default set plus extra key names (sorted, unique)."""
    names = {"unknown"} | {"key_" + k for k in KEYS} | {"mouse_" + m for m in MOUSE}
    for p in PAD:
        names |= {"xbox_" + XBOX.get(p, p), "ps_" + PLAYSTATION.get(p, p), "pad_" + p}
    names |= {"key_" + k for k in extra}
    return sorted(names)


def key_name(k, where):
    """A spec "keys" item ("minus", "key_f13") -> the Godot-style key name ("minus", "f13")."""
    if not isinstance(k, str) or not k.strip():
        raise core.ToolError(f"{where}: \"keys\" holds key names as strings (\"minus\", \"f13\", \"kp_1\")")
    k = k.strip().lower()
    k = k[4:] if k.startswith("key_") else k
    if not re.fullmatch(r"[a-z0-9_]+", k):
        raise core.ToolError(f"{where}: key {k!r}: Godot key names use a-z, 0-9 and _ (\"minus\", \"kp_1\")")
    return k


# ---- small drawing helpers (1x RGBA numpy arrays) ----------------------------------------------------------------
def _c(h):
    return tuple(int(v) for v in _rgb(h)) if isinstance(h, str) else tuple(h)


def _mix(a, b, t):
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))


def _canvas(h, w):
    return np.zeros((h, w, 4), np.uint8)


def _put(a, mask, col, alpha=255):
    a[mask, :3] = col[:3]
    a[mask, 3] = alpha


def _disc(d):
    """bool mask of a filled circle d px wide."""
    r = (d - 1) / 2.0
    y, x = np.mgrid[0:d, 0:d]
    return (x - r) ** 2 + (y - r) ** 2 <= (r + 0.35) ** 2


def _rrect(h, w, r):
    """bool mask of a rounded rectangle (corner radius r px)."""
    m = np.ones((h, w), bool)
    if r <= 0:
        return m
    y, x = np.mgrid[0:h, 0:w]
    for cy, cx in ((r, r), (r, w - 1 - r), (h - 1 - r, r), (h - 1 - r, w - 1 - r)):
        corner = ((y < r) if cy == r else (y > h - 1 - r)) & ((x < r) if cx == r else (x > w - 1 - r))
        m &= ~(corner & ((x - cx) ** 2 + (y - cy) ** 2 > (r + 0.3) ** 2))
    return m


def _edge(mask):
    """The outer one-pixel rim of a mask (pixels of mask with a 4-neighbour outside it)."""
    p = np.pad(mask, 1)
    inner = p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
    return mask & ~inner


def _grey(a, dim=0.75):
    """Disabled look: desaturated and darker, alpha kept."""
    out = a.copy()
    rgb = out[..., :3].astype(np.float32)
    g = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    out[..., :3] = np.clip((rgb * 0.25 + g[..., None] * 0.75) * dim, 0, 255).astype(np.uint8)
    return out


def _lighten(a, t=0.3, region=None):
    out = a.copy()
    sl = region if region is not None else (slice(None), slice(None))
    rgb = out[sl][..., :3].astype(np.float32)
    out[sl][..., :3] = np.clip(rgb * (1 - t) + 255 * t, 0, 255).astype(np.uint8)
    return out


def _arrow(direction, size=7):
    """bool mask of a solid arrow (triangle head + stem), size x size, pointing up / down / left / right."""
    m = np.zeros((size, size), bool)
    head = (size + 1) // 2
    mid = size // 2
    for y in range(head):
        m[y, mid - y:mid + y + 1] = True
    stem = max(1, size // 3) | 1                     # odd, so the arrow is symmetric about its middle column
    m[head:, mid - stem // 2:mid - stem // 2 + stem] = True
    return {"up": m, "down": m[::-1], "left": m.T, "right": m.T[:, ::-1]}[direction]


def _tri(direction, w, h):
    """bool mask of a solid triangle pointing down (w x h) or right / left / up (rotated)."""
    m = np.zeros((h, w), bool)
    for y in range(h):
        x0 = int(round(y * (w / 2.0) / h))
        m[y, x0:w - x0] = True
    if direction == "down":
        return m
    if direction == "up":
        return m[::-1]
    return m.T[:, ::-1] if direction == "right" else m.T


# ---- the font: keycap labels from Dotwork's glyph font ------------------------------------------------------------
_FONT = {}


def font():
    if not _FONT:
        meta, glyphs = lane_fonts.parse(FONT_FILE)
        _FONT.update(meta=meta, glyphs=glyphs)
    return _FONT["meta"], _FONT["glyphs"]


def label_mask(text):
    """bool mask of a text label in the dialogue glyph font, cropped to its ink rows (unknown characters: '?')."""
    meta, glyphs = font()
    cols = []
    for i, ch in enumerate(text):
        g = glyphs.get(ch) if ch in glyphs else glyphs.get(ch.upper(), glyphs["?"])
        if i:
            cols.append(np.zeros((meta["height"], meta["spacing"]), bool))
        cols.append(g)
    m = np.concatenate(cols, axis=1) if cols else np.zeros((meta["height"], 1), bool)
    rows = np.where(m.any(axis=1))[0]
    return m[rows[0]:rows[-1] + 1] if len(rows) else m[:1]


def _stamp(a, mask, col, cy=None, cx=None):
    """Draw mask centred at (cy, cx) of a (default: the middle)."""
    h, w = mask.shape
    cy = a.shape[0] / 2.0 if cy is None else cy
    cx = a.shape[1] / 2.0 if cx is None else cx
    y0, x0 = int(round(cy - h / 2.0)), int(round(cx - w / 2.0))
    sub = np.zeros(a.shape[:2], bool)
    sub[y0:y0 + h, x0:x0 + w] = mask[:max(0, min(h, a.shape[0] - y0)), :max(0, min(w, a.shape[1] - x0))]
    _put(a, sub, col)


# ---- prompt glyphs ------------------------------------------------------------------------------------------------
def keycap(key):
    """A keyboard key: light keycap with a darker front edge, label from the font (arrows drawn), 16 px tall; the
    width fits the label, at least 16 px (space / enter / shift / tab / backspace are wider)."""
    if key in ARROWS:
        lab = _arrow(key, 7)
    else:
        text = KEY_LABELS.get(key, key.upper().replace("_", ""))
        lab = label_mask(text[:6])
        if lab.sum() < 6:                               # a lone "-" or "." reads better twice the size
            lab = np.kron(lab, np.ones((2, 2), bool))
    W = max(16, lab.shape[1] + 8, WIDE.get(key, 0))
    a = _canvas(GLYPH_H, W)
    body = _rrect(GLYPH_H, W, 2)
    _put(a, body, CAP_SIDE)
    face = np.zeros_like(body)
    face[1:12, 1:W - 1] = True
    _put(a, face & body, CAP_TOP)
    a[1, 2:W - 2, :3] = CAP_HI                      # top highlight
    a[13:15, 2:W - 2, :3] = CAP_LOW                 # shaded front edge
    _put(a, _edge(body), OUT)
    _stamp(a, lab, INK, cy=6.5, cx=W / 2.0)         # label centred on the face (rows 1..11)
    return a


def _circle_button(fill=BODY, ring=RING, d=15):
    a = _canvas(GLYPH_H, 16)
    m = np.zeros((GLYPH_H, 16), bool)
    m[0:d, 0:d] = _disc(d)
    _put(a, m, fill)
    rim = _edge(m)
    inner = _edge(m & ~rim)
    _put(a, inner, ring)
    _put(a, rim, OUT)
    return a


def face_letter(letter):
    """Xbox-style face button: a letter in a neutral circle (no maker colours)."""
    a = _circle_button()
    _stamp(a, label_mask(letter), PAD_INK, cy=7.5, cx=7.5)
    return a


def face_symbol(kind):
    """PlayStation-style face button: an outline cross, circle, square or triangle in a neutral circle."""
    a = _circle_button()
    s = np.zeros((7, 7), bool)
    if kind == "cross":
        for i in range(7):
            s[i, i] = s[i, 6 - i] = True
    elif kind == "circle":
        s = _edge(_disc(7))
    elif kind == "square":
        s[0, :] = s[-1, :] = s[:, 0] = s[:, -1] = True
    else:   # triangle: apex up, outline
        t = np.zeros((6, 7), bool)
        for y in range(6):
            x0 = 3 - (y * 3 + 2) // 5
            t[y, x0] = t[y, 6 - x0] = True
        t[5, :] = True
        s = t
    _stamp(a, s, PAD_INK, cy=7.5, cx=7.5)
    return a


def diamond(lit):
    """Generic face buttons: four dots in a diamond, the named position (south / east / west / north) filled."""
    a = _canvas(GLYPH_H, 16)
    pos = {"north": (0, 5), "west": (5, 0), "east": (5, 10), "south": (10, 5)}
    for k, (y, x) in pos.items():
        m = np.zeros((GLYPH_H, 16), bool)
        m[y:y + 6, x:x + 6] = _disc(6)
        if k == lit:
            _put(a, m, LIT)
        else:
            _put(a, m, BODY)
            _put(a, _edge(m & ~_edge(m)), DIM)
        _put(a, _edge(m), OUT)
    return a


def shoulder(text, trigger):
    """Shoulder (LB / L1: a low bar) or trigger (LT / L2: a tall rounded-top shape) with its label."""
    lab = label_mask(text)
    W = max(18, lab.shape[1] + 8)
    a = _canvas(GLYPH_H, W)
    m = np.zeros((GLYPH_H, W), bool)
    if trigger:
        m[0:16, :] = _rrect(16, W, 5)
        m[12:, :] &= _rrect(4, W, 1)[-4:, :]
    else:
        m[3:13, :] = _rrect(10, W, 3)
    _put(a, m, BODY)
    _put(a, _edge(m & ~_edge(m)), RING)
    _put(a, _edge(m), OUT)
    rows = np.where(m.any(axis=1))[0]
    _stamp(a, lab, PAD_INK, cy=(rows[0] + rows[-1] + 1) / 2.0 + (1 if trigger else 0), cx=W / 2.0)
    return a


PILL_ICONS = {   # 7 x 5 icons for the small centre buttons
    "menu": ["#######", ".......", "#######", ".......", "#######"],
    "options": ["#######", ".......", "#######", ".......", "#######"],
    "view": ["####...", "#..###.", "#..#.#.", "####.#.", "...###."],
    "share": ["...#...", "..###..", ".#.#.#.", "...#...", "#######"],
    "start": [".#.....", ".###...", ".#####.", ".###...", ".#....."],
    "select": [".#####.", ".#...#.", ".#...#.", ".#...#.", ".#####."],
    "guide": ["...#...", "..###..", ".#####.", "..#.#..", "..###.."],
}


def pill(icon):
    """Small centre button (menu / view / options / share / start / select): a pill with a simple icon."""
    W = 18
    a = _canvas(GLYPH_H, W)
    m = np.zeros((GLYPH_H, W), bool)
    m[3:13, :] = _rrect(10, W, 4)
    _put(a, m, BODY)
    _put(a, _edge(m & ~_edge(m)), RING)
    _put(a, _edge(m), OUT)
    ic = np.array([[c == "#" for c in row] for row in PILL_ICONS[icon]], bool)
    _stamp(a, ic, PAD_INK, cy=8, cx=W / 2.0)
    return a


def guide():
    """Home / guide button: a round button with a small house."""
    a = _circle_button()
    ic = np.array([[c == "#" for c in row] for row in PILL_ICONS["guide"]], bool)
    _stamp(a, ic, PAD_INK, cy=7.5, cx=7.5)
    return a


def dpad(direction):
    """A plus-shaped d-pad with the named arm lit."""
    a = _canvas(GLYPH_H, 16)
    m = np.zeros((GLYPH_H, 16), bool)
    m[0:15, 5:10] = True
    m[5:10, 0:15] = True
    _put(a, m, BODY)
    arm = np.zeros_like(m)
    sl = {"up": (slice(1, 5), slice(6, 9)), "down": (slice(10, 14), slice(6, 9)),
          "left": (slice(6, 9), slice(1, 5)), "right": (slice(6, 9), slice(10, 14))}[direction]
    arm[sl] = True
    _put(a, arm, LIT)
    _put(a, _edge(m), OUT)
    return a


def stick(text):
    """An analogue stick seen from above: a circle with a smaller cap, labelled L / R (L3 / R3 when pressed)."""
    a = _circle_button(fill=DIM)
    cap = np.zeros((GLYPH_H, 16), bool)
    cap[2:13, 2:13] = _disc(11)
    _put(a, cap, BODY)
    _put(a, _edge(cap), OUT)
    _stamp(a, label_mask(text), PAD_INK, cy=7.5, cx=7.5)
    return a


def mouse(button):
    """A mouse outline with the left / right / middle button highlighted."""
    W = 11
    a = _canvas(GLYPH_H, W + 1)
    body = np.zeros((GLYPH_H, W + 1), bool)
    body[0:16, 0:W] = _rrect(16, W, 4)
    _put(a, body, CAP_TOP)
    top = np.zeros_like(body)
    top[1:7, :] = True
    left, right = top.copy(), top.copy()
    left[:, 5:] = False
    right[:, :6] = False
    for k, part in (("left", left), ("right", right)):
        _put(a, part & body, LIT if k == button else CAP_SIDE)
    a[0:7, 5, :3] = OUT                              # divider between the buttons
    a[7, 0:W, :3] = OUT                              # where the buttons end
    a[2:5, 5, :3] = LIT if button == "middle" else DIM   # the wheel
    _put(a, _edge(body), OUT)
    return a


def draw_glyph(name):
    """The 1x RGBA image for one glyph name (see glyph_names)."""
    kind, _, rest = name.partition("_")
    if name == "unknown":
        return keycap("unknown")
    if kind == "key":
        return keycap(rest)
    if kind == "mouse":
        return mouse(rest)
    pos = rest
    if kind == "xbox":
        pos = {v: k for k, v in XBOX.items()}.get(rest, rest)
    elif kind == "ps":
        pos = {v: k for k, v in PLAYSTATION.items()}.get(rest, rest)
    if pos.startswith("dpad_"):
        return dpad(pos[5:])
    if pos in ("lstick", "rstick"):
        return stick(pos[0].upper())
    if pos in ("l3", "r3"):
        return stick(pos.upper())
    if pos == "guide":
        return guide()
    if pos in ("l1", "r1", "l2", "r2"):
        text = rest.upper() if kind == "xbox" else pos.upper()   # LB / RT, or L1 / R2
        return shoulder(text, pos.endswith("2"))
    if pos in ("start", "select"):
        return pill(rest if kind in ("xbox", "ps") else pos)
    if pos in ("south", "east", "west", "north"):
        if kind == "xbox":
            return face_letter(rest.upper())
        if kind == "ps":
            return face_symbol(rest)
        return diamond(pos)
    raise core.ToolError(f"uikit: no drawing for glyph {name!r}")


# ---- cursors -------------------------------------------------------------------------------------------------------
POINTER = ["#...........",
           "##..........",
           "#w#.........",
           "#ww#........",
           "#www#.......",
           "#wwww#......",
           "#wwwww#.....",
           "#wwwwww#....",
           "#wwwwwww#...",
           "#wwwwwwww#..",
           "#wwwwwwwww#.",
           "#wwwww#####.",
           "#ww#ww#.....",
           "#w#.#ww#....",
           "##..#ww#....",
           "#....#ww#...",
           ".....#ww#...",
           "......##...."]


def cursor_pointer():
    """Arrow pointer: white with a dark outline, hotspot at the tip (0, 0)."""
    a = _canvas(len(POINTER), len(POINTER[0]))
    for y, row in enumerate(POINTER):
        for x, ch in enumerate(row):
            if ch != ".":
                a[y, x] = (OUT if ch == "#" else CAP_HI) + (255,)
    return a


def cursor_select():
    """Menu selection cursor: the glyph font's pointing hand (U+261E), white with a dark outline."""
    _, glyphs = lane_fonts.parse(HAND_FILE)
    hand = glyphs["☞"]
    rgba, _ = lane_fonts.render_glyph(hand, 1, "outline")
    rows = np.where(rgba[..., 3].any(axis=1))[0]
    return np.ascontiguousarray(rgba[rows[0]:rows[-1] + 1])


def hotspot(a):
    """(x, y) of the fingertip: the rightmost inked column, its middle inked row."""
    ys, xs = np.where(a[..., 3] > 0)
    x = int(xs.max())
    return x, int(np.median(ys[xs == x]))


# ---- theme textures ------------------------------------------------------------------------------------------------
def style_of(e, name):
    """lane_windows style + focus colour; a typo'd style is a usage error (exit 2)."""
    sname = e.get("style", "classic")
    if sname not in STYLES and not ("fill" in e and "frame" in e):
        raise core.ToolError(f"uikit {name}: style {sname!r} is not one of {', '.join(STYLES)} (or give \"fill\" and "
                             "\"frame\" hex lists)")
    st = dict(STYLES.get(sname, STYLES["classic"]))
    st.update({k: e[k] for k in ("fill", "frame") if k in e})
    try:
        for c in list(st["fill"]) + list(st["frame"]) + [e.get("focus") or "000000"]:
            _rgb(c)
        if len(st["frame"]) < 2 or len(st["fill"]) < 2:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise core.ToolError(f"uikit {name}: fill / frame / focus are hex colours, fill at least 2 and frame at least "
                             "2 (outline first)")
    st["focus"] = e.get("focus") or FOCUS.get(sname, FOCUS_DEFAULT)
    return st


def colours(st):
    """Named colours of a style: text in each state, ink, accent, the focus ring."""
    fr = [_c(c) for c in st["frame"]]
    fi = [_c(c) for c in st["fill"]]
    text = _mix(fr[1], (255, 255, 255), 0.35)
    return {"outline": fr[0], "light": fr[1], "metal": fr[2] if len(fr) > 2 else fr[1],
            "dark_metal": fr[-2] if len(fr) > 2 else fr[0],
            "fill": fi, "text": text, "text_hover": (255, 255, 255), "text_pressed": _mix(text, fr[1], 0.5),
            "text_disabled": (128, 128, 142), "text_dim": _mix(text, fi[-1], 0.35), "focus": _c(st["focus"]),
            "well": _mix(fi[-1], (0, 0, 0), 0.35), "shadow": _mix(fi[-1], (0, 0, 0), 0.65)}


def focus_ring(col):
    """The focus ring: a dark rim and two pixels of the focus colour, hollow; drawn outside the control (expand
    margin), so it never covers what hover changes."""
    a = _canvas(10, 10)
    for k, c in ((0, OUT), (1, col), (2, col)):
        a[k, k:10 - k] = a[9 - k, k:10 - k] = a[k:10 - k, k] = a[k:10 - k, 9 - k] = c + (255,)
    a[0, 0] = a[0, 9] = a[9, 0] = a[9, 9] = 0
    return a, 3


def well(c, size=12, rim=None):
    """A sunken field (line edit, track, list): dark inside, inner shadow top-left, a light lip bottom-right.
    rim: replace the outline with this colour (scroll_focus)."""
    a = _canvas(size, size)
    a[..., :3] = c["well"]
    a[..., 3] = 255
    a[1, 1:-1, :3] = a[1:-1, 1, :3] = c["shadow"]
    a[-2, 1:-1, :3] = a[1:-1, -2, :3] = c["dark_metal"]
    ol = rim or c["outline"]
    a[0, :, :3] = a[-1, :, :3] = a[:, 0, :3] = a[:, -1, :3] = ol
    if rim:
        a[1, 1:-1, :3] = a[1:-1, 1, :3] = a[-2, 1:-1, :3] = a[1:-1, -2, :3] = _mix(rim, c["well"], 0.45)
    a[0, 0] = a[0, -1] = a[-1, 0] = a[-1, -1] = 0
    return a, 3 if size >= 10 else 2


def bar(fill_col, rim_col, size=8):
    """A flat highlight bar (hovered or selected row), 1 px rim."""
    a = _canvas(size, size)
    a[..., :3] = fill_col
    a[..., 3] = 255
    a[0, :, :3] = a[-1, :, :3] = a[:, 0, :3] = a[:, -1, :3] = rim_col
    return a, 2


def ring1(col, size=8):
    """A one-pixel hollow ring (item cursor)."""
    a = _canvas(size, size)
    a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = col + (255,)
    return a, 2


def tab(st, state):
    """A tab: the window drawing with its bottom open onto the panel; unselected tabs sit 2 px lower and darker."""
    frame = list(st["frame"][:3])
    n = len(frame)
    img, _ = draw(st["fill"], frame, False, 16)
    t = img.copy()
    t[16 - n:] = img[15 - n]                        # open bottom: the side rings and the fill run on downwards
    if state != "selected":
        low = _canvas(16, 16)
        low[2:] = t[:-2]
        t = low
        t[..., :3] = (t[..., :3].astype(np.float32) * 0.62).astype(np.uint8)
        if state == "hovered":
            t = _lighten(t, 0.3, (slice(n + 2, 16), slice(n, 16 - n)))
        elif state == "disabled":
            t = _grey(t)
    return t, n


def knob(c, h=10, w=6, hl=None):
    """Slider grabber / scroll grabber: a small raised block. hl: outline in this colour (highlight)."""
    a = _canvas(h, w)
    m = _rrect(h, w, 1)
    _put(a, m, c["metal"])
    a[1:3, 1:w - 1, :3] = c["light"]
    a[h - 3:h - 1, 1:w - 1, :3] = c["dark_metal"]
    _put(a, _edge(m), hl or c["outline"])
    a[..., 3] = np.where(m, 255, 0)
    return a


def check_icon(c, checked, radio=False, size=10):
    """Check box / radio icon: a small well, a check mark or a dot when checked."""
    if radio:
        a = _canvas(size, size)
        m = _disc(size)
        _put(a, m, c["well"])
        _put(a, _edge(m), c["outline"])
        if checked:
            dot = np.zeros_like(m)
            dot[3:size - 3, 3:size - 3] = _disc(size - 6)
            _put(a, dot, c["light"])
        return a
    a, _ = well(c, size)
    if checked:
        mark = np.array([[ch == "#" for ch in r] for r in
                         ["......", ".....#", "....##", "#..##.", "####..", ".##..."]], bool)
        _stamp(a, mark, c["light"], cy=size / 2.0, cx=size / 2.0)
    return a


def switch_icon(c, on, w=16, h=10):
    """CheckButton switch: a track with the knob left (off) or right and lit (on)."""
    a = _canvas(h, w)
    m = _rrect(h, w, 4)
    _put(a, m, _mix(c["metal"], c["light"], 0.3) if on else c["well"])   # on: a lit metal track
    _put(a, _edge(m), c["outline"])
    k = np.zeros_like(m)
    x0 = w - h if on else 0
    k[:, x0:x0 + h] = _disc(h)
    _put(a, k, c["light"] if on else c["dark_metal"])
    _put(a, _edge(k), c["outline"])
    return a


def textures(st):
    """Every theme texture at 1x: {name: (rgba, nine-patch margin)}; icons have margin None."""
    c = colours(st)
    fill, frame, rivets = st["fill"], st["frame"], st.get("rivets", False)
    t = {}
    # buttons and tabs keep three frame rings (outline, highlight, metal): menus in a 640 x 360 shell need slim
    # controls, and the full window frame made the settings tab row too wide for its screen
    slim = list(frame[:3])
    for state in ("normal", "hover", "pressed", "disabled"):
        t[f"button_{state}"] = (widget_button(fill, slim, state, 12)[0], len(slim))
    t["focus"] = focus_ring(c["focus"])
    t["panel"] = draw(fill, frame, rivets, 24)
    t["popup"] = draw(fill, frame[:3], False, 16)
    t["tooltip"] = draw(fill, frame[:2], False, 12)
    t["well"] = well(c)
    t["well_ro"] = (_grey(well(c)[0], 0.9), 3)
    t["track"] = well(c, 8)
    t["scroll"] = well(c, 8)
    t["scroll_focus"] = well(c, 8, rim=c["focus"])
    t["row_hover"] = bar(_mix(c["fill"][0], (255, 255, 255), 0.22), c["metal"])
    t["row_selected"] = bar(_mix(c["metal"], c["fill"][1], 0.45), c["metal"])
    t["row_selected_focus"] = bar(_mix(c["metal"], c["fill"][1], 0.45), c["focus"])
    t["cursor"] = ring1(c["focus"])
    t["cursor_unfocused"] = ring1(c["dark_metal"])
    area = bar(c["metal"], c["outline"], 8)[0]
    area[1, 1:-1, :3] = c["light"]
    t["grabber_area"] = (area, 2)
    hi = bar(_mix(c["metal"], c["focus"], 0.55), c["outline"], 8)[0]
    hi[1, 1:-1, :3] = _mix(c["light"], c["focus"], 0.5)
    t["grabber_area_hl"] = (hi, 2)
    for state in ("selected", "unselected", "hovered", "disabled"):
        t[f"tab_{state}"] = tab(st, state)
    sk = knob(c, 8, 8)
    t["scroll_grabber"] = (sk, 3)
    t["scroll_grabber_hl"] = (_lighten(sk, 0.3), 3)
    t["scroll_grabber_pressed"] = ((sk.astype(np.float32) * [0.7, 0.7, 0.7, 1]).astype(np.uint8), 3)
    pf = bar(c["metal"], c["outline"], 8)[0]
    pf[1, 1:-1, :3] = c["light"]
    pf[-2, 1:-1, :3] = c["dark_metal"]
    t["progress_fill"] = (pf, 3)
    # icons (no nine-patch)
    g = knob(c, 10, 6)
    t["grabber"] = (g, None)
    t["grabber_hl"] = (knob(c, 10, 6, hl=c["focus"]), None)
    t["grabber_disabled"] = (_grey(g), None)
    t["vgrabber"] = (np.ascontiguousarray(g.transpose(1, 0, 2)), None)
    t["vgrabber_hl"] = (np.ascontiguousarray(t["grabber_hl"][0].transpose(1, 0, 2)), None)
    t["vgrabber_disabled"] = (np.ascontiguousarray(t["grabber_disabled"][0].transpose(1, 0, 2)), None)
    tick = _canvas(3, 1)
    tick[..., :3] = c["light"]
    tick[..., 3] = 255
    t["tick"] = (tick, None)
    for on in (True, False):
        k = "checked" if on else "unchecked"
        t[f"check_{k}"] = (check_icon(c, on), None)
        t[f"check_{k}_disabled"] = (_grey(check_icon(c, on)), None)
        t[f"radio_{k}"] = (check_icon(c, on, radio=True), None)
        t[f"radio_{k}_disabled"] = (_grey(check_icon(c, on, radio=True)), None)
        s = switch_icon(c, on)
        t[f"switch_{k}"] = (s, None)
        t[f"switch_{k}_disabled"] = (_grey(s), None)
        t[f"switch_{k}_mirrored"] = (np.ascontiguousarray(s[:, ::-1]), None)
        t[f"switch_{k}_disabled_mirrored"] = (np.ascontiguousarray(_grey(s)[:, ::-1]), None)
    for k, (d, w, h) in {"arrow": ("down", 7, 4), "submenu": ("right", 7, 4), "submenu_mirrored": ("left", 7, 4)}.items():
        m = _tri(d, w, h)
        a = _canvas(*m.shape)
        _put(a, m, c["text"])
        t[k] = (a, None)
    ud = _canvas(10, 7)
    _put(ud, np.vstack([_tri("up", 7, 4), np.zeros((2, 7), bool), _tri("down", 7, 4)]), c["text"])
    t["updown"] = (ud, None)
    return t, c


# ---- theme .tres ---------------------------------------------------------------------------------------------------
def _col(rgb, a=1.0):
    return "Color(%.4g, %.4g, %.4g, %.4g)" % (rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, a)


class _Tres:
    """Collects ext_resources, sub_resources and Theme properties, then writes one Theme .tres."""

    def __init__(self):
        self.ext, self.sub, self.props, self.ids = [], [], [], {}

    def ext_res(self, kind, path):
        if path not in self.ids:
            self.ext.append(f'[ext_resource type="{kind}" path="{path}" id="{len(self.ext) + 1}_{kind.lower()}"]')
            self.ids[path] = f"{len(self.ext)}_{kind.lower()}"
        return f'ExtResource("{self.ids[path]}")'

    def sub_res(self, key, kind, lines):
        if key not in self.ids:
            sid = f"{kind}_{key}"
            self.sub.append("\n".join([f'[sub_resource type="{kind}" id="{sid}"]'] + lines + [""]))
            self.ids[key] = sid
        return f'SubResource("{self.ids[key]}")'

    def set(self, typ, kind, item, value):
        self.props.append(f"{typ}/{kind}/{item} = {value}")

    def text(self):
        head = f'[gd_resource type="Theme" load_steps={len(self.ext) + len(self.sub) + 1} format=3]\n\n'
        return (head + "\n".join(self.ext) + "\n\n" + "\n".join(self.sub) + "\n[resource]\n"
                + "\n".join(self.props) + "\n")


# every Theme item the kit asks for, per type: what a test (and a reader) checks against
REQUIRED = {
    "Button": {"styles": ["normal", "hover", "pressed", "disabled", "focus"]},
    "CheckBox": {"styles": ["normal", "hover", "pressed", "disabled", "focus", "hover_pressed"],
                 "icons": ["checked", "unchecked", "checked_disabled", "unchecked_disabled", "radio_checked",
                           "radio_unchecked", "radio_checked_disabled", "radio_unchecked_disabled"]},
    "CheckButton": {"styles": ["normal", "hover", "pressed", "disabled", "focus", "hover_pressed"],
                    "icons": ["checked", "unchecked", "checked_disabled", "unchecked_disabled", "checked_mirrored",
                              "unchecked_mirrored", "checked_disabled_mirrored", "unchecked_disabled_mirrored"]},
    "HSlider": {"styles": ["slider", "grabber_area", "grabber_area_highlight"],
                "icons": ["grabber", "grabber_highlight", "grabber_disabled", "tick"]},
    "VSlider": {"styles": ["slider", "grabber_area", "grabber_area_highlight"],
                "icons": ["grabber", "grabber_highlight", "grabber_disabled", "tick"]},
    "OptionButton": {"styles": ["normal", "hover", "pressed", "disabled", "focus", "normal_mirrored",
                                "hover_mirrored", "pressed_mirrored", "disabled_mirrored"], "icons": ["arrow"]},
    "PopupMenu": {"styles": ["panel", "hover", "separator", "labeled_separator_left", "labeled_separator_right"],
                  "icons": ["checked", "unchecked", "checked_disabled", "unchecked_disabled", "radio_checked",
                            "radio_unchecked", "radio_checked_disabled", "radio_unchecked_disabled", "submenu",
                            "submenu_mirrored"]},
    "HScrollBar": {"styles": ["scroll", "scroll_focus", "grabber", "grabber_highlight", "grabber_pressed"]},
    "VScrollBar": {"styles": ["scroll", "scroll_focus", "grabber", "grabber_highlight", "grabber_pressed"]},
    "TabContainer": {"styles": ["tab_selected", "tab_unselected", "tab_hovered", "tab_disabled", "tab_focus", "panel"]},
    "TabBar": {"styles": ["tab_selected", "tab_unselected", "tab_hovered", "tab_disabled", "tab_focus"]},
    "LineEdit": {"styles": ["normal", "focus", "read_only"], "colors": ["caret_color", "selection_color"]},
    "SpinBox": {"icons": ["updown"]},
    "TooltipPanel": {"styles": ["panel"]},
    "TooltipLabel": {"colors": ["font_color"]},
    "ItemList": {"styles": ["panel", "focus", "selected", "selected_focus", "hovered", "cursor", "cursor_unfocused",
                            "hovered_selected", "hovered_selected_focus"]},
    "ProgressBar": {"styles": ["background", "fill"]},
    "Label": {"colors": ["font_color"]},
    "Panel": {"styles": ["panel"]},
    "PanelContainer": {"styles": ["panel"]},
    "HSeparator": {"styles": ["separator"]},
    "VSeparator": {"styles": ["separator"]},
}
BUTTONISH = ("Button", "CheckBox", "CheckButton", "OptionButton")
FONT_STATES = {   # font colour items per type -> colour name in colours()
    "Button": {"font_color": "text", "font_hover_color": "text_hover", "font_pressed_color": "text_pressed",
               "font_hover_pressed_color": "text_hover", "font_focus_color": "focus", "font_disabled_color": "text_disabled",
               "font_outline_color": "outline"},
    "LineEdit": {"font_color": "text", "font_selected_color": "text_hover", "font_uneditable_color": "text_disabled",
                 "font_placeholder_color": "text_dim", "font_outline_color": "outline", "clear_button_color": "text",
                 "clear_button_color_pressed": "focus"},
    "TabBar": {"font_selected_color": "text_hover", "font_hovered_color": "text", "font_unselected_color": "text_dim",
               "font_disabled_color": "text_disabled", "font_outline_color": "outline"},
    "PopupMenu": {"font_color": "text", "font_hover_color": "text_hover", "font_disabled_color": "text_disabled",
                  "font_separator_color": "text_dim", "font_accelerator_color": "text_dim", "font_outline_color": "outline"},
    "ItemList": {"font_color": "text", "font_hovered_color": "text_hover", "font_selected_color": "text_hover",
                 "font_hovered_selected_color": "text_hover", "font_outline_color": "outline"},
    "Label": {"font_color": "text", "font_outline_color": "outline"},
    "TooltipLabel": {"font_color": "text", "font_outline_color": "outline"},
    "ProgressBar": {"font_color": "text", "font_outline_color": "outline"},
}


def theme(path, res, tex, c, scale, font_res=None, font_size=None):
    """Theme .tres over the textures in res (a res:// folder). tex: {name: (rgba, margin)} at 1x."""
    w = _Tres()
    s = scale

    def sb(name, content=None, expand=0):
        """StyleBoxTexture for texture `name`: nine-patch margins from the drawing, content margins (1x px, per
        side l, t, r, b) for the text inside, expand (1x px) to draw outside the control (the focus ring)."""
        a, m = tex[name]
        cm = content if content is not None else (m + 2, m, m + 2, m)
        key = f"{name}_{'_'.join(str(v) for v in cm)}_{expand}"
        lines = [f"texture = {w.ext_res('Texture2D', f'{res}/{name}.png')}"]
        lines += [f"texture_margin_{side} = {m * s}.0" for side in ("left", "top", "right", "bottom")]
        lines += [f"content_margin_{side} = {v * s}.0" for side, v in zip(("left", "top", "right", "bottom"), cm)]
        if expand:
            lines += [f"expand_margin_{side} = {expand * s}.0" for side in ("left", "top", "right", "bottom")]
        return w.sub_res(key, "StyleBoxTexture", lines)

    def icon(name):
        return w.ext_res("Texture2D", f"{res}/{name}.png")

    def empty(pad):
        return w.sub_res(f"empty_{pad}", "StyleBoxEmpty",
                         [f"content_margin_{side} = {pad * s}.0" for side in ("left", "top", "right", "bottom")])

    def line(vertical):
        return w.sub_res(f"line_{int(vertical)}", "StyleBoxLine",
                         [f"color = {_col(c['metal'])}", f"thickness = {s}", f"vertical = {'true' if vertical else 'false'}"])

    focus = sb("focus", (0, 0, 0, 0), expand=2)
    if font_res:
        w.props.append(f"default_font = {w.ext_res('FontFile', font_res)}")
        if font_size:
            w.props.append(f"default_font_size = {int(font_size)}")
    # buttons: Button and OptionButton use the button skin; CheckBox / CheckButton rows are flat until hovered
    bm = tex["button_normal"][1]
    # text starts right inside the frame rings: the shell's settings tab row (six tabs, 40 % longer pseudo-locale
    # text) has to fit 640 px, and one more pixel of padding per side overflowed it
    pad = {st: (bm, bm, bm, bm) for st in ("normal", "hover", "disabled")}
    pad["pressed"] = (bm, bm + 1, bm, bm - 1)           # the label sinks one pixel when pressed
    for typ in ("Button", "OptionButton"):
        for st in ("normal", "hover", "pressed", "disabled"):
            w.set(typ, "styles", st, sb(f"button_{st}", pad[st]))
        w.set(typ, "styles", "focus", focus)
    w.set("Button", "styles", "hover_pressed", sb("button_pressed", pad["pressed"]))
    for st in ("normal", "hover", "pressed", "disabled"):
        w.set("OptionButton", "styles", f"{st}_mirrored", sb(f"button_{st}", pad[st]))
    w.set("OptionButton", "icons", "arrow", icon("arrow"))
    w.set("OptionButton", "constants", "arrow_margin", 3 * s)
    for typ in ("CheckBox", "CheckButton"):
        w.set(typ, "styles", "normal", empty(2))
        w.set(typ, "styles", "pressed", empty(2))
        w.set(typ, "styles", "disabled", empty(2))
        w.set(typ, "styles", "hover", sb("row_hover", (2, 2, 2, 2)))
        w.set(typ, "styles", "hover_pressed", sb("row_hover", (2, 2, 2, 2)))
        w.set(typ, "styles", "focus", focus)
        w.set(typ, "constants", "h_separation", 3 * s)
    for k in ("checked", "unchecked"):
        for typ in ("CheckBox", "PopupMenu"):
            w.set(typ, "icons", k, icon(f"check_{k}"))
            w.set(typ, "icons", f"{k}_disabled", icon(f"check_{k}_disabled"))
            w.set(typ, "icons", f"radio_{k}", icon(f"radio_{k}"))
            w.set(typ, "icons", f"radio_{k}_disabled", icon(f"radio_{k}_disabled"))
        w.set("CheckButton", "icons", k, icon(f"switch_{k}"))
        w.set("CheckButton", "icons", f"{k}_disabled", icon(f"switch_{k}_disabled"))
        w.set("CheckButton", "icons", f"{k}_mirrored", icon(f"switch_{k}_mirrored"))
        w.set("CheckButton", "icons", f"{k}_disabled_mirrored", icon(f"switch_{k}_disabled_mirrored"))
    for typ in BUTTONISH:
        for item, cname in FONT_STATES["Button"].items():
            w.set(typ, "colors", item, _col(c[cname]))
    # sliders: a sunken track, the filled part in metal (focus-tinted when highlighted), a raised grabber
    for typ, v in (("HSlider", ""), ("VSlider", "v")):
        w.set(typ, "styles", "slider", sb("track", (2, 2, 2, 2)))
        w.set(typ, "styles", "grabber_area", sb("grabber_area", (2, 2, 2, 2)))
        w.set(typ, "styles", "grabber_area_highlight", sb("grabber_area_hl", (2, 2, 2, 2)))
        w.set(typ, "icons", "grabber", icon(f"{v}grabber"))
        w.set(typ, "icons", "grabber_highlight", icon(f"{v}grabber_hl"))
        w.set(typ, "icons", "grabber_disabled", icon(f"{v}grabber_disabled"))
        w.set(typ, "icons", "tick", icon("tick"))
    # popup menu
    w.set("PopupMenu", "styles", "panel", sb("popup", (tex["popup"][1] + 1,) * 4))
    w.set("PopupMenu", "styles", "hover", sb("row_hover", (2, 1, 2, 1)))
    for k in ("separator", "labeled_separator_left", "labeled_separator_right"):
        w.set("PopupMenu", "styles", k, line(False))
    w.set("PopupMenu", "icons", "submenu", icon("submenu"))
    w.set("PopupMenu", "icons", "submenu_mirrored", icon("submenu_mirrored"))
    w.set("PopupMenu", "constants", "v_separation", 2 * s)
    for item, cname in FONT_STATES["PopupMenu"].items():
        w.set("PopupMenu", "colors", item, _col(c[cname]))
    # scroll bars: the track gets a focus-coloured rim when focused; the grabber lights on hover, darkens pressed
    for typ in ("HScrollBar", "VScrollBar"):
        w.set(typ, "styles", "scroll", sb("scroll", (3, 3, 3, 3)))
        w.set(typ, "styles", "scroll_focus", sb("scroll_focus", (3, 3, 3, 3)))
        w.set(typ, "styles", "grabber", sb("scroll_grabber", (3, 3, 3, 3)))
        w.set(typ, "styles", "grabber_highlight", sb("scroll_grabber_hl", (3, 3, 3, 3)))
        w.set(typ, "styles", "grabber_pressed", sb("scroll_grabber_pressed", (3, 3, 3, 3)))
    # tabs
    for typ in ("TabContainer", "TabBar"):
        for st in ("selected", "unselected", "hovered", "disabled"):
            m = tex[f"tab_{st}"][1]
            w.set(typ, "styles", f"tab_{st}", sb(f"tab_{st}", (m + 1, m + (0 if st == "selected" else 2), m + 1, 1)))
        w.set(typ, "styles", "tab_focus", focus)
        for item, cname in FONT_STATES["TabBar"].items():
            w.set(typ, "colors", item, _col(c[cname]))
    w.set("TabContainer", "styles", "panel", sb("panel", (tex["panel"][1],) * 4))
    # line edit / spin box
    w.set("LineEdit", "styles", "normal", sb("well", (4, 3, 4, 3)))
    w.set("LineEdit", "styles", "focus", focus)
    w.set("LineEdit", "styles", "read_only", sb("well_ro", (4, 3, 4, 3)))
    for item, cname in FONT_STATES["LineEdit"].items():
        w.set("LineEdit", "colors", item, _col(c[cname]))
    w.set("LineEdit", "colors", "caret_color", _col(c["focus"]))
    w.set("LineEdit", "colors", "selection_color", _col(c["metal"], 0.6))
    w.set("LineEdit", "constants", "caret_width", s)
    w.set("SpinBox", "icons", "updown", icon("updown"))
    # tooltip
    w.set("TooltipPanel", "styles", "panel", sb("tooltip", (tex["tooltip"][1] + 1,) * 4))
    for item, cname in FONT_STATES["TooltipLabel"].items():
        w.set("TooltipLabel", "colors", item, _col(c[cname]))
    # item list
    w.set("ItemList", "styles", "panel", sb("well", (4, 4, 4, 4)))
    w.set("ItemList", "styles", "focus", focus)
    w.set("ItemList", "styles", "hovered", sb("row_hover", (2, 1, 2, 1)))
    w.set("ItemList", "styles", "selected", sb("row_selected", (2, 1, 2, 1)))
    w.set("ItemList", "styles", "selected_focus", sb("row_selected_focus", (2, 1, 2, 1)))
    w.set("ItemList", "styles", "hovered_selected", sb("row_selected", (2, 1, 2, 1)))
    w.set("ItemList", "styles", "hovered_selected_focus", sb("row_selected_focus", (2, 1, 2, 1)))
    w.set("ItemList", "styles", "cursor", sb("cursor", (2, 1, 2, 1)))
    w.set("ItemList", "styles", "cursor_unfocused", sb("cursor_unfocused", (2, 1, 2, 1)))
    for item, cname in FONT_STATES["ItemList"].items():
        w.set("ItemList", "colors", item, _col(c[cname]))
    # progress bar, labels, panels, separators
    w.set("ProgressBar", "styles", "background", sb("track", (2, 2, 2, 2)))
    w.set("ProgressBar", "styles", "fill", sb("progress_fill", (2, 2, 2, 2)))
    for typ in ("ProgressBar", "Label"):
        for item, cname in FONT_STATES[typ].items():
            w.set(typ, "colors", item, _col(c[cname]))
    for typ in ("Panel", "PanelContainer"):
        w.set(typ, "styles", "panel", sb("panel", (tex["panel"][1],) * 4))
    w.set("HSeparator", "styles", "separator", line(False))
    w.set("VSeparator", "styles", "separator", line(True))
    w.set("HSeparator", "constants", "separation", 4 * s)
    w.set("VSeparator", "constants", "separation", 4 * s)
    return godot._write(path, w.text())


def parse_theme(text):
    """{type: {kind: {item: value}}} from a Theme .tres (the [resource] section), for tests and reports."""
    out = {}
    body = text.split("\n[resource]\n", 1)[-1]
    for line in body.splitlines():
        m = re.match(r"^(\w+)/(\w+)/(\w+) = (.+)$", line)
        if m:
            out.setdefault(m.group(1), {}).setdefault(m.group(2), {})[m.group(3)] = m.group(4)
    return out


# ---- preview scene and its focus walk --------------------------------------------------------------------------------
# (node name, Godot type, extra property lines); the order is the focus order, top to bottom. WALK: the controls a
# ui_down / ui_up walk passes through. The ones after it take ui_up / ui_down themselves (a vertical slider moves,
# a list changes its row, a vertical scroll bar scrolls), so they sit at the end of the chain. Scroll bars are not
# focusable by default in Godot; the preview turns focus on so their scroll_focus style shows.
PREVIEW = [
    ("Start", "Button", ['text = "New Game"', 'tooltip_text = "Begin a new game"']),
    ("Sound", "CheckBox", ['text = "Sound"', "button_pressed = true"]),
    ("Easy", "CheckBox", ['text = "Easy"', 'button_group = SubResource("ButtonGroup_radio")', "button_pressed = true"]),
    ("Hard", "CheckBox", ['text = "Hard"', 'button_group = SubResource("ButtonGroup_radio")']),
    ("Vsync", "CheckButton", ['text = "Vsync"', "button_pressed = true"]),
    ("Volume", "HSlider", ["custom_minimum_size = Vector2(160, 0)", "value = 60.0", "tick_count = 5",
                           "ticks_on_borders = true"]),
    ("Quality", "OptionButton", ["selected = 1", "item_count = 3", 'popup/item_0/text = "Low"', "popup/item_0/id = 0",
                                 'popup/item_1/text = "Medium"', "popup/item_1/id = 1", 'popup/item_2/text = "High"',
                                 "popup/item_2/id = 2"]),
    ("Hero", "LineEdit", ['text = "Knight"', 'placeholder_text = "Name"']),
    ("Tabs", "TabBar", ["tab_count = 3", 'tab_0/title = "Video"', 'tab_1/title = "Audio"', 'tab_2/title = "Keys"',
                        "tab_2/disabled = true"]),
    ("Pan", "HScrollBar", ["custom_minimum_size = Vector2(160, 0)", "focus_mode = 2", "max_value = 100.0",
                           "page = 25.0", "value = 30.0"]),
    ("Back", "Button", ['text = "Back"']),
    ("Saves", "ItemList", ["custom_minimum_size = Vector2(160, 64)", "item_count = 3", 'item_0/text = "Castle"',
                           'item_1/text = "Bakery"', 'item_2/text = "Iron mine"']),
    ("Gain", "VSlider", ["custom_minimum_size = Vector2(0, 64)", "value = 40.0"]),
    ("Scroll", "VScrollBar", ["custom_minimum_size = Vector2(0, 64)", "focus_mode = 2", "max_value = 100.0",
                              "page = 25.0"]),
]
WALK = 11   # Start .. Back
EXTRA = [   # shown, not in the focus chain
    ("Title", "Label", ['text = "Settings"']),
    ("Locked", "Button", ['text = "Locked"', "disabled = true", "focus_mode = 0"]),
    ("Loading", "ProgressBar", ["custom_minimum_size = Vector2(160, 0)", "value = 65.0"]),
    ("Line", "HSeparator", []),
    ("Copies", "SpinBox", ["value = 3.0", "max_value = 9.0"]),
    ("Readonly", "LineEdit", ['text = "Read only"', "editable = false", "focus_mode = 0"]),
]


def preview_scene(path, theme_res, glyph_res):
    """Every Control under the theme. Chain controls are siblings in one column (focus neighbours ../Next), the
    rest sit in a second column with a TabContainer, a Panel, a VSeparator, a hidden PopupMenu and a row of glyphs.
    Root metadata dotwork_focus_walk lists the walk (paths from the root) for verify."""
    lines = []
    ext = [f'[ext_resource type="Theme" path="{theme_res}" id="1_theme"]']
    for i, g in enumerate(glyph_res):
        ext.append(f'[ext_resource type="Texture2D" path="{g}" id="{i + 2}_glyph"]')
    walk = [f"Cols/Chain/{n}" for n, _, _ in PREVIEW[:WALK]]
    lines += [f'[gd_scene load_steps={len(ext) + 2} format=3]', ""] + ext + ["",
              '[sub_resource type="ButtonGroup" id="ButtonGroup_radio"]', "",
              '[node name="UikitPreview" type="PanelContainer"]', "offset_right = 640.0", "offset_bottom = 400.0",
              'theme = ExtResource("1_theme")',
              "metadata/dotwork_focus_walk = PackedStringArray(" + ", ".join(f'"{p}"' for p in walk) + ")", "",
              '[node name="Cols" type="HBoxContainer" parent="."]', "layout_mode = 2", "",
              '[node name="Chain" type="VBoxContainer" parent="Cols"]', "layout_mode = 2", "",
              '[node name="Title" type="Label" parent="Cols/Chain"]', "layout_mode = 2", 'text = "Settings"', ""]
    names = [n for n, _, _ in PREVIEW]
    for i, (n, typ, props) in enumerate(PREVIEW):
        prev_n, next_n = names[i - 1] if i else None, names[i + 1] if i + 1 < len(names) else None
        lines += [f'[node name="{n}" type="{typ}" parent="Cols/Chain"]', "layout_mode = 2"]
        if prev_n:
            lines += [f'focus_neighbor_top = NodePath("../{prev_n}")', f'focus_previous = NodePath("../{prev_n}")']
        if next_n:
            lines += [f'focus_neighbor_bottom = NodePath("../{next_n}")', f'focus_next = NodePath("../{next_n}")']
        lines += props + [""]
    lines += ['[node name="Side" type="VBoxContainer" parent="Cols"]', "layout_mode = 2", ""]
    for n, typ, props in EXTRA[1:]:
        lines += [f'[node name="{n}" type="{typ}" parent="Cols/Side"]', "layout_mode = 2"] + props + [""]
    lines += ['[node name="Pages" type="TabContainer" parent="Cols/Side"]', "layout_mode = 2",
              "custom_minimum_size = Vector2(160, 56)", "tab_focus_mode = 0", "current_tab = 0", "",
              '[node name="Bread" type="Label" parent="Cols/Side/Pages"]', "layout_mode = 2", 'text = "A bakery"',
              "metadata/_tab_index = 0", "",
              '[node name="Iron" type="Label" parent="Cols/Side/Pages"]', "visible = false", "layout_mode = 2",
              'text = "An iron mine"', "metadata/_tab_index = 1", "",
              '[node name="Row" type="HBoxContainer" parent="Cols/Side"]', "layout_mode = 2", "",
              '[node name="Plain" type="Panel" parent="Cols/Side/Row"]', "layout_mode = 2",
              "custom_minimum_size = Vector2(48, 32)", "",
              '[node name="Bar" type="VSeparator" parent="Cols/Side/Row"]', "layout_mode = 2", ""]
    for i in range(len(glyph_res)):
        lines += [f'[node name="Glyph{i}" type="TextureRect" parent="Cols/Side/Row"]', "layout_mode = 2",
                  "texture_filter = 1", f'texture = ExtResource("{i + 2}_glyph")', "stretch_mode = 3", ""]
    lines += ['[node name="Menu" type="PopupMenu" parent="."]', "item_count = 4", 'item_0/text = "Bread"',
              "item_0/id = 0", 'item_1/text = "Iron"', "item_1/checkable = 1", "item_1/checked = true", "item_1/id = 1",
              "item_2/id = 2", "item_2/separator = true", 'item_3/text = "Castle"', "item_3/checkable = 2",
              "item_3/id = 3", ""]
    return godot._write(path, "\n".join(lines))


# Headless check (verify runs it on every uikit preview scene): the scene's Theme must hold every REQUIRED item
# (asked through Godot's own Theme API), then the focus walk: load the scene into a running SceneTree, focus the first
# control of dotwork_focus_walk, send ui_down through Input.parse_input_event (InputEventAction, press then release)
# until the last one, then ui_up back to the first, checking gui_get_focus_owner() after every press.
FOCUS_CHECK = r'''extends SceneTree
# Dotwork UI kit check: argument after "--" is the preview scene's res:// path. Prints UIKIT_THEME, UIKIT_FOCUS lines
# and UIKIT_FOCUS_RESULT PASS / FAIL; exit 0 on PASS.
var required = __REQUIRED__
var walk = []
var plan = []
var frame = 0
var step = 0
var phase = 0
var bad = 0

func _initialize():
	var ps = load(OS.get_cmdline_user_args()[0])
	if ps == null:
		print("UIKIT_FOCUS_RESULT FAIL cannot load ", OS.get_cmdline_user_args()[0])
		quit(1)
		return
	var scene = ps.instantiate()
	root.add_child(scene)
	var th = scene.theme
	var missing = []
	for typ in required:
		for kind in required[typ]:
			for item in required[typ][kind]:
				var has = false
				if kind == "styles":
					has = th.has_stylebox(item, typ)
				elif kind == "icons":
					has = th.has_icon(item, typ)
				elif kind == "colors":
					has = th.has_color(item, typ)
				if not has:
					missing.append(typ + "/" + kind + "/" + item)
	print("UIKIT_THEME types=", required.size(), " missing=", missing.size(), " ", ", ".join(missing))
	bad += missing.size()
	for p in scene.get_meta("dotwork_focus_walk", PackedStringArray()):
		walk.append(scene.get_node(NodePath(p)))
	for i in range(1, walk.size()):
		plan.append(["ui_down", i])
	for i in range(walk.size() - 2, -1, -1):
		plan.append(["ui_up", i])

func _send(action, pressed):
	var ev = InputEventAction.new()
	ev.action = action
	ev.pressed = pressed
	Input.parse_input_event(ev)

func _focused_name():
	var o = root.gui_get_focus_owner()
	return o.name if o != null else "<none>"

func _process(_delta):
	frame += 1
	if walk.size() < 2:
		print("UIKIT_FOCUS_RESULT FAIL the scene lists fewer than two controls in dotwork_focus_walk")
		quit(1)
		return true
	if frame == 2:
		walk[0].grab_focus()
	elif frame == 3:
		var ok = root.gui_get_focus_owner() == walk[0]
		print("UIKIT_FOCUS start ", _focused_name(), " ", "ok" if ok else "BAD")
		if not ok:
			bad += 1
	elif frame > 3:
		if step >= plan.size():
			print("UIKIT_FOCUS_RESULT ", "PASS" if bad == 0 else "FAIL", " steps=", plan.size(), " bad=", bad)
			quit(0 if bad == 0 else 1)
			return true
		var act = plan[step][0]
		if phase == 0:
			_send(act, true)
		elif phase == 1:
			_send(act, false)
		else:
			var want = walk[plan[step][1]]
			var ok = root.gui_get_focus_owner() == want
			print("UIKIT_FOCUS ", act, " -> ", _focused_name(), " (want ", want.name, ") ", "ok" if ok else "BAD")
			if not ok:
				bad += 1
			step += 1
		phase = (phase + 1) % 3
	return false
'''


def focus_check(settings, scene_res):
    """(ok, UIKIT_THEME / UIKIT_FOCUS lines) of the theme check and focus walk over one preview scene, in the game's
    Godot."""
    import godotrun
    gd = FOCUS_CHECK.replace("__REQUIRED__", json.dumps(REQUIRED))
    code, out = godotrun.run_script(settings, "dotwork_uikit_focus", gd, (scene_res,), timeout=300)
    lines = [l for l in out.splitlines() if l.startswith(("UIKIT_FOCUS", "UIKIT_THEME"))]
    ok = code == 0 and any(l.startswith("UIKIT_FOCUS_RESULT PASS") for l in lines)
    return ok, lines


# ---- review sheet ----------------------------------------------------------------------------------------------------
def ninepatch(a, m, w, h):
    """Stretch a 1x nine-patch (margin m on every side) to w x h; the middle bands repeat their centre pixels."""
    H, W = a.shape[:2]
    ys = [min(y, m) if y < m else (H - (h - y) if y >= h - m else m + (y - m) % max(1, H - 2 * m)) for y in range(h)]
    xs = [min(x, m) if x < m else (W - (w - x) if x >= w - m else m + (x - m) % max(1, W - 2 * m)) for x in range(w)]
    return a[np.ix_(ys, xs)]


def _over(dst, src, y, x):
    h, w = src.shape[:2]
    region = dst[y:y + h, x:x + w]
    al = src[..., 3:4].astype(np.float32) / 255
    region[..., :3] = (src[..., :3] * al + region[..., :3] * (1 - al)).astype(np.uint8)
    region[..., 3] = np.maximum(region[..., 3], src[..., 3])


def text_img(text, col):
    """A line of text in the glyph font at 1x (full 9-row cells, so labels share a baseline)."""
    meta, glyphs = font()
    gap = np.zeros((meta["height"], meta["spacing"]), bool)
    blank = np.zeros((meta["height"], meta["space"]), bool)
    parts = []
    for ch in text:
        parts += [glyphs.get(ch, blank) if ch != " " else blank, gap]
    m = np.concatenate(parts, axis=1) if parts else np.zeros((meta["height"], 1), bool)
    a = _canvas(*m.shape)
    _put(a, m, col)
    return a


def _cell(w=48, h=22):
    a = _canvas(h, w)
    a[..., :3] = (40, 44, 52)
    a[..., 3] = 255
    return a


def _box(cell, tex, name, x, y, w, h, expand=0):
    a, m = tex[name]
    _over(cell, ninepatch(a, m, w + 2 * expand, h + 2 * expand), y - expand, x - expand)


def _label(cell, text, col, x, y, w, h):
    """Text centred in a rect (the font's caps sit on rows 0..6 of its 9-row cell)."""
    t = text_img(text, col)
    _over(cell, t, y + (h - 7) // 2, x + (w - t.shape[1]) // 2)


def state_rows(tex, c):
    """[(control, [(state, 1x image)])]: every control in every state, composed the way Godot draws it."""
    rows = []
    bx = (6, 3, 36, 16)

    def button(state, ring=False, arrow=False, col="text"):
        e = _cell()
        _box(e, tex, f"button_{state}", *bx)
        _label(e, "OK", c[col], bx[0], bx[1] + (1 if state == "pressed" else 0), bx[2] - (8 if arrow else 0), bx[3])
        if arrow:
            _over(e, tex["arrow"][0], 9, 33)
        if ring:
            _box(e, tex, "focus", *bx, expand=2)
        return e

    rows.append(("Button", [("normal", button("normal")), ("hover", button("hover", col="text_hover")),
                            ("pressed", button("pressed", col="text_pressed")),
                            ("disabled", button("disabled", col="text_disabled")),
                            ("focus", button("normal", True, col="focus")),
                            ("hover+focus", button("hover", True, col="text_hover"))]))
    rows.append(("OptionButton", [("normal", button("normal", arrow=True)),
                                  ("hover", button("hover", arrow=True, col="text_hover")),
                                  ("focus", button("normal", True, True, col="focus"))]))

    def check(icon, hover=False, ring=False, col="text"):
        e = _cell()
        wide = tex[icon][0].shape[1] > 10
        if hover:
            _box(e, tex, "row_hover", 4, 4, 40, 14)
        _over(e, tex[icon][0], 6, 6)
        _label(e, "On", c[col], 24 if wide else 18, 4, 20, 14)
        if ring:
            _box(e, tex, "focus", 4, 4, 40, 14, expand=2)
        return e

    rows.append(("CheckBox", [("off", check("check_unchecked")), ("on", check("check_checked")),
                              ("hover", check("check_checked", hover=True, col="text_hover")),
                              ("disabled", check("check_checked_disabled", col="text_disabled")),
                              ("focus", check("check_checked", ring=True, col="focus")),
                              ("radio off", check("radio_unchecked")), ("radio on", check("radio_checked")),
                              ("radio dis.", check("radio_checked_disabled", col="text_disabled"))]))
    rows.append(("CheckButton", [("off", check("switch_unchecked")), ("on", check("switch_checked")),
                                 ("hover", check("switch_checked", hover=True, col="text_hover")),
                                 ("disabled", check("switch_checked_disabled", col="text_disabled")),
                                 ("focus", check("switch_checked", ring=True, col="focus")),
                                 ("mirrored", check("switch_checked_mirrored"))]))

    def tabcell(state, ring=False):
        e = _cell()
        _box(e, tex, "panel", 2, 16, 44, 6)
        _box(e, tex, f"tab_{state}", 8, 4, 32, 13)
        col = {"selected": "text_hover", "hovered": "text", "disabled": "text_disabled"}.get(state, "text_dim")
        _label(e, "Tab", c[col], 8, 5 if state == "selected" else 7, 32, 12)
        if ring:
            _box(e, tex, "focus", 8, 4, 32, 13, expand=2)
        return e

    rows.append(("Tabs", [("selected", tabcell("selected")), ("unselected", tabcell("unselected")),
                          ("hovered", tabcell("hovered")), ("disabled", tabcell("disabled")),
                          ("focus", tabcell("selected", True))]))

    def slider(hl=False, dis=False):
        e = _cell()
        _box(e, tex, "track", 4, 9, 40, 4)
        _box(e, tex, "grabber_area_hl" if hl else "grabber_area", 4, 9, 24, 4)
        g = tex["grabber_disabled" if dis else ("grabber_hl" if hl else "grabber")][0]
        _over(e, g, 6, 25)
        return e

    rows.append(("HSlider", [("normal", slider()), ("hover = focus", slider(True)), ("disabled", slider(dis=True))]))

    def scroll(grab="scroll_grabber", track="scroll"):
        e = _cell()
        _box(e, tex, track, 4, 7, 40, 8)
        _box(e, tex, grab, 16, 7, 14, 8)
        return e

    rows.append(("ScrollBar", [("normal", scroll()), ("hover", scroll("scroll_grabber_hl")),
                               ("pressed", scroll("scroll_grabber_pressed")), ("focus", scroll(track="scroll_focus"))]))

    def field(name, ring=False, col="text"):
        e = _cell()
        _box(e, tex, name, 4, 5, 40, 12)
        _label(e, "Knight", c[col], 4, 5, 40, 12)
        if ring:
            _box(e, tex, "focus", 4, 5, 40, 12, expand=2)
        return e

    rows.append(("LineEdit", [("normal", field("well")), ("focus", field("well", True)),
                              ("read only", field("well_ro", col="text_disabled"))]))

    def items(focus):
        e = _cell(56, 40)
        _box(e, tex, "well", 3, 3, 50, 34)
        _box(e, tex, "row_hover", 5, 6, 46, 9)
        _box(e, tex, "row_selected_focus" if focus else "row_selected", 5, 16, 46, 9)
        if focus:
            _box(e, tex, "cursor", 5, 16, 46, 9)
            _box(e, tex, "focus", 3, 3, 50, 34, expand=2)
        for i, (t, col) in enumerate((("Castle", "text_hover"), ("Bakery", "text_hover"), ("Iron", "text"))):
            _label(e, t, c[col], 5, 6 + 10 * i, 46, 9)
        return e

    rows.append(("ItemList", [("hover, selected", items(False)), ("focused", items(True))]))

    def progress(f):
        e = _cell()
        _box(e, tex, "track", 4, 7, 40, 8)
        _box(e, tex, "progress_fill", 4, 7, max(6, int(40 * f)), 8)
        return e

    def panels(kind):
        e = _cell(56, 40)
        if kind == "popup":
            _box(e, tex, "popup", 2, 2, 52, 36)
            _box(e, tex, "row_hover", 6, 7, 44, 9)
            e[22, 8:48, :3] = c["metal"]
            _label(e, "Bread", c["text_hover"], 6, 7, 44, 9)
            _label(e, "Iron", c["text"], 6, 25, 44, 9)
        elif kind == "tooltip":
            _box(e, tex, "tooltip", 4, 10, 48, 18)
            _label(e, "Tip", c["text"], 4, 10, 48, 18)
        else:
            _box(e, tex, "panel", 2, 2, 52, 36)
        return e

    rows.append(("Panels", [("30 %", progress(0.3)), ("75 %", progress(0.75)), ("panel", panels("panel")),
                                      ("popup", panels("popup")), ("tooltip", panels("tooltip"))]))
    return rows


def review(path, tex, c, glyphs, cursors):
    """Every control in every state (labelled), then every glyph with its name and the cursors, on the dark review
    background, at 3x."""
    blocks = []                                          # one line each: [(x, image)]
    for title, cells in state_rows(tex, c):
        line, x = [(0, text_img(title, (200, 204, 216)))], 84
        for state, img in cells:
            lab = text_img(state, (150, 156, 172))
            col = _canvas(img.shape[0] + 10, max(img.shape[1], lab.shape[1]))
            _over(col, lab, 0, 0)
            _over(col, img, 10, 0)
            line.append((x, col))
            x += col.shape[1] + 4
        blocks.append(line)
    names = sorted(glyphs)
    for i in range(0, len(names), 6):
        line = []
        for k, n in enumerate(names[i:i + 6]):
            g, lab = glyphs[n], text_img(n, (150, 156, 172))
            col = _canvas(28, max(g.shape[1], lab.shape[1]))
            _over(col, g, 0, 0)
            _over(col, lab, 18, 0)
            line.append((k * 92, col))
        blocks.append(line)
    blocks.append([(0, cursors[0]), (24, cursors[1])])
    W = max(x + im.shape[1] for line in blocks for x, im in line) + 12
    H = sum(max(im.shape[0] for _, im in line) + 6 for line in blocks) + 8
    sheet = np.zeros((H, W, 4), np.uint8)
    sheet[..., :3] = (58, 58, 68)
    sheet[..., 3] = 255
    y = 6
    for line in blocks:
        for x, im in line:
            _over(sheet, im, y, x + 6)
        y += max(im.shape[0] for _, im in line) + 6
    img = Image.fromarray(sheet).resize((W * 3, H * 3), Image.NEAREST)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    return path


# ---- run -------------------------------------------------------------------------------------------------------------
def _scaled(a, s):
    return np.kron(a, np.ones((s, s, 1), np.uint8))


def _font_res(e, name):
    """The "font" key: a .fnt / .ttf in the game -> (res:// path, size for default_font_size or None)."""
    fp = core.project_path(e["font"])
    if not os.path.isfile(fp):
        raise core.ToolError(f"uikit {name}: font {e['font']!r} not found (make it with the fonts lane first)")
    size = None
    if fp.lower().endswith(".fnt"):
        with open(fp, encoding="utf-8", errors="replace") as f:
            m = re.search(r"\bsize=(\d+)", f.readline())
        size = int(m.group(1)) if m else None
    return "res://" + os.path.relpath(fp, core.PROJECT).replace(os.sep, "/"), size


def run(entries, pack, man, conf):
    ui = core.asset(conf, "ui")
    gdir = os.path.join(ui, "glyphs")
    ui_res = f'{conf["fixed"]["res_root"].rstrip("/")}/ui'
    extra, first_scale = [], None
    # check every entry before anything is written, so a bad spec changes nothing
    plans = []
    for e in entries:
        name = core.snake(e["name"])
        st = style_of(e, name)
        try:
            scale = int(e.get("scale", 2))
        except (TypeError, ValueError):
            scale = 0
        if not 1 <= scale <= 8:
            raise core.ToolError(f"uikit {name}: scale {e.get('scale')!r}: a whole number 1 to 8")
        keys = e.get("keys", [])
        if not isinstance(keys, list):
            raise core.ToolError(f"uikit {name}: \"keys\" is a list of key names")
        extra += [key_name(k, f"uikit {name}") for k in keys]
        fr = _font_res(e, name) if e.get("font") else (None, None)
        plans.append((name, st, scale, fr))
        first_scale = first_scale or scale
    for name, st, scale, (font_res, font_size) in plans:
        art = core.art(conf, "ui", "uikit", name)
        res = core.res(conf, "ui", "uikit", name)
        man.drop_dir(art)
        tex, c = textures(st)
        for tname, (a, m) in tex.items():
            p = core.save_clean(Image.fromarray(_scaled(a, scale)), os.path.join(art, f"{tname}.png"))
            man.add(p, "ui_texture", style=name, scale=scale, patch_margin=None if m is None else m * scale,
                    workflow="Dotwork UI kit (drawn in code)")
        th = theme(os.path.join(ui, f"theme_{name}.tres"), res, tex, c, scale, font_res, font_size)
        man.add(th, "theme", types=sorted(REQUIRED), font=font_res,
                note="the kit's shell loads the first assets/ui/theme_*.tres; default texture filter Nearest")
        shown = ["key_enter", "key_escape", "xbox_a", "ps_cross", "pad_south", "pad_dpad_up", "mouse_left"]
        scn = preview_scene(os.path.join(ui, f"uikit_preview_{name}.tscn"), f"{ui_res}/theme_{name}.tres",
                            [f"{ui_res}/glyphs/{g}.png" for g in shown])
        man.add(scn, "scene", node="PanelContainer", note="UI kit preview; verify walks its focus chain",
                focus_walk=[n for n, _, _ in PREVIEW[:WALK]])
        core.log(f"uikit {name}: theme with {len(REQUIRED)} types, {len(tex)} textures at x{scale}")
    # glyphs and cursors are style-free and shared by every theme of the game: drawn once per run
    man.drop_owned(gdir)
    names = glyph_names(sorted(set(extra)))
    glyphs, index = {}, {}
    for n in names:
        a = draw_glyph(n)
        glyphs[n] = a
        index[n] = {"w": int(a.shape[1]), "h": int(a.shape[0])}
        p = core.save_clean(Image.fromarray(a), os.path.join(gdir, f"{n}.png"))
        man.add(p, "ui_glyph", glyph=n, size=[int(a.shape[1]), int(a.shape[0])], workflow="Dotwork UI kit (drawn in code)")
    gj = core.write_text(os.path.join(gdir, "glyphs.json"), json.dumps(index, indent=1, sort_keys=True) + "\n")
    man.add(gj, "ui_glyph_index", glyphs=len(index), note="{name: {w, h}} at 1x; the shell scales by whole numbers")
    cur_imgs = []
    for k, a in (("pointer", cursor_pointer()), ("select", cursor_select())):
        hot = hotspot(a) if k == "select" else (0, 0)
        p = core.save_clean(Image.fromarray(_scaled(a, first_scale)), os.path.join(ui, f"cursor_{k}.png"))
        man.add(p, "ui_cursor", scale=first_scale, hotspot=[hot[0] * first_scale, hot[1] * first_scale],
                note="Input.set_custom_mouse_cursor(texture, shape, hotspot) or a TextureRect beside the focused row",
                workflow="Dotwork UI kit (drawn in code)")
        cur_imgs.append(a)
    for name, st, scale, _ in plans:
        tex, c = textures(st)
        sheet = review(core.src(conf, "art", "ui", f"uikit_{name}_review.png"), tex, c, glyphs, cur_imgs)
        core.log(f"uikit {name}: review {sheet}")
    core.log(f"uikit: {len(glyphs)} prompt glyphs in {os.path.relpath(gdir, core.PROJECT)}, 2 cursors")
