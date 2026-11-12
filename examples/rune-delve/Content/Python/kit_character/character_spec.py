# ---------------------------------------------------------------------------
# character_spec.py
# Purpose : The plain-Python half of the rigged character import (no `unreal`): reads a .glb's clip and joint
#           names, maps glTF names to the names Unreal's glTF importer (Interchange) gives them, finds each clip's
#           AnimSequence among the imported assets, and measures the angle between two rotations.
# Usage   : from kit_character import character_spec as spec   (character.py and the test use it)
#           python scripts/test_unreal_character.py               (the kit's exam of this file, without Unreal)
# Notes   : What Interchange did on UE 5.8.4 (2026-11-11, the golden character): a bone `mixamorig:Hips` became
#           `mixamorig_Hips` (only ':' was seen changing); a clip `walk` in `character.glb` became the AnimSequence
#           `characterwalk` (the file's stem, then the clip, no separator). Other characters in names are
#           sanitized by Unreal's object-name rules (OBJECT_NAME_BAD below) **(verify)**.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import json
import math
import struct

GLB_MAGIC = b"glTF"
GLB_JSON_CHUNK = 0x4E4F534A          # "JSON", little endian
BONE_NAME_MAP = {":": "_"}           # Interchange on UE 5.8: mixamorig:Hips -> mixamorig_Hips
OBJECT_NAME_BAD = "\"' ,.:|&!~\n\r\t@#(){}[]=;^%$`/\\*?<>"   # characters Unreal will not keep in an asset name


def read_gltf_json(path):
    """The JSON part of a .glb (or a .gltf file's JSON). Raises ValueError on a file that is neither."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != GLB_MAGIC:
        try:
            return json.loads(data.decode("utf-8-sig"))
        except ValueError as e:
            raise ValueError(f"{path}: neither a .glb nor glTF JSON ({e})")
    if len(data) < 20:
        raise ValueError(f"{path}: truncated .glb header")
    length, kind = struct.unpack_from("<II", data, 12)
    if kind != GLB_JSON_CHUNK or 20 + length > len(data):
        raise ValueError(f"{path}: the first .glb chunk is not JSON")
    return json.loads(data[20:20 + length].decode("utf-8"))


def clip_names(doc):
    """The glTF animations' names, in file order. An unnamed one is called animation_<index> here; the name
    Interchange gives its AnimSequence is **(verify)**, so name every clip in the file."""
    return [a.get("name") or f"animation_{i}" for i, a in enumerate(doc.get("animations") or [])]


def joint_names(doc, skin=0):
    """The names of one skin's joints, in the skin's order (empty when the file has no skin)."""
    skins = doc.get("skins") or []
    if skin >= len(skins):
        return []
    nodes = doc.get("nodes") or []
    return [nodes[j].get("name") or f"node_{j}" for j in skins[skin].get("joints") or []]


def ue_bone_name(name):
    """A glTF joint name as Interchange stores it on the Skeleton (mixamorig:Hips -> mixamorig_Hips)."""
    for bad, good in BONE_NAME_MAP.items():
        name = name.replace(bad, good)
    return name


def ue_object_name(name):
    """A name as Unreal keeps it in an asset name: every character it refuses becomes '_'."""
    return "".join("_" if c in OBJECT_NAME_BAD else c for c in name)


def match_clips(sequence_names, clips, stem):
    """{clip: sequence name} for each glTF clip: the sequence named exactly like the clip, else <stem><clip>
    (what Interchange does on UE 5.8), else <stem>_<clip>, else the only sequence whose name ends with the clip.
    A clip with no match is left out; the caller names it."""
    names = list(sequence_names)
    found = {}
    for clip in clips:
        c = ue_object_name(clip)
        s = ue_object_name(stem)
        for want in (c, s + c, f"{s}_{c}"):
            hit = [n for n in names if n.lower() == want.lower()]
            if len(hit) == 1:
                found[clip] = hit[0]
                break
        else:
            hit = [n for n in names if n.lower().endswith(c.lower())]
            if len(hit) == 1:
                found[clip] = hit[0]
    return found


def quat_angle_deg(a, b):
    """The angle in degrees between two rotations given as (x, y, z, w) quaternions (q and -q are the same)."""
    na = math.sqrt(sum(v * v for v in a))
    nb = math.sqrt(sum(v * v for v in b))
    if na == 0 or nb == 0:
        raise ValueError("a zero quaternion is not a rotation")
    dot = abs(sum(x * y for x, y in zip(a, b))) / (na * nb)
    return math.degrees(2 * math.acos(min(1.0, dot)))
