#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# assetspec.py
# Purpose : the engine-neutral Dotwork asset manifest (ASSET_MANIFEST.md): its version, a validator (the JSON Schema
#           in asset_manifest.schema.json plus the checks a schema cannot express: files on disk, PNG sizes, frame
#           rects inside their sheets, legal autotile masks, map cells that name real tiles), and the reference
#           loader that turns a manifest into the "loaded result" every engine importer must reproduce
#           (frame rects and seconds, clip lengths, pivots, collision boxes, tile masks, map terrain resolved to tiles).
# Usage   : python tools/art/dotwork/assetspec.py validate assets/dotwork/*.assets.json   # exit 0 ok, 1 findings
#           python tools/art/dotwork/assetspec.py expected data/golden/dotwork/assets/dotwork/golden.assets.json
#           python tools/art/dotwork/assetspec.py --help
# Notes   : Standard library only, Python 3.8+, so an importer's test (any engine) and the kit's doctor can run it
#           without Dotwork's Pillow and numpy. The JSON Schema validator here covers the keywords the schema file
#           uses (type, enum, const, required, properties, additionalProperties, items, min/maxItems, minimum,
#           exclusiveMinimum, pattern, minLength, $ref, allOf, anyOf, if/then); any other keyword is an error, so
#           the schema cannot silently grow a rule this file ignores.
#           Pseudocode of the reference loader (expected):
#             for each asset by kind:
#               animated_sprite: per clip, each frame's rect and seconds (= hold / fps), length = sum, loop, pivot
#               sprite: size, pivot, collision rects; icon: sizes; portrait: expressions
#               tileset: tile count, masks per terrain, collision and animated tile counts
#               map: per terrain layer, each cell's key (blob47 / sides4: the 8-neighbour mask, corner bits only
#                    with both sides; corners4: the corner bits of that mask) and the tile of that terrain with that
#                    key, picked among variants by probability with the cell's own roll (cell_roll, the same number
#                    in every engine); stamps layers expanded into their tiles; every placed cell of every layer with
#                    the pixel corner its image is drawn at (cell_centre minus the tile's origin); tile layers
#                    counted; objects listed
#               font: metrics and one sample glyph; ui_kit: margins and hotspots; background: layer motion
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): the corners4 rule, isometric
#           placement, the variant pick, stamps layers, placed cells in the loaded result
# ---------------------------------------------------------------------------
import argparse
import json
import math
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(HERE, "asset_manifest.schema.json")

FORMAT = "dotwork-assets"
VERSION = "1.1.0"          # MAJOR.MINOR.PATCH: an importer reads every manifest of its own major version
SUFFIX = ".assets.json"    # <assets_dir>/dotwork/<pack>.assets.json
KINDS = ("animated_sprite", "sprite", "icon", "portrait", "tileset", "map", "font", "ui_kit",   # core: every importer
         "background", "particles", "transition", "normal_map", "image")                       # extra: may be skipped
CORE_KINDS = KINDS[:8]
DIRECTIONS = ("s", "e", "n", "w", "se", "ne", "nw", "sw")
LAYER_KINDS = ("tiles", "terrain", "stamps")   # stamps since 1.1.0

# 8-neighbour autotile masks. Bit order N, NE, E, SE, S, SW, W, NW: a set bit means that neighbour holds the same
# terrain. Godot's Match Corners and Sides and Dotwork's lane_ground use this order (lane_ground.NB8).
NB8 = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))
BIT = {"n": 1, "ne": 2, "e": 4, "se": 8, "s": 16, "sw": 32, "w": 64, "nw": 128}
SIDES_ONLY = BIT["n"] | BIT["e"] | BIT["s"] | BIT["w"]
CORNERS_ONLY = BIT["ne"] | BIT["se"] | BIT["sw"] | BIT["nw"]
SQUARE_CORNERS = ("top_left", "top_right", "bottom_left", "bottom_right")
ISO_CORNERS = ("top", "right", "bottom", "left")
# a cell's corner, named per shape, and the mask bit of the neighbour across it (the diagonal cell); on a diamond
# the NW cell is up the screen (top), NE is right, SE is bottom, SW is left (Godot's get_neighbor_cell, 2026-11-11)
CORNER_BITS = {"square": {"top_left": BIT["nw"], "top_right": BIT["ne"], "bottom_right": BIT["se"], "bottom_left": BIT["sw"]},
               "isometric": {"top": BIT["nw"], "right": BIT["ne"], "bottom": BIT["se"], "left": BIT["sw"]}}
M32 = 0xFFFFFFFF


class SpecError(Exception):
    """A usage or environment problem (exit 2)."""


# ---- autotile ------------------------------------------------------------------------------
def canon(m):
    """A corner bit only counts when both sides next to it are set: 256 raw masks fold into the 47 blob masks."""
    for c in (1, 3, 5, 7):
        if not ((m >> ((c + 7) % 8)) & 1 and (m >> ((c + 1) % 8)) & 1):
            m &= ~(1 << c)
    return m


BLOB = tuple(sorted({canon(m) for m in range(256)}))   # the 47 masks; 255 = surrounded on all sides


def cell_mask(painted, x, y, mode="blob47"):
    """The key a painted cell at (x, y) needs, from the set of painted (x, y) cells of the same terrain: blob47 the
    canon mask, sides4 the four side bits, corners4 the four corner bits of the canon mask (a corner is the terrain
    only when all four cells meeting there are painted: what Godot's Match Corners painting does over a base fill,
    probed on 4.7.2, 2026-11-11)."""
    m = 0
    for b, (dx, dy) in enumerate(NB8):
        if (x + dx, y + dy) in painted:
            m |= 1 << b
    if mode == "sides4":
        return m & SIDES_ONLY
    if mode == "corners4":
        return canon(m) & CORNERS_ONLY
    return canon(m)


def corners_of(key, shape, terrain):
    """A corners4 cell key -> {corner name: terrain or -1}: the painted terrain where the corner's bit is set, -1 (any
    other terrain) where not. A tile matches when its corners equal the terrain exactly where the key says."""
    return {name: (terrain if key & bit else -1) for name, bit in CORNER_BITS.get(shape, CORNER_BITS["square"]).items()}


def tile_key(tile, mode, shape):
    """The key a tileset tile answers to: its mask (blob47, sides4), or the corner bits of its own terrain (corners4);
    None when it has neither."""
    if mode in ("blob47", "sides4"):
        return tile.get("mask")
    corners = tile.get("corners")
    if corners is None:
        return None
    names = CORNER_BITS.get(shape, CORNER_BITS["square"])
    if set(corners) != set(names):
        return None
    return sum(bit for name, bit in names.items() if corners[name] == tile["terrain"])


# ---- deterministic variant pick ----------------------------------------------------------------
def hash32(k):
    """Bob Jenkins' 32-bit integer hash (six shifts): only shifts, adds and xors, every step kept to 32 bits, so a
    port needs no 64-bit multiply (Lua's doubles, JavaScript's int32 ops and C's uint32_t all agree)."""
    k &= M32
    k = (k + 0x7ED55D16 + (k << 12)) & M32
    k = (k ^ 0xC761C23C ^ (k >> 19)) & M32
    k = (k + 0x165667B1 + (k << 5)) & M32
    k = ((k + 0xD3A2646C) ^ (k << 9)) & M32
    k = (k + 0xFD7046C5 + (k << 3)) & M32
    k = (k ^ 0xB55A4F09 ^ (k >> 16)) & M32
    return k


def cell_roll(x, y, layer):
    """The roll in [0, 1) that picks a terrain cell's variant: from the cell and the index of its layer in the map's
    layers list, the same number in every engine (negative or huge coordinates wrap at 16 bits)."""
    return hash32(hash32(((x & 0xFFFF) << 16) | (y & 0xFFFF)) + layer) / 4294967296.0


def pick_variant(candidates, roll):
    """candidates: [(weight, value)] in atlas order; the value whose weight span holds roll * total (the sum of the
    weights), the first when every weight is 0. Weight 0 is never picked."""
    total = sum(w for w, _ in candidates)
    if total <= 0:
        return candidates[0][1]
    u = roll * total
    for w, v in candidates:
        u -= w
        if u < 0:
            return v
    return candidates[-1][1]


# ---- cells on the screen -----------------------------------------------------------------------
def cell_centre(shape, x, y, tile_size):
    """The centre of map cell (x, y) in map pixels (y down): squares in rows, isometric diamonds in Godot's
    diamond-down layout (x runs down-right, y down-left; cell (0, 0) at (w/2, h/2), as TileMapLayer.map_to_local
    gives on 4.7.2, 2026-11-11). A tile's image is drawn with its origin on this point."""
    w, h = tile_size
    if shape == "isometric":
        return [(x - y + 1) * w / 2, (x + y + 1) * h / 2]
    return [(x + 0.5) * w, (y + 0.5) * h]


def tile_origin(tile, atlas):
    """The image point drawn on the cell centre: the tile's own origin, else the centre of the atlas tile."""
    if tile.get("origin"):
        return list(tile["origin"])
    return [atlas["tile_size"][0] / 2, atlas["tile_size"][1] / 2]


# ---- files ---------------------------------------------------------------------------------
def png_size(path):
    """(width, height) from a PNG's IHDR chunk, without decoding it."""
    with open(path, "rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise ValueError(f"{path}: not a PNG")
    return struct.unpack(">II", head[16:24])


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise SpecError(f"{path} not found")
    except ValueError as exc:
        raise SpecError(f"{path} is not valid JSON: {exc}")


def schema():
    return load(SCHEMA_PATH)


def base_dir(manifest_path, doc):
    """The folder every path in the manifest is relative to: the manifest's folder joined with its "base"."""
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(manifest_path)), doc.get("base", ".")))


# ---- JSON Schema (the subset the schema file uses) -----------------------------------------
KNOWN = {"$schema", "$id", "$defs", "$comment", "title", "description", "type", "enum", "const", "required",
         "properties", "additionalProperties", "items", "minItems", "maxItems", "minimum", "exclusiveMinimum",
         "pattern", "minLength", "$ref", "allOf", "anyOf", "if", "then"}
TYPES = {"object": dict, "array": list, "string": str, "boolean": bool}


def _is(v, t):
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    if t == "null":
        return v is None
    return isinstance(v, TYPES[t])


def check_schema(v, s, root, where="$", out=None):
    """Errors of v against schema s (root holds $defs), as "path: message" strings."""
    out = [] if out is None else out
    unknown = set(s) - KNOWN
    if unknown:
        raise SpecError(f"schema at {where}: keywords this validator does not implement: {sorted(unknown)}")
    if "$ref" in s:
        ref = s["$ref"]
        if not ref.startswith("#/$defs/"):
            raise SpecError(f"schema: only #/$defs/ references are supported ({ref})")
        check_schema(v, root["$defs"][ref[len("#/$defs/"):]], root, where, out)
    if "type" in s:
        ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_is(v, t) for t in ts):
            out.append(f"{where}: expected {' or '.join(ts)}, got {type(v).__name__}")
            return out
    if "const" in s and v != s["const"]:
        out.append(f"{where}: must be {s['const']!r}")
    if "enum" in s and v not in s["enum"]:
        out.append(f"{where}: {v!r} is not one of {s['enum']}")
    if isinstance(v, str):
        if "minLength" in s and len(v) < s["minLength"]:
            out.append(f"{where}: shorter than {s['minLength']}")
        if "pattern" in s and not re.search(s["pattern"], v):
            out.append(f"{where}: {v!r} does not match {s['pattern']}")
    if _is(v, "number"):
        if "minimum" in s and v < s["minimum"]:
            out.append(f"{where}: {v} is below {s['minimum']}")
        if "exclusiveMinimum" in s and v <= s["exclusiveMinimum"]:
            out.append(f"{where}: {v} must be above {s['exclusiveMinimum']}")
    if isinstance(v, list):
        if "minItems" in s and len(v) < s["minItems"]:
            out.append(f"{where}: {len(v)} items, at least {s['minItems']}")
        if "maxItems" in s and len(v) > s["maxItems"]:
            out.append(f"{where}: {len(v)} items, at most {s['maxItems']}")
        if "items" in s:
            for i, x in enumerate(v):
                check_schema(x, s["items"], root, f"{where}[{i}]", out)
    if isinstance(v, dict):
        for k in s.get("required", ()):
            if k not in v:
                out.append(f"{where}: missing {k!r}")
        props = s.get("properties", {})
        for k, x in v.items():
            if k in props:
                check_schema(x, props[k], root, f"{where}.{k}", out)
            elif s.get("additionalProperties") is False:
                out.append(f"{where}: unknown key {k!r}")
            elif isinstance(s.get("additionalProperties"), dict):
                check_schema(x, s["additionalProperties"], root, f"{where}.{k}", out)
    for sub in s.get("allOf", ()):
        check_schema(v, sub, root, where, out)
    if "anyOf" in s:
        if not any(not check_schema(v, sub, root, where, []) for sub in s["anyOf"]):
            out.append(f"{where}: matches none of the allowed forms")
    if "if" in s and not check_schema(v, s["if"], root, where, []):
        check_schema(v, s.get("then", {}), root, where, out)
    return out


# ---- semantic checks --------------------------------------------------------------------------
def _safe_path(p):
    parts = p.split("/")
    return not (p.startswith("/") or "\\" in p or ":" in p or ".." in parts or "" in parts)


def _in_rect(rect, w, h):
    x, y, rw, rh = rect
    return x >= 0 and y >= 0 and x + rw <= w and y + rh <= h


def check(doc, base=None, sch=None):
    """Every finding for one manifest: schema first, then what a schema cannot say. base: the folder paths are
    relative to (None skips the file checks)."""
    sch = sch or schema()
    errs = check_schema(doc, sch, sch)
    if errs:
        return errs
    major = doc["version"].split(".")[0]
    if major != VERSION.split(".")[0]:
        return [f"$.version: {doc['version']} is major {major}; this validator reads {VERSION.split('.')[0]}.x"]
    sizes = {}

    def file_size(p, where):
        """(w, h) of a PNG, or None after logging why (missing, unsafe path, not a PNG)."""
        if not _safe_path(p):
            errs.append(f"{where}: {p!r} must be a relative path with forward slashes and no '..'")
            return None
        if base is None:
            return None
        if p not in sizes:
            full = os.path.join(base, *p.split("/"))
            if not os.path.isfile(full):
                errs.append(f"{where}: {p} not found under {base}")
                sizes[p] = None
            elif p.lower().endswith(".png"):
                try:
                    sizes[p] = png_size(full)
                except ValueError as exc:
                    errs.append(f"{where}: {exc}")
                    sizes[p] = None
            else:
                sizes[p] = ()
        return sizes[p]

    def png(p, where, want=None):
        got = file_size(p, where)
        if got and want and tuple(want) != tuple(got):
            errs.append(f"{where}: {p} is {got[0]}x{got[1]}, the manifest says {want[0]}x{want[1]}")
        return got

    names = {}
    for i, a in enumerate(doc["assets"]):
        w = f"$.assets[{i}] {a['kind']} {a['name']}"
        if (a["kind"], a["name"]) in names:
            errs.append(f"{w}: a second {a['kind']} named {a['name']!r}")
        names[(a["kind"], a["name"])] = a
        _check_asset(a, w, png, file_size, errs)
    tilesets = {a["name"]: a for a in doc["assets"] if a["kind"] == "tileset"}
    for i, a in enumerate(doc["assets"]):
        w = f"$.assets[{i}] {a['kind']} {a['name']}"
        if a["kind"] == "map":
            _check_map(a, w, tilesets, names, errs)
        if a["kind"] == "portrait" and a.get("animation") and ("animated_sprite", a["animation"]) not in names:
            errs.append(f"{w}: animation {a['animation']!r} is not an animated_sprite in this manifest")
    return errs


def _check_asset(a, w, png, file_size, errs):
    k = a["kind"]
    if k == "animated_sprite":
        seen = set()
        for c in a["clips"]:
            cw = f"{w} clip {c['name']}"
            if c["name"] in seen:
                errs.append(f"{cw}: a second clip with this name")
            seen.add(c["name"])
            fw, fh = c["frame_size"]
            holds = c.get("holds")
            if holds is not None and len(holds) != len(c["frames"]):
                errs.append(f"{cw}: {len(holds)} holds for {len(c['frames'])} frames")
                holds = None
            sheet = png(c["sheet"], cw) if c.get("sheet") else None
            total = 0.0
            for j, f in enumerate(c["frames"]):
                hold = holds[j] if holds else 1.0
                if not math.isclose(f["duration"], hold / c["fps"], rel_tol=1e-6, abs_tol=1e-9):
                    errs.append(f"{cw} frame {j}: duration {f['duration']} is not hold {hold} / fps {c['fps']}")
                total += f["duration"]
                if f["rect"][2:] != [fw, fh]:
                    errs.append(f"{cw} frame {j}: rect size {f['rect'][2:]} differs from frame_size {[fw, fh]}")
                fs = png(f["file"], f"{cw} frame {j}", (fw, fh))
                if sheet and not _in_rect(f["rect"], *sheet):
                    errs.append(f"{cw} frame {j}: rect {f['rect']} leaves the {sheet[0]}x{sheet[1]} sheet")
                if not c.get("sheet") and fs and f["rect"] != [0, 0, fw, fh]:
                    errs.append(f"{cw} frame {j}: without a sheet the rect is the whole file, [0, 0, {fw}, {fh}]")
            if not math.isclose(total, c["length"], rel_tol=1e-6, abs_tol=1e-9):
                errs.append(f"{cw}: length {c['length']} is not the sum of its frame durations ({total})")
        for action, dirs in (a.get("directions") or {}).items():
            for d, clip in dirs.items():
                if d not in DIRECTIONS:
                    errs.append(f"{w}: direction {d!r} of {action} is not one of {list(DIRECTIONS)}")
                if clip not in seen:
                    errs.append(f"{w}: direction {action}/{d} names clip {clip!r}, which is not in clips")
    elif k == "sprite":
        png(a["image"], w, a["size"])
        if not _in_rect(a["content_rect"], *a["size"]):
            errs.append(f"{w}: content_rect {a['content_rect']} leaves the image")
        if a.get("shadow"):
            png(a["shadow"]["image"], f"{w} shadow")
    elif k == "icon":
        for s in a["sizes"]:
            png(s["image"], f"{w} {s['size']} px", (s["size"], s["size"]))
    elif k == "portrait":
        for e in a["expressions"]:
            png(e["image"], f"{w} {e['name']}", a["size"])
    elif k == "tileset":
        _check_tileset(a, w, png, errs)
    elif k == "font":
        file_size(a["file"], w)
        for p in a["pages"]:
            png(p, w)
        ids = [c[0] for c in a["chars"]]
        if len(set(ids)) != len(ids):
            errs.append(f"{w}: a character id appears twice")
        for c in a["chars"]:
            if c[8] >= len(a["pages"]):
                errs.append(f"{w}: char {c[0]} is on page {c[8]}; the font has {len(a['pages'])}")
        if a.get("license"):
            file_size(a["license"], w)
    elif k == "ui_kit":
        for p in a["parts"]:
            png(p["image"], f"{w} {p['name']}", p["size"])
            m = p.get("margins")
            if m and (m[0] + m[2] > p["size"][0] or m[1] + m[3] > p["size"][1]):
                errs.append(f"{w} {p['name']}: margins {m} are wider than the {p['size']} image")
    elif k == "background":
        for j, L in enumerate(a["layers"]):
            png(L["image"], f"{w} layer {j}", L["size"])
    elif k == "particles":
        png(a["texture"], w)
    elif k in ("transition", "normal_map", "image"):
        png(a["image"], w, a.get("size"))
        if k == "normal_map":
            file_size(a["target"], w)


def _check_tileset(a, w, png, errs):
    terrains = {}
    for ts in a["terrain_sets"]:
        for t in ts["terrains"]:
            terrains[(ts["id"], t["id"])] = ts["mode"]
    if len({ts["id"] for ts in a["terrain_sets"]}) != len(a["terrain_sets"]):
        errs.append(f"{w}: two terrain sets share an id")
    for at in a["atlases"]:
        aw = f"{w} atlas {at['name']}"
        size = png(at["image"], aw)
        tw, th = at["tile_size"]
        if size and (at["columns"] * tw > size[0] or at["rows"] * th > size[1]):
            errs.append(f"{aw}: {at['columns']}x{at['rows']} tiles of {tw}x{th} do not fit the {size[0]}x{size[1]} image")
        cells = set()
        for t in at["tiles"]:
            tw_ = f"{aw} tile {t['col']},{t['row']}"
            span = (t.get("anim") or {}).get("frames", 1)
            if t["col"] + span > at["columns"] or t["row"] >= at["rows"]:
                errs.append(f"{tw_}: outside the atlas grid ({at['columns']}x{at['rows']})")
            if (t["col"], t["row"]) in cells:
                errs.append(f"{tw_}: listed twice")
            cells.add((t["col"], t["row"]))
            if "terrain" in t:
                key = (t.get("terrain_set", 0), t["terrain"])
                mode = terrains.get(key)
                if mode is None:
                    errs.append(f"{tw_}: terrain {key[1]} of set {key[0]} is not defined")
                elif mode == "blob47" and t.get("mask") not in BLOB:
                    errs.append(f"{tw_}: mask {t.get('mask')} is not one of the 47 blob masks")
                elif mode == "sides4" and (t.get("mask") is None or t["mask"] & ~SIDES_ONLY):
                    errs.append(f"{tw_}: a sides4 mask uses only the N, E, S and W bits")
                elif mode == "corners4" and set(t.get("corners") or ()) != set(CORNER_BITS.get(a["shape"], {})):
                    errs.append(f"{tw_}: a corners4 tile on a {a['shape']} set names the corners "
                                f"{sorted(CORNER_BITS.get(a['shape'], {}))}")
            for s in t.get("collision") or []:
                x, y, cw, ch = s["rect"]
                if x < 0 or y < 0 or x + cw > tw or y + ch > th:
                    errs.append(f"{tw_}: collision {s['rect']} leaves the {tw}x{th} tile")
    for st in a.get("stamps") or []:
        if len(st["tiles"]) != st["size"][0] * st["size"][1]:
            errs.append(f"{w} stamp {st['name']}: {len(st['tiles'])} tiles for a {st['size']} block")


def _tile_index(ts):
    """{(atlas, col, row): tile} of a tileset asset."""
    return {(at["id"], t["col"], t["row"]): t for at in ts["atlases"] for t in at["tiles"]}


def _check_map(a, w, tilesets, names, errs):
    ts = tilesets.get(a["tileset"])
    if ts is None:
        errs.append(f"{w}: tileset {a['tileset']!r} is not in this manifest")
        return
    tiles = _tile_index(ts)
    modes = {(s["id"], t["id"]): s["mode"] for s in ts["terrain_sets"] for t in s["terrains"]}
    stamps = ts.get("stamps") or []
    mw, mh = a["size"]
    for i, L in enumerate(a["layers"]):
        lw = f"{w} layer {L['name']}"
        for c in L["cells"]:
            if not (0 <= c[0] < mw and 0 <= c[1] < mh):
                errs.append(f"{lw}: cell {c[:2]} is outside the {mw}x{mh} map")
                break
            if L["kind"] == "tiles" and (len(c) < 5 or tuple(c[2:5]) not in tiles):
                errs.append(f"{lw}: cell {c[:2]} names tile {c[2:5]}, which the tileset does not have")
                break
            if L["kind"] == "stamps":
                if len(c) < 3 or c[2] >= len(stamps):
                    errs.append(f"{lw}: cell {c[:2]} names stamp {c[2:3]}; the tileset has {len(stamps)}")
                    break
                sw, sh = stamps[c[2]]["size"]
                if c[0] + sw > mw or c[1] + sh > mh:
                    errs.append(f"{lw}: stamp {stamps[c[2]]['name']} at {c[:2]} leaves the {mw}x{mh} map")
                    break
        if L["kind"] == "terrain":
            if (L.get("terrain_set", 0), L["terrain"]) not in modes:
                errs.append(f"{lw}: terrain {L['terrain']} is not in tileset {ts['name']}")
            else:
                bad = [f"{x},{y}" for x, y, _, tile in resolve_terrain(ts, L, i) if tile is None]
                if bad:
                    errs.append(f"{lw}: no tile for {len(bad)} cell(s) ({', '.join(bad[:6])}): a corners4 terrain "
                                f"needs shapes at least 2 cells thick, a blob needs all 47 masks")
    for o in a.get("objects") or []:
        if not any(n == o["asset"] for (_, n) in names):
            errs.append(f"{w}: object {o['asset']!r} is not an asset in this manifest")


# ---- the reference loader --------------------------------------------------------------------
def _r(x):
    """Numbers in the loaded result: 6 decimals, integers stay integers."""
    x = round(float(x), 6)
    return int(x) if x == int(x) else x


def resolve_terrain(ts, layer, layer_index=0):
    """Each painted cell of a terrain layer -> [x, y, key, [atlas, col, row]] (sorted by y, then x): the key is
    cell_mask's (the mask, or the corner bits), the tile is picked among the layer's terrain's tiles with that key
    (atlas order) by probability with the cell's roll (cell_roll(x, y, layer_index)), None when no tile has the key.
    Godot rolls its own dice among the same tiles, so a Godot map and another engine's map agree in shape, and the
    other engines agree with each other in variants too."""
    sid, tid = layer.get("terrain_set", 0), layer["terrain"]
    mode = next(s["mode"] for s in ts["terrain_sets"] if s["id"] == sid)
    by_key = {}
    for at in ts["atlases"]:
        for t in at["tiles"]:
            if t.get("terrain") == tid and t.get("terrain_set", 0) == sid:
                k = tile_key(t, mode, ts.get("shape", "square"))
                if k is not None:
                    by_key.setdefault(k, []).append((t.get("probability", 1), [at["id"], t["col"], t["row"]]))
    painted = {(c[0], c[1]) for c in layer["cells"]}
    out = []
    for x, y in sorted(painted, key=lambda p: (p[1], p[0])):
        k = cell_mask(painted, x, y, mode)
        cands = by_key.get(k)
        out.append([x, y, k, pick_variant(cands, cell_roll(x, y, layer_index)) if cands else None])
    return out


def expand_stamps(ts, layer):
    """Each [x, y, stamp] of a stamps layer -> the stamp's tiles as [x, y, atlas, col, row] in reading order (tile j
    at (x + j % w, y + j // w)), in the order of the layer's cells."""
    stamps = ts.get("stamps") or []
    out = []
    for c in layer["cells"]:
        st = stamps[c[2]]
        sw = st["size"][0]
        for j, (atlas, col, row) in enumerate(st["tiles"]):
            out.append([c[0] + j % sw, c[1] + j // sw, atlas, col, row])
    return out


def placed_cells(ts, layer, layer_index):
    """Every cell a layer draws, as [x, y, atlas, col, row]: tiles layers as they are (flags dropped), terrain layers
    resolved (cells with no tile left out), stamps layers expanded."""
    if layer["kind"] == "terrain":
        return [[x, y] + tile for x, y, _, tile in resolve_terrain(ts, layer, layer_index) if tile]
    if layer["kind"] == "stamps":
        return expand_stamps(ts, layer)
    return [list(c[:5]) for c in layer["cells"]]


def draw_corner(ts, shape, tile_size, cell):
    """Where a placed cell's image lands: [left, top] in map pixels, the cell centre less the tile's origin (the atlas
    tile's centre unless the tile sets its own, as an iso block does)."""
    x, y, aid, col, row = cell
    atlas = next(a for a in ts["atlases"] if a["id"] == aid)
    tile = next((t for t in atlas["tiles"] if t["col"] == col and t["row"] == row), {})
    cx, cy = cell_centre(shape, x, y, tile_size)
    ox, oy = tile_origin(tile, atlas)
    return [_r(cx - ox), _r(cy - oy)]


def expected(doc):
    """The loaded result of a manifest: what each engine's importer turns into its own objects, as plain numbers.
    Importer tests load data/golden/dotwork/ and compare their objects with this (golden expected.json)."""
    out = {}
    tilesets = {a["name"]: a for a in doc["assets"] if a["kind"] == "tileset"}
    for a in doc["assets"]:
        k, key = a["kind"], f"{a['kind']}/{a['name']}"
        if k == "animated_sprite":
            clips = {}
            for c in a["clips"]:
                secs = [_r(f["duration"]) for f in c["frames"]]
                clips[c["name"]] = {"frames": len(c["frames"]), "rects": [f["rect"] for f in c["frames"]],
                                    "seconds": secs, "length": _r(sum(f["duration"] for f in c["frames"])),
                                    "loop": c["loop"], "pivot": [_r(v) for v in c["pivot"]],
                                    "texture": c.get("sheet") or None}
            out[key] = {"blend": a.get("blend", "normal"), "clips": clips, "directions": a.get("directions") or {}}
        elif k == "sprite":
            out[key] = {"size": a["size"], "pivot": [_r(v) for v in a["pivot"]],
                        "collision": [[_r(v) for v in s["rect"]] for s in a.get("collision") or []]}
        elif k == "icon":
            out[key] = {"sizes": sorted(s["size"] for s in a["sizes"])}
        elif k == "portrait":
            out[key] = {"size": a["size"], "expressions": sorted(e["name"] for e in a["expressions"]),
                        "animation": a.get("animation")}
        elif k == "tileset":
            masks, coll, anim, n = {}, 0, 0, 0
            for at in a["atlases"]:
                for t in at["tiles"]:
                    n += 1
                    coll += bool(t.get("collision"))
                    anim += bool(t.get("anim"))
                    if "terrain" in t:
                        tk = f"{t.get('terrain_set', 0)}/{t['terrain']}"
                        v = t["mask"] if "mask" in t else [t["corners"][c] for c in sorted(t["corners"])]
                        masks.setdefault(tk, [])
                        if v not in masks[tk]:
                            masks[tk].append(v)
            out[key] = {"tile_size": a["tile_size"], "shape": a["shape"], "tiles": n, "collision_tiles": coll,
                        "animated_tiles": anim,
                        "terrains": {f"{s['id']}/{t['id']}": t["name"] for s in a["terrain_sets"] for t in s["terrains"]},
                        "masks": {tk: sorted(v) for tk, v in sorted(masks.items())}}
        elif k == "map":
            ts = tilesets.get(a["tileset"])
            shape = ts.get("shape", "square") if ts else "square"
            layers, terrain, placed = {}, {}, {}
            for i, L in enumerate(a["layers"]):
                if ts:
                    cells = placed_cells(ts, L, i)
                    layers[L["name"]] = len(cells)
                    placed[L["name"]] = [c + draw_corner(ts, shape, a["tile_size"], c) for c in cells]
                    if L["kind"] == "terrain":
                        terrain[L["name"]] = resolve_terrain(ts, L, i)
                else:
                    layers[L["name"]] = len(L["cells"])
            mw, mh = a["size"]
            out[key] = {"size": a["size"], "shape": shape, "tile_size": a["tile_size"], "layers": layers,
                        "terrain": terrain, "placed": placed,
                        "centres": [[x, y] + [_r(v) for v in cell_centre(shape, x, y, a["tile_size"])]
                                    for y in range(mh) for x in range(mw)],
                        "objects": [[o["asset"], _r(o["x"]), _r(o["y"])] for o in a.get("objects") or []]}
        elif k == "font":
            sample = next((c for c in a["chars"] if c[0] == 65), a["chars"][0] if a["chars"] else None)
            out[key] = {"line_height": a["line_height"], "base": a["base"], "chars": len(a["chars"]),
                        "pages": len(a["pages"]), "sample": sample}
        elif k == "ui_kit":
            out[key] = {"parts": {p["name"]: {"size": p["size"], "margins": p.get("margins"),
                                              "hotspot": p.get("hotspot")} for p in a["parts"]}}
        elif k == "background":
            out[key] = {"layers": [[L["size"][0], L["size"][1], _r(L["velocity"][0]), _r(L["velocity"][1]),
                                    L["repeat"]] for L in a["layers"]]}
        else:
            out[key] = {"kind": k}
    return {"format": FORMAT + "-expected", "version": doc["version"], "pack": doc["pack"],
            "assets": dict(sorted(out.items()))}


# ---- command line ------------------------------------------------------------------------------
def cmd_validate(a):
    sch, bad = schema(), 0
    for p in a.files:
        doc = load(p)
        errs = check(doc, None if a.no_files else base_dir(p, doc), sch)
        if errs:
            bad += 1
            print(f"[fail] {p}: {len(errs)} findings")
            for e in errs[:a.max]:
                print(f"  {e}")
        else:
            print(f"[ OK ] {p}: {len(doc['assets'])} assets, version {doc['version']}")
    return 1 if bad else 0


def cmd_expected(a):
    print(json.dumps(expected(load(a.file)), indent=1))
    return 0


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="Validate Dotwork's engine-neutral asset manifests (<assets>/dotwork/<pack>.assets.json, "
                    "spec: ASSET_MANIFEST.md) and print the loaded result importers must match. "
                    "Exit 0 ok, 1 findings, 2 usage.")
    ap.add_argument("--debug", action="store_true", help="show tracebacks")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("validate", help="schema + files + autotile and map checks for each manifest")
    p.add_argument("files", nargs="+", help="manifest files")
    p.add_argument("--no-files", action="store_true", help="skip the checks that open files (schema and logic only)")
    p.add_argument("--max", type=int, default=40, help="findings shown per file (default 40)")
    p = sub.add_parser("expected", help="print the reference loader's result for one manifest (JSON)")
    p.add_argument("file")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    try:
        return {"validate": cmd_validate, "expected": cmd_expected}[a.cmd](a)
    except SpecError as exc:
        if a.debug:
            raise
        print(f"[error] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
