# ---------------------------------------------------------------------------
# animate_rig.py
# Purpose : Give an auto-rigged character (UniRig output: bones named bone_0..bone_N, no labels) three looping
#           animations, idle, wave and walk, by finding its body parts from the skeleton's shape, then export a
#           .glb that an engine plays (one glTF animation per clip). A showcase script for #199, not a kit tool yet.
# Usage   : blender -b --python-exit-code 1 -P animate_rig.py -- <rigged.glb> --out <animated.glb>
#               [--sheet <preview.png>] [--debug]
#           --sheet renders 4 frames of each clip (Workbench) into one picture, to check the motion by eye.
# Notes   : Assumes a biped standing on the ground, facing -Y in Blender (glTF +Z, where TRELLIS.2 and Bozzetto put
#           the front). Motion is hand-tuned keyframes, game-jam quality, not mocap. Rotations are chosen in armature
#           space (side X, front Y, up Z) and converted into each bone's own frame, so UniRig's arbitrary bone rolls
#           do not flip a swing. Exit 0 ok, 1 the skeleton is not a recognisable biped, 2 usage.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   import glb -> armature + skinned meshes
#   spine = path root -> bone whose tail is highest (the head)
#   limbs = subtrees hanging off the spine; main chain of each = follow the child with the longest reach
#   legs  = the two limbs whose lowest point is nearest the floor (left/right by sign of X)
#   arms  = the two remaining limbs reaching farthest out sideways
#   for clip in idle, wave, walk: keyframe rotations (armature-space axis + angle -> bone-local quaternion)
#   one action per clip, pushed to NLA tracks -> glTF export with every action as its own animation
import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

# --- tunables -------------------------------------------------------------------------------------------------
FPS = 24
IDLE_FRAMES = 48          # 2 s loop
WAVE_FRAMES = 48          # 2 s loop: raise, three waves, the raise held across the loop seam
WALK_FRAMES = 24          # 1 s per stride pair
IDLE_BREATH_DEG = 2.5     # spine pitch in and out
IDLE_NOD_DEG = 3.0
IDLE_ARM_DEG = 4.0
WAVE_RAISE_DEG = 105.0    # upper arm from its rest angle up toward overhead
RELAX_BELOW_DEG = 70.0    # idle and walk: arms hang this far under horizontal instead of the A-pose
WAVE_SWING_DEG = 28.0     # forearm side to side
WALK_THIGH_DEG = 24.0
WALK_KNEE_DEG = 38.0
WALK_ARM_DEG = 18.0
WALK_BOB = 0.025          # root up-down, as a fraction of body height
WALK_TWIST_DEG = 4.0      # spine counter-twist
SIDE, FRONT, UP = Vector((1, 0, 0)), Vector((0, -1, 0)), Vector((0, 0, 1))   # character faces -Y


def parse():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="animate_rig.py", description=__doc__)
    ap.add_argument("rigged", help="rigged .glb (UniRig output)")
    ap.add_argument("--out", required=True, help="animated .glb to write")
    ap.add_argument("--sheet", help="also render a preview contact sheet (.png)")
    ap.add_argument("--debug", action="store_true", help="print the bone map")
    return ap.parse_args(argv)


def fail(msg, code=1):
    print(f"[error] {msg}")
    sys.exit(code)


# --- skeleton analysis -----------------------------------------------------------------------------------------
def reach(bone):
    """Longest root-to-leaf length below and including this bone (picks a limb's main chain)."""
    return bone.length + max((reach(c) for c in bone.children), default=0.0)


def main_chain(bone):
    chain = [bone]
    while bone.children:
        bone = max(bone.children, key=reach)
        chain.append(bone)
    return chain


def subtree(bone):
    out = [bone]
    for c in bone.children:
        out += subtree(c)
    return out


def map_biped(arm):
    bones = [b for b in arm.data.bones if b.name != "neutral_bone"]
    roots = [b for b in bones if b.parent is None]
    if len(roots) != 1:
        fail(f"expected one root bone, found {len(roots)}")
    root = roots[0]
    lo = min(min(b.head_local.z, b.tail_local.z) for b in bones)
    hi = max(max(b.head_local.z, b.tail_local.z) for b in bones)
    height = hi - lo
    head_leaf = max(bones, key=lambda b: b.tail_local.z)
    spine = []
    b = head_leaf
    while b is not None:
        spine.insert(0, b)
        b = b.parent
    on_spine = set(spine)
    limbs = [c for s in spine for c in s.children if c not in on_spine]
    if len(limbs) < 4:
        fail(f"expected at least 4 limbs off the spine (2 legs, 2 arms), found {len(limbs)}")

    def low(l): return min(min(x.head_local.z, x.tail_local.z) for x in subtree(l))
    def side(l): return max((x.tail_local.x for x in subtree(l)), key=abs)

    by_low = sorted(limbs, key=low)
    legs = by_low[:2]
    if any(low(l) - lo > 0.25 * height for l in legs):
        fail("no two limbs reach the floor: not a standing biped")
    if len(by_low) > 2 and low(by_low[2]) - lo < 0.25 * height:
        fail("more than two limbs reach the floor: a quadruped or a creature, not a biped (this script does bipeds)")
    rest = [l for l in limbs if l not in legs]
    arms = sorted(rest, key=lambda l: -abs(side(l)))[:2]
    if (side(arms[0]) > 0) == (side(arms[1]) > 0):
        fail("both arm candidates are on the same side")
    if (side(legs[0]) > 0) == (side(legs[1]) > 0):
        fail("both leg candidates are on the same side")
    # character's right is screen-left when it faces -Y: negative X
    rmap = {"leg_r": min(legs, key=side), "leg_l": max(legs, key=side),
            "arm_r": min(arms, key=side), "arm_l": max(arms, key=side)}
    m = {k: main_chain(v) for k, v in rmap.items()}
    m["spine"] = spine[:-1] if len(spine) > 2 else spine   # all but the head bone
    m["head"] = [spine[-1]]
    m["root"] = root
    m["height"] = height
    return m


# --- keyframing helpers ----------------------------------------------------------------------------------------
def local_rot(bone, axis, deg):
    """A rotation about an armature-space axis, expressed in the bone's own frame (what pose bones store)."""
    rest = bone.matrix_local.to_quaternion()
    q = Quaternion(axis, math.radians(deg))
    return rest.inverted() @ q @ rest


def key_rot(pose, bone, frame, q):
    pb = pose.bones[bone.name]
    pb.rotation_mode = "QUATERNION"
    pb.rotation_quaternion = q
    pb.keyframe_insert("rotation_quaternion", frame=frame)


def key_loc(pose, bone, frame, arm_space_offset):
    pb = pose.bones[bone.name]
    pb.location = bone.matrix_local.to_quaternion().inverted() @ arm_space_offset
    pb.keyframe_insert("location", frame=frame)


def local_q(bone, q_arm):
    """An armature-space rotation (a Quaternion) expressed in the bone's own frame."""
    rest = bone.matrix_local.to_quaternion()
    return rest.inverted() @ q_arm @ rest


def upper_of(chain):
    """The upper arm: skip a shoulder/clavicle bone when the chain is long enough to have one."""
    return chain[1] if len(chain) >= 4 else chain[0]


def relax(bone, sgn):
    """Armature-space rotation that drops an A-pose arm to RELAX_BELOW_DEG under horizontal, from its own rest angle."""
    d = (bone.tail_local - bone.head_local).normalized()
    below = -math.degrees(math.asin(max(-1.0, min(1.0, d.z))))      # rest angle under horizontal
    drop = max(0.0, RELAX_BELOW_DEG - below)
    return Quaternion(FRONT, math.radians(-sgn * drop))              # -sgn lowers (+sgn raises)


def outward(chain):
    """+1 when the limb sits on +X, -1 on -X: flips sideways rotations so both arms mirror."""
    return 1 if chain[-1].tail_local.x > 0 else -1


def new_action(arm, name):
    act = bpy.data.actions.new(name)
    arm.animation_data_create()
    arm.animation_data.action = act
    for pb in arm.pose.bones:   # every clip starts from rest, so clips do not leak into each other
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = Quaternion()
        pb.location = Vector()
    return act


def finish(arm, act, frames):
    # Each clip stays a standalone action (fake user keeps it), exported with export_animation_mode="ACTIONS".
    # No NLA tracks: in Blender 5.2, slot-less NLA strips evaluated on top during the exporter's bake and pinned
    # every clip to the rest pose (every exported channel flat, exit 0 everywhere).
    act.use_fake_user = True
    act["clip_frames"] = frames
    CLIPS.append(act)
    arm.animation_data.action = None


CLIPS = []   # the actions made, in order, for the preview sheet


# --- the three clips -------------------------------------------------------------------------------------------
def clip_idle(arm, m):
    act = new_action(arm, "idle")
    P = arm.pose
    for f in range(0, IDLE_FRAMES + 1, 6):
        t = 2 * math.pi * f / IDLE_FRAMES
        for s in m["spine"][1:]:
            key_rot(P, s, f + 1, local_rot(s, SIDE, IDLE_BREATH_DEG * math.sin(t) / max(1, len(m["spine"]) - 1)))
        key_rot(P, m["head"][0], f + 1, local_rot(m["head"][0], SIDE, IDLE_NOD_DEG * math.sin(t + 0.6)))
        for k in ("arm_l", "arm_r"):
            c = m[k]; up = upper_of(c); sgn = outward(c)
            sway = Quaternion(FRONT, math.radians(sgn * IDLE_ARM_DEG * math.sin(t + 1.2)))
            key_rot(P, up, f + 1, local_q(up, sway @ relax(up, sgn)))
    finish(arm, act, IDLE_FRAMES)


def clip_wave(arm, m):
    act = new_action(arm, "wave")
    P = arm.pose
    c = m["arm_r"]
    upper = upper_of(c)
    fore = c[c.index(upper) + 1] if c.index(upper) + 1 < len(c) else None
    sgn = outward(c)
    other = m["arm_l"]
    for f in range(0, WAVE_FRAMES + 1, 3):
        u = f / WAVE_FRAMES
        # the waving arm is held up for the whole loop (no pop at the seam); about FRONT, +sgn raises an arm
        key_rot(P, upper, f + 1, local_rot(upper, FRONT, sgn * WAVE_RAISE_DEG))
        if fore is not None:
            key_rot(P, fore, f + 1, local_rot(fore, FRONT, sgn * WAVE_SWING_DEG * math.sin(2 * math.pi * 3 * u)))
        ou = upper_of(other)
        key_rot(P, ou, f + 1, local_q(ou, relax(ou, outward(other))))          # the other arm rests at the side
        key_rot(P, m["head"][0], f + 1, local_rot(m["head"][0], FRONT, sgn * 5))   # a small head tilt toward it
    finish(arm, act, WAVE_FRAMES)


def clip_walk(arm, m):
    act = new_action(arm, "walk")
    P = arm.pose
    for f in range(0, WALK_FRAMES + 1, 2):
        t = 2 * math.pi * f / WALK_FRAMES
        for k, ph in (("leg_l", 0.0), ("leg_r", math.pi)):
            c = m[k]
            swing = math.sin(t + ph)
            # +X rotation moves a hanging bone toward +Y (backward): forward swing is negative
            key_rot(P, c[0], f + 1, local_rot(c[0], SIDE, -WALK_THIGH_DEG * swing))
            if len(c) > 1:
                bend = max(0.0, math.sin(t + ph + math.pi / 2))   # knee bends as the leg comes through
                key_rot(P, c[1], f + 1, local_rot(c[1], SIDE, WALK_KNEE_DEG * bend))
        for k, ph in (("arm_l", math.pi), ("arm_r", 0.0)):       # arms counter-swing the legs, from relaxed
            c = m[k]; up = upper_of(c)
            swing = Quaternion(SIDE, math.radians(-WALK_ARM_DEG * math.sin(t + ph)))
            key_rot(P, up, f + 1, local_q(up, swing @ relax(up, outward(c))))
        key_loc(P, m["root"], f + 1, Vector((0, 0, WALK_BOB * m["height"] * abs(math.cos(t)))))
        if len(m["spine"]) > 1:
            s = m["spine"][1]
            key_rot(P, s, f + 1, local_rot(s, UP, WALK_TWIST_DEG * math.sin(t)))
    finish(arm, act, WALK_FRAMES)


# --- preview sheet ---------------------------------------------------------------------------------------------
def render_sheet(arm, meshes, path):
    sc = bpy.context.scene
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    mid, size = (lo + hi) / 2, max(hi - lo)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    cam.location = mid + Vector((size * 0.9, -size * 1.9, size * 0.25))
    cam.rotation_euler = (mid - cam.location).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam
    sc.render.engine = "BLENDER_WORKBENCH"
    # Bozzetto --material vertex models carry COLOR_0 and no image: Workbench's TEXTURE mode would draw them grey
    textured = any(n.type == "TEX_IMAGE" for o in meshes for s in o.material_slots if s.material and s.material.node_tree
                   for n in s.material.node_tree.nodes)
    has_vcol = any(len(o.data.color_attributes) for o in meshes)
    sc.display.shading.color_type = "VERTEX" if (has_vcol and not textured) else "TEXTURE"
    sc.render.resolution_x = sc.render.resolution_y = 256
    sc.render.film_transparent = False
    sc.world = sc.world or bpy.data.worlds.new("preview")
    sc.world.color = (0.82, 0.82, 0.82)    # Workbench renders the world colour as the background
    tiles = []
    tmp = Path(path).with_suffix("")
    tmp.mkdir(parents=True, exist_ok=True)
    for act in CLIPS:
        arm.animation_data.action = act      # the action's one slot is picked up by identifier
        n = int(act["clip_frames"])
        for i in range(4):
            sc.frame_set(1 + i * n // 4)
            sc.render.filepath = str(tmp / f"{act.name}_{i}.png")
            bpy.ops.render.render(write_still=True)
            tiles.append(sc.render.filepath)
    arm.animation_data.action = None
    # stitch with Blender's own image API (no Pillow inside Blender)
    W = 256
    sheet = bpy.data.images.new("sheet", W * 4, W * 3)
    px = [1.0] * (W * 4 * W * 3 * 4)
    for k, f in enumerate(tiles):
        im = bpy.data.images.load(f)
        src = list(im.pixels)
        col, row = k % 4, 2 - k // 4          # Blender images start bottom-left
        for y in range(W):
            o = ((row * W + y) * W * 4 + col * W) * 4
            px[o:o + W * 4] = src[y * W * 4:(y + 1) * W * 4]
    sheet.pixels = px
    sheet.filepath_raw = str(path)
    sheet.file_format = "PNG"
    sheet.save()
    print(f"[ OK ] preview: {path} (rows idle, wave, walk; 4 frames each)")


def main():
    a = parse()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=a.rigged)
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if len(arms) != 1:
        fail(f"expected one armature, found {len(arms)}")
    arm = arms[0]
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and any(md.type == "ARMATURE" for md in o.modifiers)]
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o not in meshes]:
        print(f"[warn] removing unskinned mesh {o.name} ({len(o.data.vertices)} vertices)")
        bpy.data.objects.remove(o)
    m = map_biped(arm)
    print("[ OK ] biped found: " + ", ".join(f"{k} {len(m[k])} bones" for k in ("spine", "leg_l", "leg_r", "arm_l", "arm_r")))
    if a.debug:
        for k in ("spine", "head", "leg_l", "leg_r", "arm_l", "arm_r"):
            print(f"       {k}: {[b.name for b in m[k]]}")
    bpy.context.scene.render.fps = FPS
    clip_idle(arm, m)
    clip_wave(arm, m)
    clip_walk(arm, m)
    if a.sheet:
        render_sheet(arm, meshes, a.sheet)
    bpy.ops.export_scene.gltf(filepath=a.out, export_format="GLB", export_animations=True,
                              export_animation_mode="ACTIONS", export_yup=True)
    print(f"[ OK ] wrote {a.out}: clips idle, wave, walk")


if __name__ == "__main__":
    main()
