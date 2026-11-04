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
#           numbered from 1. Written as pxo_version 7 (what Pixelorama 1.2.0 to 1.2.3 write; checked with 1.2.3);
#           read: 7, and 8 (Pixelorama 1.2.4 release candidates, where a cel stores its own size and offset). Layer
#           features Dotwork cannot reproduce exactly (blend modes, clipping masks, layer effects, animated opacity,
#           3D and tilemap layers, group opacity) stop the re-export when the layer is visible, instead of shipping
#           frames that differ from what the editor shows. Pixelorama saves the folder you last exported to, a
#           full path on your machine, in every .pxo (export_profile.directory_path): both commands warn about it,
#           and only --clear-export-path rewrites the file to blank it (the frames and every other entry stay).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
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

WRITE_VERSION = 7                  # pxo_version Dotwork writes (Pixelorama 1.2.0 to 1.2.3 write 7)
READ_VERSIONS = (7, 8)             # 8: Pixelorama 1.2.4 release candidates (a cel's own size and offset)
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
LAYER_NAMES = {LAYER_3D: "a 3D layer", LAYER_TILEMAP: "a tilemap layer"}
RGBA8, INDEXED = 5, -1             # colour_mode: Godot Image.FORMAT_RGBA8; indexed mode still stores RGBA8 cels
BLEND_NORMAL, BLEND_PASS = 0, -2   # BaseLayer.BlendModes NORMAL and PASS_THROUGH (groups only)
TAG_COLOURS = ("c38ce1ff", "f5a677ff", "77c341ff", "6fb7e8ff", "e8d06fff", "e86f8aff")
ZIP_TIME = (1980, 1, 1, 0, 0, 0)   # a fixed date: the same frames always give the same .pxo bytes
MIMETYPE = b"application/x-pixelorama"
SOURCE_KINDS = ("characters", "fx", "single")   # the folders under the pixelorama sources (handpolish.write_back)
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


def _animated(v):
    """True when a layer's animated_params (var_to_str of a Dictionary) holds any keyframe."""
    s = re.sub(r"\s", "", str(v or ""))
    s = re.sub(r"^Dictionary\[[^\]]*\]\((.*)\)$", r"\1", s)
    return not re.fullmatch(r'\{("[^"]*":\{\},?)*\}|', s)


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


def _over(base, top, k):
    """Normal blending of top (straight alpha) over base, both H x W x 4 uint8, with top's alpha times k (cel and
    layer opacity). Pixels top leaves fully clear keep base untouched, colour under its transparency included.
    Blended in bands of rows (BAND_PIXELS at a time): the float arrays take about 80 bytes a pixel, 5 GB on a whole
    8192 x 8192 canvas."""
    out = base
    step = max(1, BAND_PIXELS // base.shape[1])
    for y in range(0, base.shape[0], step):
        t, b = top[y:y + step], base[y:y + step]
        a = t[..., 3:4].astype(np.float64) / 255.0 * k
        hit = a[..., 0] > 0
        if not hit.any():
            continue
        if out is base:
            out = base.copy()
        da = b[..., 3:4].astype(np.float64) / 255.0
        ra = a + da * (1.0 - a)
        rgb = (t[..., :3] * a + b[..., :3] * da * (1.0 - a)) / np.maximum(ra, 1e-12)
        px = np.concatenate([np.rint(rgb), np.rint(ra * 255.0)], axis=-1).clip(0, 255).astype(np.uint8)
        out[y:y + step][hit] = px[hit]
    return out


def _mb(n):
    return f"{n / (1024 * 1024):.0f} MB"


def read_pxo(path):
    """{"size": (w, h), "fps", "frames": [H x W x 4 uint8, the visible layers composited], "seconds": [how long each
    frame shows], "tags": [(name, first, last) numbered from 0]}. Refuses, naming the layer, anything it cannot
    reproduce exactly."""
    rel = os.path.relpath(path, core.PROJECT)
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        _fail(rel, f"not a Pixelorama 1.x project ({e}); files saved by Pixelorama 0.x are not read")
    with z:
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
        fps = float(_number(d.get("fps", DEFAULT_FPS), rel, "fps", 0.001, 1000))
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

        visible = [all(layers[j].get("visible", True) for j in chain(i)) for i in range(len(layers))]
        for i, ly in enumerate(layers):
            kind = ly.get("type", LAYER_PIXEL)
            if not visible[i] or kind == LAYER_AUDIO:
                continue                       # hidden layers and sound never reach the frames
            if kind in LAYER_NAMES or kind not in (LAYER_PIXEL, LAYER_GROUP):
                _fail(rel, f"layer {name_of(i)} is {LAYER_NAMES.get(kind, f'of type {kind!r}')}: Dotwork re-exports "
                           "pixel layers and groups (merge it down or hide it)")
            blend = ly.get("blend_mode", BLEND_NORMAL)
            if blend != BLEND_NORMAL and not (kind == LAYER_GROUP and blend == BLEND_PASS):
                _fail(rel, f"layer {name_of(i)} uses blend mode {blend}: Dotwork re-exports Normal layers only "
                           "(merge it down or set it to Normal)")
            if ly.get("clipping_mask"):
                _fail(rel, f"layer {name_of(i)} is a clipping mask: merge it down first")
            if any(isinstance(e, dict) and e.get("enabled", True) for e in ly.get("effects") or []):
                _fail(rel, f"layer {name_of(i)} has layer effects: apply them (or turn them off) first")
            if _animated(ly.get("animated_params")):
                _fail(rel, f"layer {name_of(i)} has animated properties: Dotwork reads one opacity per layer")
            op = _number(ly.get("opacity", 1.0), rel, f"layer {name_of(i)} opacity", 0, 1)
            if kind == LAYER_GROUP and op != 1:
                _fail(rel, f"group {name_of(i)} has opacity {op}: Dotwork reads groups at 100 % only")

        plans, seconds, unpacked = [], [], 0
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
            plan = []                  # (buffer name, opacity, (cel w, cel h, x, y) or None for a whole-canvas cel)
            for li in order:
                if not visible[li] or layers[li].get("type", LAYER_PIXEL) != LAYER_PIXEL:
                    continue
                cel = cels[li]
                k = (_number(cel.get("opacity", 1.0), rel, f"frame {fi + 1} cel opacity", 0, 1)
                     * _number(layers[li].get("opacity", 1.0), rel, "layer opacity", 0, 1))
                name = f"image_data/frames/{fi + 1}/layer_{li + 1}"
                if version >= 8 and "image_size" in cel:
                    cw, ch = _vec2i(cel["image_size"], rel, f"frame {fi + 1} {name_of(li)} image_size")
                    ox, oy = _vec2i(cel.get("offset", "(0, 0)"), rel, f"frame {fi + 1} {name_of(li)} offset")
                    if cw < 0 or ch < 0:
                        _fail(rel, f"frame {fi + 1} {name_of(li)}: negative cel size")
                    plan.append((name, k, (cw, ch, ox, oy)))
                    unpacked += cw * ch * 4
                else:
                    plan.append((name, k, None))
                    unpacked += w * h * 4
            plans.append(plan)
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
        for plan in plans:
            img, first = np.zeros((h, w, 4), np.uint8), True
            for name, k, part in plan:
                if part:
                    cw, ch, ox, oy = part
                    layer = np.zeros((h, w, 4), np.uint8)
                    if cw and ch:
                        cel = _buffer(z, name, cw, ch, rel)
                        x0, y0, x1, y1 = max(ox, 0), max(oy, 0), min(ox + cw, w), min(oy + ch, h)
                        if x1 > x0 and y1 > y0:
                            layer[y0:y1, x0:x1] = cel[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
                else:
                    layer = _buffer(z, name, w, h, rel)
                if first and k == 1:
                    img = layer.copy()     # copied as it is: an untouched frame comes back byte for byte
                elif k > 0:
                    img = _over(img, layer, k)
                first = False
            out.append(img)
    return {"size": (w, h), "fps": fps, "frames": out, "seconds": seconds, "tags": tags}


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
    for out, items, proj_fps in jobs:
        rel = os.path.relpath(out, pack)
        frames = [np.array(Image.open(p).convert("RGBA")) for _, _, p in items]
        sizes = sorted({fr.shape[1::-1] for fr in frames})
        if len(sizes) > 1:
            raise core.ToolError(f"{rel}: frames of {len(sizes)} sizes ({', '.join('%dx%d' % s for s in sizes)}): a "
                                 "Pixelorama project has one canvas")
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

    return handpolish.write_back(pack, conf, core.src(conf, "pixelorama"), ".pxo", export, "Pixelorama")
