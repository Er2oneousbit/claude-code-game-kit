#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_pixel_sprite.py
# Purpose : Exam for pixel_sprite.py, standard library only: the example hero builds into the right atlas and JSON,
#           right-facing rows are exact mirrors of left-facing ones, every frame passes the first-art floor, and the
#           floor rejects what it exists to reject (a dot, a flat circle, a one-color box). Also the PNG round trip,
#           the refusal to overwrite, a bad color, and the example command.
# Usage   : python tools/art/test_pixel_sprite.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pixel_sprite as ps  # noqa: E402

HERE = Path(__file__).resolve().parent
EXAMPLE = HERE / "sprites" / "example_hero.py"

# Sprite files that must FAIL the floor: the "first build was dots" failure, a flat circle, a one-color box.
DOT = '''
from pixel_sprite import Sprite
PALETTE = {"orange": (230, 150, 40), "light": (250, 220, 150)}
ROWS = [("idle", "down")]
FRAMES = 1
def draw(pose, direction, frame):
    s = Sprite(PALETTE)
    s.rect(13, 13, 18, 18, "orange"); s.rect(17, 14, 18, 15, "light")
    return s
'''
CIRCLE = '''
from pixel_sprite import Sprite
PALETTE = {"red": (150, 50, 40)}
ROWS = [("idle", "down")]
FRAMES = 1
def draw(pose, direction, frame):
    s = Sprite(PALETTE)
    for y in range(32):
        for x in range(32):
            if (x - 16) ** 2 + (y - 16) ** 2 <= 100:
                s.dot(x, y, "red")
    return s
'''
BOX = '''
from pixel_sprite import Sprite
PALETTE = {"grey": (128, 128, 128)}
ROWS = [("idle", "down")]
FRAMES = 1
def draw(pose, direction, frame):
    s = Sprite(PALETTE)
    s.rect(8, 4, 23, 28, "grey")
    return s
'''
BAD_COLOR = '''
from pixel_sprite import Sprite
PALETTE = {"grey": (128, 128, 128)}
ROWS = [("idle", "down")]
FRAMES = 1
def draw(pose, direction, frame):
    s = Sprite(PALETTE)
    s.rect(8, 4, 23, 28, "gray")
    return s
'''


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ps.main(list(argv))
    return code, out.getvalue() + err.getvalue()


class PixelSpriteExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def sprite_file(self, name, text):
        p = self.dir / f"{name}.py"
        p.write_text(text, encoding="utf-8")
        return p

    def test_example_builds_atlas_json_and_preview(self):
        code, out = run("build", str(EXAMPLE), "--out", str(self.dir / "hero"))
        self.assertEqual(code, 0, out)
        grid = ps.read_png(self.dir / "hero.png")
        self.assertEqual((len(grid[0]), len(grid)), (128, 256))
        layout = json.loads((self.dir / "hero.json").read_text(encoding="utf-8"))
        self.assertEqual((layout["cell"], layout["columns"], len(layout["rows"])), (32, 4, 8))
        self.assertEqual(layout["rows"][5], {"index": 5, "pose": "punch", "direction": "left", "frames": 4, "first_frame": 20})
        self.assertEqual(layout["image"], "hero.png")
        self.assertTrue((self.dir / "hero_preview.png").is_file())

    def test_right_rows_mirror_left_rows(self):
        mod = ps.load_sprite_file(EXAMPLE)
        for pose in ("walk", "punch"):
            for f in range(4):
                left = ps.draw_frame(mod, pose, "left", f)
                right = ps.draw_frame(mod, pose, "right", f)
                self.assertEqual(right, ps.mirror(left), f"{pose} frame {f}")

    def test_example_meets_the_floor(self):
        mod = ps.load_sprite_file(EXAMPLE)
        atlas, layout = ps.build_atlas(mod)
        results = ps.check_atlas(atlas, layout["cell"])
        self.assertEqual(len(results), 32)
        self.assertEqual([r for r in results if r[1]["problems"]], [])

    def test_floor_rejects_dot_circle_and_box(self):
        for name, text, expect in (("dot", DOT, "tall"), ("circle", CIRCLE, "colors"), ("box", BOX, "colors")):
            code, out = run("build", str(self.sprite_file(name, text)), "--out", str(self.dir / name), "--preview-scale", "0")
            self.assertEqual(code, 1, f"{name}: {out}")
            self.assertIn(expect, out, name)
            self.assertIn("below the first-art floor", out)

    def test_check_command_reads_the_json_cell(self):
        run("build", str(EXAMPLE), "--out", str(self.dir / "hero"))
        code, out = run("check", str(self.dir / "hero.png"))
        self.assertEqual(code, 0, out)
        self.assertIn("32 frame(s) meet the first-art floor", out)

    def test_png_round_trip(self):
        grid = [[(x * 8, y * 8, 100, 255 if (x + y) % 3 else 0) for x in range(16)] for y in range(8)]
        p = self.dir / "rt.png"
        ps.write_png(p, grid, overwrite=False)
        self.assertEqual(ps.read_png(p), grid)

    def test_refuses_to_overwrite(self):
        run("build", str(EXAMPLE), "--out", str(self.dir / "hero"), "--preview-scale", "0")
        code, out = run("build", str(EXAMPLE), "--out", str(self.dir / "hero"), "--preview-scale", "0")
        self.assertEqual(code, 2)
        self.assertIn("--overwrite", out)
        code, out = run("build", str(EXAMPLE), "--out", str(self.dir / "hero"), "--preview-scale", "0", "--overwrite")
        self.assertEqual(code, 0, out)

    def test_bad_color_and_missing_file_are_usage_errors(self):
        code, out = run("build", str(self.sprite_file("bad", BAD_COLOR)), "--out", str(self.dir / "bad"))
        self.assertEqual(code, 2)
        self.assertIn("'gray' is not in PALETTE", out)
        code, out = run("build", str(self.dir / "nope.py"), "--out", str(self.dir / "x"))
        self.assertEqual(code, 2)
        self.assertIn("not found", out)

    # ---- regressions from an adversarial review (Fable, 2026-10-26) ---------------------------------------------
    def png_with(self, name, ihdr, idat=b"", plte=None):
        def chunk(tag, data):
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        body = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + (chunk(b"PLTE", plte) if plte else b"")
        p = self.dir / name
        p.write_bytes(body + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
        return p

    def test_malformed_pngs_are_usage_errors_not_crashes(self):
        ok_raw = zlib.compress(b"\x00" + b"\x00\x00\x00\xff" * 2)
        cases = {
            "zero.png": (struct.pack(">IIBBBBB", 0, 0, 8, 6, 0, 0, 0), ok_raw),
            "huge.png": (struct.pack(">IIBBBBB", 20000, 20000, 8, 6, 0, 0, 0), zlib.compress(b"\x00" * 1000)),
            "short.png": (struct.pack(">IIBBBBB", 2, 4, 8, 6, 0, 0, 0), ok_raw),
            "nopalette.png": (struct.pack(">IIBBBBB", 2, 1, 8, 3, 0, 0, 0), zlib.compress(b"\x00\x00\x00")),
            "badzlib.png": (struct.pack(">IIBBBBB", 2, 1, 8, 6, 0, 0, 0), b"not zlib at all"),
        }
        for name, (ihdr, idat) in cases.items():
            code, out = run("check", str(self.png_with(name, ihdr, idat)))
            self.assertEqual(code, 2, f"{name}: {out}")
            self.assertIn("[error]", out, name)
        (self.dir / "cut.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR\x00\x00")
        code, out = run("check", str(self.dir / "cut.png"))
        self.assertEqual(code, 2, out)

    def test_a_dark_figure_with_an_outline_can_pass(self):
        dark = self.sprite_file("wraith", '''
from pixel_sprite import Sprite
PALETTE = {"a": (40, 30, 60), "b": (55, 45, 80), "c": (70, 60, 100), "d": (30, 20, 45), "eye": (200, 40, 40)}
ROWS = [("idle", "down")]
FRAMES = 1
def draw(pose, direction, frame):
    s = Sprite(PALETTE)
    s.rect(11, 4, 20, 27, "a"); s.rect(12, 6, 19, 12, "b"); s.rect(13, 14, 18, 26, "c"); s.rect(8, 14, 10, 24, "d")
    s.rect(21, 14, 23, 24, "d"); s.rect(13, 8, 14, 9, "eye"); s.rect(17, 8, 18, 9, "eye")
    return s
''')
        code, out = run("build", str(dark), "--out", str(self.dir / "wraith"), "--preview-scale", "0")
        self.assertEqual(code, 0, out)

    def test_a_leftover_preview_stops_the_build_before_writing_anything(self):
        (self.dir / "hero_preview.png").write_bytes(b"old")
        code, out = run("build", str(EXAMPLE), "--out", str(self.dir / "hero"))
        self.assertEqual(code, 2, out)
        self.assertFalse((self.dir / "hero.png").exists())
        self.assertFalse((self.dir / "hero.json").exists())

    def test_example_command_copies_the_hero(self):
        code, out = run("example", "--out", str(self.dir / "sprites"))
        self.assertEqual(code, 0, out)
        self.assertEqual((self.dir / "sprites" / "example_hero.py").read_bytes(), EXAMPLE.read_bytes())

    def test_building_the_unchanged_hero_warns(self):
        code, out = run("example", "--out", str(self.dir / "sprites"))
        code, out = run("build", str(self.dir / "sprites" / "example_hero.py"), "--out", str(self.dir / "h"), "--preview-scale", "0")
        self.assertEqual(code, 0, out)
        self.assertIn("[WARN] this is the kit's reference hero", out)
        edited = (self.dir / "sprites" / "example_hero.py").read_text(encoding="utf-8").replace('"scarf": (184, 51, 47)', '"scarf": (40, 160, 80)')
        mine = self.sprite_file("my_hero", edited)
        code, out = run("build", str(mine), "--out", str(self.dir / "m"), "--preview-scale", "0")
        self.assertNotIn("[WARN]", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
