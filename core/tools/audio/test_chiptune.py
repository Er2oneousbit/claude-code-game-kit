#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_chiptune.py
# Purpose : Exam for chiptune.py: notes come out at the right pitch and time, loops get loop points
#           and a click-free seam, ties and rests work, drums render, and song mistakes name the
#           pattern, channel and step.
# Usage   : python tools/audio/test_chiptune.py
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
import chiptune  # noqa: E402
from wavfile import read_wav, stats  # noqa: E402

RATE = 22050


def song(patterns, order=None, channels=None, **extra):
    s = {"bpm": 120, "steps_per_beat": 4, "rate": RATE,
         "channels": channels or {"lead": {"wave": "sine", "volume": 0.5, "sustain": 1.0, "decay": 0.01},
                                  "drums": {"wave": "drums", "volume": 0.4}},
         "patterns": patterns, "order": order or list(patterns)}
    s.update(extra)
    return s


def pitch(samples, start, length):
    """Frequency from zero crossings of a stretch of a sine."""
    seg = samples[start:start + length]
    crossings = sum(1 for i in range(1, len(seg)) if (seg[i - 1] < 0) != (seg[i] < 0))
    return crossings / 2 / (length / RATE)


class ChiptuneExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, data, *args):
        path = self.dir / "song.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = chiptune.main([str(path), "--out", str(self.dir / "out.wav"), "--overwrite", *args])
        return rc, out.getvalue() + err.getvalue()

    def test_note_names(self):
        self.assertAlmostEqual(chiptune.note_freq("A4"), 440.0, places=3)
        self.assertAlmostEqual(chiptune.note_freq("C4"), 261.626, places=2)
        self.assertAlmostEqual(chiptune.note_freq("F#5"), chiptune.note_freq("Gb5"), places=6)
        self.assertAlmostEqual(chiptune.note_freq("A4", octave_shift=1), 880.0, places=3)
        self.assertIsNone(chiptune.note_freq("H4"))

    def test_notes_play_at_their_pitch_and_time(self):
        rc, out = self.render(song({"p": {"lead": "A4 - - - C5 - - - . . . . A5 - - -"}}, loop=False))
        self.assertEqual(rc, 0, out)
        s, rate, loop = read_wav(self.dir / "out.wav")
        beat = int(0.5 * rate)                         # 4 steps at 120 bpm = 0.5 s
        self.assertIsNone(loop)
        self.assertAlmostEqual(pitch(s, int(0.05 * rate), 8000), 440.0, delta=4)
        self.assertAlmostEqual(pitch(s, beat + int(0.05 * rate), 8000), 523.25, delta=5)
        silent = s[2 * beat + int(0.1 * rate): 3 * beat - 10]
        self.assertLess(max(abs(v) for v in silent), 0.01, "'.' must be silence")
        self.assertAlmostEqual(pitch(s, 3 * beat + int(0.05 * rate), 8000), 880.0, delta=8)

    def test_loop_points_cover_the_song_and_the_seam_is_clean(self):
        rc, out = self.render(song({"p": {"lead": "C5 - E5 - G5 - E5 -", "drums": "k . h . s . h ."}}))
        self.assertEqual(rc, 0, out)
        s, rate, loop = read_wav(self.dir / "out.wav")
        self.assertEqual(loop, (0, len(s) - 1))
        self.assertAlmostEqual(len(s) / rate, 1.0, places=2)   # 8 steps at 120 bpm
        self.assertTrue(stats(s, rate, loop)["loop_seam_ok"])

    def test_tie_continues_across_patterns(self):
        events, total = chiptune.events_for(chiptune.load_song(self.write(song(
            {"a": {"lead": "C4 - . ."}, "b": {"lead": "- - D4 ."}}, order=["a", "b"]))), "lead")
        self.assertEqual(total, 8)
        self.assertEqual(events, [(0, 2, "C4"), (6, 1, "D4")], "a '-' after a rest is not a tie")
        events, _ = chiptune.events_for(chiptune.load_song(self.write(song(
            {"a": {"lead": "C4 - - -"}, "b": {"lead": "- - D4 ."}}, order=["a", "b"]))), "lead")
        self.assertEqual(events[0], (0, 6, "C4"))

    def write(self, data):
        path = self.dir / "s.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_every_drum_renders(self):
        for kind in chiptune.DRUMS:
            hit = chiptune.render_drum(kind, RATE, __import__("random").Random(1))
            self.assertGreater(max(abs(v) for v in hit), 0.1, kind)
            self.assertLess(abs(hit[-1]), 0.01, f"{kind} ends with a click")

    def test_normalized_to_minus_one_dbfs(self):
        rc, out = self.render(song({"p": {"lead": "C4 E4 G4 C5", "drums": "k s h c"}}))
        self.assertEqual(rc, 0, out)
        s, rate, loop = read_wav(self.dir / "out.wav")
        self.assertAlmostEqual(stats(s, rate)["peak_dbfs"], -1.0, delta=0.15)

    def test_solo_renders_one_channel(self):
        data = song({"p": {"lead": ". . . .", "drums": "k . . ."}})
        rc, out = self.render(data, "--solo", "lead")
        self.assertEqual(rc, 1, "a silent solo is a failed render")
        rc, out = self.render(data, "--solo", "drums")
        self.assertEqual(rc, 0, out)

    def test_song_errors_say_where(self):
        bad = [
            (song({"p": {"lead": "C4 H4 . ."}}), "step 2"),
            (song({"p": {"lead": "C4 . . .", "drums": "k . x ."}}), "step 3"),
            (song({"p": {"lead": "C4 . . .", "drums": "k ."}}), "different step counts"),
            (song({"p": {"lead": "C4"}}, order=["p", "q"]), "'q'"),
            (song({"p": {"bass": "C4"}}), "'bass'"),
            (song({"p": {"lead": "C4"}}, channels={"lead": {"wave": "organ"}}), "wave must be"),
            (song({"p": {"lead": "C4"}}, channels={"lead": {"wave": "sine", "volum": 1}}), "volum"),
        ]
        for data, where in bad:
            rc, out = self.render(data)
            self.assertEqual(rc, 2, where)
            self.assertIn(where, out)

    # Regressions from Kimi's audit (2026-10-22): these crashed with a traceback instead of a song error
    def test_long_release_renders(self):
        ch = {"lead": {"wave": "sine", "volume": 0.5, "release": 3.0}}
        for loop in (True, False):
            rc, out = self.render(song({"p": {"lead": "C4 . . ."}}, channels=ch, loop=loop))
            self.assertEqual(rc, 0, out)

    def test_bad_numbers_are_song_errors(self):
        bad = [
            (song({"p": {"lead": "C4"}}, bpm="150"), "\"bpm\" must be a number"),
            (song({"p": {"lead": "C4"}}, bpm=0), "\"bpm\" must be between"),
            (song({"p": {"lead": "C4"}}, steps_per_beat=2.5), "whole number"),
            (song({"p": {"lead": "C4"}}, channels={"lead": {"wave": "sine", "release": 60}}), "release must be between"),
            (song({"p": {"lead": "C4"}}, channels={"lead": {"wave": "sine", "volume": "loud"}}), "volume must be a number"),
            (song({"p": {"lead": "C4"}}, channels={"lead": {"wave": "sine", "vibrato": [1, 5]}}), "vibrato must be"),
        ]
        for data, where in bad:
            rc, out = self.render(data)
            self.assertEqual(rc, 2, where)
            self.assertIn(where, out)
            self.assertNotIn("Traceback", out)

    def test_check_does_not_write(self):
        path = self.write(song({"p": {"lead": "C4 . . ."}}))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = chiptune.main([str(path), "--check"])
        self.assertEqual(rc, 0)
        self.assertIn("4 steps", out.getvalue())
        self.assertFalse((self.dir / "out.wav").exists())

    def test_triangle_is_stepped_like_the_nes(self):
        ch = dict(chiptune.CHANNEL_DEFAULTS, wave="triangle", sustain=1.0, decay=0.001, attack=0.0001)
        s = chiptune.render_note(ch, 110.0, RATE // 2, RATE, __import__("random").Random(1))
        levels = {round(v, 4) for v in s[1000:6000]}
        self.assertLessEqual(len(levels), 16)
        self.assertTrue(math.isclose(max(s[1000:6000]), 1.0, abs_tol=0.01))


if __name__ == "__main__":
    unittest.main(verbosity=1)
