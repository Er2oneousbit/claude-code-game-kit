#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_unreal_dotwork.py
# Purpose : Exam for the plain-Python half of the Unreal Dotwork importer
#           (engines/unreal/skeleton/Content/Python/kit_dotwork/dotwork_spec.py), without Unreal: its port of the
#           blob rule matches tools/art/dotwork/assetspec.py on every neighbourhood, its terrain resolution matches the
#           reference loader on the golden pack, every golden clip gets a flipbook rate with whole frame runs, and the
#           version check, path check and comparison behave.
# Usage   : python scripts/test_unreal_dotwork.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only. The Paper2D half (assets built and read back) runs in the editor:
#           `python tools/dev.py test` in a scaffolded Unreal project (#58).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
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


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ds = load(SPEC_PY, "dotwork_spec")
ref = load(ASSETSPEC_PY, "assetspec")


class BlobRule(unittest.TestCase):
    def test_every_neighbourhood_matches_the_reference(self):
        for mode in ("blob47", "sides4"):
            for raw in range(256):
                painted = {(1 + dx, 1 + dy) for b, (dx, dy) in enumerate(ds.NB8) if raw >> b & 1} | {(1, 1)}
                self.assertEqual(ds.cell_mask(painted, 1, 1, mode), ref.cell_mask(painted, 1, 1, mode), (mode, raw))

    def test_golden_terrain_layers_resolve_like_the_reference(self):
        doc = ds.load(MANIFEST)
        tilesets = {a["name"]: a for a in doc["assets"] if a["kind"] == "tileset"}
        n = 0
        for a in doc["assets"]:
            if a["kind"] != "map":
                continue
            for L in a["layers"]:
                if L["kind"] == "terrain":
                    ts = tilesets[a["tileset"]]
                    self.assertEqual(ds.resolve_terrain(ts, L), ref.resolve_terrain(ts, L), L["name"])
                    n += 1
        self.assertGreater(n, 0)

    def test_paper2d_layer_zero_is_the_top_layer(self):
        self.assertEqual([ds.paper_layer_index(i, 5) for i in range(5)], [4, 3, 2, 1, 0])


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
        self.assertEqual([a["kind"] for a in extra], ["image"])
        self.assertEqual([a["kind"] for a in skipped], ["hologram", "particles"])

    def test_compare_uses_the_tolerance_and_names_the_place(self):
        self.assertEqual(ds.compare({"a": [0.083333, 2]}, {"a": [1 / 12, 2]}), [])
        diffs = ds.compare({"a": [0.25], "b": True, "c": 1}, {"a": [0.125], "b": 1, "d": 0})
        self.assertEqual(len(diffs), 4, diffs)
        self.assertTrue(any(d.startswith("$.a[0]") for d in diffs))


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=1)
