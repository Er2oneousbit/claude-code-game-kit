#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_store.py
# Purpose : offline exam for the store lane (lane_store.py): every Steam size exact, whole-number scaling of the key
#           art (no resampling), alpha only on the library logo, the logo inside each size's safe area and absent
#           from the hero and page background, the .ico frames, the app icon, achievement icons, the title-font
#           check and the project.godot edit, the default crop keeping the hero's top (#181), then whole pack runs
#           from your own pictures and from stand-in renders (no ComfyUI).
# Usage   : python tools/art/dotwork/tests/test_store.py   (test_dotwork.py runs it too)
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
DOTWORK = os.path.dirname(HERE)
sys.path.insert(0, DOTWORK)
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import fcore  # noqa: E402

# the table in README "Store art (Steam sizes)", from the Steamworks pages read on 2026-11-01
STEAM = {"header_capsule": (920, 430), "small_capsule": (462, 174), "main_capsule": (1232, 706),
         "vertical_capsule": (748, 896), "page_background": (1438, 810), "library_capsule": (600, 900),
         "library_header": (920, 430), "library_hero": (3840, 1240), "library_logo": (1280, 720)}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def art(h, w, seed):
    """Key art stand-in: every pixel a different colour, so any resampling or misplaced crop shows."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, (h, w, 3), dtype=np.uint8)


def icon64():
    a = np.zeros((64, 64, 4), np.uint8)
    a[6:58, 6:58] = (5, 4, 7, 255)
    a[8:56, 8:56] = (210, 150, 60, 255)
    a[20:44, 20:44] = (120, 70, 30, 255)
    return a


class StoreExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_store_")
        import lane_store
        self.ls = lane_store
        self.logo = lane_store.wordmark("Iron Oven", os.path.join(DOTWORK, "glyphs", "title_brass.txt"))
        self.wide, self.tall = art(180, 320, 1), art(320, 180, 2)
        self.parts = lane_store.compose(self.wide, self.tall, self.logo)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_every_steam_size_exact(self):
        self.assertEqual(set(self.parts), set(STEAM))
        for name, (W, H) in STEAM.items():
            img = self.parts[name][0]
            self.assertEqual((img.shape[1], img.shape[0]), (W, H), name)

    def test_whole_number_scaling_only(self):
        # outside the logo, every pixel is the key art pixel (y + y0) // k, (x + x0) // k: scaled by a whole number
        # and cropped, never resampled; k is the smallest that covers the size
        for name, (img, info) in self.parts.items():
            if name == "library_logo":
                continue
            src = self.tall if info["source"] == "tall" else self.wide
            k, H, W = info["k"], img.shape[0], img.shape[1]
            self.assertEqual(k, max(-(-W // src.shape[1]), -(-H // src.shape[0])), name)
            want = src[(np.arange(H) + info["y0"]) // k][:, (np.arange(W) + info["x0"]) // k]
            keep = np.ones((H, W), bool)
            if "logo_box" in info:
                x0, y0, x1, y1 = info["logo_box"]
                keep[y0:y1, x0:x1] = False
            self.assertTrue((img[keep] == want[keep]).all(), name)

    def test_alpha_only_on_the_library_logo(self):
        for name, (img, _) in self.parts.items():
            self.assertEqual(img.shape[2], 4 if name == "library_logo" else 3, name)
        logo = self.parts["library_logo"][0]
        self.assertEqual(int(logo[0, 0, 3]), 0)                       # transparent background
        self.assertGreater(int((logo[..., 3] == 255).sum()), 1000)    # the logotype itself
        self.assertTrue(set(np.unique(logo[..., 3])) <= {0, 255})

    def test_logo_safe_area_and_no_text_on_hero(self):
        lh, lw = self.logo.shape[:2]
        for name, (img, info) in self.parts.items():
            H, W = img.shape[:2]
            if name in ("library_hero", "page_background"):
                self.assertNotIn("logo_box", info, name)               # Steam: no words on the hero
                continue
            x0, y0, x1, y1 = info["logo_box"]
            self.assertGreaterEqual(x0, W * self.ls.SAFE, name)
            self.assertGreaterEqual(y0, H * self.ls.SAFE, name)
            self.assertLessEqual(x1, W - W * self.ls.SAFE, name)
            self.assertLessEqual(y1, H - H * self.ls.SAFE, name)
            self.assertEqual((x1 - x0, y1 - y0), (lw * info["logo_k"], lh * info["logo_k"]), name)
            if name != "library_logo":
                box = self.ls.SIZES[name][3]
                k = info["logo_k"]                                         # the largest whole scale that fits
                self.assertTrue(lw * k <= box[0] * W and lh * k <= box[1] * H, name)
                self.assertTrue(lw * (k + 1) > box[0] * W or lh * (k + 1) > box[1] * H, name)
        x0, _, x1, _ = self.parts["small_capsule"][1]["logo_box"]
        self.assertGreater((x1 - x0) / 462, 0.7)                        # "should nearly fill the capsule"

    def test_default_crop_keeps_the_heros_top(self):
        # #181: the lane's own key art puts the hero's top a tenth of the way down (SUBJECT). The centre crop of the
        # widest sizes kept under half the height and cut its head off in small_capsule and library_hero
        top = {key: int(self.ls.SUBJECT[key][1] * a.shape[0]) for key, a in (("wide", self.wide), ("tall", self.tall))}
        centre = self.ls.compose(self.wide, self.tall, self.logo)
        for size in ("small_capsule", "library_hero"):
            self.assertGreater(centre[size][1]["y0"], top["wide"] * centre[size][1]["k"], size)   # the old cut
        parts = self.ls.compose(self.wide, self.tall, self.logo, None)
        for size, (W, H) in STEAM.items():
            if size == "library_logo":
                continue
            info = parts[size][1]
            self.assertLessEqual(info["y0"], top[info["source"]] * info["k"], size)   # the hero's top row stays in
            if centre[size][1]["y0"] <= top[info["source"]] * info["k"]:
                self.assertEqual(info["y0"], centre[size][1]["y0"], size)               # already kept: as before
            self.assertEqual(info["x0"], centre[size][1]["x0"], size)                   # sideways as before
        self.assertLess(parts["small_capsule"][1]["focus"][1], 0.5)
        self.assertEqual(parts["vertical_capsule"][1]["focus"], [0.5, 0.5])   # the tall sizes kept it already

    def test_ico_frames_and_icons(self):
        icon = icon64()
        frames, app = self.ls.icon_set(icon, (28, 26, 36))
        path = self.ls.save_ico(frames, os.path.join(self.tmp, "game.ico"))
        with Image.open(path) as im:
            sizes = {s[0] for s in im.info["sizes"]}
            self.assertEqual(sizes, set(self.ls.ICO_SIZES))
            im.size = (64, 64)
            got = np.array(im.convert("RGBA"))
        self.assertTrue((got == icon).all())                            # the 64 px frame is the icon itself
        self.assertTrue((frames[256] == np.repeat(np.repeat(icon, 4, 0), 4, 1)).all())
        self.assertEqual(frames[16].shape, (16, 16, 4))
        self.assertEqual(app.shape, (184, 184, 3))                      # Steam app icon: 184 px, no alpha
        self.assertTrue((app[0, 0] == (28, 26, 36)).all())
        self.assertTrue((app[100, 100] == icon[(100 + 4) // 3, (100 + 4) // 3, :3]).all())

    def test_achievement_icons(self):
        src = Image.fromarray(np.full((32, 32, 4), (40, 200, 60, 255), np.uint8))
        got, grey = self.ls.achievement(src, (28, 26, 36), (106, 90, 58))
        self.assertEqual(got.shape, (256, 256, 3))
        self.assertTrue((got[128, 128] == (40, 200, 60)).all())         # 32 px x 7 = 224, centred
        self.assertTrue((grey[..., 0] == grey[..., 1]).all() and (grey[..., 1] == grey[..., 2]).all())
        luma = got.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
        self.assertLess(grey[..., 0].mean(), luma.mean())                 # greyed and a little darker

    def test_title_font_refuses_missing_characters(self):
        with self.assertRaises(fcore.ToolError) as cm:
            self.ls.wordmark("Brot & Co @", os.path.join(DOTWORK, "glyphs", "title_brass.txt"))
        self.assertIn("@", str(cm.exception))

    def test_apply_project_godot(self):
        pg = os.path.join(self.tmp, "project.godot")
        with open(pg, "w", encoding="utf-8") as f:
            f.write('config_version=5\n\n[application]\n\nconfig/name="Test"\nconfig/icon="res://icon.svg"\n\n'
                    '[display]\n\nwindow/size/viewport_width=640\n')
        self.ls.apply_project(pg, "res://assets/art/brand/x/icon_x.png", "res://assets/art/brand/x/boot_splash_x.png",
                              (28, 26, 36))
        first = read(pg)
        self.assertIn('config/icon="res://assets/art/brand/x/icon_x.png"', first)
        self.assertNotIn("res://icon.svg", first)
        self.assertIn('boot_splash/image="res://assets/art/brand/x/boot_splash_x.png"', first)
        self.assertIn("boot_splash/use_filter=false", first)
        self.assertIn('config/name="Test"', first)
        self.assertIn("window/size/viewport_width=640", first)
        self.assertLess(first.index("boot_splash/image"), first.index("[display]"))
        self.ls.apply_project(pg, "res://assets/art/brand/x/icon_x.png", "res://assets/art/brand/x/boot_splash_x.png",
                              (28, 26, 36))
        self.assertEqual(read(pg), first)       # running it again changes nothing
        import verify                                   # verify loads what project.godot names
        self.assertEqual(verify.project_images(self.tmp), ["res://assets/art/brand/x/boot_splash_x.png",
                                                           "res://assets/art/brand/x/icon_x.png"])

    def test_store_pack_from_own_pictures(self):
        import test_dotwork as td
        import dotwork
        td.make_project(self.tmp)
        os.makedirs(os.path.join(self.tmp, "assets_src"), exist_ok=True)
        Image.fromarray(self.wide).save(os.path.join(self.tmp, "assets_src", "wide.png"))
        Image.fromarray(self.tall).save(os.path.join(self.tmp, "assets_src", "tall.png"))
        Image.fromarray(icon64()).save(os.path.join(self.tmp, "assets_src", "icon.png"))
        Image.fromarray(np.full((32, 32, 4), (40, 200, 60, 255), np.uint8)).save(os.path.join(self.tmp, "assets_src", "a.png"))
        spec = os.path.join(self.tmp, "store.json")
        entry = {"name": "Iron Oven", "title": "Iron Oven", "source": "assets_src/wide.png",
                 "tall_source": "assets_src/tall.png", "icon_source": "assets_src/icon.png",
                 "achievements": [{"name": "first_loaf", "source": "assets_src/a.png"}], "apply": True}
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"name": "store", "store": [entry]}, f)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = dotwork.main(["pack", "--spec", spec, "--project", self.tmp, "--no-verify"])
        self.assertEqual(code, 0, out.getvalue())
        steam = os.path.join(self.tmp, "assets_src", "store", "iron_oven", "steam")
        for name, (W, H) in STEAM.items():
            with Image.open(os.path.join(steam, name + ".png")) as im:
                self.assertEqual(im.size, (W, H), name)
                self.assertEqual(im.mode, "RGBA" if name == "library_logo" else "RGB", name)
        for f in ("shortcut_icon.png", "shortcut_icon.ico", "app_icon.jpg", "achievements/first_loaf.png",
                  "achievements/first_loaf_locked.png"):
            self.assertTrue(os.path.isfile(os.path.join(steam, f)), f)
        brand = os.path.join(self.tmp, "assets", "art", "brand", "iron_oven")
        for f in ("icon_iron_oven.png", "icon_iron_oven.ico", "logo_iron_oven.png", "boot_splash_iron_oven.png",
                  "brand_iron_oven.tscn", "brand_icon_iron_oven.tscn"):
            self.assertTrue(os.path.isfile(os.path.join(brand, f)), f)
        pg = read(os.path.join(self.tmp, "project.godot"))
        self.assertIn('config/icon="res://assets/art/brand/iron_oven/icon_iron_oven.png"', pg)
        with Image.open(os.path.join(steam, "small_capsule.png")) as im:   # your own picture: centred, as before
            self.assertTrue((np.array(im) == self.parts["small_capsule"][0]).all())
        # the lane's own renders (stand-ins here) keep the hero's top in every size (#181); "focus" still wins
        renders = {"wide": self.wide, "tall": self.tall}
        fake = mock.patch.object(self.ls, "_render", lambda name, *a: renders[name.rsplit("_", 1)[1]])
        for extra, focus in (({}, None), ({"focus": [0.5, 0.5]}, (0.5, 0.5))):
            spec_e = dict({k: v for k, v in entry.items() if k not in ("source", "tall_source")}, prompt="a hero",
                          **extra)
            with open(spec, "w", encoding="utf-8") as f:
                json.dump({"name": "store", "store": [spec_e]}, f)
            with fake, contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = dotwork.main(["pack", "--spec", spec, "--project", self.tmp, "--no-verify"])
            self.assertEqual(code, 0, out.getvalue())
            want = self.ls.compose(self.wide, self.tall, self.logo, focus)
            for size in ("small_capsule", "library_hero", "vertical_capsule"):
                with Image.open(os.path.join(steam, size + ".png")) as im:
                    self.assertTrue((np.array(im) == want[size][0]).all(), (size, extra))
        # a spec without a title is a usage error
        entry.pop("title")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"name": "store", "store": [entry]}, f)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(dotwork.main(["pack", "--spec", spec, "--project", self.tmp, "--no-verify"]), 2)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)
