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
#           Aseprite source is indexed only when that loses nothing), and a character whose clips have different
#           sizes (one canvas in either editor, each clip back at its own size; issue #82), and an Aseprite palette
#           scan that makes no deprecated Pillow call (issue #185). No Pixelorama, Aseprite,
#           ComfyUI or Godot needed: verify is stubbed, Aseprite's script runs are stubbed (AsepriteLiveExam runs
#           the real one when ASEPRITE_BIN is set). PixeloramaLiveExam (only when PIXELORAMA_BIN is set) has the real
#           Pixelorama open, save and export Dotwork's files headless, then re-exports them (#67), and compares its
#           layer composite with Pixelorama's own; PixeloramaCompositeExam does that offline, against what Pixelorama
#           1.2.4 made from small projects (fixtures/pixelorama_composites.json) headless and with a window (#66).
#           TilemapExam and DotworkTilemapExam: tilemap layers (pxo_tiles.py) drawn as Pixelorama draws them (every
#           flip and transpose), composited in a character, your own tilemap projects into an atlas, a TileSet, scenes
#           and a JSON map, a game's map and TileSets into tilemap projects and back (edits land in their atlas slots
#           and the map scene after Pixelorama renumbered its tiles), refusals before anything is written; the live
#           exam has Pixelorama 1.2.4 save tilemaps and edit a cell and a tile.
# Usage   : python tools/art/dotwork/tests/test_pixelorama.py   (test_dotwork.py runs it too)
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-04 with Claude (Opus 5.5, claude-opus-5-5): the shape Pixelorama 1.2.4 saves, and the live exam (#67)
# Updated : 2026-11-04 with Claude (Opus 5.5, claude-opus-5-5): blend modes, clipping masks, groups and animated
#           opacity against Pixelorama's own composites (#66)
# Updated : 2026-11-04 with Claude (Opus 5.5, claude-opus-5-5): tilemap layers and tilemap projects
# ---------------------------------------------------------------------------
import base64
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
import warnings
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


def grow_clip(tmp, anim, dw=16, dh=16):
    """Issue #82: one clip of the knight at a bigger canvas, as a second pack can write it: its frames padded (the art
    centred on the bottom edge, where a lane puts the feet), its sheet and sheet data rebuilt at that size. Returns
    the new (w, h)."""
    out = os.path.join(tmp, "assets", "art", "characters", "knight")
    files = sorted(glob.glob(os.path.join(out, "frames", f"spr_knight_{anim}_*.png")))
    w, h = W + dw, H + dh
    sheet = Image.new("RGBA", (w * len(files), h), (0, 0, 0, 0))
    for i, p in enumerate(files):
        with Image.open(p) as im:
            big = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            big.paste(im.convert("RGBA"), (dw // 2, dh))
        fcore.save_clean(big, p)
        sheet.alpha_composite(big, (i * w, 0))
    sp = fcore.save_clean(sheet, os.path.join(out, f"knight_{anim}_sheet.png"))
    with open(sp[:-4] + ".json", encoding="utf-8") as fh:
        data = json.load(fh)
    data.update(frame_w=w, frame_h=h)
    with open(sp[:-4] + ".json", "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    # that pack's manifest rows match the new files (the row whose hash matches a file is the one that counts)
    mp = os.path.join(tmp, "assets_src", "dotwork", "manifest_knights.json")
    with open(mp, encoding="utf-8") as fh:
        man = json.load(fh)
    grown = {os.path.normpath(p) for p in files + [sp, sp[:-4] + ".json"]}
    for r in man["assets"]:
        p = os.path.normpath(os.path.join(tmp, r["file"]))
        if p in grown:
            r["sha256"] = fcore.sha256_file(p)
            if "canvas" in r:
                r["canvas"] = [w, h]
    with open(mp, "w", encoding="utf-8") as fh:
        json.dump(man, fh, indent=1)
    return w, h


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


def pixelorama_save(d, b):
    """rewrite_pxo edit: the shape of a project Pixelorama 1.2.3 saved (its autosave of a Dotwork file, 2026-11-01):
    extra fields, Godot text values, empty animated parameters, indices buffers and folder entries; no pixel, tag or
    time changes."""
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


def pixelorama_124_save(d, b):
    """rewrite_pxo edit: a Dotwork file as Pixelorama 1.2.4 saves it (PixeloramaLiveExam, 2026-11-04): pxo_version 8,
    each cel cropped to its used pixels with its size as var_to_str ("Vector2i(14, 22)") and its offset as JSON of a
    Vector2i ("(4, 2)"), an empty cel 1x1, and the fields 1.2.4 adds (author_*, license, include_blended_images,
    tile_mode_*, a layer's use_cel_image_for_effects). No pixel, tag or time changes."""
    pixelorama_save(d, b)
    w, h = d["size_x"], d["size_y"]
    d.update(pxo_version=8, pixelorama_version="v1.2.4-stable", author_company="", author_contact="",
             author_display_name="", author_real_name="", license="", include_blended_images=False,
             tile_mode_x_basis_x=w, tile_mode_x_basis_y=0, tile_mode_y_basis_x=0, tile_mode_y_basis_y=h)
    for ly in d["layers"]:
        ly["use_cel_image_for_effects"] = False
    for fi, fr in enumerate(d["frames"]):
        name = f"image_data/frames/{fi + 1}/layer_1"
        a = np.frombuffer(b[name], np.uint8).reshape(h, w, 4)
        ys, xs = np.nonzero(a[..., 3])
        if len(ys):
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        else:
            y0, y1, x0, x1 = 0, 1, 0, 1
        fr["cels"][0].update(image_size="Vector2i(%d, %d)" % (x1 - x0, y1 - y0), offset="(%d, %d)" % (x0, y0))
        b[name] = np.ascontiguousarray(a[y0:y1, x0:x1]).tobytes()


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

    def test_clips_of_two_sizes_share_one_canvas_and_come_back_at_their_own_size(self):
        # issue #82: Pixelorama refused a character whose clips have different sizes, so it could not be polished
        w, h = grow_clip(self.tmp, "attack_e")
        before = snapshot(self.tmp)
        self.assertEqual(self.build()["written"], [self.knight, os.path.join(self.src, "fx", "spark.pxo"),
                                                   os.path.join(self.src, "single", "barrel.pxo")])
        pj = self.px.read_pxo(self.knight)
        self.assertEqual(pj["size"], (w, h))
        walk0 = pj["frames"][4]                                         # attack_e's 4 frames, then walk_e
        x, y = (w - W) // 2, h - H                                      # centred, feet on the bottom edge
        self.assertTrue(np.array_equal(walk0[y:, x:x + W], self.frame("walk_e", 0)))
        self.assertFalse(walk0[:y].any() or walk0[:, :x].any() or walk0[:, x + W:].any())
        self.assertEqual(self.build()["unchanged"][0], self.knight)     # matches the game: not "kept"
        self.reexport()
        self.assertEqual(changed(before, snapshot(self.tmp)), [])        # every clip back at its own size

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
        self.assertFalse(pj["windowed"])              # a hidden layer's blend mode changes nothing
        got = pj["frames"][6]
        mask = np.ones((H, W), bool)
        mask[1, 1] = False
        # the hidden white layer never shows (the colour under clear pixels is not kept: Pixelorama writes 0 there)
        self.assertTrue(np.array_equal(got[..., 3][mask], base[..., 3][mask]))
        seen = mask & (base[..., 3] > 0)
        self.assertTrue(np.array_equal(got[seen], base[seen]))
        # the glaze, as Pixelorama 1.2.4 composites it headless: alpha x opacity stored back to 8 bits (truncated),
        # then Color.blend in 32-bit floats over the art, the result truncated to 8 bits (#66)
        f = np.float32
        a1 = f(np.trunc(float(f(f(255 / 255.0) * 0.5)) * 255.0) / 255.0)
        dst = [f(v / 255.0) for v in base[1, 1]]
        sa = f(1) - a1
        ra = dst[3] * sa + a1
        rgb = [(dst[c] * dst[3] * sa + f(1) * a1) / ra for c in range(3)]
        self.assertEqual(tuple(got[1, 1]), tuple(int(np.trunc(float(v) * 255.0)) for v in rgb + [ra]))

    def test_refused_features_stop_before_writing(self):
        self.build()
        before = snapshot(self.tmp)
        with open(self.knight, "rb") as f:
            clean = f.read()

        def layer(**kw):
            return lambda d, b: d["layers"][0].update(**kw)

        def keyframe(**kw):
            kf = dict({"ease": 0, "id": 0, "trans": 0, "value": 0.5}, **kw)
            return layer(animated_params='Dictionary[String, Dictionary]({\n"opacity": {\n3: {\n%s\n}\n}\n})' % (
                ",\n".join('"%s": %s' % kv for kv in kf.items())))

        def under(kind):
            """A hidden layer of this type under a clipping mask: the shader would clip to what it draws."""
            def edit(d, b):
                d["layers"].insert(0, dict(d["layers"][0], name="under", visible=False, type=kind))
                d["layers"][1].update(clipping_mask=True)
                for fr in d["frames"]:
                    fr["cels"].insert(0, {"opacity": 1.0, "z_index": 0})
                for fi in range(len(d["frames"])):
                    b[f"image_data/frames/{fi + 1}/layer_2"] = b.pop(f"image_data/frames/{fi + 1}/layer_1")
            return edit

        def blending_group(d, b):
            d["layers"].append({"name": "g", "visible": True, "blend_mode": 0, "opacity": 1.0, "parent": -1,
                                "type": 1, "expanded": True})
            d["layers"][0]["parent"] = 1
            d["color_mode"] = -1
            for fr in d["frames"]:
                fr["cels"].append({"opacity": 1.0, "z_index": 0})
        cases = {
            "unknown blend mode": layer(blend_mode=23),
            "pass-through pixel layer": layer(blend_mode=-2),
            "clipping mask on a 3D layer": under(2),
            "indexed project with a blending group": blending_group,
            "3D layer": layer(type=2),
            "tilemap layer of no tileset": layer(type=3),
            "isometric tilemap layer": lambda d, b: (d["layers"][0].update(type=3, tileset_index=0, tile_shape=1),
                                                     d.update(tilesets=[{"tile_size": "(8, 8)", "tile_amount": 0}])),
            "layer effect": layer(effects=[{"name": "Outline", "enabled": True}]),
            "unreadable animated opacity": layer(
                animated_params='Dictionary[String, Dictionary]({\n"opacity": {3: 0.5}\n})'),
            "animated opacity of no frame": layer(
                animated_params='Dictionary[String, Dictionary]({\n"opacity": {"x": {}}\n})'),
            "unknown transition": keyframe(trans=12),
            "unknown ease": keyframe(ease=4),
            "keyframe value not a number": keyframe(value='"half"'),
            "animated opacity cut short": layer(animated_params='Dictionary[String, Dictionary]({\n"opacity": {'),
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
        self.build()
        rewrite_pxo(self.knight, pixelorama_save)
        before = snapshot(self.tmp)
        self.reexport()
        self.assertEqual(changed(before, snapshot(self.tmp)), [])

    def test_a_file_pixelorama_1_2_4_saved_round_trips_unchanged(self):
        # #67: the version 8 reader came from the 1.2.4-rc2 source; this is the shape the released 1.2.4 saves
        before = snapshot(self.tmp)
        self.build()
        sources = [self.knight, os.path.join(self.src, "fx", "spark.pxo"), os.path.join(self.src, "single", "barrel.pxo")]
        for p in sources:
            rewrite_pxo(p, pixelorama_124_save)
        with zipfile.ZipFile(self.knight) as z:
            cel = json.loads(z.read("data.json"))["frames"][0]["cels"][0]
        self.assertNotEqual(cel["image_size"], "Vector2i(%d, %d)" % (W, H))     # really cropped
        done = self.build()
        self.assertEqual((done["kept"], len(done["unchanged"])), ([], 3))       # still shows the game's frames
        r, _ = self.reexport()
        self.assertTrue(r["ok"])
        self.assertEqual(changed(before, snapshot(self.tmp)), [])

    def test_a_file_pixelorama_saved_unchanged_is_not_kept(self):
        # #100: build compared bytes, so any .pxo Pixelorama had saved was "kept: it differs" on every build, even
        # with the game's frames, tags and times, and --overwrite then replaced the user's file
        self.build()
        for p in (self.knight, os.path.join(self.src, "fx", "spark.pxo"), os.path.join(self.src, "single", "barrel.pxo")):
            rewrite_pxo(p, pixelorama_save)
        done = self.build()
        self.assertEqual(done["kept"], [])
        self.assertEqual([os.path.basename(p) for p in done["unchanged"]], ["knight.pxo", "spark.pxo", "barrel.pxo"])
        with open(self.knight, "rb") as f:
            saved = f.read()
        self.assertEqual(self.build(overwrite=True)["backups"], [])   # nothing to replace: the saved file stays
        with open(self.knight, "rb") as f:
            self.assertEqual(f.read(), saved)

        def edit(d, b):   # a pixel polished in the saved file: kept, until it is re-exported into the game
            w, h = d["size_x"], d["size_y"]
            a = np.frombuffer(b["image_data/frames/1/layer_1"], np.uint8).reshape(h, w, 4).copy()
            a[0, 0] = (200, 60, 50, 255)
            b["image_data/frames/1/layer_1"] = a.tobytes()
        rewrite_pxo(self.knight, edit)
        self.assertEqual([os.path.basename(p) for p in self.build()["kept"]], ["knight.pxo"])
        self.reexport()
        self.assertEqual(self.build()["kept"], [])

    def test_a_local_export_folder_is_reported_and_cleared_only_on_request(self):
        # Pixelorama 1.2.3 keeps the folder you last exported to in every .pxo it saves (#69): Dotwork names it, and
        # blanks it only when asked, leaving every other entry of the file and the round trip as they were
        self.build()
        home = "C:/Users/someone/Desktop/exports"

        def edit(d, b):
            d["export_profile"] = {"directory_path": '"%s"' % home, "file_name": '"knight"'}
        rewrite_pxo(self.knight, edit)
        rel = os.path.relpath(self.knight, self.tmp)
        with zipfile.ZipFile(self.knight) as z:
            old = {i.filename: (i.compress_type, z.read(i.filename)) for i in z.infolist()}
        self.assertEqual(self.px.local_paths(self.s.project, self.s.conf), [(rel, home, False)])
        with zipfile.ZipFile(self.knight) as z:
            self.assertEqual({i.filename: (i.compress_type, z.read(i.filename)) for i in z.infolist()}, old,
                             "reporting alone must not touch the file")
        self.assertEqual(self.px.local_paths(self.s.project, self.s.conf, clear=True), [(rel, home, True)])
        self.assertEqual(self.px.local_paths(self.s.project, self.s.conf), [])
        with zipfile.ZipFile(self.knight) as z:
            new = {i.filename: (i.compress_type, z.read(i.filename)) for i in z.infolist()}
        self.assertEqual(list(new), list(old))
        self.assertEqual({n: v for n, v in new.items() if n != "data.json"},
                         {n: v for n, v in old.items() if n != "data.json"})
        want = json.loads(old["data.json"][1])
        want["export_profile"]["directory_path"] = '""'
        self.assertEqual(json.loads(new["data.json"][1]), want)
        before = snapshot(self.tmp)
        r, _ = self.reexport()
        self.assertTrue(r["ok"])
        self.assertEqual(changed(before, snapshot(self.tmp)), [])

    def test_which_export_folders_count_as_local(self):
        self.build()
        cases = {'"C:/Users/someone/art"': "C:/Users/someone/art", '"D:\\\\art"': "D:\\\\art",
                 '"/home/someone/art"': "/home/someone/art", "/Users/someone/art": "/Users/someone/art",
                 '"~/art"': "~/art", '""': "", "": "", '"exports"': "", "art/out": ""}
        for value, want in cases.items():
            rewrite_pxo(self.knight, lambda d, b: d.update(export_profile={"directory_path": value}))
            self.assertEqual(self.px.export_folder(self.knight), want, value)
        rewrite_pxo(self.knight, lambda d, b: d.pop("export_profile"))
        self.assertEqual(self.px.export_folder(self.knight), "")
        rewrite_pxo(self.knight, lambda d, b: d.update(export_profile="C:/x"))
        self.assertEqual(self.px.export_folder(self.knight), "")

    def test_cli_warns_about_a_local_export_folder_and_clears_it_on_request(self):
        self.build()
        rewrite_pxo(self.knight, lambda d, b: d.update(
            export_profile={"directory_path": '"/home/someone/art"', "file_name": '"knight"'}))
        cmd = [sys.executable, os.path.join(DOTWORK, "dotwork.py"), "pixelorama", "--project", self.tmp]
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("[warn] " + os.path.join("assets_src", "pixelorama", "characters", "knight.pxo"), run.stdout)
        self.assertIn("/home/someone/art", run.stdout)
        self.assertEqual(self.px.export_folder(self.knight), "/home/someone/art")
        run = subprocess.run(cmd + ["--clear-export-path"], capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("is now blank", run.stdout)
        self.assertEqual(self.px.export_folder(self.knight), "")

    def test_cli_build(self):
        code = subprocess.run([sys.executable, os.path.join(DOTWORK, "dotwork.py"), "pixelorama", "--project",
                               self.tmp], capture_output=True, text=True, timeout=120)
        self.assertEqual(code.returncode, 0, code.stdout + code.stderr)
        self.assertIn("3 .pxo files written", code.stdout)
        code = subprocess.run([sys.executable, os.path.join(DOTWORK, "dotwork.py"), "--help"], capture_output=True,
                              text=True, timeout=120)
        self.assertIn("pixelorama", code.stdout)


COMPOSITES = os.path.join(HERE, "fixtures", "pixelorama_composites.json")
HEADLESS_CASES = ("normal", "animated", "pass_through_group")


def composite_pxo(path, case, size):
    """A .pxo (version 7) from a case of fixtures/pixelorama_composites.json: its layers and its cels (opacity,
    RGBA8 base64 or None for a group)."""
    w, h = size
    layers = []
    for ly in case["layers"]:
        d = {"name": "l", "visible": True, "locked": False, "blend_mode": 0, "clipping_mask": False, "opacity": 1.0,
             "parent": -1, "type": 0, "new_cels_linked": False, "effects": []}
        d.update(ly)
        if d["type"] == 1:
            d.setdefault("expanded", True)
        layers.append(d)
    data = {"pxo_version": 7, "size_x": w, "size_y": h, "color_mode": 5, "fps": 6.0, "layers": layers, "tags": [],
            "frames": [{"cels": [{"opacity": op, "z_index": 0} for op, _ in fr], "duration": 1.0}
                       for fr in case["frames"]]}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data.json", json.dumps(data))
        for fi, fr in enumerate(case["frames"]):
            for li, (_, buf) in enumerate(fr):
                if buf is not None:
                    z.writestr(f"image_data/frames/{fi + 1}/layer_{li + 1}", base64.b64decode(buf))
    return path


def steps_apart(a, b):
    """Per pixel, how many 8-bit steps two RGBA frames differ by: alpha, and colour weighted by alpha (a colour
    under a pixel that is all but clear barely shows)."""
    a, b = a.astype(np.float64), b.astype(np.float64)
    da = np.abs(a[..., 3] - b[..., 3])
    dc = np.abs(a[..., :3] * a[..., 3:4] - b[..., :3] * b[..., 3:4]).max(-1) / 255.0
    return np.maximum(da, dc)


class PixeloramaCompositeExam(unittest.TestCase):
    """Dotwork's layer composite against what Pixelorama 1.2.4 itself made from the same small projects
    (fixtures/pixelorama_composites.json: blend modes, clipping masks, groups that blend, pass-through groups, cel,
    layer and animated opacity), headless and with a window. Headless (its command-line export) blends Normal
    layers only, and Dotwork matches it exactly; the blend modes, clipping masks and blending groups exist only in
    its windowed GPU composite, which Dotwork follows within two steps in nearly every pixel (#66)."""

    @classmethod
    def setUpClass(cls):
        with open(COMPOSITES, encoding="utf-8") as f:
            cls.fixture = json.load(f)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_pxocomp_")
        make_game(self.tmp)                          # binds the project the error messages name files from
        import pixelorama
        self.px = pixelorama
        self.w, self.h = self.fixture["size"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def frames(self, case, which):
        return [np.frombuffer(base64.b64decode(s), np.uint8).reshape(self.h, self.w, 4)
                for s in self.fixture["cases"][case][which]]

    def read(self, case):
        return self.px.read_pxo(composite_pxo(os.path.join(self.tmp, case + ".pxo"), self.fixture["cases"][case],
                                              (self.w, self.h)))

    def test_normal_layers_equal_pixelorama_headless_exactly(self):
        # partly clear layers at cel and layer opacity under 100 %, opacity keyframes (linear, eased, constant;
        # frames before, between and after them), a pass-through group whose own opacity Pixelorama ignores
        for case in HEADLESS_CASES:
            pj = self.read(case)
            self.assertFalse(pj["windowed"], case)
            want = self.frames(case, "headless")
            self.assertEqual(len(pj["frames"]), len(want), case)
            for i, (have, theirs) in enumerate(zip(pj["frames"], want)):
                self.assertTrue(np.array_equal(have, theirs), f"{case} frame {i}")

    def test_blend_modes_clipping_and_groups_follow_the_windowed_composite(self):
        windowed = [c for c in self.fixture["cases"] if c not in HEADLESS_CASES]
        self.assertEqual(len(windowed), 26)          # 22 blend modes, two group layouts, two clipping layouts
        total = same = near = 0
        for case in windowed:
            pj = self.read(case)
            self.assertTrue(pj["windowed"], case)
            for have, gpu, cli in zip(pj["frames"], self.frames(case, "windowed"), self.frames(case, "headless")):
                d = steps_apart(have, gpu)
                shown = (have[..., 3] > 0) | (gpu[..., 3] > 0)
                total += shown.sum()
                same += (shown & (d == 0)).sum()
                near += (shown & (d <= 2)).sum()
                self.assertGreaterEqual((shown & (d <= 2)).sum(), 0.95 * shown.sum(), case)
                if case == "mode_3":                 # Multiply: Pixelorama's command-line export leaves it out
                    self.assertFalse(np.array_equal(gpu, cli))
        self.assertGreaterEqual(near, 0.99 * total)
        self.assertGreaterEqual(same, 0.8 * total)

    def test_white_and_black_in_the_hsl_modes(self):
        # the GPU's own order of operations makes the saturation of white and black 0 / 0 there: the blend comes out
        # black where an exact reading of the shader gives white (pixels 0 and 1 of the base are white and black)
        for mode in (17, 18, 19, 20):
            have = self.read(f"mode_{mode}")["frames"][0]
            gpu = self.frames(f"mode_{mode}", "windowed")[0]
            self.assertLessEqual(float(steps_apart(have[0, :2], gpu[0, :2]).max()), 2, mode)

    def test_the_windowed_composite_is_the_same_in_bands(self):
        whole = self.read("nested_groups")["frames"]
        real = self.px.BAND_PIXELS
        try:
            for band in (1, self.w * 4):
                self.px.BAND_PIXELS = band
                for a, b in zip(whole, self.read("nested_groups")["frames"]):
                    self.assertTrue(np.array_equal(a, b), band)
        finally:
            self.px.BAND_PIXELS = real

    def test_godot_values_as_pixelorama_writes_them(self):
        g = self.px._gvalue
        self.assertEqual(g('Dictionary[String, Dictionary]({\n"opacity": {}\n})'), {"opacity": {}})
        self.assertEqual(g('Dictionary[String, Variant]({\n"offset": Vector2(13, 0),\n"on": false,\n"n": &"x",\n'
                           '"c": Color(0.91764706, 1, 0.2, 1),\n"a": Array[int]([1, -2])\n})'),
                         {"offset": ("Vector2", [13, 0]), "on": False, "n": "x",
                          "c": ("Color", [0.91764706, 1, 0.2, 1]), "a": [1, -2]})
        self.assertEqual(g('{\n0: {\n"ease": 2,\n"trans": 4,\n"value": 0.5\n}\n}'),
                         {0: {"ease": 2, "trans": 4, "value": 0.5}})
        for bad in ('{', 'Dictionary(', '{"a": 1} 2', '{"a" 1}', 'what', '"open', '[' * 40 + ']' * 40):
            with self.assertRaises(ValueError, msg=bad):
                g(bad)

    def test_opacity_keyframes_as_pixelorama_reads_them(self):
        def keys(*kf):
            return {f: (v, t, e) for f, v, t, e in kf}
        at = self.px._layer_opacity
        k = keys((2, 0.2, 0, 0), (6, 1.0, 0, 0))
        self.assertEqual([at(0.7, k, f) for f in range(9)],
                         [0.2, 0.2, 0.2, 0.2 + 0.25 * 0.8, 0.2 + 0.5 * 0.8, 0.2 + 0.75 * 0.8, 1.0, 1.0, 1.0])
        self.assertEqual(at(0.7, {}, 3), 0.7)                                       # no keyframes: the layer's own
        self.assertEqual(at(0.7, keys((4, 0.3, 0, 0)), 0), 0.3)                     # one keyframe holds everywhere
        self.assertEqual(at(0.7, keys((0, 0.3, 999, 0), (4, 0.9, 0, 0)), 3), 0.3)   # constant until the next one
        quad = keys((0, 0.0, 4, 2), (4, 1.0, 0, 0))
        self.assertAlmostEqual(at(1, quad, 1), 0.125, places=6)                     # Quad in-out
        self.assertAlmostEqual(at(1, quad, 2), 0.5, places=6)
        sine = keys((0, 0.0, 1, 0), (2, 1.0, 0, 0))
        self.assertAlmostEqual(at(1, sine, 1), 1 - np.cos(np.pi / 4), places=6)    # Sine in
        back = keys((0, 0.0, 10, 1), (10, 1.0, 0, 0))
        self.assertGreater(max(at(1, back, f) for f in range(10)), 1.0)             # Back out overshoots
        for trans in self.px.EASINGS:
            for ease in range(4):
                k = keys((0, 0.25, trans, ease), (8, 0.75, 0, 0))
                self.assertAlmostEqual(at(1, k, 0), 0.25)
                self.assertTrue(all(np.isfinite(at(1, k, f)) for f in range(9)), (trans, ease))


# -------------------------------------------------- tilemap layers (pxo_tiles)
TILE = 8   # px: the tilemap exams' tile size


def tiles_of(rng, n, size=(TILE, TILE), name="Ground"):
    """A Pixelorama tileset for pxo_tiles.pxo_bytes: the empty tile, then n tiles of random pixels (some clear)."""
    tw, th = size
    tiles = [np.zeros((th, tw, 4), np.uint8)]
    for _ in range(n):
        t = rng.integers(0, 256, (th, tw, 4), dtype=np.uint8)
        t[..., 3] = rng.choice([0, 255, 255, 128], (th, tw))
        tiles.append(t)
    data = [{"probability": 1.0, "user_data": "", "center": -1, "peers": [-1] * 16} for _ in tiles]
    return {"name": name, "size": size, "tiles": tiles, "data": data, "terrains": [("grass", (90, 160, 60))]}


def as_pixelorama_draws(tile, fh, fv, tr):
    """CelTileMap.transform_tile step by step: rotate_90(COUNTERCLOCKWISE), flip_y, then flip_x, flip_y."""
    t = getattr(Image, "Transpose", Image)
    im = Image.fromarray(tile, "RGBA")
    if tr:
        im = im.transpose(t.ROTATE_90).transpose(t.FLIP_TOP_BOTTOM)
    if fh:
        im = im.transpose(t.FLIP_LEFT_RIGHT)
    if fv:
        im = im.transpose(t.FLIP_TOP_BOTTOM)
    return np.array(im)


def own_map(rng):
    """(tileset, layers) of a small map: a ground layer of every flip and transpose, and a top layer."""
    ts = tiles_of(rng, 5)
    ts["data"][2].update(user_data="water solid", center=0, peers=[0, -1, -1, 0, 0, -1, -1, -1, 0, -1, -1, -1, 0, -1,
                                                                    -1, 0])
    ts["data"][3].update(user_data="sand", probability=0.5)
    ground = {}
    for i, (fh, fv, tr) in enumerate([(a, b, c) for a in (0, 1) for b in (0, 1) for c in (0, 1)]):
        ground[(i % 4, i // 4)] = (1 + i % 3, bool(fh), bool(fv), bool(tr))
    ground[(5, 2)] = (5, False, False, False)
    return ts, [("ground", ground), ("top", {(1, 1): (4, False, True, False), (3, 0): (2, False, False, False)})]


def write_own(tmp, name, ts, layers, size=(6 * TILE, 3 * TILE)):
    import pxo_tiles
    p = os.path.join(tmp, "assets_src", "pixelorama", "tilemaps", name + ".pxo")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(pxo_tiles.pxo_bytes(size, ts, layers))
    return p


def godot_cells(scene_text, layer):
    """[(x, y, source, ax, ay, alt)] of one TileMapLayer of a scene, sorted."""
    import pxo_tiles
    body = scene_text.split(f'[node name="{layer}" type="TileMapLayer"', 1)[1].split("\n[", 1)[0]
    line = next(l for l in body.splitlines() if l.startswith("tile_map_data = "))
    return sorted(pxo_tiles.decode_cells(line[len("tile_map_data = "):]))


def make_tiles(s):
    """What the ground lane and mapbuild leave: a TileSet of two atlas sources (plain grass tiles; water with a
    terrain, collision, surface data and an animated tile), a map scene on it as Godot 4.7 saves one (uids, base64
    tile_map_data, a props node), and a second TileSet no map uses; with their manifest rows."""
    import godot
    import pxo_tiles
    conf, T, rng = s.conf, TILE, np.random.default_rng(5)
    man = fcore.Manifest(s, "town")
    art, res = fcore.art(conf, "tiles", "town"), fcore.res(conf, "tiles", "town")
    grass = rng.integers(0, 256, (T, 4 * T, 4), dtype=np.uint8)
    grass[..., 3] = 255
    water = rng.integers(0, 256, (2 * T, 3 * T, 4), dtype=np.uint8)
    water[..., 3] = rng.choice([0, 255], (2 * T, 3 * T))
    for fn, a in (("base_grass.png", grass), ("overlay_water.png", water)):
        man.add(fcore.save_clean(Image.fromarray(a), os.path.join(art, fn)), "tile_atlas", routes=("klein",), tile_px=T)
    peers = (1, -1, 1, -1, 1, -1, 1, -1)
    sources = [{"atlas_res": f"{res}/base_grass.png", "tiles": [
        {"x": k, "y": 0, "terrain": None, "probability": 1.0 if k == 0 else 0.6, "custom": "grass"} for k in range(4)]},
        {"atlas_res": f"{res}/overlay_water.png", "tiles": [
            {"x": 0, "y": 0, "terrain": 1, "peers": peers, "custom": "water", "solid_rects": [(-4, -4, 4, 4)],
             "anim": {"frames": 2, "fps": 4}},
            {"x": 0, "y": 1, "terrain": 1, "peers": peers, "custom": "water"},
            {"x": 2, "y": 1, "terrain": 1, "peers": (1, 1, 1, -1, -1, -1, -1, -1), "custom": "water"}]}]
    ts = godot.tileset_layers(os.path.join(art, "ground_town_tileset.tres"), T, sources,
                              [("grass", (90, 160, 60)), ("water", (60, 90, 200))], custom="surface", physics=True,
                              overlays=[1], mode="match_corners_and_sides")
    man.add(ts, "tileset", tile_px=T, terrains=["grass", "water"])
    base = [(x, y, 0, (x * 3 + y) % 4, 0, pxo_tiles.FLIP_H if (x, y) == (2, 1) else 0)
            for y in range(3) for x in range(5)]
    wet = [(1, 1, 1, 0, 0, 0), (2, 1, 1, 0, 1, 0), (3, 2, 1, 2, 1, pxo_tiles.TRANSPOSE)]
    scene = fcore.asset(conf, "maps", "town.tscn")
    os.makedirs(os.path.dirname(scene), exist_ok=True)
    with open(scene, "w", encoding="utf-8", newline="\n") as f:
        f.write('[gd_scene format=3 uid="uid://b1town"]\n\n'
                f'[ext_resource type="TileSet" uid="uid://c2ts" path="{res}/ground_town_tileset.tres" id="1_ab3cd"]\n\n'
                '[node name="Town" type="Node2D"]\n\n'
                '[node name="Base" type="TileMapLayer" parent="."]\n'
                f'tile_map_data = {pxo_tiles.encode_cells(base, True)}\ntile_set = ExtResource("1_ab3cd")\n\n'
                '[node name="Water" type="TileMapLayer" parent="."]\n'
                f'tile_map_data = {pxo_tiles.encode_cells(wet, True)}\ntile_set = ExtResource("1_ab3cd")\n\n'
                '[node name="Props" type="Node2D" parent="."]\ny_sort_enabled = true\n')
    man.add(scene, "scene", node="Node2D + TileMapLayers", tileset=f"{res}/ground_town_tileset.tres",
            layers={"Base": {"cells": 15, "mismatches": 0}})
    ledge = rng.integers(0, 256, (T, 2 * T, 4), dtype=np.uint8)
    ledge[..., 3] = 255
    lp = fcore.save_clean(Image.fromarray(ledge), fcore.art(conf, "tiles", "ledges", "ledges_atlas.png"))
    man.add(lp, "tile_atlas", tile_px=T)
    lt = godot.tileset_layers(fcore.art(conf, "tiles", "ledges", "ledges_tileset.tres"), T,
                              [{"atlas_res": fcore.res(conf, "tiles", "ledges", "ledges_atlas.png"),
                                "tiles": [{"x": 0, "y": 0, "terrain": None}, {"x": 1, "y": 0, "terrain": None}]}],
                              [("ledge", (100, 100, 100))])
    man.add(lt, "tileset", tile_px=T)
    return {"grass": grass, "water": water, "base": base, "wet": wet, "scene": scene}


class TilemapExam(unittest.TestCase):
    """Pixelorama tilemap layers (pxo_tiles): drawn as Pixelorama draws them, composited in any project, and your own
    tilemap projects turned into atlases, a TileSet, scenes and a JSON map; the round trip changes only what you
    edited."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_pxotiles_")
        self.s = make_game(self.tmp)
        import pixelorama
        import pxo_tiles
        self.px, self.pt = pixelorama, pxo_tiles
        self.out = os.path.join(self.tmp, "assets", "art", "tilemaps", "meadow")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def reexport(self):
        with stub_verify() as seen:
            r = self.px.reexport(self.s.project, self.s.conf)
        return r, seen

    def test_cells_are_drawn_flipped_and_transposed_as_pixelorama_draws_them(self):
        rng = np.random.default_rng(1)
        for size in ((TILE, TILE), (8, 5)):            # a transposed 8x5 tile is 5x8, shifted half the difference
            ts = tiles_of(rng, 1, size)
            tw, th = size
            for fh in (0, 1):
                for fv in (0, 1):
                    for tr in (0, 1):
                        got = self.pt.render(ts, (tw, th), {(1, 1): (1, bool(fh), bool(fv), bool(tr))}, 5 * tw, 5 * th)
                        want = np.zeros_like(got)
                        t = as_pixelorama_draws(ts["tiles"][1], fh, fv, tr)
                        x = 2 * tw - int((t.shape[1] - tw) / 2)
                        y = 2 * th - int((t.shape[0] - th) / 2)
                        want[y:y + t.shape[0], x:x + t.shape[1]] = t
                        self.assertTrue(np.array_equal(got, want), (size, fh, fv, tr))

    def test_a_tilemap_layer_in_a_character_composites_like_a_pixel_layer(self):
        # it used to stop the re-export; now it is drawn from its tiles and blended under the art
        self.px.build(self.s.project, self.s.conf)
        knight = os.path.join(self.tmp, "assets_src", "pixelorama", "characters", "knight.pxo")
        before = self.px.read_pxo(knight)["frames"]
        ts = tiles_of(np.random.default_rng(2), 2)
        cells = {(0, 0): (1, False, False, False), (2, 3): (2, True, False, True)}

        def add(d, b):
            d["layers"].insert(0, {"name": "floor", "visible": True, "opacity": 1.0, "parent": -1, "type": 3,
                                   "blend_mode": 0, "tileset_index": 0, "tile_shape": 0, "tile_size": "(8, 8)"})
            d["tilesets"] = [{"name": "f", "tile_size": "(8, 8)", "tile_amount": 3, "tile_shape": 0,
                              "tile_data": {}, "terrain_data": []}]
            for fr in d["frames"]:
                fr["cels"].insert(0, {"opacity": 1.0, "z_index": 0, "offset": "(0, 0)", "cell_data": {
                    "(%d, %d)" % k: {"index": v[0], "flip_h": v[1], "flip_v": v[2], "transpose": v[3]}
                    for k, v in cells.items()}})
            for fi in range(len(d["frames"])):
                b[f"image_data/frames/{fi + 1}/layer_2"] = b.pop(f"image_data/frames/{fi + 1}/layer_1")
            for j, t in enumerate(ts["tiles"]):
                b[f"tilesets/0/{j}"] = t.tobytes()
        rewrite_pxo(knight, add)
        floor = self.pt.render(ts, (0, 0), cells, W, H)
        for want, have in zip(before, self.px.read_pxo(knight)["frames"]):
            self.assertTrue(np.array_equal(have, self.px._headless([(floor, 1.0), (want, 1.0)], want.shape)))
        r, _ = self.reexport()
        self.assertTrue(r["ok"])
        # with a blend mode it takes the windowed composite, the art multiplied over the floor (the shader's blend)
        rewrite_pxo(knight, lambda d, b: d["layers"][1].update(blend_mode=3))
        pj = self.px.read_pxo(knight)
        self.assertTrue(pj["windowed"])
        both = (floor[..., 3] == 255) & (before[0][..., 3] == 255)
        self.assertTrue(both.any())
        want = np.rint(floor[..., :3].astype(np.float64) * before[0][..., :3] / 255.0)
        self.assertLessEqual(np.abs(pj["frames"][0][..., :3][both] - want[both]).max(), 1)

    def test_your_own_tilemap_becomes_an_atlas_a_tileset_a_scene_and_a_json_map(self):
        ts, layers = own_map(np.random.default_rng(3))
        write_own(self.tmp, "meadow", ts, layers)
        r, seen = self.reexport()
        self.assertTrue(r["ok"])
        atlas = np.array(Image.open(os.path.join(self.out, "tiles_meadow.png")).convert("RGBA"))
        self.assertEqual(atlas.shape, (TILE, 16 * TILE, 4))           # 16 slots to a row; tile N at slot N - 1
        for j in range(1, 6):
            self.assertTrue(np.array_equal(atlas[:, (j - 1) * TILE:j * TILE], ts["tiles"][j]))
        with open(os.path.join(self.out, "meadow_tileset.tres"), encoding="utf-8") as f:
            tres = f.read()
        for line in ("texture_region_size = Vector2i(8, 8)", '1:0/0/custom_data_0 = "water"',
                     "1:0/0/terrain = 0", "1:0/0/terrains_peering_bit/top_side = 0",
                     "1:0/0/terrains_peering_bit/right_side = 0", "1:0/0/terrains_peering_bit/bottom_left_corner = -1",
                     "1:0/0/physics_layer_0/polygon_0/points = PackedVector2Array(-4, -4, 4, -4, 4, 4, -4, 4)",
                     "2:0/0/probability = 0.500", '2:0/0/custom_data_0 = "sand"', "metadata/dotwork_pixelorama = true",
                     'terrain_set_0/terrain_0/name = "grass"', "terrain_set_0/mode = 0"):
            self.assertIn(line, tres)
        with open(os.path.join(self.out, "meadow.tscn"), encoding="utf-8") as f:
            scene = f.read()
        want = sorted((x, y, 0, j - 1, 0, (fh and self.pt.FLIP_H) | (fv and self.pt.FLIP_V) | (tr and self.pt.TRANSPOSE))
                      for (x, y), (j, fh, fv, tr) in layers[0][1].items())
        self.assertEqual(godot_cells(scene, "ground"), want)
        self.assertIn("res://assets/art/tilemaps/meadow/meadow_tileset.tres", scene)
        with open(os.path.join(self.out, "meadow_map.json"), encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["tile_size"], [TILE, TILE])
        self.assertEqual(doc["tilesets"][0]["solid"], [2])
        self.assertEqual(doc["tilesets"][0]["surface"], {"2": "water", "3": "sand"})
        self.assertIn([1, 1, 4, 2], doc["frames"][0][1]["cells"])         # top layer: tile 4, flipped vertically
        self.assertIn([3, 1, 2, 7], doc["frames"][0][0]["cells"])         # every flag
        rows = {r["file"].rsplit("/", 1)[1]: r for r in manifest_rows(self.tmp)["manifest_pixelorama.json"]}
        self.assertEqual(sorted(rows), ["meadow.tscn", "meadow_map.json", "meadow_tileset.tres", "tiles_meadow.png"])
        self.assertTrue(all(r["models"] == [] and r["source"].endswith("meadow.pxo") for r in rows.values()))
        self.assertIn("assets/art/tilemaps/meadow/meadow.tscn", seen["files"])

    def test_an_untouched_tilemap_round_trip_changes_no_file(self):
        ts, layers = own_map(np.random.default_rng(4))
        p = write_own(self.tmp, "meadow", ts, layers)
        self.reexport()
        before = snapshot(self.tmp)
        self.reexport()
        self.assertEqual(changed(before, snapshot(self.tmp)), [])

        def as_124_saves(d, b):
            # Pixelorama 1.2.4: version 8, its own fields, the cel moved to where its tiles start (cells relative to
            # the offset), tile colours under clear pixels dropped, the tile data it keeps (times_used)
            d.update(pxo_version=8, pixelorama_version="v1.2.4-stable", metadata={}, brushes=[], guides=[],
                     export_profile={"directory_path": '""'})
            for c in d["frames"][0]["cels"]:
                c.update(offset="(%d, %d)" % (TILE, 0), image_size="Vector2i(40, 24)", metadata={},
                         cell_data={"(%d, %d)" % (int(k[1:-1].split(",")[0]) - 1, int(k[1:-1].split(",")[1])): v
                                    for k, v in c["cell_data"].items()})
            for k in [k for k in b if k.startswith("tilesets/")]:
                t = np.frombuffer(b[k], np.uint8).reshape(TILE, TILE, 4).copy()
                t[t[..., 3] == 0] = 0
                b[k] = t.tobytes()
        rewrite_pxo(p, as_124_saves)
        self.reexport()
        self.assertEqual(changed(before, snapshot(self.tmp)), [])

    def test_an_edited_tile_changes_the_atlas_and_an_edited_cell_the_map(self):
        ts, layers = own_map(np.random.default_rng(5))
        p = write_own(self.tmp, "meadow", ts, layers)
        self.reexport()
        before = snapshot(self.tmp)
        rel = "assets/art/tilemaps/meadow/"

        def tile_pixel(d, b):
            t = np.frombuffer(b["tilesets/0/4"], np.uint8).reshape(TILE, TILE, 4).copy()
            t[0, 0] = (1, 2, 3, 255)
            b["tilesets/0/4"] = t.tobytes()
        rewrite_pxo(p, tile_pixel)
        self.reexport()
        self.assertEqual(changed(before, snapshot(self.tmp)), [rel + "tiles_meadow.png",
                                                               "assets_src/dotwork/manifest_pixelorama.json"])
        before = snapshot(self.tmp)
        rewrite_pxo(p, lambda d, b: d["frames"][0]["cels"][1]["cell_data"].update(
            {"(0, 2)": {"index": 3, "flip_h": False, "flip_v": False, "transpose": False}}))
        self.reexport()
        self.assertEqual(changed(before, snapshot(self.tmp)), [rel + "meadow.tscn", rel + "meadow_map.json",
                                                               "assets_src/dotwork/manifest_pixelorama.json"])
        # a tile Pixelorama added (Auto mode) grows the atlas and the TileSet by one slot; nothing else moves
        before = snapshot(self.tmp)

        def new_tile(d, b):
            d["tilesets"][0]["tile_amount"] = 7
            b["tilesets/0/6"] = np.full((TILE, TILE, 4), 200, np.uint8).tobytes()
            d["frames"][0]["cels"][0]["cell_data"]["(0, 0)"]["index"] = 6
        rewrite_pxo(p, new_tile)
        self.reexport()
        self.assertEqual(changed(before, snapshot(self.tmp)), [
            rel + "meadow.tscn", rel + "meadow_map.json", rel + "meadow_tileset.tres", rel + "tiles_meadow.png",
            "assets_src/dotwork/manifest_pixelorama.json"])
        with open(os.path.join(self.out, "meadow_tileset.tres"), encoding="utf-8") as f:
            self.assertIn("5:0/0 = 0", f.read())

    def test_frames_become_one_scene_each_and_a_removed_frame_leaves(self):
        ts, layers = own_map(np.random.default_rng(6))
        p = write_own(self.tmp, "meadow", ts, layers)

        def two(d, b):
            d["frames"].append(json.loads(json.dumps(d["frames"][0])))
            d["frames"][1]["cels"][0]["cell_data"] = {"(0, 0)": {"index": 5, "flip_h": False, "flip_v": False,
                                                                 "transpose": False}}
            for k in ("layer_1", "layer_2"):
                b[f"image_data/frames/2/{k}"] = b[f"image_data/frames/1/{k}"]
        rewrite_pxo(p, two)
        self.reexport()
        self.assertTrue(os.path.exists(os.path.join(self.out, "meadow_00.tscn")))
        self.assertTrue(os.path.exists(os.path.join(self.out, "meadow_01.tscn")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "meadow.tscn")))
        with open(os.path.join(self.out, "meadow_01.tscn"), encoding="utf-8") as f:
            self.assertEqual(godot_cells(f.read(), "ground"), [(0, 0, 0, 4, 0, 0)])
        write_own(self.tmp, "meadow", ts, layers)
        self.reexport()
        self.assertEqual(sorted(os.listdir(self.out)), ["meadow.tscn", "meadow_map.json", "meadow_tileset.tres",
                                                        "tiles_meadow.png"])
        self.assertFalse(any("meadow_0" in r["file"] for r in manifest_rows(self.tmp)["manifest_pixelorama.json"]))

    def test_with_engine_none_a_tilemap_gives_the_atlas_and_the_json_map(self):
        import godot
        ts, layers = own_map(np.random.default_rng(7))
        write_own(self.tmp, "meadow", ts, layers)
        godot.ENABLED = False
        self.s.conf["engine"] = self.s.conf["fixed"]["engine"] = "none"
        try:
            r = self.px.reexport(self.s.project, self.s.conf)
        finally:
            godot.ENABLED = True
            self.s.conf["engine"] = self.s.conf["fixed"]["engine"] = "godot"
        self.assertFalse(r["verified"])
        self.assertEqual(sorted(os.listdir(self.out)), ["meadow_map.json", "tiles_meadow.png"])

    def test_tilemaps_dotwork_cannot_draw_stop_before_writing(self):
        ts, layers = own_map(np.random.default_rng(8))
        p = write_own(self.tmp, "meadow", ts, layers)
        with open(p, "rb") as f:
            clean = f.read()
        before = snapshot(self.tmp)
        cases = {
            "isometric": lambda d, b: d["layers"][0].update(tile_shape=1),
            "isometric tileset": lambda d, b: d["tilesets"][0].update(tile_shape=1),
            "no tileset": lambda d, b: d["layers"][0].update(tileset_index=3),
            "blend mode": lambda d, b: d["layers"][0].update(blend_mode=3),
            "off the grid": lambda d, b: d["frames"][0]["cels"][0].update(offset="(3, 0)"),
            "tile buffer short": lambda d, b: b.update({"tilesets/0/2": b"\0" * 7}),
            "tile missing": lambda d, b: b.pop("tilesets/0/5"),
            "too many tiles": lambda d, b: d["tilesets"][0].update(tile_amount=5000),
            "huge tiles": lambda d, b: d["tilesets"][0].update(tile_size="(4096, 4096)"),
            "cell of no tile": lambda d, b: d["frames"][0]["cels"][0]["cell_data"].update({"(0, 0)": {"index": -1}}),
            "place-only of its own size": lambda d, b: d["layers"][0].update(place_only_mode=True,
                                                                             tile_size="(16, 16)"),
        }
        for what, edit in cases.items():
            with open(p, "wb") as f:
                f.write(clean)
            rewrite_pxo(p, edit)
            with self.assertRaises(fcore.ToolError, msg=what):
                self.reexport()
            self.assertEqual(changed(before, snapshot(self.tmp)), [], what)

    def test_godot_tile_map_data_in_both_forms(self):
        cells = [(0, 0, 0, 1, 0, 0), (-3, 7, 1, 2, 3, self.pt.FLIP_H | self.pt.TRANSPOSE)]
        for b64 in (False, True):
            text = self.pt.encode_cells(cells, b64)
            self.assertEqual(sorted(self.pt.decode_cells(text)), sorted(cells))
        self.assertEqual(self.pt.decode_cells('PackedByteArray("AAA=")'), [])
        with self.assertRaises(fcore.ToolError):
            self.pt.decode_cells("PackedByteArray(1, 0)")


class DotworkTilemapExam(unittest.TestCase):
    """A game's own map and TileSets into Pixelorama tilemap projects (dotwork.py pixelorama) and back: edited tiles
    land in their atlas slots, edited cells in the map scene; the TileSet is never rewritten."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_pxomap_")
        self.s = make_game(self.tmp)
        self.t = make_tiles(self.s)
        import pixelorama
        import pxo_tiles
        self.px, self.pt = pixelorama, pxo_tiles
        self.src = os.path.join(self.tmp, "assets_src", "pixelorama", "tilemaps")
        self.town = os.path.join(self.src, "town.pxo")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, **kw):
        return self.px.build(self.s.project, self.s.conf, **kw)

    def reexport(self):
        with stub_verify():
            return self.px.reexport(self.s.project, self.s.conf)

    def test_build_makes_a_project_per_map_and_per_tileset_no_map_uses(self):
        done = self.build()
        self.assertIn(self.town, done["written"])
        self.assertIn(os.path.join(self.src, "ledges_tileset.pxo"), done["written"])
        self.assertFalse(os.path.exists(os.path.join(self.src, "ground_town_tileset.pxo")))   # the map has it
        tm = self.pt.project(self.town)
        self.assertEqual([L["name"] for L in tm["layers"]], ["Base", "Water"])
        ts = tm["tilesets"][0]
        self.assertEqual(len(ts["tiles"]), 1 + 4 + 3)
        self.assertTrue(ts["data"][5]["user_data"].startswith("dotwork:1:0:0:"))
        self.assertEqual((ts["data"][5]["center"], ts["data"][5]["peers"][12]), (1, 1))   # terrain and its top side
        self.assertEqual(ts["data"][2]["probability"], 0.6)
        # the map as Godot draws it: each cell's atlas tile, flipped or transposed by its flags
        frame = self.px.read_pxo(self.town)["frames"][0]
        want = np.zeros_like(frame)
        for cells in (self.t["base"], self.t["wet"]):
            layer = np.zeros_like(frame)
            for x, y, si, ax, ay, alt in cells:
                atlas = self.t["grass"] if si == 0 else self.t["water"]
                tile = atlas[ay * TILE:(ay + 1) * TILE, ax * TILE:(ax + 1) * TILE]
                layer[y * TILE:(y + 1) * TILE, x * TILE:(x + 1) * TILE] = as_pixelorama_draws(
                    tile, alt & self.pt.FLIP_H, alt & self.pt.FLIP_V, alt & self.pt.TRANSPOSE)
            want = self.px._blend_rect(want, layer)
        self.assertTrue(np.array_equal(frame, want))
        done = self.build()
        self.assertEqual((done["written"], done["kept"]), ([], []))
        self.assertIn(self.town, done["unchanged"])

    def test_an_untouched_round_trip_changes_no_file(self):
        self.build()
        before = snapshot(self.tmp)
        r = self.reexport()
        self.assertTrue(r["ok"])
        self.assertEqual(changed(before, snapshot(self.tmp)), [])

    def test_edits_after_pixelorama_moved_its_tiles_land_in_their_slots(self):
        # Pixelorama's Auto tile mode removes a tile that no cell uses any more and shifts every index after it; the
        # tags follow the tiles. Here: tile 3 (grass 2:0) removed, tile 5 (water 0:0) edited, a Base cell set to
        # another tile.
        self.build()
        before = snapshot(self.tmp)
        with open(self.t["scene"], encoding="utf-8") as f:
            scene_before = f.read()

        def auto_mode(d, b):
            ts = d["tilesets"][0]
            n = ts["tile_amount"]
            data = [ts["tile_data"][str(j)] for j in range(n)]
            tiles = [b.pop(f"tilesets/0/{j}") for j in range(n)]
            del data[3], tiles[3]
            t = np.frombuffer(tiles[4], np.uint8).reshape(TILE, TILE, 4).copy()   # was tile 5: water 0:0
            t[1, 1] = (250, 0, 250, 255)
            tiles[4] = t.tobytes()
            ts.update(tile_amount=n - 1, tile_data={str(j): v for j, v in enumerate(data)})
            for j, t in enumerate(tiles):
                b[f"tilesets/0/{j}"] = t
            for c in d["frames"][0]["cels"]:
                cd = {}
                for k, v in c["cell_data"].items():
                    if v["index"] == 3:
                        v = dict(v, index=1)               # its cells were drawn over with tile 1 first
                    elif v["index"] > 3:
                        v = dict(v, index=v["index"] - 1)
                    cd[k] = v
                c["cell_data"] = cd
            d["frames"][0]["cels"][0]["cell_data"]["(4, 2)"] = {"index": 2, "flip_h": True, "flip_v": False,
                                                                "transpose": False}
        rewrite_pxo(self.town, auto_mode)
        r = self.reexport()
        self.assertTrue(r["ok"])
        self.assertEqual(changed(before, snapshot(self.tmp)), [
            "assets/art/tiles/town/overlay_water.png", "assets/maps/town.tscn", "assets_src/dotwork/manifest_town.json"])
        water = np.array(Image.open(os.path.join(self.tmp, "assets/art/tiles/town/overlay_water.png")).convert("RGBA"))
        self.assertEqual(tuple(water[1, 1]), (250, 0, 250, 255))
        water[1, 1] = self.t["water"][1, 1]
        self.assertTrue(np.array_equal(water[water[..., 3] > 0], self.t["water"][self.t["water"][..., 3] > 0]))
        with open(self.t["scene"], encoding="utf-8") as f:
            scene = f.read()
        base = sorted([(x, y, s, 0 if (s, ax) == (0, 2) else ax, ay, alt) for x, y, s, ax, ay, alt in self.t["base"]
                       if (x, y) != (4, 2)] + [(4, 2, 0, 1, 0, self.pt.FLIP_H)])
        self.assertEqual(godot_cells(scene, "Base"), base)
        self.assertEqual(godot_cells(scene, "Water"), sorted(self.t["wet"]))
        changed_lines = [(a, b) for a, b in zip(scene_before.split("\n"), scene.split("\n")) if a != b]
        self.assertEqual(len(changed_lines), 1)                       # only Base's tile_map_data, still base64
        self.assertTrue(changed_lines[0][1].startswith('tile_map_data = PackedByteArray("'))
        # the .pxo now holds edits: a build keeps it, --overwrite replaces it and keeps a .bak
        done = self.build()
        self.assertEqual(done["kept"], [self.town])
        done = self.build(overwrite=True)
        self.assertEqual(done["backups"], [self.town + ".bak"])
        self.assertFalse(self.pt.polished(self.town))

    def test_a_tile_pixelorama_added_stops_with_how_to_draw_instead(self):
        self.build()
        before = snapshot(self.tmp)

        def stack_mode(d, b):
            ts = d["tilesets"][0]
            ts["tile_data"][str(ts["tile_amount"])] = {"probability": 1.0, "user_data": "", "terrain_center_bit": -1}
            b[f"tilesets/0/{ts['tile_amount']}"] = np.full((TILE, TILE, 4), 9, np.uint8).tobytes()
            d["frames"][0]["cels"][0]["cell_data"]["(0, 0)"]["index"] = ts["tile_amount"]
            ts["tile_amount"] += 1
        rewrite_pxo(self.town, stack_mode)
        with self.assertRaises(fcore.ToolError) as e:
            self.reexport()
        self.assertIn("Manual", str(e.exception))
        self.assertEqual(changed(before, snapshot(self.tmp)), [])

    def test_two_projects_that_change_one_tile_differently_stop(self):
        self.build()
        before = snapshot(self.tmp)
        twin = os.path.join(self.src, "town_copy.pxo")
        shutil.copy(self.town, twin)
        for p, v in ((self.town, 1), (twin, 2)):
            def edit(d, b, v=v):
                t = np.frombuffer(b["tilesets/0/1"], np.uint8).reshape(TILE, TILE, 4).copy()
                t[0, 0] = (v, v, v, 255)
                b["tilesets/0/1"] = t.tobytes()
            rewrite_pxo(p, edit)
        with self.assertRaises(fcore.ToolError):
            self.reexport()
        self.assertEqual(changed(before, snapshot(self.tmp)), [])

    def test_a_project_without_edits_follows_the_game(self):
        # the ground lane ran again (new grass): an untouched project is rebuilt, and its re-export keeps the new art
        self.build()
        new = self.t["grass"].copy()
        new[..., :3] = 255 - new[..., :3]
        fcore.save_clean(Image.fromarray(new), os.path.join(self.tmp, "assets/art/tiles/town/base_grass.png"))
        before = snapshot(self.tmp)
        self.reexport()
        self.assertEqual(changed(before, snapshot(self.tmp)), [])
        done = self.build()
        self.assertEqual(done["written"], [self.town])
        self.assertEqual(done["backups"], [])


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

    def dotwork(self, *args):
        """dotwork.main in this process (so the Aseprite stand-in holds) with no Godot anywhere: GODOT_BIN unset."""
        import dotwork
        out, godot_bin = io.StringIO(), os.environ.pop("GODOT_BIN", None)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = dotwork.main(list(args) + ["--project", self.tmp])
        finally:
            if godot_bin is not None:
                os.environ["GODOT_BIN"] = godot_bin
        return code, out.getvalue()

    def test_reexport_with_engine_none_needs_no_godot(self):
        # #99: the re-export ended in Godot verify whatever the engine, so --engine none wrote the game, then exit 2
        code, out = self.dotwork("pixelorama", "--engine", "none")
        self.assertEqual(code, 0, out)
        pxo = os.path.join(self.tmp, "assets_src", "pixelorama", "fx", "slash.pxo")

        def edit(d, b):
            w, h = d["size_x"], d["size_y"]
            a = np.frombuffer(b["image_data/frames/1/layer_1"], np.uint8).reshape(h, w, 4).copy()
            a[0, 0] = (200, 60, 50, 255)
            b["image_data/frames/1/layer_1"] = a.tobytes()
        rewrite_pxo(pxo, edit)
        code, out = self.dotwork("pixelorama", "--reexport", "--engine", "none")
        self.assertEqual(code, 0, out)
        self.assertIn("[ OK ] re-exported (1 files changed; no Godot verify with --engine none)", out)
        self.ase._run = self.fake_aseprite()
        code, out = self.dotwork("aseprite", "--engine", "none")
        self.assertEqual(code, 0, out)
        code, out = self.dotwork("aseprite", "--reexport", "--engine", "none")
        self.assertEqual(code, 0, out)
        self.assertIn("[ OK ] re-exported (0 files changed; no Godot verify with --engine none)", out)


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

    def test_build_leaves_no_helper_files_in_the_sources(self):
        # #109: the palette BUILD_LUA loads was written beside each .aseprite and stayed in the game's tracked sources
        seen = []

        def run(conf, lua, name, params):
            if "list" in params:
                for k in ("list", "palette"):
                    self.assertTrue(os.path.isfile(params[k]), k)            # there while Aseprite runs
                    seen.append(os.path.relpath(params[k], self.tmp).replace(os.sep, "/"))
                open(params["out"], "wb").close()
            return "DOTWORK_ASE_OK"
        self.ase._run = run
        self.ase.build(self.s.project, self.s.conf)
        src = os.path.join(self.tmp, "assets_src", "aseprite")
        left = sorted(os.path.relpath(p, src).replace(os.sep, "/")
                      for p in glob.glob(os.path.join(src, "**", "*"), recursive=True) if os.path.isfile(p))
        self.assertEqual(left, ["characters/knight.aseprite", "fx/spark.aseprite", "single/barrel.aseprite"])
        self.assertTrue(seen and all(p.startswith("art_src/dotwork/") for p in seen), seen)
        self.assertEqual([p for p in seen if os.path.exists(os.path.join(self.tmp, p))], [])   # removed after

        def fails(conf, lua, name, params):
            raise fcore.JobError("Aseprite failed (1): stand-in")
        self.ase._run = fails
        shutil.rmtree(src)                                                    # a fresh build, so BUILD_LUA runs
        with self.assertRaises(fcore.JobError):
            self.ase.build(self.s.project, self.s.conf)
        self.assertEqual([p for p in seen if os.path.exists(os.path.join(self.tmp, p))], [])   # a failed run too

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

    def test_two_tags_with_one_name_stop(self):
        # issue #81 (live, Aseprite 1.3.18): a second attack_e tag over 2 frames numbered its frames from 00 too, so
        # it overwrote attack_e_00 and _01 and the shipped attack came back mixed, with verify passing. The current
        # EXPORT_LUA says DUPTAG and writes nothing; an export that still names one file twice is refused as well.
        self.sources()
        before = snapshot(self.tmp)
        frames = os.path.join(self.tmp, "assets", "art", "characters", "knight", "frames")
        walk0 = os.path.join(frames, "spr_knight_walk_e_00.png")

        def old_lua(conf, lua, name, params):                    # what the old EXPORT_LUA wrote and printed
            lines = []
            for fn in ("attack_e_00", "attack_e_01", "attack_e_02", "attack_e_03", "attack_e_00", "attack_e_01"):
                p = f"{params['prefix']}_{fn}.png"
                shutil.copyfile(walk0 if len(lines) > 3 else os.path.join(frames, f"spr_knight_{fn}.png"), p)
                lines.append(f"DOTWORK_ASE_PNG 0.125000 {p}")
            return "\n".join(lines)
        for run, says in ((old_lua, "two frames were exported as 'spr_knight_attack_e_00.png'"),
                          (lambda conf, lua, name, params: "DOTWORK_ASE_DUPTAG attack_e",
                           "two tags share the name 'attack_e'")):
            self.ase._run = run
            with stub_verify(), self.assertRaisesRegex(fcore.ToolError, says):
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
                    tag, dur, x, y, png = ln.split("|", 4)   # BUILD_LUA: each frame placed at x, y on the canvas
                    with Image.open(png) as im:
                        img = np.array(im.convert("RGBA"))
                    a = np.zeros((int(params["h"]), int(params["w"]), 4), np.uint8)
                    x, y = int(x), int(y)
                    a[y:y + img.shape[0], x:x + img.shape[1]] = img
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

    def test_the_palette_scan_makes_no_deprecated_pillow_call(self):
        # issue #185: the scan called Image.getdata, which warns under Pillow 12 and is gone in Pillow 14. A
        # DeprecationWarning is an error here, so the old call fails on Pillow 12; the older Pillow Python 3.8
        # installs has no get_flattened_data and still takes getdata without a warning
        img = np.zeros((4, 4, 4), np.uint8)
        img[1:3, 1:3] = (10, 20, 30, 255)
        img[0, 0] = (40, 50, 60, 128)                                              # one partly clear pixel
        png = os.path.join(self.tmp, "scan.png")
        Image.fromarray(img).save(png)
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            self.assertEqual(self.ase._palette_file([png], os.path.join(self.tmp, "scan.gpl")), (1, False))
        with open(os.path.join(self.tmp, "scan.gpl"), encoding="ascii") as f:
            self.assertIn(" 10  20  30\tc", f.read())

    def reexport(self):
        with stub_verify():
            return self.ase.reexport(self.s.project, self.s.conf)

    def test_clips_of_two_sizes_share_one_canvas_and_come_back_at_their_own_size(self):
        # issue #82 (live, Aseprite 1.3.18): attack_e at a bigger canvas, as a second pack can write it. The sprite
        # took the first frame's size, and an untouched round trip shipped every other clip padded to it, art in the
        # top left (then build refused such a character). Now the clips share the largest canvas, each centred on
        # its bottom edge, and each comes back at its own size.
        w, h = grow_clip(self.tmp, "attack_e")
        before = snapshot(self.tmp)
        self.build()
        knight = next(b for b in self.built if b["out"] == self.knight)
        self.assertEqual((knight["w"], knight["h"]), (w, h))
        with open(self.knight, encoding="utf-8") as f:
            walk0 = json.load(f)["frames"][4]                             # attack_e's 4 frames, then walk_e
        a = np.frombuffer(bytes.fromhex(walk0["rgba"]), np.uint8).reshape(h, w, 4)
        x, y = (w - W) // 2, h - H                                        # centred, feet on the bottom edge
        game = os.path.join(self.tmp, "assets", "art", "characters", "knight", "frames")
        with Image.open(os.path.join(game, "spr_knight_walk_e_00.png")) as im:
            self.assertTrue(np.array_equal(a[y:, x:x + W], np.array(im.convert("RGBA"))))
        self.assertEqual(self.build()["kept"], [])                        # 0.8.2 reported it "kept" every time
        self.reexport()
        self.assertEqual(changed(before, snapshot(self.tmp)), [])         # untouched: every clip at its own size

        def paint(i, px, py):
            def change(data):
                fr = data["frames"][i]
                arr = np.frombuffer(bytes.fromhex(fr["rgba"]), np.uint8).reshape(h, w, 4).copy()
                arr[py, px] = (200, 60, 50, 255)
                fr["rgba"] = arr.tobytes().hex()
            return change
        self.polish(self.knight, paint(4, x + 5, y + 5))                  # inside walk_e's box
        self.reexport()
        with Image.open(os.path.join(game, "spr_knight_walk_e_00.png")) as im:
            self.assertEqual(im.size, (W, H))
            self.assertEqual(im.convert("RGBA").getpixel((5, 5)), (200, 60, 50, 255))
        with Image.open(os.path.join(game, "spr_knight_attack_e_00.png")) as im:
            self.assertEqual(im.size, (w, h))
        polished = snapshot(self.tmp)
        self.polish(self.knight, paint(5, 0, 0))                          # outside it: refused, nothing written
        with self.assertRaisesRegex(fcore.ToolError, r"spr_knight_walk_e_01\.png has art outside clip walk_e's "
                                                     r"24x32 box"):
            self.reexport()
        self.assertEqual(changed(polished, snapshot(self.tmp)), [])

    def test_effect_frames_of_two_sizes_stop_before_anything_is_written(self):
        # an effect has no clips to tell apart: its frames must be one size, as before
        fx = os.path.join(self.tmp, "assets", "art", "fx", "spark", "spr_fx_spark_01.png")
        fcore.save_clean(Image.new("RGBA", (W + 16, H + 16), (0, 0, 0, 0)), fx)
        with self.assertRaisesRegex(fcore.ToolError, r"spark\.aseprite: frames of 2 sizes \(24x32, 40x48\)"):
            self.build()
        self.assertEqual(self.built, [])
        self.assertEqual(glob.glob(os.path.join(self.src, "**", "*.aseprite"), recursive=True), [])

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


LIVE_ASEPRITE = os.environ.get("ASEPRITE_BIN", "")
# the live exam's hand-built .aseprite: <frames> frames of w x h, each a flat colour, tags given as "name:from:to,..."
FIXTURE_LUA = r'''
local p = app.params
local spr = Sprite(tonumber(p.w), tonumber(p.h), ColorMode.RGB)
local n = tonumber(p.frames)
for i = 2, n do spr:newEmptyFrame() end
for i = 1, n do
  local img = Image(spr.spec)
  img:clear(Color{ r = 40 * i, g = 100, b = 200, a = 255 })
  spr:newCel(spr.layers[1], i, img, Point(0, 0))
end
for name, a, b in p.tags:gmatch("([^:,]+):(%d+):(%d+)") do
  local t = spr:newTag(tonumber(a), tonumber(b))
  t.name = name
end
spr:saveAs(p.out)
print("DOTWORK_ASE_OK fixture")
'''


@unittest.skipUnless(LIVE_ASEPRITE and os.path.isfile(LIVE_ASEPRITE),
                     "set ASEPRITE_BIN to run EXPORT_LUA in a real Aseprite")
class AsepriteLiveExam(unittest.TestCase):
    """EXPORT_LUA run in a real Aseprite (batch mode) on .aseprite fixtures the exam builds there; skipped without
    ASEPRITE_BIN. The stand-in exams above cover the Python half."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_aselive_")
        self.s = make_game(self.tmp)                                  # binds Dotwork's work folder to the game
        import aseprite
        self.ase = aseprite

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fixture(self, name, tags, frames=4, w=8, h=8):
        out = os.path.join(self.tmp, "src", name + ".aseprite")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        self.ase._run(self.s.conf, FIXTURE_LUA, "ase_fixture.lua",
                      {"w": w, "h": h, "frames": frames, "tags": tags, "out": out})
        return out

    def export(self, file):
        folder = os.path.join(self.tmp, "export")
        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder)
        pngs, bad = self.ase._export(self.s.conf, file, os.path.join(folder, "spr_x"))
        return [os.path.basename(p) for p, _ in pngs], bad, sorted(os.listdir(folder))

    def test_two_tags_with_one_name_export_nothing(self):
        # issue #81: the second tag's frames overwrote the first one's (spr_x_attack_e_00 and _01)
        for tags in ("attack_e:1:4,attack_e:3:4", "attack_e:1:4,Attack_E:3:4"):
            names, bad, written = self.export(self.fixture("dup", tags))
            self.assertEqual((names, written), ([], []), tags)
            self.assertIn("two tags share the name", bad, tags)
        names, bad, written = self.export(self.fixture("ok", "attack_e:1:2,walk_e:3:4"))
        self.assertIsNone(bad)
        self.assertEqual(names, ["spr_x_attack_e_00.png", "spr_x_attack_e_01.png", "spr_x_walk_e_00.png",
                                 "spr_x_walk_e_01.png"])
        self.assertEqual(written, sorted(names))

    def test_clips_of_two_sizes_round_trip_untouched(self):
        # issue #82's repro: attack_e at 40x48, walk_e at 24x32. The sprite took the first frame's size and an
        # untouched round trip changed every walk frame (padded, art in the top left). BUILD_LUA now places each
        # clip centred on the bottom edge, and the re-export crops each back: nothing changes, and a second build
        # finds the source still showing the game's frames.
        grow_clip(self.tmp, "attack_e")
        before = snapshot(self.tmp)
        done = self.ase.build(self.s.project, self.s.conf)
        knight = os.path.join(self.tmp, "assets_src", "aseprite", "characters", "knight.aseprite")
        self.assertIn(knight, done["written"])
        with stub_verify():
            self.ase.reexport(self.s.project, self.s.conf)
        self.assertEqual(changed(before, snapshot(self.tmp)), [])
        done = self.ase.build(self.s.project, self.s.conf)
        self.assertEqual((done["kept"], done["written"]), ([], []))


LIVE_PIXELORAMA = os.environ.get("PIXELORAMA_BIN", "")
PXO_TIMEOUT = 180          # s per Pixelorama run (one takes about 3 s; a job that never quits is killed)
PXO_EXT = "DotworkLive"    # the exam's Pixelorama extension, installed only in the exam's own user folder
# Pixelorama has no command-line save and its export build ignores Godot's --script, so the exam drives it with a tiny
# extension (a zip in user://extensions, enabled in user://config.ini; HandleExtensions.gd): when DOTWORK_PXO_JOB
# holds a job (JSON: files [{src, out, edits [[frame, x, y, r, g, b, a]], cells [[layer, x, y, tile]], tiles [[tileset,
# tile, x, y, r, g, b, a]]}]), it opens each .pxo with OpenSave.open_pxo_file, sets the pixels (canvas coordinates,
# layer 1; the cel grows as a pencil stroke grows it), places tiles (frame 1, canvas cells, as the tile tool's
# set_index does) and draws into tiles (then every tilemap cel is redrawn from its tiles), saves with
# OpenSave.save_pxo_file and quits. Exports use Pixelorama's own CLI (--export --output).
PXO_EXT_GD = '''extends Node

func _ready() -> void:
    var job_text := OS.get_environment("DOTWORK_PXO_JOB")
    if job_text.is_empty():
        return
    for i in 3:
        await get_tree().process_frame
    var job: Dictionary = JSON.parse_string(job_text)
    for item: Dictionary in job["files"]:
        OpenSave.open_pxo_file(item["src"])
        for i in 2:   # a tilemap cel is redrawn from its tiles in a deferred call: let it run before the save
            await get_tree().process_frame
        var project: Project = Global.projects.back()
        for e: Array in item.get("edits", []):
            var cel: PixelCel = project.frames[int(e[0])].cels[0]
            var local := cel.ensure_canvas_point_in_bounds(Vector2i(int(e[1]), int(e[2])))
            cel.image.set_pixelv(local, Color8(int(e[3]), int(e[4]), int(e[5]), int(e[6])))
        for e: Array in item.get("cells", []):
            var tcel: CelTileMap = project.frames[0].cels[int(e[0])]
            var at := Vector2i(int(e[1]), int(e[2])) - tcel.offset / tcel.get_tile_size()
            tcel.set_index(tcel.get_cell_at(at), int(e[3]), true, false, false, false)
        for e: Array in item.get("tiles", []):
            var tile: Image = project.tilesets[int(e[0])].tiles[int(e[1])].image
            tile.set_pixel(int(e[2]), int(e[3]), Color8(int(e[4]), int(e[5]), int(e[6]), int(e[7])))
            for frame in project.frames:
                for c in frame.cels:
                    if c is CelTileMap:
                        c.update_cel_portions()
        var ok := OpenSave.save_pxo_file(item["out"], false, project)
        print("DOTWORK_PXO saved %s %s" % [item["out"], ok])
    print("DOTWORK_PXO_OK")
    get_tree().quit()
'''
PXO_EXT_TSCN = ('[gd_scene load_steps=2 format=3]\n\n[ext_resource type="Script" '
                f'path="res://src/Extensions/{PXO_EXT}/live.gd" id="1"]\n\n[node name="{PXO_EXT}" type="Node"]\n'
                'script = ExtResource("1")\n')


@unittest.skipUnless(LIVE_PIXELORAMA and os.path.isfile(LIVE_PIXELORAMA),
                     "set PIXELORAMA_BIN to run the .pxo round trip in a real Pixelorama")
class PixeloramaLiveExam(unittest.TestCase):
    """Dotwork's .pxo files opened, saved and exported by a real Pixelorama (headless; checked with 1.2.4 on
    Windows), then re-exported by Dotwork; skipped without PIXELORAMA_BIN. Pixelorama runs with its user folder in the
    exam's temp folder (APPDATA, XDG_DATA_HOME), so your own settings, recent files and extensions are not touched.
    Headless, Pixelorama blends layers on the CPU (DrawingAlgos.blend_layers_headless), Normal layers only; with
    PIXELORAMA_WINDOW=1 as well, one case opens Pixelorama's window for a few seconds to export through its GPU
    shader, the only composite that applies blend modes, clipping masks and groups that blend (#66)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_pxolive_")
        self.s = make_game(self.tmp)
        import pixelorama
        self.px = pixelorama
        self.before = snapshot(self.tmp)                              # the game before any Pixelorama step
        self.px.build(self.s.project, self.s.conf)
        self.src = os.path.join(self.tmp, "assets_src", "pixelorama")
        self.sources = [os.path.join(self.src, k, n) for k, n in
                        (("characters", "knight.pxo"), ("fx", "spark.pxo"), ("single", "barrel.pxo"))]
        self.user = os.path.join(self.tmp, "pixelorama_user")
        ext = os.path.join(self.user, "pixelorama", "extensions")
        os.makedirs(ext)
        base = f"src/Extensions/{PXO_EXT}/"
        with zipfile.ZipFile(os.path.join(ext, PXO_EXT + ".zip"), "w") as z:
            z.writestr(base + "extension.json", json.dumps({
                "name": PXO_EXT, "display_name": "Dotwork live exam", "nodes": ["Main.tscn"],
                "supported_api_versions": list(range(5, 21))}))
            z.writestr(base + "live.gd", PXO_EXT_GD)
            z.writestr(base + "Main.tscn", PXO_EXT_TSCN)
        with open(os.path.join(self.user, "pixelorama", "config.ini"), "w", encoding="utf-8") as f:
            f.write(f"[extensions]\n\n{PXO_EXT}=true\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pixelorama(self, args, job=None, window=False):
        """Pixelorama's output (its exit code is not used: with a window, 1.2.4 crashes on --quit after exporting)."""
        env = dict(os.environ, APPDATA=self.user, XDG_DATA_HOME=self.user)
        env.pop("DOTWORK_PXO_JOB", None)
        if job is not None:
            env["DOTWORK_PXO_JOB"] = json.dumps(job)
        p = subprocess.run([LIVE_PIXELORAMA] + ([] if window else ["--headless"]) + args, env=env,
                           capture_output=True, encoding="utf-8",
                           errors="replace", timeout=PXO_TIMEOUT)
        return p.stdout + p.stderr

    def save(self, files, cells=(), tiles=()):
        """[(src, out, edits)] opened and saved by Pixelorama in one run (cells and tiles: tilemap edits in each)."""
        job = {"files": [{"src": s.replace(os.sep, "/"), "out": o.replace(os.sep, "/"), "edits": e or [],
                          "cells": list(cells), "tiles": list(tiles)} for s, o, e in files]}
        log = self.pixelorama([], job)
        self.assertIn("DOTWORK_PXO_OK", log, log[-2000:])
        self.assertEqual(log.count(" true\n"), len(files), log[-2000:])

    def export(self, pxo, window=False):
        """Pixelorama's own CLI export of every frame: [H x W x 4 uint8], in frame order."""
        folder = os.path.join(self.tmp, "pxo_export_" + os.path.basename(pxo)[:-4] + ("_window" if window else ""))
        os.makedirs(folder)
        self.pixelorama(["--quit", "--", pxo.replace(os.sep, "/"), "--export", "--output",
                         folder.replace(os.sep, "/") + "/f.png"], window=window)
        return [np.array(Image.open(p).convert("RGBA")) for p in sorted(glob.glob(os.path.join(folder, "*.png")))]

    def reexport(self):
        with stub_verify():
            return self.px.reexport(self.s.project, self.s.conf)

    def test_open_save_export_and_reexport_change_nothing(self):
        # #67: what the released 1.2.4 saves (pxo_version 8, cels cropped to their pixels) is read back exactly
        import handpolish
        before = {p: self.px.read_pxo(p)["frames"] for p in self.sources}
        self.save([(p, p, None) for p in self.sources])
        with zipfile.ZipFile(self.sources[0]) as z:
            d = json.loads(z.read("data.json"))
        self.assertEqual((d["pxo_version"], d["pixelorama_version"][:6]), (8, "v1.2.4"))
        self.assertTrue(any(c["image_size"] != "Vector2i(%d, %d)" % (W, H) for f in d["frames"] for c in f["cels"]))
        for p in self.sources:
            got = self.px.read_pxo(p)["frames"]
            ours = self.export(p)                                       # Pixelorama's own render of its save
            self.assertEqual(len(ours), len(got), p)
            for want, have, theirs in zip(before[p], got, ours):
                self.assertTrue(handpolish.same_look(have, want), p)
                self.assertTrue(np.array_equal(theirs[..., 3], have[..., 3]), p)
                self.assertTrue(np.array_equal(theirs[theirs[..., 3] > 0], have[have[..., 3] > 0]), p)
            # Pixelorama saves an export folder in each file (the last opened file's folder, the Desktop on a fresh
            # user folder; the .pxo's own folder once it is blank)
            self.assertNotEqual(self.px.export_folder(p), "", p)
        r = self.reexport()
        self.assertTrue(r["ok"])
        self.assertEqual(changed(self.before, snapshot(self.tmp)), [])   # every PNG, sheet, .tres and manifest
        done = self.px.build(self.s.project, self.s.conf)
        self.assertEqual((done["kept"], len(done["unchanged"])), ([], 3))

    def test_normal_layers_and_animated_opacity_equal_pixelorama_exactly(self):
        # #66, the headless half: layers of partly clear pixels at layer and cel opacity below 100 %, opacity
        # keyframes (linear, Quad in-out, Sine out, constant), a pass-through group at 40 % (Pixelorama ignores a
        # pass-through group's own opacity), a hidden layer in it and a cel moved under the art by its z-index.
        # Pixelorama works in 32-bit floats, truncates alpha x opacity to 8 bits, blends (Color.blend) and truncates
        # the result: so does Dotwork, and every frame comes out the same, byte for byte.
        rng = np.random.default_rng(66)
        keys = [(0, 0.2, 0, 0), (3, 0.9, 4, 2), (5, 0.4, 1, 1), (6, 0.66, 999, 0)]
        anim = 'Dictionary[String, Dictionary]({\n"opacity": {\n%s\n}\n})' % ",\n".join(
            '%d: {\n"ease": %d,\n"id": %d,\n"trans": %d,\n"value": %r\n}' % (f, e, i, t, v)
            for i, (f, v, t, e) in enumerate(keys))

        def partly_clear():
            a = rng.integers(0, 256, (H, W, 4), dtype=np.uint8)
            a[..., 3] = rng.choice([0, 1, 64, 128, 200, 254, 255], (H, W))
            return a

        def layers(d, b):
            art = d["layers"][0]
            d["layers"] += [dict(art, name="glaze", opacity=0.5),
                            dict(art, name="pulse", parent=4, animated_params=anim),
                            dict(art, name="hidden", parent=4, visible=False),
                            dict(art, name="group", type=1, blend_mode=-2, opacity=0.4, expanded=True)]
            for fi, fr in enumerate(d["frames"]):
                fr["cels"] += [{"opacity": 0.8 if fi == 0 else 1.0, "z_index": -1 if fi == 2 else 0},
                               {"opacity": 0.9 if fi == 4 else 1.0, "z_index": 0},
                               {"opacity": 1.0, "z_index": 0}, {"opacity": 1.0, "z_index": 0}]
                for li in (2, 3):
                    b[f"image_data/frames/{fi + 1}/layer_{li}"] = partly_clear().tobytes()
                b[f"image_data/frames/{fi + 1}/layer_4"] = np.full((H, W, 4), 255, np.uint8).tobytes()
        knight = self.sources[0]
        rewrite_pxo(knight, layers)
        pj = self.px.read_pxo(knight)
        self.assertFalse(pj["windowed"])
        theirs = self.export(knight)
        self.assertEqual(len(theirs), len(pj["frames"]))
        for i, (a, b) in enumerate(zip(pj["frames"], theirs)):
            self.assertTrue(np.array_equal(a, b), i)

    def test_one_layer_comes_back_as_it_is(self):
        # A frame of one layer at full opacity (what Dotwork writes) is copied as it is, so an untouched trip changes
        # no file. Pixelorama's own export blends even that layer over a clear canvas (Color.blend, truncated): a
        # partly clear pixel can come out one step darker there, never anything else.
        rng = np.random.default_rng(67)

        def edges(d, b):
            for fi in range(len(d["frames"])):
                a = np.frombuffer(b[f"image_data/frames/{fi + 1}/layer_1"], np.uint8).reshape(H, W, 4).copy()
                a[..., 3][a[..., 3] > 0] = rng.choice([3, 40, 128, 201, 255], int((a[..., 3] > 0).sum()))
                b[f"image_data/frames/{fi + 1}/layer_1"] = a.tobytes()
        knight = self.sources[0]
        rewrite_pxo(knight, edges)
        with zipfile.ZipFile(knight) as z:
            cels = [np.frombuffer(z.read(f"image_data/frames/{i + 1}/layer_1"), np.uint8).reshape(H, W, 4)
                    for i in range(7)]
        have = self.px.read_pxo(knight)["frames"]
        theirs = self.export(knight)
        darker = 0
        for cel, a, b in zip(cels, have, theirs):
            self.assertTrue(np.array_equal(a, cel))
            self.assertTrue(np.array_equal(a[..., 3], b[..., 3]))
            seen = a[..., 3] > 0
            diff = b[seen].astype(int) - a[seen]
            self.assertTrue(set(np.unique(diff).tolist()) <= {-1, 0})
            darker += int((diff != 0).any(-1).sum())
        self.assertGreater(darker, 0)                # the case is real: some pixels did come out darker

    @unittest.skipUnless(os.environ.get("PIXELORAMA_WINDOW") == "1",
                         "set PIXELORAMA_WINDOW=1 to export through Pixelorama's window (it opens for a few seconds)")
    def test_blend_modes_clipping_and_groups_follow_pixelorama_with_a_window(self):
        # #66, the windowed half: Pixelorama applies blend modes, clipping masks and groups that blend only on the
        # GPU. Dotwork follows its shader in 32-bit floats; the GPU rounds values near a half step its own way, so a
        # pixel can land a step or two off. Its command-line export (headless) leaves these features out altogether.
        rng = np.random.default_rng(68)

        def partly_clear():
            a = rng.integers(0, 256, (H, W, 4), dtype=np.uint8)
            a[..., 3] = rng.choice([0, 64, 128, 200, 255, 255], (H, W))
            return a

        def layers(d, b):
            art = d["layers"][0]
            d["layers"] += [dict(art, name="shade", blend_mode=3, opacity=0.8),          # Multiply
                            dict(art, name="rim", clipping_mask=True),                  # clipped to the shade
                            dict(art, name="g1", parent=5),
                            dict(art, name="g2", parent=5, blend_mode=7, opacity=0.7),   # Screen, in the group
                            dict(art, name="group", type=1, blend_mode=0, opacity=0.6, expanded=True),
                            dict(art, name="tint", blend_mode=19)]                      # Color
            for fi, fr in enumerate(d["frames"]):
                fr["cels"] += [{"opacity": 0.9 if fi == 1 else 1.0, "z_index": 0} for _ in range(6)]
                for li in (2, 3, 4, 5, 7):
                    b[f"image_data/frames/{fi + 1}/layer_{li}"] = partly_clear().tobytes()
        knight = self.sources[0]
        rewrite_pxo(knight, layers)
        pj = self.px.read_pxo(knight)
        self.assertTrue(pj["windowed"])
        gpu, cli = self.export(knight, window=True), self.export(knight)
        self.assertEqual(len(gpu), len(pj["frames"]))
        total = same = near = 0
        for a, b in zip(pj["frames"], gpu):
            d = steps_apart(a, b)
            shown = (a[..., 3] > 0) | (b[..., 3] > 0)
            total, same, near = total + shown.sum(), same + (shown & (d == 0)).sum(), near + (shown & (d <= 2)).sum()
        self.assertGreaterEqual(near, 0.99 * total)
        self.assertGreaterEqual(same, 0.8 * total)
        self.assertFalse(all(np.array_equal(a, b) for a, b in zip(gpu, cli)))

    def test_a_pixel_set_in_pixelorama_lands_only_in_its_frame(self):
        k = "assets/art/characters/knight/"
        old = np.array(Image.open(os.path.join(self.tmp, k, "frames", "spr_knight_attack_e_01.png")).convert("RGBA"))
        self.assertEqual(old[0, 0, 3], 0)            # outside the art: Pixelorama 1.2.4 grows the cropped cel to it
        self.save([(self.sources[0], self.sources[0], [[1, 0, 0, 200, 60, 50, 255]])])   # attack_e frame 1
        r = self.reexport()
        self.assertTrue(r["ok"])
        self.assertEqual(changed(self.before, snapshot(self.tmp)),
                         [k + "frames/spr_knight_attack_e_01.png", k + "knight_attack_e_sheet.png",
                          "assets_src/dotwork/manifest_knights.json", "assets_src/dotwork/manifest_knights_old.json"])
        new = np.array(Image.open(os.path.join(self.tmp, k, "frames", "spr_knight_attack_e_01.png")).convert("RGBA"))
        self.assertEqual(tuple(new[0, 0]), (200, 60, 50, 255))
        new[0, 0] = old[0, 0]
        # nothing else in the frame moved (the colour under clear pixels is not kept by any editor)
        self.assertTrue(np.array_equal(new[..., 3], old[..., 3]))
        self.assertTrue(np.array_equal(new[new[..., 3] > 0], old[old[..., 3] > 0]))

    def test_a_tilemap_pixelorama_saved_round_trips_and_exports_as_dotwork_draws_it(self):
        ts, layers = own_map(np.random.default_rng(90))
        p = write_own(self.tmp, "meadow", ts, layers)
        self.reexport()
        before = snapshot(self.tmp)
        self.save([(p, p, None)])
        with zipfile.ZipFile(p) as z:
            d = json.loads(z.read("data.json"))
        self.assertEqual((d["pxo_version"], d["layers"][0]["type"]), (8, 3))
        r = self.reexport()
        self.assertTrue(r["ok"])
        self.assertEqual(changed(before, snapshot(self.tmp)), [])
        # Pixelorama's drawing of each tilemap layer is the cel image it saved (version 8: its own size and offset);
        # its command-line export draws tilemap layers empty (their cels are drawn in a deferred call, after it)
        import pxo_tiles
        tm = pxo_tiles.project(p)
        W_, H_ = tm["size"]
        with zipfile.ZipFile(p) as z:
            for li, L in enumerate(tm["layers"]):
                cel = d["frames"][0]["cels"][li]
                cw, ch = self.px._vec2i(cel["image_size"], p, "image_size")
                ox, oy = self.px._vec2i(cel["offset"], p, "offset")
                buf = np.frombuffer(z.read(f"image_data/frames/1/layer_{li + 1}"), np.uint8).reshape(ch, cw, 4)
                theirs = np.zeros((H_, W_, 4), np.uint8)
                x0, y0, x1, y1 = max(ox, 0), max(oy, 0), min(ox + cw, W_), min(oy + ch, H_)
                theirs[y0:y1, x0:x1] = buf[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
                off, cells, _ = L["frames"][0]
                ours = pxo_tiles.render(tm["tilesets"][L["tileset"]], off, cells, W_, H_)
                self.assertTrue(np.array_equal(ours, theirs), L["name"])   # every flip and transpose, drawn alike
        self.assertEqual(self.export(p)[0][..., 3].max(), 0)

    def test_a_cell_and_a_tile_edited_in_pixelorama_change_only_the_atlas_and_the_map(self):
        ts, layers = own_map(np.random.default_rng(91))
        p = write_own(self.tmp, "meadow", ts, layers)
        self.reexport()
        before = snapshot(self.tmp)
        self.save([(p, p, None)], cells=[[1, 5, 0, 3]], tiles=[[0, 4, 2, 2, 250, 10, 20, 255]])
        r = self.reexport()
        self.assertTrue(r["ok"])
        rel = "assets/art/tilemaps/meadow/"
        self.assertEqual(changed(before, snapshot(self.tmp)), [
            rel + "meadow.tscn", rel + "meadow_map.json", rel + "tiles_meadow.png",
            "assets_src/dotwork/manifest_pixelorama.json"])
        atlas = np.array(Image.open(os.path.join(self.tmp, rel, "tiles_meadow.png")).convert("RGBA"))
        self.assertEqual(tuple(atlas[2, 3 * TILE + 2]), (250, 10, 20, 255))   # tile 4 at slot 3
        with open(os.path.join(self.tmp, rel, "meadow.tscn"), encoding="utf-8") as f:
            self.assertIn((5, 0, 0, 2, 0, 0), godot_cells(f.read(), "top"))

    def test_a_game_map_edited_in_pixelorama_changes_its_atlas_and_scene_only(self):
        t = make_tiles(self.s)
        self.px.build(self.s.project, self.s.conf)
        town = os.path.join(self.src, "tilemaps", "town.pxo")
        before = snapshot(self.tmp)
        self.save([(town, town, None)])                               # untouched: no file changes
        r = self.reexport()
        self.assertTrue(r["ok"])
        self.assertEqual(changed(before, snapshot(self.tmp)), [])
        import pxo_tiles
        tm = pxo_tiles.project(town)
        self.assertIsNotNone(tm["meta"])                              # Pixelorama kept the build record
        tags = [d["user_data"] for d in tm["tilesets"][0]["data"]]
        self.assertTrue(tags[5].startswith("dotwork:1:0:0:"))         # and each tile's slot
        self.save([(town, town, None)], cells=[[0, 4, 2, tags.index(next(u for u in tags if
                                                                         u.startswith("dotwork:0:1:0:")))]],
                  tiles=[[0, 5, 1, 1, 250, 0, 250, 255]])
        r = self.reexport()
        self.assertTrue(r["ok"])
        self.assertEqual(changed(before, snapshot(self.tmp)), [
            "assets/art/tiles/town/overlay_water.png", "assets/maps/town.tscn", "assets_src/dotwork/manifest_town.json"])
        water = np.array(Image.open(os.path.join(self.tmp, "assets/art/tiles/town/overlay_water.png")).convert("RGBA"))
        self.assertEqual(tuple(water[1, 1]), (250, 0, 250, 255))
        with open(t["scene"], encoding="utf-8") as f:
            self.assertIn((4, 2, 0, 1, 0, 0), godot_cells(f.read(), "Base"))


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)
