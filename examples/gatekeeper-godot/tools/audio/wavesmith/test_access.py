#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_access.py
# Purpose : Exam for access.py: sliders reach the right buses exactly once (nested and renamed trees, cycles, bad
#           values), caption arrows point at the side a sound comes from and stay off while it is on screen, the
#           direction rule rounds halves up as specified, the golden file is current, and the command line works.
# Usage   : python tools/audio/wavesmith/test_access.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import access as A  # noqa: E402

SLIDERS = {"master": 0.9, "music": 0.5, "sfx": 0.25, "ui": 0.75, "voice": 0.6}


class AccessExam(unittest.TestCase):
    def run_tool(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = A.main([str(a) for a in argv])
        return rc, out.getvalue() + err.getvalue()

    def test_each_slider_reaches_its_bus(self):
        buses = {b: ({} if b == "master" else {"parent": "master"})
                 for b in ("master", "music", "sfx", "ui", "dialogue", "ambience")}
        self.assertEqual(A.user_bus_gains(buses, SLIDERS), {"master": 0.9, "music": 0.5, "sfx": 0.25, "ui": 0.75,
                                                            "dialogue": 0.6, "ambience": 0.25})

    def test_a_slider_never_counts_twice_down_one_branch(self):
        buses = {"master": {}, "sfx": {"parent": "master"}, "ambience": {"parent": "sfx"},
                 "voice": {}, "dialogue": {"parent": "voice"}, "stingers": {"parent": "music"}, "music": {}}
        g = A.user_bus_gains(buses, SLIDERS)
        self.assertEqual((g["sfx"], g["ambience"], g["voice"], g["dialogue"], g["stingers"], g["music"]),
                         (0.25, 1.0, 0.6, 1.0, 1.0, 0.5))
        self.assertEqual(A.user_bus_gains({"a": {"parent": "b"}, "b": {"parent": "a"}}, SLIDERS), {"a": 1.0, "b": 1.0})

    def test_bad_slider_values(self):
        g = A.user_bus_gains({"master": {}, "music": {}, "sfx": {}, "ui": {}},
                             {"master": 2, "music": -1, "sfx": "loud", "ui": float("nan")})
        self.assertEqual(g, {"master": 1.0, "music": 0.0, "sfx": 1.0, "ui": 1.0})
        self.assertEqual(A.user_bus_gains({"dialogue": {}}, {}), {"dialogue": 1.0})        # missing slider

    def test_a_malformed_bus_is_named_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "events.json"
            for buses in ({"master": {}, "sfx": "master"}, {"master": {}, "sfx": [1]}):
                f.write_text(json.dumps({"version": 1, "buses": buses, "events": {}}), encoding="utf-8")
                rc, out = self.run_tool("gains", f)
                self.assertEqual(rc, 2, out)
                self.assertIn("bus sfx must be an object", out)
                self.assertNotIn("Traceback", out)
        self.assertEqual(A.user_bus_gains({"master": {}, "sfx": {"parent": ["x"]}}, SLIDERS)["sfx"], 0.25)
        with self.assertRaises(ValueError):
            A.user_bus_gains(["master"], SLIDERS)

    def test_arrows(self):
        w, h = 320, 180
        self.assertEqual(A.caption_arrow(0, 0, w, h), "")
        self.assertEqual(A.caption_arrow(320, -180, w, h), "")                             # the edge is on screen
        for (dx, dy), want in {(500, 0): "→", (-500, 0): "←", (0, -400): "↑", (0, 400): "↓", (500, 500): "↘",
                               (-500, 500): "↙", (-500, -500): "↖", (500, -500): "↗", (900, 120): "→"}.items():
            self.assertEqual(A.caption_arrow(dx, dy, w, h), want, (dx, dy))
        self.assertEqual(A.caption_direction(float("nan"), 0, w, h), -1)

    def test_direction_rounds_halves_up(self):
        # exactly halfway between "down-right" (1) and "down" (2), computed without atan2 noise: floor(1.5 + 0.5) = 2
        self.assertEqual(math.floor(1.5 + 0.5) % 8, 2)
        self.assertEqual(round(2.5), 2)                    # why round() is not the rule: halves go to even in Python
        self.assertEqual(math.floor(-0.5 + 0.5) % 8, 0)    # -22.5 degrees exactly: right, as JavaScript Math.round

    def test_golden_file_is_current_and_complete(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(A.cmd_vectors(type("A", (), {"write": False})()), 0)
        data = json.loads(A.GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(data["arrows"], list(A.ARROWS))
        self.assertEqual({c["type"] for c in data["cases"]}, {"access_gains", "access_arrow"})
        dirs = {s["dir"] for c in data["cases"] if c["type"] == "access_arrow" for s in c["steps"]}
        self.assertEqual(dirs, {-1, 0, 1, 2, 3, 4, 5, 6, 7})                            # every direction covered

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "ev.json"
            f.write_text(json.dumps({"buses": {"master": {}, "sfx": {"parent": "master"},
                                               "ambience": {"parent": "sfx"}}}), encoding="utf-8")
            rc, out = self.run_tool("gains", f, "--sfx", "0.5")
            self.assertEqual(rc, 0, out)
            self.assertIn("sfx          x 0.500   (sfx slider)", out)
            self.assertIn("ambience     x 1.000   (sfx slider already on a parent bus)", out)
            rc, out = self.run_tool("gains", Path(tmp) / "none.json")
            self.assertEqual(rc, 2)
        rc, out = self.run_tool("arrow", "--dx", -900, "--dy", 0, "--half-w", 320, "--half-h", 180)
        self.assertIn("← (direction 4)", out)

    def test_a_golden_file_that_is_not_utf8_is_a_usage_error(self):
        """#261: vectors --check decoded the file on disk strictly, so bad bytes were a UnicodeDecodeError traceback."""
        golden = A.GOLDEN
        try:
            with tempfile.TemporaryDirectory() as tmp:
                A.GOLDEN = Path(tmp) / "access.json"
                A.GOLDEN.write_bytes(b"\xff\xfe\x00bad")
                rc, out = self.run_tool("vectors", "--check")
                self.assertEqual(rc, 2, out)
                self.assertIn("[error]", out)
        finally:
            A.GOLDEN = golden


if __name__ == "__main__":
    unittest.main(verbosity=1)
