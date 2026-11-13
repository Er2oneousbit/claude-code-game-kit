#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_retarget.py
# Purpose : The exam for animation packs on a Bozzetto rig (#205): bone_map.py, retarget.py (`bozzetto.py rig
#           retarget`) and rig_retarget.py. No downloaded pack: the source is a small armature built here with the
#           bone names of Quaternius' Universal Animation Library (UE Mannequin naming), resting in a T-pose with
#           rolled bones, keyed at 30 fps; the target is the kit's golden character (Mixamo names, an A-pose, 24 fps).
#           Part 1 (standard library, any Python 3.8+):
#           - the UAL map gives every core Mixamo role to the right bone, the ground root keeps its name; every Mixamo
#             prefix spelling (mixamorig1:, mixamorig_, mixamorig, none) becomes mixamorig:; case does not matter;
#             a skeleton no map fits, two bones meant for one name, and a map file of your own
#           - clip lists and FBX action names (Quaternius' and Mixamo's)
#           - the command with a stand-in Blender: options checked before Blender, the backup of the rig before the
#             first retarget, the record, the asset log note naming the pack's row, a warning when the pack has none,
#             a refused transfer and --no-replace leave the model alone
#           Part 2 (when Blender or the bpy module is found):
#           - rename only: the pack's character comes out with Mixamo bone names on its skin and clips
#           - the transfer onto the golden character: every shared bone points where the pack's bone points in every
#             frame (so the T-pose pack's hanging arms hang on the A-pose rig too, not 40 degrees past), the thigh
#             swings as far as the pack's, the clip keeps its length at the target's 24 fps and loops, the golden
#             character's own clips are untouched, none of the pack's other clips or meshes come along
#           - a pack turned half round is read turned; a mirrored one, a taken clip name, an unknown clip and a
#             skeleton no map fits are refused with exit 1
# Usage   : python tools/bozzetto/test_retarget.py
#           BOZZETTO_TEST_BLENDER=skip|bpy|<path to blender>  picks part 2's Blender (skip: part 1 only)
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bozzetto as bz  # noqa: E402
import bone_map as bm  # noqa: E402
import retarget as rt  # noqa: E402

GOLDEN = HERE.parents[1] / "data" / "golden" / "character" / "character.glb"
UAL_BONES = ["root", "pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "Head",
             "clavicle_l", "upperarm_l", "lowerarm_l", "hand_l", "clavicle_r", "upperarm_r", "lowerarm_r", "hand_r",
             "thumb_01_l", "thumb_04_leaf_l", "index_02_r",
             "thigh_l", "calf_l", "foot_l", "ball_l", "ball_leaf_l", "thigh_r", "calf_r", "foot_r", "ball_r"]
LOG = """# Asset log

| ID | Type | Path | Source | Author | License | Attribution | AI | Edited | Date | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | model | `assets/models/hero.glb` | Bozzetto | generated locally | mit | Built with DINOv3. | pre-generated | no | 2026-01-01 | |
| A-0002 | model | `assets/models/hero_rigged.glb` | UniRig (local) | generated locally | mit | UniRig. | pre-generated | no | 2026-01-01 | rig of A-0001; 24 bones, Mixamo names |
| A-0003 | animation | `assets_src/packs/ual.glb` | quaternius.com | Quaternius | CC0 1.0 | | no | no | 2026-01-01 | |
"""


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = bz.main(argv)
    return code, out.getvalue() + err.getvalue()


# ---- part 1: the bone maps -------------------------------------------------------------------------------------
class MapExam(unittest.TestCase):
    def test_ual_names_map_to_mixamo_roles(self):
        kind, plan = bm.rename_plan(UAL_BONES)
        self.assertEqual(kind, "ual")
        for theirs, ours in (("pelvis", "Hips"), ("spine_01", "Spine"), ("spine_03", "Spine2"), ("neck_01", "Neck"),
                             ("Head", "Head"), ("clavicle_l", "LeftShoulder"), ("upperarm_l", "LeftArm"),
                             ("lowerarm_r", "RightForeArm"), ("hand_r", "RightHand"), ("thigh_l", "LeftUpLeg"),
                             ("calf_r", "RightLeg"), ("foot_l", "LeftFoot"), ("ball_l", "LeftToeBase"),
                             ("ball_leaf_l", "LeftToe_End"), ("thumb_01_l", "LeftHandThumb1"),
                             ("thumb_04_leaf_l", "LeftHandThumb4"), ("index_02_r", "RightHandIndex2")):
            self.assertEqual(plan[theirs], bm.PREFIX + ours, theirs)
        self.assertNotIn("root", plan, "the ground root has no Mixamo role and keeps its name")
        self.assertEqual(len(set(plan.values())), len(plan), "two bones got one name")
        self.assertTrue({bm.PREFIX + c for c in bm.CORE} <= set(plan.values()))

    def test_case_does_not_matter(self):
        kind, plan = bm.rename_plan([n.upper() if n != "root" else n for n in UAL_BONES])
        self.assertEqual((kind, plan["PELVIS"], plan["THIGH_L"]), ("ual", "mixamorig:Hips", "mixamorig:LeftUpLeg"))

    def test_every_mixamo_spelling_becomes_the_prefix(self):
        for spelled in ("mixamorig:Hips", "mixamorig1:Hips", "mixamorig12:Hips", "mixamorig_Hips", "mixamorigHips",
                        "Hips", "MIXAMORIG:hips"):
            self.assertEqual(bm.mixamo_name(spelled), "mixamorig:Hips", spelled)
        self.assertIsNone(bm.mixamo_name("bone_7"))
        roles = ["Hips", "Spine", "Head", "LeftUpLeg", "RightUpLeg", "LeftLeg", "RightLeg", "LeftArm", "RightArm",
                 "LeftForeArm", "RightForeArm", "LeftHand", "RightHand"]
        kind, plan = bm.rename_plan(["mixamorig1:" + r for r in roles])
        self.assertEqual(kind, "mixamo")
        self.assertEqual(plan["mixamorig1:LeftUpLeg"], "mixamorig:LeftUpLeg")
        kind, plan = bm.rename_plan(["mixamorig:" + r for r in roles])
        self.assertEqual(plan, {}, "Mixamo-named already: nothing to rename")

    def test_no_map_fits_and_clashes_are_refused(self):
        with self.assertRaises(bm.MapError) as cm:
            bm.rename_plan(["bone_%d" % i for i in range(20)])
        self.assertIn("--map", str(cm.exception))
        with self.assertRaises(bm.MapError) as cm:          # one Mixamo bone spelled twice
            bm.rename_plan(UAL_BONES + ["mixamorig1:Hips"])
        self.assertIn("both become mixamorig:Hips", str(cm.exception))

    def test_a_map_of_your_own(self):
        with tempfile.TemporaryDirectory() as d:
            names = {"Bip_Pelvis": "Hips", "Bip_Spine": "mixamorig:Spine", "Bip_Head": "Head"}
            for side, s in (("L", "Left"), ("R", "Right")):
                names.update({f"Bip_{side}_Thigh": s + "UpLeg", f"Bip_{side}_Calf": s + "Leg",
                              f"Bip_{side}_UpperArm": s + "Arm", f"Bip_{side}_Forearm": s + "ForeArm",
                              f"Bip_{side}_Hand": s + "Hand"})
            p = Path(d) / "map.json"
            p.write_text(json.dumps(names), encoding="utf-8")
            kind, plan = bm.rename_plan(list(names) + ["Bip_Tail"], p)
            self.assertEqual((kind, plan["Bip_L_Thigh"], plan["Bip_Spine"]),
                             ("map.json", "mixamorig:LeftUpLeg", "mixamorig:Spine"))
            self.assertNotIn("Bip_Tail", plan)
            p.write_text(json.dumps({"Bip_Pelvis": "Pelvis"}), encoding="utf-8")
            with self.assertRaises(bm.MapError):
                bm.load_map(p)

    def test_clip_lists_and_fbx_names(self):
        self.assertEqual(bm.parse_clips("Walk_Loop=walk, Idle_Loop=idle,Jump"),
                         [("Walk_Loop", "walk"), ("Idle_Loop", "idle"), ("Jump", "Jump")])
        self.assertEqual(bm.parse_clips("all"), "all")
        for bad in ("A=b,C=b", "=walk", "A="):
            with self.assertRaises(ValueError, msg=bad):
                bm.parse_clips(bad)
        self.assertEqual(bm.clip_name("Walk_Loop"), "Walk_Loop")
        self.assertEqual(bm.clip_name("Armature|Armature|Walk_Loop"), "Walk_Loop")    # Quaternius' FBX
        self.assertEqual(bm.clip_name("Armature|mixamo.com|Layer0"), "mixamo.com")    # Mixamo's FBX


# ---- part 1: the command with a stand-in Blender ---------------------------------------------------------------
class CliExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bz_retarget_exam_")
        self.root = Path(self.tmp.name) / "game"
        (self.root / "docs").mkdir(parents=True)
        (self.root / "docs" / "ASSET_LOG.md").write_text(LOG, encoding="utf-8")
        models = self.root / "assets" / "models"
        models.mkdir(parents=True)
        self.dst = models / "hero_rigged.glb"
        self.dst.write_bytes(b"glTF-rigged-v1")
        packs = self.root / "assets_src" / "packs"
        packs.mkdir(parents=True)
        (packs / "ual.glb").write_bytes(b"glTF-pack")
        (packs / "unlogged.glb").write_bytes(b"glTF-pack-2")
        self.work = self.root / "assets_src" / "bozzetto" / "hero" / "rig" / "retarget"
        self.saved = (bz.run_bpy, bz.find_blender, os.getcwd())
        bz.find_blender = lambda choice=None: ("blender", "fake-blender")
        bz.run_bpy = self.fake
        self.calls, self.rc = [], 0
        os.chdir(self.root)

    def tearDown(self):
        bz.run_bpy, bz.find_blender, cwd = self.saved
        os.chdir(cwd)
        self.tmp.cleanup()

    def fake(self, blender, script, argv, what):
        """rig_retarget.py stand-in: writes --out (the rig's bytes + '+clips') and --report like the real one."""
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        self.assertEqual(Path(script).name, "rig_retarget.py")
        rep = {"map": "ual", "clips": {"walk_ual": {"from": "Walk_Loop", "frames": 24}},
               "clips_in_file": ["idle", "walk", "walk_ual"],
               "failures": [] if self.rc == 0 else ["the pack and the target face different ways"]}
        if self.rc == 0:
            onto = argv[argv.index("--onto") + 1]
            Path(argv[argv.index("--out") + 1]).write_bytes(Path(onto).read_bytes() + b"+clips")
        Path(argv[argv.index("--report") + 1]).write_text(json.dumps(rep), encoding="utf-8")
        return self.rc, ""

    def retarget(self, *extra, pack="assets_src/packs/ual.glb"):
        return run_main(["rig", "retarget", "hero", "--from", pack, "--clips", "Walk_Loop=walk_ual", *extra])

    def test_options_are_checked_before_blender(self):
        for argv, says in ((["rig", "retarget", "hero", "--from", "assets_src/packs/ual.glb", "--clips", "all"],
                            "--clips is required"),
                           (["rig", "retarget", "hero", "--from", "assets_src/packs/ual.glb", "--clips", "A=x,B=x"],
                            "names two clips"),
                           (["rig", "retarget", "nobody", "--from", "assets_src/packs/ual.glb", "--clips", "A"],
                            "rig the character first"),
                           (["rig", "retarget", "hero", "--from", "nowhere.glb", "--clips", "A"], "not found"),
                           (["rig", "retarget", "hero", "--from", "docs/ASSET_LOG.md", "--clips", "A"], ".fbx"),
                           (["rig", "retarget", "hero", "--from", "assets_src/packs/ual.glb", "--clips", "A",
                             "--map", "no_map.json"], "--map no_map.json")):
            code, out = run_main(argv)
            self.assertEqual(code, 2, (argv, out))
            self.assertIn(says, out, argv)
        self.assertEqual(self.calls, [], "Blender ran before the options were checked")

    def test_a_run_keeps_the_rig_records_and_notes_the_pack(self):
        code, out = self.retarget("--replace")
        self.assertEqual(code, 0, out)
        backup = self.work / rt.BACKUP
        self.assertEqual(backup.read_bytes(), b"glTF-rigged-v1")
        self.assertEqual(self.dst.read_bytes(), b"glTF-rigged-v1+clips")
        argv = self.calls[0]
        self.assertEqual(Path(argv[0]).name, "ual.glb")
        self.assertEqual(Path(argv[argv.index("--onto") + 1]), self.dst.resolve())
        self.assertEqual(argv[argv.index("--clips") + 1], "Walk_Loop=walk_ual")
        for flag in ("--replace", "--sheet"):
            self.assertIn(flag, argv)
        log = (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8")
        row = [l for l in log.splitlines() if l.startswith("| A-0002")][0]
        self.assertIn("retarget: Walk_Loop as walk_ual from A-0003", row)
        self.assertIn("rig of A-0001", row)
        self.assertEqual(len(row.split("|")), len(LOG.splitlines()[-1].split("|")), "the row lost or gained a cell")
        self.assertNotIn("no row of its own", out)
        # a second run adds to the record and keeps the first backup (the rig before any retarget)
        code, out = self.retarget(pack="assets_src/packs/unlogged.glb")
        self.assertEqual(code, 0, out)
        self.assertEqual(backup.read_bytes(), b"glTF-rigged-v1")
        self.assertIn("has no row of its own", out)
        rec = json.loads((self.work / rt.RECORD).read_text(encoding="utf-8"))
        self.assertEqual([r["pack"] for r in rec["runs"]], ["assets_src/packs/ual.glb", "assets_src/packs/unlogged.glb"])
        self.assertEqual(rec["runs"][0]["pack_asset"], "A-0003")
        self.assertEqual(rec["runs"][-1]["output_sha256"], bz.sha256_bytes(self.dst.read_bytes()))

    def test_a_refused_transfer_and_no_replace_leave_the_model_alone(self):
        self.rc = 1
        code, out = self.retarget()
        self.assertEqual(code, 1, out)
        self.assertIn("face different ways", out)
        self.assertEqual(self.dst.read_bytes(), b"glTF-rigged-v1")
        self.rc = 0
        code, out = self.retarget("--no-replace")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.dst.read_bytes(), b"glTF-rigged-v1")
        self.assertEqual((self.work / "retargeted.glb").read_bytes(), b"glTF-rigged-v1+clips")
        self.assertNotIn(rt.NOTE_PREFIX, (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8"))


# ---- part 2: rig_retarget.py in Blender ------------------------------------------------------------------------
# the bpy module crashes while the process ends on Windows (bpy_common.py says more): scripts end themselves (#292)
END = textwrap.dedent('''
    if not bpy.app.binary_path and sys.platform == "win32":
        import ctypes
        sys.stdout.flush()
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k.TerminateProcess(k.GetCurrentProcess(), 0)
''')
ARGV = 'ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]\n'

# A small pack: UAL bone names, T-pose arms along X, bones rolled, facing -Y (left +X), a 30 fps walk whose thighs
# swing WALK_THIGH_DEG each way and whose arms hang ARM_DROP_DEG under horizontal, an idle, and a stray unskinned mesh
# (UAL ships one). Variants: mirrored (left bones on -X), turned (the armature object turned half round), unknown
# (bones named bone_N).
BUILD = textwrap.dedent('''
    import sys, math, bpy
    from mathutils import Vector, Quaternion
    ''') + ARGV + textwrap.dedent('''
    out, kind = ARGV[:2]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = 30
    ad = bpy.data.armatures.new("Armature"); arm = bpy.data.objects.new("Armature", ad)
    bpy.context.scene.collection.objects.link(arm); bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    def bone(name, head, tail, parent=None, roll=0.0):
        b = ad.edit_bones.new(name); b.head, b.tail, b.roll = Vector(head), Vector(tail), roll
        if parent: b.parent = ad.edit_bones[parent]
    bone("root", (0, 0, 0), (0, 0.1, 0))
    bone("pelvis", (0, 0, 0.95), (0, 0, 1.05), "root")
    bone("spine_01", (0, 0, 1.05), (0, 0, 1.2), "pelvis"); bone("spine_02", (0, 0, 1.2), (0, 0, 1.35), "spine_01")
    bone("spine_03", (0, 0, 1.35), (0, 0, 1.5), "spine_02"); bone("neck_01", (0, 0, 1.5), (0, 0, 1.6), "spine_03")
    bone("Head", (0, 0, 1.6), (0, 0, 1.8), "neck_01")
    flip = -1 if kind == "mirrored" else 1
    for s, x in (("l", 1 * flip), ("r", -1 * flip)):
        bone("clavicle_" + s, (0.02 * x, 0, 1.45), (0.15 * x, 0, 1.45), "spine_03")
        bone("upperarm_" + s, (0.15 * x, 0, 1.45), (0.43 * x, 0, 1.45), "clavicle_" + s, roll=-0.5 * x)
        bone("lowerarm_" + s, (0.43 * x, 0, 1.45), (0.7 * x, 0, 1.45), "upperarm_" + s, roll=0.3)
        bone("hand_" + s, (0.7 * x, 0, 1.45), (0.8 * x, 0, 1.45), "lowerarm_" + s)
        bone("thigh_" + s, (0.1 * x, 0, 0.95), (0.1 * x, 0, 0.52), "pelvis", roll=0.7 * x)
        bone("calf_" + s, (0.1 * x, 0, 0.52), (0.1 * x, 0, 0.1), "thigh_" + s)
        bone("foot_" + s, (0.1 * x, 0, 0.1), (0.1 * x, -0.15, 0.02), "calf_" + s)
        bone("ball_" + s, (0.1 * x, -0.15, 0.02), (0.1 * x, -0.22, 0.02), "foot_" + s)
    if kind == "unknown":
        for i, b in enumerate(list(ad.edit_bones)):
            b.name = "bone_%d" % i
    bpy.ops.object.mode_set(mode="OBJECT")
    parts = []
    for b in ad.bones:
        bpy.ops.mesh.primitive_cube_add(size=0.05, location=(b.head_local + b.tail_local) / 2)
        o = bpy.context.active_object
        o.vertex_groups.new(name=b.name).add(list(range(len(o.data.vertices))), 1.0, "REPLACE")
        parts.append(o)
    bpy.ops.object.select_all(action="DESELECT")
    for o in parts: o.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]; bpy.ops.object.join()
    body = bpy.context.active_object; body.name = "Mannequin"; body.parent = arm
    body.modifiers.new("Armature", "ARMATURE").object = arm
    bpy.ops.mesh.primitive_ico_sphere_add(radius=0.05, location=(0, 0, 2.5))     # a stray mesh nothing skins
    if kind != "unknown":
        arm.animation_data_create()
        def key(name, frame, q_world=None, loc_world=None):
            pb = arm.pose.bones[name]; rest = arm.data.bones[name].matrix_local.to_quaternion()
            pb.rotation_mode = "QUATERNION"
            if q_world is not None:
                pb.rotation_quaternion = rest.inverted() @ q_world @ rest
                pb.keyframe_insert("rotation_quaternion", frame=frame)
            if loc_world is not None:
                pb.location = rest.inverted() @ Vector(loc_world)
                pb.keyframe_insert("location", frame=frame)
        def arms(f, swing):
            for s, x in (("l", 1 * flip), ("r", -1 * flip)):
                drop = Quaternion((0, 1, 0), math.radians(ARM_DROP_DEG * x))    # +X arm down about +Y
                key("upperarm_" + s, f, Quaternion((1, 0, 0), math.radians(swing * x)) @ drop)
        for clip, frames in (("Walk_Loop", WALK_FRAMES), ("Idle_Loop", 2 * WALK_FRAMES)):
            act = bpy.data.actions.new(clip); arm.animation_data.action = act
            for f in range(0, frames + 1, 2):
                t = 2 * math.pi * f / frames
                if clip == "Walk_Loop":
                    for s, x, ph in (("l", 1, 0.0), ("r", -1, math.pi)):
                        key("thigh_" + s, f, Quaternion((1, 0, 0), math.radians(WALK_THIGH_DEG * math.sin(t + ph))))
                        key("calf_" + s, f, Quaternion((1, 0, 0), math.radians(-30 * max(0.0, math.sin(t + ph + 1.6)))))
                    arms(f, 15 * math.sin(t))
                    key("pelvis", f, loc_world=(0, 0, 0.02 * abs(math.cos(t))))
                else:
                    arms(f, 2 * math.sin(t))
                    key("Head", f, Quaternion((1, 0, 0), math.radians(4 * math.sin(t))))
            act.use_fake_user = True; arm.animation_data.action = None
    if kind == "turned":
        arm.rotation_euler = (0, 0, math.pi)
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_yup=True, export_animation_mode="ACTIONS")
''')
WALK_FRAMES, WALK_THIGH_DEG, ARM_DROP_DEG = 30, 25.0, 70.0
for _k, _v in (("WALK_FRAMES", WALK_FRAMES), ("WALK_THIGH_DEG", WALK_THIGH_DEG), ("ARM_DROP_DEG", ARM_DROP_DEG)):
    BUILD = BUILD.replace(_k, repr(_v))

# Reads the pack and the transfer's output at the same times and measures: the largest angle between each shared
# bone and the pack's (by the bone map), the thigh's swing in both, the left arm's direction, every clip's frames.
PROBE = textwrap.dedent('''
    import sys, json, math, bpy
    from mathutils import Vector, Matrix
    ''') + ARGV + textwrap.dedent('''
    pack, out, src_clip, out_clip, here, turned = ARGV[:6]
    sys.path.insert(0, here)
    sys.path.insert(0, here + "/../blender")
    import bone_map as bm
    import bpy_common as bc
    Y = Vector((0, 1, 0))
    def load(path):
        bpy.ops.wm.read_factory_settings(use_empty=True)     # the scene stays at 24 fps: both files' times line up
        bpy.ops.import_scene.gltf(filepath=path)
        arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
        bc.adopt_clip_names(bpy)                             # Blender 4.2 names actions "<clip>_<armature>"
        for t in list(arm.animation_data.nla_tracks):
            arm.animation_data.nla_tracks.remove(t)
        return arm, {a.name: a for a in bpy.data.actions}
    def frames_of(path, clip, turn=False):
        arm, acts = load(path)
        a = acts[clip]; ad = arm.animation_data; ad.action = a
        if getattr(ad, "action_slot", 1) is None: ad.action_slot = a.slots[0]
        f0, f1 = (int(round(x)) for x in a.frame_range)
        poses = []
        fix = Matrix.Rotation(math.pi, 4, "Z") if turn else Matrix()   # a turned pack, read as the tool reads it
        for f in range(f0, f1 + 1):
            bpy.context.scene.frame_set(f)
            poses.append({b.name: ((fix @ arm.matrix_world @ b.matrix).to_3x3().normalized() @ Y).normalized()
                          for b in arm.pose.bones if b.bone.length > 1e-4})
        return poses, sorted(acts), f1 - f0
    src, _, src_n = frames_of(pack, src_clip, turned == "1")
    _, plan = bm.rename_plan(list(src[0]))
    src = [{plan.get(k, k): v for k, v in p.items()} for p in src]
    dst, clips, dst_n = frames_of(out, out_clip)
    shared = [n for n in dst[0] if n in src[0] and n.startswith(bm.PREFIX)]
    worst = max(math.degrees(d[n].angle(s[n], 0.0)) for s, d in zip(src, dst) for n in shared)
    def swing(poses, n):
        pitch = [math.degrees(math.atan2(p[n].y, -p[n].z)) for p in poses]
        return max(pitch) - min(pitch)
    gold, _, gold_n = frames_of(out, "walk")
    print("RESULT" + json.dumps({"shared": len(shared), "worst_deg": worst, "src_frames": src_n, "out_frames": dst_n,
        "thigh_src": swing(src, "mixamorig:LeftUpLeg"), "thigh_out": swing(dst, "mixamorig:LeftUpLeg"),
        "loop_deg": max(math.degrees(dst[0][n].angle(dst[-1][n], 0.0)) for n in shared),
        "left_arm": list(dst[0]["mixamorig:LeftArm"]), "golden_walk_frames": gold_n,
        "golden_walk_swing": swing(gold, "mixamorig:LeftUpLeg"), "clips": clips}))
''') + END

# Reads a rename-only output: bone names on the skin and the clips' channel targets.
READ = textwrap.dedent('''
    import sys, json, bpy
    ''') + ARGV + textwrap.dedent('''
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=ARGV[0])
    arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
    body = [o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups][0]
    paths = sorted({fc.data_path.split('"')[1] for a in bpy.data.actions
                    for fc in (a.fcurves if hasattr(a, "fcurves") else [f for l in a.layers for s in l.strips
                                                                         for b in s.channelbags for f in b.fcurves])
                    if fc.data_path.startswith("pose.bones")})
    print("RESULT" + json.dumps({"bones": [b.name for b in arm.data.bones], "groups": [g.name for g in body.vertex_groups],
                                 "animated": paths, "tracks": sorted(t.name for t in arm.animation_data.nla_tracks)}))
''') + END


def glb_json(path):
    data = Path(path).read_bytes()
    return json.loads(data[20:20 + struct.unpack_from("<I", data, 12)[0]].decode("utf-8"))


def pick_blender():
    choice = os.environ.get("BOZZETTO_TEST_BLENDER", "")
    if choice == "skip":
        return None
    return bz.find_blender(choice or None)


BLENDER = pick_blender()


def blender_run(script, argv):
    kind, path = BLENDER
    cmd = ([path, "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(script), "--"] if kind == "blender"
           else [path, str(script)]) + [str(a) for a in argv]
    return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=900)


@unittest.skipUnless(BLENDER, "no Blender or bpy found (part 2 skipped)")
class RetargetExam(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="bz_retarget_bpy_")
        cls.d = Path(cls.tmp.name)
        builder = cls.d / "build.py"
        builder.write_text(BUILD + END, encoding="utf-8")
        for kind in ("pack", "mirrored", "turned", "unknown"):
            p = blender_run(builder, [cls.d / f"{kind}.glb", kind])
            assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
        cls.out = cls.d / "onto_golden.glb"
        cls.first = cls.retarget("pack", "--onto", GOLDEN, "--out", cls.out, "--clips", "Walk_Loop=walk_pack")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def retarget(cls, kind, *extra):
        rep = cls.d / f"{kind}_{len(list(cls.d.glob('*.json')))}.json"
        p = blender_run(HERE / "rig_retarget.py", [cls.d / f"{kind}.glb", "--report", rep, *extra])
        return p, (json.loads(rep.read_text(encoding="utf-8")) if rep.is_file() else {})

    def run_script(self, name, body, argv):
        script = self.d / f"{name}.py"
        script.write_text(body, encoding="utf-8")
        q = blender_run(script, argv)
        line = next((l for l in q.stdout.splitlines() if l.startswith("RESULT")), None)
        self.assertIsNotNone(line, q.stdout[-3000:] + q.stderr[-2000:])
        return json.loads(line[len("RESULT"):])

    def probe(self, out, out_clip, pack="pack", turned=False):
        return self.run_script("probe", PROBE, [self.d / f"{pack}.glb", out, "Walk_Loop", out_clip, HERE,
                                                "1" if turned else "0"])

    def test_transfer_points_every_shared_bone_where_the_pack_does(self):
        p, rep = self.first
        self.assertEqual(p.returncode, 0, p.stdout[-3000:])
        self.assertEqual((rep["map"], rep["failures"]), ("ual", []))
        self.assertEqual(rep["clips"]["walk_pack"]["fps"], 24)
        r = self.probe(self.out, "walk_pack")
        self.assertEqual(r["shared"], 22, "every golden bone has a pack bone")
        self.assertLess(r["worst_deg"], 1.0, r)
        # the pack's 30 fps second comes out as 24 frames at the golden character's 24 fps, and still loops
        self.assertEqual((r["src_frames"], r["out_frames"]), (24, 24))
        self.assertLess(r["loop_deg"], 0.5)
        self.assertAlmostEqual(r["thigh_out"], r["thigh_src"], delta=0.5)
        self.assertAlmostEqual(r["thigh_src"], 2 * WALK_THIGH_DEG, delta=1.0)
        # T-pose pack, A-pose target: the arm hangs ARM_DROP_DEG under horizontal on the left, not past the body
        x, _, z = r["left_arm"]
        self.assertAlmostEqual(math.degrees(math.atan2(-z, x)), ARM_DROP_DEG, delta=3.0)
        # the golden character's own clips are as they were; nothing of the pack came along
        self.assertEqual((r["golden_walk_frames"], round(r["golden_walk_swing"])), (24, 56))
        self.assertEqual(r["clips"], ["idle", "walk", "walk_pack"])
        meshes = [n.get("name") for n in glb_json(self.out)["nodes"] if "mesh" in n]
        self.assertEqual(meshes, ["KitCharacterBody"], "the pack's mannequin and stray mesh stay behind")

    def test_rename_only_names_the_skin_and_the_clips(self):
        out = self.d / "renamed.glb"
        p, rep = self.retarget("pack", "--out", out, "--clips", "Walk_Loop=walk,Idle_Loop=idle")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:])
        r = self.run_script("read", READ, [out])
        for n in ("mixamorig:Hips", "mixamorig:LeftUpLeg", "mixamorig:RightForeArm", "root"):
            self.assertIn(n, r["bones"])
        self.assertNotIn("pelvis", r["bones"])
        self.assertIn("mixamorig:LeftUpLeg", r["groups"], "the skin's vertex groups follow the bones")
        self.assertNotIn("thigh_l", r["groups"])
        self.assertIn("mixamorig:LeftUpLeg", r["animated"], "the clips' channels follow the bones")
        self.assertNotIn("thigh_l", r["animated"])
        self.assertEqual(r["tracks"], ["idle", "walk"])

    def test_a_pack_turned_half_round_is_read_turned(self):
        out = self.d / "turned_out.glb"
        p, rep = self.retarget("turned", "--onto", GOLDEN, "--out", out, "--clips", "Walk_Loop=walk_turned")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:])
        self.assertTrue(rep["pack_turned"])
        r = self.probe(out, "walk_turned", pack="turned", turned=True)
        self.assertLess(r["worst_deg"], 1.0, r)
        self.assertAlmostEqual(r["thigh_out"], 2 * WALK_THIGH_DEG, delta=1.0)

    def test_refusals_exit_1_and_write_nothing(self):
        for kind, extra, says in (
                ("mirrored", ["--clips", "Walk_Loop=w"], "face different ways"),
                ("pack", ["--clips", "Walk_Loop=walk"], "already has a clip 'walk'"),
                ("pack", ["--clips", "Run_Loop=run"], "no clip 'Run_Loop'"),
                ("unknown", ["--clips", "Walk_Loop=w"], "no bone map fits")):
            out = self.d / f"refused_{kind}.glb"
            p, rep = self.retarget(kind, "--onto", GOLDEN, "--out", out, *extra)
            self.assertEqual(p.returncode, 1, (kind, p.stdout[-2000:]))
            self.assertTrue(any(says in f for f in rep["failures"]), (says, rep))
            self.assertFalse(out.exists(), kind)

    def test_replace_swaps_a_clip_of_the_same_name(self):
        out = self.d / "replaced.glb"
        p, rep = self.retarget("pack", "--onto", GOLDEN, "--out", out, "--clips", "Walk_Loop=walk", "--replace")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:])
        self.assertEqual(rep["clips_in_file"], ["idle", "walk"])
        r = self.probe(out, "walk")
        self.assertLess(r["worst_deg"], 1.0, r)


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=2)
