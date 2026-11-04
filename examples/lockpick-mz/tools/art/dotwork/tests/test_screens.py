#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_screens.py
# Purpose : offline exam for the screens lane (title, loading, credits scenes) and the capture command (Movie Maker
#           command line, frame collection, first / last difference, GIF and strip), with no Godot or ComfyUI.
# Usage   : python tools/art/dotwork/tests/test_screens.py   (test_dotwork.py runs it too)
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DOTWORK = os.path.dirname(HERE)
sys.path.insert(0, DOTWORK)
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class ScreensExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_screens_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pack(self, entries, theme=False):
        import test_dotwork as td
        import dotwork
        td.make_project(self.tmp)
        with open(os.path.join(self.tmp, "project.godot"), "a", encoding="utf-8") as f:
            f.write("\n[display]\n\nwindow/size/viewport_width=480\nwindow/size/viewport_height=270\n")
        os.makedirs(os.path.join(self.tmp, "assets_src"), exist_ok=True)
        Image.new("RGB", (240, 135), (40, 60, 90)).save(os.path.join(self.tmp, "assets_src", "bd.png"))
        if theme:
            os.makedirs(os.path.join(self.tmp, "assets", "ui"), exist_ok=True)
            with open(os.path.join(self.tmp, "assets", "ui", "theme_menu.tres"), "w", encoding="utf-8") as f:
                f.write('[gd_resource type="Theme" format=3]\n\n[resource]\n')
        spec = os.path.join(self.tmp, "s.json")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"name": "screens", "screens": entries}, f)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = dotwork.main(["pack", "--spec", spec, "--project", self.tmp, "--no-verify"])
        return code, out.getvalue()

    def scene(self, name):
        return read(os.path.join(self.tmp, "assets", "art", "screens", name, f"screen_{name}.tscn"))

    def test_title_screen(self):
        code, out = self.pack([{"name": "title", "kind": "title", "backdrop": "assets_src/bd.png", "title": "Iron Oven",
                                "menu": ["Start", "Options", "Quit"]}], theme=True)
        self.assertEqual(code, 0, out)
        t = self.scene("title")
        self.assertIn('[node name="Backdrop" type="TextureRect" parent="."]', t)
        self.assertIn('path="res://assets_src/bd.png"', t)
        self.assertEqual(re.findall(r'type="Button" parent="Menu"\]\ntext = "([^"]+)"', t), ["Start", "Options", "Quit"])
        self.assertIn('path="res://assets/ui/theme_menu.tres"', t)              # the UI kit theme is used
        n_ext = len(re.findall(r"^\[ext_resource", t, re.M))
        self.assertIn(f"[gd_scene load_steps={n_ext + 1} format=3]", t)
        with Image.open(os.path.join(self.tmp, "assets", "art", "screens", "title", "logo_title.png")) as logo:
            self.assertLessEqual(logo.width, 480 * 0.7)                          # fits 70 % of the viewport
            self.assertGreater(logo.width, 480 * 0.35)

    def test_loading_screen_spinner(self):
        code, out = self.pack([{"name": "loading", "kind": "loading", "backdrop": "assets_src/bd.png",
                                "text": "Wird geladen", "style": "iron"}])
        self.assertEqual(code, 0, out)
        t = self.scene("loading")
        for want in ('type="AnimatedSprite2D"', 'autoplay = "spin"', 'type="TextureProgressBar"', 'text = "Wird geladen"',
                     "nine_patch_stretch = true"):
            self.assertIn(want, t)
        import lane_screens
        frames = lane_screens.spinner(((10, 10, 10), (100, 100, 100), (250, 250, 250)))
        self.assertEqual(len(frames), lane_screens.SPIN_FRAMES)
        angles = []
        for a in frames:   # exactly one lit dot, moving one step (45 degrees) clockwise per frame
            lit = np.argwhere(a[..., 0] == 250)
            self.assertEqual(len(lit), 4)                                         # one 2x2 dot
            cy, cx = lit.mean(0) - 7.5
            angles.append(math.degrees(math.atan2(cy, cx)) % 360)
        steps = [(angles[i + 1] - angles[i]) % 360 for i in range(len(angles) - 1)]
        for st in steps:                                                         # dots snap to whole pixels
            self.assertAlmostEqual(st, 45, delta=8)
        self.assertAlmostEqual(sum(steps), 45 * (len(frames) - 1), delta=1)
        with Image.open(os.path.join(self.tmp, "assets", "art", "screens", "loading", "ui_progress_loading_fill.png")) as f:
            self.assertEqual(f.size, (240, 16))

    def test_credits_roll(self):
        lines = ["# Iron Oven", "", "## Code", "A. Baker", "| Art | Made with Dotwork |", "|---|---|", "[Site](http://x)"]
        code, out = self.pack([{"name": "credits", "kind": "credits", "backdrop": "assets_src/bd.png", "lines": lines,
                                "seconds": 12}])
        self.assertEqual(code, 0, out)
        t = self.scene("credits")
        texts = re.findall(r'type="Label" parent="Roll"\][^\[]*?text = "([^"]*)"', t)
        self.assertEqual(texts, ["Iron Oven", "", "Code", "A. Baker", "Art  Made with Dotwork", "Site"])
        self.assertEqual(t.count('theme_type_variation = &"HeaderSmall"'), 2)       # the two headings
        self.assertIn('"values": [270.0, %s.0]' % -(6 * 24 + 40), t)              # from below the screen to past the top
        self.assertIn('"times": PackedFloat32Array(0, 12.0)', t)
        self.assertIn('autoplay = &"roll"', t)

    def test_screen_errors(self):
        code, out = self.pack([{"name": "x", "kind": "intro", "backdrop": "assets_src/bd.png"}])
        self.assertEqual(code, 2)
        self.assertIn("kind", out)
        code, out = self.pack([{"name": "credits", "kind": "credits", "backdrop": "assets_src/bd.png"}])
        self.assertEqual(code, 2)
        self.assertIn('"lines" or "file"', out)

    def test_backdrop_godot_ignores_is_refused(self):
        # Kit Godot games ship assets_src/.gdignore (#29): a scene linking a file in there opens with a missing resource
        os.makedirs(os.path.join(self.tmp, "assets_src"), exist_ok=True)
        open(os.path.join(self.tmp, "assets_src", ".gdignore"), "w").close()
        code, out = self.pack([{"name": "title", "kind": "title", "backdrop": "assets_src/bd.png", "title": "Iron Oven"}])
        self.assertEqual(code, 2, out)
        self.assertIn("'assets_src/bd.png' is in assets_src/, which Godot does not import", out)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "assets", "art", "screens", "title", "screen_title.tscn")))


class CaptureExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_capture_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_movie_maker_command(self):
        import capture
        cmd = capture.build_cmd("godot", "/g", "res://a.tscn", "/g/out", 90, 30, (640, 360))
        self.assertEqual(cmd[:3], ["godot", "--path", "/g"])
        i = cmd.index("--write-movie")
        self.assertTrue(cmd[i + 1].endswith("frame.png"))                       # .png = a numbered PNG sequence
        self.assertEqual(cmd[cmd.index("--fixed-fps") + 1], "30")
        self.assertEqual(cmd[cmd.index("--quit-after") + 1], "90")
        self.assertEqual(cmd[cmd.index("--resolution") + 1], "640x360")
        self.assertEqual(cmd[-1], "res://a.tscn")
        self.assertNotIn("--headless", cmd)                                     # Movie Maker needs a renderer
        self.assertEqual(capture.parse_size("320x180"), (320, 180))
        import fcore
        with self.assertRaises(fcore.ToolError):
            capture.parse_size("big")

    def test_frames_difference_gif_and_strip(self):
        import capture
        for i in range(5):
            a = np.zeros((18, 32, 3), np.uint8)
            a[4:8, i * 4:i * 4 + 4] = 255
            Image.fromarray(a).save(os.path.join(self.tmp, f"frame{i:08d}.png"))
        Image.new("RGB", (4, 4)).save(os.path.join(self.tmp, "frame_strip_old.png"))   # not a numbered frame
        got = capture.collect(self.tmp)
        self.assertEqual([os.path.basename(f) for f in got], [f"frame{i:08d}.png" for i in range(5)])
        self.assertEqual(capture.differ(got[0], got[-1]), 32)                     # two 4x4 squares changed
        self.assertEqual(capture.differ(got[1], got[1]), 0)
        g = capture.gif(got, os.path.join(self.tmp, "c.gif"), 10)
        with Image.open(g) as im:
            self.assertEqual(im.n_frames, 5)
        with Image.open(capture.strip(got, os.path.join(self.tmp, "s.png"), n=3, height=36)) as s:
            self.assertEqual(s.size, (3 * (64 + 4) + 4, 44))


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)
