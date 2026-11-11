#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_unrun.py
# Purpose : offline exam for the Dotwork commands and lanes no other exam ran (#14, found with a coverage run of every
#           exam): `palette extract|extend`, `materials` and `--extend-palette`, `preview title|battle|attack`,
#           `audition --promote` and its argument checks, and the scenes, img2px and effects lanes, with stand-in
#           renders in place of ComfyUI (no GPU, no models).
# Usage   : python tools/art/dotwork/tests/test_unrun.py   (test_dotwork.py runs it too)
# Exit    : 0 all pass, 1 a case failed
# Notes   : Not covered here: an audition render (it needs a stand-in Wan clip job and a character's rotations) and
#           lane_icons.py, an 8-line alias of lane_props.run_icons, which test_dotwork's small-icons case runs.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   a fake game per case (project.godot + an optional dotwork.config.json)
#   palette/materials/previews: run dotwork.main in-process with art drawn by the test; check files, sizes, exit codes
#   lanes: patch engine.run / engine.put / fcore.ensure_comfy so a "render" is a PNG the test draws at the size the
#     graph asks for; run a pack spec through dotwork.main; check the shipped files and the manifest rows
import contextlib
import glob
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
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import fcore  # noqa: E402


def make_game(root, conf=None):
    os.makedirs(os.path.join(root, "art_src", "dotwork"), exist_ok=True)
    with open(os.path.join(root, "project.godot"), "w", encoding="utf-8") as f:
        f.write("config_version=5\n")
    if conf:
        with open(os.path.join(root, "art_src", "dotwork", "dotwork.config.json"), "w", encoding="utf-8") as f:
            json.dump(conf, f)
    return root


def save(path, img):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    (img if isinstance(img, Image.Image) else Image.fromarray(img)).save(path)
    return path


def figure(w, h, colour, box):
    """An RGBA sprite: a solid block at box (x0, y0, x1, y1) on transparency."""
    a = np.zeros((h, w, 4), np.uint8)
    x0, y0, x1, y1 = box
    a[y0:y1, x0:x1] = colour + (255,)
    return a


def busy(w, h, seed):
    """A stand-in render: blocks of a few colours, so the grid sample and the palette have something to do."""
    rng = np.random.default_rng(seed)
    cols = rng.integers(0, 256, (6, 3), dtype=np.uint8)
    idx = (np.add.outer(np.arange(h) // 16, np.arange(w) // 16) + seed) % len(cols)
    return cols[idx]


class Dw(unittest.TestCase):
    """A fresh game per case and dotwork.main run in-process."""

    conf = None

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_unrun_")
        self.game = make_game(os.path.join(self.tmp, "game"), self.conf)
        os.environ.pop("COMFYUI_URL", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def dw(self, *argv):
        import dotwork
        for mod in ("materials",):        # module-level paths are bound at import: one game per process in real runs
            sys.modules.pop(mod, None)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = dotwork.main([str(a) for a in argv] + ["--project", self.game])
        return code, out.getvalue() + err.getvalue()

    def art(self, *parts):
        return os.path.join(self.game, "assets", "art", *parts)


# ---- palette -------------------------------------------------------------------------------------------------------
class PaletteExam(Dw):
    def setUp(self):
        super().setUp()
        im = np.zeros((8, 8, 4), np.uint8)
        im[...] = (255, 0, 0, 255)
        im[0, :4] = (0, 0, 255, 255)
        im[1, :4] = (0, 200, 0, 255)
        im[2, :2] = (0, 0, 0, 0)                      # transparent pixels are not colours of the art
        self.src = save(os.path.join(self.tmp, "art.png"), im)
        self.base = os.path.join(self.tmp, "base.hex")
        with open(self.base, "w", encoding="utf-8") as f:
            f.write("000000\nffffff\n")

    def hexes(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read().split()

    def test_extract_snaps_to_colours_the_art_has(self):
        out = os.path.join(self.tmp, "sub", "game.hex")      # the folder is created
        code, text = self.dw("palette", "extract", self.src, "--colors", "64", "--out", out)
        self.assertEqual(code, 0, text)
        self.assertEqual(sorted(self.hexes(out)), ["0000ff", "00c800", "ff0000"])   # never more than the art has
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "sub", "game_swatch.png")))
        self.assertIn("3 colours from 1 files", text)
        code, text = self.dw("palette", "extract", self.src, "--colors", "2", "--out", out)
        self.assertEqual(code, 0, text)
        self.assertEqual(len(self.hexes(out)), 2)
        self.assertTrue(set(self.hexes(out)) <= {"0000ff", "00c800", "ff0000"})

    def test_extend_keeps_the_base_and_adds_what_is_missing(self):
        out = os.path.join(self.tmp, "env.hex")
        code, text = self.dw("palette", "extend", self.src, "--base", self.base, "--add", "2", "--out", out)
        self.assertEqual(code, 0, text)
        got = self.hexes(out)
        self.assertEqual(len(got), 4)
        self.assertTrue({"000000", "ffffff"} <= set(got))
        self.assertIn("2 base + 2 added = 4 colours", text)
        code, text = self.dw("palette", "extend", self.src, "--base", self.base, "--add", "9", "--out", out)
        self.assertEqual(code, 2)
        self.assertIn("lower --gap or --add", text)

    def test_bad_input_is_a_usage_error_not_a_crash(self):
        """Each of these used to end in "unexpected failure: ValueError/TypeError/FileNotFoundError(...)"."""
        clear = save(os.path.join(self.tmp, "clear.png"), np.zeros((4, 4, 4), np.uint8))
        out = os.path.join(self.tmp, "x.hex")
        cases = [
            (("extract", clear, "--out", out), "no opaque pixels"),
            (("extract", self.src, "--colors", "0", "--out", out), "--colors"),
            (("extract", self.src, "--colors", "-3", "--out", out), "--colors"),
            (("extend", self.src, "--out", out), "--base"),
            (("extend", self.src, "--base", self.base, "--add", "0", "--out", out), "--add"),
            (("extend", self.src, "--base", os.path.join(self.tmp, "nope.hex"), "--out", out), "nope.hex"),
            (("extract", os.path.join(self.tmp, "none*.png"), "--out", out), "no PNG files match"),
        ]
        for args, want in cases:
            with self.subTest(args=args[:-2]):
                code, text = self.dw("palette", *args)
                self.assertEqual(code, 2, text)
                self.assertIn(want, text)
                self.assertNotIn("unexpected failure", text)
        self.assertFalse(os.path.exists(out))


# ---- materials -----------------------------------------------------------------------------------------------------
class StandIn:
    """engine.run / engine.put / fcore.ensure_comfy replaced: a render is a PNG drawn here at the size asked."""

    def __init__(self, folder):
        self.folder, self.calls, self.last_put = folder, [], None
        os.makedirs(folder, exist_ok=True)

    def size_of(self, graph):
        for node in graph.values():
            ins = node.get("inputs", {})
            if isinstance(ins.get("width"), int) and isinstance(ins.get("height"), int):
                return ins["width"], ins["height"]
        return self.last_put or (128, 128)

    def run(self, graph, timeout=1800):
        w, h = self.size_of(graph)
        self.calls.append((w, h))
        path = os.path.join(self.folder, "render_%03d.png" % len(self.calls))
        Image.fromarray(busy(w, h, len(self.calls))).save(path)
        return path, 0.1

    def put(self, img, name):
        self.last_put = (Image.open(img) if isinstance(img, str) else img).size
        return name

    def patches(self):
        import engine
        return [mock.patch.object(engine, "run", self.run), mock.patch.object(engine, "put", self.put),
                mock.patch.object(fcore, "ensure_comfy", lambda *a, **k: None),
                mock.patch.object(fcore, "require_ram", lambda *a, **k: None)]

    def __enter__(self):
        self._stack = contextlib.ExitStack()
        for p in self.patches():
            self._stack.enter_context(p)
        return self

    def __exit__(self, *exc):
        self._stack.close()


class MaterialsExam(Dw):
    def test_render_then_extend_the_env_palette(self):
        code, text = self.dw("materials", "--extend-palette")         # nothing rendered yet
        self.assertEqual(code, 2)
        self.assertIn("run `dotwork.py materials` first", text)
        with StandIn(os.path.join(self.tmp, "renders")) as fake:
            code, text = self.dw("materials", "--only", "dirt", "brick_wall")
        self.assertEqual(code, 0, text)
        self.assertIn("[ OK ] 2 materials", text)
        self.assertEqual(len(fake.calls), 2)
        work = os.path.join(self.game, "art_src", "dotwork", "ground")
        self.assertEqual(sorted(os.listdir(os.path.join(work, "palette_src"))), ["brick_wall.png", "dirt.png"])
        with Image.open(os.path.join(work, "palette_src", "dirt.png")) as im:
            self.assertEqual(im.size, (112, 112))                      # 128 px less the 8 px frame each side
        self.assertTrue(os.path.isfile(os.path.join(work, "materials_sheet.png")))
        with StandIn(os.path.join(self.tmp, "renders")) as fake:       # cached: no second render
            self.assertEqual(self.dw("materials", "--only", "dirt")[0], 0)
        self.assertEqual(fake.calls, [])
        out = os.path.join(self.tmp, "env.hex")
        code, text = self.dw("materials", "--extend-palette", "--add", "4", "--out", out)
        self.assertEqual(code, 0, text)
        with open(fcore.Settings(self.game).conf["fixed"]["env_palette"], encoding="utf-8") as f:
            base = f.read().split()
        with open(out, encoding="utf-8") as f:
            grown = f.read().split()
        self.assertTrue(set(base) <= set(grown))
        self.assertLessEqual(len(grown), len(base) + 4)
        self.assertGreater(len(grown), len(base))


# ---- previews ------------------------------------------------------------------------------------------------------
class PreviewExam(Dw):
    def draw_game_art(self):
        save(self.art("scenes", "spr_scene_title.png"), busy(320, 180, 1))
        save(self.art("ui", "symbols", "ui_cursor_hand.png"), figure(12, 12, (250, 240, 200), (2, 2, 10, 10)))
        save(self.art("battle", "bg", "spr_bg_mine_cave.png"), busy(320, 128, 2))
        for i, n in enumerate(("guard_hound", "steam_rat")):
            save(self.art("battle", "enemies", "spr_enemy_%s.png" % n), figure(64, 64, (90 + 60 * i, 60, 40), (8, 20, 56, 64)))
        save(self.art("characters", "guard", "frames", "spr_guard_ready_w_00.png"), figure(48, 48, (40, 90, 160), (12, 6, 36, 48)))
        win = np.zeros((48, 48, 4), np.uint8)
        win[...] = (20, 30, 90, 255)
        win[:4], win[-4:], win[:, :4], win[:, -4:] = [(230, 230, 240, 255)] * 4
        save(self.art("ui", "windows", "ui_window_classic.png"), win)
        for k in range(4):                                             # the staff reaches furthest right on frame 2
            reach = (24, 30, 40, 28)[k]
            a = figure(48, 48, (120, 60, 160), (10, 8, 26, 48))
            a[14:17, 26:reach] = (200, 180, 90, 255)
            save(self.art("characters", "guard", "frames", "spr_guard_cast_e_%02d.png" % k), a)
        for fx, n in (("fireball", 3), ("explosion", 4)):
            for k in range(n):
                save(self.art("fx", fx, "spr_fx_%s_%02d.png" % (fx, k)), figure(16, 16, (255, 120 + 30 * k, 20), (2, 2, 14, 14)))

    def test_title_battle_and_attack_from_the_games_own_art(self):
        self.draw_game_art()
        preview = os.path.join(self.game, "assets_src", "preview")
        code, text = self.dw("preview", "title", "--title", "Iron Oven", "--subtitle", "A test")
        self.assertEqual(code, 0, text)
        for name, size in (("title_mock.png", (640, 360)), ("title_mock_2x.png", (1280, 720))):
            with Image.open(os.path.join(preview, name)) as im:
                self.assertEqual(im.size, size)
        code, text = self.dw("preview", "battle", "--char", "guard", "--enemies", "guard_hound", "steam_rat", "guard_hound")
        self.assertEqual(code, 0, text)
        with Image.open(os.path.join(preview, "battle_mock.png")) as im:
            self.assertEqual(im.size, (640, 360))
        code, text = self.dw("preview", "attack", "--char", "guard")
        self.assertEqual(code, 0, text)
        self.assertIn("peak frame 2", text)
        with Image.open(os.path.join(preview, "demo_guard_fireball.gif")) as im:
            self.assertEqual(im.size, (960, 336))
            self.assertGreater(im.n_frames, 8)
        self.assertTrue(os.path.isfile(os.path.join(preview, "demo_guard_fireball_strip.png")))

    def test_battle_out_keeps_its_folder_and_names_the_2x_beside_it(self):
        """--out without .png used to cut four letters off the name for the 2x copy ("shot" -> "_2x.png" in the
        current folder)."""
        self.draw_game_art()
        out = os.path.join(self.tmp, "shots", "battle")
        code, text = self.dw("preview", "battle", "--char", "guard", "--enemies", "steam_rat", "--out", out)
        self.assertEqual(code, 0, text)
        self.assertTrue(os.path.isfile(out + ".png"), os.listdir(os.path.dirname(out)))
        self.assertTrue(os.path.isfile(out + "_2x.png"), os.listdir(os.path.dirname(out)))

    def test_missing_art_names_the_file(self):
        code, text = self.dw("preview", "title")
        self.assertEqual(code, 2)
        self.assertIn("spr_scene_title.png not found", text)
        code, text = self.dw("preview", "attack", "--char", "nobody")
        self.assertEqual(code, 2)
        self.assertIn("no frames match", text)

    def test_attack_survives_an_empty_frame_and_refuses_a_zero_speed(self):
        """A blank frame in the clip (a fade-in) crashed peak() on getbbox() None; --speed 0 divided by zero."""
        self.draw_game_art()
        save(self.art("characters", "guard", "frames", "spr_guard_cast_e_04.png"), np.zeros((48, 48, 4), np.uint8))
        code, text = self.dw("preview", "attack", "--char", "guard")
        self.assertEqual(code, 0, text)
        self.assertIn("peak frame 2", text)
        code, text = self.dw("preview", "attack", "--char", "guard", "--speed", "0")
        self.assertEqual(code, 2, text)
        self.assertIn("--speed", text)
        self.assertNotIn("unexpected failure", text)


# ---- audition --------------------------------------------------------------------------------------------------------
class AuditionExam(Dw):
    def take(self, folder, seed, colour):
        for k in range(3):
            save(os.path.join(folder, "f_%05d.png" % k), figure(32, 32, colour, (8, 4 + k, 24, 32)))
        with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
            json.dump({"seed": seed, "motion_fix": None}, f)

    def test_promote_ships_a_take_and_keeps_the_old_clip(self):
        code, text = self.dw("audition", "--name", "guard", "--clip", "walk_e", "--promote", "m0_s8101")
        self.assertEqual(code, 2)
        self.assertIn("no take m0_s8101 in ", text)
        root = text.split("no take m0_s8101 in ", 1)[1].split(" (tags", 1)[0].strip()
        self.take(os.path.join(root, "m0_s8101"), 8101, (200, 40, 40))
        self.take(os.path.join(root, "m0_s8102"), 8102, (40, 200, 40))
        code, text = self.dw("audition", "--name", "guard", "--clip", "walk_e", "--promote", "m0_s8101")
        self.assertEqual(code, 0, text)
        self.assertIn("--fix walk_e:seed=8101", text)
        ship = os.path.join(os.path.dirname(os.path.dirname(root)), "clips", "walk_e")
        with open(os.path.join(ship, "meta.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["seed"], 8101)
        code, text = self.dw("audition", "--name", "guard", "--clip", "walk_e", "--promote", "m0_s8102")
        self.assertEqual(code, 0, text)
        self.assertTrue(os.path.isfile(os.path.join(root, "prev_s8101", "f_00000.png")))   # promotable back
        with open(os.path.join(ship, "meta.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["seed"], 8102)

    def test_usage_errors_before_any_render(self):
        """A clip with no direction and a hue range without a dash ended in "unexpected failure: ValueError"."""
        cases = [(("--clip", "walk_e", "--seeds", "1"), "run dotwork.py character for guard first"),
                 (("--clip", "walk_e"), "needs --seeds"),
                 (("--clip", "walk", "--seeds", "1"), "--clip walk"),
                 (("--clip", "walk_e", "--seeds", "1", "--feature-hue", "30"), "--feature-hue 30")]
        for args, want in cases:
            with self.subTest(args=args):
                code, text = self.dw("audition", "--name", "guard", *args)
                self.assertEqual(code, 2, text)
                self.assertIn(want, text)
                self.assertNotIn("unexpected failure", text)


# ---- lanes with stand-in renders ------------------------------------------------------------------------------------
class LaneExam(Dw):
    conf = {"project": {"src_dir": "art_source"}}     # not the default assets_src: paths must follow the config

    def pack(self, spec):
        path = os.path.join(self.tmp, "spec.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(spec, f)
        return self.dw("pack", "--spec", path, "--no-verify")

    def rows(self, pack):
        with open(os.path.join(self.game, "art_source", "dotwork", "manifest_%s.json" % pack), encoding="utf-8") as f:
            return {r["file"]: r for r in json.load(f)["assets"]}

    def test_scenes_backdrop_from_a_stand_in_render(self):
        with StandIn(os.path.join(self.tmp, "renders")) as fake:
            code, text = self.pack({"name": "title", "scenes": [{"name": "title", "prompt": "a brass city at dusk"}]})
        self.assertEqual(code, 0, text)
        self.assertEqual(fake.calls, [(2560, 1440)])
        with Image.open(self.art("scenes", "spr_scene_title.png")) as im:
            self.assertEqual(im.size, (320, 180))
        with Image.open(os.path.join(self.game, "art_source", "art", "scenes", "title_2x.png")) as im:
            self.assertEqual(im.size, (640, 360))
        self.assertTrue(os.path.isfile(self.art("scenes", "scene_title.tscn")))
        row = self.rows("title")["assets/art/scenes/spr_scene_title.png"]
        self.assertEqual(row["kind"], "scene_backdrop")

    def test_img2px_records_its_source_under_the_configured_folder(self):
        os.makedirs(os.path.join(self.game, "concept"))
        save(os.path.join(self.game, "concept", "tower.png"), busy(400, 300, 7))
        with StandIn(os.path.join(self.tmp, "renders")) as fake:
            code, text = self.pack({"name": "town", "img2px": [{"name": "tower", "source": "concept/tower.png",
                                                                "width": 40}]})
        self.assertEqual(code, 0, text)
        self.assertEqual(fake.calls, [(320, 240)])                     # 40x30 at 8x, rounded up to 16
        with Image.open(self.art("scenes", "spr_tower.png")) as im:
            self.assertEqual(im.size, (40, 30))
        row = self.rows("town")["assets/art/scenes/spr_tower.png"]
        # the old code wrote "assets_src/..." whatever src_dir said, a path that does not exist in this game
        self.assertEqual(row["source"], "art_source/art/scenes/tower_source.png")
        self.assertTrue(os.path.isfile(os.path.join(self.game, *row["source"].split("/"))))
        with StandIn(os.path.join(self.tmp, "renders")) as fake:       # same request: resumed, no render
            self.assertEqual(self.pack({"name": "town", "img2px": [{"name": "tower", "source": "concept/tower.png",
                                                                    "width": 40}]})[0], 0)
        self.assertEqual(fake.calls, [])

    def test_tools_edit_records_its_source_under_the_configured_folder(self):
        """The tools lane's rows named assets_src/art/tools/<name>/source.png whatever src_dir said, so qa_pack's
        colour check (which opens that file) found nothing and skipped the edit."""
        save(os.path.join(self.game, "concept", "guard.png"), figure(32, 32, (60, 90, 160), (8, 4, 24, 32)))

        def fake_job(graph, timeout=1800):
            prefix = next(n["inputs"]["filename_prefix"] for n in graph.values() if n["class_type"] == "SK_SavePixelArt")
            out = os.path.join(fcore.WORK, "comfy_out", *prefix.split("/")) + "_00031_.png"
            save(out, figure(32, 32, (200, 40, 40), (8, 4, 24, 32)))
            return {"files": [out], "seconds": 0.1}

        graph = {"2": {"class_type": "LoadImage", "inputs": {}}, "5": {"class_type": "LoadImage", "inputs": {}},
                 "13": {"class_type": "CLIPTextEncode", "inputs": {}}, "9": {"class_type": "SK_SavePixelArt", "inputs": {}}}
        import engine
        import lane_character
        sys.modules.pop("lane_tools", None)      # COMFY_OUT is bound at import, to the game of the first run
        with StandIn(os.path.join(self.tmp, "renders")), mock.patch.object(engine, "run_job", fake_job), \
                mock.patch.object(lane_character, "_wf", lambda name: json.loads(json.dumps(graph))):
            code, text = self.pack({"name": "kit", "tools": [{"name": "guard_edit", "source": "concept/guard.png",
                                                              "edits": ["give him a red scarf"]}]})
        sys.modules.pop("lane_tools", None)
        self.assertEqual(code, 0, text)
        row = self.rows("kit")["assets/art/tools/guard_edit/spr_guard_edit_edit_00.png"]
        self.assertEqual(row["source"], "art_source/art/tools/guard_edit/source.png")
        self.assertTrue(os.path.isfile(os.path.join(self.game, *row["source"].split("/"))))

    def test_effects_one_shot_and_loop_from_a_cached_clip(self):
        """The effect lane's first frame and Wan clip are cached in the work folder: seed them, and the lane runs its
        own part (keep, ping-pong, dithered fade, vignette, export) without ComfyUI."""
        entries = [{"name": "burst", "subject": "a burst of flames", "motion": "the flames burst and fade", "keep": 3,
                    "size": 32},
                   {"name": "orb", "subject": "a glowing orb", "motion": "the orb pulses", "loop": True, "keep": 4,
                    "size": 32}]
        sentinel = RuntimeError("no ComfyUI in this exam")

        def refuse(*a, **k):
            raise sentinel

        work = os.path.join(self.game, "art_src", "dotwork", "fx")
        for e in entries:            # each run stops at the first effect without a cache; its folder is there by then
            with mock.patch.object(fcore, "ensure_comfy", refuse):
                self.assertEqual(self.pack({"name": "fx", "effects": entries})[0], 2)
            d = glob.glob(os.path.join(work, e["name"] + "_s777_32_*"))
            self.assertEqual(len(d), 1, os.listdir(work))
            save(os.path.join(d[0], "first.png"), figure(32, 32, (255, 140, 30), (8, 8, 24, 24)))
            for k in range(6):
                save(os.path.join(d[0], "clip", "f_%05d.png" % k), figure(32, 32, (255, 100 + 20 * k, 30), (6, 6, 26, 26)))
        with mock.patch.object(fcore, "ensure_comfy", refuse):
            code, text = self.pack({"name": "fx", "effects": entries})
        self.assertEqual(code, 0, text)
        burst = sorted(os.listdir(self.art("fx", "burst")))
        self.assertEqual(len([f for f in burst if f.endswith(".png")]), 3 + 4)     # kept frames + 4 dissolve steps
        orb = [f for f in os.listdir(self.art("fx", "orb")) if f.endswith(".png")]
        self.assertEqual(len(orb), 4 + 2)                                      # 0 1 2 3 2 1
        with Image.open(self.art("fx", "orb", "spr_fx_orb_04.png")) as a, \
                Image.open(self.art("fx", "orb", "spr_fx_orb_02.png")) as b:
            self.assertEqual(np.array(a).tobytes(), np.array(b).tobytes())   # the ping-pong repeats frame 2
        self.assertTrue(os.path.isfile(self.art("fx", "mat_additive.tres")))
        with open(self.art("fx", "orb", "fx_orb_frames.tres"), encoding="utf-8") as f:
            self.assertIn("loop", f.read())


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)
