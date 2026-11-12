#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_asset_manifest.py
# Purpose : Exam for the engine-neutral asset manifest (ASSET_MANIFEST.md): the spec's validator and reference loader
#           (assetspec.py), the writer (assetmap.py), the golden fixture (data/golden/dotwork/, golden_assets.py), and
#           real Dotwork packs: every model-free example pack written with --engine none and with Godot's files, both
#           validated, equal but for the Godot cross-references, and naming every PNG the pack shipped.
# Usage   : python tools/art/dotwork/tests/test_asset_manifest.py [-v]
# Exit    : 0 all pass, 1 a case failed
# Notes   : Offline, no GPU, about half a minute (ten example packs). Needs Dotwork's Pillow and numpy. Godot is the
#           reference: the SpriteFrames, TileSet and prop scene Dotwork writes for the golden pack are parsed here
#           and compared with what the manifest says (frames, holds, fps, loops, peering bits, origin, footprint).
#           Live, opt-in: DOTWORK_LIVE_GROUND=1 with GODOT_BIN and COMFYUI_ROOT renders a small ground pack and has
#           Godot paint its map; every terrain cell Godot chose must hold the tile the spec's rule names (2 minutes).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import copy
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
DOTWORK = os.path.dirname(HERE)
sys.path.insert(0, DOTWORK)
sys.path.insert(0, HERE)
import assetmap  # noqa: E402
import assetspec  # noqa: E402
import golden_assets  # noqa: E402

FIXTURE = golden_assets.OUT
MANIFEST = os.path.join(FIXTURE, "assets", "dotwork", "golden.assets.json")
PACKS = ("ui", "vfx", "status", "screen", "uikit")   # every example that needs no model
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", GODOT_BIN="")


def golden():
    return assetspec.load(MANIFEST)


def asset(doc, kind, name):
    return next(a for a in doc["assets"] if a["kind"] == kind and a["name"] == name)


def no_godot(v):
    """The document without its Godot cross-references (the only part --engine none leaves out)."""
    if isinstance(v, dict):
        return {k: no_godot(x) for k, x in v.items() if k != "godot"}
    if isinstance(v, list):
        return [no_godot(x) for x in v]
    return v


class Autotile(unittest.TestCase):
    def test_blob_has_47_masks_like_the_ground_lane(self):
        import lane_ground
        self.assertEqual(len(assetspec.BLOB), 47)
        self.assertEqual(list(assetspec.BLOB), list(lane_ground.BLOB))
        self.assertEqual(assetspec.NB8, tuple(tuple(x) for x in lane_ground.NB8))

    def test_corner_bits_need_both_sides(self):
        n, ne, e = assetspec.BIT["n"], assetspec.BIT["ne"], assetspec.BIT["e"]
        self.assertEqual(assetspec.canon(ne), 0)
        self.assertEqual(assetspec.canon(n | ne), n)
        self.assertEqual(assetspec.canon(n | ne | e), n | ne | e)
        painted = {(0, 0), (1, 0), (0, 1), (1, 1)}
        self.assertEqual(assetspec.cell_mask(painted, 0, 0), assetspec.BIT["e"] | assetspec.BIT["se"] | assetspec.BIT["s"])
        self.assertEqual(assetspec.cell_mask(painted, 0, 0, "sides4"), assetspec.BIT["e"] | assetspec.BIT["s"])

    def test_png_size_reads_the_header(self):
        self.assertEqual(assetspec.png_size(os.path.join(FIXTURE, "assets", "art", "ui", "icons", "ui_icon_potion_32.png")),
                         (32, 32))

    def test_corners_key_is_the_canon_masks_corner_bits(self):
        block = {(x, y) for x in (0, 1, 2) for y in (0, 1, 2)}
        self.assertEqual(assetspec.cell_mask(block, 1, 1, "corners4"), assetspec.CORNERS_ONLY)
        self.assertEqual(assetspec.cell_mask(block, 0, 0, "corners4"), assetspec.BIT["se"])      # the top-left cell
        self.assertEqual(assetspec.cell_mask(block, 1, 0, "corners4"), assetspec.BIT["se"] | assetspec.BIT["sw"])
        self.assertEqual(assetspec.cell_mask({(0, 0), (1, 1)}, 0, 0, "corners4"), 0)             # a diagonal touch
        self.assertEqual(assetspec.corners_of(assetspec.BIT["se"], "square", 3),
                         {"top_left": -1, "top_right": -1, "bottom_right": 3, "bottom_left": -1})
        self.assertEqual(assetspec.corners_of(assetspec.BIT["nw"] | assetspec.BIT["ne"], "isometric", 1),
                         {"top": 1, "right": 1, "bottom": -1, "left": -1})

    def test_hash_and_roll_vectors(self):
        self.assertEqual([assetspec.hash32(k) for k in (0, 1, 0xFFFFFFFF)], [1800329511, 3028713910, 4268016002])
        for cell, want in (((0, 0, 0), 0.169182), ((3, 1, 1), 0.765973), ((3, 2, 1), 0.531301), ((-1, -1, 0), 0.992978)):
            self.assertAlmostEqual(assetspec.cell_roll(*cell), want, places=6, msg=cell)
        self.assertEqual(assetspec.cell_roll(70000, 2, 3), assetspec.cell_roll(70000 - 65536, 2, 3))
        self.assertTrue(all(0 <= assetspec.cell_roll(x, y, L) < 1 for x in range(-3, 9) for y in range(-3, 9) for L in range(3)))

    def test_pick_walks_the_weights_in_order(self):
        cands = [(1, "a"), (0.6, "b")]
        self.assertEqual(assetspec.pick_variant(cands, 0.0), "a")
        self.assertEqual(assetspec.pick_variant(cands, 0.624), "a")
        self.assertEqual(assetspec.pick_variant(cands, 0.626), "b")
        self.assertEqual(assetspec.pick_variant([(0, "a"), (1, "b")], 0.0), "b")       # weight 0 is never picked
        self.assertEqual(assetspec.pick_variant([(0, "a"), (0, "b")], 0.9), "a")       # all zero: the first
        self.assertEqual(assetspec.pick_variant(cands, 0.9999999999), "b")

    def test_cell_centres_are_godots(self):
        iso = [16, 8]
        self.assertEqual(assetspec.cell_centre("isometric", 0, 0, iso), [8, 4])    # TileMapLayer.map_to_local, 4.7.2
        self.assertEqual(assetspec.cell_centre("isometric", 1, 0, iso), [16, 8])
        self.assertEqual(assetspec.cell_centre("isometric", 0, 1, iso), [0, 8])
        self.assertEqual(assetspec.cell_centre("isometric", 0, 2, iso), [-8, 12])
        self.assertEqual(assetspec.cell_centre("isometric", 3, 2, iso), [16, 24])
        self.assertEqual(assetspec.cell_centre("square", 2, 1, [8, 8]), [20, 12])


class CornersRule(unittest.TestCase):
    """What Godot 4.7.2's Match Corners painting chose over a base fill on the golden sets (probed 2026-11-11): the
    spec's rule must pick the same tiles. Shapes: a 2x2 block, a 3x3 block and a 3x3 L missing its bottom-right cell;
    grass (terrain 0) on the square pair set, grass (terrain 1, the upper material) on the iso transitions."""

    GODOT = {
        ("meadow", "block2"): {(3, 3): [0, 4, 2], (4, 3): [0, 4, 1], (3, 4): [0, 6, 0], (4, 4): [0, 5, 0]},
        ("meadow", "block3"): {(2, 2): [0, 4, 2], (3, 2): [0, 4, 3], (4, 2): [0, 4, 1], (2, 3): [0, 6, 2], (3, 3): [0, 7, 3],
                               (4, 3): [0, 5, 1], (2, 4): [0, 6, 0], (3, 4): [0, 7, 0], (4, 4): [0, 5, 0]},
        ("meadow", "ell"): {(2, 2): [0, 4, 2], (3, 2): [0, 4, 3], (4, 2): [0, 4, 1], (2, 3): [0, 6, 2], (3, 3): [0, 7, 1],
                            (4, 3): [0, 5, 0], (2, 4): [0, 6, 0], (3, 4): [0, 5, 0]},
        ("iso_isle", "block2"): {(3, 3): [2, 8, 0], (4, 3): [2, 4, 0], (3, 4): [2, 2, 0], (4, 4): [2, 1, 0]},
        ("iso_isle", "block3"): {(2, 2): [2, 8, 0], (3, 2): [2, 12, 0], (4, 2): [2, 4, 0], (2, 3): [2, 10, 0], (3, 3): [2, 15, 0],
                                 (4, 3): [2, 5, 0], (2, 4): [2, 2, 0], (3, 4): [2, 3, 0], (4, 4): [2, 1, 0]},
        ("iso_isle", "ell"): {(2, 2): [2, 8, 0], (3, 2): [2, 12, 0], (4, 2): [2, 4, 0], (2, 3): [2, 10, 0], (3, 3): [2, 7, 0],
                              (4, 3): [2, 1, 0], (2, 4): [2, 2, 0], (3, 4): [2, 1, 0]},
    }
    TERRAIN = {"meadow": 0, "iso_isle": 1}

    def test_spec_picks_godots_tiles(self):
        """Compared by what a tile is (centre terrain and corners), not by atlas slot: both sets hold their all-corners
        tile twice (one per centre copy), and Godot rolls between those duplicates as the spec rolls."""
        doc = golden()
        for (name, shape), want in self.GODOT.items():
            ts = asset(doc, "tileset", name)
            tiles = {(at["id"], t["col"], t["row"]): (t.get("terrain"), t.get("corners"))
                     for at in ts["atlases"] for t in at["tiles"]}
            layer = {"name": shape, "kind": "terrain", "terrain_set": 0, "terrain": self.TERRAIN[name],
                     "cells": [list(c) for c in want]}
            got = {(x, y): tiles[tuple(tile)] for x, y, _, tile in assetspec.resolve_terrain(ts, layer)}
            self.assertEqual(got, {c: tiles[tuple(t)] for c, t in want.items()}, (name, shape))

    def test_narrow_shapes_have_no_tile(self):
        ts = asset(golden(), "tileset", "meadow")
        for cells in ([[3, 3]], [[3, 3], [4, 3]], [[2, 3], [3, 3], [4, 3]], [[3, 3], [4, 4]]):
            got = assetspec.resolve_terrain(ts, {"name": "n", "kind": "terrain", "terrain": 0, "cells": cells})
            self.assertTrue(all(tile is None for *_, tile in got), cells)


class Validator(unittest.TestCase):
    """Every rule the spec states, broken once on a copy of the golden manifest."""

    def setUp(self):
        self.doc = golden()
        self.base = os.path.join(FIXTURE, "assets")

    def findings(self, mutate):
        d = copy.deepcopy(self.doc)
        mutate(d)
        return assetspec.check(d, self.base)

    def assertFinds(self, mutate, text):
        errs = self.findings(mutate)
        self.assertTrue(any(text in e for e in errs), f"no finding with {text!r} in {errs[:5]}")

    def test_golden_passes(self):
        self.assertEqual(assetspec.check(self.doc, self.base), [])

    def test_schema_rules(self):
        self.assertFinds(lambda d: d.pop("pack"), "missing 'pack'")
        self.assertFinds(lambda d: d.update(version="2.0.0"), "does not match")
        self.assertFinds(lambda d: d["assets"].append({"kind": "mesh", "name": "x"}), "is not one of")
        self.assertFinds(lambda d: asset(d, "sprite", "crate").update(extra=1), "unknown key 'extra'")
        self.assertFinds(lambda d: asset(d, "sprite", "crate").update(size=[16]), "at least 2")
        self.assertFinds(lambda d: asset(d, "animated_sprite", "hero")["clips"][0].update(fps=0), "must be above 0")
        self.assertFinds(lambda d: asset(d, "sprite", "crate").update(image="../outside.png"), "no '..'")

    def test_animation_rules(self):
        def holds(d):
            asset(d, "animated_sprite", "hero")["clips"][0]["holds"] = [1.0]
        self.assertFinds(holds, "holds for")

        def duration(d):
            asset(d, "animated_sprite", "hero")["clips"][0]["frames"][0]["duration"] = 9.0
        self.assertFinds(duration, "is not hold")

        def rect(d):
            c = asset(d, "animated_sprite", "hero")["clips"][0]
            c["frames"][-1]["rect"][0] += 16
        self.assertFinds(rect, "leaves the")

        def direction(d):
            asset(d, "animated_sprite", "hero")["directions"]["walk"]["s"] = "nope"
        self.assertFinds(direction, "not in clips")

    def test_tile_and_map_rules(self):
        def mask(d):
            ts = asset(d, "tileset", "ground_yard")
            next(t for a in ts["atlases"] for t in a["tiles"] if "mask" in t)["mask"] = 2   # NE alone is no blob mask
        self.assertFinds(mask, "47 blob masks")

        def cell(d):
            asset(d, "map", "yard")["layers"][0]["cells"][0][3] = 40
        self.assertFinds(cell, "does not have")

        def obj(d):
            asset(d, "map", "yard")["objects"][0]["asset"] = "barrel"
        self.assertFinds(obj, "not an asset")

        def coll(d):
            ts = asset(d, "tileset", "ground_yard")
            next(t for a in ts["atlases"] for t in a["tiles"] if t.get("collision"))["collision"][0]["rect"] = [0, 0, 9, 9]
        self.assertFinds(coll, "leaves the 8x8 tile")

        def narrow(d):
            asset(d, "map", "meadow_patch")["layers"][1]["cells"].append([0, 0])    # a lone grass cell
        self.assertFinds(narrow, "no tile for 1 cell(s) (0,0)")

        def stamp_index(d):
            asset(d, "map", "yard")["layers"][-1]["cells"][0][2] = 5
        self.assertFinds(stamp_index, "names stamp [5]")

        def stamp_edge(d):
            asset(d, "map", "yard")["layers"][-1]["cells"][0][1] = 5                # a 1x2 door from the last row
        self.assertFinds(stamp_edge, "leaves the 8x6 map")

        def corner_names(d):
            ts = asset(d, "tileset", "iso_isle")
            next(t for a in ts["atlases"] for t in a["tiles"] if "corners" in t)["corners"] = {"top_left": 1}
        self.assertFinds(corner_names, "names the corners ['bottom', 'left', 'right', 'top']")

    def test_missing_file_and_wrong_size(self):
        self.assertFinds(lambda d: asset(d, "sprite", "crate").update(image="art/props/gone.png"), "not found")
        self.assertFinds(lambda d: asset(d, "sprite", "crate").update(size=[17, 16]), "the manifest says 17x16")

    def test_unknown_schema_keyword_is_refused(self):
        with self.assertRaises(assetspec.SpecError):
            assetspec.check_schema(1, {"multipleOf": 2}, {})

    def test_cli_exit_codes(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(assetspec.main(["validate", MANIFEST]), 0)
            with tempfile.TemporaryDirectory() as tmp:
                bad = os.path.join(tmp, "bad.assets.json")
                d = copy.deepcopy(self.doc)
                d["version"] = "1.0"
                with open(bad, "w", encoding="utf-8") as f:
                    json.dump(d, f)
                self.assertEqual(assetspec.main(["validate", bad]), 1)
            with redirect_stdout(io.StringIO()), _quiet_stderr():
                self.assertEqual(assetspec.main(["validate", os.path.join(FIXTURE, "nope.json")]), 2)


class _quiet_stderr:
    def __enter__(self):
        self.old, sys.stderr = sys.stderr, io.StringIO()

    def __exit__(self, *exc):
        sys.stderr = self.old


class Golden(unittest.TestCase):
    def test_fixture_is_current(self):
        self.assertEqual(golden_assets.check(FIXTURE), [], "run python tools/art/dotwork/tests/golden_assets.py --write")

    def test_expected_is_the_reference_loaders_result(self):
        with open(os.path.join(FIXTURE, "expected.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), json.loads(json.dumps(assetspec.expected(golden()))))

    def test_every_kind_is_in_the_fixture(self):
        self.assertEqual(sorted({a["kind"] for a in golden()["assets"]}), sorted(assetspec.KINDS))
        layer_kinds = {L["kind"] for a in golden()["assets"] if a["kind"] == "map" for L in a["layers"]}
        self.assertEqual(sorted(layer_kinds), sorted(assetspec.LAYER_KINDS))
        e = assetspec.load(os.path.join(FIXTURE, "expected.json"))["assets"]
        self.assertEqual(sorted({v["shape"] for k, v in e.items() if k.startswith("map/")}), ["isometric", "square"])

    def test_loaded_values(self):
        e = assetspec.load(os.path.join(FIXTURE, "expected.json"))["assets"]
        walk = e["animated_sprite/hero"]["clips"]["walk_s"]
        self.assertEqual(walk["seconds"], [0.125, 0.125, 0.25, 0.125])   # holds 1, 1, 2, 1 at 8 fps
        self.assertEqual(walk["length"], 0.625)
        self.assertEqual(walk["pivot"], [8, 24])                          # the feet: bottom centre
        self.assertFalse(e["animated_sprite/hero"]["clips"]["attack_e"]["loop"])
        self.assertEqual(sorted(e["animated_sprite/hero"]["directions"]["walk"]), ["e", "n", "s", "w"])
        self.assertEqual(e["sprite/crate"], {"size": [16, 16], "pivot": [8, 16], "collision": [[3, 4, 10, 12]]})
        self.assertEqual(e["tileset/ground_yard"]["animated_tiles"], 47)
        self.assertEqual(len(e["tileset/ground_yard"]["masks"]["0/1"]), 47)
        for layer in e["map/yard"]["terrain"].values():
            for x, y, m, tile in layer:
                self.assertIn(m, assetspec.BLOB)
                self.assertIsNotNone(tile, f"no tile for mask {m} at {x},{y}")
        path = {(x, y): tile for x, y, _, tile in e["map/yard"]["terrain"]["Path"]}
        self.assertEqual((path[(3, 1)], path[(3, 2)]), ([1, 11, 3], [1, 10, 3]))   # two full cells, one rolls the variant
        self.assertEqual(e["map/yard"]["layers"]["Fixtures"], 2)                      # the door stamp, expanded
        self.assertEqual(e["map/yard"]["placed"]["Fixtures"], [[7, 0, 4, 0, 0, 56, 0], [7, 1, 4, 1, 0, 56, 8]])
        self.assertEqual(e["map/yard"]["centres"][0], [0, 0, 4, 4])
        grass = {(x, y): tile for x, y, _, tile in e["map/meadow_patch"]["terrain"]["Grass"]}
        self.assertEqual(grass[(2, 2)], [0, 7, 3])                                    # all four corners grass
        self.assertEqual(grass[(1, 1)], [0, 4, 2])                                    # only the bottom-right corner
        isle = e["map/isle"]
        self.assertEqual((isle["shape"], isle["tile_size"]), ("isometric", [16, 8]))
        self.assertEqual(isle["placed"]["Blocks"], [[3, 0, 1, 0, 0, 24, 8]])          # origin [8, 8]: lifted 4 px
        self.assertEqual(isle["placed"]["Grass"][0], [1, 1, 2, 8, 0, 0, 8])
        self.assertIn([0, 1, 0, 8], isle["centres"])


class GodotReference(unittest.TestCase):
    """The golden pack built with Godot's files: the manifest is the same, and says what those files say."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        with redirect_stdout(io.StringIO()):
            cls.doc = golden_assets.make(cls.tmp, with_godot=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def read(self, rel):
        with open(os.path.join(self.tmp, "assets", *rel.split("/")), encoding="utf-8") as f:
            return f.read()

    def test_same_manifest_with_or_without_godot(self):
        self.assertEqual(no_godot(self.doc), no_godot(golden()))
        self.assertEqual(asset(self.doc, "animated_sprite", "hero")["godot"], "art/characters/hero/hero_frames.tres")
        self.assertNotIn("godot", asset(golden(), "animated_sprite", "hero"))

    def test_sprite_frames(self):
        hero = asset(self.doc, "animated_sprite", "hero")
        text = self.read(hero["godot"])
        ext = dict(re.findall(r'path="[^"]*/([^"/]+)" id="([^"]+)"', text))
        ids = {v: k for k, v in ext.items()}
        anims = re.findall(r'\{\n"frames": \[(.*?)\],\n"loop": (true|false),\n"name": &"([^"]+)",\n"speed": ([0-9.]+)', text, re.S)
        self.assertEqual(len(anims), len(hero["clips"]))
        clips = {c["name"]: c for c in hero["clips"]}
        for frames, loop, name, speed in anims:
            c = clips[name]
            got = re.findall(r'"duration": ([0-9.]+),\n"texture": ExtResource\("([^"]+)"\)', frames)
            self.assertEqual([ids[r] for _, r in got], [f["file"].rsplit("/", 1)[1] for f in c["frames"]])
            self.assertEqual(loop == "true", c["loop"])
            self.assertEqual(float(speed), c["fps"])
            for (d, _), f in zip(got, c["frames"]):
                self.assertAlmostEqual(float(d) / float(speed), f["duration"])   # Godot: duration / speed seconds

    def test_tileset_peering_bits(self):
        ts = asset(self.doc, "tileset", "ground_yard")
        text = self.read(ts["godot"])
        order = ("top_side", "top_right_corner", "right_side", "bottom_right_corner", "bottom_side",
                 "bottom_left_corner", "left_side", "top_left_corner")
        for at in ts["atlases"]:
            block = text.split(f'[sub_resource type="TileSetAtlasSource" id="TileSetAtlasSource_{at["id"] + 1}"]')[1]
            block = block.split("[sub_resource")[0].split("[resource]")[0]
            for t in at["tiles"]:
                k = f'{t["col"]}:{t["row"]}/0'
                self.assertIn(f"\n{k} = 0", block)
                if "mask" in t:
                    peers = dict(re.findall(r"(?m)^" + re.escape(k) + r"/terrains_peering_bit/(\w+) = (-?\d+)", block))
                    got = sum(1 << b for b, name in enumerate(order) if int(peers[name]) == t["terrain"])
                    self.assertEqual(got, t["mask"], k)
                polys = re.findall(r"(?m)^" + re.escape(k) + r"/physics_layer_0/polygon_\d+/points = PackedVector2Array\(([^)]*)\)", block)
                self.assertEqual(len(polys), len(t.get("collision") or []), k)
                for poly, c in zip(polys, t.get("collision") or []):
                    v = [float(x) for x in poly.split(",")]
                    x0, y0 = min(v[0::2]) + 4, min(v[1::2]) + 4     # tile-centre coordinates -> the tile's corner
                    self.assertEqual([x0, y0, max(v[0::2]) - min(v[0::2]), max(v[1::2]) - min(v[1::2])], c["rect"])

    def test_prop_scene(self):
        crate = asset(self.doc, "sprite", "crate")
        text = self.read(crate["godot"])
        ox, oy = (float(v) for v in re.search(r"offset = Vector2\(([-\d.]+), ([-\d.]+)\)", text).groups())
        w, h = crate["size"]
        self.assertEqual([w / 2 - ox, h / 2 - oy], crate["pivot"])   # a centred Sprite2D shifted onto the origin
        sw, sh = (float(v) for v in re.search(r"size = Vector2\(([-\d.]+), ([-\d.]+)\)", text).groups())
        py = float(re.search(r"position = Vector2\(0, ([-\d.]+)\)", text).group(1))
        x, y, cw, ch = crate["collision"][0]["rect"]
        self.assertEqual([cw, ch], [sw, sh])
        self.assertEqual([x + cw / 2 - crate["pivot"][0], y + ch / 2 - crate["pivot"][1]], [0, py])


class Writer(unittest.TestCase):
    def test_stale_record_is_skipped_with_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {"assets": [], "entities": {"assets/art/fx/x/fx_x_frames.tres": {
                "kind": "frames", "res_dir": "res://assets/art/fx/x", "animations": {"play": [["gone.png"], 8, True, None]}}}}
            doc, warns = assetmap.build(tmp, "assets", data, "p")
            self.assertEqual(doc["assets"], [])
            self.assertTrue(warns and "not in the game" in warns[0])

    def test_pivots(self):
        self.assertEqual(assetmap.pivot_of("feet_bottom_center", 16, 24), [8, 24])
        self.assertEqual(assetmap.pivot_of("center", 15, 9), [7.5, 4.5])
        self.assertEqual(assetmap.pivot_of(None, 4, 4), [2, 2])
        self.assertEqual(assetmap.pivot_of("right", 32, 8), [32, 4])
        self.assertEqual(assetmap.pivot_of("tail_tip_bottom_left_third", 16, 15), [4, 15])

    def test_written_only_when_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p, changed, _ = assetmap.write(tmp, "assets", {"assets": []}, "p")
            self.assertTrue(changed)
            self.assertEqual(assetmap.write(tmp, "assets", {"assets": []}, "p")[1], False)
            self.assertTrue(p.endswith(os.path.join("assets", "dotwork", "p.assets.json")))


def dotwork(game, *args):
    r = subprocess.run([sys.executable, os.path.join(DOTWORK, "dotwork.py"), *args, "--project", game],
                       capture_output=True, encoding="utf-8", errors="replace", env=ENV, cwd=game)
    return r.returncode, r.stdout + r.stderr


class RealPacks(unittest.TestCase):
    """Every model-free example pack, built twice: --engine none, and Godot's files (no Godot run)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.none, cls.gd = os.path.join(cls.tmp, "none"), os.path.join(cls.tmp, "gd")
        os.makedirs(cls.none)
        os.makedirs(cls.gd)
        with open(os.path.join(cls.none, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("# a game\n")
        with open(os.path.join(cls.gd, "project.godot"), "w", encoding="utf-8") as f:
            f.write('config_version=5\n[application]\nconfig/name="t"\n')
        cls.out = {}
        for p in PACKS:
            spec = os.path.join(DOTWORK, "examples", f"{p}.json")
            cls.out[("none", p)] = dotwork(cls.none, "pack", "--spec", spec, "--engine", "none")
            cls.out[("gd", p)] = dotwork(cls.gd, "pack", "--spec", spec, "--no-verify")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def manifests(self, game):
        return {p: assetspec.load(assetmap.manifest_path(os.path.join(game, "assets"), p)) for p in PACKS}

    def test_packs_pass(self):
        for k, (code, out) in self.out.items():
            self.assertEqual(code, 0, f"{k}: {out[-1500:]}")
            self.assertIn("[ OK ] asset manifest", out, k)

    def test_manifests_validate(self):
        for game in (self.none, self.gd):
            for p, doc in self.manifests(game).items():
                self.assertEqual(assetspec.check(doc, os.path.join(game, "assets")), [], p)

    def test_same_without_godot(self):
        # one exception: two packs ship font_dialogue.fnt (ui at scale 2, uikit its own); both games built them in the
        # same order, and a pack rebuilds every manifest, so the last one written wins in both
        a, b = self.manifests(self.none), self.manifests(self.gd)
        for p in PACKS:
            self.assertEqual(no_godot(a[p]), no_godot(b[p]), p)
        self.assertTrue(any(x.get("godot") for x in b["status"]["assets"]))

    def test_every_shipped_png_is_named(self):
        """Every PNG a pack's provenance rows list under assets/ is in that pack's asset manifest."""
        for game in (self.none, self.gd):
            for p, doc in self.manifests(game).items():
                named = golden_assets._files_of(doc)
                with open(os.path.join(game, "assets_src", "dotwork", f"manifest_{p}.json"), encoding="utf-8") as f:
                    rows = json.load(f)["assets"]
                pngs = {r["file"][len("assets/"):] for r in rows if r["file"].startswith("assets/")
                        and r["file"].endswith(".png")}
                self.assertEqual(sorted(pngs - named), [], p)

    def test_manifest_command(self):
        code, out = dotwork(self.none, "manifest", "--check", "--engine", "none")
        self.assertEqual(code, 0, out)
        path = assetmap.manifest_path(os.path.join(self.none, "assets"), "status")
        doc = assetspec.load(path)
        doc["assets"][0]["clips"][0]["loop"] = not doc["assets"][0]["clips"][0]["loop"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        code, out = dotwork(self.none, "manifest", "--check", "--engine", "none")
        self.assertEqual(code, 1, out)
        self.assertIn("differs from what its provenance manifest gives now", out)
        code, out = dotwork(self.none, "manifest", "--engine", "none")
        self.assertEqual(code, 0, out)
        self.assertEqual(dotwork(self.none, "manifest", "--check", "--engine", "none")[0], 0)

    def test_untouched_hand_polish_round_trip_changes_no_manifest(self):
        """The ui pack's hit effects go to Pixelorama and back untouched: no provenance or asset manifest changes."""
        def snap():
            out = {}
            for sub in (("assets", "dotwork"), ("assets_src", "dotwork")):
                folder = os.path.join(self.none, *sub)
                for fn in sorted(os.listdir(folder)):
                    with open(os.path.join(folder, fn), "rb") as f:
                        out[fn] = f.read()
            return out
        code, out = dotwork(self.none, "pixelorama", "--engine", "none")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isdir(os.path.join(self.none, "assets_src", "pixelorama", "fx")), out)
        before = snap()
        code, out = dotwork(self.none, "pixelorama", "--reexport", "--engine", "none")
        self.assertEqual(code, 0, out)
        self.assertIn("0 files changed", out)
        self.assertEqual(snap(), before, out[-800:])

    def test_status_loop_is_a_sheet_clip(self):
        doc = self.manifests(self.none)["status"]
        poison = asset(doc, "animated_sprite", "status_poison")
        c = poison["clips"][0]
        self.assertEqual((c["name"], c["loop"], len(c["frames"])), ("poison", True, 8))
        self.assertEqual(c["sheet"], "art/fx/status/poison/status_poison_sheet.png")
        self.assertEqual([f["rect"][0] for f in c["frames"]], [i * c["frame_size"][0] for i in range(8)])


YARD = {"name": "yard", "ground": {
    "name": "yard", "base": [{"material": "grass_lush", "variants": 2}],
    "overlays": [{"material": "dirt", "relief": "flat", "variants": 1},
                 {"material": "water_deep", "relief": "sunken", "solid": True, "animate": {"frames": 2}}],
    "map": {"name": "yard_map", "rows": ["ggdddggg", "gdddgggg", "gdwwgggg", "ggwwwggg", "gggggwgg", "ggggwwwg"],
            "legend": {"g": [], "d": ["dirt"], "w": ["dirt", "water_deep"]}}}}


@unittest.skipUnless(os.environ.get("DOTWORK_LIVE_GROUND") and os.environ.get("GODOT_BIN"),
                     "set DOTWORK_LIVE_GROUND=1, GODOT_BIN and COMFYUI_ROOT (renders 3 textures, about 3 minutes)")
class LiveGroundExam(unittest.TestCase):
    """A real ground pack (ComfyUI renders, Godot paints the map): every terrain cell Godot's solver chose holds the
    tile the spec's rule names (the mask of its painted neighbours)."""

    def test_godot_paints_what_the_spec_resolves(self):
        with tempfile.TemporaryDirectory() as game:
            with open(os.path.join(game, "project.godot"), "w", encoding="utf-8") as f:
                f.write('config_version=5\n[application]\nconfig/name="t"\n')
            spec = os.path.join(game, "yard.json")
            with open(spec, "w", encoding="utf-8") as f:
                json.dump(YARD, f)
            r = subprocess.run([sys.executable, os.path.join(DOTWORK, "dotwork.py"), "pack", "--spec", spec,
                                "--project", game], capture_output=True, encoding="utf-8", errors="replace", cwd=game)
            self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-2000:])
            doc = assetspec.load(assetmap.manifest_path(os.path.join(game, "assets"), "yard"))
            self.assertEqual(assetspec.check(doc, os.path.join(game, "assets")), [])
            with open(os.path.join(game, "art_src", "dotwork", "mapbuild", "yard_map_report.json"), encoding="utf-8") as f:
                rep = json.load(f)
            ts, mp = asset(doc, "tileset", "ground_yard"), asset(doc, "map", "yard_map")
            tiles = {(at["id"], t["col"], t["row"]): t for at in ts["atlases"] for t in at["tiles"]}
            n = 0
            for L in (x for x in mp["layers"] if x["kind"] == "terrain"):
                chosen = {(int(c[0]), int(c[1])): (int(c[2]), int(c[3]), int(c[4]))
                          for c in next(x for x in rep["layers"] if x["name"] == L["name"])["cells"]}
                self.assertEqual(set(chosen), {(c[0], c[1]) for c in L["cells"]}, L["name"])
                for x, y, m, _ in assetspec.resolve_terrain(ts, L):
                    self.assertEqual(tiles[chosen[(x, y)]]["mask"], m, f"{L['name']} {x},{y}")
                    n += 1
            self.assertGreater(n, 20)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    unittest.main()
