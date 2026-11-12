#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# golden_assets.py
# Purpose : build the golden fixture of the engine-neutral asset manifest (ASSET_MANIFEST.md), data/golden/dotwork/:
#           one small pack with every asset kind (a 4-direction character with holds, an additive effect, a prop with
#           collision, icons, a portrait with talking frames, a blob47 ground tileset with an animated solid overlay,
#           two path variants, decals and a door stamp, a corners4 pair set, a sides4 platform set with one-way caps,
#           an isometric set, three maps (the yard with its door stamp, a corners4 patch on the pair set, an isometric
#           isle with a block and a corners4 pond), a bitmap font, a UI kit, a scrolling background, particles, a
#           transition, a normal map, an image), its manifest, and expected.json: the loaded result every engine
#           importer must reproduce (#55 to #62, #285).
# Usage   : python tools/art/dotwork/tests/golden_assets.py --check            # exit 1 when the fixture is stale
#           python tools/art/dotwork/tests/golden_assets.py --write [--out DIR]
#           python tools/art/dotwork/tests/golden_assets.py --godot DIR          # the same pack with Godot's files
# Notes   : No GPU and no model: pixels are drawn here (a standard-library PNG writer, filter 0, so --check compares
#           decoded pixels, not zlib's bytes), and the Godot side runs Dotwork's own writers and lane functions
#           (godot.sprite_frames / tileset / tileset_layers / prop_scene, lane_ground.blob_rows, lane_tiles.tile_rows,
#           lane_platforms.tileset, lane_iso.tileset, mapbuild.plan), whose records assetmap.py turns into the
#           manifest, exactly as in a real pack. Needs Dotwork's Pillow and numpy (the lane modules import them).
#           The fixture: <out>/assets/ is an assets folder (the manifest in assets/dotwork/golden.assets.json),
#           <out>/expected.json the reference loader's result (assetspec.expected).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): path variants, a stamps layer,
#           the corners4 and isometric maps
# ---------------------------------------------------------------------------
import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
DOTWORK = os.path.dirname(HERE)
sys.path.insert(0, DOTWORK)
import assetmap  # noqa: E402
import assetspec  # noqa: E402
import godot  # noqa: E402

OUT = os.path.normpath(os.path.join(DOTWORK, "..", "..", "..", "data", "golden", "dotwork"))
PACK = "golden"
ASSETS = "assets"
RES = "res://assets/art"
T = 8          # tile size of the square sets
DATE = "2026-11-11"
INK = (20, 16, 28, 255)


# ---- pixels -------------------------------------------------------------------------------------
class Canvas:
    def __init__(self, w, h, fill=(0, 0, 0, 0)):
        self.w, self.h = w, h
        self.px = [list(fill) for _ in range(w * h)]

    def rect(self, x, y, w, h, c):
        for yy in range(max(0, y), min(self.h, y + h)):
            for xx in range(max(0, x), min(self.w, x + w)):
                self.px[yy * self.w + xx] = list(c)
        return self

    def paste(self, other, x, y):
        for yy in range(other.h):
            for xx in range(other.w):
                p = other.px[yy * other.w + xx]
                if p[3] and 0 <= x + xx < self.w and 0 <= y + yy < self.h:
                    self.px[(y + yy) * self.w + x + xx] = list(p)
        return self

    def png(self):
        raw = b"".join(b"\x00" + bytes(v for p in self.px[y * self.w:(y + 1) * self.w] for v in p) for y in range(self.h))

        def chunk(tag, data):
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def png_pixels(path):
    """Decoded RGBA rows of a PNG this file wrote (filter 0 only): what --check compares."""
    with open(path, "rb") as f:
        data = f.read()
    pos, idat, w = 8, b"", 0
    while pos < len(data):
        n, tag = struct.unpack(">I4s", data[pos:pos + 8])
        if tag == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", data[pos + 8:pos + 18])
            if (depth, ctype) != (8, 6):
                return None
        elif tag == b"IDAT":
            idat += data[pos + 8:pos + 8 + n]
        pos += 12 + n
    raw = zlib.decompress(idat)
    rows = [raw[i:i + 1 + 4 * w] for i in range(0, len(raw), 1 + 4 * w)]
    return None if any(r[0] for r in rows) else b"".join(r[1:] for r in rows)


# ---- the fake game ---------------------------------------------------------------------------------
class Game:
    """A throwaway game folder: files under assets/, provenance rows, and the records Dotwork's writers make."""

    def __init__(self, root):
        self.root = root
        self.rows, self.ents = [], {}

    def path(self, rel):
        p = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def png(self, rel, img, kind, **meta):
        data = img.png()
        with open(self.path(rel), "wb") as f:
            f.write(data)
        return self.row(rel, kind, hashlib.sha256(data).hexdigest(), **meta)

    def text(self, rel, body, kind, **meta):
        with open(self.path(rel), "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        return self.row(rel, kind, hashlib.sha256(body.encode("utf-8")).hexdigest(), **meta)

    def row(self, rel, kind, sha, **meta):
        r = {"file": rel, "kind": kind, "sha256": sha, "date": DATE, "models": []}
        r.update({k: v for k, v in meta.items() if v is not None})
        self.rows = [x for x in self.rows if x["file"] != rel] + [r]
        return r

    def record(self, kind, path, data):
        rel = os.path.relpath(path, self.root).replace(os.sep, "/")
        self.ents[rel] = dict(json.loads(json.dumps(data, default=_plain)), kind=kind)

    def res_path(self, res):
        return os.path.join(self.root, *res[len("res://"):].split("/"))


def _plain(v):
    return v.item() if hasattr(v, "item") else list(v)


def figure(w, h, body, step, shade):
    """A small standing figure, its legs apart by step: enough to see a walk in an importer's own viewer."""
    c = Canvas(w, h)
    c.rect(w // 2 - 4, 4, 8, 6, shade).rect(w // 2 - 3, 5, 6, 4, (236, 200, 160, 255))   # head
    c.rect(w // 2 - 5, 10, 10, 8, body)                                                     # body
    c.rect(w // 2 - 4 - step, 18, 3, 6, INK).rect(w // 2 + 1 + step, 18, 3, 6, INK)         # legs
    return c


def blob_tile(m, base, edge, frame=0):
    """An 8 px blob tile: the centre, plus an arm or corner for every set bit of the mask (N, NE, E, SE, S, SW, W, NW)."""
    c = Canvas(T, T).rect(2, 2, 4, 4, base)
    boxes = {0: (2, 0, 4, 2), 1: (6, 0, 2, 2), 2: (6, 2, 2, 4), 3: (6, 6, 2, 2), 4: (2, 6, 4, 2), 5: (0, 6, 2, 2),
             6: (0, 2, 2, 4), 7: (0, 0, 2, 2)}
    for b, (x, y, w, h) in boxes.items():
        if m >> b & 1:
            c.rect(x, y, w, h, base)
    if frame:
        c.rect(3, 3, 2, 2, edge)
    else:
        c.rect(3, 3, 1, 1, edge)
    return c


def atlas(tiles, cols, tw=T, th=T):
    rows = (len(tiles) + cols - 1) // cols
    a = Canvas(cols * tw, rows * th)
    for i, t in enumerate(tiles):
        if t is not None:
            a.paste(t, (i % cols) * tw, (i // cols) * th)
    return a


# ---- the pack ------------------------------------------------------------------------------------------
def build_game(root, with_godot=False):
    """Every asset of the golden pack into the game at root. Returns the Game (rows + records)."""
    import lane_ground
    import lane_iso
    import lane_platforms
    import lane_tiles
    import mapbuild
    g = Game(root)
    godot.ENABLED, godot.RECORD = with_godot, g.record
    try:
        _character(g)
        _effect(g)
        _prop_icon_portrait(g)
        ground = _ground(g, lane_ground)
        _map(g, mapbuild, ground)
        _pair(g, lane_tiles)
        _meadow_map(g)
        _platforms(g, lane_platforms)
        _iso(g, lane_iso)
        _iso_map(g)
        _font_ui(g)
        _extras(g)
    finally:
        godot.ENABLED, godot.RECORD = True, None
    return g


def _character(g):
    """hero: idle (2 frames) and walk (4) in s, e, n, w; walk_s holds its third frame twice; attack_e is a one-shot
    with a hold on its strike."""
    colours = {"s": (60, 110, 200, 255), "e": (60, 160, 90, 255), "n": (170, 70, 70, 255), "w": (190, 150, 50, 255)}
    out = "assets/art/characters/hero"
    anims = {}
    clips = [(f"{a}_{d}", d, n, fps, loop, holds) for d in "senw"
             for a, n, fps, loop, holds in (("idle", 2, 4, True, None),
                                            ("walk", 4, 8, True, [1.0, 1.0, 2.0, 1.0] if d == "s" else None))]
    clips.append(("attack_e", "e", 3, 10, False, [1.0, 2.0, 1.0]))
    W, H = 16, 24
    for name, d, n, fps, loop, holds in clips:
        files, sheet = [], Canvas(W * n, H)
        for i in range(n):
            fr = figure(W, H, colours[d], (i % 2) if name.startswith("walk") else 0, INK)
            if name.startswith("attack"):
                fr.rect(12, 11, 4 * i // 2 + 1, 2, (220, 220, 230, 255))   # the blade comes out
            fn = f"spr_hero_{name}_{i:02d}.png"
            g.png(f"{out}/frames/{fn}", fr, "frame", animation=name, canvas=[W, H], anchor="feet_bottom_center")
            sheet.paste(fr, i * W, 0)
            files.append(fn)
        g.png(f"{out}/hero_{name}_sheet.png", sheet, "sheet", animation=name, frames=n, fps=fps, loop=loop,
              canvas=[W, H], anchor="feet_bottom_center", durations=holds)
        data = {"frame_w": W, "frame_h": H, "frames": n, "fps": fps, "loop": loop, "anchor": "bottom_center"}
        if holds:
            data["durations"] = holds
        g.text(f"{out}/hero_{name}_sheet.json", json.dumps(data, indent=1), "sheet_data", animation=name)
        anims[name] = (files, fps, loop, holds) if holds else (files, fps, loop)
    godot.sprite_frames(g.path(f"{out}/hero_frames.tres"), f"{RES}/characters/hero/frames", anims)


def _effect(g):
    out = "assets/art/fx/spark"
    files = []
    for i in range(3):
        c = Canvas(16, 16).rect(8 - 2 * i - 1, 8 - 2 * i - 1, 4 * i + 2, 4 * i + 2, (255, 210, 90, 255))
        fn = f"spr_fx_spark_{i:02d}.png"
        g.png(f"{out}/{fn}", c, "fx_frame", canvas=[16, 16], anchor="center", blend="add")
        files.append(fn)
    godot.sprite_frames(g.path(f"{out}/fx_spark_frames.tres"), f"{RES}/fx/spark", {"play": (files, 12, False)})


def _prop_icon_portrait(g):
    crate = Canvas(16, 16).rect(2, 3, 12, 13, INK).rect(3, 4, 10, 11, (150, 100, 50, 255))
    g.png("assets/art/props/spr_crate.png", crate, "prop", size=[16, 16], content_bbox=[2, 3, 14, 16],
          anchor="bottom_center")
    godot.prop_scene(g.path("assets/art/props/prop_crate.tscn"), f"{RES}/props/spr_crate.png", (16, 16),
                     (2, 3, 14, 16), node_name="Crate", solid=True, footprint="base")
    for px in (16, 32):
        c = Canvas(px, px).rect(px // 4, px // 4, px // 2, px // 2 + px // 8, INK)
        c.rect(px // 4 + 1, px // 4 + 1, px // 2 - 2, px // 2 + px // 8 - 2, (200, 40, 60, 255))
        g.png(f"assets/art/ui/icons/ui_icon_potion_{px}.png", c, "icon", size=[px, px], anchor="center")
    out = "assets/art/portraits"
    for ex, mouth in (("", 1), ("_happy", 2), ("_talk", 3)):
        c = Canvas(24, 24).rect(4, 2, 16, 22, (120, 90, 160, 255)).rect(6, 4, 12, 12, (236, 200, 160, 255))
        c.rect(10, 12, 4, mouth, INK)
        g.png(f"{out}/spr_sage_portrait{ex}.png", c, "portrait", expression=ex[1:] or None, size=[24, 24])
    godot.sprite_frames(g.path(f"{out}/portrait_sage_frames.tres"), f"{RES}/portraits", {
        "idle": (["spr_sage_portrait.png"], 1, True),
        "talk": (["spr_sage_portrait.png", "spr_sage_portrait_talk.png"], 10, True)})


def _ground(g, lane_ground):
    """ground yard: a base with 2 variants, a path overlay (surface dirt), animated solid water (2 frames), 2 decals and
    a 1x2 door fixture; the rows the ground lane hands godot.tileset_layers."""
    out, res = "assets/art/tiles/yard", f"{RES}/tiles/yard"
    grass = [(70, 140, 60, 255), (80, 150, 66, 255)]
    g.png(f"{out}/base_grass.png", atlas([Canvas(T, T, c) for c in grass], 2), "tile_atlas", tile_px=T,
          terrains=["grass"])
    terrains = [("grass", (70, 140, 60)), ("path", (150, 120, 80)), ("water", (50, 90, 200))]
    sources = [{"atlas_res": f"{res}/base_grass.png", "kind": "base", "name": "grass",
                "tiles": [{"x": k, "y": 0, "terrain": None, "probability": 1.0 if k == 0 else 0.6} for k in range(2)]}]
    # 47 blob tiles, then two variants (a second full tile and a second lone tile, marked with a 2x2 dot) at
    # probability 0.6: of the map's two full path cells the variant pick (cell_roll) lands on one and not the other
    path_tiles = [blob_tile(m, (150, 120, 80, 255), INK) for m in lane_ground.BLOB]
    path_tiles += [blob_tile(255, (150, 120, 80, 255), (230, 200, 120, 255), 1), blob_tile(0, (150, 120, 80, 255), (230, 200, 120, 255), 1)]
    g.png(f"{out}/overlay_path.png", atlas(path_tiles, 12), "tile_atlas", tile_px=T, terrains=["path"], relief="flat",
          solid=False, variants="full and lone tiles twice (slots 47, 48)")
    path_rows = lane_ground.blob_rows(1, T, "dirt", False, 0, "organic")
    for i, m in ((47, 255), (48, 0)):
        path_rows.append({"x": i % 12, "y": i // 12, "terrain": 1, "probability": 0.6, "custom": "dirt",
                          "peers": tuple(1 if (m >> b) & 1 else -1 for b in range(8))})
    sources.append({"atlas_res": f"{res}/overlay_path.png", "kind": "overlay", "name": "path", "tiles": path_rows})
    n = 2   # animated water: frame f of tile i at column i % 12 * n + f (lane_ground.run)
    water = Canvas(12 * n * T, 4 * T)
    for i, m in enumerate(lane_ground.BLOB):
        for f in range(n):
            water.paste(blob_tile(m, (50, 90, 200, 255), (200, 230, 255, 255), f), ((i % 12) * n + f) * T, (i // 12) * T)
    g.png(f"{out}/overlay_water.png", water, "tile_atlas", tile_px=T, terrains=["water"], relief="sunken", solid=True)
    rows = lane_ground.blob_rows(2, T, None, True, 0, "organic")
    for r in rows:
        r["x"] *= n
        r["anim"] = {"frames": n, "fps": 4.0}
    sources.append({"atlas_res": f"{res}/overlay_water.png", "kind": "overlay", "name": "water", "tiles": rows})
    decals = [Canvas(T, T).rect(3, 4, 2, 2, (230, 230, 90, 255)), Canvas(T, T).rect(2, 5, 4, 1, (120, 90, 60, 255))]
    g.png(f"{out}/decals_yard.png", atlas(decals, 2), "tile_atlas", tile_px=T, layout="1x2 decals: flower, twig")
    sources.append({"atlas_res": f"{res}/decals_yard.png", "kind": "decals", "name": "decals",
                    "tiles": [{"x": k, "y": 0, "terrain": None} for k in range(2)]})
    door = [Canvas(T, T, (110, 70, 40, 255)).rect(0, 0, T, 1, INK), Canvas(T, T, (110, 70, 40, 255)).rect(5, 3, 1, 1, INK)]
    g.png(f"{out}/fixtures_yard.png", atlas(door, 12), "tile_atlas", tile_px=T, layout="door 1x2 from slot 0")
    fixtures = {"door": {"w": 1, "h": 2, "first": 0, "solid": True}}
    sources.append({"atlas_res": f"{res}/fixtures_yard.png", "kind": "fixtures", "name": "fixtures", "cols": 12,
                    "fixtures": fixtures, "tiles": [{"x": j, "y": 0, "terrain": None,
                                                     "solid_rects": [(-T // 2, -T // 2, T // 2, T // 2)]}
                                                    for j in range(2)]})
    godot.tileset_layers(g.path(f"{out}/ground_yard_tileset.tres"), T, sources, terrains, custom="surface",
                         physics=True, overlays=[1, 2], mode="match_corners_and_sides")
    return {"res": f"{res}/ground_yard_tileset.tres", "sources": sources, "terrains": terrains, "tile_px": T}


# the path is 3 cells thick in places, so some cells take the full tile (mask 255) and roll for its variant; water
# sits on the path (legend "w" paints both), as a real spec does
MAP = {"name": "yard", "seed": 3, "decal_density": 0.6,
       "rows": ["ggpppggg", "gppppggg", "gpwwpggg", "ggwwwggg", "gggggggg", "gggggggg"],
       "legend": {"g": [], "p": ["path"], "w": ["path", "water"]},
       "objects": [{"fixture": "door", "at": [7, 0]}], "props": [{"prop": "crate", "at": [1, 4]}]}


def _map(g, mapbuild, ground):
    layers, w, h = mapbuild.plan(MAP, ground)
    props = mapbuild.plan_props(MAP, T, "res://assets", "art")
    godot.record("map", g.path("assets/maps/yard.tscn"), {"tileset": ground["res"], "w": w, "h": h, "tile_px": T,
                                                         "layers": layers, "props": props})   # as mapbuild.build


def _meadow_map(g):
    """meadow_patch: a corners4 map on the pair set, 6 x 5: a base of the all-sand tile, then grass (terrain 0) painted
    as a 3 x 3 block with a 2 x 2 tail, every shape at least 2 cells thick (the corners rule's precondition)."""
    grass = [[x, y] for y in (1, 2, 3) for x in (1, 2, 3)] + [[4, 2], [4, 3]]
    godot.record("map", g.path("assets/maps/meadow_patch.tscn"), {
        "tileset": f"{RES}/tiles/meadow/meadow_tileset.tres", "w": 6, "h": 5, "tile_px": T, "layers": [
            {"name": "Sand", "kind": "tiles", "cells": [[x, y, 0, 0, 0] for y in range(5) for x in range(6)]},
            {"name": "Grass", "kind": "terrain", "terrain": 0, "cells": grass}], "props": []})


def _iso_map(g):
    """isle: an isometric map, 4 x 3 diamonds of 16 x 8: floors placed (two variants by parity), a 2 x 2 pond of the
    upper terrain (grass, terrain 1) painted with the corners rule, and one block (a taller tile with its own origin)."""
    godot.record("map", g.path("assets/maps/isle.tscn"), {
        "tileset": f"{RES}/tiles/iso/isle/iso_isle_tileset.tres", "w": 4, "h": 3, "tile_px": 16, "tile_size": [16, 8],
        "layers": [
            {"name": "Floor", "kind": "tiles", "cells": [[x, y, 0, (x + y) % 2, 0] for y in range(3) for x in range(4)]},
            {"name": "Grass", "kind": "terrain", "terrain": 1, "cells": [[1, 1], [2, 1], [1, 2], [2, 2]]},
            {"name": "Blocks", "kind": "tiles", "cells": [[3, 0, 1, 0, 0]]}], "props": []})


def _pair(g, lane_tiles):
    """meadow: the pair lane's 8x4 corner atlas (corners4), grass over sand."""
    out, res = "assets/art/tiles/meadow", f"{RES}/tiles/meadow"
    a, b = (90, 160, 70, 255), (220, 200, 140, 255)
    tiles = []
    for copy in (0, 1):
        for bits in range(16):
            c = Canvas(T, T, b)
            for k, (x, y) in enumerate(((0, 0), (4, 0), (0, 4), (4, 4))):   # NW, NE, SW, SE
                if bits >> k & 1:
                    c.rect(x, y, 4, 4, a)
            tiles.append((copy, bits, c))
    grid = Canvas(8 * T, 4 * T)
    for copy, bits, c in tiles:
        grid.paste(c, ((bits % 4) + 4 * copy) * T, (bits // 4) * T)
    g.png(f"{out}/tiles_meadow.png", grid, "tile_atlas", tile_px=T, terrains=["grass", "sand"])
    godot.tileset(g.path(f"{out}/meadow_tileset.tres"), f"{res}/tiles_meadow.png", T, 8,
                  lane_tiles.tile_rows(["grass", "sand"], {"grass": "grass", "sand": "sand"}),
                  [("grass", (90, 160, 70)), ("sand", (220, 200, 140))], "match_corners", custom="surface")


def _platforms(g, lane_platforms):
    """ledge: the platform lane's 16 side tiles (sides4, full collision) and 3 one-way caps."""
    out, res = "assets/art/tiles/platforms/ledge", f"{RES}/tiles/platforms/ledge"
    tiles = []
    for i in range(16):
        c = Canvas(T, T, (120, 85, 50, 255))
        if i & 1:
            c.rect(0, 0, T, 2, (90, 170, 70, 255))
        tiles.append(c)
    tiles += [Canvas(T, T).rect(0, 0, T, 2, (90, 170, 70, 255)) for _ in range(3)]
    g.png(f"{out}/platforms_ledge_atlas.png", atlas(tiles, 8), "tileset_atlas", tile=T, tiles=16, one_way=3)
    lane_platforms.tileset(g.path(f"{out}/platforms_ledge_tileset.tres"), f"{res}/platforms_ledge_atlas.png", T, 8)


def _iso(g, lane_iso):
    """isle: 2:1 isometric floors (2), one block 4 px tall, and one transition pair (corners4 on the diamond)."""
    out, res = "assets/art/tiles/iso/isle", f"{RES}/tiles/iso/isle"
    W, H, bh = 16, 8, 4

    def diamond(col):
        c = Canvas(W, H)
        for y in range(H):
            half = (y + 1) * 2 if y < H // 2 else (H - y) * 2
            c.rect(W // 2 - half, y, 2 * half, 1, col)
        return c
    g.png(f"{out}/iso_isle_floors.png", atlas([diamond((80, 150, 70, 255)), diamond((90, 160, 80, 255))], 2, W, H),
          "tileset_atlas", tile=[W, H], tiles=["grass_0", "grass_1"])
    block = Canvas(W, H + bh).rect(0, H // 2, W, bh + H // 2, (110, 110, 120, 255)).paste(diamond((150, 150, 160, 255)), 0, 0)
    g.png(f"{out}/iso_isle_blocks.png", block, "tileset_atlas", tile=[W, H + bh], tiles=1, origin_lift=bh // 2)
    trans = [diamond((80 + 8 * b, 150, 70, 255)) for b in range(16)]
    g.png(f"{out}/iso_isle_transitions.png", atlas(trans + trans, 32, W, H), "tileset_atlas", tile=[W, H], tiles=32)
    lane_iso.tileset(g.path(f"{out}/iso_isle_tileset.tres"), f"{res}/iso_isle_floors.png", 2,
                     f"{res}/iso_isle_blocks.png", 1, W, bh, f"{res}/iso_isle_transitions.png", [("sand", "grass")])


GLYPHS = {65: ["010", "101", "111", "101", "101"], 66: ["110", "101", "110", "101", "110"]}


def _font_ui(g):
    out = "assets/art/ui/fonts"
    page = Canvas(16, 8)
    lines = ['info face="tiny" size=5 bold=0 italic=0 charset="" unicode=1 stretchH=100 smooth=0 aa=0 '
             'padding=0,0,0,0 spacing=1,1', "common lineHeight=7 base=5 scaleW=16 scaleH=8 pages=1 packed=0",
             'page id=0 file="font_tiny.png"', "chars count=3",
             "char id=32 x=0 y=0 width=0 height=0 xoffset=0 yoffset=0 xadvance=3 page=0 chnl=15"]
    for k, (cid, rows) in enumerate(sorted(GLYPHS.items())):
        for y, row in enumerate(rows):
            for x, bit in enumerate(row):
                if bit == "1":
                    page.rect(1 + k * 4 + x, 1 + y, 1, 1, (255, 255, 255, 255))
        lines.append(f"char id={cid} x={1 + k * 4} y=1 width=3 height=5 xoffset=0 yoffset=0 xadvance=4 page=0 chnl=15")
    lines.append("kernings count=1")
    lines.append("kerning first=65 second=66 amount=-1")
    g.png(f"{out}/font_tiny.png", page, "font_page", font="font_tiny.fnt", scale=1, effect="none")
    g.text(f"{out}/font_tiny.fnt", "\n".join(lines) + "\n", "font", format="AngelCode BMFont text", glyphs=2,
           line_height=7, scale=1)
    ui = "assets/art/ui/windows"
    win = Canvas(12, 12, INK).rect(1, 1, 10, 10, (40, 50, 110, 255)).rect(2, 2, 8, 8, (60, 75, 150, 255))
    g.png(f"{ui}/ui_window_plain.png", win, "ui_window", style="plain", scale=1,
          patch_margins={"left": 3, "top": 3, "right": 3, "bottom": 3})
    for state, col in (("normal", (90, 90, 100, 255)), ("hover", (120, 120, 135, 255)), ("pressed", (60, 60, 70, 255))):
        g.png(f"{ui}/ui_button_plain_{state}.png", Canvas(10, 10, INK).rect(1, 1, 8, 8, col), "ui_button",
              state=state, scale=1, patch_margin=2)
    cur = Canvas(8, 8)
    for i in range(6):
        cur.rect(0, i, i + 1, 1, (250, 250, 250, 255))
    g.png(f"{ui}/cursor_pointer.png", cur, "ui_cursor", scale=1, hotspot=[0, 0])


def _extras(g):
    """The extra kinds an importer may skip: a scrolling background, particles, a transition, a normal map, an image."""
    sky = Canvas(32, 16, (120, 170, 230, 255)).rect(0, 12, 32, 4, (80, 120, 70, 255))
    g.png("assets/art/battle/bg/spr_bg_hills.png", sky, "battle_bg", size=[32, 16], display_scale=2)
    clouds = Canvas(32, 6).rect(4, 1, 8, 3, (250, 250, 250, 255)).rect(20, 2, 6, 2, (250, 250, 250, 255))
    g.png("assets/art/battle/bg/spr_bg_hills_clouds_near.png", clouds, "battle_bg_layer", rows=6, scroll_px_per_s=-4.0,
          seamless="horizontal")
    fx = "assets/art/fx/vfx/embers"
    g.png(f"{fx}/vfx_embers_particle.png", Canvas(2, 2, (255, 255, 255, 255)), "particle_texture", mask="dot")
    g.text(f"{fx}/vfx_embers_particles.json", json.dumps({"amount": 12, "lifetime": 1.4, "one_shot": False,
                                                          "colors": ["#ffd060", "#ff8030", "#802010"]}, indent=1) + "\n",
           "particles_json")
    rule = Canvas(8, 8)
    for y in range(8):
        for x in range(8):
            v = (x + y) * 255 // 14
            rule.rect(x, y, 1, 1, (v, v, v, 255))
    g.png("assets/art/ui/transitions/transition_wipe.png", rule, "transition_rule", transition="wipe", size=[8, 8])
    nm = Canvas(16, 16).rect(2, 3, 12, 13, (128, 128, 255, 255))
    g.png("assets/art/lit/yard/props/spr_crate_n.png", nm, "normal_map", pairs_with="assets/art/props/spr_crate.png",
          convention="opengl (green up, as Godot 4 expects)")
    g.png("assets/art/brand/golden/logo_golden.png", Canvas(12, 4, (240, 200, 60, 255)), "logo", scale=4)


# ---- write / check -------------------------------------------------------------------------------------
def make(out, with_godot=False):
    """The fixture into out (assets/ with the manifest and every file it names, expected.json). Returns the doc."""
    with tempfile.TemporaryDirectory() as tmp:
        g = build_game(tmp, with_godot)
        doc, warns = assetmap.build(tmp, ASSETS, {"assets": g.rows, "entities": g.ents}, PACK)
        if warns:
            raise RuntimeError("golden pack: " + "; ".join(warns))
        errs = assetspec.check(doc, os.path.join(tmp, ASSETS))
        if errs:
            raise RuntimeError("golden pack does not pass the spec:\n  " + "\n  ".join(errs[:20]))
        if os.path.isdir(out):
            shutil.rmtree(out)
        files = sorted(_files_of(doc) | ({a["godot"] for a in doc["assets"] if a.get("godot")} if with_godot else set()))
        for rel in files:
            dst = os.path.join(out, ASSETS, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(tmp, ASSETS, *rel.split("/")), dst)
        if with_godot:   # what the Godot side wrote that the manifest does not name (a SpriteFrames' scene etc.)
            for r in g.ents:
                src = os.path.join(tmp, *r.split("/"))
                if os.path.isfile(src):
                    dst = os.path.join(out, *r.split("/"))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copyfile(src, dst)
    mp = assetmap.manifest_path(os.path.join(out, ASSETS), PACK)
    os.makedirs(os.path.dirname(mp), exist_ok=True)
    with open(mp, "w", encoding="utf-8", newline="\n") as f:
        f.write(assetmap.text_of(doc))
    with open(os.path.join(out, "expected.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(assetspec.expected(doc), indent=1) + "\n")
    if not with_godot:   # a Godot game would import the fixture's PNGs as its own (as data/golden/shaders/ does)
        open(os.path.join(out, ".gdignore"), "w").close()
    return doc


def _files_of(doc):
    """Every path the manifest names."""
    out = set()

    def walk(v, key=None):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, str) and key in ("file", "image", "sheet", "texture", "target", "license", "pages"):
            out.add(v)
    walk(doc["assets"])
    return out


def tree(folder):
    """{relative path: content} with PNGs as their decoded pixels: what --check compares."""
    out = {}
    for base, _, files in os.walk(folder):
        for fn in files:
            p = os.path.join(base, fn)
            rel = os.path.relpath(p, folder).replace(os.sep, "/")
            if fn.endswith(".png"):
                out[rel] = ("png", png_pixels(p))
            else:
                with open(p, "rb") as f:
                    out[rel] = ("bytes", f.read().replace(b"\r\n", b"\n"))
    return out


def check(out):
    """Findings: files the committed fixture lacks, has too many of, or holds with other content."""
    with tempfile.TemporaryDirectory() as tmp:
        make(tmp)
        want, have = tree(tmp), tree(out) if os.path.isdir(out) else {}
    bad = [f"missing {k}" for k in sorted(set(want) - set(have))] + [f"extra {k}" for k in sorted(set(have) - set(want))]
    bad += [f"changed {k}" for k in sorted(set(want) & set(have)) if want[k] != have[k]]
    return bad


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="The golden fixture of Dotwork's engine-neutral asset manifest "
                                             "(data/golden/dotwork/). Exit 0 ok, 1 stale, 2 usage.")
    ap.add_argument("--write", action="store_true", help="rebuild the fixture")
    ap.add_argument("--check", action="store_true", help="exit 1 when the committed fixture differs from a rebuild")
    ap.add_argument("--godot", metavar="DIR", help="build the same pack with Godot's files into DIR (for a look)")
    ap.add_argument("--out", default=OUT, help=f"fixture folder (default {OUT})")
    a = ap.parse_args(argv)
    if a.godot:
        make(a.godot, with_godot=True)
        print(f"[ OK ] golden pack with Godot files: {a.godot}")
        return 0
    if a.write:
        doc = make(a.out)
        print(f"[ OK ] {len(doc['assets'])} assets -> {a.out}")
        return 0
    if a.check:
        bad = check(a.out)
        for b in bad:
            print(f"[fail] {b}")
        if bad:
            print("[fail] the golden fixture is stale: python tools/art/dotwork/tests/golden_assets.py --write")
            return 1
        print(f"[ OK ] golden fixture current: {a.out}")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
