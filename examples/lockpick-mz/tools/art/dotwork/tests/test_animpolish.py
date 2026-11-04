#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_animpolish.py
# Purpose : offline exam for the opt-in animation polish (animpolish.py, pose.py anticipation, godot.sprite_frames
#           durations, the character lane's holds / smear / anticipation / shaders keys): defaults unchanged against
#           digests taken from the code before the polish, the smear on the frame of peak motion and in the frame's own
#           colours, holds in the SpriteFrames, the wind-up moving against the strike, and the shader files.
# Usage   : python -I -B tools/art/dotwork/tests/test_animpolish.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : No GPU, ComfyUI, models or Godot. GOLDEN holds digests of the skeleton (keypoints rounded to 1e-9, so a
#           libm that differs in the last bit still matches) and of a character export with no polish keys, taken from
#           the code before this change.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import hashlib
import json
import os
import re
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

GOLDEN = {
    "keypoints": "49152de2cd3aff7e3ef89700c1df408c6c91275be18f0495c0daf4c18ad4cb14",
    "frames": "635fbd84c7e88bab77664a2457a8a9eefa776da1f017f86ecf8078a565323ca3",
    "motion_keys": {"attack": "df7df204ba", "cast": "6948158e8c", "idle": "a4721a6dcf", "walk": "aae3afffae"},
    "tres": "eb91bc2244c8e7a2fc508a250b1d64aba2a116be8e58e03425d936df4b1e9e34",
    "sheet_json": "e0f16d4a3512317863ff71794c601d58e2807c3a58c5179b3909be2b76fadc7d",
    "frame_pixels": "9486242aeaf7529c60ceaa0d425ea53d5159592cb66ba2e7fea2594251250fa6",
}
OUTLINE, IRON, BLADE, SHINE = (24, 20, 30), (120, 120, 130), (176, 186, 200), (236, 240, 248)


def read(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8", "newline": ""})) as f:
        return f.read()


def chibi():
    """A 72 px figure with a face (fit() measures it), as the skeleton tests use."""
    im = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
    im.paste((40, 110, 50, 255), (26, 6, 46, 70))
    im.paste((250, 210, 180, 255), (30, 22, 42, 34))
    return im


def plain(x, arm_y):
    """The figure the golden export was made from: a block body and a bar that moves (no outline)."""
    a = np.zeros((72, 64, 4), np.uint8)
    a[10:70, 20 + x:36 + x] = (120, 120, 130, 255)
    a[arm_y:arm_y + 4, 36 + x:56 + x] = (200, 60, 40, 255)
    return Image.fromarray(a)


def knight(arm_y, x=0):
    """An outlined iron body with an outlined sword held out to its right: the blade's rows move with arm_y."""
    a = np.zeros((72, 64, 4), np.uint8)
    a[9:71, 19 + x:37 + x] = OUTLINE + (255,)
    a[10:70, 20 + x:36 + x] = IRON + (255,)
    a[arm_y - 1:arm_y + 5, 36 + x:57 + x] = OUTLINE + (255,)
    a[arm_y:arm_y + 4, 37 + x:56 + x] = BLADE + (255,)
    a[arm_y + 1:arm_y + 3, 38 + x:55 + x] = SHINE + (255,)
    return Image.fromarray(a)


def durations_of(tres):
    """{animation: [frame durations]} parsed from a SpriteFrames .tres."""
    out = {}
    for block in re.findall(r'\{\n"frames": \[(.*?)\],\n"loop": \w+,\n"name": &"(\w+)"', read(tres), re.S):
        out[block[1]] = [float(d) for d in re.findall(r'"duration": ([0-9.]+)', block[0])]
    return out


class AnimPolish(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_animpolish_")
        os.environ.pop("COMFYUI_URL", None)
        import godot
        self.godot_was = godot.ENABLED

    def tearDown(self):
        import godot
        godot.ENABLED = self.godot_was
        shutil.rmtree(self.tmp, ignore_errors=True)

    def bind(self, root=None, engine=None):
        """A bare game (project.godot + work folder) bound like dotwork.py binds one; ComfyUI points at a closed port,
        so nothing here can reach a real server."""
        root = root or self.tmp
        os.makedirs(os.path.join(root, "art_src", "dotwork"), exist_ok=True)
        with open(os.path.join(root, "project.godot"), "w") as f:
            f.write("config_version=5\n")
        with open(os.path.join(root, "art_src", "dotwork", "dotwork.config.json"), "w", encoding="utf-8") as f:
            json.dump({"comfyui": {"url": "http://127.0.0.1:9"}}, f)
        import engine as eng
        import godot
        s = fcore.Settings(root, engine=engine)
        fcore.bind(s)
        fcore.load_lock()
        eng.bind(s.conf)
        godot.ENABLED = s.godot()
        return s

    def character(self, s, entry, clips):
        import lane_character as lc
        man = fcore.Manifest(s, "polish")
        c = lc.Character(entry, s.project, man, s.conf)
        sp = os.path.join(self.tmp, "rot_ref.png")
        next(iter(clips.values()))[0][0].save(sp)
        rot = {d: sp for d in {d for _, d in clips}}
        return c, man, rot

    # ---- 1. defaults: the same skeleton, cache keys and SpriteFrames as before the polish
    def test_defaults_match_the_base_output(self):
        import godot
        import pose
        s = self.bind()
        for wind in (None, 0.0):   # the default, and the new keyword at 0: both are the old skeleton
            kw = {} if wind is None else {"anticipation": wind}
            h = hashlib.sha256()
            for a in pose.ACTIONS:
                for v in ("side", "quarter", "front"):
                    for i in range(33):
                        h.update(repr([(round(x, 9), round(y, 9)) for x, y in pose.keypoints(a, i / 32, v, **kw)])
                                 .encode())
            self.assertEqual(h.hexdigest(), GOLDEN["keypoints"], kw)
            h = hashlib.sha256()
            for a in pose.ACTIONS:
                for d in ("s", "e", "n", "w", "se"):
                    for f in pose.frames(a, d, chibi(), n=9, size=160, **kw):
                        h.update(f.tobytes())
            self.assertEqual(h.hexdigest(), GOLDEN["frames"], kw)
        self.assertEqual(pose.VERSION, 2)
        # an entry with no polish keys (or switched off) keeps every clip's cache key and exports the same files
        for extra in ({}, {"anticipation": False, "holds": False, "smear": False, "shaders": False}):
            entry = dict({"name": "knight", "actions": ["idle", "walk", "attack", "cast"], "directions": ["s", "e"],
                          "skeleton": ["walk", "attack", "cast"]}, **extra)
            clips = {("idle", "s"): ([plain(0, 30), plain(0, 31)], []),
                     ("attack", "e"): ([plain(0, y) for y in (30, 29, 27, 20, 10, 6, 5, 5)], []),
                     ("cast", "e"): ([plain(x, 30) for x in (0, 1, 2, 3)], [])}
            c, man, rot = self.character(s, entry, clips)
            self.assertEqual({a: c.motion_key(a) for a in ("walk", "attack", "cast", "idle")}, GOLDEN["motion_keys"])
            tres, size = c.export(clips, rot)
            self.assertEqual(size, [72, 72])
            self.assertEqual(hashlib.sha256(read(tres, "rb")).hexdigest(), GOLDEN["tres"], extra)
            js = os.path.join(c.out, "knight_attack_e_sheet.json")
            self.assertEqual(hashlib.sha256(read(js, "rb")).hexdigest(), GOLDEN["sheet_json"], extra)
            h = hashlib.sha256()
            for n in sorted(os.listdir(os.path.join(c.out, "frames"))):
                h.update(n.encode() + Image.open(os.path.join(c.out, "frames", n)).convert("RGBA").tobytes())
            self.assertEqual(h.hexdigest(), GOLDEN["frame_pixels"], extra)
            self.assertNotIn("durations", json.dumps(man.data))
        # the writer: no durations (or None) is the old text exactly
        a = godot.sprite_frames(os.path.join(self.tmp, "a.tres"), "res://x", {"walk": (["a.png", "b.png"], 8, True)})
        b = godot.sprite_frames(os.path.join(self.tmp, "b.tres"), "res://x",
                                {"walk": (["a.png", "b.png"], 8, True, None)})
        self.assertEqual(read(a, "rb"), read(b, "rb"))
        self.assertEqual(read(a).count('"duration": 1.0,'), 2)

    # ---- 2. the smear lands on the frame of peak motion
    def test_smear_lands_on_the_peak_frame(self):
        import animpolish
        s = self.bind()
        ys = [40, 39, 37, 30, 20, 16, 15, 15]   # the sword's top row per frame: fastest around frames 3 and 4
        # the peak frame from the known motion alone: the largest step between each frame's neighbours
        want = max(range(1, len(ys) - 1), key=lambda i: abs(ys[i + 1] - ys[i - 1]))
        self.assertEqual(want, 3)
        fr = [knight(y) for y in ys]
        fr[5] = knight(ys[5], x=3)   # the export re-centres a frame whose bbox grew: the whole body jumps 3 px
        sp = animpolish.speeds(fr, loop=False)
        self.assertEqual((sp[0], sp[-1]), (0, 0))                       # a one-shot's ends have no speed
        self.assertEqual(int(np.argmax(sp)), want)
        self.assertEqual(animpolish.peak(fr, False), want)
        img, info = animpolish.smear(fr, want)
        self.assertIsNotNone(img, info)
        before, after = np.array(fr[want]), np.array(img)
        new = (after[..., 3] == 255) & (before[..., 3] == 0)
        self.assertTrue(np.array_equal(after[before[..., 3] == 255], before[before[..., 3] == 255]))   # drawn as was
        self.assertGreater(new.sum(), 40)
        rows, cols = np.nonzero(new)
        # the sword rose from rows 36-41 to 29-34: the smear trails below it, back along its path, beside the body
        self.assertEqual((rows.min(), rows.max()), (35, 41))
        self.assertTrue(cols.min() >= 37 and cols.max() <= 56, (cols.min(), cols.max()))
        self.assertLess(info["vector"][1], -5)                           # it moved up
        self.assertIsNone(animpolish.smear([knight(30), knight(30), knight(30)], 1)[0])   # nothing moved: none
        # through the character lane: only the peak frame changes, the frame count stays, the QA note says where
        clips = {("attack", "e"): ([knight(y) for y in ys], [])}
        c, man, rot = self.character(s, {"name": "knight", "actions": ["attack"], "directions": ["e"]}, clips)
        c.export(clips, rot)
        plain_px = {n: np.array(Image.open(os.path.join(c.out, "frames", n))) for n in os.listdir(os.path.join(c.out,
                                                                                                             "frames"))}
        c2, man2, _ = self.character(s, {"name": "knight", "actions": ["attack"], "directions": ["e"], "smear": True},
                                     clips)
        c2.export(clips, rot)
        smeared = {n: np.array(Image.open(os.path.join(c2.out, "frames", n))) for n in os.listdir(os.path.join(
            c2.out, "frames"))}
        self.assertEqual(sorted(smeared), sorted(plain_px))
        changed = [n for n in sorted(plain_px) if not np.array_equal(plain_px[n], smeared[n])]
        self.assertEqual(changed, [f"spr_knight_attack_e_{want:02d}.png"])
        row = next(r for r in man2.data["assets"] if r["kind"] == "sheet")
        self.assertTrue(any(f"smear on frame {want}" in q for q in row["qa"]), row["qa"])
        # smear: true covers the strikes only; a walk is smeared when named
        self.assertIsNone(animpolish.pick(True, "walk", "e"))
        self.assertTrue(animpolish.pick(["walk"], "walk", "e"))
        self.assertIsNone(animpolish.pick({"attack_w": True}, "attack", "e"))
        self.assertTrue(animpolish.pick({"attack_w": True}, "attack", "w"))

    # ---- 3. the smear's colours are the frame's own
    def test_smear_uses_only_the_frames_colours(self):
        import animpolish
        fr = [knight(y) for y in (44, 42, 30, 18, 16)]
        k = animpolish.peak(fr, False)
        self.assertEqual(k, 2)
        img, info = animpolish.smear(fr, k)
        self.assertIsNotNone(img, info)
        before, after = np.array(fr[k]), np.array(img)
        self.assertEqual(set(np.unique(after[..., 3]).tolist()) - {0, 255}, set())   # no partial alpha
        pal = {tuple(p) for p in before[before[..., 3] == 255][:, :3].tolist()}
        got = {tuple(p) for p in after[after[..., 3] == 255][:, :3].tolist()}
        self.assertLessEqual(got, pal)                                                # nothing outside the palette
        new = (after[..., 3] == 255) & (before[..., 3] == 0)
        trail = {tuple(p) for p in after[new][:, :3].tolist()}
        self.assertTrue(trail and trail <= {BLADE, SHINE}, trail)   # the blade's own colours, never the outline
        # a far half that thins out: the last rows of the smear are a checker, not solid
        rows = np.nonzero(new.any(1))[0]
        far = new[rows.max()]
        self.assertTrue(far.any() and not (far[np.nonzero(far)[0].min():np.nonzero(far)[0].max() + 1]).all())

    # ---- 3b. a lunge: only the blade is smeared, and a body that only changes shape is not smeared at all (#187)
    def test_smear_leaves_the_body_on_a_lunge(self):
        import animpolish

        def lunger(legs_x, blade_y):
            """A head and torso that stay, legs that step legs_x px (the body changes shape: the alignment cannot
            undo it) and a thin blade held out at blade_y."""
            a = np.zeros((72, 72, 4), np.uint8)
            a[5:51, 19:37] = OUTLINE + (255,)
            a[6:50, 20:36] = IRON + (255,)
            a[49:71, 19 + legs_x:37 + legs_x] = OUTLINE + (255,)
            a[50:70, 20 + legs_x:36 + legs_x] = (90, 60, 50, 255)
            a[blade_y - 1:blade_y + 3, 36:68] = OUTLINE + (255,)
            a[blade_y:blade_y + 2, 37:67] = BLADE + (255,)
            return Image.fromarray(a)
        for step in (4, -4, -6):
            fr = [lunger(0, 36), lunger(step, 24)]       # the blade rises 12 px while the legs step
            img, info = animpolish.smear(fr, 1)
            self.assertIsNotNone(img, (step, info))
            before, after = np.array(fr[1]), np.array(img)
            rows, cols = np.nonzero((after[..., 3] == 255) & (before[..., 3] == 0))
            # only along the blade's path (rows 23-38 between where it was and where it is), nothing at the legs
            self.assertTrue(rows.min() >= 23 and rows.max() <= 38 and cols.min() >= 36, (step, rows.min(), rows.max()))
            self.assertLess(info["vector"][1], -10, step)                 # it moved up, as the blade did
            self.assertLess(abs(info["vector"][0]), 2, step)              # not sideways with the legs
        # the legs step and nothing else moves: no smear, and the note says why
        img, info = animpolish.smear([lunger(0, 30), lunger(-6, 30)], 1)
        self.assertIsNone(img)
        self.assertIn("mostly the body", info)
        # the showcase duelist's west attack, frames 2 and 3 of seed 4244 (fixtures/duelist_lunge.png, Dotwork's own
        # output): the smear dragged the coat and left checker squares at the boots. The blade barely moves there;
        # the coat and the boots do
        strip = Image.open(os.path.join(HERE, "fixtures", "duelist_lunge.png")).convert("RGBA")
        fr = [strip.crop((0, 0, 72, 72)), strip.crop((72, 0, 144, 72))]
        img, info = animpolish.smear(fr, 1)
        self.assertIsNone(img, info)
        self.assertIn("mostly the body", info)

    # ---- 4. holds land in the SpriteFrames (and the sheet JSON, for other engines)
    def test_holds_in_the_spriteframes(self):
        import animpolish
        import godot
        s = self.bind()
        self.assertEqual([godot.duration(v) for v in (1, 2, 1.5, 0.25, 3.0)], ["1.0", "2.0", "1.5", "0.25", "3.0"])
        with self.assertRaises(ValueError):
            godot.duration(0)
        ys = [40, 39, 37, 30, 20, 16, 15, 15]
        clips = {("attack", "e"): ([knight(y) for y in ys], []),
                 ("walk", "s"): ([knight(y) for y in (30, 31, 30, 29)], []),
                 ("walk", "e"): ([knight(y) for y in (30, 31, 30, 29)], []),
                 ("cast", "e"): ([knight(y) for y in (30, 28, 24, 30)], []),
                 ("idle", "s"): ([knight(30), knight(31)], [])}
        entry = {"name": "knight", "actions": ["idle", "walk", "attack", "cast"], "directions": ["s", "e"],
                 "holds": {"attack": True, "walk": {"1": 2.5}, "cast_e": [1, 2, 1, 4]}}
        c, man, rot = self.character(s, entry, clips)
        tres, _ = c.export(clips, rot)
        got = durations_of(tres)
        k = animpolish.peak([knight(y) for y in ys], False)
        self.assertEqual(k, 3)
        attack = [1.0] * 8
        attack[k - 1], attack[k + 1] = animpolish.HOLDS["attack"]   # the wind-up, and the hit-stop on the impact
        self.assertEqual(got["attack_e"], attack)
        self.assertEqual(attack[2:5], [2.0, 1.0, 3.0])
        self.assertEqual(got["walk_s"], [1.0, 2.5, 1.0, 1.0])
        self.assertEqual(got["walk_e"], [1.0, 2.5, 1.0, 1.0])           # an action's rule covers each of its clips
        self.assertEqual(got["cast_e"], [1.0, 2.0, 1.0, 4.0])
        self.assertEqual(got["idle_s"], [1.0, 1.0])
        with open(os.path.join(c.out, "knight_attack_e_sheet.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["durations"], attack)
        with open(os.path.join(c.out, "knight_idle_s_sheet.json"), encoding="utf-8") as f:
            self.assertNotIn("durations", json.load(f))
        row = next(r for r in man.data["assets"] if r.get("animation") == "attack_e" and r["kind"] == "sheet")
        self.assertEqual(row["durations"], attack)
        self.assertTrue(any("frame 2 x2 (wind-up)" in q and "frame 4 x3 (impact)" in q for q in row["qa"]), row["qa"])
        # holds: true covers attack, cast and shoot; a list that does not fit the clip is padded and said so
        self.assertIsNone(animpolish.pick(True, "walk", "s"))
        d, note = animpolish.durations(4, None, [2, 2], "walk", True)
        self.assertEqual((d, "padded" in note), ([2.0, 2.0, 1.0, 1.0], True))
        d, note = animpolish.durations(8, 0, True, "attack", True)       # a loop wraps: the wind-up is the last frame
        self.assertEqual((d[7], d[1]), (2.0, 3.0))
        # spec mistakes stop the character before anything renders
        import lane_character as lc
        for bad in ({"holds": {"atack": True}}, {"holds": {"attack": [1, 0]}}, {"holds": {"attack": {"x": 2}}},
                    {"holds": "yes"}, {"smear": {"jump": True}}, {"shaders": ["glow"]}, {"shaders": []}):
            with self.assertRaises(fcore.ToolError, msg=bad):
                lc.Character(dict({"name": "x", "actions": ["walk", "attack"]}, **bad), s.project,
                             fcore.Manifest(s, "x"), s.conf)

    # ---- 5. anticipation: the wind-up moves against the strike, just before it
    def test_anticipation_pulls_back_before_the_strike(self):
        import pose
        s = self.bind()
        ts = [i / 64 for i in range(65)]
        for a in pose.ANTICIPATE:
            base = [pose.keypoints(a, t, "side") for t in ts]
            wind = [pose.keypoints(a, t, "side", anticipation=1.0) for t in ts]
            wx = [kp[4][0] for kp in base]                           # the striking (right) wrist; + x is forward
            strike = max(range(len(ts) - 1), key=lambda i: wx[i + 1] - wx[i])
            self.assertGreater(wx[strike + 1] - wx[strike], 0, a)    # the strike moves forward (+x)
            before = range(1, strike + 3)
            # the wind-up: before the strike the body and the wrist go back (-x), further than the action alone
            i = min(before, key=lambda j: wind[j][1][0] - base[j][1][0])
            self.assertLess(wind[i][1][0] - base[i][1][0], -0.04, a)          # the neck leans away from the target
            self.assertLess(wind[i][1][0], base[0][1][0] - 0.02, a)           # behind where it stood at rest
            self.assertLess(wind[i][4][0] - base[i][4][0], -0.04, a)          # the wrist draws back with it
            self.assertLess(wind[i][8][1], base[i][8][1], a)                  # and the body sinks a little
            self.assertLess(ts[i], 0.3, a)
            # then the strike still lands where it did: forward of the wind-up, the same pose once it is over
            self.assertGreater(max(kp[4][0] for kp in wind[i:]) - wind[i][4][0], 0.1, a)
            self.assertEqual([wind[j] for j in range(len(ts)) if ts[j] >= 0.45],
                             [base[j] for j in range(len(ts)) if ts[j] >= 0.45], a)
            for v in ("side", "quarter", "front"):   # the loop starts (and frames() ends) on the action's own pose
                self.assertEqual(pose.keypoints(a, 0.0, v, anticipation=1.0), pose.keypoints(a, 0.0, v), (a, v))
                if a != "attack":   # cast and shoot come back to rest at t 1 too (attack's arm never did)
                    self.assertEqual(pose.keypoints(a, 1.0, v, anticipation=1.0), pose.keypoints(a, 0.0, v), (a, v))
            if a != "attack":
                for t in ts:   # feet planted
                    kp = pose.keypoints(a, t, "quarter", anticipation=0.6)
                    self.assertEqual((kp[10][1], kp[13][1]), (pose.H["ankle"], pose.H["ankle"]), (a, t))
            # on screen: facing east the head goes left during the wind-up, facing west it goes right
            spr = chibi()
            for d, sign in (("e", -1), ("w", 1)):
                off = [np.array(f) for f in pose.frames(a, d, spr, n=17)]
                on = [np.array(f) for f in pose.frames(a, d, spr, n=17, anticipation=1.0)]
                nose = np.array(pose.COLOURS[0])
                shift = []
                for j in range(1, 5):   # t 1/16 .. 4/16: the wind-up
                    x0 = np.nonzero((off[j] == nose).all(-1))[1].mean()
                    x1 = np.nonzero((on[j] == nose).all(-1))[1].mean()
                    shift.append(x1 - x0)
                self.assertGreater(max(sign * v for v in shift), 15, (a, d, shift))
                self.assertTrue(np.array_equal(on[0], on[-1]), (a, d))
                self.assertTrue(np.array_equal(on[12], off[12]), (a, d))   # t 0.75: the wind-up is long gone
        # the character key: skeleton strikes only; its clips (and only those) get a new cache key
        import lane_character as lc
        plainc = lc.Character({"name": "k", "actions": ["walk", "attack", "cast"], "skeleton": ["walk", "attack", "cast"]},
                              s.project, fcore.Manifest(s, "k"), s.conf)
        c = lc.Character({"name": "k", "actions": ["walk", "attack", "cast"], "skeleton": ["walk", "attack", "cast"],
                          "anticipation": {"attack": True, "cast": 0.5}}, s.project, fcore.Manifest(s, "k"), s.conf)
        self.assertEqual(c.wind, {"attack": 1.0, "cast": 0.5})
        self.assertEqual(c.motion_key("walk"), plainc.motion_key("walk"))
        self.assertNotEqual(c.motion_key("attack"), plainc.motion_key("attack"))
        self.assertNotEqual(c.motion_key("cast"), plainc.motion_key("cast"))
        allc = lc.Character({"name": "k", "actions": ["walk", "attack"], "skeleton": ["walk", "attack"],
                             "anticipation": True}, s.project, fcore.Manifest(s, "k"), s.conf)
        self.assertEqual(allc.wind, {"attack": 1.0})
        for bad in ({"anticipation": ["attack"], "skeleton": ["walk"]},              # not a skeleton action
                    {"anticipation": ["walk"], "skeleton": ["walk"]},                # no strike to wind up
                    {"anticipation": {"attack": 1.5}, "skeleton": ["attack"]}):
            with self.assertRaises(fcore.ToolError, msg=bad):
                lc.Character(dict({"name": "x", "actions": ["walk", "attack"]}, **bad), s.project,
                             fcore.Manifest(s, "x"), s.conf)
        man = fcore.Manifest(s, "none")
        lc.Character({"name": "y", "actions": ["walk"], "anticipation": True}, s.project, man, s.conf)
        self.assertTrue(any("anticipation is for skeleton" in t for t in man.data["assumptions"]))
        # the render hands the amount to the skeleton (the graph and the server are stand-ins: nothing is sent)
        seen = []

        class Sent(Exception):
            pass

        def frames(action, direction, sprite, **kw):
            sprite.close()
            seen.append((action, kw.get("anticipation")))
            return []

        def run_job(g, timeout=0):
            raise Sent()
        graph = {"2": {"class_type": "LoadImage", "inputs": {}}, "5": {"class_type": "SK_AnimationPreset", "inputs": {}},
                 "18": {"class_type": "CLIPTextEncode", "inputs": {}},
                 "29": {"class_type": "SK_Stabilize", "inputs": {"frames": ["28", 0], "anchor": "bottom_center"}}}
        sprite = os.path.join(self.tmp, "k_e.png")
        chibi().save(sprite)
        with mock.patch.object(lc, "_wf", lambda name: json.loads(json.dumps(graph))), \
                mock.patch.object(lc.lib, "put", lambda img, name: (img.close(), name)[1]), \
                mock.patch.object(lc.lib, "missing_models", lambda names: []), \
                mock.patch.object(lc.lib, "run_job", run_job), \
                mock.patch.object(lc.pose, "frames", frames), \
                mock.patch.object(lc.pose, "control_graph", lambda g, names, *a, **k: g), \
                mock.patch.object(fcore, "ensure_comfy", lambda *a: None), \
                mock.patch.object(fcore, "require_ram", lambda *a, **k: None):
            for action in ("attack", "walk"):
                with self.assertRaises(Sent):
                    c.render(action, "e", sprite, 4242, os.path.join(self.tmp, "clips", f"{action}_e"))
        self.assertEqual(seen, [("attack", 1.0), ("walk", 0.0)])

    # ---- 5b. #180: a skeleton strike holds around the skeleton's strike frame, not the measured peak
    def test_skeleton_holds_land_on_the_strike(self):
        import animpolish
        import pose
        s = self.bind()
        # a plain skeleton shoot as Wan draws it: the biggest motion is the weapon coming up from rest (frames 0-2),
        # then the held aim, a small recoil at frame 4 and the aim again. The measured peak is the raise
        ys = [60, 50, 30, 30, 27, 30, 30, 40]
        fr = [knight(y) for y in ys]
        self.assertIn(animpolish.peak(fr, False), (1, 2))
        self.assertEqual(pose.strike_frame("shoot", 8), 4)   # the recoil, t 0.52, of 8 frames over one loop
        clips = {("shoot", "e"): (fr, [])}
        entry = {"name": "archer", "actions": ["shoot"], "directions": ["e"], "skeleton": ["shoot"], "holds": True}
        c, man, rot = self.character(s, entry, clips)
        got = durations_of(c.export(clips, rot)[0])["shoot_e"]
        want = [1.0] * 8
        want[3], want[5] = animpolish.HOLDS["shoot"]   # the aim before the shot held 3x, the recoil after it 1.5x
        self.assertEqual(got, want)
        row = next(r for r in man.data["assets"] if r.get("animation") == "shoot_e" and r["kind"] == "sheet")
        self.assertTrue(any("holds around the strike frame 4" in q for q in row["qa"]), row["qa"])
        # without the skeleton the same frames keep the measured peak (generated or hand-drawn clips)
        free = dict(entry, skeleton=[])
        c2, _, _ = self.character(s, free, clips)
        k = animpolish.peak(fr, False)
        self.assertEqual(durations_of(c2.export(clips, rot)[0])["shoot_e"],
                         animpolish.durations(8, k, True, "shoot", False)[0])
        # the frames SpriteKiln kept, when the render recorded them: a loop closing at control frame 31, and a
        # one-shot preset's six frames spread first to last
        loop8 = [0, 3, 7, 11, 15, 19, 23, 27]
        self.assertEqual([pose.strike_frame(a, 8, loop8) for a in ("attack", "cast", "shoot")], [3, 2, 4])
        self.assertEqual(pose.strike_frame("cast", 8, loop8, anticipation=1.0), 3)   # the deeper draw lands later
        self.assertEqual(pose.strike_frame("attack", 6, [0, 6, 12, 19, 25, 31]), 2)
        self.assertEqual(pose.strike_frame("attack", 6), 3)                          # without them: an even loop
        self.assertIsNone(pose.strike_frame("walk", 8))
        self.assertIsNone(pose.strike_frame("shoot", 2))
        # the render records them from the frame select's preview text (the graph and server are stand-ins)
        graph = {"2": {"class_type": "LoadImage", "inputs": {}}, "5": {"class_type": "SK_AnimationPreset", "inputs": {}},
                 "18": {"class_type": "CLIPTextEncode", "inputs": {}},
                 "24": {"class_type": "SK_FrameSelect", "inputs": {"frames": ["22", 0], "skip_start": 1}},
                 "29": {"class_type": "SK_Stabilize", "inputs": {"frames": ["28", 0], "anchor": "bottom_center"}}}
        info = "32 source frames, loop closes at frame 31 (diff 0.0012), picked [0, 3, 7, 11, 15, 19, 23, 27]"
        import lane_character as lc
        sprite = os.path.join(self.tmp, "a_e.png")
        chibi().save(sprite)
        clip = os.path.join(c.work, "clips", "shoot_e")
        with mock.patch.object(lc, "_wf", lambda name: json.loads(json.dumps(graph))), \
                mock.patch.object(lc.lib, "put", lambda img, name: (img.close(), name)[1]), \
                mock.patch.object(lc.lib, "missing_models", lambda names: []), \
                mock.patch.object(lc.lib, "run_job", lambda g, timeout=0: {"files": [], "seconds": 1.0,
                                                                            "texts": {"25": [info]}}), \
                mock.patch.object(lc, "COMFY_WORK", os.path.join(self.tmp, "comfy_work")), \
                mock.patch.object(lc.pose, "control_graph", lambda g, names, *a, **k: g), \
                mock.patch.object(lc.core, "free_models", lambda: None), \
                mock.patch.object(fcore, "ensure_comfy", lambda *a: None), \
                mock.patch.object(fcore, "require_ram", lambda *a, **k: None):
            c.render("shoot", "e", sprite, 4242, clip)
        with open(os.path.join(clip, "meta.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["frame_select"], {"picked": loop8, "skip": 1, "source": 33})
        # and the QA'd clip carries the strike to the holds; a trim that cuts it off falls back to the measured peak
        for i, im in enumerate(fr):
            im.save(os.path.join(clip, f"f_00001_{i:02d}.png"))
        c.frames("shoot", "e", rot)
        self.assertEqual(c.strikes[("shoot", "e")], 4)
        cut = lc.Character(dict(entry, clip_fix={"shoot_e": {"keep": 3}}), s.project, fcore.Manifest(s, "cut"), s.conf)
        cut.frames("shoot", "e", rot)
        self.assertIsNone(cut.strikes[("shoot", "e")])

    # ---- 5b. a still pose named like an action: the battle set's cast beside a cast clip facing the same way
    def test_pose_named_like_an_action(self):
        # it used to replace the clip: cast_w shipped as the one still frame, and with holds or smear the export
        # stopped on an IndexError (the 8-frame clip's strike frame looked up in the 1-frame still)
        import animpolish
        s = self.bind()
        fr = [knight(y) for y in (30, 28, 24, 18, 14, 22, 28, 30)]
        entry = {"name": "fencer", "asymmetric": True, "actions": ["cast"], "directions": ["w"], "skeleton": ["cast"],
                 "holds": True, "smear": True, "poses": {"cast": "thrusts the free hand forward"}, "pose_dirs": ["w"]}
        c, man, rot = self.character(s, entry, {("cast", "w"): (fr, [])})
        still = os.path.join(self.tmp, "still_cast_w.png")
        knight(30).save(still)

        def fake_frames(action, direction, rot_, clip_dir=None):
            c.strikes[(action, direction)] = 3                     # as frames() records a skeleton strike
            return list(fr), []
        c.south, c.rotate, c.clip, c.frames = (lambda: rot["w"]), (lambda south: rot), (lambda *a, **k: None), \
            fake_frames
        asked = []
        c.pose = lambda name, d, instr, sprite, shipped=None: (asked.append(shipped), still)[1]
        clips, _ = c.build()
        self.assertEqual(len(clips[("cast", "w")][0]), 8)          # the animation stays whole
        self.assertEqual(len(clips[("cast_pose", "w")][0]), 1)     # the still beside it
        self.assertEqual(asked, ["cast_pose"])                     # rendered under the name it ships as
        got = durations_of(c.export(clips, rot)[0])
        self.assertEqual(len(got["cast_w"]), 8)
        self.assertEqual(sorted(got["cast_w"])[-2:], sorted(animpolish.HOLDS["cast"]))   # held round the strike
        self.assertEqual(got["cast_pose_w"], [1.0])
        self.assertTrue(any("cast_pose_w" in a for a in man.data["assumptions"]), man.data["assumptions"])
        # a pose with its own name keeps it
        c2, _, _ = self.character(s, dict(entry, poses={"ready": "a fencing guard"}), {("cast", "w"): (fr, [])})
        c2.south, c2.rotate, c2.clip, c2.frames = c.south, c.rotate, c.clip, fake_frames
        c2.pose = c.pose
        self.assertIn(("ready", "w"), c2.build()[0])
        # the renamed still takes its own clip_fix entry: cast_pose_w retakes the pose, cast_w only the clip
        import lane_character as lc
        fixed = lc.Character(dict(entry, clip_fix={"cast_w": {"seed": 11}, "cast_pose_w": {"seed": 77}}), s.project,
                             man, s.conf)
        cached = os.path.join(fixed.work, "poses", "cast_w.png")
        os.makedirs(os.path.dirname(cached), exist_ok=True)
        knight(30).save(cached)
        with open(cached[:-4] + ".json", "w", encoding="utf-8") as f:
            json.dump({"instr": "thrusts the free hand forward", "seed": 77}, f)
        self.assertEqual(fixed.pose("cast", "w", "thrusts the free hand forward", still, "cast_pose"), cached)

    # ---- 6. the shaders: the hitfx flash reused byte for byte, the dissolve beside it, both well-formed
    def test_shader_files(self):
        import animpolish
        import godot
        import lane_hitfx
        s = self.bind()
        clips = {("attack", "e"): ([knight(y) for y in (30, 28, 24, 30)], [])}
        c, man, rot = self.character(s, {"name": "knight", "actions": ["attack"], "directions": ["e"],
                                         "shaders": True}, clips)
        c.build = lambda: (clips, rot)
        c.run()
        sh = os.path.join(s.project, "assets", "art", "fx", "shaders")
        names = sorted(os.listdir(sh))
        self.assertEqual(names, ["damage_flash.gdshader", "dissolve.gdshader", "mat_damage_flash.tres",
                                 "mat_dissolve.tres"])
        mine = {n: read(os.path.join(sh, n), "rb") for n in names}
        # the hitfx lane writes the same flash files: one flash shader in the game, whichever lane asked
        lane_hitfx.run([{"name": "flash", "kind": "flash"}], s.project, fcore.Manifest(s, "fx"), s.conf)
        for n in ("damage_flash.gdshader", "mat_damage_flash.tres"):
            self.assertEqual(read(os.path.join(sh, n), "rb"), mine[n], n)
        self.assertEqual(mine["damage_flash.gdshader"].decode("utf-8"), lane_hitfx.FLASH_SHADER)
        for stem in ("damage_flash", "dissolve"):
            code, mat = mine[f"{stem}.gdshader"].decode("utf-8"), mine[f"mat_{stem}.tres"].decode("utf-8")
            for text in (code, mat):
                self.assertNotIn("\r", text)
                self.assertNotIn("\u2014", text)
            self.assertTrue(code.startswith("shader_type canvas_item;\n"), stem)
            self.assertEqual(code.count("{"), code.count("}"), stem)
            self.assertEqual(code.count("("), code.count(")"), stem)
            self.assertIn("void fragment() {", code)
            uniforms = dict(re.findall(r"^uniform \w+ (\w+)(?: : [^=;]+)? = ([^;]+);$", code, re.M))
            params = dict(re.findall(r"^shader_parameter/(\w+) = (.+)$", mat, re.M))
            self.assertEqual(set(uniforms), set(params), stem)   # every parameter is a uniform, and the other way round
            for k, v in params.items():
                if not v.startswith("Color"):
                    self.assertAlmostEqual(float(v), float(uniforms[k]), msg=(stem, k))
            self.assertTrue(mat.startswith('[gd_resource type="ShaderMaterial" load_steps=2 format=3]\n'))
            self.assertIn(f'[ext_resource type="Shader" path="res://assets/art/fx/shaders/{stem}.gdshader" id="1_sh"]',
                          mat)
            self.assertIn('\n[resource]\nshader = ExtResource("1_sh")\n', mat)
        dis = mine["dissolve.gdshader"].decode("utf-8")
        self.assertEqual(sorted(re.findall(r"^uniform \w+ (\w+)", dis, re.M)),
                         ["edge_color", "edge_width", "noise_scale", "pixel_size", "progress", "seed"])
        self.assertIn("floor(UV / TEXTURE_PIXEL_SIZE)", dis)                 # the noise sits on whole texels
        self.assertIn("(texel + 0.5) * TEXTURE_PIXEL_SIZE", dis)             # texel centres: nearest, any filter
        self.assertIn("c.a = 0.0;", dis)                                     # hard cut, no partial alpha
        self.assertNotIn("smoothstep", dis)
        self.assertNotIn("texture(", dis.replace("texture(TEXTURE, (texel + 0.5)", ""))   # no noise texture
        kinds = {r["file"].rsplit("/", 1)[-1]: r["kind"] for r in man.data["assets"] if "/fx/shaders/" in r["file"]}
        self.assertEqual(kinds, {"damage_flash.gdshader": "shader", "dissolve.gdshader": "shader",
                                 "mat_damage_flash.tres": "material", "mat_dissolve.tres": "material"})
        # one kind only; and --engine none writes no Godot shader at all
        s2 = self.bind(os.path.join(self.tmp, "g2"))
        made = animpolish.write_shaders(s2.conf, fcore.Manifest(s2, "x"), ["dissolve"])
        self.assertEqual([os.path.basename(p) for p in made], ["dissolve.gdshader", "mat_dissolve.tres"])
        godot.ENABLED = False
        self.assertEqual(animpolish.write_shaders(s2.conf, fcore.Manifest(s2, "x"), ["flash", "dissolve"]), [])
        self.assertFalse(os.path.exists(os.path.join(s2.project, "assets", "art", "fx", "shaders",
                                                     "damage_flash.gdshader")))


if __name__ == "__main__":
    unittest.main(verbosity=1)
