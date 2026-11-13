#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# bone_map.py
# Purpose : Bone-name maps from animation packs to Mixamo's names (`mixamorig:Hips` ...), the names Bozzetto's rig
#           routes give a skeleton and every engine's character helper is tested on (#205). rig_retarget.py renames a
#           pack's skeleton with these before it plays the pack's clips on a Bozzetto rig (or keeps the pack's own
#           character, now Mixamo-named). Standard library only, so the exam checks the maps on any Python 3.8+.
# Usage   : import bone_map as bm
#             kind, plan = bm.rename_plan(bone_names)          # ("ual", {"pelvis": "mixamorig:Hips", ...})
#             kind, plan = bm.rename_plan(bone_names, "my_map.json")   # a map of your own (JSON, see below)
#             pairs = bm.parse_clips("Walk_Loop=walk,Idle_Loop=idle")   # [("Walk_Loop", "walk"), ...]
#           python tools/bozzetto/bone_map.py [--map file.json] NAME ...  prints the plan for those bone names
# Exit    : (the command) 0 every core bone mapped, 1 not, 2 usage
# Notes   : Built-in maps:
#             mixamo  any spelling of Mixamo's own names: `mixamorig:Hips` (Mixamo's FBX, Bozzetto, Unity, Bevy),
#                     `mixamorig1:Hips` .. (Mixamo numbers the prefix when a scene holds two characters),
#                     `mixamorig_Hips` (Godot, Unreal), `mixamorigHips` (three.js) and bare `Hips`: all become
#                     `mixamorig:Hips`
#             ual     Quaternius' Universal Animation Library (CC0, 2025): `pelvis`, `spine_01..03`, `neck_01`,
#                     `Head`, `clavicle_l`, `upperarm_l`, `lowerarm_l`, `hand_l`, `thigh_l`, `calf_l`, `foot_l`,
#                     `ball_l`, `ball_leaf_l`, fingers `thumb_01_l` .. `pinky_04_leaf_l` (the UE Mannequin's
#                     naming); its ground-level `root` bone has no Mixamo role and keeps its name
#           Matching is case-insensitive. A map of your own is JSON {"their_name": "Hips", ...}: a Mixamo role with or
#           without the `mixamorig:` prefix; names it does not list go through the mixamo spelling rule.
#           A plan is refused (MapError) when two bones would get one name, a new name is already another bone's,
#           or a core role (CORE) is missing: a half-mapped skeleton would play half a clip.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   mixamo_name(n): strip "mixamorig", digits and ":"/"_" -> a known Mixamo role? "mixamorig:" + role : None
#   rename_plan(names, map_file=None):
#     candidates = [the map file] or [mixamo, ual]; for each: new name per bone (map entry, else mixamo_name)
#     pick the candidate that maps the most CORE roles (mixamo first on a tie) -> refuse if any CORE role is missing,
#     two bones share a new name, or a new name is an unmapped bone's -> {old: new} for the bones whose name changes
#   parse_clips("A=a,B,all") -> [(source clip, new name)] or "all"
import argparse
import json
import re
import sys
from pathlib import Path

PREFIX = "mixamorig:"
# Mixamo's humanoid roles (the bone names after the prefix); fingers 1..4 per finger, 4 being the tip
_SIDE_ROLES = ["Shoulder", "Arm", "ForeArm", "Hand", "UpLeg", "Leg", "Foot", "ToeBase", "Toe_End"] + \
    [f"Hand{f}{i}" for f in ("Thumb", "Index", "Middle", "Ring", "Pinky") for i in range(1, 5)]
ROLES = ["Hips", "Spine", "Spine1", "Spine2", "Neck", "Head", "HeadTop_End"] + \
    [s + r for s in ("Left", "Right") for r in _SIDE_ROLES]
# the roles a skeleton must have for the engines' character helpers and rig_finish.py (its MIXAMO_CORE) to treat it
# as Mixamo-named; a pack without one of these is refused, never half-mapped
CORE = ("Hips", "Spine", "Head", "LeftUpLeg", "RightUpLeg", "LeftLeg", "RightLeg", "LeftArm", "RightArm",
        "LeftForeArm", "RightForeArm", "LeftHand", "RightHand")
_ROLE_BY_LOWER = {r.lower(): r for r in ROLES}
_MIXAMO_SPELLING = re.compile(r"^mixamorig\d*[:_]?(?P<role>.+)$", re.IGNORECASE)
_LAYER = re.compile(r"^(Layer\d*|BaseLayer|AnimLayer\d*)$", re.IGNORECASE)   # FBX animation layer names


def _ual():
    """Quaternius UAL (UE Mannequin naming) -> Mixamo roles, keys lower case."""
    m = {"pelvis": "Hips", "spine_01": "Spine", "spine_02": "Spine1", "spine_03": "Spine2", "neck_01": "Neck",
         "head": "Head"}
    for s, side in (("l", "Left"), ("r", "Right")):
        for theirs, role in (("clavicle", "Shoulder"), ("upperarm", "Arm"), ("lowerarm", "ForeArm"),
                             ("hand", "Hand"), ("thigh", "UpLeg"), ("calf", "Leg"), ("foot", "Foot"),
                             ("ball", "ToeBase"), ("ball_leaf", "Toe_End")):
            m[f"{theirs}_{s}"] = side + role
        for finger in ("thumb", "index", "middle", "ring", "pinky"):
            for i in (1, 2, 3):
                m[f"{finger}_0{i}_{s}"] = f"{side}Hand{finger.capitalize()}{i}"
            m[f"{finger}_04_leaf_{s}"] = f"{side}Hand{finger.capitalize()}4"
    return m


MAPS = {"mixamo": {}, "ual": _ual()}          # mixamo: the spelling rule alone
MAP_NOTES = {"mixamo": "Mixamo's own names (any prefix spelling)",
             "ual": "Quaternius Universal Animation Library (UE Mannequin naming)"}


class MapError(Exception):
    pass


def mixamo_name(name):
    """`mixamorig:Hips`, `mixamorig1:Hips`, `mixamorig_Hips`, `mixamorigHips` or `Hips` -> `mixamorig:Hips`; a name
    that is no Mixamo role -> None."""
    m = _MIXAMO_SPELLING.match(name)
    role = _ROLE_BY_LOWER.get((m.group("role") if m else name).lower())
    return PREFIX + role if role else None


def role_of(value):
    """A map value ("Hips" or "mixamorig:Hips") -> "mixamorig:Hips"; MapError when it is no Mixamo role."""
    full = mixamo_name(value)
    if full is None:
        raise MapError(f"{value!r} is not a Mixamo bone name (e.g. Hips, Spine1, LeftUpLeg, RightHandIndex1)")
    return full


def load_map(path):
    """A JSON map {"their_name": "Hips" | "mixamorig:Hips"} -> {their_name lower: "mixamorig:Hips"}."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MapError(f"--map {path}: {exc}")
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise MapError(f"--map {path}: write an object of names, {{\"pelvis\": \"Hips\", \"thigh_l\": \"LeftUpLeg\"}}")
    return {k.lower(): role_of(v) for k, v in data.items()}


def _apply(names, table):
    """{bone: new name or None} under one map (entries first, then the Mixamo spelling rule)."""
    out = {}
    for n in names:
        hit = table.get(n.lower())
        out[n] = (hit if hit.startswith(PREFIX) else PREFIX + hit) if hit else mixamo_name(n)
    return out


def rename_plan(names, map_file=None):
    """(map name, {old: new}) for the bones whose name changes; MapError when the skeleton does not map."""
    names = list(names)
    if map_file:
        candidates = [(Path(map_file).name, load_map(map_file))]
    else:
        candidates = list(MAPS.items())
    scored = []
    for kind, table in candidates:
        new = _apply(names, table)
        got = {v for v in new.values() if v}
        scored.append((sum(PREFIX + c in got for c in CORE), kind, new))
    best = max(scored, key=lambda s: s[0])          # max keeps the first on a tie: mixamo before ual
    score, kind, new = best
    missing = [c for c in CORE if PREFIX + c not in {v for v in new.values() if v}]
    if missing:
        raise MapError(f"no bone map fits this skeleton (the closest, {kind}, misses {', '.join(missing)}): pass "
                       "--map your_map.json ({\"their_name\": \"Hips\", ...}); bones: "
                       + ", ".join(names[:12]) + (" ..." if len(names) > 12 else ""))
    seen = {}
    for old, nn in new.items():
        if nn is None:
            continue
        if nn in seen:
            raise MapError(f"{seen[nn]!r} and {old!r} would both become {nn}: one of them is not what the {kind} "
                           "map expects (pass --map to say which)")
        seen[nn] = old
    kept = {n for n, nn in new.items() if nn is None}
    clash = sorted(nn for nn in seen if nn in kept)
    if clash:
        raise MapError(f"{clash[0]} is already the name of a bone the map leaves alone")
    return kind, {old: nn for old, nn in new.items() if nn and nn != old}


def parse_clips(text):
    """'Walk_Loop=walk,Idle_Loop=idle,Jump' -> [("Walk_Loop", "walk"), ("Idle_Loop", "idle"), ("Jump", "Jump")];
    'all' (or empty) -> 'all'. ValueError with a plain message when wrong."""
    text = (text or "").strip()
    if text.lower() in ("", "all"):
        return "all"
    out, new_names = [], set()
    for part in text.split(","):
        src, sep, dst = part.strip().partition("=")
        src, dst = src.strip(), (dst.strip() if sep else src.strip())
        if not src or not dst:
            raise ValueError(f"--clips {part.strip()!r}: write SOURCE=new_name or SOURCE, comma-separated")
        if dst in new_names:
            raise ValueError(f"--clips names two clips {dst!r}")
        new_names.add(dst)
        out.append((src, dst))
    return out


def clip_name(action_name):
    """An imported action's clip name: glTF keeps the clip's own name; Blender's FBX importer writes
    '<object>|<take>|<clip>' (Quaternius' FBX: 'Armature|Armature|Walk_Loop'; Mixamo's, by its naming:
    'Armature|mixamo.com|Layer0'): the last part that is not an animation layer's name."""
    parts = [p for p in action_name.split("|") if p]
    while len(parts) > 1 and _LAYER.match(parts[-1]):
        parts.pop()
    return parts[-1] if parts else action_name


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="bone_map.py", description="Print how a skeleton's bone names map to Mixamo's "
                                 "(the plan rig_retarget.py applies). Built-in maps: "
                                 + "; ".join(f"{k}: {v}" for k, v in MAP_NOTES.items()) + ".")
    ap.add_argument("names", nargs="+", help="bone names, as the pack has them")
    ap.add_argument("--map", help="a JSON map of your own: {\"their_name\": \"Hips\", ...}")
    a = ap.parse_args(argv)
    try:
        kind, plan = rename_plan(a.names, a.map)
    except MapError as exc:
        print(f"[error] {exc}")
        return 1
    print(f"[ OK ] map: {kind}")
    for old in a.names:
        print(f"  {old} -> {plan.get(old, old + ' (kept)')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
