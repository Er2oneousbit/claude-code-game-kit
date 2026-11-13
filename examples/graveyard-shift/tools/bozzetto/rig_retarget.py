#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# rig_retarget.py
# Purpose : Animation packs on a Bozzetto character (#205). Renames a pack's skeleton to Mixamo's names (bone_map.py:
#           Quaternius' Universal Animation Library, Mixamo's own FBX in any prefix spelling, or a map of your own)
#           and either writes the pack's own character back, Mixamo-named, or plays chosen clips of the pack on a
#           Mixamo-named rig (a `rig make` result, the golden character) and writes that rig with the new clips.
# Usage   : Inside Blender (any OS):
#             blender -b --python-exit-code 1 -P tools/bozzetto/rig_retarget.py -- <pack.glb|.fbx> --out <out.glb>
#               [--onto <rigged.glb>] [--clips Walk_Loop=walk,Idle_Loop=idle|all] [--map my_map.json] [--replace]
#               [--sheet clips.png] [--report r.json] [--debug]
#           With the bpy module:  python tools/bozzetto/rig_retarget.py <pack.glb> --out <out.glb> ...
#           Usually run by `bozzetto.py rig retarget <name> --from <pack.glb>` (retarget.py), which finds Blender,
#           keeps a backup and notes the clips in the asset log.
#           Without --onto: the pack's character, bones renamed, the chosen clips (all by default) under their new
#           names: check and finish it with rig_finish.py like any rig. With --onto: the clips are transferred onto
#           that rig; its own clips stay (one of the same name is refused unless --replace).
# Needs   : Blender 4.2+ or the bpy module
# Exit    : 0 written, 1 refused (no map fits, the rigs face different ways, a clip name is taken, the transfer
#           missed its own check), 2 usage or environment
# Notes   : The transfer is a retarget, not a copy of curves: packs and Bozzetto rest in different poses (Quaternius'
#           UAL in a T-pose, Bozzetto rigs and the golden character in an A-pose) and their bones point and roll
#           differently. Per output frame and per bone both rigs share (by Mixamo name), in world space:
#             D = source pose rotation x source rest rotation^-1          (how far the pack's bone turned)
#             A = rotation from the target bone's rest direction to the source bone's rest direction
#             target world rotation = D x A x target rest rotation
#           so every shared bone points exactly where the pack's bone points (the self-check measures it: under
#           MAX_DIR_ERROR_DEG or exit 1). The hips also move: the pack's hips offset from their rest spot, scaled by
#           the ratio of the two hips heights. Twist about a bone's own axis is not matched beyond what A carries (a
#           forearm can roll a little differently); fingers transfer only when both rigs have them.
#           Frame rates: each rig's keys are laid on the frame grid Blender had when it was imported; the clips are
#           sampled by time and keyed at the target's clip rate (its own clips' rate, else the pack's), at whole
#           frames: a clip whose length is not a whole number of target frames is stretched by under half a frame
#           so a loop still closes (the report's "stretch"). The pack's clips must face the same way as the target
#           (feet toward -Y in Blender, glTF's +Z front, left at +X) or it refuses rather than mirror a walk.
#           Run it before `rig chain`: the chain keys its sway into the clips the file has when the chain is made.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   --onto: import the target -> its clips detached (names, fake user) -> scene takes their frame rate
#   import the pack (keys on the scene's grid at that moment: its fps) -> its armature, meshes, clips
#   bone_map.rename_plan(pack bones) -> rename bones (two passes, via temporary names) -> clips' paths follow
#   choose clips (--clips), give them their new names
#   no --onto: drop the other clips -> export the pack's character -> sheet -> done
#   --onto: target must be Mixamo-named; both face the same way
#     per clip: N = round(seconds x rate) frames; per frame k: the pack sampled at its time; target pose built
#     parent-first from the formula above (hips also located); keyed as quaternions (sign kept continuous)
#     self-check: evaluate the keyed clip; every shared bone's direction within MAX_DIR_ERROR_DEG of the pack's
#     remove the pack (objects, clips) -> re-centre the new clips' hips (rig_finish) -> export -> sheet -> report
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "blender"))
import bone_map as bm  # noqa: E402  (the maps: standard library, shared with the exam)
import bpy_common as bc  # noqa: E402  (clip names, clip frame rates, the bpy module's exit: #292)
import rig_finish as rf  # noqa: E402  (detached clips, re-centring, the contact sheet)

# --- tunables -------------------------------------------------------------------------------------------------
MAX_DIR_ERROR_DEG = 2.0     # self-check: a shared bone may point at most this far from the pack's bone
CHECK_EVERY = 4             # self-check every this many output frames (and the last)
MIN_BONE_LEN = 1e-4         # metres: bones shorter than this have no direction to check
Y = Vector((0.0, 1.0, 0.0))
DEBUG = False


class Refused(Exception):
    pass


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}")


def parse():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser(
        prog="rig_retarget.py", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Rename an animation pack's skeleton to Mixamo names and keep its character, or play its clips "
                    "on a Mixamo-named rig (Bozzetto's rig make, the golden character).",
        epilog="Built-in maps: " + "; ".join(f"{k}: {v}" for k, v in bm.MAP_NOTES.items())
               + ".\nExamples:\n  rig_retarget.py UAL1_Standard.glb --onto hero_rigged.glb --clips "
                 "Walk_Loop=walk,Idle_Loop=idle --out hero_rigged_new.glb --sheet clips.png\n"
                 "  rig_retarget.py UAL1_Standard.glb --clips Walk_Loop=walk,Idle_Loop=idle --out mannequin.glb")
    ap.add_argument("source", help="the pack's file: .glb/.gltf, or .fbx (Mixamo's downloads)")
    ap.add_argument("--out", required=True, help="the .glb to write")
    ap.add_argument("--onto", help="a Mixamo-named rigged .glb to receive the clips (without it: the pack's own "
                                   "character comes out, renamed)")
    ap.add_argument("--clips", default="", help="clips to take, SOURCE=new_name or SOURCE, comma-separated, or all "
                                                "(default: all without --onto; required with it)")
    ap.add_argument("--map", help="a JSON bone map of your own: {\"their_name\": \"Hips\", ...}")
    ap.add_argument("--replace", action="store_true", help="--onto: replace a clip the rig already has by that name")
    ap.add_argument("--sheet", help="render 4 frames of each written clip into this PNG")
    ap.add_argument("--report", help="write the JSON report here")
    ap.add_argument("--debug", action="store_true", help="print the bone plan and every clip's numbers")
    a = ap.parse_args(argv)
    try:
        a.pairs = bm.parse_clips(a.clips)
    except ValueError as exc:
        ap.error(str(exc))
    if a.onto and a.pairs == "all":
        ap.error("--onto needs --clips (e.g. Walk_Loop=walk,Idle_Loop=idle): a pack can hold dozens of clips")
    for p in [a.source] + ([a.onto] if a.onto else []) + ([a.map] if a.map else []):
        if not Path(p).is_file():
            ap.error(f"{p} not found")
    return a


# --- import ---------------------------------------------------------------------------------------------------
def import_file(path):
    """Import a .glb/.gltf/.fbx; returns (new objects, new actions, the scene's fps the keys were laid at)."""
    objs, acts = set(bpy.data.objects), set(bpy.data.actions)
    suffix = Path(path).suffix.lower()
    if suffix in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))     # may set the scene's fps from the file
    else:
        raise Refused(f"{path}: import .glb, .gltf or .fbx")
    sc = bpy.context.scene
    return ([o for o in bpy.data.objects if o not in objs], [a for a in bpy.data.actions if a not in acts],
            sc.render.fps / sc.render.fps_base)


def one_armature(objs, what):
    arms = [o for o in objs if o.type == "ARMATURE"]
    if len(arms) != 1:
        raise Refused(f"{what}: expected one armature, found {len(arms)}")
    return arms[0]


def skinned(objs, arm):
    return [o for o in objs if o.type == "MESH" and any(m.type == "ARMATURE" and m.object == arm
                                                        for m in o.modifiers)]


def bone_clips(acts):
    """Only actions that move bones (a glTF import also makes actions for morph targets and objects)."""
    return [a for a in acts if any(rf.bone_of(fc.data_path)[0] for fc in bc.fcurves_of(a))]


def detach(arm, acts):
    """Clips off the NLA stack, named after their glTF clip, kept alive (rig_finish.detach_clips for one rig)."""
    bc.adopt_clip_names(bpy)
    for a in acts:
        a.use_fake_user = True
    if arm.animation_data:
        for tr in list(arm.animation_data.nla_tracks):
            arm.animation_data.nla_tracks.remove(tr)
        arm.animation_data.action = None
    else:
        arm.animation_data_create()


# --- names ----------------------------------------------------------------------------------------------------
def rename_bones(arm, acts, map_file):
    """Apply bone_map's plan; returns (map name, plan). Bones go through temporary names first, so a new name never
    meets an old one mid-way (Blender would add .001); every clip's paths follow (Blender renames them itself;
    this also covers a clip it did not)."""
    kind, plan = bm.rename_plan([b.name for b in arm.data.bones], map_file)
    tmp = {}
    for i, old in enumerate(plan):
        tmp[old] = f"__retarget_{i}"
        arm.data.bones[old].name = tmp[old]
    for old, new in plan.items():
        arm.data.bones[tmp[old]].name = new
    paths = {}
    for old, new in plan.items():
        paths[f'pose.bones["{old}"]'] = f'pose.bones["{new}"]'
        paths[f'pose.bones["{tmp[old]}"]'] = f'pose.bones["{new}"]'
    for act in acts:
        for fc in bc.fcurves_of(act):
            for a, b in paths.items():
                if fc.data_path.startswith(a + "."):
                    fc.data_path = b + fc.data_path[len(a):]
                    break
        for grp in getattr(act, "groups", []):
            if grp.name in plan:
                grp.name = plan[grp.name]
    for line in (f"{o} -> {n}" for o, n in plan.items()):
        dbg(line)
    return kind, plan


def choose_clips(acts, pairs):
    """[(action, new name)] for --clips; Refused names a clip the pack does not have."""
    by_name = {}
    for a in acts:
        by_name.setdefault(bm.clip_name(a.name), a)
        by_name.setdefault(a.name, a)
    if pairs == "all":
        return [(a, bm.clip_name(a.name)) for a in acts]
    out = []
    for src, dst in pairs:
        a = by_name.get(src)
        if a is None:
            have = sorted({bm.clip_name(x.name) for x in acts})
            raise Refused(f"the pack has no clip {src!r}; it has: {', '.join(have[:40])}"
                          + (" ..." if len(have) > 40 else ""))
        out.append((a, dst))
    return out


# --- rigs in the world ----------------------------------------------------------------------------------------
def world_rest(arm, bone):
    return arm.matrix_world @ bone.matrix_local


def rot_of(m):
    return m.to_3x3().normalized().to_quaternion()


def direction(m):
    return (m.to_3x3().normalized() @ Y).normalized()


def facing(arm, what):
    """(front sign, left sign): the feet's toe direction along Y (-1: toes to -Y, the kit's front) and the side
    LeftUpLeg stands on along X (+1: left is +X)."""
    b = arm.data.bones
    foot, leg = b.get(bm.PREFIX + "LeftFoot"), b.get(bm.PREFIX + "LeftUpLeg")
    if foot is None or leg is None:
        raise Refused(f"{what}: no {bm.PREFIX}LeftFoot or LeftUpLeg to tell which way it faces")
    w = arm.matrix_world
    toe = (w @ foot.tail_local - w @ foot.head_local).y
    side = (w @ leg.head_local).x - (w @ b[bm.PREFIX + "Hips"].head_local).x
    return (-1 if toe < 0 else 1), (1 if side > 0 else -1)


def lowest_z(arm):
    w = arm.matrix_world
    return min(min((w @ b.head_local).z, (w @ b.tail_local).z) for b in arm.data.bones)


def parents_first(arm):
    return sorted(arm.data.bones, key=rf.depth)


# --- the transfer ---------------------------------------------------------------------------------------------
class Transfer:
    def __init__(self, src, tgt, turn=False):
        self.src, self.tgt = src, tgt
        # a pack facing the other way (both its toes and its left flipped: a half turn, not a mirror) is read turned
        self.sw = (Matrix.Rotation(math.pi, 4, "Z") if turn else Matrix()) @ src.matrix_world
        tb, sb = tgt.data.bones, src.data.bones
        self.shared = [b.name for b in tb if b.name.startswith(bm.PREFIX) and b.name in sb]
        self.hips = bm.PREFIX + "Hips"
        self.order = parents_first(tgt)
        self.tw = tgt.matrix_world.copy()
        self.tw_inv = self.tw.inverted()
        self.tw_q = rot_of(self.tw)
        self.s_rest = {n: self.sw @ sb[n].matrix_local for n in self.shared}
        self.t_rest = {n: world_rest(tgt, tb[n]) for n in self.shared}
        self.s_rest_q_inv = {n: rot_of(m).inverted() for n, m in self.s_rest.items()}
        self.align = {n: direction(self.t_rest[n]).rotation_difference(direction(self.s_rest[n]))
                      for n in self.shared}
        s_h = self.s_rest[self.hips].translation.z - lowest_z(src)
        t_h = self.t_rest[self.hips].translation.z - lowest_z(tgt)
        self.ratio = t_h / s_h if s_h > 1e-6 else 1.0
        dbg(f"shared bones {len(self.shared)}, hips height ratio {self.ratio:.4f}")

    def sample(self, frame):
        """The pack's world pose of every shared bone at a (fractional) frame."""
        sc = bpy.context.scene
        whole = math.floor(frame)
        sc.frame_set(int(whole), subframe=frame - whole)
        return {n: self.sw @ self.src.pose.bones[n].matrix for n in self.shared}

    def target_basis(self, src_pose):
        """{bone: (location, quaternion)} of the target's pose bones (matrix_basis) for one sampled pack pose."""
        tb = self.tgt.data.bones
        M, out = {}, {}
        for b in self.order:
            rest = b.matrix_local
            rel = (b.parent.matrix_local.inverted() @ rest) if b.parent else None
            base = (M[b.parent.name] @ rel) if b.parent else rest.copy()
            if b.name in src_pose:
                d = rot_of(src_pose[b.name]) @ self.s_rest_q_inv[b.name]
                q_arm = self.tw_q.inverted() @ (d @ self.align[b.name] @ rot_of(self.t_rest[b.name]))
                head = base.translation
                if b.name == self.hips:
                    moved = src_pose[b.name].translation - self.s_rest[b.name].translation
                    head = self.tw_inv @ (self.t_rest[b.name].translation + moved * self.ratio)
                M[b.name] = Matrix.Translation(head) @ q_arm.to_matrix().to_4x4()
            else:
                M[b.name] = base
            local = (rel.inverted() @ M[b.parent.name].inverted() if b.parent else rest.inverted()) @ M[b.name]
            loc, q, _ = local.decompose()
            out[b.name] = (loc, q)
        assert set(out) == {b.name for b in tb}
        return out

    def clip(self, src_act, name, src_fps, rate):
        """Key one clip on the target; returns (action, report entry, the pack's directions per checked frame)."""
        f0, f1 = (float(x) for x in src_act.frame_range)
        seconds = (f1 - f0) / src_fps
        n = max(1, round(seconds * rate))
        play(self.src, src_act)
        play(self.tgt, None)
        poses, checks = [], {}
        for k in range(n + 1):
            pose = self.sample(f0 + (f1 - f0) * k / n)
            poses.append(self.target_basis(pose))
            if k % CHECK_EVERY == 0 or k == n:
                checks[k] = {b: direction(m) for b, m in pose.items()
                             if self.src.data.bones[b].length > MIN_BONE_LEN}
        play(self.src, None)
        act = bpy.data.actions.new(name)
        play(self.tgt, act)
        prev = {}
        for k, basis in enumerate(poses):
            for bname, (loc, q) in basis.items():
                pb = self.tgt.pose.bones[bname]
                pb.rotation_mode = "QUATERNION"
                if bname in prev and prev[bname].dot(q) < 0:
                    q = -q                          # the same rotation, but no spin the long way round
                prev[bname] = q
                if bname not in self.shared and 0 < k < n:
                    continue                        # a bone the pack lacks holds its rest pose: two keys do
                pb.rotation_quaternion = q
                pb.keyframe_insert("rotation_quaternion", frame=k)
                if bname == self.hips:
                    pb.location = loc
                    pb.keyframe_insert("location", frame=k)
        act.use_fake_user = True
        play(self.tgt, None)
        entry = {"from": bm.clip_name(src_act.name), "frames": n, "fps": rate, "seconds": round(n / rate, 4),
                 "stretch": round(n / (seconds * rate), 4) if seconds > 0 else 1.0}
        return act, entry, checks

    def check(self, act, checks):
        """The largest angle between a target bone and the pack's bone over the checked frames (degrees)."""
        sc = bpy.context.scene
        play(self.tgt, act)
        worst, where = 0.0, ""
        for k, dirs in checks.items():
            sc.frame_set(k)
            for bname, want in dirs.items():
                if self.tgt.data.bones[bname].length <= MIN_BONE_LEN:
                    continue
                got = direction(self.tgt.matrix_world @ self.tgt.pose.bones[bname].matrix)
                ang = math.degrees(got.angle(want, 0.0))
                if ang > worst:
                    worst, where = ang, f"{bname} at frame {k}"
        play(self.tgt, None)
        return worst, where


def play(arm, act):
    """Give the armature this clip (None: none). Blender 4.4+ actions hold slots: when assigning did not pick one,
    the clip's first slot is set, or the pose would silently stay at rest."""
    ad = arm.animation_data or arm.animation_data_create()
    ad.action = act
    if act is not None and hasattr(ad, "action_slot") and ad.action_slot is None and len(getattr(act, "slots", [])):
        ad.action_slot = act.slots[0]


def remove_objects(objs):
    for o in objs:
        if o.name in bpy.data.objects:
            bpy.data.objects.remove(o, do_unlink=True)


def export(path, clips):
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", export_yup=True,
                              export_animations=bool(clips), export_animation_mode="ACTIONS",
                              export_anim_slide_to_zero=True)


def main():
    global DEBUG
    a = parse()
    DEBUG = a.debug
    rep = {"source": Path(a.source).name, "onto": Path(a.onto).name if a.onto else None, "failures": []}
    code = 0
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        sc = bpy.context.scene
        tgt = t_objs = None
        t_clips = []
        if a.onto:
            t_objs, t_acts, _ = import_file(a.onto)
            tgt = one_armature(t_objs, Path(a.onto).name)
            t_clips = bone_clips(t_acts)
            detach(tgt, t_clips)
            bc.conform_clip_fps(bpy, sc, t_clips, quiet=not DEBUG)
            have = {b.name for b in tgt.data.bones}
            missing = [c for c in bm.CORE if bm.PREFIX + c not in have]
            if missing:
                raise Refused(f"{Path(a.onto).name} is not Mixamo-named (no {', '.join(bm.PREFIX + c for c in missing[:4])}"
                              "): rig it with `bozzetto.py rig make` (names mixamo), or run this without --onto "
                              "on it first")
        t_fps = sc.render.fps / sc.render.fps_base
        s_objs, s_acts, s_fps = import_file(a.source)
        src = one_armature(s_objs, Path(a.source).name)
        s_clips = bone_clips(s_acts)
        detach(src, s_clips)
        kind, plan = rename_bones(src, s_clips, a.map)
        rep.update(map=kind, renamed=len(plan))
        print(f"[ OK ] {len(plan)} bones renamed to Mixamo names ({kind} map: {bm.MAP_NOTES.get(kind, 'your map')})")
        chosen = choose_clips(s_clips, a.pairs)
        if not chosen:
            raise Refused(f"{Path(a.source).name} has no clips")
        if tgt is None:                          # the pack's own character, renamed
            keep = {act for act, _ in chosen}
            for act in s_clips:
                if act not in keep:
                    bpy.data.actions.remove(act)
            for act, new in chosen:
                act.name = new
            sc.render.fps, sc.render.fps_base = int(round(s_fps)), 1.0
            rate = bc.conform_clip_fps(bpy, sc, [act for act, _ in chosen], quiet=not DEBUG)
            rep["clips"] = {new: {"from": new, "fps": rate} for _, new in chosen}
            export(a.out, chosen)
            print(f"[ OK ] wrote {a.out} with clips {', '.join(n for _, n in chosen)}; check and finish it: "
                  "rig_finish.py <it> --out <game>/..._rigged.glb --sheet clips.png")
            if a.sheet:
                rf.render_sheet(src, skinned(s_objs, src), [act for act, _ in chosen], a.sheet)
        else:
            for who, arm in (("the pack", src), ("the target", tgt)):
                rep[who.split()[-1] + "_facing"] = facing(arm, who)
            (pt, pl), (tt, tl) = rep["pack_facing"], rep["target_facing"]
            turn = pt == -tt and pl == -tl          # a half turn (an FBX made for another engine's front)
            rep["pack_turned"] = turn
            if turn:
                print("[info] the pack faces the other way from the target: its clips are read turned half round")
            elif (pt, pl) != (tt, tl):
                raise Refused(f"the pack and the target face different ways (toes, left side: pack "
                              f"{rep['pack_facing']}, target {rep['target_facing']}; the kit's front is toes to -Y in "
                              "Blender, left at +X): one of them is mirrored or turned a quarter; fix that first")
            taken = {act.name for act in t_clips}
            clash = [new for _, new in chosen if new in taken]
            if clash and not a.replace:
                raise Refused(f"the target already has a clip {clash[0]!r}: pass --replace, or name it otherwise "
                              f"(--clips {chosen[0][0].name}=other_name)")
            rate = t_fps if t_clips else (bc.clip_fps([k.co[0] for act, _ in chosen for fc in bc.fcurves_of(act)
                                                       for k in fc.keyframe_points], s_fps) or s_fps)
            sc.render.fps, sc.render.fps_base = int(round(rate)), 1.0
            for old in [act for act in t_clips if act.name in clash]:
                t_clips.remove(old)
                bpy.data.actions.remove(old)
            tr = Transfer(src, tgt, turn)
            if len(tr.shared) < len(bm.CORE):
                raise Refused(f"only {len(tr.shared)} bones are shared by the pack and the target")
            made, rep["clips"] = [], {}
            for act, new in chosen:
                out, entry, checks = tr.clip(act, new, s_fps, rate)
                err, where = tr.check(out, checks)
                entry["max_dir_error_deg"] = round(err, 3)
                rep["clips"][new] = entry
                made.append(out)
                ok = err <= MAX_DIR_ERROR_DEG
                print(f"[{' OK ' if ok else 'FAIL'}] {new} (from {entry['from']}): {entry['frames']} frames at "
                      f"{rate:g} fps, bones within {err:.2f} degrees of the pack's"
                      + ("" if ok else f" (worst {where}; the limit is {MAX_DIR_ERROR_DEG:g})"))
                dbg(f"{new}: {json.dumps(entry)}")
                if not ok:
                    rep["failures"].append(f"{new}: {where} {err:.2f} degrees off the pack's pose")
            if rep["failures"]:
                raise Refused("the transfer missed its own check; nothing written")
            for act in s_clips:
                bpy.data.actions.remove(act)
            remove_objects(s_objs)
            rep["recentred"] = rf.recentre_clips(tgt, made, 1.0)
            export(a.out, t_clips + made)
            rep["clips_in_file"] = [x.name for x in t_clips + made]
            print(f"[ OK ] wrote {a.out} with clips {', '.join(rep['clips_in_file'])}")
            if a.sheet:
                rf.render_sheet(tgt, skinned(t_objs, tgt), made, a.sheet)
    except (Refused, bm.MapError) as exc:
        rep["failures"].append(str(exc))
        print(f"[FAIL] {exc}")
        code = 1
    if a.report:
        Path(a.report).write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    try:
        code = main()
    except SystemExit as exc:          # argparse: usage errors
        code = exc.code if isinstance(exc.code, int) else 2
    except Exception as exc:  # noqa: BLE001
        if DEBUG:
            import traceback
            traceback.print_exc()
        print(f"[error] {exc!r}")
        code = 2
    bc.end_process(bpy, code)          # the bpy module crashes on a plain exit after a glTF export (#292)
