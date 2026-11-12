#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# rig_finish.py
# Purpose : Finish an auto-rigged character in Blender and prove the rig works: drop meshes nothing skins, put the
#           model back at its real size, check the skin weights (the failures that pass with exit 0 elsewhere), give
#           the bones Mixamo names so engines and animation packs recognise them, optionally key three looping clips
#           (idle, wave, walk), and write one .glb plus a JSON report.
# Usage   : Inside Blender (any OS):
#             blender -b --python-exit-code 1 -P tools/bozzetto/rig_finish.py -- <rigged.glb> --out <out.glb> [options]
#           With the bpy module:  python tools/bozzetto/rig_finish.py <rigged.glb> --out <out.glb> [options]
#           Options: --scale 1.8 (multiply the size: Tripo returns 1.0 m tall), --names mixamo|keep,
#                    --animate idle,wave,walk|none, --report r.json, --sheet clips.png, --check-only
# Needs   : Blender 4.2+ or the bpy module
# Exit    : 0 written (or --check-only passed), 1 the rig failed a check (or is not a biped when names or clips need
#           one), 2 usage or environment
# Notes   : bozzetto.py rig make runs this after UniRig or Tripo; it also runs on its own.
#           The weight checks, on every skinned mesh: vertices with no weight; NaN weights; weights that do not sum to
#           1; vertices on glTF's placeholder bone (`neutral_bone`, what an importer uses for a vertex with no real
#           joint: UniRig's NaN skin weights became exactly that, a rig that deforms nothing); one bone holding most
#           vertices; too few bones holding any. Limits are the constants below.
#           Biped mapping, without names (UniRig's bones are bone_0 ... bone_N): the spine is the path from the root
#           to the highest bone tip; limbs hang off it; the two reaching the floor are legs, the two reaching
#           farthest out sideways are arms; left is +X (the character faces -Y in Blender, glTF's +Z front). A third
#           limb on the floor stops it: quadrupeds need their own gaits.
#           Clips are keyed in the character's frame (side X, front -Y, up Z) and converted into each bone's frame,
#           so arbitrary bone rolls never flip a swing. Arms drop from the A-pose to a relaxed angle measured from
#           their own rest pose. Game-jam quality, not mocap. Each clip is its own action, exported with
#           export_animation_mode ACTIONS (no NLA strips: Blender 5.2's slot-less strips baked to the rest pose).
#           A model that already has animations (Tripo's) keeps them; --animate adds clips only to one without.
#           Re-centring: Tripo's retarget with animate_in_place returned walk and run clips whose mixamorig:Hips
#           carried a constant sideways location in every key (1.4 and 2.8 m on a 1.0 m model, idle about 0), so the
#           character stood metres from its origin in those clips: preview rows looked tiny, render_sprites shrank
#           every sheet to hold it, and an engine showed it jump away from its collider on a clip change. For every
#           clip the root-most bone with location keys (the hips) is measured: its horizontal displacement from the
#           rest pose, in the character's frame (up Z, front -Y), averaged over its keys. A mean over RECENTRE_MIN of
#           the rig's height is subtracted from every key (converted into the bone's own axes, which differ per
#           rig), so the per-key wobble and every vertical bob stay as they were. A clip whose hips end more than
#           TRAVEL_MIN of the height from where they started travels (root motion, not in place): it is left as it
#           is and named, since moving its path would move where the motion starts. The kit asks Tripo for in-place
#           clips and the clips keyed here are in place by construction (only a vertical bob), so a travelling clip
#           is a surprise worth a look. A root whose parent is animated too is left alone (its offset is not one
#           constant in the bone's own frame); a parent whose keys never change (every bone sampled) does not count,
#           and a bone whose location keys all sit at 0 is not "the hips": a glTF round trip keys every bone, so the
#           root-most bone with keys that leave 0 is measured (a ground root above the hips used to hide them).
#           Clips at another frame rate (#292): Tripo keys at 30 fps; imported into Blender's 24 fps scene the keys sit
#           every 0.8 frames and the glTF exporter, sampling whole frames, writes the last frame 0.8 frames short of
#           the key that closed the loop (walk came back with a visible seam, idle lost its loop). The scene is set
#           to the clips' own rate first (tools/blender/bpy_common.py), so every key is a whole frame. Blender 4.2's
#           importer names actions "<clip>_<armature>": they take their clip's name back, so the export keeps "walk".
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): Blender 4.2 clip names, clips at 30 fps, the bpy
#           module's exit crash (#292); the hips are the root-most bone whose location keys move, and their parent
#           counts as animated only when its keys change
# ---------------------------------------------------------------------------
#
# Pseudocode
#   import -> clips take their names from the NLA tracks, the tracks go, the scene takes the clips' frame rate
#   -> one armature, else exit 1 -> remove meshes without an Armature modifier -> --scale on the top objects
#   weights per skinned mesh (placeholder bone counts as unweighted) -> any limit broken: report, exit 1
#   names or clips wanted -> map the biped (spine, legs, arms) or exit 1 -> rename to mixamorig:* -> key the clips
#   -> per clip: hips' mean horizontal offset from rest; travels: leave; over the tolerance: subtract it from the keys
#   -> export .glb (clips as glTF animations) -> report JSON -> --sheet: 4 frames per clip
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "blender"))
import bpy_common as bc  # noqa: E402  (clip names, clip frame rate, the bpy module's exit: #292)

# --- tunables -------------------------------------------------------------------------------------------------
MAX_UNWEIGHTED = 0.005      # share of vertices allowed without a real bone
MAX_ONE_BONE = 0.60         # share of vertices one bone may dominate (a rig with everything on one bone is broken)
MIN_BONES_USED = 4          # bones that must dominate at least one vertex
SUM_TOLERANCE = 0.02        # weights of a vertex must sum to 1 within this
DEFORM_DEG = 15.0           # the deformation check bends every bone by this much
MIN_DEFORM = 0.02           # ... and the mesh must then move at least this share of the model's height
PLACEHOLDER = "neutral_bone"
FPS = 24
IDLE_FRAMES, WAVE_FRAMES, WALK_FRAMES = 48, 48, 24
IDLE_BREATH_DEG, IDLE_NOD_DEG, IDLE_ARM_DEG = 2.5, 3.0, 4.0
WAVE_RAISE_DEG, WAVE_SWING_DEG = 105.0, 28.0
RELAX_BELOW_DEG = 70.0      # idle and walk: arms hang this far under horizontal instead of the A-pose
WALK_THIGH_DEG, WALK_KNEE_DEG, WALK_ARM_DEG = 24.0, 38.0, 18.0
WALK_BOB, WALK_TWIST_DEG = 0.025, 4.0
SIDE, FRONT, UP = Vector((1, 0, 0)), Vector((0, -1, 0)), Vector((0, 0, 1))
MIXAMO = "mixamorig:"
MIXAMO_CORE = ("Hips", "Spine", "Head", "LeftUpLeg", "RightUpLeg", "LeftArm", "RightArm", "LeftHand", "RightHand")
CLIPS_KNOWN = ("idle", "wave", "walk")
RECENTRE_MIN = 0.01         # share of the rig's height: hips standing closer than this to their rest spot stay as is
TRAVEL_MIN = 0.10           # share of the height: hips ending this much farther from where they started travel


class RigFail(Exception):
    pass


def parse():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser(prog="rig_finish.py", description="Finish and check an auto-rigged character.")
    ap.add_argument("rigged", help="rigged .glb (UniRig or Tripo output)")
    ap.add_argument("--out", help="the finished .glb (required unless --check-only)")
    ap.add_argument("--scale", type=float, default=1.0, help="multiply the model's size (Tripo returns 1.0 m tall)")
    ap.add_argument("--names", choices=("mixamo", "keep"), default="mixamo", help="bone names (default mixamo)")
    ap.add_argument("--animate", default="none", help="clips to key: idle,wave,walk or none (default none)")
    ap.add_argument("--report", help="write the JSON report here")
    ap.add_argument("--sheet", help="render 4 frames of each clip into this PNG")
    ap.add_argument("--check-only", action="store_true", help="only the weight checks, nothing written but --report")
    a = ap.parse_args(argv)
    clips = [] if a.animate.strip().lower() in ("", "none") else [c.strip() for c in a.animate.split(",")]
    bad = [c for c in clips if c not in CLIPS_KNOWN]
    if bad:
        ap.error(f"unknown clip {bad[0]!r}: choose from {', '.join(CLIPS_KNOWN)}")
    if not a.out and not a.check_only:
        ap.error("--out is required (or --check-only)")
    a.clips = clips
    return a


# --- weights -------------------------------------------------------------------------------------------------
def check_weights(arm, meshes):
    bones = {b.name for b in arm.data.bones if b.name != PLACEHOLDER}
    total = unweighted = on_placeholder = nan = badsum = 0
    dominant = {}
    for m in meshes:
        names = {g.index: g.name for g in m.vertex_groups}
        for v in m.data.vertices:
            total += 1
            raw = [(names.get(g.group), g.weight) for g in v.groups]
            # read every raw weight first: `NaN > 0` is false, so filtering on > 0 used to drop NaN weights before
            # this check could see them (#208); negative and infinite weights are broken too
            if any(not math.isfinite(w) or w < 0 for _, w in raw):
                nan += 1
            gs = [(n, w) for n, w in raw if math.isfinite(w) and w > 0]
            real = [(n, w) for n, w in gs if n in bones]
            if any(n == PLACEHOLDER for n, _ in gs) and not real:
                on_placeholder += 1
            if not real:
                unweighted += 1
                continue
            if abs(sum(w for _, w in real) - 1.0) > SUM_TOLERANCE:
                badsum += 1
            top = max(real, key=lambda t: t[1])[0]
            dominant[top] = dominant.get(top, 0) + 1
    top_bone, top_count = max(dominant.items(), key=lambda t: t[1]) if dominant else (None, 0)
    rep = {"vertices": total, "unweighted": unweighted, "on_placeholder_bone": on_placeholder, "nan": nan,
           "sum_not_1": badsum, "bones": len(bones), "bones_used": len(dominant),
           "top_bone": top_bone, "top_bone_share": round(top_count / total, 3) if total else 0}
    fails = []
    if total == 0:
        fails.append("no skinned vertices")
    else:
        if on_placeholder:
            fails.append(f"{on_placeholder} vertices sit only on glTF's placeholder bone ({PLACEHOLDER}): the skin "
                         "weights were empty or NaN when the file was written")
        if unweighted / total > MAX_UNWEIGHTED:
            fails.append(f"{unweighted} of {total} vertices have no weight")
        if nan:
            fails.append(f"{nan} vertices have NaN, infinite or negative weights")
        if top_count / total > MAX_ONE_BONE:
            fails.append(f"bone {top_bone} holds {100 * top_count / total:.0f}% of the vertices")
        if len(dominant) < MIN_BONES_USED:
            fails.append(f"only {len(dominant)} bones hold any vertex")
    if badsum and total and badsum / total > MAX_UNWEIGHTED:
        fails.append(f"{badsum} vertices have weights that do not sum to 1")
    rep["failures"] = fails
    return rep


def deform_check(arm, meshes):
    """Bend every bone and measure how far the skinned mesh moves, as a share of its height; then restore the pose.
    The weight checks are static: this is the proof that the rig deforms (#223), the failure the spike first met."""
    def coords():
        dg = bpy.context.evaluated_depsgraph_get()
        pts = []
        for m in meshes:
            ev = m.evaluated_get(dg)
            me = ev.to_mesh()
            pts += [m.matrix_world @ v.co for v in me.vertices]
            ev.to_mesh_clear()
        return pts
    rest = coords()
    if not rest:
        return 0.0
    height = (max(p.z for p in rest) - min(p.z for p in rest)) or 1.0
    saved = {pb.name: (pb.rotation_mode, pb.rotation_quaternion.copy(), pb.rotation_euler.copy())
             for pb in arm.pose.bones}
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (math.radians(DEFORM_DEG), 0.0, math.radians(DEFORM_DEG / 2))
    bpy.context.view_layer.update()
    bent = coords()
    for pb in arm.pose.bones:
        mode, q, e = saved[pb.name]
        pb.rotation_mode = mode
        pb.rotation_quaternion, pb.rotation_euler = q, e
    bpy.context.view_layer.update()
    return max((a - b).length for a, b in zip(rest, bent)) / height


# --- biped mapping -------------------------------------------------------------------------------------------
def reach(bone):
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
    bones = [b for b in arm.data.bones if b.name != PLACEHOLDER]
    roots = [b for b in bones if b.parent is None]
    if len(roots) != 1:
        raise RigFail(f"expected one root bone, found {len(roots)}")
    root = roots[0]
    lo = min(min(b.head_local.z, b.tail_local.z) for b in bones)
    hi = max(max(b.head_local.z, b.tail_local.z) for b in bones)
    height = hi - lo
    spine, b = [], max(bones, key=lambda x: x.tail_local.z)
    while b is not None:
        spine.insert(0, b)
        b = b.parent
    on_spine = set(spine)
    limbs = [c for s in spine for c in s.children if c not in on_spine]
    if len(limbs) < 4:
        raise RigFail(f"not a biped: {len(limbs)} limbs off the spine (2 legs and 2 arms needed)")

    def low(l): return min(min(x.head_local.z, x.tail_local.z) for x in subtree(l))
    def side(l): return max((x.tail_local.x for x in subtree(l)), key=abs)

    by_low = sorted(limbs, key=low)
    legs = by_low[:2]
    if any(low(l) - lo > 0.25 * height for l in legs):
        raise RigFail("not a standing biped: no two limbs reach the floor")
    if len(by_low) > 2 and low(by_low[2]) - lo < 0.25 * height:
        raise RigFail("more than two limbs reach the floor: a quadruped or a creature, not a biped")
    arms = sorted([l for l in limbs if l not in legs], key=lambda l: -abs(side(l)))[:2]
    # facing (#216): arms must spread along X (the character faces -Y in Blender, glTF's +Z front)
    tips = [x.tail_local for a in arms for x in subtree(a)]
    span_x = max(abs(p.x) for p in tips)
    span_y = max(abs(p.y) for p in tips)
    if span_y > span_x:
        raise RigFail("the arms spread along Y, not X: the model faces sideways. Turn it to face front (glTF +Z, "
                      "Blender -Y), e.g. `bozzetto.py make ... --turn 90`, then rig again")
    for pair, what in ((arms, "arm"), (legs, "leg")):
        if (side(pair[0]) > 0) == (side(pair[1]) > 0):
            raise RigFail(f"both {what} candidates are on the same side")
    # toes point forward: a foot pointing +Y means the model faces backward, and left and right would swap (#216)
    toe_y = sum((main_chain(l)[-1].tail_local - main_chain(l)[-1].head_local).y for l in legs)
    if toe_y > 0.02 * height:
        raise RigFail("the feet point +Y: the model faces backward, so left and right would swap. Turn it 180 "
                      "degrees (`bozzetto.py make ... --turn 180`), then rig again")
    # the hips are the spine bone both legs hang from; a ground-level root below it is not renamed (#216)
    hips = legs[0].parent
    if hips is None or legs[1].parent is None or legs[1].parent.name != hips.name:
        raise RigFail("the legs do not hang from one spine bone, so the hips are unclear")
    at = next(i for i, s in enumerate(spine) if s.name == hips.name)
    m = {"leg_r": main_chain(min(legs, key=side)), "leg_l": main_chain(max(legs, key=side)),
         "arm_r": main_chain(min(arms, key=side)), "arm_l": main_chain(max(arms, key=side))}
    m["root"], m["spine"], m["head"] = hips, spine[at:-1], [spine[-1]]
    m["height"] = height
    return m


def rename_mixamo(arm, m):
    """mixamorig:* names by role (Unity's Humanoid and Mixamo-style packs map these). Extra bones keep their names."""
    names = {}

    def put(bone, name):   # first role wins: a bone is never renamed twice
        if bone is not None and bone.name not in names:
            names[bone.name] = MIXAMO + name
    put(m["root"], "Hips")
    # compare by name: bpy hands out a new Python object on every access, so `is` never matches
    mid = [b for b in m["spine"] if b.name != m["root"].name]
    if mid:
        put(mid[-1], "Neck") if len(mid) >= 2 else None
        for b, n in zip(mid[:-1] if len(mid) >= 2 else mid, ("Spine", "Spine1", "Spine2")):
            put(b, n)
    put(m["head"][0], "Head")
    for side, s in (("leg_l", "Left"), ("leg_r", "Right")):
        for b, n in zip(m[side], ("UpLeg", "Leg", "Foot", "ToeBase", "Toe_End")):
            put(b, s + n)
    for side, s in (("arm_l", "Left"), ("arm_r", "Right")):
        c = m[side]
        if len(c) < 3:   # Mixamo (and Unity's Humanoid) need upper arm, forearm and hand: do not guess (#216)
            raise RigFail(f"the {s.lower()} arm has {len(c)} bone(s); Mixamo names need upper arm, forearm and hand. "
                          "Pass --names keep to rig it with its own names")
        parts = ("Shoulder", "Arm", "ForeArm", "Hand") if len(c) >= 4 else ("Arm", "ForeArm", "Hand")
        for b, n in zip(c, parts):
            put(b, s + n)
    for old, new in names.items():      # bone renames carry the vertex groups with them
        arm.data.bones[old].name = new
    return len(names)


# --- clips ---------------------------------------------------------------------------------------------------
def local_rot(bone, axis, deg):
    rest = bone.matrix_local.to_quaternion()
    return rest.inverted() @ Quaternion(axis, math.radians(deg)) @ rest


def local_q(bone, q_arm):
    rest = bone.matrix_local.to_quaternion()
    return rest.inverted() @ q_arm @ rest


def upper_of(chain):
    return chain[1] if len(chain) >= 4 else chain[0]


def outward(chain):
    return 1 if chain[-1].tail_local.x > 0 else -1


def relax(bone, sgn):
    d = (bone.tail_local - bone.head_local).normalized()
    below = -math.degrees(math.asin(max(-1.0, min(1.0, d.z))))
    return Quaternion(FRONT, math.radians(-sgn * max(0.0, RELAX_BELOW_DEG - below)))   # -sgn lowers, +sgn raises


def key_rot(pose, bone, frame, q):
    pb = pose.bones[bone.name]
    pb.rotation_mode = "QUATERNION"
    pb.rotation_quaternion = q
    pb.keyframe_insert("rotation_quaternion", frame=frame)


def key_loc(pose, bone, frame, offset):
    pb = pose.bones[bone.name]
    pb.location = bone.matrix_local.to_quaternion().inverted() @ offset
    pb.keyframe_insert("location", frame=frame)


def new_action(arm, name):
    act = bpy.data.actions.new(name)
    arm.animation_data_create()
    arm.animation_data.action = act
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = Quaternion()
        pb.location = Vector()
    return act


def finish_action(arm, act, frames, made):
    act.use_fake_user = True
    act["clip_frames"] = frames
    made.append(act)
    arm.animation_data.action = None


def clip_idle(arm, m, made):
    act, P = new_action(arm, "idle"), arm.pose
    for f in range(0, IDLE_FRAMES + 1, 6):
        t = 2 * math.pi * f / IDLE_FRAMES
        for s in m["spine"][1:]:
            key_rot(P, s, f + 1, local_rot(s, SIDE, IDLE_BREATH_DEG * math.sin(t) / max(1, len(m["spine"]) - 1)))
        key_rot(P, m["head"][0], f + 1, local_rot(m["head"][0], SIDE, IDLE_NOD_DEG * math.sin(t + 0.6)))
        for k in ("arm_l", "arm_r"):
            c = m[k]; up = upper_of(c); sgn = outward(c)
            sway = Quaternion(FRONT, math.radians(sgn * IDLE_ARM_DEG * math.sin(t + 1.2)))
            key_rot(P, up, f + 1, local_q(up, sway @ relax(up, sgn)))
    finish_action(arm, act, IDLE_FRAMES, made)


def clip_wave(arm, m, made):
    act, P = new_action(arm, "wave"), arm.pose
    c, other = m["arm_r"], m["arm_l"]
    upper = upper_of(c)
    fore = c[c.index(upper) + 1] if c.index(upper) + 1 < len(c) else None
    sgn = outward(c)
    for f in range(0, WAVE_FRAMES + 1, 3):
        u = f / WAVE_FRAMES
        key_rot(P, upper, f + 1, local_rot(upper, FRONT, sgn * WAVE_RAISE_DEG))   # held up all loop: no seam pop
        if fore is not None:
            key_rot(P, fore, f + 1, local_rot(fore, FRONT, sgn * WAVE_SWING_DEG * math.sin(2 * math.pi * 3 * u)))
        ou = upper_of(other)
        key_rot(P, ou, f + 1, local_q(ou, relax(ou, outward(other))))
        key_rot(P, m["head"][0], f + 1, local_rot(m["head"][0], FRONT, sgn * 5))
    finish_action(arm, act, WAVE_FRAMES, made)


def clip_walk(arm, m, made):
    act, P = new_action(arm, "walk"), arm.pose
    for f in range(0, WALK_FRAMES + 1, 2):
        t = 2 * math.pi * f / WALK_FRAMES
        for k, ph in (("leg_l", 0.0), ("leg_r", math.pi)):
            c = m[k]
            key_rot(P, c[0], f + 1, local_rot(c[0], SIDE, -WALK_THIGH_DEG * math.sin(t + ph)))   # + about X: backward
            if len(c) > 1:
                key_rot(P, c[1], f + 1, local_rot(c[1], SIDE, WALK_KNEE_DEG * max(0.0, math.sin(t + ph + math.pi / 2))))
        for k, ph in (("arm_l", math.pi), ("arm_r", 0.0)):
            c = m[k]; up = upper_of(c)
            swing = Quaternion(SIDE, math.radians(-WALK_ARM_DEG * math.sin(t + ph)))
            key_rot(P, up, f + 1, local_q(up, swing @ relax(up, outward(c))))
        key_loc(P, m["root"], f + 1, Vector((0, 0, WALK_BOB * m["height"] * abs(math.cos(t)))))
        if len(m["spine"]) > 1:
            s = m["spine"][1]
            key_rot(P, s, f + 1, local_rot(s, UP, WALK_TWIST_DEG * math.sin(t)))
    finish_action(arm, act, WALK_FRAMES, made)


# --- re-centring (Tripo's in-place clips with an offset root) ---------------------------------------------------
fcurves_of = bc.fcurves_of   # every F-curve of an action, on Blender 4.2 to 5.x


def detach_clips(arm):
    """The imported clips as plain actions: named after their glTF clip (Blender 4.2 names the action
    "<clip>_<armature>", the NLA track keeps the clip's name), kept alive, and off the NLA stack, so a clip assigned
    for a check or a preview plays alone. Returns the actions."""
    bc.adopt_clip_names(bpy)
    clips = list(bpy.data.actions)
    for c in clips:
        c.use_fake_user = True
    if arm.animation_data:
        for tr in list(arm.animation_data.nla_tracks):
            arm.animation_data.nla_tracks.remove(tr)
        arm.animation_data.action = None
    return clips


def constant_curve(fc):
    """True when every key of the F-curve holds one value (a parent sampled by an exporter but never moved)."""
    vals = [k.co[1] for k in fc.keyframe_points]
    return not vals or max(vals) - min(vals) <= 1e-6


def at_rest(fc):
    """True when every key of a location F-curve is 0: the bone never leaves its rest spot. glTF exporters write
    location keys for every bone, so a key is no sign of motion."""
    return all(abs(k.co[1]) <= 1e-6 for k in fc.keyframe_points)


def bone_of(path):
    """'pose.bones["X"].location' -> ('X', 'location'); anything else -> (None, None)."""
    head = 'pose.bones["'
    if not path.startswith(head) or '"].' not in path:
        return None, None
    name, prop = path[len(head):].split('"].', 1)
    return name, prop


def new_location_curve(act, bone, index, frames):
    """A location F-curve for an axis the clip never keyed (value 0, the pose default), keyed at the same frames."""
    path = f'pose.bones["{bone}"].location'
    if hasattr(act, "fcurves"):
        fc = act.fcurves.new(path, index=index, action_group=bone)
    else:   # Blender 5: the channel bag that already holds this bone's curves
        bag = next(b for layer in act.layers for s in layer.strips for b in s.channelbags
                   if any(bone_of(f.data_path)[0] == bone for f in b.fcurves))
        fc = bag.fcurves.new(path, index=index)
    for f in frames:
        fc.keyframe_points.insert(f, 0.0).interpolation = "LINEAR"
    return fc


def depth(bone):
    n = 0
    while bone.parent is not None:
        bone, n = bone.parent, n + 1
    return n


def rig_height(arm):
    """The rig's height in metres as it stands (bone heads and tails, the armature object's rotation and scale)."""
    w = arm.matrix_world.to_3x3()
    zs = [(w @ p).z for b in arm.data.bones if b.name != PLACEHOLDER for p in (b.head_local, b.tail_local)]
    return (max(zs) - min(zs)) if zs else 0.0


def recentre_clip(arm, act, height):
    """Remove the mean horizontal offset of the clip's root-most location-keyed bone (the hips) from its keys.
    Returns the report entry (offsets in the file's metres, before --scale); the keys change only for 'recentred'.
    A root bone's head moves by matrix_local @ location in armature space (rest @ basis), so a constant offset in
    the character's frame is one constant vector in the bone's frame: subtracting it keeps every wobble and bob."""
    curves, keyed = {}, set()
    for fc in fcurves_of(act):
        name, prop = bone_of(fc.data_path)
        if name is None or name not in arm.data.bones:
            continue
        if not constant_curve(fc):      # a bone with keys that never change is not animated (Tripo keys every bone)
            keyed.add(name)
        if prop == "location":
            curves.setdefault(name, {})[fc.array_index] = fc
    if not curves:
        return {"action": "no location keys"}
    # a bone whose location keys all sit at 0 never moves: a glTF round trip gives every bone such keys, and a
    # ground-level root above the hips used to be picked here and found "in place" while the hips stood 1.4 m off
    moving = {n: axes for n, axes in curves.items() if any(not at_rest(fc) for fc in axes.values())}
    if not moving:
        return {"action": "in place", "offset_m": 0.0, "travel_m": 0.0}
    # root-most moving bone; on a tie the one called Hips (Mixamo's root), then by name
    root = min((arm.data.bones[n] for n in moving), key=lambda b: (depth(b), "Hips" not in b.name, b.name))
    entry = {"bone": root.name}
    p = root.parent
    while p is not None:
        if p.name in keyed:
            entry.update(action="left (parent animated)", parent=p.name)
            return entry
        p = p.parent
    axes = curves[root.name]
    frames = sorted({k.co[0] for fc in axes.values() for k in fc.keyframe_points})
    to_world = arm.matrix_world.to_3x3() @ root.matrix_local.to_3x3()     # bone-local location -> world metres
    pts = [to_world @ Vector([axes[i].evaluate(f) if i in axes else 0.0 for i in range(3)]) for f in frames]
    mean = sum(pts, Vector()) / len(pts)
    offset = Vector((mean.x, mean.y, 0.0))                                 # horizontal only: the bob stays
    travel = Vector((pts[-1].x - pts[0].x, pts[-1].y - pts[0].y, 0.0)).length
    entry.update(offset_m=offset.length, travel_m=travel)
    if travel > TRAVEL_MIN * height:
        entry["action"] = "left (travels: root motion)"
        return entry
    if offset.length <= RECENTRE_MIN * height:
        entry["action"] = "in place"
        return entry
    local = to_world.inverted() @ offset
    for i in range(3):
        if abs(local[i]) < 1e-9:
            continue
        fc = axes.get(i) or new_location_curve(act, root.name, i, frames)
        for k in fc.keyframe_points:
            k.co[1] -= local[i]
            k.handle_left[1] -= local[i]
            k.handle_right[1] -= local[i]
        fc.update()
    entry["action"] = "recentred"
    return entry


def recentre_clips(arm, clips, scale):
    """Run recentre_clip on every clip; print and return the report (metres after --scale)."""
    height = rig_height(arm)
    out = {}
    for act in clips:
        e = recentre_clip(arm, act, height) if height > 0 else {"action": "no height"}
        for k in ("offset_m", "travel_m"):
            if k in e:
                e[k] = round(e[k] * scale, 3)
        out[act.name] = e
        if e["action"] == "recentred":
            print(f"[ OK ] {act.name}: re-centred {e['offset_m']:.2f} m ({e['bone']} stood that far sideways from its "
                  "rest spot in every key; the wobble and bob are kept)")
        elif e["action"].startswith("left (travels"):
            print(f"[WARN] {act.name}: {e['bone']} travels {e['travel_m']:.2f} m from the first key to the last (root "
                  "motion, not in place): left as it is")
        elif e["action"].startswith("left (parent"):
            print(f"[WARN] {act.name}: {e['bone']} and its parent {e['parent']} are both animated: not re-centred")
    return out


# --- preview -------------------------------------------------------------------------------------------------
def render_sheet(arm, meshes, clips, path):
    sc = bpy.context.scene
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    mid, size = (lo + hi) / 2, max(hi - lo)
    cam = bpy.data.objects.new("rig_cam", bpy.data.cameras.new("rig_cam"))
    sc.collection.objects.link(cam)
    cam.location = mid + Vector((size * 0.9, -size * 1.9, size * 0.25))
    cam.rotation_euler = (mid - cam.location).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam
    sc.render.engine = "BLENDER_WORKBENCH"
    textured = any(n.type == "TEX_IMAGE" for o in meshes for s in o.material_slots
                   if s.material and s.material.node_tree for n in s.material.node_tree.nodes)
    sc.display.shading.color_type = "VERTEX" if (not textured and any(len(o.data.color_attributes) for o in meshes)) \
        else "TEXTURE"
    sc.world = sc.world or bpy.data.worlds.new("preview")
    sc.world.color = (0.82, 0.82, 0.82)
    W = 256
    sc.render.resolution_x = sc.render.resolution_y = W
    tmp = Path(path).with_suffix("")
    tmp.mkdir(parents=True, exist_ok=True)
    rows = max(1, len(clips))
    px = [1.0] * (W * 4 * W * rows * 4)
    for r, act in enumerate(clips):
        arm.animation_data.action = act
        f0, f1 = (int(x) for x in act.frame_range)
        for i in range(4):
            sc.frame_set(f0 + i * max(1, f1 - f0) // 4)
            sc.render.filepath = str(tmp / f"{r}_{i}.png")
            bpy.ops.render.render(write_still=True)
            src = list(bpy.data.images.load(sc.render.filepath).pixels)
            row = rows - 1 - r
            for y in range(W):
                o = ((row * W + y) * W * 4 + i * W) * 4
                px[o:o + W * 4] = src[y * W * 4:(y + 1) * W * 4]
    arm.animation_data.action = None
    img = bpy.data.images.new("rig_sheet", W * 4, W * rows)
    img.pixels = px
    img.filepath_raw = str(path)
    img.file_format = "PNG"
    img.save()
    for f in tmp.glob("*.png"):
        f.unlink()
    tmp.rmdir()
    print(f"[ OK ] preview {path} (one row per clip, 4 frames each)")


def main():
    a = parse()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=a.rigged)
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if len(arms) != 1:
        print(f"[FAIL] expected one armature, found {len(arms)}")
        return 1
    arm = arms[0]
    existing = detach_clips(arm)
    bc.conform_clip_fps(bpy, bpy.context.scene, existing)
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and any(md.type == "ARMATURE" for md in o.modifiers)]
    dropped = []
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o not in meshes]:
        dropped.append(f"{o.name} ({len(o.data.vertices)} vertices)")
        bpy.data.objects.remove(o)
    for d in dropped:
        print(f"[ OK ] removed a mesh nothing skins: {d}")
    rep = check_weights(arm, meshes)
    rep["dropped_meshes"] = dropped
    print(f"[{'FAIL' if rep['failures'] else ' OK '}] weights: {rep['vertices']} vertices, {rep['bones']} bones, "
          f"{rep['bones_used']} in use, unweighted {rep['unweighted']}, NaN {rep['nan']}, top bone "
          f"{rep['top_bone_share'] * 100:.0f}%")
    if not rep["failures"]:
        moved = deform_check(arm, meshes)
        rep["deform_max_share"] = round(moved, 3)
        print(f"[{' OK ' if moved >= MIN_DEFORM else 'FAIL'}] deforms: bending every bone {DEFORM_DEG:g} degrees moves "
              f"the mesh up to {moved * 100:.0f}% of its height")
        if moved < MIN_DEFORM:
            rep["failures"].append(f"the rig does not deform the mesh (bending every bone moves it {moved * 100:.1f}% "
                                   f"of its height, under {MIN_DEFORM * 100:.0f}%)")
    for f in rep["failures"]:
        if not f.startswith("the rig does not deform"):
            print(f"[FAIL] {f}")
    rep["clips_in_file"] = [x.name for x in existing]
    rep["fps"] = bpy.context.scene.render.fps
    code = 1 if rep["failures"] else 0
    if code == 0 and not a.check_only:
        made = []
        try:
            # a rig counts as Mixamo-named only with every core role; a partly renamed one is refused (#216)
            have = {b.name for b in arm.data.bones}
            core = {MIXAMO + n for n in MIXAMO_CORE}
            already = core <= have
            if not already and a.names == "mixamo" and any(n.startswith(MIXAMO) for n in have):
                raise RigFail(f"the rig is partly Mixamo-named (missing {', '.join(sorted(core - have))}); fix the "
                              "names or pass --names keep")
            if (a.names == "mixamo" and not already) or (a.clips and not existing):
                m = map_biped(arm)
                rep["biped"] = {k: len(m[k]) for k in ("spine", "leg_l", "leg_r", "arm_l", "arm_r")}
                if a.names == "mixamo" and not already:
                    rep["renamed"] = rename_mixamo(arm, m)
                    print(f"[ OK ] {rep['renamed']} bones renamed to Mixamo names (mixamorig:Hips ...)")
                if a.clips and not existing:
                    bpy.context.scene.render.fps = FPS
                    for c in a.clips:
                        {"idle": clip_idle, "wave": clip_wave, "walk": clip_walk}[c](arm, m, made)
                    print(f"[ OK ] clips keyed: {', '.join(a.clips)}")
            elif already:
                print("[ OK ] bones already have Mixamo names")
            if a.clips and existing:
                print(f"[ OK ] the file has clips already ({', '.join(rep['clips_in_file'])}); --animate adds none")
        except RigFail as e:
            rep["failures"].append(str(e))
            print(f"[FAIL] {e}")
            code = 1
        if code == 0:
            clips = made or existing
            # before the scale: the keys are in the bone's frame either way, the report gives metres after it
            rep["recentred"] = recentre_clips(arm, clips, a.scale)
            if a.scale != 1.0:
                for o in [o for o in bpy.data.objects if o.parent is None]:
                    o.scale = o.scale * a.scale
                print(f"[ OK ] scaled by {a.scale:g}")
            # slide to zero: keys start at frame 1 (1/24 s); an engine loops a clip over 0..length, so without it
            # the first pose was held an extra frame every cycle (#290)
            bpy.ops.export_scene.gltf(filepath=a.out, export_format="GLB", export_yup=True,
                                      export_animations=bool(clips), export_animation_mode="ACTIONS",
                                      export_anim_slide_to_zero=True)
            rep["clips"] = [x.name for x in clips]
            print(f"[ OK ] wrote {a.out}" + (f" with clips {', '.join(rep['clips'])}" if clips else ""))
            if a.sheet and clips:
                render_sheet(arm, meshes, clips, a.sheet)
    if a.report:
        Path(a.report).write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    try:
        code = main()
    except SystemExit as exc:          # argparse: usage errors
        code = exc.code if isinstance(exc.code, int) else 2
    except Exception as exc:  # noqa: BLE001
        print(f"[error] {exc!r}")
        code = 2
    bc.end_process(bpy, code)          # the bpy module crashes on a plain exit after a glTF export (#292)
