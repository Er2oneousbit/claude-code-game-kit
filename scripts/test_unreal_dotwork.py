#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_unreal_dotwork.py
# Purpose : Exam for the plain-Python half of the Unreal Dotwork importer
#           (engines/unreal/skeleton/Content/Python/kit_dotwork/dotwork_spec.py), without Unreal: its port of the
#           terrain rules matches tools/art/dotwork/assetspec.py on every neighbourhood and mode (the corners4 keys of
#           a 3x3 block among them), its hash and roll give the spec's test vectors, its terrain resolution (the
#           variant pick included), stamps expansion, cell centres and draw corners match the reference loader and
#           expected.json on the golden pack's three maps, every golden clip gets a flipbook rate with whole frame
#           runs, and the version check, path check and comparison behave.
# Usage   : python scripts/test_unreal_dotwork.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only. The Paper2D half (assets built and read back) runs in the editor:
#           `python tools/dev.py test` in a scaffolded Unreal project (#58).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): layer index, corners4, the
#           hash and roll vectors, stamps, centres and placed cells against expected.json, particles as an extra kind
# Updated : 2026-11-14 with Claude (Opus 5.5, claude-opus-5-5): five golden terrain layers (atlas_order_check)
# Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): #286: font_layout (glyph cells with the x offset
#           drawn in, so an offline Font lands every glyph and advance where the BMFont does), the tile user data
#           (surface and animation), the plain-Python PNG reader the importer lays font pages out with
# ---------------------------------------------------------------------------
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
SPEC_PY = KIT / "engines" / "unreal" / "skeleton" / "Content" / "Python" / "kit_dotwork" / "dotwork_spec.py"
ASSETSPEC_PY = KIT / "core" / "tools" / "art" / "dotwork" / "assetspec.py"
GOLDEN = KIT / "core" / "data" / "golden" / "dotwork"
MANIFEST = GOLDEN / "assets" / "dotwork" / "golden.assets.json"
EXPECTED = GOLDEN / "expected.json"
# ASSET_MANIFEST.md "Variants: the probability pick" and "Placing tiles": the vectors every engine must give
HASH_VECTORS = {0: 1800329511, 1: 3028713910, 0xFFFFFFFF: 4268016002}
ROLL_VECTORS = {(0, 0, 0): 0.169182, (3, 1, 1): 0.765973, (3, 2, 1): 0.531301, (-1, -1, 0): 0.992978}
ISO_CENTRES = {(0, 0): [8, 4], (1, 0): [16, 8], (0, 1): [0, 8], (3, 2): [16, 24]}   # a 16x8 diamond set


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ds = load(SPEC_PY, "dotwork_spec")
dpng = load(SPEC_PY.parent / "dotwork_png.py", "dotwork_png")
ref = load(ASSETSPEC_PY, "assetspec")


def golden_maps():
    """(map asset, its tileset asset) for every golden map."""
    doc = ds.load(MANIFEST)
    tilesets = {a["name"]: a for a in doc["assets"] if a["kind"] == "tileset"}
    return [(a, tilesets[a["tileset"]]) for a in doc["assets"] if a["kind"] == "map"]


def expected_maps():
    with open(EXPECTED, encoding="utf-8") as f:
        return {k: v for k, v in json.load(f)["assets"].items() if k.startswith("map/")}


class TerrainRules(unittest.TestCase):
    def test_every_neighbourhood_matches_the_reference_in_every_mode(self):
        for mode in ("blob47", "sides4", "corners4"):
            for raw in range(256):
                painted = {(1 + dx, 1 + dy) for b, (dx, dy) in enumerate(ds.NB8) if raw >> b & 1} | {(1, 1)}
                self.assertEqual(ds.cell_mask(painted, 1, 1, mode), ref.cell_mask(painted, 1, 1, mode), (mode, raw))

    def test_corners4_keys_of_a_three_by_three_block(self):
        block = {(x, y) for x in range(3) for y in range(3)}
        self.assertEqual(ds.cell_mask(block, 1, 1, "corners4"), 170)   # all four corners
        self.assertEqual(ds.cell_mask(block, 0, 0, "corners4"), 8)     # top-left cell: only its SE corner
        self.assertEqual(ds.cell_mask(block, 1, 0, "corners4"), 40)    # top-middle: SE and SW

    def test_corners4_tile_keys_follow_the_shape(self):
        square = {"terrain": 1, "corners": {"top_left": 1, "top_right": -1, "bottom_right": 1, "bottom_left": -1}}
        self.assertEqual(ds.tile_key(square, "corners4", "square"), 128 + 8)
        iso = {"terrain": 1, "corners": {"top": 1, "right": 1, "bottom": -1, "left": -1}}
        self.assertEqual(ds.tile_key(iso, "corners4", "isometric"), 128 + 2)
        self.assertIsNone(ds.tile_key(iso, "corners4", "square"))      # wrong corner names for the shape
        self.assertEqual(ds.tile_key({"mask": 255}, "blob47", "square"), 255)

    def test_hash_and_roll_vectors(self):
        for k, want in HASH_VECTORS.items():
            self.assertEqual(ds.hash32(k), want, k)
            self.assertEqual(ds.hash32(k), ref.hash32(k), k)
        for (x, y, layer), want in ROLL_VECTORS.items():
            self.assertAlmostEqual(ds.cell_roll(x, y, layer), want, delta=1e-6, msg=(x, y, layer))
            self.assertEqual(ds.cell_roll(x, y, layer), ref.cell_roll(x, y, layer), (x, y, layer))

    def test_pick_walks_the_weights_in_atlas_order(self):
        cands = [(0.6, "a"), (1, "b"), (0, "never")]
        self.assertEqual(ds.pick_variant(cands, 0.0), "a")
        self.assertEqual(ds.pick_variant(cands, 0.3749), "a")           # 0.3749 * 1.6 = 0.59984 < 0.6
        self.assertEqual(ds.pick_variant(cands, 0.375), "b")
        self.assertEqual(ds.pick_variant(cands, 0.999999), "b")
        self.assertEqual(ds.pick_variant([(0, "x"), (0, "y")], 0.5), "x")

    def test_golden_terrain_layers_resolve_like_the_reference_with_the_layer_index(self):
        n, variants = 0, 0
        for a, ts in golden_maps():
            for i, L in enumerate(a["layers"]):
                if L["kind"] == "terrain":
                    got = ds.resolve_terrain(ts, L, i)
                    self.assertEqual(got, ref.resolve_terrain(ts, L, i), (a["name"], L["name"]))
                    self.assertTrue(all(tile is not None for _, _, _, tile in got), (a["name"], L["name"]))
                    # yard's Path layer holds two full cells: one rolls the 0.6 variant, the other the base tile
                    variants += sum(1 for _, _, k, tile in got if a["name"] == "yard" and k == 255 and tile[1] == 11)
                    n += 1
        self.assertEqual(n, 5)   # yard Path and Water, meadow_patch Grass, isle Grass, atlas_order_check Marker
        self.assertEqual(variants, 1)

    def test_golden_terrain_matches_expected_json(self):
        want = expected_maps()
        for a, ts in golden_maps():
            for i, L in enumerate(a["layers"]):
                if L["kind"] == "terrain":
                    self.assertEqual(ds.resolve_terrain(ts, L, i), want[f"map/{a['name']}"]["terrain"][L["name"]],
                                     (a["name"], L["name"]))

    def test_paper2d_layer_zero_is_the_top_layer(self):
        self.assertEqual([ds.paper_layer_index(i, 5) for i in range(5)], [4, 3, 2, 1, 0])


class Placement(unittest.TestCase):
    def test_isometric_centres(self):
        for (x, y), want in ISO_CENTRES.items():
            self.assertEqual(ds.cell_centre("isometric", x, y, [16, 8]), want, (x, y))
            self.assertEqual(ds.cell_centre("isometric", x, y, [16, 8]), ref.cell_centre("isometric", x, y, [16, 8]))
        self.assertEqual(ds.cell_centre("square", 3, 2, [8, 8]), [28, 20])

    def test_a_stamps_layer_expands_in_reading_order(self):
        ts = {"stamps": [{"name": "door", "size": [1, 2], "tiles": [[4, 0, 0], [4, 1, 0]]},
                         {"name": "well", "size": [2, 2], "tiles": [[4, 2, 0], [4, 3, 0], [4, 2, 1], [4, 3, 1]]}]}
        layer = {"kind": "stamps", "cells": [[7, 0, 0], [1, 3, 1]]}
        self.assertEqual(ds.expand_stamps(ts, layer), [[7, 0, 4, 0, 0], [7, 1, 4, 1, 0],
                                                       [1, 3, 4, 2, 0], [2, 3, 4, 3, 0], [1, 4, 4, 2, 1], [2, 4, 4, 3, 1]])
        self.assertEqual(ds.expand_stamps(ts, layer), ref.expand_stamps(ts, layer))

    def test_golden_placed_cells_and_centres_match_expected_json(self):
        want = expected_maps()
        for a, ts in golden_maps():
            exp = want[f"map/{a['name']}"]
            shape = ts.get("shape", "square")
            for i, L in enumerate(a["layers"]):
                cells = ds.placed_cells(ts, L, i)
                self.assertEqual(len(cells), exp["layers"][L["name"]], (a["name"], L["name"]))
                placed = [c + ds.draw_corner(ts, shape, a["tile_size"], c) for c in cells]
                self.assertEqual(ds.compare(exp["placed"][L["name"]], placed, f"{a['name']}/{L['name']}"), [])
            centres = [[x, y] + [ds.round6(v) for v in ds.cell_centre(shape, x, y, a["tile_size"])]
                       for y in range(a["size"][1]) for x in range(a["size"][0])]
            self.assertEqual(ds.compare(exp["centres"], centres, a["name"]), [])

    def test_drawing_offset_puts_paper2d_tiles_where_the_spec_draws_them(self):
        # Paper2D draws a tile's top-left at the cell's top-left + (dx, dy + cell_h - tile_h); the spec at
        # centre - origin. A cell-sized tile needs no offset; the golden iso block (16x12, origin [8, 8]) on a 16x8
        # diamond happens to sit where Paper2D's bottom alignment puts it; an 8x16 tile with the default origin
        # (its centre) on an 8x8 cell is drawn 4 px lower than bottom-aligned
        self.assertEqual(ds.drawing_offset({"tile_size": [16, 8], "tiles": [{"col": 0, "row": 0}]}, [16, 8]),
                         ((0, 0), []))
        self.assertEqual(ds.drawing_offset({"tile_size": [16, 12], "tiles": [{"col": 0, "row": 0, "origin": [8, 8]}]},
                                           [16, 8]), ((0, 0), []))
        self.assertEqual(ds.drawing_offset({"tile_size": [8, 16], "tiles": [{"col": 0, "row": 0}]}, [8, 8]),
                         ((0, 4), []))
        offset, odd = ds.drawing_offset({"tile_size": [8, 8], "tiles": [{"col": 0, "row": 0},
                                                                         {"col": 1, "row": 0, "origin": [4, 8]}]}, [8, 8])
        self.assertEqual((offset, odd), ((0, 0), [[1, 0]]))            # the second tile wants (0, -4): reported


class FlipbookRate(unittest.TestCase):
    def test_every_golden_clip_gets_whole_frame_runs(self):
        doc = ds.load(MANIFEST)
        for a in doc["assets"]:
            for c in a.get("clips") or [] if a["kind"] == "animated_sprite" else []:
                durations = [f["duration"] for f in c["frames"]]
                rate, runs, exact = ds.flipbook_rate(c["fps"], durations)
                self.assertTrue(exact, (a["name"], c["name"]))
                for d, r in zip(durations, runs):
                    self.assertAlmostEqual(r / rate, d, delta=1e-6)

    def test_holds_of_one_and_a_half_double_the_rate(self):
        rate, runs, exact = ds.flipbook_rate(12, [1 / 12, 1.5 / 12, 1 / 12])
        self.assertEqual((rate, runs, exact), (24, [2, 3, 2], True))

    def test_durations_off_the_fps_fall_back_to_milliseconds(self):
        rate, runs, exact = ds.flipbook_rate(10, [0.1234567, 0.1])
        self.assertFalse(exact)
        self.assertEqual(rate, ds.FALLBACK_RATE)
        self.assertEqual(runs, [123, 100])


class Manifest(unittest.TestCase):
    def write(self, doc):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".assets.json", delete=False, encoding="utf-8")
        json.dump(doc, tmp)
        tmp.close()
        self.addCleanup(os.remove, tmp.name)
        return tmp.name

    def test_another_major_is_refused_naming_both(self):
        path = self.write({"format": "dotwork-assets", "version": "2.0.0", "assets": []})
        with self.assertRaises(ds.ManifestError) as ctx:
            ds.load(path)
        self.assertIn("2.0.0", str(ctx.exception))
        self.assertIn("1.x", str(ctx.exception))

    def test_a_newer_minor_loads(self):
        self.assertEqual(ds.load(self.write({"format": "dotwork-assets", "version": "1.4.0", "assets": []}))["version"],
                         "1.4.0")

    def test_unsafe_paths_are_refused(self):
        for bad in ("../x.png", "/x.png", "C:/x.png", "a\\b.png", ""):
            with self.assertRaises(ds.ManifestError, msg=bad):
                ds.resolve("/base", bad)
        self.assertTrue(ds.resolve("/base", "art/x.png").endswith(os.path.join("art", "x.png")))

    def test_unknown_kinds_are_skipped_and_core_kinds_ordered(self):
        core, extra, skipped = ds.ordered([{"kind": "map"}, {"kind": "hologram"}, {"kind": "sprite"},
                                           {"kind": "image"}, {"kind": "tileset"}, {"kind": "particles"}])
        self.assertEqual([a["kind"] for a in core], ["sprite", "tileset", "map"])
        self.assertEqual([a["kind"] for a in extra], ["image", "particles"])   # every extra kind is a texture
        self.assertEqual([a["kind"] for a in skipped], ["hologram"])
        self.assertEqual(set(ds.TEXTURE_KINDS), set(ref.KINDS) - set(ref.CORE_KINDS))

    def test_a_newer_layer_kind_is_known_to_the_importer(self):
        self.assertEqual(set(ds.LAYER_KINDS), set(ref.LAYER_KINDS))

    def test_compare_uses_the_tolerance_and_names_the_place(self):
        self.assertEqual(ds.compare({"a": [0.083333, 2]}, {"a": [1 / 12, 2]}), [])
        diffs = ds.compare({"a": [0.25], "b": True, "c": 1}, {"a": [0.125], "b": 1, "d": 0})
        self.assertEqual(len(diffs), 4, diffs)
        self.assertTrue(any(d.startswith("$.a[0]") for d in diffs))


class Fonts(unittest.TestCase):
    """#286: an offline Font draws a glyph's USize pixels at the pen and advances by USize + one Kerning."""

    def golden_font(self, name):
        doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
        return next(a for a in doc["assets"] if a["kind"] == "font" and a["name"] == name)

    def test_every_glyph_lands_and_advances_as_the_bmfont_says(self):
        for name in ("tiny", "duo"):
            font = self.golden_font(name)
            kerning, cells, sizes, clipped = ds.font_layout(font["chars"])
            self.assertEqual(clipped, [])
            for code, x, y, w, h, xoff, yoff, xadv, page in font["chars"]:
                pg, u, v, cw, ch, dx, sx, sy, sw = cells[code]
                self.assertEqual(cw + kerning, xadv, f"{name} {code}: Unreal's advance is the cell plus the Kerning")
                self.assertEqual((pg, dx, sx, sy, sw, ch), (page, xoff if h else 0, x, y, w, h), f"{name} {code}")
                if h:
                    self.assertLessEqual(dx + w, cw, f"{name} {code}: the ink fits its cell")
                    self.assertLessEqual(u + cw, sizes[pg][0])
                    self.assertLessEqual(v + ch, sizes[pg][1])

    def test_duo_glyph_65_is_on_page_1_one_pixel_right_of_the_pen(self):
        kerning, cells, sizes, _ = ds.font_layout(self.golden_font("duo")["chars"])
        self.assertEqual(len(sizes), 2)
        self.assertEqual(cells[65][0], 1)
        self.assertEqual(cells[65][5], 1)
        self.assertEqual(cells[65][3] + kerning, 5)

    def test_cells_on_one_page_never_overlap_and_wrap_at_the_row_width(self):
        chars = [[c, 0, 0, 5, 7, 1, 0, 8, 0] for c in range(33, 120)]
        _, cells, sizes, _ = ds.font_layout(chars, row_width=64)
        boxes = sorted((v[1], v[2], v[3], v[4]) for v in cells.values())
        for i, (u, v, w, h) in enumerate(boxes):
            for u2, v2, w2, h2 in boxes[i + 1:]:
                self.assertFalse(u < u2 + w2 and u2 < u + w and v < v2 + h2 and v2 < v + h, (u, v, u2, v2))
        self.assertLessEqual(sizes[0][0], 64)

    def test_a_negative_xoffset_is_clipped_to_the_pen_and_named(self):
        _, cells, _, clipped = ds.font_layout([[65, 0, 0, 4, 5, -1, 0, 4, 0]])
        self.assertEqual(clipped, [65])
        self.assertEqual(cells[65][5], 0)


class TileUserData(unittest.TestCase):
    def test_surface_and_animation_share_paper2ds_one_name(self):
        self.assertEqual(ds.tile_user_data({"surface": "dirt"}), "dirt")
        self.assertEqual(ds.tile_user_data({"anim": {"frames": 2, "fps": 4}}), "anim=2@4")
        self.assertEqual(ds.tile_user_data({"surface": "water", "anim": {"frames": 3, "fps": 7.5}}), "water;anim=3@7.5")
        self.assertEqual(ds.tile_user_data({"anim": {"frames": 1, "fps": 4}}), "")
        self.assertEqual(ds.parse_tile_user_data("water;anim=3@7.5"), ("water", 3, 7.5))
        self.assertEqual(ds.parse_tile_user_data("dirt"), ("dirt", 1, 0.0))
        self.assertEqual(ds.parse_tile_user_data("anim=x@y"), ("", 1, 0.0))

    def test_every_golden_water_tile_says_its_animation(self):
        doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
        ts = next(a for a in doc["assets"] if a["kind"] == "tileset" and a["name"] == "ground_yard")
        water = [t for at in ts["atlases"] for t in at["tiles"] if t.get("anim")]
        self.assertEqual(len(water), 47)
        self.assertTrue(all(ds.parse_tile_user_data(ds.tile_user_data(t))[1:] == (2, 4.0) for t in water))


class Png(unittest.TestCase):
    def test_golden_pngs_read_and_survive_a_write(self):
        for rel in ("art/ui/fonts/font_duo_1.png", "art/tiles/yard/overlay_water.png", "art/props/spr_crate.png"):
            img = dpng.read(str(GOLDEN / "assets" / rel))
            again = dpng.read_bytes(dpng.to_bytes(img))
            self.assertEqual((again.width, again.height, bytes(again.data)), (img.width, img.height, bytes(img.data)))
        page = dpng.read(str(GOLDEN / "assets" / "art" / "ui" / "fonts" / "font_duo_1.png"))
        self.assertEqual(page.pixel(2, 1)[3], 255, "glyph 65's top stroke")
        self.assertEqual(page.pixel(0, 0)[3], 0)

    def test_every_filter_type_decodes(self):
        import struct
        import zlib
        w, h, rows = 3, 5, []
        want = [[(x * 40 + y * 7) % 256 for x in range(w * 4)] for y in range(h)]
        prev = [0] * (w * 4)
        for f, line in enumerate(want):              # filters 0, 1, 2, 3, 4, one per row
            out = []
            for i, b in enumerate(line):
                a = line[i - 4] if i >= 4 else 0
                c = prev[i - 4] if i >= 4 else 0
                pred = [0, a, prev[i], (a + prev[i]) // 2, dpng._paeth(a, prev[i], c)][f]
                out.append((b - pred) % 256)
            rows.append(bytes([f] + out))
            prev = line

        def chunk(tag, data):
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        raw = (dpng.SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))
        img = dpng.read_bytes(raw)
        self.assertEqual(bytes(img.data), bytes(b for line in want for b in line))
        with self.assertRaises(dpng.PngError):
            dpng.read_bytes(b"not a png")

    def test_small_palettes_read_like_pillow(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        import io
        src = Image.new("RGBA", (5, 3), (0, 0, 0, 0))
        for x, y, c in ((0, 0, (255, 255, 255, 255)), (3, 1, (200, 40, 10, 255)), (4, 2, (255, 255, 255, 255))):
            src.putpixel((x, y), c)
        for mode, kw in (("P1", {"bits": 1}), ("P2", {"bits": 2})):
            buf = io.BytesIO()
            im = src.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=2 ** kw["bits"])
            im.save(buf, "PNG", **kw)
            got = dpng.read_bytes(buf.getvalue(), mode)
            want = Image.open(io.BytesIO(buf.getvalue())).convert("RGBA")
            for y in range(3):
                for x in range(5):
                    self.assertEqual(got.pixel(x, y)[:3], want.getpixel((x, y))[:3],
                                     f"{mode} {x},{y}")
            self.assertEqual((got.width, got.height), (5, 3))


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=1)
