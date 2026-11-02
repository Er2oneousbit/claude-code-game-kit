#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_diorama.py
# Purpose : offline exam for the diorama lane (lane_diorama.py, 2.5D): tile cut-outs (a cell, the first solid cell
#           of a blob atlas), the scene layout (one quad per map cell, a block per raised cell, billboards standing on
#           the right height with pixel_size 1 / tile_px), the camera pose, and spec errors.
# Usage   : python tools/art/dotwork/tests/test_diorama.py   (test_dotwork.py runs it too)
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


class DioramaExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_diorama_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tile_cells(self):
        import lane_diorama
        import fcore
        a = np.zeros((16, 24, 4), np.uint8)          # 3 x 2 cells of 8 px; only cell (2, 1) is fully opaque
        a[0:8, 0:8] = (10, 200, 10, 255)
        a[0, 0, 3] = 0
        a[8:16, 16:24] = (200, 120, 40, 255)
        a[0:8, 8:16] = (1, 2, 3, 255)
        a[3, 12, 3] = 128
        im = Image.fromarray(a)
        c, at = lane_diorama.cell(im, 8, "solid")
        self.assertEqual(at, [2, 1])
        self.assertTrue((c == a[8:16, 16:24]).all())
        c, at = lane_diorama.cell(im, 8, [1, 0])
        self.assertTrue((c == a[0:8, 8:16]).all())
        with self.assertRaises(fcore.ToolError):
            lane_diorama.cell(im, 8, [3, 0])

    def test_camera_pose(self):
        import lane_diorama
        pos, rot = lane_diorama.camera_pose(4.0, 3.0, 30.0, 10.0)
        self.assertAlmostEqual(pos[1], 5.0)
        self.assertAlmostEqual(pos[2], 3.0 + 10 * math.cos(math.radians(30)))
        self.assertEqual(rot, (-30.0, 0.0, 0.0))
        # pitched down by -30 about X, the camera's forward (0, 0, -1) points at the map centre
        a = math.radians(rot[0])
        fwd = (0.0, math.sin(a), -math.cos(a))                                     # R_x(a) applied to (0, 0, -1)
        to_c = (4.0 - pos[0], 0 - pos[1], 3.0 - pos[2])
        n = math.sqrt(sum(v * v for v in to_c))
        self.assertAlmostEqual(fwd[1], to_c[1] / n, places=6)
        self.assertAlmostEqual(fwd[2], to_c[2] / n, places=6)

    def pack(self, entry):
        import test_dotwork as td
        import dotwork
        td.make_project(self.tmp)
        d = os.path.join(self.tmp, "assets_src")
        os.makedirs(d, exist_ok=True)
        Image.fromarray(np.full((8, 16, 4), (60, 160, 60, 255), np.uint8)).save(os.path.join(d, "grass.png"))
        Image.fromarray(np.full((8, 8, 4), (130, 130, 140, 255), np.uint8)).save(os.path.join(d, "wall.png"))
        Image.fromarray(np.full((12, 6, 4), (150, 90, 40, 255), np.uint8)).save(os.path.join(d, "post.png"))
        frames = os.path.join(self.tmp, "assets", "art", "c")
        os.makedirs(frames, exist_ok=True)
        Image.fromarray(np.full((20, 10, 4), (220, 220, 220, 255), np.uint8)).save(os.path.join(frames, "f0.png"))
        with open(os.path.join(frames, "c_frames.tres"), "w", encoding="utf-8") as f:
            f.write('[gd_resource type="SpriteFrames" load_steps=2 format=3]\n\n'
                    '[ext_resource type="Texture2D" path="res://assets/art/c/f0.png" id="1_idle"]\n\n[resource]\n')
        spec = os.path.join(self.tmp, "d.json")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"name": "d", "diorama": [entry]}, f)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = dotwork.main(["pack", "--spec", spec, "--project", self.tmp, "--no-verify"])
        return code, out.getvalue()

    def test_scene_layout(self):
        entry = {"name": "yard", "tile_px": 8,
                 "legend": {"g": {"top": "assets_src/grass.png", "tile": [1, 0]},
                            "w": {"top": "assets_src/grass.png", "side": "assets_src/wall.png", "height": 2}},
                 "rows": ["gwg", "g g"],
                 "sprites": [{"source": "assets_src/post.png", "at": [1, 0]},
                             {"frames": "assets/art/c/c_frames.tres", "animation": "walk_s", "at": [0, 1]}],
                 "camera": {"tilt": 45, "fov": 25, "distance": 6, "dof": False}}
        code, out = self.pack(entry)
        self.assertEqual(code, 0, out)
        t = read(os.path.join(self.tmp, "assets", "art", "diorama", "yard", "diorama_yard.tscn"))
        self.assertEqual(len(re.findall(r'type="MeshInstance3D" parent="Tiles"', t)), 5 + 1)   # 5 cells (a gap) + 1 block
        self.assertIn('[node name="B1_0" type="MeshInstance3D" parent="Tiles"]\nposition = Vector3(1.5, 1, 0.5)', t)
        self.assertIn("size = Vector3(1, 2, 1)", t)                                  # the raised block
        self.assertIn('[node name="T1_0" type="MeshInstance3D" parent="Tiles"]\nposition = Vector3(1.5, 2.001, 0.5)', t)
        post = re.search(r'\[node name="S0" type="Sprite3D" parent="Sprites"\]\n(.*?)(\n\n|\Z)', t, re.S).group(1)
        self.assertIn("position = Vector3(1.5, 2, 0.5)", post)                     # stands on top of the block
        self.assertIn("offset = Vector2(0, 6)", post)                              # bottom at the origin (12 px / 2)
        self.assertIn("pixel_size = 0.125", post)                                  # 1 / tile_px
        self.assertIn("billboard = 2", post)                                       # turns around its vertical axis
        self.assertIn("texture_filter = 0", post)
        self.assertIn('type="AnimatedSprite3D" parent="Sprites"', t)
        self.assertIn('animation = &"walk_s"', t)
        self.assertIn("offset = Vector2(0, 10)", t)                                # the frame is 20 px tall
        self.assertNotIn("CameraAttributesPractical", t)                           # dof off
        n_ext = len(re.findall(r"^\[ext_resource", t, re.M))
        n_sub = len(re.findall(r"^\[sub_resource", t, re.M))
        self.assertIn(f"[gd_scene load_steps={n_ext + n_sub + 1} format=3]", t)
        top = np.array(Image.open(os.path.join(self.tmp, "assets", "art", "diorama", "yard", "tile_g_top.png")))
        self.assertEqual(top.shape, (8, 8, 4))

    def test_errors(self):
        code, out = self.pack({"name": "x", "tile_px": 8, "legend": {"g": {"top": "assets_src/grass.png"}}, "rows": ["gq"]})
        self.assertEqual(code, 2)
        self.assertIn("q", out)
        code, out = self.pack({"name": "x", "tile_px": 8, "legend": {"g": {"top": "assets_src/grass.png"}}, "rows": ["g"],
                               "sprites": [{"source": "assets_src/post.png", "at": [3, 0]}]})
        self.assertEqual(code, 2)
        self.assertIn("outside the map", out)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)
