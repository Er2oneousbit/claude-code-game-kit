#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_babble.py
# Purpose : Exam for babble.py: every voice renders a valid, unclipped WAV with a reveal timeline that matches
#           the text, takes repeat exactly, questions rise and exclamations get louder, recorded syllable banks
#           work, and bad input is a clear usage error.
# Usage   : python tools/audio/test_babble.py
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
import babble  # noqa: E402
from wavfile import read_wav, stats, write_wav  # noqa: E402

LINE = "Welcome, traveler. The bakery opens at dawn!"


class BabbleExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = babble.main([str(a) for a in args])
        return rc, out.getvalue() + err.getvalue()

    def timeline(self, wav):
        return json.loads(wav.with_suffix(".timeline.json").read_text(encoding="utf-8"))

    def test_every_voice_renders_a_valid_wav_and_timeline(self):
        for voice in babble.PRESETS:
            path = self.dir / f"{voice}.wav"
            rc, out = self.run_tool(LINE, "--voice", voice, "--out", path)
            self.assertEqual(rc, 0, out)
            samples, rate, loop = read_wav(path)
            st = stats(samples, rate)
            self.assertEqual(rate, babble.RATE)
            self.assertIsNone(loop)
            self.assertLess(st["peak_dbfs"], 0.0, f"{voice} clips")
            self.assertGreater(st["rms_dbfs"], -40.0, f"{voice} is nearly silent")
            self.assertLess(abs(samples[0]) + abs(samples[-1]), 0.01, f"{voice} starts or ends with a click")
            tl = self.timeline(path)
            self.assertEqual(tl["voice"], voice)
            self.assertAlmostEqual(tl["seconds"], st["seconds"], places=2)

    def test_reveal_has_one_entry_per_character_in_order(self):
        path = self.dir / "a.wav"
        self.run_tool(LINE, "--out", path)
        reveal = self.timeline(path)["reveal"]
        self.assertEqual([r["i"] for r in reveal], list(range(len(LINE))))
        times = [r["t"] for r in reveal]
        self.assertEqual(times, sorted(times))
        self.assertLess(times[-1], self.timeline(path)["seconds"])

    def test_punctuation_pauses_longer_than_a_letter(self):
        p = babble.check_params(dict(babble.PRESETS["knight"]))
        _, reveal, _ = babble.plan("ab, cd", p, babble.seeded_rng("ab, cd", "knight", 0))
        letter_step = reveal[1]["t"] - reveal[0]["t"]
        comma_step = reveal[3]["t"] - reveal[2]["t"]
        self.assertGreater(comma_step, 2 * letter_step)

    def test_same_take_same_bytes_and_seeds_or_text_differ(self):
        a, b, c, d = (self.dir / f"{n}.wav" for n in "abcd")
        self.run_tool(LINE, "--voice", "baker", "--seed", 2, "--out", a)
        self.run_tool(LINE, "--voice", "baker", "--seed", 2, "--out", b)
        self.run_tool(LINE, "--voice", "baker", "--seed", 3, "--out", c)
        self.run_tool(LINE + " Yes.", "--voice", "baker", "--seed", 2, "--out", d)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertNotEqual(a.read_bytes(), c.read_bytes())
        self.assertNotEqual(a.read_bytes(), d.read_bytes())

    def test_question_rises_on_the_last_two_blips_only(self):
        p = babble.check_params(dict(babble.PRESETS["knight"], jitter=0))
        text = "Is the gate open? Yes it is."
        blips, _, _ = babble.plan(text, p, babble.seeded_rng(text, "knight", 0))
        q = [b for b in blips if b["t"] < 1.0 / p["cps"] * text.index("?")]
        rest = blips[len(q):]
        self.assertTrue(all(b["semis"] == 0 for b in q[:-2]), q)
        self.assertTrue(all(b["semis"] >= 3 for b in q[-2:]), q[-2:])
        self.assertTrue(all(b["semis"] == 0 for b in rest), "the rise leaked into the next sentence")

    def test_exclamation_is_higher_and_louder(self):
        p = babble.check_params(dict(babble.PRESETS["knight"], jitter=0))
        text = "Run now!"
        blips, _, _ = babble.plan(text, p, babble.seeded_rng(text, "knight", 0))
        self.assertTrue(all(b["semis"] == 2 and b["gain"] > 1 for b in blips), blips)

    def test_vowel_only_letters_render(self):
        # "" is a substring of every string: an onset check written as `cons in "bdkpt"` crashed on vowel-only
        # blips such as "aa" or "eye" in an earlier prototype
        path = self.dir / "vowels.wav"
        rc, out = self.run_tool("aa ee eye oh", "--voice", "smith", "--out", path)
        self.assertEqual(rc, 0, out)

    def test_metal_changes_the_sound(self):
        plain, metal = self.dir / "plain.wav", self.dir / "metal.wav"
        self.run_tool(LINE, "--voice", "smith", "--out", plain)
        self.run_tool(LINE, "--voice", "smith", "--set", "metal=0.8", "--out", metal)
        self.assertNotEqual(plain.read_bytes(), metal.read_bytes())

    def test_recorded_bank_is_used(self):
        bank = self.dir / "bank"
        bank.mkdir()
        for name, hz in (("ba", 220), ("ko", 330), ("mi", 440)):
            tone = [0.5 * math.sin(2 * math.pi * hz * i / 22050) for i in range(int(0.2 * 22050))]
            write_wav(bank / f"{name}.wav", tone, 22050)
        synth, rec = self.dir / "synth.wav", self.dir / "rec.wav"
        self.run_tool(LINE, "--out", synth)
        rc, out = self.run_tool(LINE, "--bank-dir", bank, "--bank-f0", 220, "--out", rec)
        self.assertEqual(rc, 0, out)
        self.assertNotEqual(synth.read_bytes(), rec.read_bytes())
        st = stats(read_wav(rec)[0], babble.RATE)
        self.assertLess(st["peak_dbfs"], 0.0)

    def test_variants_and_lines_write_numbered_files(self):
        rc, out = self.run_tool(LINE, "--variants", 3, "--out", self.dir / "take.wav")
        self.assertEqual(rc, 0, out)
        self.assertEqual(sorted(p.name for p in self.dir.glob("take_*.wav")), ["take_1.wav", "take_2.wav", "take_3.wav"])
        script = self.dir / "dialog.txt"
        script.write_text("Hello there.\n\nGoodbye now!\n", encoding="utf-8")
        rc, out = self.run_tool("--lines", script, "--voice", "sprite", "--out", self.dir / "bubble.wav")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.timeline(self.dir / "bubble_2.wav")["text"], "Goodbye now!")
        self.assertFalse((self.dir / "bubble_3.wav").exists(), "blank lines must not become bubbles")

    def test_text_without_letters_fails_without_writing(self):
        path = self.dir / "dots.wav"
        rc, out = self.run_tool("...!?", "--out", path)
        self.assertEqual(rc, 1, out)
        self.assertIn("nothing to say", out)
        self.assertFalse(path.exists())

    def test_usage_errors_are_exit_2_without_traceback(self):
        existing = self.dir / "exists.wav"
        self.run_tool("hi", "--out", existing)
        cases = [
            ("hi", "--voice", "nobody", "--out", self.dir / "x.wav"),
            ("hi",),
            ("--out", self.dir / "x.wav"),
            ("hi", "--set", "loudness=3", "--out", self.dir / "x.wav"),
            ("hi", "--set", "f0=5", "--out", self.dir / "x.wav"),
            ("hi", "--set", "per=1.5", "--out", self.dir / "x.wav"),
            ("hi", "--out", existing),
            ("hi", "--bank-dir", self.dir / "missing", "--out", self.dir / "x.wav"),
        ]
        for args in cases:
            rc, out = self.run_tool(*args)
            self.assertEqual(rc, 2, f"{args}: {out}")
            self.assertIn("[error]", out)
            self.assertNotIn("Traceback", out)

    def test_overwrite_replaces(self):
        path = self.dir / "o.wav"
        self.run_tool("hi", "--out", path)
        rc, out = self.run_tool("hello", "--out", path, "--overwrite")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.timeline(path)["text"], "hello")


if __name__ == "__main__":
    unittest.main(verbosity=1)
