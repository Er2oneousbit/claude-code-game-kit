#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_audio_events.py
# Purpose : Exam for audio_events.py: the random source is the published Park-Miller generator, the director's
#           rules hold (no back-to-back repeats, shuffle rounds, cooldowns, voice caps, ducking ramps, time order),
#           validate catches each kind of broken events file, audit warns about repetition, loud takes and missing
#           captions, and data/golden/audio.json is current.
# Usage   : python tools/audio/wavesmith/test_audio_events.py
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
import audio_events as AE  # noqa: E402
from wavfile import write_wav  # noqa: E402

GOOD = {
    "version": 1,
    "seed": 1,
    "buses": {"master": {}, "music": {"parent": "master", "volume_db": -4}, "sfx": {"parent": "master"},
              "ui": {"parent": "master"}, "dialogue": {"parent": "master"}},
    "ducking": [{"trigger": "dialogue", "targets": ["music"], "depth_db": -8, "attack_ms": 80, "release_ms": 400}],
    "events": {
        "step_stone": {"bus": "sfx", "files": ["s1.wav", "s2.wav", "s3.wav"], "pitch_semitones": [-1, 1],
                       "volume_db": [-3, 0], "pick": "random_no_repeat", "max_voices": 4, "cooldown_ms": 60,
                       "caption": "[footsteps]"},
        "click": {"bus": "ui", "files": ["click.wav"]},
    },
}


def director(events, seed=1, ducking=None):
    return AE.Director({"seed": seed, "events": events, "ducking": ducking or []})


class AudioEventsExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = AE.main([str(a) for a in args])
        return rc, out.getvalue() + err.getvalue()

    def test_values_of_the_wrong_type_are_problems_not_crashes(self):
        good = {"version": 1, "seed": 1, "buses": {"master": {}, "sfx": {"parent": "master"}},
                "events": {"hit": {"bus": "sfx", "files": ["a.wav"]}}}
        self.assertEqual(AE.validate(good), [])
        for bad in ("x", [1], 3, None, True):
            for change, word in (({"buses": {"master": {}, "sfx": bad}}, "bus sfx"), ({"buses": bad}, "bus"),
                                 ({"events": {"hit": bad}}, "event hit"), ({"events": bad}, "events"),
                                 ({"ducking": bad}, "ducking"), ({"ducking": [bad]}, "ducking[0]"),
                                 ({"events": {"hit": {"bus": [bad], "files": ["a.wav"]}}}, "bus")):
                problems = AE.validate(dict(good, **change))        # must not raise
                self.assertTrue(problems and any(word in p for p in problems), f"{change}: {problems}")
        self.assertEqual(AE.validate(["not", "an", "object"])[0][:30], "the file must hold one JSON ob")

    # ---- the random source
    def test_park_miller_matches_the_published_check_value(self):
        # Park and Miller (1988): seeded with 1, the state after 10000 steps is 1043618065
        r = AE.Rng(1)
        for _ in range(10000):
            r.next()
        self.assertEqual(r.s, 1043618065)

    def test_event_seed_is_stable_and_never_zero(self):
        self.assertEqual(AE.event_seed("step_stone", 1), AE.event_seed("step_stone", 1))
        self.assertNotEqual(AE.event_seed("step_stone", 1), AE.event_seed("step_stone", 2))
        self.assertGreater(AE.event_seed("", 0), 0)

    # ---- director rules
    def test_no_repeat_never_plays_the_same_file_twice_in_a_row(self):
        d = director({"e": {"bus": "sfx", "files": ["a", "b", "c"], "lengths_ms": [10, 10, 10]}})
        picks = [d.play("e", t * 100)["variant"] for t in range(300)]
        self.assertTrue(all(a != b for a, b in zip(picks, picks[1:])))
        self.assertEqual(set(picks), {0, 1, 2})

    def test_shuffle_plays_every_file_once_per_round(self):
        d = director({"e": {"bus": "sfx", "files": list("abcde"), "lengths_ms": [10] * 5, "pick": "shuffle"}})
        picks = [d.play("e", t * 100)["variant"] for t in range(50)]
        for r in range(10):
            self.assertEqual(sorted(picks[r * 5:(r + 1) * 5]), [0, 1, 2, 3, 4])
        self.assertTrue(all(a != b for a, b in zip(picks, picks[1:])), "no repeat across a refill")

    def test_ranges_are_respected(self):
        d = director({"e": {"bus": "sfx", "files": ["a", "b"], "lengths_ms": [10, 10], "pitch_semitones": [-2, 3],
                            "volume_db": [-6, -1]}})
        for t in range(200):
            r = d.play("e", t * 50)
            self.assertTrue(-2 <= r["pitch_semitones"] <= 3 and -6 <= r["gain_db"] <= -1)
            self.assertAlmostEqual(r["pitch_ratio"], 2 ** (r["pitch_semitones"] / 12))

    def test_cooldown_rejects_without_drawing(self):
        ev = {"bus": "sfx", "files": ["a", "b", "c"], "lengths_ms": [10] * 3, "cooldown_ms": 100,
              "pitch_semitones": [-1, 1]}
        a, b = director({"e": ev}), director({"e": ev})
        self.assertEqual(a.play("e", 0)["result"], "played")
        self.assertEqual(a.play("e", 50), {"result": "cooldown"})
        b.play("e", 0)
        self.assertEqual(a.play("e", 200), b.play("e", 200), "a rejected play must not consume randomness")

    def test_voice_cap_steals_the_oldest_or_refuses(self):
        ev = {"bus": "sfx", "files": ["a"], "lengths_ms": [1000], "max_voices": 2}
        d = director({"e": dict(ev, steal="oldest")})
        ids = [d.play("e", t)["voice"] for t in (0, 10)]
        third = d.play("e", 20)
        self.assertEqual((third["result"], third["stolen"]), ("played", ids[0]))
        d = director({"e": dict(ev, steal="none")})
        d.play("e", 0)
        d.play("e", 10)
        self.assertEqual(d.play("e", 20), {"result": "capped"})
        self.assertEqual(d.play("e", 1000)["result"], "played", "the first voice ended at 1000 ms")

    def test_ducking_ramps_are_straight_lines_in_db(self):
        d = director({"line": {"bus": "dialogue", "files": ["l"], "lengths_ms": [1000]}},
                     ducking=[{"trigger": "dialogue", "targets": ["music", "amb"], "depth_db": -10,
                               "attack_ms": 100, "release_ms": 500}])
        d.play("line", 0)
        self.assertEqual(d.duck(25), {"music": -2.5, "amb": -2.5})
        self.assertEqual(d.duck(500)["music"], -10)
        self.assertAlmostEqual(d.duck(1250)["music"], -5.0)
        self.assertEqual(d.duck(2000)["music"], 0.0)

    def test_instant_attack_and_release(self):
        d = director({"line": {"bus": "dialogue", "files": ["l"], "lengths_ms": [300]}},
                     ducking=[{"trigger": "dialogue", "targets": ["music"], "depth_db": -6, "attack_ms": 0,
                               "release_ms": 0}])
        d.play("line", 0)
        self.assertEqual(d.duck(1)["music"], -6)
        self.assertEqual(d.duck(301)["music"], 0.0)

    def test_history_is_pruned_without_changing_results(self):
        ev = {"line": {"bus": "dialogue", "files": ["l"], "lengths_ms": [100]},
              "step": {"bus": "sfx", "files": ["a", "b"], "lengths_ms": [50, 50]}}
        rule = [{"trigger": "dialogue", "targets": ["music"], "depth_db": -6, "attack_ms": 40, "release_ms": 200}]
        d = director(ev, ducking=rule)
        for t in range(0, 20000, 250):
            d.play("line", t)
            d.play("step", t + 10)
            d.duck(t + 200)
        self.assertLessEqual(len(d.history), 1, "only voices still able to matter are kept")
        self.assertFalse(any(v["bus"] == "sfx" for v in d.history), "non-trigger buses are never kept")

    def test_calls_out_of_time_order_are_refused(self):
        d = director({"e": {"bus": "sfx", "files": ["a"], "lengths_ms": [10]}})
        d.play("e", 100)
        with self.assertRaises(ValueError):
            d.play("e", 50)

    # ---- validate
    def test_good_file_validates(self):
        f = self.dir / "ev.json"
        f.write_text(json.dumps(GOOD), encoding="utf-8")
        rc, out = self.run_tool("validate", f)
        self.assertEqual(rc, 0, out)

    def test_each_kind_of_broken_file_is_named(self):
        def broken(edit):
            data = copy.deepcopy(GOOD)
            edit(data)
            return AE.validate(data)
        cases = [
            (lambda d: d["buses"].pop("master"), "'master' bus is required"),
            (lambda d: d["buses"]["sfx"].update(parent="nowhere"), "parent 'nowhere'"),
            (lambda d: d["buses"].update(a={"parent": "b"}, b={"parent": "a"}), "parent loop"),
            (lambda d: d["ducking"][0].update(targets=["nope"]), "target 'nope'"),
            (lambda d: d["ducking"][0].update(depth_db=3), "depth_db"),
            (lambda d: d["events"].update({"Pas de géant": d["events"]["click"]}), "lowercase ASCII"),
            (lambda d: d["events"]["click"].update(pick="loudest"), "pick must be"),
            (lambda d: d["events"]["click"].update(pitch_semitones=[2, -2]), "pitch_semitones"),
            (lambda d: d["events"]["click"].update(files=["click.txt"]), "not an audio file"),
            (lambda d: d["events"]["click"].update(bus="voices"), "bus 'voices'"),
            (lambda d: d["events"]["click"].update(max_voices=0), "max_voices"),
            (lambda d: d.update(seed=-5), "seed must be a whole number"),
            (lambda d: d.update(seed=1.5), "seed must be a whole number"),
            (lambda d: d["events"]["click"].update(pick=None), "pick is null"),
            (lambda d: d["events"]["click"].update(directional="yes"), "directional must be true or false"),
        ]
        for edit, words in cases:
            problems = broken(edit)
            self.assertTrue(any(words in p for p in problems), f"{words}: {problems}")

    def test_missing_files_found_with_root(self):
        f = self.dir / "ev.json"
        f.write_text(json.dumps(GOOD), encoding="utf-8")
        rc, out = self.run_tool("validate", f, "--root", self.dir)
        self.assertEqual(rc, 1, out)
        self.assertIn("s1.wav not found", out)

    def test_the_docs_example_validates(self):
        # the JSON shown in docs/resources/audio.md ("Sound events") must stay a valid events file
        doc = (Path(__file__).resolve().parents[3] / "docs" / "resources" / "audio.md").read_text(encoding="utf-8")
        section = doc[doc.index("## Sound events"):]
        block = section[section.index("```json") + 7:section.index("```", section.index("```json") + 7)]
        data = json.loads(block)
        self.assertEqual(AE.validate(data), [])
        self.assertEqual(AE.audit(data), [], "the example should model good practice")

    # ---- audit
    def test_audit_warns_about_repetition_random_picks_and_captions(self):
        data = copy.deepcopy(GOOD)
        data["events"]["hit"] = {"bus": "sfx", "files": ["h.wav"], "pick": "random"}
        data["events"]["swing"] = {"bus": "sfx", "files": ["a.wav", "b.wav"], "pick": "random", "caption": "[whoosh]"}
        warnings = AE.audit(data)
        self.assertTrue(any("hit: 1 file(s) and no pitch range" in w for w in warnings), warnings)
        self.assertTrue(any("swing: pick random can repeat" in w for w in warnings), warnings)
        self.assertTrue(any("hit: no caption" in w for w in warnings), warnings)
        self.assertFalse(any(w.startswith("click:") for w in warnings), "UI sounds need no caption or variants")

    def test_audit_lets_looped_beds_be_one_file(self):
        data = copy.deepcopy(GOOD)
        data["events"]["rain"] = {"bus": "ambience", "files": ["rain.wav"], "max_voices": 1, "caption": "[rain]"}
        tone = [0.2 * math.sin(2 * math.pi * 220 * i / 48000) for i in range(48000)]
        write_wav(self.dir / "rain.wav", tone, 48000)                        # no loop point: a one-shot
        self.assertTrue(any(w.startswith("rain: 1 file(s)") for w in AE.audit(data, self.dir)))
        write_wav(self.dir / "rain.wav", tone, 48000, loop=(0, 47999))       # a bed that loops
        self.assertFalse(any(w.startswith("rain:") for w in AE.audit(data, self.dir)))
        self.assertTrue(any(w.startswith("rain: 1 file(s)") for w in AE.audit(data)), "without --root it cannot know")

    def test_audit_measures_loudness_spread_between_takes(self):
        data = copy.deepcopy(GOOD)
        rate = 48000
        for name, db in (("s1.wav", -20), ("s2.wav", -21), ("s3.wav", -30)):
            a = 10 ** (db / 20)
            write_wav(self.dir / name, [a * math.sin(2 * math.pi * 1000 * i / rate) for i in range(rate)], rate)
        warnings = AE.audit(data, self.dir)
        self.assertTrue(any("step_stone: its files differ by 10.0 LU" in w for w in warnings), warnings)
        f = self.dir / "ev.json"
        f.write_text(json.dumps(data), encoding="utf-8")
        rc, out = self.run_tool("audit", f, "--root", self.dir, "--strict")
        self.assertEqual(rc, 1, out)

    # ---- golden vectors
    def test_golden_file_is_current_and_stale_is_caught(self):
        rc, out = self.run_tool("vectors", "--check")
        self.assertEqual(rc, 0, out)
        stale = self.dir / "audio.json"
        current = AE.render(AE.build_vectors())
        self.assertIn('"version": 1', current)
        stale.write_text(current.replace('"version": 1', '"version": 0', 1), encoding="utf-8")
        rc, out = self.run_tool("vectors", "--check", "--out", stale)
        self.assertEqual(rc, 1, out)

    def test_usage(self):
        rc, out = self.run_tool("vectors")
        self.assertEqual(rc, 2, out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
