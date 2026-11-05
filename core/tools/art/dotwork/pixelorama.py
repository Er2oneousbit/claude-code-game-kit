#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# pixelorama.py
# Purpose : the Pixelorama round trip, beside aseprite.py: build editable .pxo projects (one per character, effect or
#           single image; one animation tag per clip; each frame's duration from the clip's holds; the asset's own
#           colours as the project palette), and re-export hand-polished ones back to the shipped PNGs, sheets and
#           SpriteFrames (handpolish.py). The .pxo files are read and written here in Python: neither direction needs
#           Pixelorama installed.
# Usage   : dotwork.py pixelorama [--overwrite], then dotwork.py pixelorama --reexport [--clear-export-path]
# Notes   : The format is Pixelorama's own (src/Autoload/OpenSave.gd and src/Classes/Project.gd): a zip holding
#           data.json (the project) and one raw RGBA8 buffer per cel at image_data/frames/<frame>/layer_<layer>, both
#           numbered from 1. Written as pxo_version 7 (what Pixelorama 1.2.0 to 1.2.3 write; 1.2.3 and 1.2.4 open
#           it); read: 7, and 8 (Pixelorama 1.2.4, where a cel stores its own size and offset; checked against the
#           released 1.2.4 by the live exam). 7 stays the written version: 1.2.3 has no version check and reads
#           every cel as a whole canvas, so a cropped version 8 cel would load wrong there.
#           Layers composite as Pixelorama 1.2.4 does, and it has two composites: without a window (its command-line
#           export) it blends Normal layers on the CPU (DrawingAlgos.blend_layers_headless: cel, layer and animated
#           opacity; groups add nothing of their own), and Dotwork matches that byte for byte; with a window it blends
#           on the GPU (BlendLayers.gdshader), the only place blend modes, clipping masks and groups that blend their
#           own layers exist, and Dotwork follows that shader within two 8-bit steps (the GPU rounds near a half step
#           its own way). A project uses the second only when it has one of those. Layer effects (GPU shaders only)
#           and 3D layers stop the re-export when the layer is visible; a tilemap layer is drawn from its tiles and
#           cells (pxo_tiles.py), and a tilemap project under tilemaps/ becomes a TileSet and maps (pxo_tiles.py).
#           Pixelorama saves the folder you last exported to, a full path on your machine, in every .pxo
#           (export_profile.directory_path): both commands warn about it, and only --clear-export-path rewrites the
#           file to blank it (the frames and every other entry stay).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-04 with Claude (Opus 5.5, claude-opus-5-5): a character whose clips have different sizes gets one
#           canvas, each clip centred on its bottom edge; the re-export crops each back (#82)
# Updated : 2026-11-04 with Claude (Opus 5.5, claude-opus-5-5): version 8 checked against the released Pixelorama
#           1.2.4 (#67)
# Updated : 2026-11-04 with Claude (Opus 5.5, claude-opus-5-5): blend modes, clipping masks, groups that blend, and
#           animated opacity carried over; the headless composite matched exactly, the windowed one measured (#66)
# Updated : 2026-11-04 with Claude (Opus 5.5, claude-opus-5-5): tilemap layers drawn and composited; tilemap projects
#           (yours, and the game's maps and TileSets) built and re-exported through pxo_tiles.py
# ---------------------------------------------------------------------------
import glob
import io
import json
import math
import os
import re
import zipfile
import zlib
from collections import Counter

import numpy as np
from PIL import Image

import fcore as core
import handpolish

WRITE_VERSION = 7                  # pxo_version Dotwork writes (Pixelorama 1.2.0 to 1.2.3 write 7; 1.2.4 reads it)
READ_VERSIONS = (7, 8)             # 8: Pixelorama 1.2.4 (a cel's own size and offset)
MAX_SIDE = 8192                    # px: a larger canvas or cel in data.json is refused before any buffer is read
MAX_JSON = 8 * 1024 * 1024         # bytes: a larger data.json is refused (a real one is well under 1 MB)
MAX_FRAMES = 4096                  # frames, and tags
MAX_LAYERS = 256
# A .pxo is a tracked file a pull request can carry, and its zip packs zeros tightly: a 411 KB file declaring 100
# frames of 1024x1024 took 434 MB to read (2026-11-01 review). What a project would take is added up from data.json
# and refused before any buffer is read:
MAX_DECODED = 512 * 1024 * 1024    # bytes: the composited frames held at once (frames x width x height x 4), and the
#                                    frames one re-export writes
MAX_UNPACKED = 1024 * 1024 * 1024  # bytes: every cel buffer of the visible pixel layers, together
BAND_PIXELS = 1 << 20              # pixels blended at a time: a layer's float work stays near 80 MB on any canvas
MAX_CLIP = handpolish.MAX_CLIP     # frames per animation: the shipped names carry two digits (spr_<name>_<anim>_NN)
PALETTE_MAX = 256                  # colours: a frame set with more gets no project palette (the art is unchanged)
PALETTE_WIDTH = 8                  # Pixelorama's default palette grid width
DEFAULT_FPS = 6.0                  # Pixelorama's default when data.json has no fps
LAYER_PIXEL, LAYER_GROUP, LAYER_3D, LAYER_TILEMAP, LAYER_AUDIO = 0, 1, 2, 3, 4   # Global.LayerTypes
LAYER_NAMES = {LAYER_3D: "a 3D layer"}
PAINTED = (LAYER_PIXEL, LAYER_TILEMAP)   # layers with a cel image of their own (a tilemap's is drawn from its tiles)
RGBA8, INDEXED = 5, -1             # colour_mode: Godot Image.FORMAT_RGBA8; indexed mode still stores RGBA8 cels
BLEND_NORMAL, BLEND_PASS = 0, -2   # BaseLayer.BlendModes NORMAL and PASS_THROUGH (groups only)
BLEND_INTERSECT, BLEND_MATCH = 21, 22   # BaseLayer.BlendModes INTERSECTION and MATCH_COLORS
BLEND_LAST = 22                    # Pixelorama 1.2.4 has blend modes 0 (Normal) to 22 (Match colors)
TRANS_LINEAR, TRANS_CONSTANT, EASE_IN = 0, 999, 0   # a keyframe's transition and ease (Tween; AnimatableObject)
TAG_COLOURS = ("c38ce1ff", "f5a677ff", "77c341ff", "6fb7e8ff", "e8d06fff", "e86f8aff")
ZIP_TIME = (1980, 1, 1, 0, 0, 0)   # a fixed date: the same frames always give the same .pxo bytes
MIMETYPE = b"application/x-pixelorama"
SOURCE_KINDS = ("characters", "fx", "single", "tilemaps")   # the folders under the pixelorama sources (handpolish.write_back;
#                                                            tilemaps: pxo_tiles)
# An absolute path as a Godot program on Windows, Linux or macOS writes it: C:/ or C:\, /home/..., \\server\...
ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]|~(?:[\\/]|$))")


# -------------------------------------------------- writing
def _put(z, name, data):
    info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 0          # the same bytes on every system
    info.external_attr = 0
    z.writestr(info, data, compresslevel=9)


def _preview(frame):
    """preview.png as Pixelorama writes it (file managers show it): the first frame, nearest-neighbour, longest side
    256."""
    im = Image.fromarray(frame, "RGBA")
    w, h = im.size
    size = (256, max(1, int(256 * h / w))) if w > h else (max(1, int(256 * w / h)), 256)
    buf = io.BytesIO()
    im.resize(size, Image.NEAREST).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _palette(colours, name):
    """A project palette entry ({name: JSON text}, as Project.serialize writes it): colours as Godot Color text."""
    cols = [{"color": "(%.6f, %.6f, %.6f, 1.0)" % (r / 255, g / 255, b / 255), "index": i}
            for i, (r, g, b) in enumerate(colours)]
    text = json.dumps({"comment": "the asset's own colours (Dotwork)", "colors": cols, "width": PALETTE_WIDTH,
                       "height": max(1, math.ceil(len(colours) / PALETTE_WIDTH))})
    return {name: text}


def pxo_bytes(frames, durations, tags, fps, colours=None, palette_name="Dotwork"):
    """One .pxo with a single pixel layer "art". frames: H x W x 4 uint8 arrays of one size; durations: Pixelorama's
    per-frame multiplier (a frame shows duration / fps seconds); tags: [(name, first, last)] numbered from 0."""
    h, w = frames[0].shape[:2]
    data = {
        "pxo_version": WRITE_VERSION, "size_x": w, "size_y": h, "color_mode": RGBA8, "fps": float(fps),
        "layers": [{"name": "art", "visible": True, "locked": False, "blend_mode": BLEND_NORMAL,
                    "clipping_mask": False, "opacity": 1.0, "parent": -1, "type": LAYER_PIXEL,
                    "new_cels_linked": False}],
        "frames": [{"cels": [{"opacity": 1.0, "z_index": 0}], "duration": float(d)} for d in durations],
        "tags": [{"name": n, "color": TAG_COLOURS[i % len(TAG_COLOURS)], "from": a + 1, "to": b + 1}
                 for i, (n, a, b) in enumerate(tags)],
        "current_frame": 0, "current_layer": 0,
        "user_data": "Made by Dotwork. After polishing, run: dotwork.py pixelorama --reexport",
    }
    if colours:
        data["palettes"] = [_palette(colours, palette_name)]
        data["project_current_palette_name"] = palette_name
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        _put(z, "data.json", json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        _put(z, "mimetype", MIMETYPE)
        _put(z, "preview.png", _preview(frames[0]))
        for i, f in enumerate(frames):
            _put(z, f"image_data/frames/{i + 1}/layer_1", np.ascontiguousarray(f, np.uint8).tobytes())
    return buf.getvalue()


# -------------------------------------------------- reading
def _fail(rel, msg):
    raise core.ToolError(f"{rel}: {msg}")


def _number(v, rel, what, lo=None, hi=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        _fail(rel, f"{what} is not a number ({v!r})")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        _fail(rel, f"{what} {v} is outside {lo} to {hi}")
    return v


def _vec2i(v, rel, what):
    """A Godot Vector2i as Pixelorama writes it: "Vector2i(3, 4)" (var_to_str), "(3, 4)" (JSON of a Vector2i), or a
    two-number list."""
    if isinstance(v, (list, tuple)) and len(v) == 2:
        x, y = v
    else:
        m = re.fullmatch(r"\s*(?:Vector2i?)?\(\s*(-?\d+)(?:\.0+)?\s*,\s*(-?\d+)(?:\.0+)?\s*\)\s*", str(v))
        if not m:
            _fail(rel, f"{what} {v!r} is not a pair of whole numbers")
        x, y = m.groups()
    return int(_number(int(x), rel, what, -MAX_SIDE, MAX_SIDE)), int(_number(int(y), rel, what, -MAX_SIDE, MAX_SIDE))


# -------------------------------------------------- animated opacity (AnimatableObject.gd, Godot's Tween)
_TOKEN = re.compile(r'\s*(?:(?P<s>"(?:[^"\\]|\\.)*")|(?P<n>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)|'
                    r'(?P<i>[A-Za-z_][A-Za-z_0-9]*)|(?P<p>[{}\[\]():,&^]))')


def _gvalue(text):
    """A Godot value as var_to_str writes it (the subset a layer's animated_params uses): dictionaries (any keys),
    arrays, strings, numbers, true/false/null; a typed container's type list is skipped, and any other constructor
    such as Vector2(1, 2) comes back as (name, [arguments]). Raises ValueError on anything else."""
    toks, pos = [], 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            if text[pos:].strip():
                raise ValueError(f"unexpected {text[pos:pos + 12]!r}")
            break
        pos = m.end()
        toks.append((m.lastgroup, m.group(m.lastgroup)))
    at = [0]

    def peek():
        return toks[at[0]] if at[0] < len(toks) else ("", "")

    def take(want=None):
        t = peek()
        if want is not None and t[1] != want:
            raise ValueError(f"expected {want!r}, found {t[1]!r}")
        at[0] += 1
        return t

    def items(close, depth):
        out = []
        while peek()[1] != close:
            if not peek()[0]:
                raise ValueError("the text ends early")
            out.append(value(depth))
            if peek()[1] == ",":
                take()
        take(close)
        return out

    def value(depth):
        if depth > 32:
            raise ValueError("nested too deep")
        kind, tok = take()
        if kind == "s":
            return json.loads(tok)
        if kind == "n":
            return float(tok) if re.search(r"[.eE]", tok) else int(tok)
        if tok in ("&", "^"):                  # StringName (&"x") and NodePath (^"x")
            return value(depth + 1)
        if tok == "{":
            out = {}
            while peek()[1] != "}":
                if not peek()[0]:
                    raise ValueError("the text ends early")
                k = value(depth + 1)
                take(":")
                out[tuple(k) if isinstance(k, list) else k] = value(depth + 1)
                if peek()[1] == ",":
                    take()
            take("}")
            return out
        if tok == "[":
            return items("]", depth + 1)
        if kind == "i":
            if tok in ("true", "false", "null"):
                return {"true": True, "false": False, "null": None}[tok]
            if peek()[1] == "[":               # Dictionary[String, Dictionary](...): the types are not needed
                take()
                while peek()[0] in ("i", "p") and peek()[1] not in ("]", "(", "{"):
                    take()                     # type names and the commas between them
                take("]")
            take("(")
            args = items(")", depth + 1)
            if tok in ("Dictionary", "Array") and len(args) == 1:
                return args[0]
            return (tok, args)
        raise ValueError(f"unexpected {tok!r}")

    v = value(0)
    if at[0] != len(toks):
        raise ValueError("text after the value")
    return v


def _opacity_keys(ly, rel, name):
    """The layer's opacity keyframes: {frame index from 0: (value, trans, ease)}, {} when it has none. Pixelorama
    keeps them in animated_params (var_to_str of a Dictionary); a layer animates nothing but its opacity."""
    text = ly.get("animated_params")
    if text in (None, ""):
        return {}
    try:
        params = _gvalue(text) if isinstance(text, str) else text
    except (ValueError, RecursionError) as e:
        _fail(rel, f"layer {name}: its animated properties cannot be read ({e})")
    if not isinstance(params, dict):
        _fail(rel, f"layer {name}: its animated properties are not a dictionary")
    keys = params.get("opacity") or {}
    if not isinstance(keys, dict):
        _fail(rel, f"layer {name}: its opacity keyframes are not a dictionary")
    out = {}
    for fi, kf in keys.items():
        if not isinstance(fi, int) or isinstance(fi, bool) or not isinstance(kf, dict):
            _fail(rel, f"layer {name}: opacity keyframe {fi!r} is not a frame number with its settings")
        v = _number(kf.get("value", 1.0), rel, f"layer {name} opacity keyframe {fi}")
        trans, ease = kf.get("trans", TRANS_LINEAR), kf.get("ease", EASE_IN)
        if (trans not in EASINGS and trans != TRANS_CONSTANT) or ease not in (0, 1, 2, 3):
            _fail(rel, f"layer {name}: opacity keyframe {fi} has transition {trans!r} and ease {ease!r}, which "
                       "Pixelorama 1.2.4 does not have")
        out[fi] = (float(v), trans, ease)
    return out


def _f(x):
    """A value stored in a 32-bit float (Godot's real_t and Color)."""
    return float(np.float32(x))


def _ease_fns():
    """Godot 4.7's easing equations (scene/animation/easing_equations.h, after Robert Penner's): t from 0 to d,
    from b to b + c. Godot computes them in 32-bit floats (real_t), and in doubles from where an expression meets one
    (Math::PI, 0.001, the sine of a double): each step here is rounded the same way. pow and sqrt of floats come
    from Python's math rounded to a float, where Godot calls the C library's float versions, which may differ in the
    last bit."""
    import math
    f, pi = _f, math.pi
    f3 = np.float32

    def lin(t, b, c, d):
        return f(f(c * t) / d + b)

    # where Godot's expression meets a double (Math::PI, 0.001, sin of a double), the rest of it is in doubles
    def sine_in(t, b, c, d):
        return f(-c * math.cos(f(t / d) * (pi / 2)) + c + b)

    def sine_out(t, b, c, d):
        return f(c * math.sin(f(t / d) * (pi / 2)) + b)

    def sine_io(t, b, c, d):
        return f(f(-c / 2) * (math.cos(pi * t / d) - 1) + b)

    def pw(x, n):
        return f(math.pow(x, n))

    def poly(n):
        def ein(t, b, c, d):
            return f(f(c * pw(f(t / d), n)) + b)

        def eout(t, b, c, d):
            if n == 5:
                return f(f(c * f(pw(f(f(t / d) - 1), n) + 1)) + b)
            return f(f(-c * f(pw(f(f(t / d) - 1), n) - 1)) + b)

        def eio(t, b, c, d):
            t = f(f(t / d) * 2)
            if t < 1:
                return f(f(f(c / 2) * pw(t, n)) + b)
            if n == 5:
                return f(f(f(c / 2) * f(pw(f(t - 2), n) + 2)) + b)
            return f(f(f(-c / 2) * f(pw(f(t - 2), n) - 2)) + b)
        return ein, eout, eio

    def quad_out(t, b, c, d):
        t = f(t / d)
        return f(f(f(-c * t) * f(t - 2)) + b)

    def quad_io(t, b, c, d):
        t = f(f(t / d) * 2)
        if t < 1:
            return f(f(f(c / 2) * pw(t, 2)) + b)
        return f(f(f(-c / 2) * f(f(f(t - 1) * f(t - 3)) - 1)) + b)

    def expo_in(t, b, c, d):
        return b if t == 0 else f(f(f(c * pw(2, f(10 * f(f(t / d) - 1)))) + b) - c * 0.001)

    def expo_out(t, b, c, d):
        return f(b + c) if t == d else f(c * 1.001 * f(-pw(2, f(f(-10 * t) / d)) + 1) + b)

    def expo_io(t, b, c, d):
        if t == 0:
            return b
        if t == d:
            return f(b + c)
        t = f(f(t / d) * 2)
        if t < 1:
            return f(f(f(f(c / 2) * pw(2, f(10 * f(t - 1)))) + b) - c * 0.0005)
        return f(f(c / 2) * 1.0005 * f(-pw(2, f(-10 * f(t - 1))) + 2) + b)

    def el(kind):
        def fn(t, b, c, d):
            if t == 0:
                return b
            if kind == "io":
                t = f(t / f(d / 2))
                if t == 2:
                    return f(b + c)
                p = f(d * f(f3(0.3) * f3(1.5)))
            else:
                t = f(t / d)
                if t == 1:
                    return f(b + c)
                p = f(d * f3(0.3))
            s = f(p / 4)

            def wave(t):
                return math.sin(f(f(t * d) - s) * (2 * pi) / p)
            if kind == "in":
                t = f(t - 1)
                a = f(c * pw(2, f(10 * t)))
                return f(-(a * wave(t)) + b)
            if kind == "out":
                return f(f(c * pw(2, f(-10 * t))) * wave(t) + c + b)
            if t < 1:
                t = f(t - 1)
                a = f(c * pw(2, f(10 * t)))
                return f(-0.5 * (a * wave(t)) + b)
            t = f(t - 1)
            a = f(c * pw(2, f(-10 * t)))
            return f(a * wave(t) * 0.5 + c + b)
        return fn

    def cubic_in(t, b, c, d):
        t = f(t / d)
        return f(f(f(f(c * t) * t) * t) + b)

    def cubic_out(t, b, c, d):
        t = f(f(t / d) - 1)
        return f(f(c * f(f(f(t * t) * t) + 1)) + b)

    def cubic_io(t, b, c, d):
        t = f(t / f(d / 2))
        if t < 1:
            return f(f(f(f(f(c / 2) * t) * t) * t) + b)
        t = f(t - 2)
        return f(f(f(c / 2) * f(f(f(t * t) * t) + 2)) + b)

    def root(x):
        return f(math.sqrt(x)) if x >= 0 else float("nan")

    def circ_in(t, b, c, d):
        t = f(t / d)
        return f(f(-c * f(root(f(1 - f(t * t))) - 1)) + b)

    def circ_out(t, b, c, d):
        t = f(f(t / d) - 1)
        return f(f(c * root(f(1 - f(t * t)))) + b)

    def circ_io(t, b, c, d):
        t = f(t / f(d / 2))
        if t < 1:
            return f(f(f(-c / 2) * f(root(f(1 - f(t * t))) - 1)) + b)
        t = f(t - 2)
        return f(f(f(c / 2) * f(root(f(1 - f(t * t))) + 1)) + b)

    def bounce_out(t, b, c, d):
        t = f(t / d)
        k = f(f3(7.5625))
        if t < f(1 / f3(2.75)):
            return f(f(c * f(f(k * t) * t)) + b)
        if t < f(2 / f3(2.75)):
            t = f(t - f(f3(1.5) / f3(2.75)))
            return f(f(c * f(f(f(k * t) * t) + 0.75)) + b)
        if t < 2.5 / 2.75:
            t = f(t - f(f3(2.25) / f3(2.75)))
            return f(f(c * f(f(f(k * t) * t) + 0.9375)) + b)
        t = f(t - f(f3(2.625) / f3(2.75)))
        return f(f(c * f(f(f(k * t) * t) + 0.984375)) + b)

    def bounce_in(t, b, c, d):
        return f(f(c - bounce_out(f(d - t), 0.0, c, d)) + b)

    s1, s2 = f(f3(1.70158)), f(f3(1.70158) * f3(1.525))

    def back_in(t, b, c, d):
        t = f(t / d)
        return f(f(f(f(c * t) * t) * f(f(f(s1 + 1) * t) - s1)) + b)

    def back_out(t, b, c, d):
        t = f(f(t / d) - 1)
        return f(f(c * f(f(f(t * t) * f(f(f(s1 + 1) * t) + s1)) + 1)) + b)

    def back_io(t, b, c, d):
        t = f(t / f(d / 2))
        if t < 1:
            return f(f(f(c / 2) * f(f(t * t) * f(f(f(s2 + 1) * t) - s2))) + b)
        t = f(t - 2)
        return f(f(f(c / 2) * f(f(f(t * t) * f(f(f(s2 + 1) * t) + s2)) + 2)) + b)

    def spring_out(t, b, c, d):
        t = f(t / d)
        s = f(1.0 - t)
        t = f((math.sin(t * pi * (0.2 + 2.5 * t * t * t)) * pw(s, f(f3(2.2))) + t) * (1.0 + (1.2 * s)))
        return f(f(c * t) + b)

    def spring_in(t, b, c, d):
        return f(f(c - spring_out(f(d - t), 0.0, c, d)) + b)

    def halves(first, second):
        """Godot's in_out / out_in for the curves built from two halves."""
        def fn(t, b, c, d):
            if t < f(d / 2):
                return first(f(t * 2), b, f(c / 2), d)
            h = f(c / 2)
            return second(f(f(t * 2) - d), f(b + h), h, d)
        return fn

    def four(ein, eout, eio):
        return (ein, eout, eio, halves(eout, ein))

    return {   # Tween.TransitionType: (EASE_IN, EASE_OUT, EASE_IN_OUT, EASE_OUT_IN)
        0: (lin, lin, lin, lin),
        1: four(sine_in, sine_out, sine_io),
        2: four(*poly(5)), 3: four(*poly(4)),
        4: four(poly(2)[0], quad_out, quad_io),
        5: four(expo_in, expo_out, expo_io),
        6: four(el("in"), el("out"), el("io")),
        7: four(cubic_in, cubic_out, cubic_io),
        8: four(circ_in, circ_out, circ_io),
        9: (bounce_in, bounce_out, halves(bounce_in, bounce_out), halves(bounce_out, bounce_in)),
        10: four(back_in, back_out, back_io),
        11: (spring_in, spring_out, halves(spring_in, spring_out), halves(spring_out, spring_in)),
    }


EASINGS = _ease_fns()


def _layer_opacity(opacity, keys, fi):
    """BaseLayer.get_opacity(frame): the layer's own opacity, or its keyframes at frame fi
    (AnimatableObject.get_animated_property and Tween.interpolate_value; a frame before the first keyframe or after
    the last takes that keyframe's value)."""
    if not keys:
        return opacity
    if fi in keys:
        return keys[fi][0]
    ks = sorted(keys)
    lo, hi = ks[0], ks[-1]
    if len(ks) > 1:
        for k in ks:                             # AnimatableObject.find_frame_edges
            if lo < k <= fi:
                lo = k
            if fi <= k < hi:
                hi = k
    a, trans, ease = keys[lo]
    if trans == TRANS_CONSTANT:
        return a
    b, d = a + (keys[hi][0] - a), _f(hi - lo)
    w = 1.0 if d == 0 else EASINGS[trans][ease](_f(fi - lo), 0.0, 1.0, d)   # Tween.run_equation
    return a + _f(w) * (b - a)                    # Math::lerp, in doubles


def _buffer(z, name, w, h, rel):
    """One cel's raw RGBA8 buffer as an H x W x 4 array; the declared size is checked before anything is inflated."""
    try:
        info = z.getinfo(name)
    except KeyError:
        _fail(rel, f"{name} is missing")
    if info.file_size != w * h * 4:
        _fail(rel, f"{name} holds {info.file_size} bytes, not the {w * h * 4} of a {w}x{h} RGBA image")
    try:
        data = z.read(name)
    except (zipfile.BadZipFile, zlib.error, OSError) as e:
        _fail(rel, f"{name} cannot be read ({e})")
    if len(data) != w * h * 4:
        _fail(rel, f"{name} unpacked to {len(data)} bytes, not {w * h * 4}")
    return np.frombuffer(data, np.uint8).reshape(h, w, 4)


# -------------------------------------------------- compositing (DrawingAlgos.gd, BlendLayers.gdshader)
def _unit(b):
    """Image.get_pixel: bytes as the 32-bit floats Godot keeps (byte / 255.0)."""
    return (b.astype(np.float64) / 255.0).astype(np.float32)


def _byte(x):
    """Image.set_pixel: uint8(CLAMP(x * 255.0, 0, 255)) of a 32-bit float, which truncates."""
    return np.clip(np.trunc(x.astype(np.float32).astype(np.float64) * 255.0), 0, 255).astype(np.uint8)


def _blend_rect(img, src):
    """Image.blend_rect: Color.blend of src over img, in 32-bit floats, wherever src is not fully clear; both
    H x W x 4 uint8."""
    hit = src[..., 3] != 0
    if not hit.any():
        return img
    d, s = _unit(img[hit]), _unit(src[hit])
    sa = np.float32(1) - s[:, 3]
    ra = d[:, 3] * sa + s[:, 3]
    px = np.empty_like(d)
    px[:, 3] = ra
    for c in range(3):
        px[:, c] = (d[:, c] * d[:, 3] * sa + s[:, c] * s[:, 3]) / ra
    out = img.copy()
    out[hit] = _byte(px)
    return out


def _headless(cels, shape):
    """DrawingAlgos.blend_layers_headless, the composite Pixelorama's own export makes without a window (its
    command-line export): each cel's alpha times its opacity, stored back to 8 bits when the opacity is under 1,
    then Image.blend_rect over the frame so far, from a clear canvas. cels: [(H x W x 4 uint8, opacity)]."""
    img = np.zeros(shape, np.uint8)
    for cel, k in cels:
        if k < 1.0:
            cel = cel.copy()
            cel[..., 3] = _byte((_unit(cel[..., 3]).astype(np.float64) * k).astype(np.float32))
        img = _blend_rect(img, cel)
    return img


# The windowed composite (BlendLayers.gdshader): Pixelorama blends on the GPU with this shader whenever it has a
# window, in its canvas and its export alike, and only there does it apply blend modes, clipping masks and groups that
# blend their own layers. Ported here in 32-bit floats, with the opacities as the shader reads them (stored in an R8
# texture at the top, a half-float one inside a group). The GPU writes its result as 8-bit colour, rounded; its own
# rounding of values within about 0.06 of a half step differs from exact rounding (measured on one test machine), so
# such a composite lands within two steps of Pixelorama's in a few pixels.
def _r8(k):
    """An opacity through Pixelorama's R8 metadata texture: uint8(k * 255), truncated, read back as byte / 255."""
    return np.float32(np.clip(np.trunc(float(np.float32(k)) * 255.0), 0, 255) / 255.0)


def _rgh(k):
    """An opacity through a half-float metadata texture (Math::make_half_float: the mantissa truncated, values
    under 2^-14 zero)."""
    bits = int(np.float32(k).view(np.uint32))
    if bits & 0x7F800000 <= 0x38000000:
        return np.float32(0)
    return np.uint32(bits & ~0x1FFF).view(np.float32)


def _mix(x, y, a):
    return x * (np.float32(1) - a) + y * a


def _hsl(rgb):
    """rgb_to_hsl of the shader (via HCV, after Sam Hocevar and Emil Persson)."""
    f = np.float32
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    gb = (g < b)[..., None]
    p = np.where(gb, np.stack([b, g, np.full_like(r, -1), np.full_like(r, f(2 / 3))], -1),
                 np.stack([g, b, np.zeros_like(r), np.full_like(r, f(-1 / 3))], -1))
    rl = (r < p[..., 0])[..., None]
    q = np.where(rl, np.stack([p[..., 0], p[..., 1], p[..., 3], r], -1),
                 np.stack([r, p[..., 1], p[..., 2], p[..., 0]], -1))
    c = q[..., 0] - np.minimum(q[..., 3], q[..., 1])
    h = np.abs((q[..., 3] - q[..., 1]) / (f(6) * c + f(1e-10)) + q[..., 2])
    lum = q[..., 0] - c * f(0.5)
    # the shader adds 1e-10 to 1 - |2L - 1|; the GPU's compiler (GLSL may reorder) adds it to the 1 first, where it
    # vanishes, so white and black come out 0 / 0 here: NaN, and the blend gives black there (measured, 1.2.4)
    s = c / ((f(1) + f(1e-10)) - np.abs(lum * f(2) - f(1)))
    return np.stack([h, s, lum], -1)


def _rgb(hsl):
    """hsl_to_rgb of the shader."""
    f = np.float32
    h = hsl[..., 0]
    rgb = np.clip(np.stack([np.abs(h * f(6) - f(3)) - f(1), f(2) - np.abs(h * f(6) - f(2)),
                            f(2) - np.abs(h * f(6) - f(4))], -1), 0, 1).astype(f)
    c = (f(1) - np.abs(f(2) * hsl[..., 2] - f(1))) * hsl[..., 1]
    return (rgb - f(0.5)) * c[..., None] + hsl[..., 2:3]


def _shade(mode, cur, prev, k):
    """The shader's blend(): cur (this layer, its clipping applied) over prev (the frame so far), both H x W x 4
    float32 straight alpha, with this layer's opacity k."""
    f, one, two = np.float32, np.float32(1), np.float32(2)
    cur, prev = cur.copy(), prev.copy()
    cur[..., 3] *= k
    keep = cur[..., 3] <= f(0.001)                  # nothing to blend: the frame so far stays
    if mode in (BLEND_INTERSECT, BLEND_MATCH) and k > f(0.001):
        keep[:] = False
    c, p = cur[..., :3], prev[..., :3]
    res = np.zeros_like(cur)
    alpha = True
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        if mode == 1:                                # Erase
            res = prev.copy()
            res[..., 3] -= cur[..., 3]
            cur[..., 3] = 0
            alpha = False
        elif mode in (17, 18, 19, 20):               # Hue, Saturation, Color, Luminosity
            ch, ph = _hsl(c), _hsl(p)
            pick = {17: (ch, ph, ph), 18: (ph, ch, ph), 19: (ch, ch, ph), 20: (ph, ph, ch)}[mode]
            res[..., :3] = _rgb(np.stack([pick[0][..., 0], pick[1][..., 1], pick[2][..., 2]], -1))
        elif mode == BLEND_INTERSECT:
            res[..., :3] = c
            gone = cur[..., 3] * prev[..., 3] <= f(0.001)
            cur[..., 3][gone] = 0
            prev[..., 3][gone] = 0
        elif mode == BLEND_MATCH:
            res = cur.copy()
            differ = ~(np.abs(cur - prev) <= f(0.001)).all(-1)
            prev[..., 3][differ] = 0
            cur[differ] = 0
            alpha = False
        else:
            res[..., :3] = {
                0: lambda: c,
                2: lambda: np.minimum(p, c),
                3: lambda: p * c,
                4: lambda: one - (one - p) / c,
                5: lambda: p + c - one,
                6: lambda: np.maximum(p, c),
                7: lambda: one - (one - p) * (one - c),
                8: lambda: p / (one - c),
                9: lambda: p + c,
                10: lambda: _mix(two * p * c, one - two * (one - c) * (one - p), np.rint(p)),
                11: lambda: _mix(two * p * c + p * p * (one - two * c),
                                 np.sqrt(p) * (two * c - one) + (two * p) * (one - c), np.rint(p)),
                12: lambda: _mix(two * p * c, one - two * (one - c) * (one - p), np.rint(c)),
                13: lambda: np.abs(p - c),
                14: lambda: p + c - two * p * c,
                15: lambda: p - c,
                16: lambda: p / c,
            }[mode]()
        res[..., :3] = _mix(prev[..., :3], res[..., :3], cur[..., 3:4])
        if alpha:
            res[..., 3] = prev[..., 3] * (one - cur[..., 3]) + cur[..., 3]
        # a division by zero gives inf (clamped) or NaN, which the GPU's clamp turns to 0
        res = np.clip(np.nan_to_num(res, nan=0.0, posinf=1.0, neginf=0.0), 0, 1).astype(f)
        out = _mix(cur, res, prev[..., 3:4])        # "proportional to how much previous color had alpha"
    out[keep] = prev[keep]
    return out


def _gpu_bytes(x):
    """What the GPU writes for the shader's result: 8-bit colour, rounded to the nearest step."""
    return np.clip(np.rint(x.astype(np.float64) * 255.0), 0, 255).astype(np.uint8)


def _mb(n):
    return f"{n / (1024 * 1024):.0f} MB"


def _gpu_blend(items, cel, shape):
    """The shader's fragment() over items [(what, opacity, blend mode, clipped)] in draw order: the first drawn as it
    is (its opacity only), each next one blended over the result; a clipped one takes the alpha of the layer just
    under it in the list, shown or not. A group's own result goes back through 8 bits before its parent blends it.
    cel(layer) is that cel's band of rows (uint8) or None when it was not read (nothing of it shows)."""
    res, under = None, None
    for n, (what, k, mode, clip) in enumerate(items):
        clipped_next = n + 1 < len(items) and items[n + 1][3]
        if k > 0 or clipped_next or res is None:
            tex = _texture(what, cel, shape) if (k > 0 or clipped_next) else np.zeros(shape, np.float32)
        else:
            tex = None                         # nothing of it shows, and no clipping mask needs it
        if res is None:
            res = tex.copy()
            res[..., 3] *= k
        elif tex is not None:
            cur = tex
            if clip:
                cur = tex.copy()
                cur[..., 3] *= under[..., 3] if under is not None else 0
            res = _shade(mode, cur, res, k)
        under = tex
    return res if res is not None else np.zeros(shape, np.float32)


def _texture(what, cel, shape):
    """A layer as the shader samples it, float32: a cel, a group's own blend (8-bit, as the GPU wrote it), or clear."""
    if what[0] == "cel":
        b = cel(what[1])
        if b is not None:
            return _unit(b)
    elif what[0] == "group" and what[2]:
        return _unit(_gpu_bytes(_gpu_blend(what[2], cel, shape)))
    return np.zeros(shape, np.float32)


def open_project(path):
    """(open zip, data.json as a dict, path relative to the game, pxo_version, width, height) of a .pxo, with the
    checks every reader needs first: a Pixelorama 1.2 project of a size, frame and layer count Dotwork reads, whose
    layer parents are group layers of the project. The caller closes the zip."""
    rel = os.path.relpath(path, core.PROJECT)
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        _fail(rel, f"not a Pixelorama 1.x project ({e}); files saved by Pixelorama 0.x are not read")
    try:
        try:
            info = z.getinfo("data.json")
        except KeyError:
            _fail(rel, "no data.json: not a Pixelorama project")
        if info.file_size > MAX_JSON:
            _fail(rel, f"data.json is {info.file_size} bytes (over {MAX_JSON})")
        try:
            d = json.loads(z.read("data.json").decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError, zipfile.BadZipFile, zlib.error) as e:
            _fail(rel, f"data.json cannot be read ({e})")
        if not isinstance(d, dict):
            _fail(rel, "data.json is not an object")
        version = d.get("pxo_version")
        if version not in READ_VERSIONS:
            _fail(rel, f"pxo_version {version!r}: Dotwork reads {' and '.join(map(str, READ_VERSIONS))} (Pixelorama "
                       "1.2.x); open it in Pixelorama 1.2 and save it again")
        w = int(_number(d.get("size_x"), rel, "size_x", 1, MAX_SIDE))
        h = int(_number(d.get("size_y"), rel, "size_y", 1, MAX_SIDE))
        if d.get("color_mode", RGBA8) not in (RGBA8, INDEXED):
            _fail(rel, f"colour mode {d.get('color_mode')!r}: Dotwork reads RGBA and indexed projects")
        layers, frames = d.get("layers"), d.get("frames")
        if not isinstance(layers, list) or not layers or not isinstance(frames, list) or not frames:
            _fail(rel, "no layers or no frames")
        if len(frames) > MAX_FRAMES:
            _fail(rel, f"{len(frames)} frames (over {MAX_FRAMES})")
        if len(layers) > MAX_LAYERS:
            _fail(rel, f"{len(layers)} layers (over {MAX_LAYERS})")
        if len(frames) * w * h * 4 > MAX_DECODED:
            _fail(rel, f"{len(frames)} frames of {w}x{h} would take {_mb(len(frames) * w * h * 4)} to hold (over "
                       f"{_mb(MAX_DECODED)}): split the project")
        for i, ly in enumerate(layers):
            if not isinstance(ly, dict):
                _fail(rel, f"layer {i + 1} is not an object")
            p = ly.get("parent", -1)
            if not (p == -1 or (isinstance(p, int) and not isinstance(p, bool) and 0 <= p < len(layers) and p != i
                                and isinstance(layers[p], dict) and layers[p].get("type") == LAYER_GROUP)):
                _fail(rel, f"layer {ly.get('name', i + 1)!r}: parent {p!r} is not a group layer of this project")
    except BaseException:
        z.close()
        raise
    return z, d, rel, version, w, h


def visible_in(layers, i, rel):
    """True when layer i and every group above it are visible (a loop in the parents is refused)."""
    seen = []
    while i != -1:
        if i in seen:
            _fail(rel, f"layer {layers[i].get('name', i + 1)!r}: its groups contain each other")
        seen.append(i)
        if not layers[i].get("visible", True):
            return False
        i = layers[i].get("parent", -1)
    return True


def read_pxo(path):
    """{"size": (w, h), "fps", "frames": [H x W x 4 uint8, the visible layers composited], "seconds": [how long each
    frame shows], "tags": [(name, first, last) numbered from 0], "windowed": True when a layer needs the windowed
    composite}. Refuses, naming the layer, anything it cannot reproduce.
    Two composites, as Pixelorama 1.2.4 has two: a project of Normal layers (pass-through groups, cel and layer
    opacity, animated opacity) composites as Pixelorama's own export does without a window (_headless), exactly; one
    that uses a blend mode, a clipping mask or a group that blends its own layers, which only Pixelorama's windowed
    GPU composite applies (its command-line export leaves them out), composites as that shader does (_shade).
    A tilemap layer is drawn from its tiles and cells, as Pixelorama draws it when it opens the file (pxo_tiles), and
    then composites like a pixel layer."""
    import pxo_tiles
    z, d, rel, version, w, h = open_project(path)
    with z:
        fps = float(_number(d.get("fps", DEFAULT_FPS), rel, "fps", 0.001, 1000))
        layers, frames = d["layers"], d["frames"]

        def name_of(i):
            return repr(layers[i].get("name") or f"layer {i + 1}")

        def chain(i):
            """The layer and its groups up the tree (a loop in the parents is refused)."""
            seen = []
            while i != -1:
                if i in seen:
                    _fail(rel, f"layer {name_of(i)}: its groups contain each other")
                seen.append(i)
                i = layers[i].get("parent", -1)
            return seen

        kinds = [ly.get("type", LAYER_PIXEL) for ly in layers]
        blends = [ly.get("blend_mode", BLEND_NORMAL) for ly in layers]   # a group without one blends (deserialize)
        visible = [all(layers[j].get("visible", True) for j in chain(i)) for i in range(len(layers))]
        # BaseLayer.is_blended_by_ancestor: a group above it that is not pass-through draws it
        blended = [any(blends[j] != BLEND_PASS for j in chain(i)[1:]) for i in range(len(layers))]
        keys, opac = {}, []
        for i, ly in enumerate(layers):
            kind = kinds[i]
            opac.append(float(_number(ly.get("opacity", 1.0), rel, f"layer {name_of(i)} opacity", 0, 1))
                        if visible[i] else 0.0)
            if not visible[i] or kind == LAYER_AUDIO:
                continue                       # hidden layers and sound never reach the frames
            if kind in LAYER_NAMES or kind not in (LAYER_PIXEL, LAYER_GROUP, LAYER_TILEMAP):
                _fail(rel, f"layer {name_of(i)} is {LAYER_NAMES.get(kind, f'of type {kind!r}')}: Dotwork re-exports "
                           "pixel, tilemap and group layers (merge it down or hide it)")
            b = blends[i]
            if isinstance(b, bool) or not isinstance(b, int) or not (
                    BLEND_NORMAL <= b <= BLEND_LAST or (kind == LAYER_GROUP and b == BLEND_PASS)):
                _fail(rel, f"layer {name_of(i)} has blend mode {b!r}, which Pixelorama 1.2.4 does not have")
            if any(isinstance(e, dict) and e.get("enabled", True) for e in ly.get("effects") or []):
                _fail(rel, f"layer {name_of(i)} has layer effects: they are shaders Pixelorama runs only with a "
                           "window, on the GPU (its own command-line export leaves them out), and Dotwork cannot run "
                           "them; press Apply on each in the layer's effects, or turn them off")
            keys[i] = _opacity_keys(ly, rel, name_of(i))
        # tilemap layers: their tilesets, read when the first tilemap cel is needed (a visible layer's checked now)
        sets, tileset_of = [], {}
        tilemap_cels = {}                      # (frame, layer): (offset, cells) of each tilemap cel that is drawn

        def tileset_for(li):
            if not sets:
                sets.append(pxo_tiles.tilesets(z, d, rel))
            if li not in tileset_of:
                tileset_of[li] = sets[0][pxo_tiles.layer_tileset(layers[li], sets[0], rel, name_of(li))]
            return tileset_of[li]
        for i in range(len(layers)):
            if visible[i] and kinds[i] == LAYER_TILEMAP:
                tileset_for(i)

        def mode_of(li):
            """The blend mode the shader reads: a pass-through group's (or a hidden layer's odd value) as Normal."""
            b = blends[li]
            return b if isinstance(b, int) and not isinstance(b, bool) and BLEND_NORMAL <= b <= BLEND_LAST else 0
        windowed = any(visible[i] and kinds[i] in (LAYER_PIXEL, LAYER_GROUP, LAYER_TILEMAP) and (
            (kinds[i] == LAYER_GROUP and blends[i] != BLEND_PASS) or (kinds[i] in PAINTED and blends[i])
            or layers[i].get("clipping_mask")) for i in range(len(layers)))
        if windowed and d.get("color_mode") == INDEXED and any(
                visible[i] and kinds[i] == LAYER_GROUP and blends[i] != BLEND_PASS for i in range(len(layers))):
            _fail(rel, "an indexed project with a group that blends its layers: Pixelorama maps that group to the "
                       "palette, which Dotwork does not; set the group to pass-through or the project to RGBA")

        plans, seconds, unpacked, sizes = [], [], 0, {}
        for fi, fr in enumerate(frames):
            cels = fr.get("cels") if isinstance(fr, dict) else None
            if not isinstance(cels, list) or len(cels) != len(layers):
                _fail(rel, f"frame {fi + 1} has {len(cels) if isinstance(cels, list) else 'no'} cels for "
                           f"{len(layers)} layers")
            dur = _number(fr.get("duration", 1.0), rel, f"frame {fi + 1} duration", 0, 10000)
            if not dur > 0:
                _fail(rel, f"frame {fi + 1} has a duration of 0")
            seconds.append(dur / fps)
            if not all(isinstance(c, dict) for c in cels):
                _fail(rel, f"frame {fi + 1}: a cel is not an object")
            zs = [int(_number(c.get("z_index", 0), rel, f"frame {fi + 1} z_index", -len(layers), len(layers)))
                  for c in cels]
            # draw order as Pixelorama sorts it (Project._z_index_sort): layer index plus the cel's z-index, then z
            order = sorted(range(len(layers)), key=lambda i: (i + zs[i], zs[i]))

            def final(li):
                """BaseCel.get_final_opacity: the layer's opacity at this frame (keyframes too) times the cel's."""
                k = _number(cels[li].get("opacity", 1.0), rel, f"frame {fi + 1} cel opacity", 0, 1)
                return _layer_opacity(opac[li], keys.get(li), fi) * k

            def need(li):
                """Note that cel li of this frame is read (its buffer and its size, checked now)."""
                nonlocal unpacked
                if (fi, li) in sizes:
                    return
                cel = cels[li]
                if kinds[li] == LAYER_TILEMAP:   # drawn on the whole canvas from its tiles
                    tileset_for(li)
                    tilemap_cels[(fi, li)] = pxo_tiles.cells_of(cel, rel, f"frame {fi + 1} {name_of(li)}")
                    sizes[(fi, li)] = None
                    unpacked += w * h * 4
                elif version >= 8 and "image_size" in cel:
                    cw, ch = _vec2i(cel["image_size"], rel, f"frame {fi + 1} {name_of(li)} image_size")
                    ox, oy = _vec2i(cel.get("offset", "(0, 0)"), rel, f"frame {fi + 1} {name_of(li)} offset")
                    if cw < 0 or ch < 0:
                        _fail(rel, f"frame {fi + 1} {name_of(li)}: negative cel size")
                    sizes[(fi, li)] = (cw, ch, ox, oy)
                    unpacked += cw * ch * 4
                else:
                    sizes[(fi, li)] = None
                    unpacked += w * h * 4

            if not windowed:
                plan = []                  # (layer, opacity): DrawingAlgos.blend_layers_headless, in draw order
                for li in order:
                    if visible[li] and kinds[li] in PAINTED:
                        k = final(li)
                        if k > 0:
                            plan.append((li, k))
                            need(li)
                plans.append(plan)
                continue

            def node(li, k, mode, clip):
                """One layer of a GPU blend: (what it draws, opacity as the shader reads it, blend mode, clipped)."""
                if kinds[li] == LAYER_GROUP and blends[li] != BLEND_PASS:
                    what = ("group", li, group(li))
                elif kinds[li] in PAINTED:
                    what = ("cel", li)
                elif kinds[li] == LAYER_GROUP:
                    what = ("clear", li)       # a pass-through group draws nothing of its own
                else:
                    what = ("other", li)       # hidden: a 3D or audio layer
                return (what, k, mode, clip)

            def group(g):
                """GroupLayer.blend_children: the group's own layers in timeline order (not sorted by z-index),
                pass-through groups inside it opened up, each opacity in a half-float texture. Clipping masks do
                nothing inside a group that blends (Pixelorama marks every layer there as one to skip)."""
                items, width = [], 0

                def add(li):
                    k = _rgh(final(li)) if visible[li] else np.float32(0)
                    items.append(node(li, k, mode_of(li), False))
                    if k > 0 and kinds[li] in PAINTED:
                        need(li)

                def open_up(g2):
                    nonlocal width
                    for c in [i for i in range(g2) if layers[i].get("parent", -1) == g2]:
                        if kinds[c] == LAYER_GROUP and blends[c] == BLEND_PASS:
                            open_up(c)
                        else:
                            if kinds[c] != LAYER_GROUP:
                                width += 1     # the metadata grows by one for each such layer, not for a group
                            add(c)
                children = [i for i in range(g) if layers[i].get("parent", -1) == g]
                width = len(children)
                for c in children:
                    if kinds[c] == LAYER_GROUP and blends[c] == BLEND_PASS:
                        open_up(c)
                    else:
                        add(c)
                return items[:width]           # layers past the metadata's width are not drawn

            top = []
            for li in order:                   # DrawingAlgos.blend_layers: every layer has its place, shown or not
                shown = visible[li] and not blended[li]
                k = _r8(final(li)) if shown else np.float32(0)
                clip = bool(layers[li].get("clipping_mask")) and not blended[li] and bool(top)
                top.append(node(li, k, mode_of(li), clip))
                if k > 0:
                    if kinds[li] in PAINTED:
                        need(li)
                    if clip:                   # the shader clips to the raw layer under it, shown or not
                        under = top[-2][0]
                        if under[0] == "cel":
                            need(under[1])
                        elif under[0] == "other":
                            _fail(rel, f"frame {fi + 1}: clipping mask {name_of(li)} sits on {name_of(under[1])}, "
                                       "which is not a pixel layer or a group (merge it down or move it)")
            plans.append(top)
        if unpacked > MAX_UNPACKED:
            _fail(rel, f"its visible cels would unpack to {_mb(unpacked)} (over {_mb(MAX_UNPACKED)}): merge or hide "
                       "layers, or split the project")
        tags = []
        if len(d.get("tags") or []) > MAX_FRAMES:
            _fail(rel, f"{len(d['tags'])} tags (over {MAX_FRAMES})")
        for t in d.get("tags") or []:
            if not isinstance(t, dict):
                _fail(rel, "a tag is not an object")
            name = str(t.get("name", ""))
            if not handpolish.TAG_NAME.fullmatch(name):
                _fail(rel, f"tag {name!r}: animation names use letters, digits and _ only")
            a = int(_number(t.get("from"), rel, f"tag {name} from", 1, len(frames)))
            b = int(_number(t.get("to"), rel, f"tag {name} to", a, len(frames)))
            tags.append((name, a - 1, b - 1))

        out = []
        for fi, plan in enumerate(plans):
            cache = {}

            def cel(li):
                """Cel li of this frame on the whole canvas (a version 8 cel placed at its offset)."""
                if li not in cache:
                    name, part = f"image_data/frames/{fi + 1}/layer_{li + 1}", sizes[(fi, li)]
                    if (fi, li) in tilemap_cels:
                        img = pxo_tiles.render(tileset_of[li], *tilemap_cels[(fi, li)], w, h)
                    elif part:
                        cw, ch, ox, oy = part
                        img = np.zeros((h, w, 4), np.uint8)
                        if cw and ch:
                            buf = _buffer(z, name, cw, ch, rel)
                            x0, y0, x1, y1 = max(ox, 0), max(oy, 0), min(ox + cw, w), min(oy + ch, h)
                            if x1 > x0 and y1 > y0:
                                img[y0:y1, x0:x1] = buf[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
                    else:
                        img = _buffer(z, name, w, h, rel)
                    cache[li] = img
                return cache[li]

            if not windowed:
                if len(plan) == 1 and plan[0][1] >= 1.0:
                    # one layer as it is: an untouched frame comes back byte for byte
                    out.append(cel(plan[0][0]).copy())
                    continue
                img = np.zeros((h, w, 4), np.uint8)
                step = max(1, BAND_PIXELS // w)       # in bands of rows: the float work stays near 80 MB
                cels = [(cel(li), k) for li, k in plan]
                for y in range(0, h, step):
                    img[y:y + step] = _headless([(c[y:y + step], k) for c, k in cels], img[y:y + step].shape)
                out.append(img)
                continue
            img = np.zeros((h, w, 4), np.uint8)
            step = max(1, BAND_PIXELS // w)
            for y in range(0, h, step):
                rows = slice(y, y + step)
                res = _gpu_blend(plan, lambda li: cel(li)[rows] if (fi, li) in sizes else None,
                                 (min(h, y + step) - y, w, 4))
                img[rows] = _blend_rect(img[rows], _gpu_bytes(res))   # Image.blend_rect over a clear canvas
            out.append(img)
    return {"size": (w, h), "fps": fps, "frames": out, "seconds": seconds, "tags": tags, "windowed": windowed}


# -------------------------------------------------- the round trip
def _runs(items):
    """[(tag, first, last)] for consecutive items sharing a tag name ("" = untagged)."""
    tags = []
    for i, (t, _, _) in enumerate(items):
        if not t:
            continue
        if tags and tags[-1][0] == t and tags[-1][2] == i - 1:
            tags[-1] = (t, tags[-1][1], i)
        else:
            tags.append((t, i, i))
    return tags


def _shows_the_game(path, items, frames, durations, proj_fps):
    """True when the .pxo at path still shows what this build writes from items (the game's frames), whatever its
    bytes: Pixelorama rewrites data.json with its own fields on every save (pixelorama_version, export_profile,
    indices buffers ...), so a file only opened and saved, or polished and re-exported, never matches pxo_bytes again
    (issue #100). The checks are aseprite._shows_the_game's: the tags, the frame count, every frame's look
    (handpolish.same_look) and, in a tag, its time on screen within HOLD_TOLERANCE_S. A file read_pxo refuses (a layer
    it cannot composite) may hold polish, so it does not match."""
    try:
        pj = read_pxo(path)
    except core.ToolError:
        return False
    if len(pj["frames"]) != len(frames) or sorted(pj["tags"]) != sorted(_runs(items)):
        return False
    for (tag, _, _), want, have, dur, shown in zip(items, frames, pj["frames"], durations, pj["seconds"]):
        if tag and abs(shown - dur / proj_fps) > handpolish.HOLD_TOLERANCE_S:
            return False
        if not handpolish.same_look(have, want):
            return False
    return True


def build(pack, conf, overwrite=False):
    """Write <src_dir>/pixelorama/{characters,fx,single}/<name>.pxo. A .pxo that already exists and still shows the
    game's frames (_shows_the_game) is left as it is. One that differs may hold hand polish (or the game's art changed
    since): it is kept unless overwrite, and a file
    overwrite replaces is first copied to <name>.pxo.bak (one level, as the game shells keep their saves).
    A character whose clips have different sizes gets the widest and tallest as its canvas (handpolish.clip_box).
    Returns {"written": [...], "unchanged": [...], "kept": [...], "backups": [the .bak files written]}."""
    src = core.src(conf, "pixelorama")
    chars, fx, single, fps, fx_loop, holds = handpolish.groups(pack)
    jobs = []   # (out, [(tag, seconds or None, png)], project fps)
    for name, anims in chars.items():
        items, rates = [], Counter()
        for anim in sorted(anims):
            files = sorted(anims[anim])
            f = handpolish.rate(fps, name, anim)[0]
            rates[f] += len(files)
            secs = handpolish.frame_seconds(holds.get((name, anim)), f, len(files))
            items += [(anim, s, os.path.join(pack, p)) for s, p in zip(secs, files)]
        # the project plays at the rate most frames use; every other clip's frames carry their own multiplier
        jobs.append((os.path.join(src, "characters", f"{name}.pxo"), items,
                     max(rates.items(), key=lambda kv: (kv[1], kv[0]))[0]))
    for name, files in fx.items():
        tag = fx_loop.get(name, "play")
        rate = handpolish.fx_rate(conf, name, tag)[0]
        jobs.append((os.path.join(src, "fx", f"{name}.pxo"),
                     [(tag, 1.0 / rate, os.path.join(pack, f)) for f in sorted(files)], rate))
    for f in single:
        jobs.append((os.path.join(src, "single", os.path.basename(f)[:-4] + ".pxo"),
                     [("", None, os.path.join(pack, f))], 8))
    done = {"written": [], "unchanged": [], "kept": [], "backups": []}
    _build_tilemaps(pack, conf, overwrite, done)
    for out, items, proj_fps in jobs:
        rel = os.path.relpath(out, pack)
        frames = [np.array(Image.open(p).convert("RGBA")) for _, _, p in items]
        sizes = sorted({fr.shape[1::-1] for fr in frames})
        if len(sizes) > 1:
            # a project has one canvas: a character's clips share the largest, each centred on its bottom edge
            # (handpolish.clip_box), and the re-export crops each back (issue #82). An effect's frames must match.
            if os.path.basename(os.path.dirname(out)) != "characters":
                raise core.ToolError(f"{rel}: frames of {len(sizes)} sizes ({', '.join('%dx%d' % s for s in sizes)}): "
                                     "a Pixelorama project has one canvas")
            canvas = handpolish.canvas_of(sizes)
            frames = [np.array(handpolish.pad(Image.fromarray(fr, "RGBA"), canvas)) for fr in frames]
        durations = [1.0 if s is None else round(s * proj_fps, 6) for _, s, _ in items]
        opaque = np.concatenate([fr[fr[..., 3] == 255][:, :3] for fr in frames])
        colours = [tuple(int(v) for v in c) for c in np.unique(opaque, axis=0)]   # sorted, like aseprite.py's .gpl
        if len(colours) > PALETTE_MAX:
            core.log(f"pixelorama build {rel}: {len(colours)} colours, over {PALETTE_MAX}: no project palette")
            colours = None
        blob = pxo_bytes(frames, durations, _runs(items), proj_fps, colours,
                         palette_name=os.path.splitext(os.path.basename(out))[0] + " (Dotwork)")
        if os.path.exists(out):
            with open(out, "rb") as fh:
                old = fh.read()
            if old == blob or _shows_the_game(out, items, frames, durations, proj_fps):
                done["unchanged"].append(out)
                continue
            if not overwrite:
                done["kept"].append(out)
                core.log(f"pixelorama build {rel}: kept (it differs from the game's frames; --overwrite replaces it)")
                continue
            # the file being replaced may hold polish that was never re-exported: keep it beside the new one
            with open(core.safe_dest(out + ".bak"), "wb") as fh:
                fh.write(old)
            done["backups"].append(out + ".bak")
            core.log(f"pixelorama build {rel}: the file it replaces is kept as {os.path.basename(out)}.bak")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(core.safe_dest(out), "wb") as fh:
            fh.write(blob)
        done["written"].append(out)
        core.log(f"pixelorama build {rel}: {len(frames)} frames, {len(_runs(items))} tags, "
                 f"{len(colours or [])} colours, {proj_fps} fps")
    return done


def _build_tilemaps(pack, conf, overwrite, done):
    """<src_dir>/pixelorama/tilemaps/<map>.pxo for each Dotwork map scene, and <tileset>.pxo for each TileSet no map
    uses (pxo_tiles.dotwork_jobs). An existing file that holds no edits (pxo_tiles.polished) is rebuilt when the game
    changed; one with edits is kept unless overwrite (then backed up as .bak, as build does)."""
    import pxo_tiles
    for out, blob, _ in pxo_tiles.dotwork_jobs(pack, conf):
        rel = os.path.relpath(out, pack)
        if os.path.exists(out):
            with open(out, "rb") as fh:
                old = fh.read()
            if old == blob or not pxo_tiles.polished(out) and _same_tilemap(out, blob):
                done["unchanged"].append(out)
                continue
            if pxo_tiles.polished(out):
                if not overwrite:
                    done["kept"].append(out)
                    core.log(f"pixelorama build {rel}: kept (it holds edits not re-exported yet; --overwrite "
                             "replaces it)")
                    continue
                with open(core.safe_dest(out + ".bak"), "wb") as fh:
                    fh.write(old)
                done["backups"].append(out + ".bak")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(core.safe_dest(out), "wb") as fh:
            fh.write(blob)
        done["written"].append(out)
        core.log(f"pixelorama build {rel}: tilemap project written")


def _same_tilemap(path, blob):
    """True when the tilemap .pxo at path shows what blob would (its tiles, their data and the cells), whatever
    Pixelorama added on save."""
    import pxo_tiles
    tmp = os.path.join(core.WORK, "pxo_compare.pxo")
    os.makedirs(core.WORK, exist_ok=True)
    with open(tmp, "wb") as fh:
        fh.write(blob)
    try:
        a, b = pxo_tiles.project(path), pxo_tiles.project(tmp)
    except core.ToolError:
        return False
    finally:
        os.remove(tmp)

    def look(tm):
        ts = tm["tilesets"][0] if tm["tilesets"] else {"tiles": [], "data": []}
        tw, th = ts.get("size", (1, 1))
        return ([pxo_tiles._hash(t) for t in ts["tiles"]], [t["user_data"] for t in ts["data"]], tm["meta"],
                [(L["name"], sorted(((x + L["frames"][0][0][0] // tw, y + L["frames"][0][0][1] // th), c)
                                    for (x, y), c in L["frames"][0][1].items())) for L in tm["layers"]])
    return look(a) == look(b)


# -------------------------------------------------- the export folder Pixelorama keeps in each .pxo
def _unquote(v):
    """A Godot String as var_to_str writes it (the text in double quotes, the form Pixelorama 1.2.3 keeps in
    export_profile) or as plain text: the text itself."""
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v


def _data(z):
    """data.json of an open .pxo as a dict, or None when it is missing, too big or not an object (read_pxo reports
    those)."""
    try:
        if z.getinfo("data.json").file_size > MAX_JSON:
            return None
        d = json.loads(z.read("data.json").decode("utf-8"))
    except (KeyError, ValueError, UnicodeDecodeError, RecursionError, zipfile.BadZipFile, zlib.error):
        return None
    return d if isinstance(d, dict) else None


def export_folder(path):
    """The folder Pixelorama last exported this .pxo to, when it is an absolute path on someone's machine; else ""."""
    try:
        with zipfile.ZipFile(path) as z:
            d = _data(z)
    except (zipfile.BadZipFile, OSError):
        return ""
    prof = d.get("export_profile") if d else None
    v = prof.get("directory_path") if isinstance(prof, dict) else None
    folder = _unquote(v) if isinstance(v, str) else ""
    return folder if ABSOLUTE.match(folder) else ""


def clear_export_folder(path):
    """Rewrites a .pxo with its export folder blank (in the same form, quoted or not). Every other zip entry is
    copied as it was, in the same order and compression; data.json changes only in that one value."""
    with zipfile.ZipFile(path) as z:
        d = _data(z)
        entries = [(info, z.read(info.filename)) for info in z.infolist()]
    if d is None:
        return False
    prof = d["export_profile"]
    prof["directory_path"] = '""' if prof["directory_path"].startswith('"') else ""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for info, data in entries:
            if info.filename == "data.json":
                data = json.dumps(d, ensure_ascii=False).encode("utf-8")
            out.writestr(info, data)
    tmp = path + ".tmp"
    with open(core.safe_dest(tmp), "wb") as fh:
        fh.write(buf.getvalue())
    os.replace(tmp, path)
    return True


def local_paths(pack, conf, clear=False):
    """[(.pxo path relative to the game, the absolute export folder it holds, cleared)] for every Pixelorama source;
    clear=True blanks each folder (dotwork.py pixelorama --clear-export-path)."""
    src = core.src(conf, "pixelorama")
    found = []
    for kind in SOURCE_KINDS:
        for f in sorted(glob.glob(os.path.join(src, kind, "*.pxo"))):
            folder = export_folder(f)
            if folder:
                found.append((os.path.relpath(f, pack), folder, bool(clear) and clear_export_folder(f)))
    return found


def reexport(pack, conf):
    """Hand-polished .pxo -> shipped PNGs (+ .tres, sheets, manifest rows), then verify."""
    tmp = os.path.join(core.WORK, "pxo_export")
    os.makedirs(tmp, exist_ok=True)

    def export(file, prefix):
        for p in glob.glob(os.path.join(tmp, "*.png")):
            os.remove(p)
        pj = read_pxo(file)
        rel = os.path.relpath(file, pack)
        frames, secs, tags = pj["frames"], pj["seconds"], pj["tags"]
        kind = os.path.basename(os.path.dirname(file))       # characters, fx or single (write_back's folders)
        named = {}
        if kind == "characters":
            if not tags:
                raise core.ToolError(f"{rel}: no tags: each animation is one tag named like the animation (walk_s)")
            names = [t[0] for t in tags]
            if len(set(names)) != len(names):
                raise core.ToolError(f"{rel}: two tags share a name ({sorted({n for n in names if names.count(n) > 1})})")
            for name, a, b in tags:
                if b - a + 1 > MAX_CLIP:
                    raise core.ToolError(f"{rel}: tag {name} has {b - a + 1} frames (at most {MAX_CLIP})")
                for k, i in enumerate(range(a, b + 1)):
                    named[f"{prefix}_{name}_{k:02d}.png"] = i
            left = len(frames) - len(set(named.values()))
            if left:
                core.log(f"pixelorama reexport {rel}: {left} frames outside every tag were left out")
        elif kind == "fx":
            order = [i for _, a, b in tags for i in range(a, b + 1)] if tags else range(len(frames))
            named = {f"{prefix}_{k:04d}.png": i for k, i in enumerate(order)}   # renamed by write_back
        else:
            named = {f"{prefix}.png": 0}
        w, h = pj["size"]
        if len(named) * w * h * 4 > MAX_DECODED:   # overlapping tags can name one frame many times
            raise core.ToolError(f"{rel}: its tags name {len(named)} frames of {w}x{h}, "
                                 f"{_mb(len(named) * w * h * 4)} to write (over {_mb(MAX_DECODED)})")
        for fn, i in named.items():
            Image.fromarray(frames[i], "RGBA").save(os.path.join(tmp, fn))
        return sorted(os.path.join(tmp, fn) for fn in named), {fn: secs[i] for fn, i in named.items()}

    import pxo_tiles
    tiles = pxo_tiles.reexport(pack, conf)       # tilemap projects first: they may make the first manifest
    if tiles:
        core.log(f"pixelorama reexport tilemaps: {len(tiles)} files changed ({', '.join(tiles[:8])}"
                 f"{' ...' if len(tiles) > 8 else ''})")
    r = handpolish.write_back(pack, conf, core.src(conf, "pixelorama"), ".pxo", export, "Pixelorama")
    r["changed"] = r.get("changed", 0) + len(tiles)
    return r
