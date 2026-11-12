#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_chain.py
# Purpose : The exam for `bozzetto.py rig chain` (chain.py, rig_chain.py), offline.
#           Part 1 (standard library, any Python 3.8+):
#           - the selector, sway and clip parsers: every form, and the mistakes they must name
#           - the command with a stand-in Blender: options checked before Blender starts, the rig before its first
#             chain kept and every re-run started from it (no stacked chains), a re-rigged model becoming the new
#             base, --no-replace leaving the model alone, a refusal or failed check replacing nothing, the chain
#             noted once in the model's ASSET_LOG row
#           Part 2 (when Blender or the bpy module is found): a made-up character built here in Blender (a biped
#           from boxes with Mixamo bone names, a looping walk and idle, a one-shot hit, and a red scarf hanging down
#           its back, in six variants: its own shell coloured by material, by texture or by colour attribute; a box
#           with two rows; a band fused into the back surface, by material or texture; a red lump instead):
#           - selection by colour from each source, by material, by box; refusals for nothing selected, most of
#             the mesh, a lump, cloth on a loop, an unknown clip, --rebuild no on a fused part
#           - bone count and parent, weights summing to 1 with every chain bone in use, the sway looping exactly
#             (the chain's first frame equals its last), the chain moving, the body unchanged (bone poses and the
#             mesh, every clip), the cloth bake moving the chain in the one-shot from rest, the output reloading
#             with its chain and all three clips
#           - the two-row box cut into rows without changing its size; the fused band rebuilt as a strip that
#             still shows the red of the texture, inside its faces too when the band's texture sits in two islands
#             with another colour between them (the flecks of the live run); clips keyed at 30 fps counted as
#             loops without --loop, swaying and as long as they were (#292)
#           - one real `bozzetto.py rig chain` run in a scratch game
# Usage   : python tools/bozzetto/test_chain.py
#           BOZZETTO_TEST_BLENDER=skip|bpy|<path to blender>  picks part 2's Blender (skip: part 1 only)
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): the split-island band and the 30 fps clips (#292)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bozzetto as bz  # noqa: E402
import chain as ch  # noqa: E402

RED = "#c8202a"
LOG = """# Asset log

| ID | Type | Path | Source | Author | License | Attribution | AI | Edited | Date | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | model | `assets/models/npc_scarf.glb` | Bozzetto | generated locally | mit | Built with DINOv3. | pre-generated | no | 2026-01-01 | |
| A-0002 | model | `assets/models/npc_scarf_rigged.glb` | UniRig (local) | generated locally | mit | UniRig. | pre-generated | no | 2026-01-01 | rig of A-0001; 24 bones, Mixamo names |
"""


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = bz.main(argv)
    return code, out.getvalue() + err.getvalue()


# ---- part 1: parsers -------------------------------------------------------------------------------------------
class ParseExam(unittest.TestCase):
    def test_selector_forms(self):
        p = ch.parse_part("scarf=colour:#C8202A~0.2")
        self.assertEqual(p["label"], "scarf")
        t = p["terms"][0]
        self.assertEqual((t["kind"], t["hex"], t["tol"]), ("colour", RED, 0.2))
        self.assertAlmostEqual(t["rgb"][0], 200 / 255)
        p = ch.parse_part("color:c8202a", 3)
        self.assertEqual((p["label"], p["terms"][0]["tol"]), ("chain3", ch.TOL_DEFAULT))
        p = ch.parse_part("hair=material:Hair & box:0.1,1.5,-0.2,-0.1,1.9,0.1")
        self.assertEqual([t["kind"] for t in p["terms"]], ["material", "box"])
        self.assertEqual(p["terms"][1]["lo"], [-0.1, 1.5, -0.2])
        self.assertEqual(p["terms"][1]["hi"], [0.1, 1.9, 0.1])
        self.assertEqual(ch.parse_part("group:Tail=Bones")["terms"][0]["name"], "Tail=Bones")   # '=' after ':'

    def test_selector_mistakes_are_named(self):
        for text, says in (("colour:#c820", "#rrggbb"), ("colour:#c8202a~0", "between 0 and 1"),
                           ("colour:#c8202a~x", "not a number"), ("shape:round", "colour, group, material or box"),
                           ("box:1,2,3,4,5", "six numbers"), ("box:0,0,0,1,0,1", "no volume"),
                           ("Scarf!=colour:#c8202a", "part label"), ("scarf=", "names no selector"),
                           ("colour", "kind:value")):
            with self.assertRaises(ValueError, msg=text) as cm:
                ch.parse_part(text)
            self.assertIn(says, str(cm.exception), text)

    def test_sway_and_clips(self):
        self.assertEqual(ch.parse_sway("10"), (10.0, {}))
        self.assertEqual(ch.parse_sway("10,Idle=4,run=14"), (10.0, {"idle": 4.0, "run": 14.0}))
        self.assertEqual(ch.parse_sway("idle=4"), (float(ch.SWAY_DEFAULT), {"idle": 4.0}))
        for bad in ("50", "walk=x"):
            with self.assertRaises(ValueError):
                ch.parse_sway(bad)
        self.assertEqual(ch.parse_clips("none"), [])
        self.assertEqual(ch.parse_clips("oneshots"), ["*oneshots*"])
        self.assertEqual(ch.parse_clips("Hit, death"), ["hit", "death"])


# ---- part 1: the command with a stand-in Blender ---------------------------------------------------------------
class CliExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bz_chain_exam_")
        self.root = Path(self.tmp.name) / "game"
        (self.root / "docs").mkdir(parents=True)
        (self.root / "docs" / "ASSET_LOG.md").write_text(LOG, encoding="utf-8")
        self.models = self.root / "assets" / "models"
        self.models.mkdir(parents=True)
        self.dst = self.models / "npc_scarf_rigged.glb"
        self.dst.write_bytes(b"glTF-rigged-v1")
        self.work = self.root / "assets_src" / "bozzetto" / "npc_scarf" / "rig" / "chain"
        self.saved = (bz.run_bpy, bz.find_blender, os.getcwd())
        bz.find_blender = lambda choice=None: ("blender", "fake-blender")
        bz.run_bpy = self.fake
        self.calls, self.rc, self.fail = [], 0, None
        os.chdir(self.root)

    def tearDown(self):
        bz.run_bpy, bz.find_blender, cwd = self.saved
        os.chdir(cwd)
        self.tmp.cleanup()

    def fake(self, blender, script, argv, what):
        """rig_chain.py stand-in: writes --out (base bytes + '+chain') and --report like the real one."""
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        self.assertEqual(Path(script).name, "rig_chain.py")
        rep = {"parts": [{"label": "scarf", "parent": "mixamorig:Neck", "bones": ["scarf_01", "scarf_02"],
                          "rebuild": "none"}],
               "clips": {"walk": {"motion": "sway", "amplitude_deg": 8, "cycles": 1, "loop_error": 0.0},
                         "hit": {"motion": "none"}},
               "failures": [self.fail] if self.fail else []}
        if self.rc == 0:
            Path(argv[argv.index("--out") + 1]).write_bytes(Path(argv[0]).read_bytes() + b"+chain")
        Path(argv[argv.index("--report") + 1]).write_text(json.dumps(rep), encoding="utf-8")
        return self.rc, ""

    def chain(self, *extra):
        return run_main(["rig", "chain", "npc_scarf", "--part", f"scarf=colour:{RED}~0.15", *extra])

    def test_options_are_checked_before_blender(self):
        for argv, says in ((["rig", "chain", "npc_scarf"], "--part is required"),
                           (["rig", "chain", "npc_scarf", "--part", "colour:#zz0000"], "#rrggbb"),
                           (["rig", "chain", "npc_scarf", "--part", "colour:#c8202a", "--bones", "1"], "--bones 1"),
                           (["rig", "chain", "npc_scarf", "--part", "colour:#c8202a", "--lag", "0.9"], "--lag"),
                           (["rig", "chain", "npc_scarf", "--part", "colour:#c8202a", "--sway", "90"], "--sway"),
                           (["rig", "chain", "npc_scarf", "--part", "a=colour:#c8202a", "--part", "a=group:x"],
                            "both labelled"),
                           (["rig", "chain", "npc_nobody", "--part", "colour:#c8202a"], "rig the character first")):
            code, out = run_main(argv)
            self.assertEqual(code, 2, (argv, out))
            self.assertIn(says, out, argv)
        self.assertEqual(self.calls, [], "Blender ran before the options were checked")

    def test_first_run_keeps_the_rig_and_reruns_start_from_it(self):
        code, out = self.chain("--bones", "5", "--cloth", "hit")
        self.assertEqual(code, 0, out)
        backup = self.work / ch.BACKUP
        self.assertEqual(backup.read_bytes(), b"glTF-rigged-v1")
        self.assertEqual(self.dst.read_bytes(), b"glTF-rigged-v1+chain")
        argv = self.calls[0]
        self.assertEqual(Path(argv[0]), backup)
        for flag, value in (("--bones", "5"), ("--cloth", "hit"), ("--part", f"scarf=colour:{RED}~0.15")):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        self.assertIn("--sheet", argv)
        # a re-run starts from the rig before the chain, so the chain is replaced, never stacked
        code, out = self.chain("--bones", "3")
        self.assertEqual(code, 0, out)
        self.assertEqual(Path(self.calls[1][0]), backup)
        self.assertEqual(self.dst.read_bytes(), b"glTF-rigged-v1+chain")
        self.assertIn("a re-run replaces the chain", out)
        rec = json.loads((self.work / ch.RECORD).read_text(encoding="utf-8"))
        self.assertEqual(rec["output_sha256"], bz.sha256_bytes(self.dst.read_bytes()))
        self.assertEqual(rec["options"]["bones"], 3)
        log = (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8")
        row = [l for l in log.splitlines() if l.startswith("| A-0002")][0]
        self.assertEqual(row.count(ch.NOTE_PREFIX), 1, row)
        self.assertIn("chain: scarf (2 bones)", row)
        self.assertIn("rig of A-0001", row)
        self.assertEqual(len(row.split("|")), len(LOG.splitlines()[-1].split("|")), "the row lost or gained a cell")

    def test_a_rerigged_model_becomes_the_new_base(self):
        self.assertEqual(self.chain()[0], 0)
        self.dst.write_bytes(b"glTF-rigged-v2")             # rig make --overwrite since the last chain run
        code, out = self.chain()
        self.assertEqual(code, 0, out)
        self.assertEqual((self.work / ch.BACKUP).read_bytes(), b"glTF-rigged-v2")
        self.assertEqual(self.dst.read_bytes(), b"glTF-rigged-v2+chain")

    def test_no_replace_leaves_the_model_alone(self):
        code, out = self.chain("--no-replace")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.dst.read_bytes(), b"glTF-rigged-v1")
        self.assertEqual((self.work / "chained.glb").read_bytes(), b"glTF-rigged-v1+chain")
        self.assertNotIn(ch.NOTE_PREFIX, (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8"))
        self.assertEqual(self.chain()[0], 0)               # then the real run, from the same base
        self.assertEqual(self.dst.read_bytes(), b"glTF-rigged-v1+chain")

    def test_a_refusal_or_failed_check_replaces_nothing(self):
        self.rc, self.fail = 1, "--part colour:#c8202a selected nothing"
        code, out = self.chain()
        self.assertEqual(code, 1, out)
        self.assertIn("selected nothing", out)
        self.assertIn("is unchanged", out)
        self.assertEqual(self.dst.read_bytes(), b"glTF-rigged-v1")
        self.rc, self.fail = 2, "no clip named 'jump'"
        code, out = self.chain("--cloth", "jump")
        self.assertEqual(code, 2, out)
        self.assertIn("no clip named", out)
        self.assertNotIn(ch.NOTE_PREFIX, (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8"))

    def test_no_log_row_is_said_not_invented(self):
        (self.root / "docs" / "ASSET_LOG.md").write_text(LOG.rsplit("\n| A-0002", 1)[0] + "\n", encoding="utf-8")
        code, out = self.chain()
        self.assertEqual(code, 0, out)
        self.assertIn("has no row", out)


# ---- part 2: the made-up character in Blender ------------------------------------------------------------------
END = textwrap.dedent('''
    if not bpy.app.binary_path and sys.platform == "win32":
        # the bpy module crashes while the process ends on Windows (rig_chain.py says more): end it here
        import ctypes
        sys.stdout.flush()
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k.TerminateProcess(k.GetCurrentProcess(), 0)
''')

BUILD = textwrap.dedent('''
    import sys, math, bpy
    from mathutils import Vector, Quaternion
    ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]   # Blender, or the bpy module
    out_dir = ARGV[0]
    M = "mixamorig:"
    BONES = [("Hips", (0, 0, 0.9), (0, 0, 1.05), None), ("Spine", (0, 0, 1.05), (0, 0, 1.2), "Hips"),
             ("Spine1", (0, 0, 1.2), (0, 0, 1.32), "Spine"), ("Spine2", (0, 0, 1.32), (0, 0, 1.45), "Spine1"),
             ("Neck", (0, 0, 1.45), (0, 0, 1.55), "Spine2"), ("Head", (0, 0, 1.55), (0, 0, 1.8), "Neck")]
    for s, x in (("Left", 1), ("Right", -1)):
        BONES += [(s + "UpLeg", (0.1 * x, 0, 0.9), (0.1 * x, 0, 0.5), "Hips"),
                  (s + "Leg", (0.1 * x, 0, 0.5), (0.1 * x, 0, 0.08), s + "UpLeg"),
                  (s + "Foot", (0.1 * x, 0, 0.08), (0.1 * x, -0.12, 0.0), s + "Leg"),
                  (s + "Shoulder", (0.05 * x, 0, 1.42), (0.17 * x, 0, 1.42), "Spine2"),
                  (s + "Arm", (0.17 * x, 0, 1.42), (0.42 * x, 0, 1.22), s + "Shoulder"),
                  (s + "ForeArm", (0.42 * x, 0, 1.22), (0.62 * x, 0, 1.02), s + "Arm"),
                  (s + "Hand", (0.62 * x, 0, 1.02), (0.7 * x, 0, 0.95), s + "ForeArm")]
    SIZE = {"Hips": (0.32, 0.2), "Spine": (0.32, 0.2), "Spine1": (0.34, 0.2), "Spine2": (0.36, 0.2),
            "Neck": (0.1, 0.1), "Head": (0.2, 0.22)}
    SHIRT, SKIN, RED = (0.19, 0.31, 0.63), (0.88, 0.69, 0.56), (0.784, 0.125, 0.165)

    def lin(c):
        return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)

    def box(V, F, G, C, head, tail, w, d, rows, group, col):
        """A box from head to tail, `rows` rings of 4 vertices; upright boxes are wide in X, deep in Y."""
        h, t = Vector(head), Vector(tail)
        axis = (t - h).normalized()
        ref = Vector((0, 0, 1)) if abs(axis.z) < 0.9 else Vector((0, 1, 0))
        u = axis.cross(ref).normalized(); v = axis.cross(u).normalized()
        base = len(V)
        for r in range(rows + 1):
            c = h.lerp(t, r / rows)
            for a, b in ((1, 1), (-1, 1), (-1, -1), (1, -1)):
                V.append(c + u * (a * w / 2) + v * (b * d / 2)); G.append(group)
        for r in range(rows):
            for k in range(4):
                a, b = base + r * 4 + k, base + r * 4 + (k + 1) % 4
                F.append((a, b, b + 4, a + 4)); C.append(col)
        F.append(tuple(base + k for k in range(4))[::-1]); C.append(col)
        F.append(tuple(base + rows * 4 + k for k in range(4))); C.append(col)

    def build(kind):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        ad = bpy.data.armatures.new("rig"); arm = bpy.data.objects.new("rig", ad)
        bpy.context.scene.collection.objects.link(arm); bpy.context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode="EDIT")
        for n, h, t, p in BONES:
            b = ad.edit_bones.new(M + n); b.head, b.tail = Vector(h), Vector(t)
            if p:
                b.parent = ad.edit_bones[M + p]
                b.use_connect = (Vector(h) - ad.edit_bones[M + p].tail).length < 1e-6
        bpy.ops.object.mode_set(mode="OBJECT")
        V, F, G, C = [], [], [], []
        for n, h, t, p in BONES:
            w, d = SIZE.get(n, (0.08, 0.08))
            box(V, F, G, C, h, t, w, d, 3, M + n, SKIN if n in ("Head", "Neck") or "Hand" in n else SHIRT)
        if kind in ("free", "texture", "vertex", "thirty"):     # the scarf tail: its own shell, 12 rows
            box(V, F, G, C, (0, 0.115, 1.48), (0, 0.13, 0.95), 0.12, 0.012, 12,
                [(M + "Spine2", 0.6), (M + "Spine1", 0.4)], RED)
        elif kind == "front":                         # the same tail hanging down the chest instead of the back
            box(V, F, G, C, (0, -0.115, 1.48), (0, -0.13, 0.95), 0.12, 0.012, 12,
                [(M + "Spine2", 0.6), (M + "Spine1", 0.4)], RED)
        elif kind == "box":                           # the same tail as one box: two rows
            box(V, F, G, C, (0, 0.115, 1.48), (0, 0.13, 0.95), 0.12, 0.03, 1, M + "Spine2", RED)
        elif kind == "lump":                          # a red lump on the chest
            box(V, F, G, C, (0, -0.13, 1.3), (0, -0.13, 1.38), 0.08, 0.08, 1, M + "Spine2", RED)
        elif kind in ("fused", "fused_tex", "fused_split"):   # the back as one surface, the scarf a raised red band
            nx, nz, x0, x1, z0, z1 = 8, 12, -0.17, 0.17, 0.95, 1.48
            base = len(V)
            for j in range(nz + 1):
                for i in range(nx + 1):
                    x = x0 + (x1 - x0) * i / nx; z = z1 - (z1 - z0) * j / nz
                    V.append(Vector((x, 0.102 + (0.02 if i == 4 else 0.0), z)))
                    G.append(M + ("Spine2" if z > 1.32 else ("Spine1" if z > 1.2 else "Spine")))
            for j in range(nz):
                for i in range(nx):
                    a = base + j * (nx + 1) + i
                    F.append((a, a + nx + 1, a + nx + 2, a + 1)); C.append(RED if 3 <= i < 5 else SHIRT)
        me = bpy.data.meshes.new("body"); me.from_pydata([tuple(v) for v in V], [], F); me.update()
        body = bpy.data.objects.new("body", me); bpy.context.scene.collection.objects.link(body)
        for i, gs in enumerate(G):
            for n, w in ([(gs, 1.0)] if isinstance(gs, str) else gs):
                g = body.vertex_groups.get(n) or body.vertex_groups.new(name=n)
                g.add([i], w, "REPLACE")
        if kind in ("texture", "fused_tex", "fused_split"):   # a 64 px texture: red right half, shirt and skin left
            # fused_split: the red is two islands (the right half's top and bottom) with shirt colour between them,
            # the band's upper half mapped to one and its lower half to the other, as an AI mesh's atlas is cut up
            split = kind == "fused_split"
            img = bpy.data.images.new("tex", 64, 64)
            px = []
            for y in range(64):
                for x in range(64):
                    red = x >= 32 and (not split or y < 20 or y >= 44)
                    px += [*(RED if red else (SKIN if (y >= 32 and x < 32) else SHIRT)), 1.0]
            img.pixels = px; img.pack()
            mat = bpy.data.materials.new("cloth"); mat.use_nodes = True
            tex = mat.node_tree.nodes.new("ShaderNodeTexImage"); tex.image = img
            mat.node_tree.links.new(tex.outputs["Color"], mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
            me.materials.append(mat)
            uv = me.uv_layers.new(name="UVMap")
            for f, c in zip(me.polygons, C):
                u0, v0 = (0.75, 0.5) if c == RED else ((0.25, 0.75) if c == SKIN else (0.25, 0.25))
                if split and c == RED:                # the split between two strip rows, so a face straddles it
                    v0 = 0.88 if f.center.z > 1.25 else 0.12
                for k, li in enumerate(f.loop_indices):
                    uv.data[li].uv = (u0 + 0.05 * math.cos(k), v0 + 0.05 * math.sin(k))
        elif kind == "vertex":                        # a colour attribute and a material that shows it
            attr = me.color_attributes.new("Color", "BYTE_COLOR", "CORNER")
            for f, c in zip(me.polygons, C):
                for li in f.loop_indices:
                    attr.data[li].color_srgb = (*c, 1.0)
            mat = bpy.data.materials.new("vcol"); mat.use_nodes = True
            vc = mat.node_tree.nodes.new("ShaderNodeVertexColor"); vc.layer_name = "Color"
            mat.node_tree.links.new(vc.outputs["Color"], mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
            me.materials.append(mat)
        else:                                         # one material per colour
            idx = {}
            for c, nm in ((SHIRT, "Shirt"), (SKIN, "Skin"), (RED, "Scarf")):
                m = bpy.data.materials.new(nm); m.use_nodes = True
                m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*lin(c), 1.0)
                me.materials.append(m); idx[c] = len(me.materials) - 1
            for f, c in zip(me.polygons, C):
                f.material_index = idx[c]
        body.parent = arm
        body.modifiers.new("Armature", "ARMATURE").object = arm
        arm.animation_data_create()
        P = arm.pose.bones

        def key(name, frames, fn):
            act = bpy.data.actions.new(name); act.use_fake_user = True
            arm.animation_data.action = act
            for f in frames:
                for pb in P:
                    pb.rotation_mode = "QUATERNION"; pb.rotation_quaternion = Quaternion()
                for n, axis, deg in fn(f):
                    pb = P[M + n]; pb.rotation_quaternion = Quaternion(axis, math.radians(deg))
                    pb.keyframe_insert("rotation_quaternion", frame=f)
            arm.animation_data.action = None

        def walk(f):                                  # loops: frame 25 is frame 1
            t = 2 * math.pi * (f - 1) / 24
            return [("LeftUpLeg", (1, 0, 0), 25 * math.sin(t)), ("RightUpLeg", (1, 0, 0), -25 * math.sin(t)),
                    ("LeftArm", (1, 0, 0), -15 * math.sin(t)), ("RightArm", (1, 0, 0), 15 * math.sin(t)),
                    ("Spine1", (0, 1, 0), 4 * math.sin(t))]

        def idle(f):
            t = 2 * math.pi * (f - 1) / 48
            return [("Spine1", (1, 0, 0), 2 * math.sin(t)), ("Head", (1, 0, 0), 3 * math.sin(t + 0.5))]

        def hit(f):                                   # a one-shot: leans back, comes partly back
            a = 25 * math.sin(math.pi * min(1.0, (f - 1) / 8)) if f <= 9 else 25 * math.exp(-(f - 9) / 6) * 0.4
            return [("Spine", (1, 0, 0), -a), ("Spine2", (1, 0, 0), -a * 0.6), ("Head", (1, 0, 0), a * 0.5)]
        key("walk", range(1, 26), walk); key("idle", range(1, 50), idle); key("hit", range(1, 22), hit)
        if kind == "thirty":                          # the same clips keyed at 30 fps, as Tripo's come (#292)
            bpy.context.scene.render.fps = 30
        bpy.ops.export_scene.gltf(filepath=f"{out_dir}/{kind}.glb", export_format="GLB", export_yup=True,
                                  export_animations=True, export_animation_mode="ACTIONS")

    for k in ("free", "texture", "vertex", "box", "fused", "fused_tex", "fused_split", "lump", "front", "thirty"):
        build(k)
        print("BUILT", k)
''')

# Reads an input and an output .glb and measures what the exam asserts. Body bones and meshes are compared frame by
# frame in every clip; the chain's own bones are found by the label prefix.
PROBE = textwrap.dedent('''
    import sys, json, bpy
    import numpy as np
    from mathutils.kdtree import KDTree
    ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]   # Blender, or the bpy module
    src, out, label, common_dir = ARGV[:4]
    sys.path.insert(0, common_dir)
    import bpy_common as bc

    def load(path):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=path)
        arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
        bc.adopt_clip_names(bpy)           # Blender 4.2 names actions "<clip>_<armature>"; the track keeps the clip
        for t in list(arm.animation_data.nla_tracks) if arm.animation_data else []:
            arm.animation_data.nla_tracks.remove(t)
        # a 30 fps clip's keys sit every 0.8 frames at 24 fps: the poses are read at whole frames, so the scene
        # follows the clips' rate (as rig_chain itself does), else the first and last frame would miss the keys
        bc.conform_clip_fps(bpy, bpy.context.scene, list(bpy.data.actions), quiet=True)
        meshes = [o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)]
        return arm, meshes

    def play(arm, name):
        ad = arm.animation_data or arm.animation_data_create()
        ad.action = bpy.data.actions[name]
        if hasattr(ad, "action_slot") and ad.action_slot is None:
            ad.action_slot = (list(ad.action_suitable_slots) or list(ad.action.slots))[0]
        f0, f1 = (int(round(x)) for x in ad.action.frame_range)
        return f0, f1

    def points(meshes):
        dg = bpy.context.evaluated_depsgraph_get(); pts = []
        for m in meshes:
            ev = m.evaluated_get(dg); me = ev.to_mesh()
            pts += [tuple(m.matrix_world @ v.co) for v in me.vertices]; ev.to_mesh_clear()
        return pts

    def mats(arm, names):
        return {n: np.array(arm.pose.bones[n].matrix) for n in names}

    arm, meshes = load(src)
    clips = sorted(a.name for a in bpy.data.actions)
    body_names = [b.name for b in arm.data.bones]
    ref = {}
    for c in clips:
        f0, f1 = play(arm, c)
        for f in sorted({f0, (2 * f0 + f1) // 3, (f0 + 2 * f1) // 3, f1}):
            bpy.context.scene.frame_set(f)
            # keyed by the frame within the clip: the output's clips start at 0 s (slid to zero, #290), the input's
            # may start at frame 1
            ref[(c, f - f0)] = (mats(arm, body_names), points(meshes))
    arm, meshes = load(out)
    chain = [b.name for b in arm.data.bones if b.name.startswith(label + "_")]
    part = [m for m in meshes if m.name.startswith(label)]
    body = [m for m in meshes if m not in part]
    res = {"clips": sorted(a.name for a in bpy.data.actions), "chain": chain,
           "parents": {n: arm.data.bones[n].parent.name for n in chain}, "body_bone_err": 0.0, "body_mesh_err": 0.0,
           "loop_err": {}, "tip_move": {}, "first_frame_bend": {}, "part_vertices": sum(len(m.data.vertices) for m in part),
           "body_vertices": sum(len(m.data.vertices) for m in body)}
    for c in clips:
        f0, f1 = play(arm, c)
        tips = []
        for f in range(f0, f1 + 1):
            bpy.context.scene.frame_set(f)
            if (c, f - f0) in ref:
                bm, bp = ref[(c, f - f0)]
                cur = mats(arm, body_names)
                res["body_bone_err"] = max(res["body_bone_err"], max(float(np.abs(cur[n] - bm[n]).max()) for n in bm))
                kd = KDTree(len(bp))
                for i, p in enumerate(bp):
                    kd.insert(p, i)
                kd.balance()
                res["body_mesh_err"] = max([res["body_mesh_err"]] + [kd.find(p)[2] for p in points(body)])
            tips.append(np.array(arm.matrix_world @ arm.pose.bones[chain[-1]].tail))
            if f == f0:
                first = mats(arm, chain)
                res["first_frame_bend"][c] = max(float(np.abs(np.array(arm.pose.bones[n].matrix_basis)
                                                              - np.eye(4)).max()) for n in chain)
            if f == f1:
                last = mats(arm, chain)
                res["loop_err"][c] = max(float(np.abs(first[n] - last[n]).max()) for n in chain)
        res["tip_move"][c] = max(float(np.linalg.norm(t - tips[0])) for t in tips)
    sums, top = [], set()
    for m in part:
        names = {g.index: g.name for g in m.vertex_groups}
        for v in m.data.vertices:
            gs = [(names[g.group], g.weight) for g in v.groups if g.weight > 0]
            sums.append(sum(w for _, w in gs))
            top.add(max(gs, key=lambda x: x[1])[0])
    res["weight_sum_range"] = [min(sums), max(sums)] if sums else None
    res["dominant"] = sorted(top)
    if part:
        co = np.array([tuple(m.matrix_world @ v.co) for m in part for v in m.data.vertices])
        res["part_size"] = (co.max(axis=0) - co.min(axis=0)).tolist()
        m = part[0]
        img = next((n.image for s in m.material_slots if s.material and s.material.node_tree
                    for n in s.material.node_tree.nodes if n.type == "TEX_IMAGE" and n.image), None)
        if img is not None and m.data.uv_layers:
            w, h = img.size
            px = np.empty(w * h * 4, dtype=np.float32); img.pixels.foreach_get(px); px = px.reshape(h, w, 4)
            uv = m.data.uv_layers.active.data
            def at(u, v):
                return px[min(h - 1, int(v % 1 * h)), min(w - 1, int(u % 1 * w)), :3]
            cols = [at(*l.uv) for l in uv]
            res["part_texture_mean"] = np.mean(cols, axis=0).tolist()
            # what a face really shows: the texture at its centre and halfway along each edge, where coordinates
            # interpolated between corners in different texture islands sweep through whatever lies between
            inner = []
            for p in m.data.polygons:
                us = [uv[li].uv for li in p.loop_indices]
                inner.append(at(sum(x[0] for x in us) / len(us), sum(x[1] for x in us) / len(us)))
                for a, b in zip(us, us[1:] + us[:1]):
                    inner.append(at((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
            res["part_texture_inside"] = [[round(float(c), 3) for c in col] for col in inner]
    print("PROBE" + json.dumps(res))
''')


def pick_blender():
    choice = os.environ.get("BOZZETTO_TEST_BLENDER", "")
    if choice == "skip":
        return None
    return bz.find_blender(choice or None)


BLENDER = pick_blender()


def blender_run(script, argv, timeout=900):
    kind, path = BLENDER
    cmd = ([path, "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(script), "--"] if kind == "blender"
           else [path, str(script)]) + [str(a) for a in argv]
    return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)


@unittest.skipUnless(BLENDER, "Blender not found (set BLENDER_BIN, or BOZZETTO_TEST_BLENDER=bpy): part 2 skipped")
class ChainExam(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="bz_chain_bpy_")
        cls.d = Path(cls.tmp.name)
        (cls.d / "build.py").write_text(BUILD + END, encoding="utf-8")
        (cls.d / "probe.py").write_text(PROBE + END, encoding="utf-8")
        p = blender_run(cls.d / "build.py", [cls.d])
        assert p.returncode == 0 and p.stdout.count("BUILT") == 10, p.stdout[-2000:] + p.stderr[-2000:]
        cls.runs = {}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def chain(self, kind, *extra, key=None):
        """rig_chain.py on a fixture (cached per argument list): (process, report)."""
        key = key or (kind,) + extra
        if key not in self.runs:
            name = f"run{len(self.runs)}"
            rep = self.d / f"{name}.json"
            p = blender_run(HERE / "rig_chain.py", [self.d / f"{kind}.glb", "--out", self.d / f"{name}.glb",
                                                   "--report", rep, *extra])
            self.runs[key] = (p, json.loads(rep.read_text(encoding="utf-8")) if rep.is_file() else {},
                              self.d / f"{name}.glb")
        return self.runs[key]

    def probe(self, kind, out, label="scarf"):
        q = blender_run(self.d / "probe.py", [self.d / f"{kind}.glb", out, label, HERE.parent / "blender"])
        line = next((l for l in q.stdout.splitlines() if l.startswith("PROBE")), None)
        self.assertIsNotNone(line, q.stdout[-3000:] + q.stderr[-2000:])
        return json.loads(line[5:])

    def test_the_scarf_by_colour_gets_a_looping_chain_and_the_body_is_unchanged(self):
        p, rep, out = self.chain("free", "--part", f"scarf=colour:{RED}~0.15", "--cloth", "hit", "--bones", "4")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:])
        part = rep["parts"][0]
        self.assertEqual((part["parent"], part["rebuild"], len(part["bones"])), ("mixamorig:Neck", "none", 4))
        self.assertEqual(part["faces"], 100)                   # the scarf's 50 quads, as glTF's triangles
        self.assertEqual(part["bones_holding_vertices"], 4)
        self.assertAlmostEqual(part["length_m"], 0.53, delta=0.03)
        clips = rep["clips"]
        self.assertEqual((clips["walk"]["kind"], clips["idle"]["kind"], clips["hit"]["kind"]),
                         ("loop", "loop", "one-shot"))
        self.assertEqual((clips["walk"]["motion"], clips["hit"]["motion"]), ("sway", "cloth"))
        self.assertTrue(all(c["body_keys_unchanged"] for c in clips.values()), clips)
        self.assertEqual(rep["checks"]["failures"], [])
        r = self.probe("free", out)
        self.assertEqual(r["clips"], ["hit", "idle", "walk"])
        self.assertEqual(r["chain"], [f"scarf_0{i}" for i in range(1, 5)])
        self.assertEqual(r["parents"]["scarf_01"], "mixamorig:Neck")
        self.assertEqual(r["parents"]["scarf_04"], "scarf_03")
        self.assertEqual(set(r["dominant"]), {f"scarf_0{i}" for i in range(1, 5)} | {"mixamorig:Neck"})
        lo, hi = r["weight_sum_range"]
        self.assertAlmostEqual(lo, 1.0, delta=0.01)
        self.assertAlmostEqual(hi, 1.0, delta=0.01)
        for c in ("walk", "idle"):
            self.assertLess(r["loop_err"][c], 1e-4, f"{c}: the chain's first and last frame differ")
            self.assertGreater(r["tip_move"][c], 0.02, f"{c}: the scarf does not move")
        self.assertLess(r["first_frame_bend"]["hit"], 1e-4, "the cloth bake does not start at rest")
        self.assertGreater(r["tip_move"]["hit"], 0.05, "the cloth bake does not move the scarf")
        self.assertLess(r["body_bone_err"], 1e-4, "a body bone moved differently")
        self.assertLess(r["body_mesh_err"], 1e-4, "the body mesh changed")
        data = Path(out).read_bytes()             # #290: every clip starts at 0 s, read from the .glb itself
        doc = json.loads(data[20:20 + int.from_bytes(data[12:16], "little")].decode("utf-8"))
        starts = {a["name"]: min(doc["accessors"][s["input"]]["min"][0] for s in a["samplers"]) for a in doc["animations"]}
        self.assertTrue(all(abs(t) < 1e-6 for t in starts.values()), f"clips start at {starts} s")

    def test_colour_from_texture_and_colour_attribute(self):
        for kind in ("texture", "vertex"):
            p, rep, _ = self.chain(kind, "--part", f"colour:{RED}~0.1", "--bones", "3")
            self.assertEqual(p.returncode, 0, (kind, p.stdout[-2000:]))
            self.assertEqual(rep["parts"][0]["faces"], 100, kind)

    def test_material_and_box_selectors(self):
        p, rep, _ = self.chain("free", "--part", "tail=material:scarf", "--bones", "3")
        self.assertEqual(p.returncode, 0, p.stdout[-2000:])
        self.assertEqual(rep["parts"][0]["bones"], ["tail_01", "tail_02", "tail_03"])
        # the scarf below 1.2 m only (glTF axes: Y up, so the box's Y is Blender's Z)
        p, rep, _ = self.chain("free", "--part", f"colour:{RED}&box:-1,0,-1,1,1.2,1", "--bones", "2")
        self.assertEqual(p.returncode, 0, p.stdout[-2000:])
        self.assertLess(rep["parts"][0]["faces"], 60)
        self.assertGreater(rep["parts"][0]["faces"], 30)

    def test_refusals_name_the_problem(self):
        for kind, extra, code, says in (
                ("free", ["--part", "colour:#00ff00"], 1, "nothing on the model is near that colour"),
                ("free", ["--part", "colour:#d02a30~0.02"], 1, "widen the tolerance"),
                ("free", ["--part", "colour:#30509f~0.1"], 1, "most of the character"),
                ("lump", ["--part", f"colour:{RED}"], 1, "is a lump"),
                ("free", ["--part", f"colour:{RED}", "--cloth", "walk"], 2, "that clip loops"),
                ("free", ["--part", f"colour:{RED}", "--cloth", "jump"], 2, "no clip named 'jump'"),
                ("fused", ["--part", f"colour:{RED}", "--rebuild", "no"], 1, "cannot swing without tearing")):
            p, rep, out = self.chain(kind, *extra)
            self.assertEqual(p.returncode, code, (extra, p.stdout[-2000:]))
            self.assertTrue(any(says in f for f in rep.get("failures", [])), (says, rep))
            self.assertFalse(out.exists(), f"{extra} wrote a model")

    def test_a_box_with_two_rows_is_cut_without_changing_its_shape(self):
        p, rep, out = self.chain("box", "--part", f"scarf=colour:{RED}")
        self.assertEqual(p.returncode, 0, p.stdout[-2000:])
        part = rep["parts"][0]
        self.assertEqual((part["rebuild"], part["rows_before"]), ("cuts", 2))
        self.assertGreaterEqual(part["rows_after"], part["rows_needed"])
        r = self.probe("box", out)
        # x, y, z in Blender: the box as built (0.03 deep, leaning 0.015 back over its 0.53 m)
        for got, want in zip(r["part_size"], (0.12, 0.045, 0.53)):
            self.assertAlmostEqual(got, want, delta=0.005)
        self.assertLess(r["loop_err"]["walk"], 1e-4)

    def test_a_fused_band_is_rebuilt_as_a_strip_that_keeps_its_colour(self):
        p, rep, out = self.chain("fused_tex", "--part", f"scarf=colour:{RED}")
        self.assertEqual(p.returncode, 0, p.stdout[-2000:])
        part = rep["parts"][0]
        self.assertEqual(part["rebuild"], "strip")
        self.assertIn("texture baked", part["look"])
        self.assertAlmostEqual(part["width_m"], 0.085, delta=0.02)
        r = self.probe("fused_tex", out)
        red = [0.784, 0.125, 0.165]
        self.assertLess(max(abs(a - b) for a, b in zip(r["part_texture_mean"], red)), 0.1, r["part_texture_mean"])
        self.assertLess(r["body_mesh_err"], 1e-4)               # the band stays on the body as it was
        self.assertLess(r["loop_err"]["walk"], 1e-4)
        self.assertGreater(r["tip_move"]["walk"], 0.02)

    def test_a_band_across_two_texture_islands_shows_no_body_colour(self):
        """Live run 2026-11-11: a rebuilt scarf showed flecks of the body's texture. The strip's corners took the
        texture coordinates of their nearest original point; when two corners of one face sat in different islands
        of the atlas, the face swept through everything between them. Every point of the strip must show the part."""
        p, rep, out = self.chain("fused_split", "--part", f"scarf=colour:{RED}")
        self.assertEqual(p.returncode, 0, p.stdout[-2000:])
        self.assertEqual(rep["parts"][0]["rebuild"], "strip")
        r = self.probe("fused_split", out)
        red = (0.784, 0.125, 0.165)
        inside = r.get("part_texture_inside") or []
        self.assertGreater(len(inside), 50, "the probe sampled no face interiors")
        off = [c for c in inside if max(abs(a - b) for a, b in zip(c, red)) > 0.2]
        self.assertLess(len(off) / len(inside), 0.02, f"{len(off)} of {len(inside)} samples inside the strip's faces "
                                                     f"show another colour than the scarf's, e.g. {off[:3]}")

    def test_a_clip_keyed_at_30_fps_loops_and_keeps_its_length(self):
        """#292: Tripo keys at 30 fps; in Blender's 24 fps scene those keys sit every 0.8 frames, the first and last
        pose read at whole frames differ (the loop test failed without --loop) and the export cut the loop short.
        The scene takes the clips' rate: the walk is a loop on its own, the sway loops, the length is kept."""
        p, rep, out = self.chain("thirty", "--part", f"scarf=colour:{RED}", "--bones", "3")
        self.assertEqual(p.returncode, 0, p.stdout[-2000:])
        self.assertEqual(rep.get("fps"), 30, rep.get("fps"))
        clips = rep["clips"]
        self.assertEqual((clips["walk"]["kind"], clips["idle"]["kind"], clips["hit"]["kind"]),
                         ("loop", "loop", "one-shot"), clips)
        self.assertEqual(clips["walk"]["motion"], "sway")
        self.assertEqual(clips["walk"]["frames"], [1, 25])
        r = self.probe("thirty", out)
        self.assertLess(r["loop_err"]["walk"], 1e-4)
        self.assertGreater(r["tip_move"]["walk"], 0.02)
        self.assertLess(r["body_bone_err"], 1e-4, "a body bone moved differently")
        data = Path(out).read_bytes()
        doc = json.loads(data[20:20 + int.from_bytes(data[12:16], "little")].decode("utf-8"))
        ends = {a["name"]: max(doc["accessors"][s["input"]]["max"][0] for s in a["samplers"]) for a in doc["animations"]}
        self.assertAlmostEqual(ends["walk"], 24 / 30, places=4, msg=f"walk lasts {ends['walk']} s, not 0.8")
        self.assertAlmostEqual(ends["idle"], 48 / 30, places=4, msg=f"idle lasts {ends['idle']} s, not 1.6")

    def test_the_preview_looks_from_the_side_the_chain_hangs_on(self):
        # #291 live run: a scarf down the chest was hidden in chain.png, which always looked from behind
        for kind, side in (("front", "front"), ("free", "behind")):
            sheet = self.d / f"sheet_{kind}.png"
            p, rep, _ = self.chain(kind, "--part", f"scarf=colour:{RED}", "--sheet", sheet)
            self.assertEqual(p.returncode, 0, p.stdout[-2000:])
            self.assertEqual(rep.get("preview_from"), side, kind)
            self.assertIn(f"seen from {side}", p.stdout)
            self.assertTrue(sheet.is_file(), kind)

    def test_the_command_end_to_end(self):
        """One real `bozzetto.py rig chain` in a scratch game: the model replaced, the backup, the sheet, the note."""
        root = self.d / "game"
        models = root / "assets" / "models"
        models.mkdir(parents=True)
        (root / "docs").mkdir()
        (root / "docs" / "ASSET_LOG.md").write_text(LOG, encoding="utf-8")
        (models / "npc_scarf_rigged.glb").write_bytes((self.d / "free.glb").read_bytes())
        argv = ["rig", "chain", "npc_scarf", "--part", f"scarf=colour:{RED}", "--project", str(root)]
        if BLENDER[0] == "bpy":
            argv += ["--blender", "bpy"]
        else:
            argv += ["--blender", BLENDER[1]]
        code, out = run_main(argv)
        self.assertEqual(code, 0, out)
        work = root / "assets_src" / "bozzetto" / "npc_scarf" / "rig" / "chain"
        self.assertEqual((work / ch.BACKUP).read_bytes(), (self.d / "free.glb").read_bytes())
        self.assertNotEqual((models / "npc_scarf_rigged.glb").read_bytes(), (self.d / "free.glb").read_bytes())
        self.assertTrue((work / "chain.png").is_file())
        self.assertIn("scarf: 4 bones on mixamorig:Neck", out)
        self.assertIn("chain: scarf (4 bones)", (root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=1)
