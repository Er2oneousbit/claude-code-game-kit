#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_music.py
# Purpose : Exam for music.py: the sample grid (half rounds up), bar-aligned loops with the tail folded back and a
#           loop chunk on the grid, boundaries for every quantize (with an intro and loop wrap), the transition map's
#           rule order, fades, stingers and synced entries, stem and file validation, the tempo estimate, the golden
#           vectors being current, and the command line.
# Usage   : python tools/audio/test_music.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import copy
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import music as M  # noqa: E402
from wavfile import read_wav_channels, write_wav  # noqa: E402

RATE = 44100
MUSIC = {"version": 1, "sample_rate": RATE, "start": "explore",
         "tracks": {"explore": {"bpm": 96, "bars": 2, "stems": {"pads": "explore_pads.wav", "drums": "explore_drums.wav"}},
                    "combat": {"bpm": 96, "bars": 1, "stems": {"full": "combat.wav"}}},
         "stingers": {"alarm": {"file": "alarm.wav", "bars": 1}},
         "transitions": [{"from": "explore", "to": "combat", "quantize": "beat", "sync": True},
                         {"from": "combat", "to": "explore", "quantize": "bar", "fade_ms": 500, "stinger": "alarm"}]}


def clicks(bpm, seconds, rate=RATE, every=1):
    """A click on every `every`-th beat: 5 ms decaying bursts."""
    x = [0.0] * int(seconds * rate)
    k = 0
    while True:
        s = M.beat_sample(k * every, bpm, rate)
        if s >= len(x):
            return x
        for i in range(int(0.005 * rate)):
            if s + i < len(x):
                x[s + i] = 0.8 * math.sin(2 * math.pi * 2000 * i / rate) * (1 - i / (0.005 * rate))
        k += 1


class MusicExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = M.main([str(a) for a in args])
        return rc, out.getvalue() + err.getvalue()

    def stems(self, data, frames=None, loop=True):
        for t in data["tracks"].values():
            start, end = M.loop_points(t, RATE)
            for f in t["stems"].values():
                write_wav(self.dir / f, [0.1] * (frames or end), RATE, loop=(start, end - 1) if loop else None)
        for s in data["stingers"].values():
            write_wav(self.dir / s["file"], [0.1] * RATE, RATE)

    # ---- grid
    def test_grid_rounds_halves_up_in_samples(self):
        self.assertEqual(M.beat_sample(1, 96, 44100), 27563)              # 27562.5: Python's round() would say 27562
        self.assertEqual(M.beat_sample(3, 96, 44100), 82688)              # 82687.5
        self.assertEqual(M.beat_sample(64, 96, 44100), 1764000)           # 16 bars are exactly 40 s
        self.assertEqual(M.bar_sample(1, {"bpm": 137.5, "beats_per_bar": 3}, 44100), 57731)
        t = {"bpm": 96, "beats_per_bar": 4}
        for s in (0, 110249, 110250, 110251, 999999):
            b = M.bar_index_at(s, t, RATE)
            self.assertLessEqual(M.bar_sample(b, t, RATE), s)
            self.assertGreater(M.bar_sample(b + 1, t, RATE), s)

    # ---- loops
    def test_loop_is_exactly_n_bars_with_the_tail_folded_onto_the_start(self):
        end = M.beat_sample(8, 96, RATE)                                   # 2 bars
        src = [0.0] * (end + 2000)
        src[100], src[end + 100] = 0.25, 0.5                               # a note, and ring-out past the loop end
        body, loop = M.make_loop(src, RATE, 1, 96, 2)
        self.assertEqual(len(body), end)
        self.assertEqual(loop, (0, end - 1))
        self.assertAlmostEqual(body[100], 0.75)                            # the tail lands on the start
        stereo = [v for x in src for v in (x, -x)]
        body2, _ = M.make_loop(stereo, RATE, 2, 96, 2)
        self.assertAlmostEqual(body2[201], -0.75)                          # per channel
        with self.assertRaises(M.ToolError):
            M.make_loop(src[:end - 1], RATE, 1, 96, 2)
        f = self.dir / "raw.wav"
        write_wav(f, src, RATE)
        rc, out = self.run_tool("loop", f, "--bpm", 96, "--bars", 2, "--out", self.dir / "loop.wav")
        self.assertEqual(rc, 0, out)
        samples, rate, lp, ch = read_wav_channels(self.dir / "loop.wav")
        self.assertEqual((len(samples), lp), (end, (0, end - 1)))

    # ---- boundaries and plans
    def test_boundaries_for_every_quantize_with_an_intro(self):
        t = {"bpm": 120, "beats_per_bar": 4, "bars": 4, "loop_start_bar": 1}   # 1 bar intro, loop bars 2-4
        bar = M.bar_sample(1, t, RATE)                                      # 88200
        self.assertEqual(M.next_boundary(t, RATE, 1000, "immediate"), 1000)
        self.assertEqual(M.next_boundary(t, RATE, 1000, "beat"), 22050)
        self.assertEqual(M.next_boundary(t, RATE, 22050, "beat"), 22050)   # on a boundary: now
        self.assertEqual(M.next_boundary(t, RATE, 1000, "bar"), bar)
        self.assertEqual(M.next_boundary(t, RATE, bar + 1, "phrase", phrase_bars=2), 2 * bar)
        self.assertEqual(M.next_boundary(t, RATE, 5, "loop_end"), 4 * bar)
        self.assertEqual(M.next_boundary(t, RATE, 3 * bar + 5, "phrase", phrase_bars=8), 4 * bar)   # never past end
        self.assertEqual(M.position(t, RATE, 0, 4 * bar), bar)             # the loop end wraps to bar 2, not bar 1
        self.assertEqual(M.position(t, RATE, 0, 7 * bar + 7), bar + 7)

    def test_rule_order_fades_stingers_and_sync(self):
        d = copy.deepcopy(MUSIC)
        d["transitions"].append({"from": "*", "to": "combat", "quantize": "immediate"})
        d["default_transition"] = {"quantize": "bar", "fade_ms": 250}
        self.assertEqual(M.rule_for(d, "explore", "combat")["quantize"], "beat")   # the exact pair wins over *
        r = M.plan(d, "explore", 0, 0, "combat", 30000)                      # beat 2 of bar 1
        self.assertEqual((r["switch_at"], r["to_offset"], r["fade"]), (M.beat_sample(2, 96, RATE),
                                                                       M.beat_sample(2, 96, RATE), 11025))
        r = M.plan(d, "combat", 0, 0, "explore", 1000)                       # stinger: explore enters a bar later
        bar = M.bar_sample(1, d["tracks"]["combat"], RATE)
        self.assertEqual((r["switch_at"], r["stinger_at"], r["to_start_at"], r["fade"]), (bar, bar, 2 * bar, 22050))
        d["tracks"]["combat"]["bpm"] = 100                                    # grids differ: no synced entry
        self.assertEqual(M.plan(d, "explore", 0, 0, "combat", 30000)["to_offset"], 0)

    # ---- validate
    def test_good_music_validates_with_its_files(self):
        self.stems(MUSIC)
        rc, out = self.run_tool("validate", self.write(MUSIC), "--root", self.dir)
        self.assertEqual(rc, 0, out)

    def write(self, data, name="music.json"):
        p = self.dir / name
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_stem_problems_are_named(self):
        self.stems(MUSIC)
        start, end = M.loop_points(MUSIC["tracks"]["explore"], RATE)
        write_wav(self.dir / "explore_drums.wav", [0.1] * (end + 10), RATE, loop=(start, end - 1))
        write_wav(self.dir / "combat.wav", [0.1] * 100, 48000, loop=(0, 50))
        problems = "\n".join(M.validate(MUSIC, self.dir))
        for words in ("stem drums: 44100 Hz, 1 channel(s), 220510 samples differs from stem pads",
                      "track combat stem full: 48000 Hz, the music runs at 44100 Hz",
                      "track combat stem full: 100 samples, the loop needs",
                      "is off the bar grid"):
            self.assertIn(words, problems)
        write_wav(self.dir / "explore_pads.wav", [0.1] * end, RATE)
        self.assertIn("stem pads: no loop point", "\n".join(M.validate(MUSIC, self.dir)))

    def test_map_problems_are_named(self):
        d = copy.deepcopy(MUSIC)
        d["transitions"] += [{"from": "nowhere", "to": "combat"}, {"from": "*", "to": "explore", "quantize": "soon"},
                             {"from": "*", "to": "combat", "stinger": "boom"},
                             {"from": "*", "to": "combat", "stinger": "alarm", "sync": True}]
        d["stingers"]["long"] = {"file": "l.wav", "bars": 99}
        d["tracks"]["bad"] = {"bpm": 5, "bars": 1, "stems": {"a": "a.wav"}}
        d["start"] = "title"
        text = "\n".join(M.validate(d))
        for words in ("from must be a track name", "quantize must be one of", "stinger 'boom' is not in stingers",
                      "a stinger and sync do not combine", "stinger long: bars must be", "track bad: bpm must be",
                      "start 'title' is not a track"):
            self.assertIn(words, text)
        self.assertEqual(M.validate({"version": 2}), ["version must be 1"])

    # ---- tempo
    def test_tempo_estimate_finds_the_beat(self):
        for bpm in (96, 120, 140):
            bpm_est, conf = M.tempo(clicks(bpm, 8), RATE, 1)
            self.assertAlmostEqual(bpm_est, bpm, delta=1.0, msg=f"{bpm}")
            self.assertGreater(conf, 0.3)
        with self.assertRaises(M.ToolError):
            M.tempo([0.0] * RATE, RATE, 1)

    def test_docs_example_validates_and_plans(self):
        doc = (Path(__file__).resolve().parents[2] / "docs" / "resources" / "audio.md").read_text(encoding="utf-8")
        example = json.loads(doc.split("## Adaptive music", 1)[1].split("```json", 1)[1].split("```", 1)[0])
        self.assertEqual(M.validate(example), [])
        r = M.plan(example, "combat", 0, 0, "explore", 1000)
        self.assertEqual((r["stinger"], r["fade"]), ("alarm", 22050))

    # ---- golden vectors and the command line
    def test_golden_vectors_are_current_and_exact(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(M.cmd_vectors(type("A", (), {"write": False})()), 0)
        data = json.loads(M.GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(data["tolerance"], 0)
        types = {c["type"] for c in data["cases"]}
        self.assertEqual(types, {"music_grid", "music_plan"})

    def test_cli_plan_grid_and_errors(self):
        f = self.write(MUSIC)
        rc, out = self.run_tool("plan", f, "--from", "combat", "--to", "explore", "--at", "0.1")
        self.assertEqual(rc, 0, out)
        self.assertEqual(json.loads(out)["seconds"]["switch_at"], 2.5)
        rc, out = self.run_tool("grid", "--bpm", 120, "--bars", 2)
        self.assertIn("bar   2:    2.0000 s  sample 88200", out)
        for args in (("plan", f, "--from", "x", "--to", "combat", "--at", 0), ("validate", self.dir / "none.json"),
                     ("loop", self.dir / "none.wav", "--bpm", 90, "--bars", 1, "--out", self.dir / "o.wav")):
            rc, out = self.run_tool(*args)
            self.assertEqual(rc, 2, f"{args}: {out}")
            self.assertNotIn("Traceback", out)
        rc, out = self.run_tool("validate", self.write({"version": 1, "sample_rate": RATE, "tracks": {}}))
        self.assertEqual(rc, 1, out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
