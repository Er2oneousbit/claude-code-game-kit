#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_unreal_character.py
# Purpose : Exam for the plain-Python half of the Unreal rigged character import
#           (engines/unreal/skeleton/Content/Python/kit_character/character_spec.py), without Unreal: it reads the
#           golden character's clip and joint names from the .glb, maps glTF bone names the way Interchange does on
#           UE 5.8 (':' -> '_'), finds each clip's AnimSequence among imported names, and measures rotation angles.
# Usage   : python scripts/test_unreal_character.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only. The Interchange half (import, sample walk) runs in the editor:
#           `python tools/dev.py test` in a scaffolded Unreal project (#290).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
SPEC_PY = KIT / "engines" / "unreal" / "skeleton" / "Content" / "Python" / "kit_character" / "character_spec.py"
GOLDEN = KIT / "core" / "data" / "golden" / "character"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cs = load(SPEC_PY, "character_spec")
EXPECTED = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
DOC = cs.read_gltf_json(GOLDEN / EXPECTED["file"])


class GoldenFile(unittest.TestCase):
    def test_clip_names_are_expected_jsons(self):
        self.assertEqual(sorted(cs.clip_names(DOC)), sorted(EXPECTED["clips"]))

    def test_joint_names_are_expected_jsons_with_the_root_first(self):
        joints = cs.joint_names(DOC)
        self.assertEqual(sorted(joints), sorted(EXPECTED["bones"]))
        self.assertEqual(joints[0], EXPECTED["root_bone"])

    def test_every_bone_maps_to_a_name_without_a_colon(self):
        mapped = [cs.ue_bone_name(b) for b in EXPECTED["bones"]]
        self.assertTrue(all(":" not in m for m in mapped), mapped)
        self.assertEqual(len(set(mapped)), len(mapped))
        self.assertEqual(cs.ue_bone_name("mixamorig:Hips"), "mixamorig_Hips")


class ReadGltf(unittest.TestCase):
    def test_plain_gltf_json_and_garbage(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.gltf"
            p.write_text(json.dumps({"animations": [{"name": "run"}, {}]}), encoding="utf-8")
            self.assertEqual(cs.clip_names(cs.read_gltf_json(p)), ["run", "animation_1"])
            bad = Path(d) / "b.glb"
            bad.write_bytes(b"\x00\x01not a gltf")
            with self.assertRaises(ValueError):
                cs.read_gltf_json(bad)
            short = Path(d) / "c.glb"
            short.write_bytes(b"glTF\x02\x00\x00\x00")
            with self.assertRaises(ValueError):
                cs.read_gltf_json(short)

    def test_no_skin_means_no_joints(self):
        self.assertEqual(cs.joint_names({"nodes": [{"name": "a"}]}), [])


class MatchClips(unittest.TestCase):
    def test_interchange_names_stem_then_clip(self):
        """UE 5.8: clip walk in character.glb became the AnimSequence characterwalk."""
        found = cs.match_clips(["characteridle", "characterwalk"], ["idle", "walk"], "character")
        self.assertEqual(found, {"idle": "characteridle", "walk": "characterwalk"})

    def test_exact_and_underscore_names_and_case(self):
        self.assertEqual(cs.match_clips(["Walk"], ["walk"], "hero"), {"walk": "Walk"})
        self.assertEqual(cs.match_clips(["hero_Run"], ["run"], "hero"), {"run": "hero_Run"})

    def test_names_unreal_refuses_are_sanitized(self):
        self.assertEqual(cs.ue_object_name("big jump.v2"), "big_jump_v2")
        self.assertEqual(cs.match_clips(["herobig_jump"], ["big jump"], "hero"), {"big jump": "herobig_jump"})

    def test_an_ambiguous_or_missing_clip_is_left_out(self):
        self.assertEqual(cs.match_clips(["a_walk", "b_walk"], ["walk"], "hero"), {})
        self.assertEqual(cs.match_clips(["heroidle"], ["walk"], "hero"), {})

    def test_the_longest_exact_rule_wins_over_a_suffix(self):
        found = cs.match_clips(["herowalk", "herofastwalk"], ["walk", "fastwalk"], "hero")
        self.assertEqual(found, {"walk": "herowalk", "fastwalk": "herofastwalk"})


class Angles(unittest.TestCase):
    def test_angles(self):
        ident = (0.0, 0.0, 0.0, 1.0)
        z90 = (0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4))
        self.assertAlmostEqual(cs.quat_angle_deg(ident, z90), 90.0, places=6)
        self.assertAlmostEqual(cs.quat_angle_deg(z90, tuple(-v for v in z90)), 0.0, places=6)
        self.assertAlmostEqual(cs.quat_angle_deg(ident, (0.0, 0.0, 0.0, 2.0)), 0.0, places=6)
        with self.assertRaises(ValueError):
            cs.quat_angle_deg(ident, (0.0, 0.0, 0.0, 0.0))


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
