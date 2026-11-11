#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_render_sprites_manifest.py
# Purpose : The exam for render_sprites.py's Dotwork asset manifest writer, without Blender: the pieces that build
#           the animated_sprite (clip per action and direction, sheet rects, per-frame durations, loop, pivot,
#           direction table), the merge into an existing manifest, the base folder and path rules, the option
#           checks, and the committed fixture data/golden/character/sprites/ (rendered from the golden character):
#           it passes assetspec.py's validator with its files, and its expected.json is assetspec's loaded result.
#           The renders themselves are checked by test_render_sprites.py (bpy, live).
# Usage   : python tools/blender/test_render_sprites_manifest.py [-v]
# Exit    : 0 all tests pass, 1 a test failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "art" / "dotwork"))
import assetspec  # noqa: E402
import render_sprites as rs  # noqa: E402

FIXTURE = HERE.parents[1] / "data" / "golden" / "character" / "sprites"
MANIFEST = FIXTURE / "dotwork" / "character.assets.json"


def rendered(action, dirs, frames, fps=12, loop=True, cell=32, sheet=None):
    """One rendered clip as run() hands it to build_asset."""
    return {"action": action, "loop": loop, "fps": fps, "sheet": sheet or f"art/hero/hero_{action}.png",
            "rows": [{"dir": d, "pivot": [cell / 2, cell * 0.8],
                      "files": [f"art/hero/hero_frames/{rs.clip_name(action, d)}_{i:02d}.png" for i in range(frames)]}
                     for d in dirs]}


def parse_error(argv):
    """render_sprites' argument parser on argv: (exit code, stderr)."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        try:
            rs.parse_args(argv)
            return 0, ""
        except SystemExit as exc:
            return exc.code, err.getvalue()


class BuildAsset(unittest.TestCase):
    def test_eight_directions_make_a_clip_each_and_the_table(self):
        a = rs.build_asset("hero", [rendered("walk", rs.COMPASS[8], 6)], 32)
        self.assertEqual([c["name"] for c in a["clips"]],
                         ["walk_s", "walk_sw", "walk_w", "walk_nw", "walk_n", "walk_ne", "walk_e", "walk_se"])
        self.assertEqual(a["directions"]["walk"]["nw"], "walk_nw")
        self.assertEqual(set(a["directions"]["walk"]), set(assetspec.DIRECTIONS))

    def test_rect_is_column_by_frame_and_row_by_direction(self):
        a = rs.build_asset("hero", [rendered("walk", rs.COMPASS[4], 3, cell=40)], 40)
        west = a["clips"][1]
        self.assertEqual(west["name"], "walk_w")
        self.assertEqual([f["rect"] for f in west["frames"]], [[0, 40, 40, 40], [40, 40, 40, 40], [80, 40, 40, 40]])
        self.assertEqual(west["frame_size"], [40, 40])

    def test_durations_follow_fps_and_sum_to_length(self):
        a = rs.build_asset("hero", [rendered("idle", ("s",), 5, fps=6)], 32)
        c = a["clips"][0]
        self.assertEqual([f["duration"] for f in c["frames"]], [1 / 6] * 5)
        self.assertAlmostEqual(c["length"], 5 / 6)
        self.assertNotIn("holds", c)

    def test_loop_and_once(self):
        a = rs.build_asset("hero", [rendered("walk", ("s",), 2), rendered("die", ("s",), 2, loop=False)], 32)
        self.assertEqual([c["loop"] for c in a["clips"]], [True, False])

    def test_one_direction_names_the_clip_after_the_action_and_has_no_table(self):
        a = rs.build_asset("crate", [rendered("open", rs.COMPASS[1], 2)], 32)
        self.assertEqual(a["clips"][0]["name"], "open")
        self.assertNotIn("directions", a)

    def test_the_asset_passes_the_schema_and_semantic_checks(self):
        a = rs.build_asset("hero", [rendered("walk", rs.COMPASS[8], 4), rendered("idle", rs.COMPASS[8], 2)], 32)
        doc = rs.merge_manifest(None, a, "rendered", "..")
        self.assertEqual(assetspec.check(doc), [])
        self.assertEqual(doc["generator"], "render_sprites")
        self.assertEqual(doc["version"].split(".")[0], assetspec.VERSION.split(".")[0])


class Merge(unittest.TestCase):
    def test_replaces_the_asset_of_that_name_and_keeps_the_others(self):
        first = rs.merge_manifest(None, rs.build_asset("hero", [rendered("walk", ("s",), 2)], 32), "p", "..")
        second = rs.merge_manifest(first, rs.build_asset("guard", [rendered("walk", ("s",), 2)], 32), "p", "..")
        third = rs.merge_manifest(second, rs.build_asset("hero", [rendered("run", ("s",), 2)], 32), "p", "..")
        self.assertEqual([a["name"] for a in third["assets"]], ["guard", "hero"])
        self.assertEqual(third["assets"][1]["clips"][0]["name"], "run_s")
        self.assertEqual(assetspec.check(third), [])

    def test_refuses_a_manifest_another_tool_wrote(self):
        dotwork = {"format": "dotwork-assets", "version": "1.0.0", "pack": "town", "generator": "dotwork",
                   "base": "..", "assets": []}
        with self.assertRaisesRegex(ValueError, "dotwork"):
            rs.merge_manifest(dotwork, rs.build_asset("hero", [rendered("walk", ("s",), 2)], 32), "town", "..")

    def test_refuses_another_base(self):
        doc = rs.merge_manifest(None, rs.build_asset("hero", [rendered("walk", ("s",), 2)], 32), "p", ".")
        with self.assertRaisesRegex(ValueError, "base"):
            rs.merge_manifest(doc, rs.build_asset("x", [rendered("walk", ("s",), 2)], 32), "p", "..")


class Paths(unittest.TestCase):
    def test_base_is_the_assets_folder_above_dotwork(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, base = rs.manifest_base(Path(tmp) / "assets" / "dotwork" / "x.assets.json")
            self.assertEqual((folder, base), (Path(tmp) / "assets", ".."))
            folder, base = rs.manifest_base(Path(tmp) / "packs" / "x.assets.json")
            self.assertEqual((folder, base), (Path(tmp) / "packs", "."))

    def test_rel_to_uses_forward_slashes_and_refuses_outside(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "assets"
            self.assertEqual(rs.rel_to(base / "art" / "hero" / "a.png", base), "art/hero/a.png")
            self.assertIsNone(rs.rel_to(Path(tmp) / "elsewhere" / "a.png", base))

    def test_relative_paths_work_from_the_current_folder(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                folder, base = rs.manifest_base(Path("assets/dotwork/x.assets.json"))
                self.assertEqual(rs.rel_to(Path("assets/art/h/s.png"), folder), "art/h/s.png")
            finally:
                os.chdir(cwd)


class Options(unittest.TestCase):
    def test_manifest_needs_an_action(self):
        code, err = parse_error(["m.glb", "--out", "s.png", "--manifest", "a/dotwork/p.assets.json"])
        self.assertEqual(code, 2)
        self.assertIn("--action", err)

    def test_manifest_needs_dotwork_direction_counts(self):
        code, err = parse_error(["m.glb", "--out", "s.png", "--actions", "all", "--directions", "16",
                                 "--manifest", "a/dotwork/p.assets.json"])
        self.assertEqual(code, 2)
        self.assertIn("1, 4 or 8", err)

    def test_manifest_file_name(self):
        code, err = parse_error(["m.glb", "--out", "s.png", "--action", "walk", "--manifest", "p.json"])
        self.assertEqual(code, 2)
        self.assertIn(".assets.json", err)

    def test_action_and_actions_exclude_each_other_and_frames(self):
        self.assertEqual(parse_error(["m.glb", "--out", "s.png", "--action", "a", "--actions", "b"])[0], 2)
        self.assertEqual(parse_error(["m.glb", "--out", "s.png", "--actions", "all", "--frames", "1:4"])[0], 2)
        self.assertEqual(parse_error(["m.glb", "--out", "s.png", "--step", "0"])[0], 2)
        self.assertEqual(parse_error(["m.glb", "--out", "s.png", "--action", "a", "--name", "bad name"])[0], 2)

    def test_a_good_line_parses(self):
        self.assertEqual(parse_error(["m.glb", "--out", "s.png", "--actions", "idle,walk", "--step", "2",
                                      "--manifest", "assets/dotwork/r.assets.json", "--once", "die"])[0], 0)


class Api(unittest.TestCase):
    def test_functions_other_tools_import_are_still_there(self):
        # bozzetto/turntable.py frames its contact sheet with import_asset and scene_bounds (a refactor once dropped
        # scene_bounds and the turntable step failed while this exam passed)
        for name in ("import_asset", "scene_bounds", "setup_scene", "place_camera", "stitch"):
            self.assertTrue(callable(getattr(rs, name, None)), name)
        used = (HERE.parent / "bozzetto" / "turntable.py").read_text(encoding="utf-8")
        for name in ("import_asset", "scene_bounds"):
            self.assertIn("rs." + name, used, "turntable.py no longer uses " + name + ": update this list")


class CommittedFixture(unittest.TestCase):
    """data/golden/character/sprites/: render_sprites.py --manifest on the golden character (README there)."""

    def test_validates_with_its_files(self):
        doc = assetspec.load(str(MANIFEST))
        self.assertEqual(assetspec.check(doc, assetspec.base_dir(str(MANIFEST), doc)), [])
        self.assertEqual(doc["generator"], "render_sprites")

    def test_expected_json_is_the_loaded_result(self):
        doc = assetspec.load(str(MANIFEST))
        want = json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))
        self.assertEqual(assetspec.expected(doc), want)

    def test_every_direction_of_every_clip(self):
        doc = assetspec.load(str(MANIFEST))
        sprite = next(a for a in doc["assets"] if a["kind"] == "animated_sprite")
        for action, dirs in sprite["directions"].items():
            self.assertEqual(sorted(dirs), sorted(rs.COMPASS[4]), action)
        self.assertTrue(all(c["loop"] for c in sprite["clips"]))


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    unittest.main()
