#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# pxo_tiles.py
# Purpose : Pixelorama tilemap layers (pixelorama.py's tilemap half): read a .pxo's tilesets and tilemap cels, draw
#           them as Pixelorama does (each cell's tile, flipped and transposed), and turn a tilemap project under
#           <src_dir>/pixelorama/tilemaps/ into game files. Two kinds of tilemap project:
#           - your own (made in Pixelorama): tileset atlas PNGs at the project's tile size, a Godot TileSet (Dotwork's
#             writer: terrains, probabilities, a "surface" custom data layer and full-tile collision from each tile's
#             user data), a TileMapLayer scene per frame and a JSON map, under <art_dir>/tilemaps/<name>/;
#           - one Dotwork built from a game's map scene (mapbuild) or TileSet (dotwork.py pixelorama): the re-export
#             puts edited tiles back into their atlas slots and edited cells back into the map scene; the TileSet
#             itself is never rewritten.
# Usage   : imported by pixelorama.py (read_pxo composites tilemap layers; build and reexport handle tilemaps/)
# Notes   : The format is Pixelorama 1.2.4's (src/Classes/TileSetCustom.gd, Cels/CelTileMap.gd, Layers/LayerTileMap.gd,
#           Autoload/OpenSave.gd): data.json "tilesets" [{name, tile_size "(16, 16)", tile_amount, tile_shape,
#           tile_data {index: {probability, user_data, terrain_center_bit, terrain_peering_bits[16]}}, terrain_data
#           [{name, color}]}], each tile a raw RGBA8 buffer at tilesets/<set>/<index> (tile 0 is the empty tile); a
#           tilemap layer (type 3) names its tileset_index; a tilemap cel keeps cell_data {"(x, y)": {index, flip_h,
#           flip_v, transpose}} and an offset in pixels. Pixelorama redraws a tilemap cel from its cells when it opens
#           the file (the cel's own buffer is not read), so Dotwork draws it the same way: tile at offset + cell x
#           tile size, transposed first (rotate 90 counter-clockwise, then flip vertically), then flipped.
#           Godot draws a cell's FLIP_H / FLIP_V / TRANSPOSE alternative flags in that same order.
#           Pixelorama's Auto tile mode adds and removes tiles as you draw (indices shift), so a Dotwork-built
#           project names each tile's atlas slot in its user data ("dotwork:<source>:<x>:<y>:<hash>", the hash of the
#           tile as built): edits are what differs from the hash, wherever the tile moved to.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import base64
import glob
import hashlib
import io
import json
import math
import os
import re
import struct
import zipfile

import numpy as np
from PIL import Image

import fcore as core
import godot
import handpolish

MAX_TILES = 4096                 # tiles in one tileset
MAX_TILE_SIDE = 512              # px
MAX_CELLS = 1 << 20              # cells in one tilemap cel
ATLAS_COLUMNS = 16               # tiles per atlas row (fixed, so a tile added later moves no other tile)
SQUARE = 0                       # TileSet.TILE_SHAPE_SQUARE: the only shape read
LAYER_TILEMAP = 3                # Global.LayerTypes.TILEMAP
# TileSet.CellNeighbor: Pixelorama's terrain_peering_bits are indexed by it; a square tile uses these eight
NEIGHBOUR = {0: "right_side", 3: "bottom_right_corner", 4: "bottom_side", 7: "bottom_left_corner", 8: "left_side",
             11: "top_left_corner", 12: "top_side", 15: "top_right_corner"}
PEERS8 = (12, 15, 0, 3, 4, 7, 8, 11)   # godot.PEERS8 order (N, NE, E, SE, S, SW, W, NW) as CellNeighbor indices
FLIP_H, FLIP_V, TRANSPOSE = 1 << 12, 1 << 13, 1 << 14   # TileSetAtlasSource.TRANSFORM_* (alternative id flags)
SOLID = "solid"                  # a tile whose user data has this word gets a full-tile collision box
TAG = re.compile(r"dotwork:(\d+):(\d+):(\d+):([0-9a-f]{16})")
META = "dotwork"                 # project metadata key of a Dotwork-built tilemap project (JSON text)
NOTE = "hand-polished in Pixelorama"
OWN_WORKFLOW = "Pixelorama tilemap (drawn by hand), re-exported by Dotwork"


def _px():
    import pixelorama
    return pixelorama


# -------------------------------------------------- reading
def tilesets(z, d, rel):
    """The project's tilesets: [{"name", "size": (w, h), "shape", "tiles": [h x w x 4 uint8, tile 0 the empty one],
    "data": [{"probability", "user_data", "center", "peers": [16]}], "terrains": [(name, (r, g, b))]}]. Sizes are
    checked before any tile buffer is read."""
    px = _px()
    raw = d.get("tilesets") or []
    if not isinstance(raw, list) or len(raw) > px.MAX_LAYERS:
        px._fail(rel, "tilesets is not a list of at most %d" % px.MAX_LAYERS)
    out, total = [], 0
    for i, t in enumerate(raw):
        if not isinstance(t, dict):
            px._fail(rel, f"tileset {i} is not an object")
        tw, th = px._vec2i(t.get("tile_size"), rel, f"tileset {i} tile_size")
        if not (1 <= tw <= MAX_TILE_SIDE and 1 <= th <= MAX_TILE_SIDE):
            px._fail(rel, f"tileset {i}: tiles of {tw}x{th} (1 to {MAX_TILE_SIDE} px a side)")
        n = int(px._number(t.get("tile_amount", 0), rel, f"tileset {i} tile_amount", 0, MAX_TILES))
        total += n * tw * th * 4
        out.append({"name": str(t.get("name") or ""), "size": (tw, th), "shape": t.get("tile_shape", SQUARE),
                    "amount": n, "raw": t})
    if total > px.MAX_UNPACKED:
        px._fail(rel, f"its tilesets would unpack to {px._mb(total)} (over {px._mb(px.MAX_UNPACKED)})")
    for i, ts in enumerate(out):
        tw, th = ts["size"]
        t = ts.pop("raw")
        data = t.get("tile_data") or {}
        if not isinstance(data, dict):
            px._fail(rel, f"tileset {i}: tile_data is not an object")
        ts["tiles"], ts["data"] = [], []
        for j in range(ts.pop("amount")):
            ts["tiles"].append(px._buffer(z, f"tilesets/{i}/{j}", tw, th, rel))
            td = data.get(str(j)) or {}
            if not isinstance(td, dict):
                px._fail(rel, f"tileset {i} tile {j}: its data is not an object")   # #246
            peers = td.get("terrain_peering_bits") or [-1] * 16
            if not isinstance(peers, list) or len(peers) > 16:
                px._fail(rel, f"tileset {i} tile {j}: terrain_peering_bits is not a list of 16")
            ts["data"].append({
                "probability": float(px._number(td.get("probability", 1.0), rel, f"tileset {i} tile {j} probability",
                                                0, 1e6)),
                "user_data": str(td.get("user_data") or ""),
                "center": int(px._number(td.get("terrain_center_bit", -1), rel, f"tileset {i} tile {j} terrain",
                                         -1, 255)),
                "peers": [int(px._number(b, rel, f"tileset {i} tile {j} peering bit", -1, 255)) for b in peers]
                + [-1] * (16 - len(peers))})
        terrains = []
        if not isinstance(t.get("terrain_data") or [], list):
            px._fail(rel, f"tileset {i}: terrain_data is not a list")   # #246
        for k, tr in enumerate(t.get("terrain_data") or []):
            if not isinstance(tr, dict):
                px._fail(rel, f"tileset {i}: terrain {k} is not an object")
            terrains.append((str(tr.get("name") or ""), _colour(tr.get("color"))))
        ts["terrains"] = terrains or [("", (128, 88, 64))]   # Pixelorama's default terrain (Color("805840"))
    return out


def _colour(text):
    """(r, g, b) bytes of a Godot Color as var_to_str writes it, "Color(0.5, 0.34, 0.25, 1)"; Pixelorama's default
    terrain colour when it cannot be read."""
    m = re.fullmatch(r"\s*(?:Color)?\(\s*([-\d.e]+)\s*,\s*([-\d.e]+)\s*,\s*([-\d.e]+)\s*(?:,\s*[-\d.e]+\s*)?\)\s*",
                     str(text or ""))
    if not m:
        return (128, 88, 64)
    try:
        vals = [float(v) for v in m.groups()]
    except ValueError:                      # #246: "Color(e, e, e, 1)" passed the pattern
        return (128, 88, 64)
    if not all(math.isfinite(v) for v in vals):
        return (128, 88, 64)
    return tuple(int(round(min(max(v, 0.0), 1.0) * 255)) for v in vals)


def layer_tileset(ly, sets, rel, name):
    """The tileset index a tilemap layer uses, refusing what Dotwork does not draw (an isometric or hexagonal layer,
    a place-only layer whose tile size is not its tileset's)."""
    px = _px()
    i = ly.get("tileset_index")
    if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(sets):
        px._fail(rel, f"tilemap layer {name}: tileset_index {i!r} is not a tileset of this project")
    shape = ly.get("tile_shape", SQUARE)
    if shape != SQUARE or sets[i]["shape"] != SQUARE:
        px._fail(rel, f"tilemap layer {name}: isometric and hexagonal tilemaps are not read (square tiles only)")
    if ly.get("place_only_mode") and "tile_size" in ly and \
            px._vec2i(ly["tile_size"], rel, f"layer {name} tile_size") != sets[i]["size"]:
        px._fail(rel, f"tilemap layer {name}: a place-only layer with a tile size of its own is not read")
    return i


def cells_of(cel, rel, where):
    """(offset (x, y) in pixels, {(x, y): (index, flip_h, flip_v, transpose)}) of a tilemap cel; cells of tile 0 (the
    empty tile) are left out, as Pixelorama skips them."""
    px = _px()
    off = px._vec2i(cel.get("offset", "(0, 0)"), rel, f"{where} offset")
    data = cel.get("cell_data") or {}
    if not isinstance(data, dict):
        px._fail(rel, f"{where}: cell_data is not an object")
    if len(data) > MAX_CELLS:
        px._fail(rel, f"{where}: {len(data)} cells (over {MAX_CELLS})")
    cells = {}
    for k, v in data.items():
        if not isinstance(v, dict):
            px._fail(rel, f"{where}: cell {k} is not an object")
        idx = v.get("index", 0)
        if isinstance(idx, bool) or not isinstance(idx, (int, float)) or not math.isfinite(idx) or idx != int(idx) \
                or idx < 0:   # #246: 1e999 and NaN crashed
            px._fail(rel, f"{where}: cell {k} has tile {idx!r}")
        if int(idx) == 0:
            continue
        cells[px._vec2i(k, rel, f"{where} cell")] = (int(idx), bool(v.get("flip_h")), bool(v.get("flip_v")),
                                                    bool(v.get("transpose")))
    return off, cells


def transform(tile, fh, fv, tr):
    """CelTileMap.transform_tile: transposed first, then flipped horizontally, then vertically."""
    if tr:
        tile = tile.transpose(1, 0, 2)
    if fh:
        tile = tile[:, ::-1]
    if fv:
        tile = tile[::-1]
    return tile


def render(ts, off, cells, w, h, rows=None):
    """A tilemap cel on the w x h canvas (CelTileMap._draw_cell: each tile copied, clear pixels too, in cell order;
    an index past the tileset draws the empty tile). rows: a (first, last) band of canvas rows, or None."""
    y0, y1 = rows or (0, h)
    out = np.zeros((y1 - y0, w, 4), np.uint8)
    tw, th = ts["size"]
    for (cx, cy) in sorted(cells):
        idx, fh, fv, tr = cells[(cx, cy)]
        if idx >= len(ts["tiles"]):
            idx = 0
        tile = transform(ts["tiles"][idx], fh, fv, tr)
        # (transformed size - tile size) / 2 as Godot's Vector2i divides: toward zero (a transposed 8x5 tile)
        x = off[0] + cx * tw - int((tile.shape[1] - tw) / 2)
        y = off[1] + cy * th - int((tile.shape[0] - th) / 2)
        a0, a1, b0, b1 = max(x, 0), min(x + tile.shape[1], w), max(y, y0), min(y + tile.shape[0], y1)
        if a1 > a0 and b1 > b0:
            out[b0 - y0:b1 - y0, a0:a1] = tile[b0 - y:b1 - y, a0 - x:a1 - x]
    return out


def project(path):
    """A tilemap project under tilemaps/: {"rel", "size", "tilesets", "frames", "layers": [{"name", "tileset",
    "frames": [(offset, cells, opacity)]}], "meta": the Dotwork build record or None}. Only visible tilemap layers;
    visible pixel layers are left out with a log line (a map is made of tiles)."""
    px = _px()
    z, d, rel, version, w, h = px.open_project(path)
    with z:
        layers, frames = d["layers"], d["frames"]
        sets = tilesets(z, d, rel)
        out, other = [], 0
        for li, ly in enumerate(layers):
            if not isinstance(ly, dict):
                px._fail(rel, f"layer {li + 1} is not an object")
            name = str(ly.get("name") or f"layer {li + 1}")
            if not px.visible_in(layers, li, rel):
                continue
            kind = ly.get("type", 0)
            if kind != LAYER_TILEMAP:
                other += kind not in (1, 4)          # groups and sound draw nothing of their own
                continue
            if ly.get("blend_mode", 0) or ly.get("clipping_mask"):
                px._fail(rel, f"tilemap layer {name!r}: a blend mode or clipping mask (a TileMapLayer draws Normal)")
            # second-model review: what Pixelorama applies above the layer was dropped, so the scene drew it
            # differently. A group that blends its layers, a group's opacity and layer effects are refused.
            gi = ly.get("parent", -1)
            while gi != -1:
                g = layers[gi]
                gname = str(g.get("name") or f"layer {gi + 1}")
                if g.get("blend_mode", px.BLEND_NORMAL) != px.BLEND_PASS:
                    px._fail(rel, f"tilemap layer {name!r} is in group {gname!r}, which blends its layers: set the "
                                  "group to Pass through (a TileMapLayer cannot be blended as a group)")
                if float(px._number(g.get("opacity", 1.0), rel, f"group {gname!r} opacity", 0, 1)) != 1.0 or \
                        px._opacity_keys(g, rel, repr(gname)):
                    px._fail(rel, f"tilemap layer {name!r} is in group {gname!r}, whose opacity is not 100%: set the "
                                  "opacity on the tilemap layer instead")
                if px.visible_in(layers, gi, rel) and any(
                        isinstance(e, dict) and e.get("enabled", True) for e in (g.get("effects") or [])):
                    px._fail(rel, f"tilemap layer {name!r} is in group {gname!r}, which has layer effects")
                gi = g.get("parent", -1)
            if any(isinstance(e, dict) and e.get("enabled", True) for e in (ly.get("effects") or [])):
                px._fail(rel, f"tilemap layer {name!r} has layer effects (a TileMapLayer has none)")
            ti = layer_tileset(ly, sets, rel, repr(name))
            keys = px._opacity_keys(ly, rel, repr(name))
            opacity = float(px._number(ly.get("opacity", 1.0), rel, f"layer {name!r} opacity", 0, 1))
            fr = []
            for fi, f in enumerate(frames):
                cels = f.get("cels") if isinstance(f, dict) else None
                if not isinstance(cels, list) or len(cels) != len(layers) or not isinstance(cels[li], dict):
                    px._fail(rel, f"frame {fi + 1} has no cel for layer {name!r}")
                off, cells = cells_of(cels[li], rel, f"frame {fi + 1} {name!r}")
                if px._number(cels[li].get("z_index", 0), rel, f"frame {fi + 1} {name!r} z_index") != 0:
                    px._fail(rel, f"frame {fi + 1}: the cel of tilemap layer {name!r} has a z-index, which moves it "
                                  "in the draw order: set it to 0 and order the layers instead")
                k = px._number(cels[li].get("opacity", 1.0), rel, f"frame {fi + 1} cel opacity", 0, 1)
                fr.append((off, cells, px._layer_opacity(opacity, keys, fi) * k))
            out.append({"name": name, "tileset": ti, "frames": fr})
        if other:
            core.log(f"pixelorama reexport {rel}: {other} visible layers that are not tilemaps were left out (a map "
                     "is made of tiles)")
        meta = (d.get("metadata") or {}).get(META) if isinstance(d.get("metadata"), dict) else None
        try:
            meta = json.loads(meta) if isinstance(meta, str) else None
        except ValueError:
            meta = None
        return {"rel": rel, "size": (w, h), "tilesets": sets, "frames": len(frames), "layers": out,
                "other": other, "meta": meta if isinstance(meta, dict) else None}


# -------------------------------------------------- writing a tilemap .pxo
def _godot_colour(rgb):
    return "Color(%.6f, %.6f, %.6f, 1)" % tuple(c / 255 for c in rgb)


def pxo_bytes(size, tileset, layers, meta=None):
    """A .pxo of tilemap layers sharing one tileset: size (w, h) in pixels; tileset {"name", "size", "tiles" [tile 0
    the empty one], "data" [...], "terrains"}; layers [(name, {(x, y): (index, fh, fv, tr)})]; meta: the Dotwork build
    record (project metadata, JSON text). pxo_version 7, like pixelorama.pxo_bytes; each cel's buffer holds the drawn
    map (Pixelorama redraws it from the cells anyway)."""
    px = _px()
    w, h = size
    tw, th = tileset["size"]
    data = {
        "pxo_version": px.WRITE_VERSION, "size_x": w, "size_y": h, "color_mode": px.RGBA8, "fps": px.DEFAULT_FPS,
        "layers": [{"name": n, "visible": True, "locked": False, "blend_mode": px.BLEND_NORMAL, "clipping_mask": False,
                    "opacity": 1.0, "parent": -1, "type": LAYER_TILEMAP, "new_cels_linked": False,
                    "tileset_index": 0, "place_only_mode": False, "tile_size": "(%d, %d)" % (tw, th),
                    "tile_shape": SQUARE, "tile_layout": 5, "tile_offset_axis": 0} for n, _ in layers],
        "frames": [{"cels": [{"opacity": 1.0, "z_index": 0, "offset": "(0, 0)", "cell_data": {
            "(%d, %d)" % xy: {"index": c[0], "flip_h": c[1], "flip_v": c[2], "transpose": c[3]}
            for xy, c in sorted(cells.items())}} for _, cells in layers], "duration": 1.0}],
        "tags": [], "current_frame": 0, "current_layer": 0,
        "tilesets": [{"name": tileset["name"], "tile_size": "(%d, %d)" % (tw, th),
                      "tile_amount": len(tileset["tiles"]), "tile_shape": SQUARE,
                      "tile_data": {str(j): {"probability": t["probability"], "user_data": t["user_data"],
                                             "terrain_center_bit": t["center"], "terrain_peering_bits": t["peers"],
                                             "times_used": 0} for j, t in enumerate(tileset["data"])},
                      "terrain_data": [{"name": n, "color": _godot_colour(c)} for n, c in tileset["terrains"]]}],
        "user_data": "Made by Dotwork. After editing, run: dotwork.py pixelorama --reexport",
    }
    if meta is not None:
        data["metadata"] = {META: json.dumps(meta, sort_keys=True)}
    drawn = [render(tileset, (0, 0), cells, w, h) for _, cells in layers]
    first = drawn[0] if drawn else np.zeros((h, w, 4), np.uint8)
    for im in drawn[1:]:
        first = px._blend_rect(first, im)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        px._put(z, "data.json", json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        px._put(z, "mimetype", px.MIMETYPE)
        px._put(z, "preview.png", px._preview(first))
        for i, im in enumerate(drawn):
            px._put(z, f"image_data/frames/1/layer_{i + 1}", np.ascontiguousarray(im).tobytes())
        for j, t in enumerate(tileset["tiles"]):
            px._put(z, f"tilesets/0/{j}", np.ascontiguousarray(t, np.uint8).tobytes())
    return buf.getvalue()


# -------------------------------------------------- Godot text files (TileSet and scenes Dotwork wrote or Godot saved)
HEAD = re.compile(r"^\[(\w+)(\s.*)?\]\s*$")
ATTR = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|[^\s\]]+)')
TAGS = ("gd_resource", "gd_scene", "ext_resource", "sub_resource", "resource", "node", "connection", "editable")


def blocks(text):
    """[header line, [body lines]] blocks of a Godot text resource (only Godot's own section tags open one)."""
    out = [["", []]]
    for line in text.splitlines():
        m = HEAD.match(line)
        if m and m.group(1) in TAGS:
            out.append([line, []])
        else:
            out[-1][1].append(line)
    return out


def attrs(header):
    return {k: (v[1:-1] if v.startswith('"') else v) for k, v in ATTR.findall(header)}


def _tag(header):
    m = HEAD.match(header)
    return m.group(1) if m else ""


def _abs_res(res, what):
    """A res:// path as a file inside the game (refused outside it)."""
    if not str(res).startswith("res://"):
        raise core.ToolError(f"{what} {res!r} is not a res:// path")
    return core.contained(res[len("res://"):], core.PROJECT, what=what)


def read_tileset(res):
    """A square Dotwork TileSet .tres: {"res", "path", "size": (w, h), "sources": [{"id", "atlas_res", "atlas",
    "tiles": [(x, y)] in file order, "terrain": {(x, y): id}, "peers": {(x, y): {CellNeighbor index: id}},
    "probability": {(x, y): p}}], "terrains": [(name, rgb)]}. None for a TileSet Dotwork does not carry (isometric,
    margins or separation, a source that is not an atlas)."""
    path = _abs_res(res, "TileSet")
    with open(path, encoding="utf-8") as f:
        bl = blocks(f.read())
    ext = {attrs(h).get("id"): attrs(h).get("path") for h, _ in bl if _tag(h) == "ext_resource"}
    subs = {attrs(h).get("id"): (attrs(h).get("type"), b) for h, b in bl if _tag(h) == "sub_resource"}
    body = next((b for h, b in bl if _tag(h) == "resource"), [])
    size, terrains, order = None, {}, []
    for line in body:
        k, _, v = (s.strip() for s in line.partition("="))
        if k in ("tile_shape", "tile_layout", "tile_offset_axis") and v not in ("0", ""):
            return None
        m = re.fullmatch(r"Vector2i\((\d+), (\d+)\)", v)
        if k == "tile_size" and m:
            size = (int(m.group(1)), int(m.group(2)))
        m = re.fullmatch(r"terrain_set_0/terrain_(\d+)/(name|color)", k)
        if m:
            t = terrains.setdefault(int(m.group(1)), ["", (128, 88, 64)])
            if m.group(2) == "name":
                t[0] = json.loads(v) if v.startswith('"') else v
            else:
                t[1] = _colour(v)
        m = re.fullmatch(r"sources/(\d+)", k)
        if m:
            ref = re.fullmatch(r'SubResource\("([^"]+)"\)', v)
            if not ref:
                return None
            order.append((int(m.group(1)), ref.group(1)))
    sources = []
    for sid, ref in sorted(order):
        kind, sb = subs.get(ref, (None, []))
        if kind != "TileSetAtlasSource":
            return None
        src = {"id": sid, "tiles": [], "terrain": {}, "peers": {}, "probability": {}, "anim": set()}
        region = size
        for line in sb:
            k, _, v = (s.strip() for s in line.partition("="))
            if k in ("margins", "separation") and v not in ("Vector2i(0, 0)", ""):
                return None
            if k == "texture":
                ref2 = re.fullmatch(r'ExtResource\("([^"]+)"\)', v)
                src["atlas_res"] = ext.get(ref2.group(1)) if ref2 else None
            m = re.fullmatch(r"Vector2i\((\d+), (\d+)\)", v)
            if k == "texture_region_size" and m:
                region = (int(m.group(1)), int(m.group(2)))
            m = re.fullmatch(r"(\d+):(\d+)/(.*)", k)
            if not m:
                continue
            xy, rest = (int(m.group(1)), int(m.group(2))), m.group(3)
            if rest == "0":
                src["tiles"].append(xy)
            elif rest == "animation_columns":
                src["anim"].add(xy)
            elif rest == "0/terrain":
                src["terrain"][xy] = int(v)
            elif rest == "0/probability":
                src["probability"][xy] = float(v)
            elif rest.startswith("0/terrains_peering_bit/"):
                name = rest.rsplit("/", 1)[1]
                nb = next((i for i, n in NEIGHBOUR.items() if n == name), None)
                if nb is not None:
                    src["peers"].setdefault(xy, {})[nb] = int(v)
            elif re.fullmatch(r"\d+", rest) and rest != "0":
                return None                      # alternative tiles: not carried
        if not src.get("atlas_res") or region is None or (size and region != size):
            return None
        src["atlas"] = _abs_res(src["atlas_res"], "TileSet atlas")
        sources.append(src)
    if size is None or not sources:
        return None
    return {"res": res, "path": path, "size": size, "sources": sources,
            "terrains": [tuple(terrains[i]) for i in sorted(terrains)]}


def decode_cells(text):
    """TileMapLayer.tile_map_data (comma bytes, or base64 as Godot 4.4+ saves it) -> [(x, y, source, ax, ay, alt)]."""
    m = re.fullmatch(r'\s*PackedByteArray\(\s*"([^"]*)"\s*\)\s*', text)
    if m:
        raw = base64.b64decode(m.group(1))
    else:
        m = re.fullmatch(r"\s*PackedByteArray\(([\d,\s]*)\)\s*", text)
        if not m:
            raise core.ToolError(f"tile_map_data {text[:40]!r}... cannot be read")
        raw = bytes(int(b) for b in m.group(1).replace(",", " ").split())
    if len(raw) < 2 or (len(raw) - 2) % 12:
        raise core.ToolError("tile_map_data is not Godot's format 0 (2 bytes, then 12 per cell)")
    if struct.unpack_from("<H", raw)[0] != 0:
        raise core.ToolError("tile_map_data is a format Dotwork does not read (only format 0)")
    return [struct.unpack_from("<hhHHHH", raw, 2 + 12 * i) for i in range((len(raw) - 2) // 12)]


def encode_cells(cells, base64_form=False):
    """The tile_map_data value for [(x, y, source, ax, ay, alt)], sorted, in the form given."""
    raw = struct.pack("<H", 0) + b"".join(struct.pack("<hhHHHH", *c) for c in sorted(cells))
    if base64_form:
        return 'PackedByteArray("%s")' % base64.b64encode(raw).decode("ascii")
    return "PackedByteArray(%s)" % ", ".join(str(b) for b in raw)


def read_map(res, tileset_res):
    """A map scene's TileMapLayers on that TileSet: (text, [(name, line index of tile_map_data or None, cells,
    base64 form)]), in scene order (the first is drawn first)."""
    path = _abs_res(res, "map scene")
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    lines = text.split("\n")
    ext = {}
    out, cur = [], None
    for i, line in enumerate(lines):
        s = line.rstrip("\r")
        if HEAD.match(s):
            cur = None
            a = attrs(s)
            if _tag(s) == "ext_resource":
                ext[a.get("id")] = a.get("path")
            elif _tag(s) == "node" and a.get("type") == "TileMapLayer":
                cur = {"name": a.get("name"), "line": None, "cells": [], "b64": False, "tileset": None}
                out.append(cur)
            continue
        if cur is None:
            continue
        if s.startswith("tile_map_data = "):
            cur["line"] = i
            cur["cells"] = decode_cells(s[len("tile_map_data = "):])
            cur["b64"] = '("' in s
        m = re.fullmatch(r'tile_set = ExtResource\("([^"]+)"\)', s)
        if m:
            cur["tileset"] = ext.get(m.group(1))
    return text, [L for L in out if L["tileset"] == tileset_res]


def tilemap_scene(path, root, tileset_res, layers):
    """A Node2D with one TileMapLayer per layer [(name, cells [(x, y, source, ax, ay, alt)], alpha)], first drawn
    first; Dotwork's own form (comma bytes, as lane_lighting writes its demo floor)."""
    lines = ["[gd_scene load_steps=2 format=3]", "",
             f'[ext_resource type="TileSet" path="{tileset_res}" id="1_tiles"]', "",
             f'[node name={godot.q(root)} type="Node2D"]']
    for name, cells, alpha in layers:
        lines += ["", f'[node name={godot.q(name)} type="TileMapLayer" parent="."]']
        if alpha < 1.0:
            lines.append("modulate = Color(1, 1, 1, %g)" % round(alpha, 6))
        lines += [f"tile_map_data = {encode_cells(cells)}", 'tile_set = ExtResource("1_tiles")']
    return godot._write(path, "\n".join(lines) + "\n")


# -------------------------------------------------- shared helpers
def _hash(tile):
    """16 hex digits of a tile as it looks (the colour under clear pixels does not count: editors drop it)."""
    t = np.ascontiguousarray(tile, np.uint8).copy()
    t[t[..., 3] == 0] = 0
    return hashlib.sha256(t.tobytes() + bytes(str(t.shape), "ascii")).hexdigest()[:16]


def _node_name(name, taken):
    """A Godot node name from a layer name (no . : @ / \" %), unique among taken."""
    base = re.sub(r'[.:@/"%\\]', "_", name).strip() or "Layer"
    n, k = base, 2
    while n in taken:
        n, k = f"{base}{k}", k + 1
    taken.add(n)
    return n


def _flags(fh, fv, tr):
    return (FLIP_H if fh else 0) | (FLIP_V if fv else 0) | (TRANSPOSE if tr else 0)


def _surface(user):
    """(surface text or None, solid) from a tile's user data: the word "solid" gives it collision, the rest names its
    surface (the custom data the terrain lanes write as "surface")."""
    words = [w for w in re.split(r"[\s,;]+", user.strip()) if w]
    rest = " ".join(w for w in words if w.lower() != SOLID)
    return (rest or None), any(w.lower() == SOLID for w in words)


def _same_bytes(path, write):
    """Run write() (which writes path) and say whether the file's bytes changed."""
    before = handpolish._bytes(path)
    write()
    return handpolish._bytes(path) != before


class OwnRows:
    """Manifest rows of the files re-exported from your own tilemap projects (manifest_pixelorama.json): a row is
    added or brought up to date only when its file changed, and the manifest is saved only then, so an untouched
    round trip rewrites nothing."""

    def __init__(self):
        self.man = core.Manifest(core.SETTINGS, "pixelorama")
        self.dirty = False

    def record(self, path, kind, source, changed, **fields):
        rel = os.path.relpath(path, core.PROJECT).replace(os.sep, "/")
        row = next((r for r in self.man.data["assets"] if r["file"] == rel), None)
        if row is not None and not changed:
            return
        if row is None:
            row = {"file": rel, "kind": kind, "models": [], "workflow": OWN_WORKFLOW, "source": source}
            self.man.data["assets"].append(row)
        import datetime
        row.update({k: v for k, v in fields.items() if v is not None}, sha256=core.sha256_file(path),
                   date=datetime.date.today().isoformat(), kind=kind, source=source)
        self.dirty = True

    def stale(self, source, keep):
        """Files an earlier re-export of this source wrote that this one did not: deleted with their rows. Returns
        their project paths."""
        gone = []
        for r in list(self.man.data["assets"]):
            if r.get("source") == source and r["file"] not in keep:
                # a manifest is a tracked file a pull request can carry: a row never deletes outside the game
                p = core.contained(r["file"], core.PROJECT, what="manifest_pixelorama.json row")
                if os.path.isfile(p):
                    os.remove(core.safe_dest(p))
                self.man.data["assets"].remove(r)
                gone.append(r["file"])
        self.dirty = self.dirty or bool(gone)
        return gone

    def save(self):
        if self.dirty:
            self.man.save()


# -------------------------------------------------- your own tilemap project -> game files
def export_own(tm, name, conf, rows, touched):
    """Atlases, TileSet, scenes and JSON map of a tilemap project made in Pixelorama (see the header). Every file is
    written only when its content changed."""
    if not tm["layers"]:
        raise core.ToolError(f"{tm['rel']}: no visible tilemap layer")
    source = tm["rel"].replace(os.sep, "/")
    used = sorted({L["tileset"] for L in tm["layers"]})
    sets = [tm["tilesets"][i] for i in used]
    tw, th = sets[0]["size"]
    if any(s["size"] != (tw, th) for s in sets):
        raise core.ToolError(f"{tm['rel']}: its tilemap layers use tilesets of different tile sizes (one TileSet has "
                             "one tile size)")
    out = core.art(conf, "tilemaps", name)
    res = core.res(conf, "tilemaps", name)
    written = set()

    def rel(p):
        return os.path.relpath(p, core.PROJECT).replace(os.sep, "/")

    def done(p, kind, changed, **fields):
        if p is None:
            return
        rows.record(p, kind, source, changed, **fields)
        written.add(rel(p))
        if changed:
            touched.append(rel(p))

    # maps first, checked before anything is written: cells in canvas cells (an offset must sit on the tile grid)
    frames = []
    for fi in range(tm["frames"]):
        layers = []
        for L in tm["layers"]:
            off, cells, alpha = L["frames"][fi]
            if off[0] % tw or off[1] % th:
                raise core.ToolError(f"{tm['rel']}: frame {fi + 1} layer {L['name']!r} is moved off the tile grid "
                                     f"(offset {off[0]}, {off[1]}): move it by whole tiles")
            n = len(tm["tilesets"][L["tileset"]]["tiles"])
            cl = []
            for (cx, cy), (idx, fh, fv, tr) in sorted(cells.items()):
                if idx < n:                      # past the tileset: Pixelorama draws the empty tile there
                    cl.append((cx + off[0] // tw, cy + off[1] // th, idx, _flags(fh, fv, tr)))
            layers.append((L, cl, alpha))
        frames.append(layers)
    # atlases: tile j of a tileset at slot j - 1, ATLAS_COLUMNS to a row (tile 0, the empty tile, is not drawn)
    sources, terrains, slot = [], [], {}
    for k, (si, ts) in enumerate(zip(used, sets)):
        n = len(ts["tiles"]) - 1
        if n < 1:
            continue
        cols = ATLAS_COLUMNS
        atlas = np.zeros((((n + cols - 1) // cols) * th, cols * tw, 4), np.uint8)
        for j in range(1, n + 1):
            x, y = (j - 1) % cols, (j - 1) // cols
            atlas[y * th:(y + 1) * th, x * tw:(x + 1) * tw] = ts["tiles"][j]
        fn = f"tiles_{name}.png" if len(used) == 1 else f"tiles_{name}_{k + 1}.png"
        p = os.path.join(out, fn)
        done(p, "tile_atlas", handpolish.keep_or_save(Image.fromarray(atlas, "RGBA"), p), tile_px=[tw, th],
             tiles=n, layout=f"{cols} columns: Pixelorama tile N at slot N - 1, reading order")
        first = len(terrains)
        terrains += [(n_ or f"{ts['name'] or 'tileset'} {t + 1}", c) for t, (n_, c) in enumerate(ts["terrains"])]
        tiles = []
        for j in range(1, n + 1):
            t = ts["data"][j]
            surface, solid = _surface(t["user_data"])
            row = {"x": (j - 1) % cols, "y": (j - 1) // cols, "probability": t["probability"], "custom": surface,
                   "terrain": None, "solid_rects": [(-tw // 2, -th // 2, tw - tw // 2, th - th // 2)] if solid else None}
            peers = [t["peers"][b] for b in PEERS8]
            if t["center"] >= 0 or any(b >= 0 for b in peers):
                row["terrain"] = first + t["center"] if t["center"] >= 0 else -1
                row["peers"] = tuple(first + b if b >= 0 else -1 for b in peers)
            tiles.append(row)
            slot[(si, j)] = (len(sources), row["x"], row["y"])
        sources.append({"atlas_res": f"{res}/{fn}", "tiles": tiles})
    if not sources:
        raise core.ToolError(f"{tm['rel']}: its tilesets hold no tiles")
    custom = "surface" if any(t.get("custom") for s in sources for t in s["tiles"]) else None
    physics = any(t.get("solid_rects") for s in sources for t in s["tiles"])
    tres = os.path.join(out, f"{name}_tileset.tres")
    if not godot.ENABLED:
        # #245, #257: without Godot no TileSet or scene is written, so every one an earlier Godot re-export of this
        # project wrote is kept, whatever the frame count now names them
        written.add(rel(tres))
        written.update(r["file"] for r in rows.man.data["assets"]
                       if r.get("source") == source and r.get("kind") in ("tileset", "scene"))
    if godot.ENABLED:
        done(tres, "tileset", _same_bytes(tres, lambda: godot.tileset_layers(
            tres, (tw, th), sources, terrains, custom=custom, physics=physics, mode="match_corners_and_sides",
            metadata={"dotwork_pixelorama": "true"})), tile_px=[tw, th], terrains=[t[0] for t in terrains],
             terrain_mode="match_corners_and_sides", custom_data=custom, physics=physics)
    multi = len(frames) > 1
    for fi, layers in enumerate(frames):
        scene = os.path.join(out, f"{name}_{fi:02d}.tscn" if multi else f"{name}.tscn")
        if not godot.ENABLED:
            written.add(rel(scene))   # #245: kept as the last Godot re-export wrote it
            continue
        taken, nodes = set(), []
        for L, cells, alpha in layers:
            nodes.append((_node_name(L["name"], taken),
                          [(x, y) + slot[(L["tileset"], j)] + (fl,) for x, y, j, fl in cells], alpha))
        root = "".join(p.title() for p in re.split(r"[^A-Za-z0-9]+", name) if p) or "Map"
        done(scene, "scene", _same_bytes(scene, lambda: tilemap_scene(scene, root, f"{res}/{name}_tileset.tres",
                                                                      nodes)),
             node="Node2D + TileMapLayers", tileset=f"{res}/{name}_tileset.tres", layers=[n for n, _, _ in nodes])
    doc = {"note": "Made in Pixelorama, re-exported by Dotwork. A cell is [x, y, tile, flags]: tile N sits at atlas "
                   "slot N - 1 (reading order, `columns` to a row); flags 1 flip_h, 2 flip_v, 4 transpose "
                   "(transposed first, then flipped)",
           "tile_size": [tw, th], "columns": ATLAS_COLUMNS,
           "tilesets": [{"atlas": s["atlas_res"].rsplit("/", 1)[1], "tiles": len(s["tiles"]),
                         "surface": {str(i + 1): t["custom"] for i, t in enumerate(s["tiles"]) if t.get("custom")},
                         "solid": [i + 1 for i, t in enumerate(s["tiles"]) if t.get("solid_rects")]}
                        for s in sources],
           "frames": [[{"name": L["name"], "tileset": used.index(L["tileset"]), "opacity": round(alpha, 6),
                        "cells": [[x, y, j, (1 if fl & FLIP_H else 0) | (2 if fl & FLIP_V else 0)
                                   | (4 if fl & TRANSPOSE else 0)] for x, y, j, fl in cells]}
                       for L, cells, alpha in layers] for layers in frames]}
    jp = os.path.join(out, f"{name}_map.json")
    done(jp, "map_data", handpolish.write_if_changed(jp, json.dumps(doc, indent=1)), frames=len(frames))
    removed = rows.stale(source, written)
    touched.extend(removed)       # a deleted file is a change too (#245: "0 files changed" hid it)
    gone = len(removed)
    core.log(f"pixelorama reexport tilemap {name}: {sum(len(s['tiles']) for s in sources)} tiles, "
             f"{len(tm['layers'])} layers, {len(frames)} frames" + (f", {gone} stale files removed" if gone else ""))


# -------------------------------------------------- a Dotwork map or TileSet -> a tilemap .pxo, and back
def _tileset_of(ts):
    """The Pixelorama tileset for a Dotwork TileSet: the empty tile, then every tile of every source in file order,
    each tagged with its atlas slot and its hash; terrains, probabilities and peering bits copied (Pixelorama paints
    terrains with them)."""
    tw, th = ts["size"]
    tiles, data, where = [np.zeros((th, tw, 4), np.uint8)], [_tile_data("")], {}
    for si, s in enumerate(ts["sources"]):
        atlas = np.array(Image.open(s["atlas"]).convert("RGBA"))
        for (x, y) in s["tiles"]:
            t = np.zeros((th, tw, 4), np.uint8)
            part = atlas[y * th:(y + 1) * th, x * tw:(x + 1) * tw]
            t[:part.shape[0], :part.shape[1]] = part
            where[(si, x, y)] = len(tiles)
            tiles.append(t)
            peers = [-1] * 16
            for nb, tid in s["peers"].get((x, y), {}).items():
                peers[nb] = tid
            data.append(_tile_data(f"dotwork:{si}:{x}:{y}:{_hash(t)}", s["probability"].get((x, y), 1.0),
                                   s["terrain"].get((x, y), -1), peers))
    terrains = ts["terrains"] or [("", (128, 88, 64))]
    return {"name": os.path.basename(ts["res"])[:-5], "size": (tw, th), "tiles": tiles, "data": data,
            "terrains": terrains}, where


def _tile_data(user, probability=1.0, center=-1, peers=None):
    return {"probability": probability, "user_data": user, "center": center, "peers": peers or [-1] * 16}


def _data_hash(data, terrains=()):
    """A tileset's tile data as built (probability, user data, terrain centre and peering bits per tile) and its
    terrain definitions, hashed: a terrain painted or added in Pixelorama is an edit as much as a pixel is (#245,
    #257)."""
    norm = [[round(float(d["probability"]), 6), str(d["user_data"]), int(d["center"]),
             [int(b) for b in d["peers"]] + [-1] * (16 - len(d["peers"]))] for d in data]
    norm.append([[str(n), [int(c) for c in rgb]] for n, rgb in terrains])
    return hashlib.sha256(json.dumps(norm, ensure_ascii=True).encode("ascii")).hexdigest()[:16]


def _cells_hash(layers):
    """The cells of a Dotwork-built project as built: [(layer name, [(x, y, source, ax, ay, flags)])], hashed."""
    return hashlib.sha256(json.dumps([[n, sorted(c)] for n, c in layers]).encode("ascii")).hexdigest()[:16]


def dotwork_jobs(pack, conf):
    """[(out .pxo, bytes, what it was built from)] for each map scene a Dotwork pack wrote (mapbuild) and each square
    TileSet no map uses; a TileSet Dotwork cannot carry (isometric, lit copies) is skipped with a log line."""
    rows = handpolish.GameManifests().current() if glob.glob(
        os.path.join(core.SETTINGS.src, "dotwork", "manifest_*.json")) else []
    src = core.src(conf, "pixelorama", "tilemaps")
    jobs, used = [], set()
    for r in rows:
        if r["kind"] == "scene" and r.get("tileset") and r.get("source") is None:
            scene_res = "res://" + r["file"]
            if not os.path.exists(os.path.join(core.PROJECT, r["file"])):
                continue
            ts = read_tileset(r["tileset"])
            if ts is None:
                core.log(f"pixelorama build: {r['file']} uses a TileSet Dotwork does not carry into Pixelorama")
                continue
            used.add(r["tileset"])
            _, layers = read_map(scene_res, r["tileset"])
            jobs.append((os.path.join(src, os.path.basename(r["file"])[:-5] + ".pxo"), ts, scene_res, layers))
    for r in rows:
        res = "res://" + r["file"]
        if r["kind"] != "tileset" or r.get("lit_from") or r.get("source") is not None or res in used \
                or not os.path.exists(os.path.join(core.PROJECT, r["file"])):
            continue
        ts = read_tileset(res)
        if ts is None:
            core.log(f"pixelorama build: {r['file']} is not a square TileSet of atlas sources (skipped)")
            continue
        jobs.append((os.path.join(src, os.path.basename(r["file"])[:-5] + ".pxo"), ts, "", None))
    # second-model review: maps/one/town.tscn and maps/two/town.tscn both made tilemaps/town.pxo, the second
    # replacing the first unbacked; two sources for one project stop the build before anything is written
    seen = {}
    for path, ts, scene_res, _ in jobs:
        what = scene_res or ts["res"]
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            raise core.ToolError(f"{seen[key]} and {what} would both become {os.path.relpath(path, pack)}: rename "
                                 "one of them (Pixelorama projects are named after the map or TileSet file)")
        seen[key] = what
    out = []
    for path, ts, scene_res, layers in jobs:
        tileset, where = _tileset_of(ts)
        tw, th = ts["size"]
        if layers is None:   # a TileSet alone: each source's tiles where they sit in its atlas, a row between sources
            cells, top = {}, 0
            for si, s in enumerate(ts["sources"]):
                for (x, y) in s["tiles"]:
                    cells[(x, y + top)] = (where[(si, x, y)], False, False, False)
                top += max([y for _, y in s["tiles"]] + [0]) + 2
            named = [("tiles", cells)]
            built = []
        else:
            named, built = [], []
            for L in layers:
                cells, flat = {}, []
                for x, y, si, ax, ay, alt in L["cells"]:
                    if alt & 0xFFF or (si, ax, ay) not in where:
                        raise core.ToolError(f"{scene_res}: layer {L['name']} cell ({x}, {y}) holds a tile Dotwork "
                                             "does not carry (an alternative tile or an animation frame)")
                    if x < 0 or y < 0:
                        raise core.ToolError(f"{scene_res}: layer {L['name']} has cells left of or above (0, 0)")
                    cells[(x, y)] = (where[(si, ax, ay)], bool(alt & FLIP_H), bool(alt & FLIP_V), bool(alt & TRANSPOSE))
                    flat.append((x, y, si, ax, ay, alt & (FLIP_H | FLIP_V | TRANSPOSE)))
                named.append((L["name"], cells))
                built.append((L["name"], flat))
        xs = [x for _, c in named for x, _ in c] or [0]
        ys = [y for _, c in named for _, y in c] or [0]
        size = ((max(xs) + 1) * tw, (max(ys) + 1) * th)
        if max(size) > _px().MAX_SIDE:
            core.log(f"pixelorama build {os.path.relpath(path, pack)}: {size[0]}x{size[1]} px is over "
                     f"{_px().MAX_SIDE}; skipped")
            continue
        meta = {"tileset": ts["res"], "scene": scene_res, "layers": [n for n, _ in named],
                "cells": _cells_hash(built) if layers is not None else "", "data": _data_hash(tileset["data"], tileset["terrains"])}
        out.append((path, pxo_bytes(size, tileset, named, meta), meta))
    return out


def polished(path):
    """True when a Dotwork-built tilemap .pxo holds edits (a tile whose look differs from its tag, a tile with no tag
    in a cell, other cells than built), or cannot be read as one. Unchanged files can be rebuilt freely."""
    try:
        tm = project(path)
    except core.ToolError:
        return True
    if not tm["meta"]:
        return True
    if tm.get("other") or tm["frames"] > 1:
        return True               # #245: a pixel layer or a frame the user added (a build makes one frame of tiles)
    want = tm["meta"].get("data")
    if want is not None and (len(tm["tilesets"]) != 1 or _data_hash(tm["tilesets"][0]["data"], tm["tilesets"][0]["terrains"]) != want):
        return True               # #245: terrain bits, probability or user data changed in Pixelorama
    try:
        edits, layers = _edits(tm)
    except core.ToolError:
        return True
    return bool(edits) or (tm["meta"].get("scene") and _cells_hash(layers) != tm["meta"].get("cells"))


def _edits(tm):
    """({(source, x, y): tile}, [(layer name, [(x, y, source, ax, ay, flags)])]) of a Dotwork-built project: the
    tiles that differ from their tag, and the cells. A tile with no tag used in a cell is refused (it has no atlas
    slot); so are two edits of one slot that differ."""
    if not tm["layers"] or any(L["tileset"] != 0 for L in tm["layers"]):
        raise core.ToolError(f"{tm['rel']}: a Dotwork-built tilemap keeps its one tileset; a layer uses another")
    ts = tm["tilesets"][0]
    slot, edits = {}, {}
    for j, t in enumerate(ts["data"]):
        m = TAG.fullmatch(t["user_data"].strip())
        if not m or j == 0:
            continue
        s = tuple(int(v) for v in m.groups()[:3])
        slot[j] = s
        if _hash(ts["tiles"][j]) != m.group(4):
            if s in edits and _hash(edits[s]) != _hash(ts["tiles"][j]):
                raise core.ToolError(f"{tm['rel']}: two tiles carry atlas slot {s} with different pixels")
            edits[s] = ts["tiles"][j]
    layers = []
    tw, th = ts["size"]
    for L in tm["layers"]:
        off, cells, alpha = L["frames"][0]
        if alpha != 1.0:     # second-model review: an opacity edit was neither re-exported nor seen as an edit
            raise core.ToolError(f"{tm['rel']}: layer {L['name']!r} is at {round(alpha * 100)}% opacity; a map Dotwork "
                                 "built keeps its layers at 100% (set the opacity on the TileMapLayer in Godot)")
        if off[0] % tw or off[1] % th:
            raise core.ToolError(f"{tm['rel']}: layer {L['name']!r} is moved off the tile grid (offset {off[0]}, "
                                 f"{off[1]}): move it by whole tiles")
        flat = []
        for (cx, cy), (j, fh, fv, tr) in cells.items():
            if j >= len(ts["tiles"]):
                continue
            if j not in slot:
                raise core.ToolError(
                    f"{tm['rel']}: layer {L['name']!r} cell ({cx}, {cy}) uses tile {j}, a tile Pixelorama added (its "
                    "Auto or Stack tile mode adds one when you draw on a tile used in more than one cell). A Dotwork "
                    "TileSet keeps its atlas: undo it, set the tile mode to Manual (an edit then changes the tile "
                    "everywhere it is used) and draw again")
            x, y = cx + off[0] // tw, cy + off[1] // th
            flat.append((x, y) + slot[j] + (_flags(fh, fv, tr),))
        layers.append((L["name"], flat))
    return edits, layers


def reexport_dotwork(items, man, touched):
    """Dotwork-built tilemap projects [(path, project)] -> edited tiles into their atlas slots (all projects' edits
    gathered first: two that change one slot differently stop the re-export) and edited cells into each map scene
    (only its tile_map_data lines). The TileSet is never rewritten."""
    edits, maps = {}, []
    for path, tm in items:
        meta = tm["meta"]
        ts = read_tileset(meta["tileset"])
        if ts is None or ts["size"] != tm["tilesets"][0]["size"]:
            raise core.ToolError(f"{tm['rel']}: its TileSet {meta['tileset']} changed shape since the .pxo was built; "
                                 "rebuild it with dotwork.py pixelorama --overwrite")
        e, layers = _edits(tm)
        for s, t in e.items():
            if s[0] >= len(ts["sources"]) or tuple(s[1:]) not in ts["sources"][s[0]]["tiles"]:
                raise core.ToolError(f"{tm['rel']}: atlas slot {s} is no longer in {meta['tileset']}; rebuild the "
                                     ".pxo with dotwork.py pixelorama --overwrite")
            key = (meta["tileset"],) + s
            if key in edits and _hash(edits[key][0]) != _hash(t):
                raise core.ToolError(f"{tm['rel']} and {edits[key][1]} change tile {s} of {meta['tileset']} "
                                     "differently: keep one edit, rebuild the other .pxo with --overwrite")
            edits[key] = (t, tm["rel"], ts)
        if meta.get("scene") and _cells_hash(layers) != meta.get("cells"):
            maps.append((tm, meta, layers))
    # second-model review: a map whose layers no longer match failed after the atlases were written; every map is
    # checked first, so a re-export that stops has changed nothing
    checked = []
    for tm, meta, layers in maps:
        text, nodes = read_map(meta["scene"], meta["tileset"])
        names = [L["name"] for L in nodes]
        if sorted(n for n, _ in layers) != sorted(names):
            raise core.ToolError(f"{tm['rel']}: its tilemap layers ({', '.join(n for n, _ in layers)}) are not the "
                                 f"map's ({', '.join(names)}): keep one layer per TileMapLayer, named like it")
        new = dict(layers)
        for L in nodes:
            if L["line"] is None and new[L["name"]] and sorted(L["cells"]) != sorted(new[L["name"]]):
                raise core.ToolError(f"{meta['scene']}: layer {L['name']} has no tile_map_data line to write")
        checked.append((tm, meta, text, nodes, new))
    # tiles -> atlases, one write per atlas
    atlases = {}
    for (tres, si, x, y), (t, _, ts) in sorted(edits.items(), key=lambda kv: kv[0]):
        p = ts["sources"][si]["atlas"]
        if p not in atlases:
            atlases[p] = np.array(Image.open(p).convert("RGBA"))
        a = atlases[p]
        tw, th = ts["size"]
        part = a[y * th:(y + 1) * th, x * tw:(x + 1) * tw]
        part[...] = t[:part.shape[0], :part.shape[1]]
        if (x, y) in ts["sources"][si]["anim"]:
            core.log(f"pixelorama reexport: tile {x}:{y} of {tres} is animated; only its first frame was changed")
    for p, a in atlases.items():
        changed = handpolish.keep_or_save(Image.fromarray(a, "RGBA"), p)
        man.record(p, "tile_atlas", NOTE, changed)
        if changed:
            touched.append(os.path.relpath(p, core.PROJECT).replace(os.sep, "/"))
    # cells -> map scenes
    for tm, meta, text, nodes, new in checked:
        lines = text.split("\n")
        for L in nodes:
            if sorted(L["cells"]) == sorted(new[L["name"]]) or L["line"] is None:
                if L["line"] is None and new[L["name"]]:
                    raise core.ToolError(f"{meta['scene']}: layer {L['name']} has no tile_map_data line to write")
                continue
            cr = "\r" if lines[L["line"]].endswith("\r") else ""
            lines[L["line"]] = f"tile_map_data = {encode_cells(new[L['name']], L['b64'])}{cr}"
        body = "\n".join(lines)
        p = _abs_res(meta["scene"], "map scene")
        changed = body != text
        if changed:
            core.write_atomic(p, body.encode("utf-8"))
            touched.append(os.path.relpath(p, core.PROJECT).replace(os.sep, "/"))
        man.record(p, "scene", NOTE, changed)


def reexport(pack, conf):
    """Every tilemap project under <src_dir>/pixelorama/tilemaps/: your own ones into <art_dir>/tilemaps/<name>/,
    Dotwork-built ones back into their atlases and map scenes. Returns the files changed (relative paths)."""
    src = core.src(conf, "pixelorama", "tilemaps")
    files = sorted(glob.glob(os.path.join(src, "*.pxo")))
    touched = []
    if not files:
        return touched
    own, built = [], []
    for f in files:
        tm = project(f)
        (built if tm["meta"] else own).append((f, tm))
    if own:
        rows = OwnRows()
        for f, tm in own:
            export_own(tm, core.snake(os.path.basename(f)[:-4]), conf, rows, touched)
        rows.save()
    if built:
        reexport_dotwork(built, handpolish.GameManifests(), touched)
    return touched
