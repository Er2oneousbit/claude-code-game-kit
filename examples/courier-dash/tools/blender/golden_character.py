#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# golden_character.py
# Purpose : Build the kit's golden rigged character, data/golden/character/character.glb: a small blocky biped with
#           Mixamo bone names (mixamorig:Hips ...), as Bozzetto's rig routes name them, and two looping clips (idle,
#           walk). Every engine's test loads it, plays walk and checks that a bone moved; render_sprites.py renders
#           it into the 8-direction sheet fixture. Made here from boxes and sine waves: no third-party or AI asset.
# Usage   : Inside Blender (any OS):
#             blender -b --factory-startup --python-exit-code 1 -P tools/blender/golden_character.py -- [options]
#           With the bpy module:  python tools/blender/golden_character.py [options]
#           Options: --out <file.glb> (default data/golden/character/character.glb next to tools/),
#                    --expected <file.json> (default expected.json beside --out), --debug
# Needs   : Blender 4.2+ or the bpy module
# Exit    : 0 written, 1 the build failed, 2 usage or environment (no bpy)
# Notes   : Blender space: +Z up, the character faces -Y (glTF +Z front after export), left is +X, metres, feet on
#           the ground at the origin. Each body part is one box weighted fully to one bone (rigid skinning: seams at
#           the joints, which a test fixture does not mind). Arms rest in an A-pose, 40 degrees under horizontal,
#           like Bozzetto rigs. Clips are keyed like rig_finish.py's: rotations in the character's frame converted
#           into each bone's own frame, each clip its own action, exported with export_animation_mode ACTIONS.
#           Both clips loop: the last key equals the first, so a glTF clip's last frame repeats its first
#           (render_sprites.py drops that duplicate for a looping sprite clip).
#           expected.json records what engine tests compare: bone names, root bone, clip names and lengths, the
#           bone that moves most in walk, height. The exam (test_golden_character.py) checks the .glb against it.
#           With the bpy module on Windows the process is ended through bpy_common.end_process (#292): a plain exit
#           after a glTF export crashed (bpy 4.2) and hid the exit code.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): the bpy module's exit crash (#292)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   empty scene -> armature with the bones below (edit mode: head, tail, parent)
#   one mesh: a box per part along its bone, vertex group = that bone, weight 1; a material per colour
#   parent the mesh to the armature with an Armature modifier
#   key idle (48 frames) and walk (24 frames) at 24 fps, each its own action
#   export .glb (+Y up, animations as ACTIONS) -> write expected.json from what was built
import argparse
import json
import math
import sys
from pathlib import Path

# --- tunables -------------------------------------------------------------------------------------------------
FPS = 24
IDLE_FRAMES, WALK_FRAMES = 48, 24          # loop lengths in frames (2 s and 1 s)
IDLE_KEY_STEP, WALK_KEY_STEP = 4, 2        # a key every this many frames
IDLE_BREATH_DEG, IDLE_NOD_DEG, IDLE_ARM_DEG, IDLE_BOB = 3.0, 4.0, 4.0, 0.008
WALK_THIGH_DEG, WALK_KNEE_DEG, WALK_ARM_DEG, WALK_ELBOW_DEG, WALK_BOB = 28.0, 40.0, 24.0, 15.0, 0.025
ARM_DROP_DEG = 40.0                        # A-pose: arms this far under horizontal at rest
PREFIX = "mixamorig:"
MOVING_BONE = "LeftUpLeg"                  # the bone engine tests watch in walk (it swings 2 x WALK_THIGH_DEG)
SIDE, FRONT, UP = (1, 0, 0), (0, -1, 0), (0, 0, 1)
COLOURS = {"skin": (0.86, 0.66, 0.52), "shirt": (0.13, 0.55, 0.55), "trousers": (0.16, 0.2, 0.42),
           "shoes": (0.18, 0.12, 0.1)}

# Bones: name, head (x, y, z), tail, parent. Left is +X. Mixamo's names and hierarchy (Unity's Humanoid and
# Mixamo-style animation packs map them).
_A = math.radians(ARM_DROP_DEG)


def _arm(x0, z0, length):
    """A point `length` along an A-pose arm from (x0, z0); sign of x0 picks the side."""
    s = 1 if x0 > 0 else -1
    return (x0 + s * length * math.cos(_A), 0.0, z0 - length * math.sin(_A))


BONES = [
    ("Hips", (0, 0, 0.95), (0, 0, 1.05), None),
    ("Spine", (0, 0, 1.05), (0, 0, 1.18), "Hips"),
    ("Spine1", (0, 0, 1.18), (0, 0, 1.31), "Spine"),
    ("Spine2", (0, 0, 1.31), (0, 0, 1.46), "Spine1"),
    ("Neck", (0, 0, 1.46), (0, 0, 1.56), "Spine2"),
    ("Head", (0, 0, 1.56), (0, 0, 1.8), "Neck"),
]
for _side, _s in (("Left", 1), ("Right", -1)):
    _sh = (_s * 0.04, 0, 1.43)
    _a0 = (_s * 0.17, 0, 1.43)
    BONES += [
        (_side + "Shoulder", _sh, _a0, "Spine2"),
        (_side + "Arm", _a0, _arm(_a0[0], _a0[2], 0.27), _side + "Shoulder"),
        (_side + "ForeArm", _arm(_a0[0], _a0[2], 0.27), _arm(_a0[0], _a0[2], 0.52), _side + "Arm"),
        (_side + "Hand", _arm(_a0[0], _a0[2], 0.52), _arm(_a0[0], _a0[2], 0.62), _side + "ForeArm"),
        (_side + "UpLeg", (_s * 0.1, 0, 0.95), (_s * 0.1, 0, 0.52), "Hips"),
        (_side + "Leg", (_s * 0.1, 0, 0.52), (_s * 0.1, 0, 0.09), _side + "UpLeg"),
        (_side + "Foot", (_s * 0.1, 0, 0.09), (_s * 0.1, -0.12, 0.03), _side + "Leg"),
        (_side + "ToeBase", (_s * 0.1, -0.12, 0.03), (_s * 0.1, -0.2, 0.03), _side + "Foot"),
    ]

# Boxes: bone -> (width across, depth, material, start offset along the bone, end offset). Offsets in metres extend
# the box past the bone's head (negative start) or tail, so joints overlap and the feet reach the ground.
BOXES = {
    "Hips": (0.32, 0.2, "trousers", -0.06, 0.0), "Spine": (0.3, 0.19, "shirt", 0, 0), "Spine1": (0.32, 0.2, "shirt", 0, 0),
    "Spine2": (0.38, 0.22, "shirt", 0, 0.02), "Neck": (0.09, 0.09, "skin", 0, 0), "Head": (0.22, 0.24, "skin", 0, 0),
    "Arm": (0.09, 0.09, "shirt", -0.03, 0), "ForeArm": (0.08, 0.08, "skin", 0, 0), "Hand": (0.09, 0.05, "skin", 0, 0.02),
    "UpLeg": (0.14, 0.15, "trousers", 0, 0), "Leg": (0.11, 0.12, "trousers", 0, 0.03),
    "Foot": (0.1, 0.07, "shoes", -0.03, 0.0), "ToeBase": (0.1, 0.06, "shoes", 0, 0),
}
NOSE = (0.05, 0.06, 0.05)                  # a box on the face's front, so a sprite shows which way it faces


def dbg(on, msg):
    if on:
        print(f"[debug] {msg}")


def script_argv():
    """Blender passes its own args first; ours come after a lone '--'."""
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else argv[1:]


def parse(argv):
    here = Path(__file__).resolve().parent
    default = here.parents[1] / "data" / "golden" / "character" / "character.glb"
    ap = argparse.ArgumentParser(prog="golden_character.py",
                                 description="Build the golden rigged character (Mixamo names, idle and walk clips).")
    ap.add_argument("--out", default=str(default), help=f"the .glb to write (default {default})")
    ap.add_argument("--expected", help="expected.json to write (default: beside --out)")
    ap.add_argument("--debug", action="store_true", help="verbose output")
    a = ap.parse_args(argv)
    if not a.out.lower().endswith(".glb"):
        ap.error("--out must end in .glb")
    return a


# --- build ----------------------------------------------------------------------------------------------------
def build_armature(bpy):
    data = bpy.data.armatures.new("KitCharacter")
    arm = bpy.data.objects.new("KitCharacter", data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    made = {}
    for name, head, tail, parent in BONES:
        b = data.edit_bones.new(PREFIX + name)
        b.head, b.tail = head, tail
        b.roll = 0.0
        if parent:
            b.parent = made[parent]
            b.use_connect = False
        made[name] = b
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def part_of(name):
    for side in ("Left", "Right"):
        if name.startswith(side):
            return name[len(side):]
    return name


def build_mesh(bpy, arm):
    """One mesh, a box per bone (and a nose), each box weighted fully to its bone."""
    import bmesh
    from mathutils import Matrix, Vector
    mesh = bpy.data.meshes.new("KitCharacterBody")
    obj = bpy.data.objects.new("KitCharacterBody", mesh)
    bpy.context.scene.collection.objects.link(obj)
    mats = {}
    for key, rgb in COLOURS.items():
        m = bpy.data.materials.new(key)
        m.diffuse_color = (*rgb, 1.0)
        if bpy.app.version < (5, 0, 0):   # 5.x materials always have nodes
            m.use_nodes = True
        bsdf = m.node_tree.nodes.get("Principled BSDF") if m.node_tree else None
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.8
        obj.data.materials.append(m)
        mats[key] = len(mats)
    bm = bmesh.new()
    deform = bm.verts.layers.deform.verify()
    groups = {}

    def add_box(bone, w, d, mat, y0, y1, extra=None):
        """Box in the bone's own frame (y along the bone), moved to armature space by its rest matrix."""
        g = groups.setdefault(bone.name, obj.vertex_groups.new(name=bone.name).index)
        m = bone.matrix_local @ (extra or Matrix.Identity(4))
        corners = [(x, y, z) for x in (-w / 2, w / 2) for y in (y0, y1) for z in (-d / 2, d / 2)]
        vs = [bm.verts.new(m @ Vector(c)) for c in corners]
        for v in vs:
            v[deform][g] = 1.0
        for idx in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            f = bm.faces.new([vs[i] for i in idx])
            f.material_index = mats[mat]

    for b in arm.data.bones:
        part = part_of(b.name[len(PREFIX):])
        if part not in BOXES:
            continue
        w, d, mat, s0, s1 = BOXES[part]
        add_box(b, w, d, mat, s0, b.length + s1)
    head = arm.data.bones[PREFIX + "Head"]
    nw, nd, nh = NOSE
    # the nose: in the head bone's frame, y runs up the head and z points to the face's front (bone roll 0 on a
    # vertical bone puts local z on -Y, the character's front)
    front = head.matrix_local.to_3x3().inverted() @ Vector(FRONT)
    nose = Matrix.Translation(front * 0.13)
    add_box(head, nw, nd, "skin", 0.06, 0.06 + nh, nose)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    obj.parent = arm
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    return obj


def local_rot(bone, axis, deg):
    """A rotation about `axis` (character frame) as the bone's own pose rotation."""
    from mathutils import Quaternion, Vector
    rest = bone.matrix_local.to_quaternion()
    return rest.inverted() @ Quaternion(Vector(axis), math.radians(deg)) @ rest


def key_rot(arm, name, frame, q):
    pb = arm.pose.bones[PREFIX + name]
    pb.rotation_mode = "QUATERNION"
    pb.rotation_quaternion = q
    pb.keyframe_insert("rotation_quaternion", frame=frame)


def key_loc(arm, name, frame, offset):
    from mathutils import Vector
    bone = arm.data.bones[PREFIX + name]
    pb = arm.pose.bones[PREFIX + name]
    pb.location = bone.matrix_local.to_quaternion().inverted() @ Vector(offset)
    pb.keyframe_insert("location", frame=frame)


def new_action(bpy, arm, name):
    from mathutils import Quaternion, Vector
    act = bpy.data.actions.new(name)
    arm.animation_data_create()
    arm.animation_data.action = act
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = Quaternion()
        pb.location = Vector()
    return act


def finish_action(arm, act):
    act.use_fake_user = True
    arm.animation_data.action = None


def clip_idle(bpy, arm):
    act = new_action(bpy, arm, "idle")
    bones = arm.data.bones
    for f in range(0, IDLE_FRAMES + 1, IDLE_KEY_STEP):
        t = 2 * math.pi * f / IDLE_FRAMES
        for s in ("Spine1", "Spine2"):
            key_rot(arm, s, f + 1, local_rot(bones[PREFIX + s], SIDE, IDLE_BREATH_DEG / 2 * math.sin(t)))
        key_rot(arm, "Head", f + 1, local_rot(bones[PREFIX + "Head"], SIDE, IDLE_NOD_DEG * math.sin(t + 0.6)))
        for side, sgn in (("Left", 1), ("Right", -1)):
            key_rot(arm, side + "Arm", f + 1,
                    local_rot(bones[PREFIX + side + "Arm"], FRONT, sgn * IDLE_ARM_DEG * math.sin(t + 1.2)))
        key_loc(arm, "Hips", f + 1, (0, 0, IDLE_BOB * math.sin(t)))
    finish_action(arm, act)
    return act


def clip_walk(bpy, arm):
    act = new_action(bpy, arm, "walk")
    bones = arm.data.bones
    for f in range(0, WALK_FRAMES + 1, WALK_KEY_STEP):
        t = 2 * math.pi * f / WALK_FRAMES
        for side, ph in (("Left", 0.0), ("Right", math.pi)):
            # + about X swings a leg backward (the character faces -Y); a knee bends the same way
            key_rot(arm, side + "UpLeg", f + 1,
                    local_rot(bones[PREFIX + side + "UpLeg"], SIDE, -WALK_THIGH_DEG * math.sin(t + ph)))
            key_rot(arm, side + "Leg", f + 1, local_rot(bones[PREFIX + side + "Leg"], SIDE,
                                                        WALK_KNEE_DEG * max(0.0, math.sin(t + ph + math.pi / 2))))
        for side, ph in (("Left", math.pi), ("Right", 0.0)):
            key_rot(arm, side + "Arm", f + 1,
                    local_rot(bones[PREFIX + side + "Arm"], SIDE, -WALK_ARM_DEG * math.sin(t + ph)))
            key_rot(arm, side + "ForeArm", f + 1, local_rot(bones[PREFIX + side + "ForeArm"], SIDE, -WALK_ELBOW_DEG))
        key_loc(arm, "Hips", f + 1, (0, 0, WALK_BOB * abs(math.cos(t))))
    finish_action(arm, act)
    return act


def height_of(bpy, obj):
    from mathutils import Vector
    zs = [(obj.matrix_world @ Vector(c)).z for c in obj.bound_box]
    return max(zs) - min(zs), min(zs)


def build(bpy, out, expected_path, debug):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps, scene.render.fps_base = FPS, 1.0
    arm = build_armature(bpy)
    body = build_mesh(bpy, arm)
    height, floor = height_of(bpy, body)
    dbg(debug, f"{len(arm.data.bones)} bones, {len(body.data.polygons)} faces, height {height:.3f} m, floor {floor:.3f}")
    clips = [clip_idle(bpy, arm), clip_walk(bpy, arm)]
    scene.frame_start, scene.frame_end = 1, IDLE_FRAMES + 1
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(out), export_format="GLB", export_yup=True, export_animations=True,
                              export_animation_mode="ACTIONS", export_skins=True, export_def_bones=False,
                              export_anim_slide_to_zero=True)   # keys from 0 s: a clip starting at frame 1 (1/24 s)
                                                                # holds its first pose an extra frame on every loop
    frames = {"idle": IDLE_FRAMES, "walk": WALK_FRAMES}
    exp = {
        "file": out.name,
        "note": "written by tools/blender/golden_character.py; engine tests compare with these numbers",
        "up": "+Y", "front": "+Z", "units": "metres", "fps": FPS,
        "height_m": round(height, 4),
        "triangles": sum(len(p.vertices) - 2 for p in body.data.polygons),
        "root_bone": PREFIX + "Hips",
        "bones": [b.name for b in arm.data.bones],
        "clips": {c.name: {"frames": frames[c.name], "seconds": round(frames[c.name] / FPS, 6), "loop": True}
                  for c in clips},
        "moving_bone": PREFIX + MOVING_BONE,
        "moving_bone_swing_deg": 2 * WALK_THIGH_DEG,
        "bone_names_in_engines": {   # what each engine's import makes of mixamorig:Hips (#290, each engine's test)
            "glTF": PREFIX + "Hips", "Godot": "mixamorig_Hips", "Unreal": "mixamorig_Hips",
            "three.js": "mixamorigHips", "Unity (glTFast)": PREFIX + "Hips", "Bevy": PREFIX + "Hips"},
    }
    with open(expected_path, "w", encoding="utf-8", newline="\n") as fh:   # LF on Windows too, as git stores it
        fh.write(json.dumps(exp, indent=1) + "\n")
    size = out.stat().st_size
    clip_text = ", ".join("%s %d frames" % (k, v["frames"]) for k, v in exp["clips"].items())
    print(f"[ OK ] {out}: {len(exp['bones'])} bones, {exp['triangles']} triangles, {exp['height_m']} m, "
          f"clips {clip_text}, {size // 1024} KB")
    print(f"[ OK ] {expected_path}")
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        a = parse(script_argv())
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        import bpy
    except ImportError:
        print("[ENV ] bpy not available. Run inside Blender:\n"
              "         blender -b --factory-startup --python-exit-code 1 -P tools/blender/golden_character.py --\n"
              "       or with the bpy module for your Python version (pip install bpy)", file=sys.stderr)
        return 2
    out = Path(a.out).resolve()
    expected = Path(a.expected).resolve() if a.expected else out.with_name("expected.json")
    try:
        return build(bpy, out, expected, a.debug)
    except Exception as exc:  # keep the exit-code contract on surprises
        print(f"[error] golden_character failed: {exc!r}. Re-run with --debug.", file=sys.stderr)
        if a.debug:
            raise
        return 1


def exit_with(code):
    """sys.exit, or with the bpy module on Windows the process end that does not crash after a glTF export (#292)."""
    try:
        import bpy
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import bpy_common
    except ImportError:
        sys.exit(code)
    bpy_common.end_process(bpy, code)


if __name__ == "__main__":
    exit_with(main())
