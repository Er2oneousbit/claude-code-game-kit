#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_sfx_synth.py
# Purpose : Exam for sfx_synth.py and wavfile.py: every preset renders a valid, unclipped WAV, seeds
#           repeat exactly, recipes re-render byte for byte, and bad input is a clear usage error.
# Usage   : python tools/audio/test_sfx_synth.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sfx_synth  # noqa: E402
from wavfile import read_wav, stats, write_wav  # noqa: E402


class SfxSynthExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sfx_synth.main([str(a) for a in args])
        return rc, out.getvalue() + err.getvalue()

    def test_every_preset_renders_a_valid_wav(self):
        for name in sfx_synth.PRESETS:
            path = self.dir / f"{name}.wav"
            rc, out = self.run_tool(name, "--out", path)
            self.assertEqual(rc, 0, out)
            samples, rate, loop = read_wav(path)
            st = stats(samples, rate)
            self.assertEqual(rate, sfx_synth.RATE)
            self.assertIsNone(loop, "effects must not loop")
            self.assertGreater(st["seconds"], 0.03, name)
            self.assertLess(st["peak_dbfs"], 0.0, f"{name} clips")
            self.assertGreater(st["rms_dbfs"], -40.0, f"{name} is nearly silent")
            self.assertLess(abs(samples[0]) + abs(samples[-1]), 0.01, f"{name} starts or ends with a click")

    def test_same_seed_same_bytes_and_different_seeds_differ(self):
        a, b, c = self.dir / "a.wav", self.dir / "b.wav", self.dir / "c.wav"
        self.run_tool("coin", "--seed", 4, "--out", a)
        self.run_tool("coin", "--seed", 4, "--out", b)
        self.run_tool("coin", "--seed", 5, "--out", c)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertNotEqual(a.read_bytes(), c.read_bytes())

    def test_recipe_rerenders_exactly(self):
        first = self.dir / "jump.wav"
        rc, out = self.run_tool("jump", "--seed", 2, "--set", "decay=0.3", "--out", first)
        self.assertEqual(rc, 0, out)
        recipe = first.with_suffix(".sfx.json")
        self.assertEqual(json.loads(recipe.read_text(encoding="utf-8"))["params"]["decay"], 0.3)
        again = self.dir / "again.wav"
        rc, out = self.run_tool("--from", recipe, "--out", again, "--no-recipe")
        self.assertEqual(rc, 0, out)
        self.assertEqual(first.read_bytes(), again.read_bytes())

    def test_noise_preset_repeats_exactly(self):
        a, b = self.dir / "a.wav", self.dir / "b.wav"
        self.run_tool("explosion", "--out", a)
        self.run_tool("explosion", "--out", b)
        self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_variants_write_numbered_files(self):
        rc, out = self.run_tool("blip", "--variants", 3, "--out", self.dir / "blip.wav")
        self.assertEqual(rc, 0, out)
        for i in (1, 2, 3):
            self.assertTrue((self.dir / f"blip_{i}.wav").is_file())
            self.assertTrue((self.dir / f"blip_{i}.sfx.json").is_file())

    def test_slide_changes_pitch_the_right_way(self):
        # a rising jump: more zero crossings in the second half than in the first
        path = self.dir / "j.wav"
        self.run_tool("jump", "--set", "wave=sine", "--out", path)
        s, _, _ = read_wav(path)
        half = len(s) // 2
        crossings = [sum(1 for i in range(a + 1, b) if (s[i - 1] < 0) != (s[i] < 0)) for a, b in ((0, half), (half, len(s)))]
        self.assertGreater(crossings[1], crossings[0])

    def test_usage_errors(self):
        cases = [("nope", "--out", self.dir / "x.wav"), ("jump",),
                 ("jump", "--set", "wobble=3", "--out", self.dir / "x.wav"),
                 ("jump", "--set", "wave=organ", "--out", self.dir / "x.wav"),
                 ("jump", "--set", "volume=2", "--out", self.dir / "x.wav")]
        for args in cases:
            rc, out = self.run_tool(*args)
            self.assertEqual(rc, 2, args)
            self.assertIn("[error]", out)

    def test_from_recipe_refuses_variants_and_seed(self):
        first = self.dir / "jump.wav"
        self.run_tool("jump", "--out", first)
        for extra in (("--variants", 3), ("--seed", 4)):
            rc, out = self.run_tool("--from", first.with_suffix(".sfx.json"), "--out", self.dir / "x.wav", *extra)
            self.assertEqual(rc, 2, extra)
            self.assertIn("does not combine", out)
        self.assertEqual(sorted(p.name for p in self.dir.glob("x*")), [], "nothing written")

    def test_existing_file_not_overwritten(self):
        path = self.dir / "j.wav"
        self.run_tool("jump", "--out", path)
        rc, out = self.run_tool("jump", "--seed", 9, "--out", path)
        self.assertEqual(rc, 2)
        self.assertIn("--overwrite", out)

    def test_clipping_is_reported(self):
        rc, out = self.run_tool("explosion", "--set", "volume=1", "--set", "punch=1", "--out", self.dir / "loud.wav")
        self.assertEqual(rc, 1, out)
        self.assertIn("clipped", out)

    def test_wav_loop_chunk_round_trip(self):
        path = self.dir / "loop.wav"
        write_wav(path, [0.0, 0.5, -0.5, 0.0], 8000, loop=(0, 3))
        samples, rate, loop = read_wav(path)
        self.assertEqual((rate, loop, len(samples)), (8000, (0, 3), 4))


if __name__ == "__main__":
    unittest.main(verbosity=1)
