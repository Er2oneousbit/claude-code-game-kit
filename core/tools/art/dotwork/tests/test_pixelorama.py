#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_pixelorama.py
# Purpose : offline exam for the hand-polish round trips: pixelorama.py (.pxo written and read in Python: one tag
#           per clip, frame durations from the holds, the asset's colours as the palette; an untouched re-export
#           gives every file back byte for byte, an edit reaches the game, layers composite, a refused feature stops
#           before anything is written, pxo_version 8 cels with their own size and offset) and aseprite.py's frame
#           times (holds in the build list, kept through a re-export that rounds to milliseconds), the
#           manifests (an untouched trip rewrites none, code-drawn effects keep their provenance, a clip added in the
#           editor takes only its sibling's provenance), the size limits (a project too large to hold is refused
#           before any image is read; a tag holds at most 100 frames in both editors), and building again in
#           either editor (a source that differs from the game's frames is kept; --overwrite keeps a .bak; an
#           Aseprite source is indexed only when that loses nothing). No Pixelorama, Aseprite, ComfyUI or Godot
#           needed: verify is stubbed, Aseprite's script runs are stubbed.
# Usage   : python tools/art/dotwork/tests/test_pixelorama.py   (test_dotwork.py runs it too)
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DOTWORK = os.path.dirname(HERE)
sys.path.insert(0, DOTWORK)
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import fcore  # noqa: E402

W, H = 24, 32
# anim: fps, loop, holds; walk_e first, as a lane may list its clips: the SpriteFrames order must survive the trip
CLIPS = {"walk_e": (12, True, None), "attack_e": (8, False, [1.0, 2.0, 1.0, 3.0])}   # 1/12 s: 83.3 ms
FX_FPS = 20                   # a hit effect's own speed (the config default is 12): it must survive the trip too   # anim: fps, loop, holds
INK = [(5, 4, 7), (60, 52, 70), (120, 104, 96), (182, 160, 128), (210, 150, 60), (150, 90, 40), (90, 130, 170),
       (170, 200, 220), (200, 60, 50), (240, 230, 200)]


def figure(rng):
    """A small sprite: clear background, a body of a few palette colours."""
    a = np.zeros((H, W, 4), np.uint8)
    y0, x0 = int(rng.integers(2, 8)), int(rng.integers(2, 8))
    for _ in range(14):
        y, x = y0 + int(rng.integers(0, 20)), x0 + int(rng.integers(0, 12))
        a[y:y + 3, x:x + 3] = INK[int(rng.integers(0, len(INK)))] + (255,)
    a[a[..., 3] == 0, :3] = (153, 145, 110)   # colour under clear pixels, as some code-drawn lanes leave it
    return a


def make_game(tmp):
    """A game holding what the character, effect and prop lanes write: frames, sheets (+ data with holds),
    SpriteFrames and manifest rows."""
    import godot
    os.makedirs(os.path.join(tmp, "art_src", "dotwork"), exist_ok=True)
    with open(os.path.join(tmp, "project.godot"), "w") as f:
        f.write("config_version=5\n")
    s = fcore.Settings(tmp)
    fcore.bind(s)
    godot.ENABLED = s.godot()
    conf, man, rng = s.conf, fcore.Manifest(s, "knights"), np.random.default_rng(7)
    out = fcore.art(conf, "characters", "knight")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/characters/knight'
    anims = {}
    for anim, (fps, loop, durs) in CLIPS.items():
        n = 4 if anim == "attack_e" else 3
        files, sheet = [], Image.new("RGBA", (W * n, H), (0, 0, 0, 0))
        for i in range(n):
            im = Image.fromarray(figure(rng))
            fn = f"spr_knight_{anim}_{i:02d}.png"
            fcore.save_clean(im, os.path.join(out, "frames", fn))
            files.append(fn)
            sheet.alpha_composite(im, (i * W, 0))
        anims[anim] = (files, fps, loop) if durs is None else (files, fps, loop, durs)
        sp = fcore.save_clean(sheet, os.path.join(out, f"knight_{anim}_sheet.png"))
        data = {"frame_w": W, "frame_h": H, "frames": n, "fps": fps, "loop": loop, "anchor": "bottom_center"}
        if durs is not None:
            data["durations"] = durs
        with open(sp[:-4] + ".json", "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        man.add(sp, "sheet", animation=anim, frames=n, fps=fps, loop=loop, canvas=[W, H], anchor="feet_bottom_center",
                qa=[], routes=("qwen_rotate", "wan"), durations=durs)
        man.add(sp[:-4] + ".json", "sheet_data", animation=anim)
        for fn in files:
            man.add(os.path.join(out, "frames", fn), "frame", animation=anim, canvas=[W, H],
                    anchor="feet_bottom_center", routes=("qwen_rotate", "wan"))
    tres = godot.sprite_frames(os.path.join(out, "knight_frames.tres"), res + "/frames", anims)
    man.add(tres, "sprite_frames", animations=sorted(anims), canvas=[W, H], anchor="feet_bottom_center",
            node="AnimatedSprite2D", offset=[0, -(H // 2)])
    fxo, files = fcore.art(conf, "fx", "spark"), []
    for i in range(3):
        fn = f"spr_fx_spark_{i:02d}.png"
        fcore.save_clean(Image.fromarray(figure(rng)), os.path.join(fxo, fn))
        man.add(os.path.join(fxo, fn), "fx_frame", routes=("klein", "wan"), blend="add")
        files.append(fn)
    t = godot.sprite_frames(os.path.join(fxo, "fx_spark_frames.tres"),
                            f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/fx/spark',
                            {"play": (files, FX_FPS, False)})
    man.add(t, "sprite_frames", animations=["play"])
    prop = fcore.save_clean(Image.fromarray(figure(rng)), fcore.art(conf, "props", "barrel.png"))
    man.add(prop, "prop", routes=("klein",))
    # the status, spell and talking-portrait lanes write sheet rows with no animation name (they crashed the
    # Aseprite round trip's grouping until this fix): they are not character clips and must be skipped
    mark = fcore.save_clean(Image.new("RGBA", (64, 16)), fcore.art(conf, "fx", "status", "poison", "status_poison_sheet.png"))
    man.add(mark, "sheet", frames=4, fps=8)
    # a spell frame (the spells lane's own folder and name, another size): not an effects-lane clip, never touched
    spell = fcore.save_clean(Image.new("RGBA", (40, 40), (90, 130, 170, 255)),
                             fcore.art(conf, "fx", "spells", "blast", "spr_spell_blast_00.png"))
    man.add(spell, "fx_frame", animation="blast", canvas=[40, 40], anchor="center", blend="add")
    # an older pack that wrote the same character: its manifest lists the same files, its attack sheet row is stale
    # (no holds, another hash). Each file must count once, and the row matching the file on disk must win.
    old = json.loads(json.dumps(man.data))
    old["pack"], old["assets"] = "knights_old", [r for r in old["assets"] if "/characters/knight/" in r["file"]]
    for r in old["assets"]:
        if r["file"].endswith("knight_attack_e_sheet.png"):
            r.update(durations=[1.0] * 4, sha256="0" * 64)
    with open(os.path.join(tmp, "assets_src", "dotwork", "manifest_knights_old.json"), "w", encoding="utf-8") as fh:
        json.dump(old, fh, indent=1)
    return s


def snapshot(tmp):
    """{path in the game: bytes} for everything the game ships under assets/, plus every Dotwork manifest (a round
    trip must not rewrite provenance it did not change)."""
    out = {}
    for p in (glob.glob(os.path.join(tmp, "assets", "**", "*"), recursive=True)
              + glob.glob(os.path.join(tmp, "assets_src", "dotwork", "manifest_*.json"))):
        if os.path.isfile(p):
            with open(p, "rb") as f:
                out[os.path.relpath(p, tmp).replace(os.sep, "/")] = f.read()
    return out


def changed(before, after):
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def rewrite_pxo(path, edit):
    """Open a .pxo, let edit(data, buffers) change data.json (a dict) and the cel buffers ({name: bytes}), write it
    back."""
    with zipfile.ZipFile(path) as z:
        data = json.loads(z.read("data.json"))
        bufs = {n: z.read(n) for n in z.namelist() if n != "data.json"}
    edit(data, bufs)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data.json", json.dumps(data))
        for n, b in bufs.items():
            z.writestr(n, b)


@contextlib.contextmanager
def stub_verify():
    import verify
    real, seen = verify.verify, {}

    def fake(settings, files):
        seen["files"] = files
        return {"ok": True}
    verify.verify = fake
    try:
        yield seen
    finally:
        verify.verify = real


class PixeloramaExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_pxo_")
        self.s = make_game(self.tmp)
        import pixelorama
        self.px = pixelorama
        self.src = os.path.join(self.tmp, "assets_src", "pixelorama")
        self.knight = os.path.join(self.src, "characters", "knight.pxo")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, **kw):
        return self.px.build(self.s.project, self.s.conf, **kw)

    def reexport(self):
        with stub_verify() as seen:
            r = self.px.reexport(self.s.project, self.s.conf)
        return r, seen

    def frame(self, anim, i):
        return np.array(Image.open(os.path.join(self.tmp, "assets", "art", "characters", "knight", "frames",
                                                f"spr_knight_{anim}_{i:02d}.png")).convert("RGBA"))

    def test_build_one_project_per_asset_tags_holds_palette(self):
        done = self.build()
        self.assertEqual(sorted(os.path.relpath(p, self.src).replace(os.sep, "/") for p in done["written"]),
                         ["characters/knight.pxo", "fx/spark.pxo", "single/barrel.pxo"])
        pj = self.px.read_pxo(self.knight)
        self.assertEqual(pj["tags"], [("attack_e", 0, 3), ("walk_e", 4, 6)])
        self.assertEqual(pj["fps"], 8.0)   # the rate most frames play at (4 attack frames at 8, 3 walk frames at 12)
        want = [h / 8 for h in CLIPS["attack_e"][2]] + [1 / 12] * 3
        for got, w in zip(pj["seconds"], want):
            self.assertAlmostEqual(got, w, places=6)
        order = [("attack_e", i) for i in range(4)] + [("walk_e", i) for i in range(3)]
        for got, (anim, i) in zip(pj["frames"], order):
            self.assertTrue(np.array_equal(got, self.frame(anim, i)), f"{anim} {i}")
        with zipfile.ZipFile(self.knight) as z:
            data = json.loads(z.read("data.json"))
            self.assertEqual(z.read("mimetype"), b"application/x-pixelorama")
            self.assertTrue(z.read("preview.png").startswith(b"\x89PNG"))
        self.assertEqual(data["pxo_version"], 7)
        self.assertEqual(data["layers"][0]["new_cels_linked"], False)   # PixelLayer.deserialize reads it directly
        pal = json.loads(list(data["palettes"][0].values())[0])
        used = {tuple(c) for f in pj["frames"] for c in f[f[..., 3] == 255][:, :3].tolist()}
        self.assertEqual(len(pal["colors"]), len(used))
        self.assertEqual(data["project_current_palette_name"], "knight (Dotwork)")
        self.assertEqual(self.px.read_pxo(os.path.join(self.src, "single", "barrel.pxo"))["tags"], [])
        spark = self.px.read_pxo(os.path.join(self.src, "fx", "spark.pxo"))
        self.assertEqual((spark["fps"], spark["tags"]), (float(FX_FPS), [("play", 0, 2)]))

    def test_build_is_deterministic_and_keeps_polish(self):
        self.build()
        with open(self.knight, "rb") as f:
            first = f.read()
        self.assertEqual([os.path.basename(p) for p in self.build()["unchanged"]],
                         ["knight.pxo", "spark.pxo", "barrel.pxo"])
        rewrite_pxo(self.knight, lambda d, b: d["frames"][0].update(duration=5.0))
        with open(self.knight, "rb") as f:
            polished = f.read()
        done = self.build()
        self.assertEqual([os.path.basename(p) for p in done["kept"]], ["knight.pxo"])
        with open(self.knight, "rb") as f:
            self.assertEqual(f.read(), polished)                    # hand polish is never overwritten by default
        self.build(overwrite=True)
        with open(self.knight, "rb") as f:
            self.assertEqual(f.read(), first)

    def test_overwrite_keeps_the_replaced_file(self):
        self.build()
        with open(self.knight, "rb") as f:
            first = f.read()
        rewrite_pxo(self.knight, lambda d, b: d["frames"][0].update(duration=5.0))
        with open(self.knight, "rb") as f:
            polished = f.read()
        done = self.build(overwrite=True)
        self.assertEqual(done["backups"], [self.knight + ".bak"])
        with open(self.knight + ".bak", "rb") as f:
            self.assertEqual(f.read(), polished)                    # the polish it replaced is still there
        with open(self.knight, "rb") as f:
            self.assertEqual(f.read(), first)
        self.assertEqual(self.build(overwrite=True)["backups"], [])  # nothing replaced: the .bak stays as it was
        with open(self.knight + ".bak", "rb") as f:
            self.assertEqual(f.read(), polished)
        rewrite_pxo(self.knight, lambda d, b: d["frames"][1].update(duration=4.0))
        code = subprocess.run([sys.executable, os.path.join(DOTWORK, "dotwork.py"), "pixelorama", "--overwrite",
                               "--project", self.tmp], capture_output=True, text=True, timeout=120)
        self.assertEqual(code.returncode, 0, code.stdout + code.stderr)
        self.assertIn("the old file is kept as knight.pxo.bak", code.stdout)

    def test_a_new_clip_takes_only_provenance(self):
        # the review's case (2026-11-01): a tag added in the editor, on a character whose first sheet row is the
        # attack. The new clip's rows took the attack's holds [1, 2, 1, 3] and qa, so the next build timed the
        # 2-frame clip by them and the re-export after it wrote them into the SpriteFrames and the sheet data.
        k = "assets/art/characters/knight/"
        for m in ("knights", "knights_old"):
            mp = os.path.join(self.tmp, "assets_src", "dotwork", f"manifest_{m}.json")
            with open(mp, encoding="utf-8") as f:
                man = json.load(f)
            attack = next(r for r in man["assets"] if r["file"] == k + "knight_attack_e_sheet.png")
            man["assets"].remove(attack)
            man["assets"].insert(0, attack)                         # the sheet row a new clip finds first
            for r in man["assets"]:
                if r["file"].startswith(k):
                    r.update(models=["knight_model.safetensors"], workflow="knight clips", request="a knight", seed=7,
                             prompt="a knight, side view")
            with open(mp, "w", encoding="utf-8") as f:
                json.dump(man, f, indent=1)
        self.build()

        def edit(d, b):                                           # a 2-frame clip idle_e after the others
            n = len(d["frames"])
            for j in range(2):
                d["frames"].append({"cels": [{"opacity": 1.0, "z_index": 0}], "duration": 1.0})
                a = np.frombuffer(b["image_data/frames/5/layer_1"], np.uint8).reshape(H, W, 4).copy()
                a[0, j] = (200, 60, 50, 255)
                b[f"image_data/frames/{n + j + 1}/layer_1"] = a.tobytes()
            d["tags"].append({"name": "idle_e", "color": "c38ce1ff", "from": n + 1, "to": n + 2})
        rewrite_pxo(self.knight, edit)
        self.reexport()

        def rows():
            return {r["file"]: r for rs in manifest_rows(self.tmp).values() for r in rs}
        got = rows()
        for f in (k + "knight_idle_e_sheet.png", k + "frames/spr_knight_idle_e_00.png",
                  k + "frames/spr_knight_idle_e_01.png"):
            for key in ("durations", "qa", "request", "seed", "prompt"):
                self.assertNotIn(key, got[f], f"{f} {key}")
            self.assertEqual((got[f]["models"], got[f]["workflow"]), (["knight_model.safetensors"], "knight clips"), f)
            self.assertEqual(got[f]["note"], "hand-polished in Pixelorama")
        self.assertEqual(got[k + "knight_idle_e_sheet.png"]["frames"], 2)
        sheet_json = os.path.join(self.tmp, k, "knight_idle_e_sheet.json")
        with open(sheet_json, encoding="utf-8") as f:
            self.assertNotIn("durations", json.load(f))
        # the next build and re-export: the clip still plays one frame per tick
        self.build(overwrite=True)
        pj = self.px.read_pxo(self.knight)
        first = next(a for n, a, _ in pj["tags"] if n == "idle_e")
        self.assertEqual(pj["seconds"][first:first + 2], [1 / 8, 1 / 8])
        self.reexport()
        self.assertNotIn("durations", rows()[k + "knight_idle_e_sheet.png"])
        with open(sheet_json, encoding="utf-8") as f:
            self.assertNotIn("durations", json.load(f))

    def test_untouched_reexport_is_byte_identical(self):
        before = snapshot(self.tmp)
        self.build()
        r, seen = self.reexport()
        self.assertTrue(r["ok"])
        self.assertEqual(changed(before, snapshot(self.tmp)), [])   # every PNG, sheet, sheet data and .tres
        self.assertIn("assets/art/characters/knight/knight_frames.tres", seen["files"])

    def test_clear_pixels_zeroed_by_the_editor_change_nothing(self):
        # Pixelorama's export and save write 0, 0, 0, 0 under fully clear pixels; the shipped files must stay
        before = snapshot(self.tmp)
        self.build()

        def edit(d, b):
            for n in list(b):
                if n.startswith("image_data/frames/"):
                    a = np.frombuffer(b[n], np.uint8).reshape(H, W, 4).copy()
                    a[a[..., 3] == 0] = 0
                    b[n] = a.tobytes()
        rewrite_pxo(self.knight, edit)
        self.reexport()
        self.assertEqual(changed(before, snapshot(self.tmp)), [])

    def test_edit_and_new_hold_reach_the_game(self):
        before = snapshot(self.tmp)
        self.build()

        def edit(d, b):
            name = "image_data/frames/2/layer_1"                    # attack_e frame 1
            a = np.frombuffer(b[name], np.uint8).reshape(H, W, 4).copy()
            a[0, 0] = (200, 60, 50, 255)
            b[name] = a.tobytes()
            d["frames"][4]["duration"] = 2.0 * 8 / 12                # walk_e frame 0 held twice as long
        rewrite_pxo(self.knight, edit)
        self.reexport()
        diff = changed(before, snapshot(self.tmp))
        k = "assets/art/characters/knight/"
        self.assertEqual(diff, [k + "frames/spr_knight_attack_e_01.png", k + "knight_attack_e_sheet.png",
                                k + "knight_frames.tres", k + "knight_walk_e_sheet.json",
                                "assets_src/dotwork/manifest_knights.json", "assets_src/dotwork/manifest_knights_old.json"])
        rows = {}
        for m in ("knights", "knights_old"):
            with open(os.path.join(self.tmp, "assets_src", "dotwork", f"manifest_{m}.json"), encoding="utf-8") as f:
                rows[m] = {r["file"]: r for r in json.load(f)["assets"]}
        frame = rows["knights"][k + "frames/spr_knight_attack_e_01.png"]
        was = {r["file"]: r for r in json.loads(before["assets_src/dotwork/manifest_knights.json"])["assets"]}
        self.assertEqual(frame["note"], "hand-polished in Pixelorama")
        self.assertEqual({x: v for x, v in frame.items() if x not in ("sha256", "note")},   # provenance kept
                         {x: v for x, v in was[frame["file"]].items() if x not in ("sha256", "note")})
        sheet = rows["knights_old"][k + "knight_attack_e_sheet.png"]
        self.assertEqual(sheet["durations"], [1.0, 2.0, 1.0, 3.0])          # the stale pack's row is corrected too
        self.assertEqual(sheet["sha256"], rows["knights"][k + "knight_attack_e_sheet.png"]["sha256"])
        self.assertEqual(tuple(self.frame("attack_e", 1)[0, 0]), (200, 60, 50, 255))
        with open(os.path.join(self.tmp, k, "knight_walk_e_sheet.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["durations"], [2.0, 1.0, 1.0])
        with open(os.path.join(self.tmp, k, "knight_frames.tres"), encoding="utf-8") as f:
            tres = f.read()
        self.assertIn('"duration": 2.0', tres)
        self.assertIn('"duration": 3.0', tres)                       # the attack's own holds are still there

    def test_layers_composite_hidden_ignored(self):
        self.build()

        def edit(d, b):
            d["layers"].append({"name": "hidden", "visible": False, "blend_mode": 3, "opacity": 1.0, "parent": -1,
                                "type": 0, "new_cels_linked": False})
            d["layers"].append({"name": "glaze", "visible": True, "blend_mode": 0, "opacity": 0.5, "parent": -1,
                                "type": 0, "new_cels_linked": False})
            for fi, fr in enumerate(d["frames"]):
                fr["cels"] += [{"opacity": 1.0, "z_index": 0}, {"opacity": 1.0, "z_index": 0}]
                junk = np.full((H, W, 4), 255, np.uint8)
                glaze = np.zeros((H, W, 4), np.uint8)
                glaze[1, 1] = (255, 255, 255, 255)
                b[f"image_data/frames/{fi + 1}/layer_2"] = junk.tobytes()
                b[f"image_data/frames/{fi + 1}/layer_3"] = glaze.tobytes()
        rewrite_pxo(self.knight, edit)
        base = self.frame("walk_e", 2)
        pj = self.px.read_pxo(self.knight)
        got = pj["frames"][6]
        mask = np.ones((H, W), bool)
        mask[1, 1] = False
        self.assertTrue(np.array_equal(got[mask], base[mask]))     # the hidden white layer never shows
        a0 = base[1, 1, 3] / 255.0
        ra = 0.5 + a0 * 0.5
        want_rgb = (255 * 0.5 + base[1, 1, :3] * a0 * 0.5) / ra
        self.assertEqual(tuple(got[1, 1]), tuple(int(v) for v in np.rint(list(want_rgb) + [ra * 255])))

    def test_refused_features_stop_before_writing(self):
        self.build()
        before = snapshot(self.tmp)
        with open(self.knight, "rb") as f:
            clean = f.read()

        def layer(**kw):
            return lambda d, b: d["layers"][0].update(**kw)
        cases = {
            "blend mode": layer(blend_mode=3),
            "clipping mask": layer(clipping_mask=True),
            "3D layer": layer(type=2),
            "tilemap layer": layer(type=3),
            "layer effect": layer(effects=[{"name": "Outline", "enabled": True}]),
            "animated opacity": layer(animated_params='Dictionary[String, Dictionary]({\n"opacity": {3: 0.5}\n})'),
            "newer pxo": lambda d, b: d.update(pxo_version=9),
            "older pxo": lambda d, b: d.update(pxo_version=5),
            "short buffer": lambda d, b: b.update({"image_data/frames/1/layer_1": b"\0" * 10}),
            "missing buffer": lambda d, b: b.pop("image_data/frames/3/layer_1"),
            "bad tag": lambda d, b: d["tags"][0].update(name="../escape"),
            "tag past the end": lambda d, b: d["tags"][1].update(to=99),
            "zero duration": lambda d, b: d["frames"][0].update(duration=0),
            "huge canvas": lambda d, b: d.update(size_x=100000),
            "parent loop": lambda d, b: d["layers"].__setitem__(0, dict(d["layers"][0], parent=0)),
            "tag over 100 frames": lambda d, b: (
                [d["frames"].append(dict(d["frames"][0])) or b.update({
                    f"image_data/frames/{len(d['frames'])}/layer_1": b["image_data/frames/1/layer_1"]})
                 for _ in range(101 - len(d["frames"]))], d["tags"][0].update({"from": 1, "to": 101})),
        }
        for what, edit in cases.items():
            with open(self.knight, "wb") as f:
                f.write(clean)
            rewrite_pxo(self.knight, edit)
            with self.assertRaises(fcore.ToolError, msg=what):
                self.reexport()
            self.assertEqual(changed(before, snapshot(self.tmp)), [], what)
        with open(self.knight, "wb") as f:
            f.write(b"not a zip")
        with self.assertRaises(fcore.ToolError):
            self.reexport()

    def test_size_is_checked_before_any_image_is_read(self):
        # the review's case (2026-11-01): the limits were per cel, so a small file could declare frames that take
        # gigabytes to hold. data.json alone decides, and a refused project has no buffer read.
        self.build()
        with open(self.knight, "rb") as f:
            clean = f.read()
        reads, real = [], self.px._buffer

        def counting(z, name, w, h, rel):
            reads.append(name)
            return real(z, name, w, h, rel)

        def frames_of(n):
            return lambda d: d["frames"].extend(json.loads(json.dumps(d["frames"][0])) for _ in range(n - 7))

        def layers(n, visible):
            def add(d):
                for _ in range(n):
                    d["layers"].append(dict(d["layers"][0], name="more", visible=visible))
                    for fr in d["frames"]:
                        fr["cels"].append({"opacity": 1.0, "z_index": 0})
            return add

        def v8_cels(d):
            d["pxo_version"] = 8
            for fr in d["frames"]:
                fr["cels"][0].update(image_size="Vector2i(8192, 8192)", offset="(0, 0)")
        cases = {   # what: (edit of data.json, what the refusal says)
            "200 frames of 8192x8192": (lambda d: (d.update(size_x=8192, size_y=8192), frames_of(200)(d)), "to hold"),
            "300 layers": (layers(299, False), "layers"),
            "3 visible layers of 4096x4096": (lambda d: (d.update(size_x=4096, size_y=4096), layers(2, True)(d)),
                                              "unpack"),
            "v8 cels of 8192x8192": (v8_cels, "unpack"),
            "5000 tags": (lambda d: d["tags"].extend(dict(d["tags"][0], name=f"t{i}") for i in range(5000)), "tags"),
        }
        self.px._buffer = counting
        try:
            for what, (edit, says) in cases.items():
                with open(self.knight, "wb") as f:
                    f.write(clean)
                rewrite_pxo(self.knight, lambda d, b: edit(d))
                with self.assertRaisesRegex(fcore.ToolError, says, msg=what):
                    self.px.read_pxo(self.knight)
                self.assertEqual(reads, [], what)
        finally:
            self.px._buffer = real

    def test_a_reexport_writes_no_more_than_the_budget(self):
        # overlapping tags can name one frame many times: what a re-export writes is held to the same budget
        self.build()
        before = snapshot(self.tmp)
        rewrite_pxo(self.knight, lambda d, b: d["tags"].append(dict(d["tags"][1], name="walk_e_again")))
        real = self.px.MAX_DECODED
        self.px.MAX_DECODED = 7 * W * H * 4                          # the knight's own 7 frames, exactly
        try:
            self.assertEqual(len(self.px.read_pxo(self.knight)["frames"]), 7)
            with self.assertRaisesRegex(fcore.ToolError, "to write"):
                self.reexport()
        finally:
            self.px.MAX_DECODED = real
        self.assertEqual(changed(before, snapshot(self.tmp)), [])

    def test_banded_blending_is_the_same(self):
        self.build()
        rng = np.random.default_rng(3)

        def edit(d, b):
            d["layers"].append({"name": "glaze", "visible": True, "blend_mode": 0, "opacity": 0.6, "parent": -1,
                                "type": 0, "new_cels_linked": False})
            for fi, fr in enumerate(d["frames"]):
                fr["cels"].append({"opacity": 0.7, "z_index": 0})
                b[f"image_data/frames/{fi + 1}/layer_2"] = rng.integers(0, 256, (H, W, 4), np.uint8).tobytes()
        rewrite_pxo(self.knight, edit)
        whole = self.px.read_pxo(self.knight)["frames"]
        real = self.px.BAND_PIXELS
        try:
            for band in (1, W * 5):                                   # one row at a time; 5 rows (a short last band)
                self.px.BAND_PIXELS = band
                for a, b in zip(whole, self.px.read_pxo(self.knight)["frames"]):
                    self.assertTrue(np.array_equal(a, b), band)
        finally:
            self.px.BAND_PIXELS = real

    def test_pxo_version_8_cels_with_size_and_offset(self):
        self.build()
        want = self.frame("attack_e", 0)

        def edit(d, b):
            d["pxo_version"] = 8
            ys, xs = np.nonzero(want[..., 3])
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            cel = d["frames"][0]["cels"][0]
            cel["image_size"] = "Vector2i(%d, %d)" % (x1 - x0, y1 - y0)   # var_to_str, as PixelCel.serialize writes
            cel["offset"] = "(%d, %d)" % (x0, y0)                         # JSON of a Vector2i
            b["image_data/frames/1/layer_1"] = np.ascontiguousarray(want[y0:y1, x0:x1]).tobytes()
            for fr in d["frames"][1:]:
                fr["cels"][0].update(image_size="Vector2i(%d, %d)" % (W, H), offset="(0, 0)")
        rewrite_pxo(self.knight, edit)
        got = self.px.read_pxo(self.knight)["frames"][0]
        self.assertTrue(np.array_equal(got[got[..., 3] > 0], want[want[..., 3] > 0]))
        self.assertTrue(np.array_equal(got[..., 3], want[..., 3]))

    def test_reads_the_fields_pixelorama_writes(self):
        # the shape of a project Pixelorama 1.2.3 saved (its autosave of a Dotwork file, 2026-11-01): extra fields,
        # Godot text values, empty animated parameters, indices buffers and folder entries
        self.build()

        def edit(d, b):
            d.update(pixelorama_version="v1.2.3-stable", brushes=[], guides=[], metadata={}, reference_images=[],
                     tilesets=[], vanishing_points=[], symmetry_points=[63.0, 63.0], next_keyframe_id=0,
                     export_profile={"directory_path": "\"/somewhere\"", "file_name": "\"knight\""})
            for ly in d["layers"]:
                ly.update(animated_params='Dictionary[String, Dictionary]({\n"opacity": {}\n})', effects=[],
                          metadata={}, ui_color="(0.0, 0.0, 0.0, 0.0)")
            for fi, fr in enumerate(d["frames"]):
                fr["metadata"] = {}
                for c in fr["cels"]:
                    c.update(metadata={}, ui_color="(0.0, 0.0, 0.0, 0.0)")
                b[f"image_data/frames/{fi + 1}/indices_layer_1"] = b"\0"
                b[f"image_data/frames/{fi + 1}/"] = b""
        rewrite_pxo(self.knight, edit)
        before = snapshot(self.tmp)
        self.reexport()
        self.assertEqual(changed(before, snapshot(self.tmp)), [])

    def test_cli_build(self):
        code = subprocess.run([sys.executable, os.path.join(DOTWORK, "dotwork.py"), "pixelorama", "--project",
                               self.tmp], capture_output=True, text=True, timeout=120)
        self.assertEqual(code.returncode, 0, code.stdout + code.stderr)
        self.assertIn("3 .pxo files written", code.stdout)
        code = subprocess.run([sys.executable, os.path.join(DOTWORK, "dotwork.py"), "--help"], capture_output=True,
                              text=True, timeout=120)
        self.assertIn("pixelorama", code.stdout)


def manifest_rows(tmp):
    out = {}
    for p in sorted(glob.glob(os.path.join(tmp, "assets_src", "dotwork", "manifest_*.json"))):
        with open(p, encoding="utf-8") as f:
            out[os.path.basename(p)] = json.load(f)["assets"]
    return out


class CodeDrawnEffectExam(unittest.TestCase):
    """The kit's review case (2026-11-01): the hit effects of examples/ui.json are drawn in code, so their manifest
    rows carry no model and name their workflow, canvas and anchor. An untouched round trip, with either editor, must
    leave every manifest byte for byte; an edited frame keeps its row's provenance and only gains a new sha256 and the
    polish note."""

    def setUp(self):
        import godot
        self.tmp = tempfile.mkdtemp(prefix="dotwork_hitfx_")
        os.makedirs(os.path.join(self.tmp, "art_src", "dotwork"), exist_ok=True)
        with open(os.path.join(self.tmp, "project.godot"), "w") as f:
            f.write("config_version=5\n")
        with open(os.path.join(DOTWORK, "examples", "ui.json"), encoding="utf-8") as f:
            hitfx = json.load(f)["hitfx"]
        spec = os.path.join(self.tmp, "hitfx.json")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"name": "ui", "hitfx": hitfx}, f)
        r = subprocess.run([sys.executable, os.path.join(DOTWORK, "dotwork.py"), "pack", "--spec", spec, "--project",
                            self.tmp, "--no-verify"], capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.s = fcore.Settings(self.tmp)
        fcore.bind(self.s)
        godot.ENABLED = self.s.godot()
        import aseprite
        import pixelorama
        self.ase, self.px = aseprite, pixelorama
        self.real_run, self.env = aseprite._run, os.environ.get("ASEPRITE_BIN")
        os.environ["ASEPRITE_BIN"] = sys.executable          # any file that exists: _run is stubbed

    def tearDown(self):
        self.ase._run = self.real_run
        if self.env is None:
            os.environ.pop("ASEPRITE_BIN", None)
        else:
            os.environ["ASEPRITE_BIN"] = self.env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_aseprite(self):
        """EXPORT_LUA's stand-in: each effect's shipped frames, timed in whole milliseconds at its own speed."""
        import handpolish
        game = os.path.join(self.tmp, "assets", "art", "fx")

        def run(conf, lua, name, params):
            if "list" in params:                              # BUILD_LUA: nothing to write for the stand-in
                open(params["out"], "wb").close()
                return "DOTWORK_ASE_OK"
            prefix = params["prefix"]
            fx = os.path.basename(prefix)[len("spr_fx_"):]
            speed = handpolish.tres_animations(os.path.join(game, fx, f"fx_{fx}_frames.tres"))[0][1]
            lines = []
            for k, p in enumerate(sorted(glob.glob(os.path.join(game, fx, f"spr_fx_{fx}_*.png")))):
                shutil.copyfile(p, f"{prefix}_play_{k:02d}.png")
                lines.append(f"DOTWORK_ASE_PNG {int(1000 / speed) / 1000:.6f} {prefix}_play_{k:02d}.png")
            return "\n".join(lines)
        return run

    def test_the_rows_are_code_drawn(self):
        rows = [r for rows in manifest_rows(self.tmp).values() for r in rows if r["kind"] == "fx_frame"]
        self.assertTrue(rows)
        self.assertTrue(all(r["models"] == [] and "drawn in code" in r.get("workflow", "") for r in rows))

    def test_untouched_round_trips_change_no_manifest(self):
        before = snapshot(self.tmp)
        done = self.px.build(self.s.project, self.s.conf)
        self.assertEqual(sorted(os.path.basename(p) for p in done["written"]), ["hit_spark.pxo", "slash.pxo"])
        with stub_verify():
            self.px.reexport(self.s.project, self.s.conf)
        self.assertEqual(changed(before, snapshot(self.tmp)), [], "Pixelorama")
        self.ase._run = self.fake_aseprite()
        self.ase.build(self.s.project, self.s.conf)
        with stub_verify():
            self.ase.reexport(self.s.project, self.s.conf)
        self.assertEqual(changed(before, snapshot(self.tmp)), [], "Aseprite")

    def test_an_edited_frame_keeps_its_provenance(self):
        before = manifest_rows(self.tmp)
        self.px.build(self.s.project, self.s.conf)
        pxo = os.path.join(self.tmp, "assets_src", "pixelorama", "fx", "hit_spark.pxo")

        def edit(d, b):
            w, h = d["size_x"], d["size_y"]
            a = np.frombuffer(b["image_data/frames/1/layer_1"], np.uint8).reshape(h, w, 4).copy()
            a[h // 2, w // 2] = (200, 60, 50, 255)
            b["image_data/frames/1/layer_1"] = a.tobytes()
        rewrite_pxo(pxo, edit)
        with stub_verify():
            self.px.reexport(self.s.project, self.s.conf)
        after = manifest_rows(self.tmp)
        self.assertEqual(list(after), list(before))
        for man in before:
            self.assertEqual([r["file"] for r in after[man]], [r["file"] for r in before[man]], "row order")
            for old, new in zip(before[man], after[man]):
                if old["file"].endswith("spr_fx_hit_spark_00.png"):
                    self.assertNotEqual(new["sha256"], old["sha256"])
                    self.assertEqual(new["note"], "hand-polished in Pixelorama")
                    self.assertEqual({k: v for k, v in new.items() if k not in ("sha256", "note")},
                                     {k: v for k, v in old.items() if k not in ("sha256", "note")})
                    self.assertEqual(new["models"], [])
                    self.assertIn("drawn in code", new["workflow"])
                else:
                    self.assertEqual(new, old, old["file"])


class AsepriteHoldsExam(unittest.TestCase):
    """aseprite.py's frame times, with Aseprite's script runs stubbed (the Lua itself needs Aseprite)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_ase_")
        self.s = make_game(self.tmp)
        import aseprite
        self.ase = aseprite
        self.real_run = aseprite._run
        self.env = os.environ.get("ASEPRITE_BIN")
        os.environ["ASEPRITE_BIN"] = sys.executable          # any file that exists: _run is stubbed

    def tearDown(self):
        self.ase._run = self.real_run
        if self.env is None:
            os.environ.pop("ASEPRITE_BIN", None)
        else:
            os.environ["ASEPRITE_BIN"] = self.env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_build_list_times_each_frame_by_its_hold(self):
        lists = {}

        def run(conf, lua, name, params):
            if "list" in params:
                with open(params["list"], encoding="utf-8") as f:
                    lists[os.path.basename(params["out"])] = [ln.split("|")[:2] for ln in f.read().split("\n") if ln]
            return "DOTWORK_ASE_OK"
        self.ase._run = run
        self.ase.build(self.s.project, self.s.conf)
        self.assertEqual(lists["knight.aseprite"],
                         [["attack_e", "0.1250"], ["attack_e", "0.2500"], ["attack_e", "0.1250"], ["attack_e", "0.3750"],
                          ["walk_e", "0.0833"], ["walk_e", "0.0833"], ["walk_e", "0.0833"]])

    def fake_export(self, edit=None):
        """A stand-in for EXPORT_LUA: the game's frames as Aseprite would export them, frame times in whole
        milliseconds (truncated) as Aseprite keeps them."""
        game = os.path.join(self.tmp, "assets", "art")
        holds = {a: (CLIPS[a][2] or [1.0] * 3, CLIPS[a][0]) for a in CLIPS}

        def run(conf, lua, name, params):
            prefix, lines = params["prefix"], []
            base = os.path.basename(prefix)
            if base == "spr_knight":
                for p in sorted(glob.glob(os.path.join(game, "characters", "knight", "frames", "*.png"))):
                    fn = os.path.basename(p)
                    anim, i = fn[len("spr_knight_"):-7], int(fn[-6:-4])
                    h, fps = holds[anim]
                    ms = int(h[i] / fps * 1000)
                    if edit and fn in edit:
                        ms = edit[fn]
                    shutil.copyfile(p, os.path.join(os.path.dirname(prefix), fn))
                    lines.append(f"DOTWORK_ASE_PNG {ms / 1000:.6f} {os.path.dirname(prefix)}/{fn}")
            elif base == "spr_fx_spark":
                for k, p in enumerate(sorted(glob.glob(os.path.join(game, "fx", "spark", "*.png")))):
                    shutil.copyfile(p, f"{prefix}_play_{k:02d}.png")
                    lines.append(f"DOTWORK_ASE_PNG {int(1000 / FX_FPS) / 1000:.6f} {prefix}_play_{k:02d}.png")
            else:
                shutil.copyfile(os.path.join(game, "props", "barrel.png"), prefix + ".png")
                lines.append(f"DOTWORK_ASE_PNG 0.100000 {prefix}.png")
            return "\n".join(lines)
        return run

    def sources(self):
        src = os.path.join(self.tmp, "assets_src", "aseprite")
        for rel in ("characters/knight.aseprite", "fx/spark.aseprite", "single/barrel.aseprite"):
            os.makedirs(os.path.dirname(os.path.join(src, rel)), exist_ok=True)
            open(os.path.join(src, rel), "wb").close()

    def test_untouched_reexport_keeps_holds_byte_for_byte(self):
        self.sources()
        before = snapshot(self.tmp)
        self.ase._run = self.fake_export()
        with stub_verify():
            self.ase.reexport(self.s.project, self.s.conf)
        self.assertEqual(changed(before, snapshot(self.tmp)), [])

    def test_a_retimed_frame_becomes_a_hold(self):
        self.sources()
        self.ase._run = self.fake_export(edit={"spr_knight_walk_e_02.png": 250})   # 0.25 s at 12 fps = 3.0
        with stub_verify():
            self.ase.reexport(self.s.project, self.s.conf)
        with open(os.path.join(self.tmp, "assets", "art", "characters", "knight", "knight_walk_e_sheet.json")) as f:
            self.assertEqual(json.load(f)["durations"], [1.0, 1.0, 3.0])

    def test_a_tag_name_that_leaves_the_folder_stops(self):
        self.sources()
        self.ase._run = lambda conf, lua, name, params: "DOTWORK_ASE_BADTAG ../escape"
        with stub_verify(), self.assertRaises(fcore.ToolError):
            self.ase.reexport(self.s.project, self.s.conf)

    def test_a_tag_over_100_frames_stops(self):
        # the review's case (2026-11-01): EXPORT_LUA names frame 100 of a tag _100.png, which the re-export read as
        # an animation "walk_e_" with its own sheet
        self.sources()
        before = snapshot(self.tmp)
        frame0 = os.path.join(self.tmp, "assets", "art", "characters", "knight", "frames", "spr_knight_walk_e_00.png")

        def run(conf, lua, name, params):
            lines = []
            for k in range(101):
                p = "%s_walk_e_%02d.png" % (params["prefix"], k)
                shutil.copyfile(frame0, p)
                lines.append(f"DOTWORK_ASE_PNG 0.083000 {p}")
            return "\n".join(lines)
        self.ase._run = run
        with stub_verify(), self.assertRaisesRegex(fcore.ToolError, "walk_e has 101 frames"):
            self.ase.reexport(self.s.project, self.s.conf)
        self.assertEqual(changed(before, snapshot(self.tmp)), [])

    def test_an_untagged_character_stops(self):
        self.sources()
        frame0 = os.path.join(self.tmp, "assets", "art", "characters", "knight", "frames", "spr_knight_walk_e_00.png")

        def run(conf, lua, name, params):                          # no tags: EXPORT_LUA writes <prefix>.png
            shutil.copyfile(frame0, params["prefix"] + ".png")
            return f"DOTWORK_ASE_PNG 0.100000 {params['prefix']}.png"
        self.ase._run = run
        with stub_verify(), self.assertRaisesRegex(fcore.ToolError, "in no tag"):
            self.ase.reexport(self.s.project, self.s.conf)


class AsepriteGuardExam(unittest.TestCase):
    """aseprite.py build keeps hand polish (issue #64: it rebuilt every source from the game's frames). An existing
    .aseprite is exported first: one that still shows the game's frames is left alone, one that differs is kept
    unless --overwrite, which keeps <name>.aseprite.bak. The stand-in Aseprite keeps a file as JSON (each frame's tag,
    time in whole milliseconds and pixels) and exports what it holds, as EXPORT_LUA does."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_aseguard_")
        self.s = make_game(self.tmp)
        import aseprite
        self.ase = aseprite
        self.real_run, self.env = aseprite._run, os.environ.get("ASEPRITE_BIN")
        os.environ["ASEPRITE_BIN"] = sys.executable          # any file that exists: _run is stubbed
        self.runs, self.built = [], []
        aseprite._run = self.fake
        self.src = os.path.join(self.tmp, "assets_src", "aseprite")
        self.knight = os.path.join(self.src, "characters", "knight.aseprite")
        self.others = [os.path.join(self.src, "fx", "spark.aseprite"),
                       os.path.join(self.src, "single", "barrel.aseprite")]

    def tearDown(self):
        self.ase._run = self.real_run
        if self.env is None:
            os.environ.pop("ASEPRITE_BIN", None)
        else:
            os.environ["ASEPRITE_BIN"] = self.env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake(self, conf, lua, name, params):
        self.runs.append(name)
        if name == "ase_build.lua":
            self.built.append(dict(params))
            frames = []
            with open(params["list"], encoding="utf-8") as f:
                for ln in f.read().splitlines():
                    tag, dur, png = ln.split("|", 2)
                    with Image.open(png) as im:
                        a = np.array(im.convert("RGBA"))
                    frames.append({"tag": tag, "ms": int(float(dur) * 1000), "size": [a.shape[1], a.shape[0]],
                                   "rgba": a.tobytes().hex()})
            with open(params["out"], "w", encoding="utf-8") as f:
                json.dump({"frames": frames}, f, sort_keys=True)
            return "DOTWORK_ASE_OK"
        with open(params["file"], encoding="utf-8") as f:
            data = json.load(f)
        if data.get("badtag"):
            return "DOTWORK_ASE_BADTAG " + data["badtag"]
        tags = []
        for fr in data["frames"]:
            if fr["tag"] and fr["tag"] not in tags:
                tags.append(fr["tag"])
        lines, todo = [], ([(params["prefix"] + ".png", data["frames"][0])] if not tags else
                           [("%s_%s_%02d.png" % (params["prefix"], t, k), fr) for t in tags
                            for k, fr in enumerate(x for x in data["frames"] if x["tag"] == t)])
        for path, fr in todo:
            w, h = fr["size"]
            a = np.frombuffer(bytes.fromhex(fr["rgba"]), np.uint8).reshape(h, w, 4).copy()
            Image.fromarray(a, "RGBA").save(path)
            lines.append(f"DOTWORK_ASE_PNG {fr['ms'] / 1000:.6f} {path}")
        return "\n".join(lines)

    def build(self, **kw):
        return self.ase.build(self.s.project, self.s.conf, **kw)

    def polish(self, path, change):
        """Change the stand-in file as a hand edit in Aseprite would."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        change(data)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, sort_keys=True)
        with open(path, "rb") as f:
            return f.read()

    @staticmethod
    def read(path):
        with open(path, "rb") as f:
            return f.read()

    def test_a_second_build_leaves_every_source_alone(self):
        first = self.build()
        before = {p: self.read(p) for p in [self.knight] + self.others}
        self.runs.clear()
        done = self.build()
        # the knight's walk frames show 1/12 s in the game and 83 ms in Aseprite: within HOLD_TOLERANCE_S, the same
        self.assertNotIn("ase_build.lua", self.runs)               # compared by exporting, never rebuilt
        self.assertEqual({p: self.read(p) for p in before}, before)
        self.assertEqual(sorted(first["written"]), sorted(before))
        self.assertEqual((done["written"], done["kept"], done["backups"]), ([], [], []))
        self.assertEqual(sorted(done["unchanged"]), sorted(before))

    def test_polish_is_kept_and_overwrite_keeps_a_bak(self):
        self.build()
        first = self.read(self.knight)
        others = {p: self.read(p) for p in self.others}

        def pixel(data):
            fr = data["frames"][1]
            w, h = fr["size"]
            a = np.frombuffer(bytes.fromhex(fr["rgba"]), np.uint8).reshape(h, w, 4).copy()
            a[0, 0] = (200, 60, 50, 255)
            fr["rgba"] = a.tobytes().hex()
        polished = self.polish(self.knight, pixel)
        done = self.build()
        self.assertEqual(self.read(self.knight), polished)        # issue #64: this was rebuilt from the game's frames
        self.assertEqual((done["kept"], done["written"], done["backups"]), ([self.knight], [], []))
        self.assertFalse(os.path.exists(self.knight + ".bak"))
        done = self.build(overwrite=True)
        self.assertEqual((done["written"], done["backups"]), ([self.knight], [self.knight + ".bak"]))
        self.assertEqual(self.read(self.knight + ".bak"), polished)
        self.assertEqual(self.read(self.knight), first)
        self.assertEqual({p: self.read(p) for p in self.others}, others)
        self.assertFalse(any(os.path.exists(p + ".bak") for p in self.others))
        done = self.build(overwrite=True)                           # nothing differs now: nothing replaced
        self.assertEqual((done["written"], done["backups"]), ([], []))
        self.assertEqual(self.read(self.knight + ".bak"), polished)

    def test_every_kind_of_change_counts_as_polish(self):
        self.build()
        clean = self.read(self.knight)

        def retime(data):
            data["frames"][4]["ms"] += 50                               # walk_e 0: 83 ms -> 133 ms
        cases = {
            "a retimed frame": retime,
            "a frame added to a tag": lambda d: d["frames"].insert(4, dict(d["frames"][3])),
            "a frame removed": lambda d: d["frames"].pop(),
            "a new tag": lambda d: d["frames"].append(dict(d["frames"][0], tag="idle_e")),
            "a renamed tag": lambda d: [fr.update(tag="stride_e") for fr in d["frames"] if fr["tag"] == "walk_e"],
            "a resized canvas": lambda d: [fr.update(size=[fr["size"][1], fr["size"][0]]) for fr in d["frames"]],
            "a tag name that leaves the folder": lambda d: d.update(badtag="../escape"),
        }
        for what, change in cases.items():
            with open(self.knight, "wb") as f:
                f.write(clean)
            polished = self.polish(self.knight, change)
            done = self.build()
            self.assertEqual(self.read(self.knight), polished, what)
            self.assertEqual(done["kept"], [self.knight], what)

    def test_indexed_only_when_it_loses_nothing(self):
        # the batch_27 live check (2026-11-01): portraits of 845 to 2772 colours came back quantized from an indexed
        # sprite, an untouched re-export shipped them, and build reported them as differing every time
        man, rng = fcore.Manifest(self.s, "knights"), np.random.default_rng(5)
        bust = np.zeros((32, 32, 4), np.uint8)
        bust[..., :3], bust[..., 3] = rng.integers(0, 256, (32, 32, 3)), 255        # about 1000 colours
        man.add(fcore.save_clean(Image.fromarray(bust), fcore.art(self.s.conf, "portraits", "spr_bust.png")),
                "portrait")
        glow = np.zeros((16, 16, 4), np.uint8)
        glow[4:12, 4:12] = (240, 230, 200, 255)
        glow[3, 4:12, 3] = 120                                                      # a few colours, partly clear
        man.add(fcore.save_clean(Image.fromarray(glow), fcore.art(self.s.conf, "ui", "icons", "ui_icon_glow.png")),
                "icon")
        self.build()
        self.assertEqual({os.path.basename(p["out"]): p["indexed"] for p in self.built},
                         {"knight.aseprite": "1", "spark.aseprite": "1", "barrel.aseprite": "1",
                          "spr_bust.aseprite": "0", "ui_icon_glow.aseprite": "0"})

    def test_the_command_line_reports_kept_and_replaced_files(self):
        import dotwork
        self.build()
        self.polish(self.knight, lambda d: d["frames"][0].update(ms=500))
        for args, says in ((["aseprite"], "[warn] kept assets_src"), (["aseprite", "--overwrite"],
                                                                      "the old file is kept as knight.aseprite.bak")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(dotwork.main(args + ["--project", self.tmp]), 0)
            self.assertIn(says, out.getvalue().replace(os.sep, "/"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(dotwork.main(["aseprite", "--project", self.tmp]), 0)
        self.assertIn("0 .aseprite files written, 3 unchanged", out.getvalue())


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)
