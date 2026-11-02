#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_vfx.py
# Purpose : offline exam for the vfx lane (lane_vfx.py): frame counts and canvas sizes, one-shots that end on an empty
#           frame and loops that wrap, colours taken only from the ramp, trails that fade along their length, particle
#           scenes that point at a real texture and a ParticleProcessMaterial with the expected one_shot / amount, spec
#           errors that exit 2 before anything is written, and the verify loader's particle check. No GPU, ComfyUI or
#           Godot needed.
# Usage   : python -I -B tools/art/dotwork/tests/test_vfx.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DOTWORK = os.path.dirname(HERE)
sys.path.insert(0, DOTWORK)   # -I leaves the script's folder off sys.path
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import fcore  # noqa: E402

SPRITE_KINDS = ("arrow", "bolt", "orb", "dust", "footstep", "landing", "pickup_sparkle", "level_up")
PARTICLE_KINDS = ("dust_particles", "sparkle_particles", "ember_particles")
PROJECTILES = ("arrow", "bolt", "orb")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def colours(a):
    """The set of RGB colours of a frame's opaque pixels."""
    return {tuple(int(v) for v in c) for c in a[a[..., 3] > 0][:, :3]}


def ramp_set(ramp):
    return {tuple(int(v) for v in c) for c in ramp}


def blocks(text):
    """{header: body} for every [section] of a Godot text resource."""
    out = {}
    for m in re.finditer(r"^(\[[^\]]+\])\n(.*?)(?=^\[|\Z)", text, re.S | re.M):
        out[m.group(1)] = m.group(2)
    return out


def block(text, head_re):
    found = [b for h, b in blocks(text).items() if re.search(head_re, h)]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} sections match {head_re}")
    return found[0]


def prop(body, key):
    m = re.search(rf"^{re.escape(key)} = (.*)$", body, re.M)
    return m.group(1) if m else None


def gradient(text, gid):
    """(offsets, [(r, g, b, a) in 0..255 / 0..1]) of a Gradient sub-resource."""
    body = block(text, rf'type="Gradient" id="{gid}"')
    offs = [float(v) for v in re.search(r"offsets = PackedFloat32Array\(([^)]*)\)", body).group(1).split(",")]
    vals = [float(v) for v in re.search(r"colors = PackedColorArray\(([^)]*)\)", body).group(1).split(",")]
    cols = [(round(vals[i] * 255), round(vals[i + 1] * 255), round(vals[i + 2] * 255), vals[i + 3])
            for i in range(0, len(vals), 4)]
    return offs, cols


def luma(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


class VfxExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_vfx_")
        os.makedirs(os.path.join(self.tmp, "art_src", "dotwork"))
        with open(os.path.join(self.tmp, "project.godot"), "w") as f:
            f.write("config_version=5\n")
        import engine
        import godot
        s = fcore.Settings(self.tmp)
        fcore.bind(s)
        engine.bind(s.conf)
        godot.ENABLED = True
        self.art = os.path.join(self.tmp, "assets", "art", "fx", "vfx")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def lane(self):
        try:
            import lane_vfx
        except ImportError:
            self.fail("lane_vfx is missing")
        return lane_vfx

    def pack(self, entries, *extra):
        import dotwork
        spec = os.path.join(self.tmp, "vfx_spec.json")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"name": "vfx", "vfx": entries}, f)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = dotwork.main(["pack", "--spec", spec, "--project", self.tmp, "--no-verify", *extra])
        return code, out.getvalue() + err.getvalue()

    # ---- frame counts and sizes
    def test_frame_counts_and_sizes(self):
        v = self.lane()
        self.assertEqual(set(v.KINDS), set(SPRITE_KINDS))
        self.assertEqual(set(v.PARTICLES), set(PARTICLE_KINDS))
        for kind in SPRITE_KINDS:
            _, size, n = v.KINDS[kind][:3]
            ramp = v.ramp_of({"name": kind}, kind)
            fr = v.frames(kind, size, n, 7601, ramp)
            self.assertEqual(len(fr), n, kind)
            self.assertTrue(all(f.shape == (size, size, 4) and f.dtype == np.uint8 for f in fr), kind)
            self.assertEqual([f.tobytes() for f in fr], [f.tobytes() for f in v.frames(kind, size, n, 7601, ramp)])
            if kind in PROJECTILES:
                tr = v.trail_frames(kind, size, n, 7601, ramp)
                self.assertEqual(len(tr), n, kind)
                self.assertTrue(all(f.shape == (size, 2 * size, 4) for f in tr), kind)
        code, out = self.pack([{"name": "bow", "kind": "arrow", "size": 20, "frames": 6, "fps": 15},
                               {"name": "puff", "kind": "dust", "size": 30, "frames": 9},
                               {"name": "spark", "kind": "pickup_sparkle"}])
        self.assertEqual(code, 0, out)
        d = os.path.join(self.art, "bow")
        self.assertEqual(sorted(f for f in os.listdir(d) if re.match(r"spr_vfx_bow_\d\d\.png$", f)),
                         [f"spr_vfx_bow_{i:02d}.png" for i in range(6)])
        self.assertEqual(len([f for f in os.listdir(d) if f.startswith("spr_vfx_bow_trail_")]), 6)
        with Image.open(os.path.join(d, "spr_vfx_bow_03.png")) as im:
            self.assertEqual(im.size, (20, 20))
        with Image.open(os.path.join(d, "vfx_bow_sheet.png")) as im:
            self.assertEqual(im.size, (120, 20))
        with Image.open(os.path.join(d, "vfx_bow_trail_sheet.png")) as im:
            self.assertEqual(im.size, (240, 20))
        meta = json.loads(read(os.path.join(d, "vfx_bow_sheet.json")))
        self.assertEqual((meta["frame_w"], meta["frame_h"], meta["frames"], meta["fps"], meta["loop"], meta["blend"]),
                         (20, 20, 6, 15, True, "mix"))
        tmeta = json.loads(read(os.path.join(d, "vfx_bow_trail_sheet.json")))
        self.assertEqual((tmeta["frame_w"], tmeta["frame_h"], tmeta["frames"], tmeta["blend"]), (40, 20, 6, "add"))
        tres = read(os.path.join(d, "vfx_bow_frames.tres"))
        anims = re.findall(r'"frames": \[(.*?)\],\n"loop": (\w+),\n"name": &"(\w+)",\n"speed": ([\d.]+)', tres, re.S)
        self.assertEqual({(a[2], a[0].count("ExtResource"), a[1], a[3]) for a in anims},
                         {("fly", 6, "true", "15.0"), ("trail", 6, "true", "15.0")})
        meta = json.loads(read(os.path.join(self.art, "puff", "vfx_puff_sheet.json")))
        self.assertEqual((meta["frame_w"], meta["frames"], meta["loop"], meta["anchor"]), (30, 9, False, "bottom"))
        self.assertIn('"loop": false', read(os.path.join(self.art, "puff", "vfx_puff_frames.tres")))
        self.assertIn("offset = Vector2(0, -15)", read(os.path.join(self.art, "puff", "vfx_puff.tscn")))   # feet
        self.assertNotIn("offset", read(os.path.join(self.art, "spark", "vfx_spark.tscn")))                # centred
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "assets_src", "art", "fx", "vfx_review.png")))

    # ---- one-shots end empty, loops wrap
    def test_one_shots_end_empty_and_loops_wrap(self):
        v = self.lane()
        for kind in SPRITE_KINDS:
            draw, size, n0, loop = v.KINDS[kind][:4]
            ramp = v.ramp_of({"name": kind}, kind)
            for n in (n0, n0 + 3):
                fr = v.frames(kind, size, n, 7601, ramp)
                opaque = [int((f[..., 3] > 0).sum()) for f in fr]
                self.assertGreater(len({f.tobytes() for f in fr}), n // 2, kind)                  # it moves
                if loop:
                    self.assertTrue(all(opaque), kind)
                    # the frame after the last is the first: the drawing at t = 1 is frame 0
                    self.assertTrue(np.array_equal(v.paint(kind, draw(1.0, size, 7601), ramp), fr[0]), kind)
                    steps = [int((fr[i] != fr[i + 1]).any(-1).sum()) for i in range(n - 1)]
                    wrap = int((fr[-1] != fr[0]).any(-1).sum())
                    self.assertLessEqual(wrap, max(steps) * 1.25, (kind, n, wrap, steps))           # no jump
                    if kind in PROJECTILES:
                        tdraw = v.KINDS[kind][6]
                        tr = v.trail_frames(kind, size, n, 7601, ramp)
                        self.assertTrue(np.array_equal(v.glow_paint(tdraw(1.0, 2 * size, size, 7601), ramp), tr[0]),
                                        kind)
                else:
                    self.assertTrue(all(opaque[:-1]), (kind, n, opaque))                           # always visible
                    self.assertEqual(opaque[-1], 0, (kind, n))                                     # ends empty
                    self.assertLess(opaque[-2], max(opaque), (kind, n))                            # thins out first

    # ---- colours come only from the ramp
    def test_colours_only_from_ramp(self):
        v = self.lane()
        for kind in SPRITE_KINDS:
            _, size, n = v.KINDS[kind][:3]
            for e in ({"name": kind}, {"name": kind, "color": "#3080ff"},
                      {"name": kind, "colors": ["#202020", "#808080", "#f0f0f0"]}):
                ramp = v.ramp_of(e, kind)
                ok = ramp_set(ramp)
                for f in v.frames(kind, size, n, 7601, ramp):
                    self.assertTrue(colours(f) <= ok, (kind, e, colours(f) - ok))
                    self.assertTrue(set(np.unique(f[..., 3])) <= {0, 255}, kind)                   # hard alpha
                if kind in PROJECTILES:
                    for f in v.trail_frames(kind, size, n, 7601, ramp):
                        self.assertTrue(colours(f) <= ok, (kind, "trail", e))
        a = v.frames("orb", 20, 6, 1, v.ramp_of({"name": "o", "color": "#3080ff"}, "orb"))
        b = v.frames("orb", 20, 6, 1, v.ramp_of({"name": "o"}, "orb"))
        self.assertNotEqual(colours(a[0]), colours(b[0]))                                          # color is used
        self.assertEqual(len(v.ramp_of({"name": "z", "color": "#3080ff"}, "bolt")), 5)
        code, out = self.pack([{"name": "glint", "kind": "sparkle_particles",
                                "colors": ["#102040", "#4080c0", "#e0f0ff"]},
                               {"name": "embers", "kind": "ember_particles"},
                               {"name": "frost", "kind": "orb", "color": "#80c0ff", "trail": "line"}])
        self.assertEqual(code, 0, out)
        for name, ok in (("glint", {(16, 32, 64), (64, 128, 192), (224, 240, 255)}),
                         ("embers", ramp_set(v.ramp_of({"name": "e"}, "ember_particles")))):
            text = read(os.path.join(self.art, name, f"vfx_{name}.tscn"))
            offs, cols = gradient(text, "Gradient_1")
            self.assertEqual({c[:3] for c in cols}, ok, name)                                     # every step, no other
            with Image.open(os.path.join(self.art, name, f"vfx_{name}_particle.png")) as im:
                m = np.asarray(im.convert("RGBA"))
            self.assertEqual(colours(m), {(255, 255, 255)}, name)                                 # a white mask, hard alpha,
            self.assertTrue(set(np.unique(m[..., 3])) <= {0, 255}, name)                          # tinted by the ramp
        text = read(os.path.join(self.art, "frost", "vfx_frost.tscn"))
        self.assertEqual({c[:3] for c in gradient(text, "Gradient_trail")[1]},
                         ramp_set(v.ramp_of({"name": "f", "color": "#80c0ff"}, "orb")))

    # ---- trails fade along their length
    def test_trails_fade_along_length(self):
        v = self.lane()
        for kind in PROJECTILES:
            _, size, n = v.KINDS[kind][:3]
            ramp = v.ramp_of({"name": kind}, kind)
            for f in v.trail_frames(kind, size, n, 7601, ramp):
                light = (f[..., :3].astype(float).mean(-1) * (f[..., 3] > 0)).sum(0)   # per column, tail -> head
                w = f.shape[1]
                tail, mid, head = light[:w // 3].sum(), light[w // 3:2 * w // 3].sum(), light[2 * w // 3:].sum()
                self.assertGreater(head, mid, kind)
                self.assertGreater(mid, tail, kind)
                self.assertLess(tail, head * 0.5, kind)
                self.assertEqual(light[0], 0, kind)                                           # gone at the far end
        code, out = self.pack([{"name": "a", "kind": "arrow", "trail": "line"},
                               {"name": "b", "kind": "bolt", "trail": "particles"},
                               {"name": "c", "kind": "orb", "trail": "sprite"}])
        self.assertEqual(code, 0, out)
        text = read(os.path.join(self.art, "a", "vfx_a.tscn"))
        trail = block(text, r'node name="Trail" type="Line2D"')
        pts = [float(x) for x in re.search(r"PackedVector2Array\(([^)]*)\)", trail).group(1).split(",")]
        self.assertLess(pts[0], pts[2])                                                         # tail first, head last
        self.assertEqual(pts[2] - 1, v.trail_join("arrow", 16))                                 # ends at the body
        offs, cols = gradient(text, "Gradient_trail")
        self.assertEqual(offs, sorted(offs))
        alphas, lumas = [c[3] for c in cols], [luma(c) for c in cols]
        self.assertEqual(alphas[0], 0)
        self.assertEqual(alphas, sorted(alphas))                                                # opaque toward the head
        self.assertEqual(lumas[1:], sorted(lumas[1:]))                                          # brighter at the head
        self.assertIn("width_curve", trail)
        self.assertLess(text.index('[node name="Trail"'), text.index('[node name="Body"'))      # drawn behind it
        text = read(os.path.join(self.art, "b", "vfx_b.tscn"))
        offs, cols = gradient(text, "Gradient_trail")
        alphas, lumas = [c[3] for c in cols], [luma(c) for c in cols]
        self.assertEqual(alphas, sorted(alphas, reverse=True))                                  # older = fainter
        self.assertEqual(alphas[-1], 0)
        self.assertEqual(lumas[:-1], sorted(lumas[:-1], reverse=True))
        self.assertEqual(prop(block(text, r'node name="Trail" type="GPUParticles2D"'), "local_coords"), "false")
        text = read(os.path.join(self.art, "c", "vfx_c.tscn"))
        trail = block(text, r'node name="Trail" type="AnimatedSprite2D"')
        self.assertEqual(prop(trail, "animation"), '&"trail"')
        self.assertEqual(prop(trail, "position"), f"Vector2({v.trail_join('orb', 20) - 20 + 1}, 0)")

    # ---- particle scenes
    def test_particle_scenes(self):
        v = self.lane()
        code, out = self.pack([{"name": "road_dust", "kind": "dust_particles"},
                               {"name": "glint", "kind": "sparkle_particles"},
                               {"name": "forge", "kind": "ember_particles", "amount": 24},
                               {"name": "anvil", "kind": "ember_particles", "one_shot": True, "size": 12},
                               {"name": "shot", "kind": "orb"}])
        self.assertEqual(code, 0, out)
        want = {"road_dust": ("true", "10", "0.9"), "glint": ("false", "8", "0"), "forge": ("false", "24", "0"),
                "anvil": ("true", "16", "0.6")}
        man = json.loads(read(os.path.join(self.tmp, "assets_src", "dotwork", "manifest_vfx.json")))
        files = {r["file"] for r in man["assets"]}
        for name, (one_shot, amount, expl) in want.items():
            text = read(os.path.join(self.art, name, f"vfx_{name}.tscn"))
            node = block(text, rf'node name="Vfx{name.title().replace("_", "")}" type="GPUParticles2D"')
            self.assertEqual((prop(node, "one_shot"), prop(node, "amount"), prop(node, "explosiveness")),
                             (one_shot, amount, expl), name)
            tex = re.search(r'\[ext_resource type="Texture2D" path="res://([^"]+)" id="([^"]+)"\]', text)
            self.assertTrue(os.path.isfile(os.path.join(self.tmp, *tex.group(1).split("/"))), name)
            self.assertEqual(prop(node, "texture"), f'ExtResource("{tex.group(2)}")')
            sid = re.search(r'SubResource\("([^"]+)"\)', prop(node, "process_material")).group(1)
            pm = block(text, rf'type="ParticleProcessMaterial" id="{sid}"')
            self.assertEqual(prop(pm, "particle_flag_disable_z"), "true")
            self.assertIsNotNone(prop(pm, "color_ramp"))
            self.assertIn(f"assets/art/fx/vfx/{name}/vfx_{name}.tscn", files)                 # verify gets it
            starter = '[node name="Start" type="AnimationPlayer" parent="."]' in text
            self.assertEqual(starter, one_shot == "true", name)                                 # one-shots arm on spawn
            if starter:
                self.assertEqual(prop(node, "emitting"), "false")
                self.assertIn('tracks/0/path = NodePath(".:emitting")', text)
            meta = json.loads(read(os.path.join(self.art, name, f"vfx_{name}_particles.json")))
            self.assertEqual((meta["amount"], meta["one_shot"]), (int(amount), one_shot == "true"))
        self.assertIn("ExtResource(\"2_mat\")", read(os.path.join(self.art, "forge", "vfx_forge.tscn")))   # embers glow
        self.assertNotIn("mat_additive", read(os.path.join(self.art, "road_dust", "vfx_road_dust.tscn")))  # dust mixes
        # half the area: half the speed (initial_velocity scales with size)
        a = block(read(os.path.join(self.art, "anvil", "vfx_anvil.tscn")), r'type="ParticleProcessMaterial"')
        f = block(read(os.path.join(self.art, "forge", "vfx_forge.tscn")), r'type="ParticleProcessMaterial"')
        self.assertAlmostEqual(float(prop(a, "initial_velocity_max")) * 2, float(prop(f, "initial_velocity_max")))
        text = read(os.path.join(self.art, "shot", "vfx_shot.tscn"))                            # the orb's trail
        tex = re.search(r'\[ext_resource type="Texture2D" path="res://([^"]+)" id="3_tex"\]', text)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, *tex.group(1).split("/"))))
        self.assertIn('[sub_resource type="ParticleProcessMaterial" id="ParticleProcessMaterial_trail"]', text)
        # --engine none: the texture and the emitter JSON still ship, no scene
        shutil.rmtree(os.path.join(self.tmp, "assets"))
        code, out = self.pack([{"name": "glint", "kind": "sparkle_particles"}], "--engine", "none")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.art, "glint", "vfx_glint_particle.png")))
        self.assertTrue(os.path.isfile(os.path.join(self.art, "glint", "vfx_glint_particles.json")))
        self.assertFalse(os.path.exists(os.path.join(self.art, "glint", "vfx_glint.tscn")))

    # ---- spec errors exit 2, before anything is written
    def test_spec_errors_exit_2(self):
        self.lane()
        code, out = self.pack([{"name": "fine", "kind": "dust"}])
        self.assertEqual(code, 0, out)
        bad = [({"name": "x", "kind": "meteor"}, "meteor"), ({"name": "x", "kind": "dust", "size": 4}, "size"),
               ({"name": "x", "kind": "orb", "frames": 1}, "frames"),
               ({"name": "x", "kind": "orb", "size": "big"}, "size"),
               ({"name": "x", "kind": "orb", "colors": ["#ffffff"]}, "colors"),
               ({"name": "x", "kind": "orb", "colors": "#ffffff"}, "colors"),
               ({"name": "x", "kind": "orb", "color": "blue"}, "color"),
               ({"name": "x", "kind": "arrow", "trail": "rope"}, "rope"),
               ({"name": "x", "kind": "dust", "trail": "line"}, "trail"),
               ({"name": "x", "kind": "ember_particles", "amount": 0}, "amount"),
               ({"name": "x", "kind": "ember_particles", "amount": True}, "amount"),
               ({"name": "x", "kind": "arrow", "amount": 5}, "amount"),
               ({"name": "x", "kind": "dust_particles", "one_shot": "yes"}, "one_shot"),
               ({"name": "x", "kind": "sparkle_particles", "frames": 6}, "frames")]
        for e, word in bad:
            shutil.rmtree(os.path.join(self.tmp, "assets"), ignore_errors=True)
            code, out = self.pack([{"name": "ok", "kind": "orb"}, e])
            self.assertEqual(code, 2, (e, out))
            self.assertIn(word, out, e)
            self.assertFalse(os.path.exists(os.path.join(self.art, "ok")), e)                  # nothing written

    # ---- verify instantiates the new scenes and checks their emitters
    def test_verify_checks_particle_scenes(self):
        self.lane()
        import verify
        loader = verify.LOADER
        self.assertTrue("bad += _fx_check(p, n)" in loader, "the loader does not check scene nodes")   # every scene
        fx = loader[loader.index("func _fx_check"):]
        for need in ("GPUParticles2D", "ParticleProcessMaterial", "node.texture != null", "Line2D", "gradient",
                     "get_children()"):
            self.assertTrue(need in fx, need)
        import dotwork
        self.assertIn("vfx", dotwork.LANES)
        keys = dotwork.entry_keys("vfx")
        self.assertTrue({"kind", "size", "frames", "fps", "color", "colors", "trail", "amount", "one_shot"} <= keys)

    # ---- the shipped example
    def test_example_spec(self):
        self.lane()
        import dotwork
        path = os.path.join(DOTWORK, "examples", "vfx.json")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            spec = dotwork.load_spec(path)
        self.assertNotIn("is not read by Dotwork", err.getvalue())
        kinds = {e.get("kind", e["name"]) for e in spec["vfx"]}
        self.assertEqual(kinds, set(SPRITE_KINDS) | set(PARTICLE_KINDS))
        self.assertEqual({e.get("trail") for e in spec["vfx"]} - {None}, {"line", "particles"})
        text = read(path).lower()
        self.assertNotIn(chr(0x2014), text)                                                    # no em dash
        self.assertNotIn(":\\", text)                                                          # no local paths


if __name__ == "__main__":
    unittest.main()
