#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_presets.py
# Purpose : Exam for data/input/presets.json (#166, motor access): each one-handed layout binds every action the
#           shell knows, on both devices, with no two actions of a group on one input, and really stays on its side
#           of the keyboard and of the gamepad.
# Usage   : python tools/access/test_presets.py      (in a game)   python core/tools/access/test_presets.py (kit)
# Notes   : Standard library only. The action list and the group rule (ui_* apart from the rest) are the shell's
#           reference (tools/golden_vectors.py) when it is there, else the ones below.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRESETS = next((p for p in (ROOT / "data/input/presets.json", ROOT / "core/data/input/presets.json") if p.is_file()),
               ROOT / "data/input/presets.json")
ACTIONS = ["ui_up", "ui_down", "ui_left", "ui_right", "ui_accept", "ui_cancel", "move_left", "move_right", "move_up",
           "move_down", "jump", "attack", "interact", "pause"]
# what one hand reaches: QWERTY's halves (space and the edge keys under either thumb or little finger), the pad's halves
LEFT_KEYS = set("qwertasdfgzxcvb") | {"space", "escape", "tab", "shift"}
RIGHT_KEYS = set("yuiophjklnm") | {"space", "enter", "backspace"}
LEFT_PAD = {"dpad_up", "dpad_down", "dpad_left", "dpad_right", "l1", "l2", "l3", "select"}
RIGHT_PAD = {"south", "east", "west", "north", "r1", "r2", "r3", "start"}
SIDES = {"one_hand_left": (LEFT_KEYS, LEFT_PAD), "one_hand_right": (RIGHT_KEYS, RIGHT_PAD)}


def group(action):
    return "ui" if action.startswith("ui_") else "game"


class PresetExam(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(PRESETS.read_text(encoding="utf-8"))

    def test_both_layouts_bind_every_action_on_both_devices(self):
        self.assertEqual(sorted(self.data["presets"]), sorted(SIDES))
        for name, preset in self.data["presets"].items():
            with self.subTest(preset=name):
                self.assertEqual(sorted(preset["bindings"]), sorted(ACTIONS))
                for action, pair in preset["bindings"].items():
                    self.assertEqual(len(pair), 2, action)
                    self.assertTrue(pair[0].startswith("key:") and pair[1].startswith("pad:"), (action, pair))

    def test_no_two_actions_of_a_group_share_an_input(self):
        for name, preset in self.data["presets"].items():
            seen = {}
            for action, pair in preset["bindings"].items():
                for b in pair:
                    key = (group(action), b)
                    with self.subTest(preset=name, binding=b):
                        self.assertNotIn(key, seen, f"{action} and {seen.get(key)} both use {b}")
                    seen[key] = action

    def test_each_layout_stays_on_its_side(self):
        for name, (keys, pad) in SIDES.items():
            for action, (kb, button) in self.data["presets"][name]["bindings"].items():
                with self.subTest(preset=name, action=action):
                    self.assertIn(kb.split(":", 1)[1], keys)
                    self.assertIn(button.split(":", 1)[1], pad)

    def test_the_reference_agrees_on_the_actions(self):
        ref = ROOT / "tools/golden_vectors.py"
        if not ref.is_file():
            self.skipTest("the shell's reference is not in this project")
        sys.path.insert(0, str(ref.parent))
        import golden_vectors
        self.assertEqual(sorted(golden_vectors.DEFAULT_BINDINGS), sorted(ACTIONS))
        for name, preset in self.data["presets"].items():
            b, conflicts = dict(preset["bindings"]), []
            for action, pair in preset["bindings"].items():
                for slot, binding in enumerate(pair):
                    b, c = golden_vectors.rebind(b, action, slot, binding)
                    conflicts += c
            self.assertEqual(conflicts, [], name)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=1)
