#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_sound_sets.py
# Purpose : Exam for sound_sets.py: the code-made UI set renders the same every time and checks clean and ship-safe;
#           attack counting (one step, heel and toe, two steps, a noise floor); completeness (missing and extra takes,
#           missing sidecars); levels (bus level, spread between takes, true peak cap); loops (loop point kept by
#           leveling, missing loop point); licenses (--ship); the sets file's errors; audio_events output that
#           validates; make for both generators (local_sfx replaced by a stand-in, no GPU); out_dir never leaves
#           --root (.., absolute paths, network shares, a symlinked folder).
# Usage   : python tools/audio/wavesmith/test_sound_sets.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import math
import os
import random
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_events  # noqa: E402
import sound_sets as S  # noqa: E402
from wavfile import crossfade_loop, read_wav_channels, write_wav  # noqa: E402

RATE = 44100


def burst(seconds, at=0.0, total=0.6, floor=0.0, seed=1):
    """A footstep stand-in: decaying noise bursts starting at each time in `at`, over an optional noise floor."""
    rng = random.Random(seed)
    n = int(total * RATE)
    out = [floor * rng.uniform(-1, 1) for _ in range(n)]
    for t0 in (at if isinstance(at, (list, tuple)) else [at]):
        i0 = int(t0 * RATE)
        for i in range(int(seconds * RATE)):
            if i0 + i < n:
                out[i0 + i] += 0.5 * rng.uniform(-1, 1) * math.exp(-i / (0.02 * RATE))
    return out


class SoundSetsExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = S.main([str(a) for a in args])
        return rc, out.getvalue() + err.getvalue()

    def sets_file(self, sets, name="sets.json"):
        path = self.root / name
        path.write_text(json.dumps({"version": 1, "out_dir": "audio", "target": "home", "sets": sets}), encoding="utf-8")
        return path

    def wav(self, rel, samples, loop=None, meta=None, channels=1):
        path = self.root / "audio" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        write_wav(path, samples, RATE, loop=loop, channels=channels)
        if meta is not False:
            path.with_suffix(".gen.json").write_text(json.dumps(meta or {"tool": "local_sfx", "license": "Stability AI "
                                                                         "Community License"}), encoding="utf-8")
        return path

    def steps_set(self, takes=2, **kw):
        s = {"generator": "local_sfx", "bus": "sfx", "kind": "oneshot", "seconds": 0.6, "takes": takes, "onsets": 1,
             "prompt": "one footstep on {}", "variants": {"stone": "stone"}}
        s.update(kw)
        return {"footsteps": s}

    def leveled_steps(self, n, **kw):
        for k in range(1, n + 1):
            S.set_level(self.wav(f"footsteps/footsteps_stone_{k}.wav", burst(0.2, 0.05, seed=k), **kw), "sfx",
                        "home", "oneshot")

    # ---- the UI set
    def test_ui_set_renders_the_same_and_checks_clean_and_ship_safe(self):
        a, b = self.root / "audio" / "ui", self.root / "again"
        self.assertEqual(self.run_tool("ui", "--out", a)[0], 0)
        self.assertEqual(self.run_tool("ui", "--out", b)[0], 0)
        names = sorted(p.name for p in a.glob("*.wav"))
        self.assertEqual(len(names), len(S.UI_SET))
        for n in names:
            self.assertEqual((a / n).read_bytes(), (b / n).read_bytes(), n)
            meta = json.loads((a / n).with_suffix(".sfx.json").read_text(encoding="utf-8"))
            self.assertTrue(meta["ship_safe"])
            self.assertEqual(meta["tool"], "sfx_synth")
        sets = self.sets_file({"ui": {"generator": "sfx_synth", "bus": "ui", "takes": 1, "onsets": 1,
                                      "variants": S.UI_SET}})
        rc, out = self.run_tool("check", sets, "--root", self.root, "--ship")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"{len(S.UI_SET)} file(s) in {len(S.UI_SET)} variant(s), 0 problem(s)", out)

    # ---- attacks
    def test_attack_counting(self):
        def count(x):
            return len(S.onsets([x], RATE))
        self.assertEqual(count(burst(0.2, 0.05)), 1)
        self.assertEqual(count(burst(0.15, [0.05, 0.075])), 1)             # heel and toe, 25 ms apart: one step
        self.assertEqual(count(burst(0.15, [0.05, 0.35], total=0.7)), 2)   # two steps
        self.assertEqual(count(burst(0.15, [0.05, 0.3, 0.55], total=0.9, floor=0.002)), 3)   # over a -48 dB floor
        self.assertEqual(count([0.0] * 4410), 0)
        # a soft attack that takes 100 ms to rise (grass, gravel): it climbs through the band between the re-arm and
        # attack levels on its way up and must still count (the first version found 0 attacks in real grass takes)
        rng = random.Random(2)
        soft = [0.5 * rng.uniform(-1, 1) * min(1.0, i / (0.1 * RATE)) * math.exp(-i / (0.3 * RATE))
                for i in range(int(0.6 * RATE))]
        self.assertEqual(count(soft), 1)

    def test_attacks_closer_than_the_gap_are_one_event(self):
        heel_toe = [burst(0.05, [0.02, 0.14], total=0.5)]                  # 120 ms apart, a quiet gap between
        self.assertEqual(S.onsets(heel_toe, RATE, 0.0), [0.02, 0.14])
        self.assertEqual(S.onsets(heel_toe, RATE), [0.02])
        self.assertEqual(len(S.onsets([burst(0.12, [0.02, 0.3], total=0.6)], RATE, 0.4)), 1)   # a set can widen it
        errors = S.validate({"version": 1, "sets": self.steps_set(attack_gap_s=5)})
        self.assertTrue(any("attack_gap_s must be" in e for e in errors), errors)

    def test_a_double_step_is_reported(self):
        self.wav("footsteps/footsteps_stone_1.wav", burst(0.2, 0.05))
        self.wav("footsteps/footsteps_stone_2.wav", burst(0.15, [0.05, 0.35], total=0.7))
        for k in (1, 2):
            S.set_level(self.root / "audio" / f"footsteps/footsteps_stone_{k}.wav", "sfx", "home", "oneshot")
        rc, out = self.run_tool("check", self.sets_file(self.steps_set()), "--root", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("footsteps_stone_2.wav: 2 attacks (at 0.05, 0.35 s), expected 1", out)
        self.assertNotIn("footsteps_stone_1.wav:", out)
        rc, out = self.run_tool("check", self.sets_file(self.steps_set(attack_gap_s=0.5)), "--root", self.root)
        self.assertEqual(rc, 0, out)                                         # a set's own gap: one crunchy step

    # ---- completeness and provenance
    def test_missing_and_extra_takes_and_missing_sidecar(self):
        self.leveled_steps(2)
        self.wav("footsteps/footsteps_stone_3.wav", burst(0.2, 0.05))
        (self.root / "audio" / "footsteps" / "footsteps_stone_1.gen.json").unlink()
        rc, out = self.run_tool("check", self.sets_file(self.steps_set(takes=4)), "--root", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("missing footsteps/footsteps_stone_4.wav", out)
        self.assertIn("footsteps_stone_1.wav: no .gen.json or .sfx.json", out)
        S.set_level(self.root / "audio" / "footsteps/footsteps_stone_3.wav", "sfx", "home", "oneshot")
        rc, out = self.run_tool("check", self.sets_file(self.steps_set(takes=2)), "--root", self.root)
        self.assertIn("extra take footsteps_stone_3.wav", out)

    # ---- levels
    def test_levels_and_spread_between_takes(self):
        self.leveled_steps(2)
        rc, out = self.run_tool("check", self.sets_file(self.steps_set()), "--root", self.root)
        self.assertEqual(rc, 0, out)
        path = self.root / "audio" / "footsteps" / "footsteps_stone_2.wav"
        samples, rate, loop, ch = read_wav_channels(path)
        write_wav(path, [s * 10 ** (-5 / 20) for s in samples], rate)      # one take 5 dB quieter
        rc, out = self.run_tool("check", self.sets_file(self.steps_set()), "--root", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("takes are 5.0 LU apart (limit 3)", out)
        self.assertIn("-5.0 LU from the sfx level -30", out)

    def test_leveling_caps_true_peak_and_check_accepts_the_cap(self):
        spike = [0.0] * 4410
        spike[2000] = 0.2                                                   # one click: very peaky, very quiet
        path = self.wav("footsteps/footsteps_stone.wav", spike)
        gain, note = S.set_level(path, "sfx", "home", "oneshot")
        self.assertIn("capped by true peak", note)
        chans, rate, _ = S.read_channels(path)
        import loudness
        self.assertLessEqual(loudness.db(loudness.true_peak(chans, rate)), S.TP_CEILING + 0.01)
        facts, problems = S.check_file(path, self.steps_set(takes=1)["footsteps"], "home")
        self.assertFalse([p for p in problems if "LU from" in p], problems)

    # ---- loops
    def test_loops_keep_their_loop_point_and_need_one(self):
        rng = random.Random(4)
        noise = [0.3 * rng.uniform(-1, 1) for _ in range(6 * RATE)]
        body = crossfade_loop(noise, RATE, 1.0)
        amb = {"amb": {"generator": "local_sfx", "bus": "ambience", "kind": "loop", "seconds": 5, "takes": 1,
                       "prompt": "{}", "variants": {"rain": "rain"}}}
        path = self.wav("amb/amb_rain.wav", body, loop=(0, len(body) - 1))
        S.set_level(path, "ambience", "home", "loop")
        self.assertEqual(read_wav_channels(path)[2], (0, len(body) - 1))
        rc, out = self.run_tool("check", self.sets_file(amb), "--root", self.root)
        self.assertEqual(rc, 0, out)
        write_wav(path, read_wav_channels(path)[0], RATE)                    # the loop chunk lost
        rc, out = self.run_tool("check", self.sets_file(amb), "--root", self.root)
        self.assertIn("no loop point", out)

    # ---- licenses
    def test_ship_refuses_files_whose_license_is_not_cleared(self):
        self.leveled_steps(2)
        sets = self.sets_file(self.steps_set())
        self.assertEqual(self.run_tool("check", sets, "--root", self.root)[0], 0)
        rc, out = self.run_tool("check", sets, "--root", self.root, "--ship")
        self.assertEqual(rc, 1)
        self.assertIn("not ship-safe (Stability AI Community License)", out)

    # ---- the sets file
    def test_values_of_the_wrong_type_are_problems_not_crashes(self):
        ok = {"generator": "sfx_synth", "bus": "ui", "variants": {"soft": S.UI_SET["click"]}}
        for bad in ("x", [1], 3, None, True):
            for data, word in (({"version": 1, "target": [bad], "sets": {"s": ok}}, "target"),
                               ({"version": 1, "sets": {"s": dict(ok, bus=[bad])}}, "bus"),
                               ({"version": 1, "sets": {"s": dict(ok, event=bad)}}, "event"),
                               ({"version": 1, "sets": {"s": dict(ok, variants=bad)}}, "variants")):
                problems = S.validate(data)                          # must not raise
                self.assertTrue(problems and any(word in p for p in problems), f"{data}: {problems}")

    def test_errors_are_named(self):
        bad = {"x": {"generator": "magic", "bus": "sfx", "variants": {"a": "b"}},
               "y": {"generator": "local_sfx", "bus": "sfx", "seconds": 1, "prompt": "no slot", "variants": {"a": "b"}},
               "z": {"generator": "sfx_synth", "bus": "ui", "kind": "loop", "variants": {"a": {"wobble": 1}}},
               "Bad": {"generator": "sfx_synth", "bus": "nowhere", "takes": 0, "variants": {}}}
        errors = S.validate({"version": 1, "sets": bad})
        text = "\n".join(errors)
        for want in ("set x: generator must be", "set y: prompt must contain {} once", "set z: sfx_synth makes one-shots",
                     "set z variant a: unknown parameter(s): wobble", "set Bad: name must be", "set Bad: bus must be",
                     "set Bad: takes must be", "set Bad: variants must be"):
            self.assertIn(want, text)
        self.assertEqual(self.run_tool("plan", self.sets_file(bad))[0], 2)

    # ---- audio events
    def test_events_validate_and_merge_safely(self):
        sets = self.sets_file(dict(self.steps_set(event={"pitch_semitones": [-1, 1], "caption": "[steps on {variant}]"}),
                                   amb={"generator": "local_sfx", "bus": "ambience", "kind": "loop", "seconds": 5,
                                        "prompt": "{}", "variants": {"night_meadow": "crickets"},
                                        "event": {"caption": "[{variant}]"}}))
        events = S.events_for(S.load_sets(sets), "audio")
        self.assertEqual(events["footsteps_stone"]["files"],
                         ["footsteps/footsteps_stone_1.wav", "footsteps/footsteps_stone_2.wav"])
        self.assertEqual(events["footsteps_stone"]["pick"], "random_no_repeat")
        self.assertEqual(events["footsteps_stone"]["caption"], "[steps on stone]")
        self.assertEqual(events["amb_night_meadow"], {"bus": "ambience", "files": ["amb/amb_night_meadow.wav"],
                                                      "max_voices": 1, "caption": "[night meadow]"})
        target = self.root / "audio_events.json"
        target.write_text(json.dumps({"version": 1, "seed": 1, "buses": {"master": {}, "sfx": {"parent": "master"},
                                      "ambience": {"parent": "master"}},
                                      "events": {"amb_night_meadow": {"bus": "sfx", "files": ["x.wav"]}}}),
                          encoding="utf-8")
        before = target.read_bytes()
        rc, out = self.run_tool("events", sets, "--root", "audio", "--merge", target)
        self.assertEqual(rc, 2)
        self.assertIn("already has amb_night_meadow", out)
        self.assertEqual(target.read_bytes(), before)
        rc, out = self.run_tool("events", sets, "--root", "audio", "--merge", target, "--overwrite")
        self.assertEqual(rc, 0, out)
        self.assertEqual(audio_events.validate(json.loads(target.read_text(encoding="utf-8"))), [])
        ui = self.sets_file({"ui": {"generator": "sfx_synth", "bus": "ui", "variants": {"click": S.UI_SET["click"]}}},
                            "ui_sets.json")
        before = target.read_bytes()
        rc, out = self.run_tool("events", ui, "--merge", target)               # the file has no ui bus
        self.assertEqual(rc, 2)
        self.assertIn("would not validate", out)
        self.assertEqual(target.read_bytes(), before)

    # ---- make
    def test_make_with_sfx_synth_takes(self):
        sets = self.sets_file({"blips": {"generator": "sfx_synth", "bus": "ui", "takes": 3, "onsets": 1,
                                         "variants": {"soft": S.UI_SET["click"]}}})
        rc, out = self.run_tool("make", sets, "--root", self.root)
        self.assertEqual(rc, 0, out)
        files = [self.root / "audio" / "blips" / f"blips_soft_{k}.wav" for k in (1, 2, 3)]
        self.assertEqual(len({f.read_bytes() for f in files}), 3)            # three different takes
        rc, out = self.run_tool("check", sets, "--root", self.root, "--ship")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.run_tool("make", sets, "--root", self.root)[0], 1)   # exists: refused, not replaced

    def test_out_dir_never_leaves_the_root(self):
        proj = self.root / "proj"
        proj.mkdir()
        blips = {"blips": {"generator": "sfx_synth", "bus": "ui", "variants": {"soft": S.UI_SET["click"]}}}
        outside = self.root / "escape_dir"
        for bad in ("../escape_dir", str(outside), "a/../../escape_dir", "//host/share", "C:/escape_dir"):
            f = self.root / "bad_sets.json"
            f.write_text(json.dumps({"version": 1, "out_dir": bad, "sets": blips}), encoding="utf-8")
            for cmd in ("make", "check"):
                rc, out = self.run_tool(cmd, f, "--root", proj)
                self.assertEqual(rc, 2, f"{cmd} {bad}: {out}")
                self.assertIn("out_dir", out)
            self.assertFalse(outside.exists(), f"{bad} wrote outside the root")
        self.assertTrue(any("climbs out" in e for e in S.validate({"version": 1, "out_dir": "../x", "sets": blips})))
        try:                                        # a folder inside the root that is a link to somewhere outside
            outside.mkdir()
            os.symlink(outside, proj / "linked", target_is_directory=True)
        except (OSError, NotImplementedError):
            return                                  # no symlink rights here (Windows without developer mode)
        f = self.root / "link_sets.json"
        f.write_text(json.dumps({"version": 1, "out_dir": "linked", "sets": blips}), encoding="utf-8")
        rc, out = self.run_tool("make", f, "--root", proj)
        self.assertEqual(rc, 2, out)
        self.assertIn("outside the project root", out)
        self.assertEqual(list(outside.iterdir()), [])

    def test_make_with_local_sfx_calls_it_right_and_levels_its_output(self):
        calls = []

        def fake_main(argv):                                                 # stands in for the GPU
            calls.append(argv)
            out = Path(argv[argv.index("--out") + 1])
            keep = int(argv[argv.index("--keep") + 1])
            for k in range(1, keep + 1):
                p = out if keep == 1 else out.with_name(f"{out.stem}_{k}{out.suffix}")
                body = crossfade_loop(burst(0.3, 0.0, total=6.0, floor=0.05, seed=k), RATE, 1.0)
                write_wav(p, body, RATE, loop=(0, len(body) - 1) if "--loop" in argv else None)
                p.with_suffix(".gen.json").write_text(json.dumps({"tool": "local_sfx", "license": "Stability"}),
                                                      encoding="utf-8")
            return 0
        sys.modules["local_sfx"] = types.SimpleNamespace(main=fake_main)
        try:
            sets = self.sets_file({"amb": {"generator": "local_sfx", "bus": "ambience", "kind": "loop", "seconds": 5,
                                           "takes": 2, "mono": True, "prompt": "{}, ambience",
                                           "variants": {"rain": "steady rain"}}})
            rc, out = self.run_tool("make", sets, "--root", self.root, "--seed", 7)
        finally:
            del sys.modules["local_sfx"]
        self.assertEqual(rc, 0, out)
        argv = calls[0]
        self.assertEqual(argv[:2], ["make", "steady rain, ambience"])
        for flag, value in (("--seconds", "5"), ("--variants", "4"), ("--keep", "2"), ("--seed", "7")):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        self.assertIn("--loop", argv)
        self.assertIn("--mono", argv)
        for k in (1, 2):
            path = self.root / "audio" / "amb" / f"amb_rain_{k}.wav"
            self.assertIsNotNone(read_wav_channels(path)[2])                  # loop point survived leveling
            lufs, how = S.level(*S.read_channels(path)[:2], "loop")
            self.assertEqual(how, "integrated")
            self.assertAlmostEqual(lufs, -34.0, delta=0.1)

    def test_make_keeps_one_shots_with_the_right_number_of_attacks(self):
        # renders ranked 1..6 by local_sfx; 1, 3 and 4 are double steps: the set must keep 2, 5 (and flag nothing)
        doubles = {1, 3, 4}

        def fake_main(argv):
            out = Path(argv[argv.index("--out") + 1])
            keep = int(argv[argv.index("--keep") + 1])
            self.assertEqual(keep, int(argv[argv.index("--variants") + 1]))      # every render comes back
            for k in range(1, keep + 1):
                p = out.with_name(f"{out.stem}_{k}{out.suffix}")
                at = [0.05, 0.35] if k in doubles else 0.05
                write_wav(p, burst(0.15, at, total=0.7, seed=k), RATE)
                p.with_suffix(".gen.json").write_text(json.dumps({"tool": "local_sfx", "license": "L", "rank": k}),
                                                      encoding="utf-8")
            return 0
        sys.modules["local_sfx"] = types.SimpleNamespace(main=fake_main)
        try:
            sets = self.sets_file(self.steps_set(takes=2, renders=6))
            rc, out = self.run_tool("make", sets, "--root", self.root)
            self.assertEqual(rc, 0, out)
            self.assertIn("[pick] 3 of 6 render(s) have 1 attack(s); kept 2 of those", out)
            folder = self.root / "audio" / "footsteps"
            ranks = [json.loads((folder / f"footsteps_stone_{k}.gen.json").read_text(encoding="utf-8"))["rank"]
                     for k in (1, 2)]
            self.assertEqual(ranks, [2, 5])                                     # the best single steps, in rank order
            self.assertEqual(sorted(p.name for p in folder.glob("*.wav")), ["footsteps_stone_1.wav",
                                                                           "footsteps_stone_2.wav"])
            self.assertEqual(self.run_tool("check", sets, "--root", self.root)[0], 0)
            doubles.update({2, 5, 6})                                           # now every render is a double step
            rc, out = self.run_tool("make", sets, "--root", self.root, "--overwrite")
            self.assertIn("kept 0 of those and 2 that check will flag", out)
            self.assertEqual(self.run_tool("check", sets, "--root", self.root)[0], 1)
        finally:
            del sys.modules["local_sfx"]

    def test_docs_example_validates(self):
        doc = (Path(__file__).resolve().parents[3] / "docs" / "resources" / "audio.md").read_text(encoding="utf-8")
        section = doc.split("## Sound sets", 1)[1]
        example = json.loads(section.split("```json", 1)[1].split("```", 1)[0])
        self.assertEqual(S.validate(example), [])
        events = S.events_for(example, example["out_dir"])
        buses = {"master": {}, **{b: {"parent": "master"} for b in ("sfx", "ambience", "ui", "music", "dialogue")}}
        self.assertEqual(audio_events.validate({"version": 1, "seed": 1, "buses": buses, "events": events}), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
