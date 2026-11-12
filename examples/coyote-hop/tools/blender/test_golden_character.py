#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_golden_character.py
# Purpose : The exam for the golden rigged character (data/golden/character/character.glb, built by
#           golden_character.py): the file every engine's character test loads. Reads the .glb with the standard
#           library (no Blender) and checks it against expected.json: the joint names (Mixamo), the root bone, the
#           clips and their lengths, that every clip loops (last key = first key), that walk really swings the
#           moving bone (decoded from the key values, not from accessor min/max, which glTF only requires on time),
#           the height, no textures, and the size budget. With Blender or bpy it also rebuilds the character into
#           a temp folder and checks that the committed file is current (by what the kit built: nodes, joints,
#           triangles, clips and their lengths; not by how the exporter packed it, which differs between Blender
#           4.2 and 5.x, #292).
# Usage   : python tools/blender/test_golden_character.py [-v]
#           GOLDEN_CHARACTER_BLENDER=skip|bpy|<blender.exe> picks the rebuild (default: BLENDER_BIN, then Blender on
#           PATH, then the bpy module; none found: that one test is skipped)
# Exit    : 0 all tests pass, 1 a test failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): the rebuild check compares the character, not the
#           exporter's accessor count (#292)
# ---------------------------------------------------------------------------
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILDER = HERE / "golden_character.py"
GOLDEN = HERE.parents[1] / "data" / "golden" / "character"
GLB = GOLDEN / "character.glb"
EXPECTED = GOLDEN / "expected.json"
MAX_BYTES = 300 * 1024          # the fixture stays small: every game ships a copy
COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_glb(path):
    """(json dict, bin bytes) of a .glb."""
    data = Path(path).read_bytes()
    magic, version, _ = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or version != 2:
        raise ValueError(f"{path} is not a glTF 2 binary")
    jlen, jtype = struct.unpack_from("<I4s", data, 12)
    doc = json.loads(data[20:20 + jlen].decode("utf-8"))
    rest = 20 + jlen
    blen, _ = struct.unpack_from("<I4s", data, rest)
    return doc, data[rest + 8:rest + 8 + blen]


def floats(doc, binary, index):
    """An accessor of 32-bit floats as a list of tuples (or of numbers for SCALAR)."""
    acc = doc["accessors"][index]
    if acc["componentType"] != 5126:
        raise ValueError(f"accessor {index} is not float32")
    view = doc["bufferViews"][acc["bufferView"]]
    n = COMPONENTS[acc["type"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride", 4 * n)
    out = []
    for i in range(acc["count"]):
        vals = struct.unpack_from(f"<{n}f", binary, start + i * stride)
        out.append(vals[0] if n == 1 else vals)
    return out


def quat_angle_deg(a, b):
    dot = abs(sum(x * y for x, y in zip(a, b)))
    return math.degrees(2 * math.acos(min(1.0, dot)))


def find_blender():
    """('blender', path) or ('bpy', None) or (None, reason)."""
    pick = os.environ.get("GOLDEN_CHARACTER_BLENDER", "")
    if pick == "skip":
        return None, "GOLDEN_CHARACTER_BLENDER=skip"
    if pick and pick != "bpy":
        return ("blender", pick) if Path(pick).exists() else (None, f"{pick} not found")
    if not pick:
        for cand in (os.environ.get("BLENDER_BIN", ""), shutil.which("blender") or ""):
            if cand and Path(cand).exists():
                return "blender", cand
    try:
        import bpy  # noqa: F401
        return "bpy", None
    except ImportError:
        return None, "no Blender (BLENDER_BIN, PATH) and no bpy module"


class GoldenCharacter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exp = json.loads(EXPECTED.read_text(encoding="utf-8"))
        cls.doc, cls.bin = read_glb(GLB)
        cls.nodes = cls.doc["nodes"]

    def node_index(self, name):
        return next(i for i, n in enumerate(self.nodes) if n.get("name") == name)

    def test_size_budget(self):
        self.assertLess(GLB.stat().st_size, MAX_BYTES)

    def test_joints_are_the_expected_mixamo_bones(self):
        skins = self.doc["skins"]
        self.assertEqual(len(skins), 1)
        names = [self.nodes[j]["name"] for j in skins[0]["joints"]]
        self.assertEqual(sorted(names), sorted(self.exp["bones"]))
        self.assertTrue(all(n.startswith("mixamorig:") for n in names), names)

    def test_root_bone_is_hips(self):
        joints = set(self.doc["skins"][0]["joints"])
        children = {c for j in joints for c in self.nodes[j].get("children", [])}
        roots = [self.nodes[j]["name"] for j in joints if j not in children]
        self.assertEqual(roots, [self.exp["root_bone"]])

    def test_clips_and_lengths(self):
        anims = {a["name"]: a for a in self.doc["animations"]}
        self.assertEqual(sorted(anims), sorted(self.exp["clips"]))
        for name, want in self.exp["clips"].items():
            times = floats(self.doc, self.bin, anims[name]["samplers"][0]["input"])
            self.assertAlmostEqual(times[0], 0.0, places=5, msg=f"{name} starts at {times[0]} s, not 0")
            self.assertAlmostEqual(times[-1], want["seconds"], places=4, msg=name)

    def test_every_clip_loops_seamlessly(self):
        for a in self.doc["animations"]:
            for s in a["samplers"]:
                vals = floats(self.doc, self.bin, s["output"])
                first, last = vals[0], vals[-1]
                diff = max(abs(x - y) for x, y in zip(first, last)) if isinstance(first, tuple) else abs(first - last)
                self.assertLess(diff, 1e-4, f"{a['name']}: a channel ends {diff} away from where it starts")

    def test_walk_swings_the_moving_bone(self):
        walk = next(a for a in self.doc["animations"] if a["name"] == "walk")
        node = self.node_index(self.exp["moving_bone"])
        ch = next(c for c in walk["channels"] if c["target"] == {"node": node, "path": "rotation"})
        keys = floats(self.doc, self.bin, walk["samplers"][ch["sampler"]]["output"])
        swing = max(quat_angle_deg(a, b) for a in keys for b in keys)
        self.assertGreater(swing, 0.9 * self.exp["moving_bone_swing_deg"], f"swing {swing:.1f} degrees")

    def test_height_and_feet_on_the_ground(self):
        prim = self.doc["meshes"][0]["primitives"]
        lo = min(self.doc["accessors"][p["attributes"]["POSITION"]]["min"][1] for p in prim)
        hi = max(self.doc["accessors"][p["attributes"]["POSITION"]]["max"][1] for p in prim)
        self.assertAlmostEqual(hi - lo, self.exp["height_m"], places=2)
        self.assertLess(abs(lo), 0.01, f"feet at {lo} m, not on the ground (y = 0)")

    def test_no_textures_or_required_extensions(self):
        # engine tests load it headless (Three.js in Node, Bevy without a GPU): no images to decode
        self.assertFalse(self.doc.get("images"))
        self.assertFalse(self.doc.get("extensionsRequired"))

    def test_rebuild_matches(self):
        how, where = find_blender()
        if how is None:
            self.skipTest(f"rebuild check skipped: {where}")
        with tempfile.TemporaryDirectory(prefix="golden_char_") as tmp:
            out = Path(tmp) / "character.glb"
            args = ["--out", str(out)]
            if how == "blender":
                cmd = [where, "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(BUILDER), "--", *args]
            else:
                cmd = [sys.executable, str(BUILDER), *args]
            proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=600)
            self.assertEqual(proc.returncode, 0, (proc.stdout + proc.stderr)[-800:])
            got = json.loads((Path(tmp) / "expected.json").read_text(encoding="utf-8"))
            self.assertEqual(got, self.exp, "the committed expected.json is stale: rebuild with golden_character.py")
            doc, binary = read_glb(out)
            # what the kit controls, not how an exporter packs it: Blender 4.2 writes 157 accessors for the same
            # character that 5.x writes in 89 (#292), so the accessor count is no fingerprint
            self.assertEqual(shape_of(doc, binary), shape_of(self.doc, self.bin),
                             "the committed character.glb is stale: rebuild with golden_character.py")


def shape_of(doc, binary):
    """The character as the kit built it: nodes, joints, triangles, clips and their lengths (the same on every Blender
    that exports it)."""
    tris = sum(doc["accessors"][p["indices"]]["count"] // 3 for m in doc["meshes"] for p in m["primitives"])
    clips = {}
    for a in doc["animations"]:
        times = [floats(doc, binary, s["input"]) for s in a["samplers"]]
        clips[a["name"]] = (round(min(t[0] for t in times), 4), round(max(t[-1] for t in times), 4),
                            len(a["channels"]))
    return {"nodes": sorted(n.get("name", "") for n in doc["nodes"]),
            "joints": sorted(doc["nodes"][j]["name"] for j in doc["skins"][0]["joints"]),   # 4.2 orders them differently
            "triangles": tris, "clips": clips}


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    unittest.main()
