# ---------------------------------------------------------------------------
# test_character_golden.py
# Purpose : Check: imports the golden rigged character (data/golden/character/character.glb) with
#           kit_character.import_character into /Temp (never saved) and compares it with expected.json: every bone
#           under its Unreal name, the root bone, the height in centimetres, the axes, both clips (length, frames,
#           Loop flag, root motion off), and that `walk` plays: the moving bone turns by at least half its swing,
#           the clip's last pose equals its first (a seamless loop) and the root stays in place. The file is
#           imported twice into the same folder, first at Interchange's default rate, then at expected.json's fps:
#           the frame counts prove the second run reimported the clips (what a game does after the .glb changes).
# Usage   : python tools/dev.py test   (runs it through the pythonscript commandlet; needs PythonScriptPlugin)
#           python tools/dev.py exec Content/Python/kit_character/test_character_golden.py   (the same check alone)
# Notes   : Numbers come from expected.json; the constants below are what UE 5.8 does to any glTF (axes, units),
#           measured 2026-11-11. Logs CHARACTER_BONE / CHARACTER_SWING / CHARACTER_OK, or CHARACTER_DIFF lines.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import json
import os
import uuid

import unreal

from kit_character import character_spec as spec
from kit_character.character import import_character

GOLDEN = "data/golden/character"
DEST = "/Temp/KitCharacterTest"      # under /Temp: never saved; a run id keeps runs apart
CM_PER_M = 100.0                     # glTF metres arrive as Unreal centimetres
HEIGHT_TOL_CM = 1.0
FRONT_AXIS = "+Y"                    # glTF front (+Z) as imported: the way the UE Mannequin's mesh faces
LEFT_AXIS = "+X"                     # glTF +X stays +X
MIN_SWING_FRACTION = 0.5             # walk must turn the moving bone by at least this part of expected.json's swing
MAX_SWING_FRACTION = 1.1
LOOP_SEAM_DEG = 0.5                  # last pose vs first pose of a looping clip
IN_PLACE_CM = 1.0                    # how far the root may drift sideways over a clip with no root motion
TIME_TOL_S = 1e-3


def rot(t):
    q = t.rotation
    return (q.x, q.y, q.z, q.w)


def axis_name(v):
    """The dominant horizontal axis of a vector as '+X', '-Y', ..."""
    x, y = v
    return ("+" if (x if abs(x) >= abs(y) else y) >= 0 else "-") + ("X" if abs(x) >= abs(y) else "Y")


def world(pose, bone):
    return unreal.AnimPoseExtensions.get_bone_pose(pose, bone, unreal.AnimPoseSpaces.WORLD).translation


def ue(ch, name):
    """The Skeleton's name for a glTF bone, or the importer's mapping when the Skeleton has none (a diff says so)."""
    try:
        return ch.bone(name)
    except KeyError:
        return spec.ue_bone_name(name)


def check_bones(ch, exp, diffs):
    for name in exp["bones"]:
        try:
            ch.bone(name)
        except KeyError:
            diffs.append(f"bone {name}: not on the Skeleton (as {spec.ue_bone_name(name)!r} either)")
    if len(ch.bones) != len(exp["bones"]):
        diffs.append(f"{len(ch.bones)} bones on the Skeleton, expected.json lists {len(exp['bones'])}")
    root = ue(ch, exp["root_bone"])
    parent = ch.mesh.get_bone_parent(root)
    if not ch.bones or ch.bones[0] != root or str(parent or "None") != "None":
        diffs.append(f"root bone is {ch.bones[:1]} (parent {parent}), expected {root} with no parent")
    for name in (exp["root_bone"], exp["moving_bone"]):
        unreal.log(f"CHARACTER_BONE {name} -> {ue(ch, name)}")


def check_space(ch, exp, diffs):
    b = ch.mesh.get_bounds()
    height = 2 * b.box_extent.z
    if abs(height - exp["height_m"] * CM_PER_M) > HEIGHT_TOL_CM:
        diffs.append(f"height {height:.2f} cm, expected {exp['height_m'] * CM_PER_M:.2f} (Z up, centimetres)")
    if abs(b.origin.z - b.box_extent.z) > HEIGHT_TOL_CM:
        diffs.append(f"feet at z={b.origin.z - b.box_extent.z:.2f} cm, expected on the ground at 0")
    ref = unreal.AnimPoseExtensions.get_reference_pose(ch.skeleton)
    # Front: from each foot bone to its toe bone; left: from the Right* bones to the Left* bones (Mixamo names)
    fronts, lefts = [], []
    for name in exp["bones"]:
        if "ToeBase" in name:
            toe = ue(ch, name)
            foot = str(ch.mesh.get_bone_parent(toe))
            d = world(ref, toe) - world(ref, foot)
            fronts.append((d.x, d.y))
        if "Left" in name and name.replace("Left", "Right") in exp["bones"]:
            d = world(ref, ue(ch, name)) - world(ref, ue(ch, name.replace("Left", "Right")))
            lefts.append((d.x, d.y))
    front = axis_name([sum(v[i] for v in fronts) for i in (0, 1)]) if fronts else "?"
    left = axis_name([sum(v[i] for v in lefts) for i in (0, 1)]) if lefts else "?"
    unreal.log(f"CHARACTER_AXES up=+Z front={front} left={left} height_cm={height:.2f}")
    if front != FRONT_AXIS or left != LEFT_AXIS:
        diffs.append(f"axes front={front} left={left}, expected front={FRONT_AXIS} left={LEFT_AXIS}")


def check_clips(ch, exp, diffs):
    lib = unreal.AnimationLibrary
    for clip, want in exp["clips"].items():
        seq = ch.sequences.get(clip)
        if seq is None:
            diffs.append(f"clip {clip}: no AnimSequence (made: {', '.join(ch.sequences) or 'none'})")
            continue
        if abs(seq.get_play_length() - want["seconds"]) > TIME_TOL_S:
            diffs.append(f"clip {clip}: {seq.get_play_length():.4f} s, expected {want['seconds']}")
        if lib.get_num_frames(seq) != want["frames"]:
            diffs.append(f"clip {clip}: {lib.get_num_frames(seq)} frames, expected {want['frames']} at {exp['fps']} fps")
        if seq.get_editor_property("loop") != want["loop"]:
            diffs.append(f"clip {clip}: Loop flag {seq.get_editor_property('loop')}, expected {want['loop']}")
        if lib.is_root_motion_enabled(seq) or lib.is_root_motion_lock_forced(seq):
            diffs.append(f"clip {clip}: root motion or Force Root Lock is on")


def check_walk(ch, exp, diffs):
    lib = unreal.AnimationLibrary
    seq = ch.sequences.get("walk")
    if seq is None:
        return
    bone, root = ue(ch, exp["moving_bone"]), ch.bones[0]
    n = lib.get_num_frames(seq)
    length = seq.get_play_length()
    times = [length * f / n for f in range(n + 1)]
    rots = [rot(lib.get_bone_pose_for_time(seq, bone, t, False)) for t in times]
    swing = max(spec.quat_angle_deg(a, b) for a in rots for b in rots)
    want = exp["moving_bone_swing_deg"]
    unreal.log(f"CHARACTER_SWING {bone} turns {swing:.2f} degrees over walk (expected.json: {want})")
    if not MIN_SWING_FRACTION * want <= swing <= MAX_SWING_FRACTION * want:
        diffs.append(f"walk: {bone} turns {swing:.2f} degrees, expected {MIN_SWING_FRACTION * want:.1f} to "
                     f"{MAX_SWING_FRACTION * want:.1f}")
    seam = spec.quat_angle_deg(rots[0], rots[-1])
    if seam > LOOP_SEAM_DEG:
        diffs.append(f"walk: last pose of {bone} is {seam:.2f} degrees from the first (not a seamless loop)")
    roots = [lib.get_bone_pose_for_time(seq, root, t, False).translation for t in times]
    drift = max(((p.x - roots[0].x) ** 2 + (p.y - roots[0].y) ** 2) ** 0.5 for p in roots)
    if drift > IN_PLACE_CM:
        diffs.append(f"walk: root {root} drifts {drift:.2f} cm sideways (expected in place)")


def main():
    root = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
    gold = os.path.join(root, GOLDEN)
    with open(os.path.join(gold, "expected.json"), encoding="utf-8") as f:
        exp = json.load(f)
    dest = f"{DEST}/{uuid.uuid4().hex[:8]}"
    glb = os.path.join(gold, exp["file"])
    first = import_character(glb, dest)          # Interchange's own rate (glTF stores none)
    unreal.log("CHARACTER_FIRST_IMPORT " + ", ".join(
        f"{c}={unreal.AnimationLibrary.get_num_frames(s)} frames" for c, s in sorted(first.sequences.items())))
    ch = import_character(glb, dest, sample_rate=exp["fps"])   # the same folder again: the clips are reimported
    diffs = []
    if ch.mesh != first.mesh or ch.skeleton != first.skeleton:
        diffs.append("the second import made a new SkeletalMesh or Skeleton instead of updating the first")
    for check in (check_bones, check_space, check_clips, check_walk):
        check(ch, exp, diffs)
    for line in diffs:
        unreal.log_error(f"CHARACTER_DIFF {line}")
    if diffs:
        raise AssertionError(f"the golden character differs from expected.json in {len(diffs)} place(s): see CHARACTER_DIFF")
    unreal.log(f"CHARACTER_OK {ch.mesh.get_name()}: {len(ch.bones)} bones, clips "
               f"{', '.join(sorted(ch.sequences))}, imported into {dest}")


main()
