#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_seed_sweep.py
# Purpose : Exam for tools/seed_sweep.py (#183): the seed x setting matrix, placeholders, the first run alone and the
#           rest in parallel with --no-build and a data folder each, outcomes and numbers read from the game's lines
#           (not dev.py's own), pass rates per setting, --min-pass, --spec, --json, timeouts, Unity's one-at-a-time
#           rule and the stop on a first run that cannot start.
# Usage   : python core/tools/test_seed_sweep.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only, offline. Each case builds a fake game folder: tools/seed_sweep.py (the real one)
#           and a fake tools/dev.py whose smoke "plays" from its arguments (reckless bots lose on odd seeds), logs
#           every call with its start and end time, and answers `smoke -h` with or without --no-build / --data-dir.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE / "seed_sweep.py"

FAKE_DEV = r'''
import json, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
argv = sys.argv[1:]
if argv[-1:] == ["-h"]:
    flags = "" if os.environ.get("FAKE_NO_FLAGS") else "  --no-build  skip the build\n  --data-dir DIR  data folder\n"
    print("usage: dev.py smoke [options]\n" + flags)
    sys.exit(0)
start = time.time()
if os.environ.get("FAKE_ENV_FAIL"):
    print("[error] the engine is not installed")
    sys.exit(2)
game = argv[argv.index("--") + 1:] if "--" in argv else []
opts = dict(zip(game[::2], game[1::2]))
query = argv[argv.index("--query") + 1] if "--query" in argv else ""
for pair in query.split("&"):
    if "=" in pair:
        k, v = pair.split("=", 1)
        opts["--" + k] = v
seed, bot = int(opts.get("--seed", "0")), opts.get("--bot", "skilled")
print("[debug] run: game --until RUN_WON --fail-on CAUGHT")
print("BOOT_OK fake 0.1.0")
time.sleep(float(os.environ.get("FAKE_SLEEP", "0.3")))
lost = bot == "reckless" and seed % 2 == 1
if lost:
    print(f"[INFO][game] CAUGHT score={seed * 10} time={seed + 0.5}")
    print("[FAIL] marker 'RUN_WON' not seen")
else:
    print(f"[INFO][game] RUN_WON score={seed * 10} time={seed + 0.25}")
    print("[ OK ] smoke passed (marker 'RUN_WON' reached)")
print(f"FRAME_TIMES frames=120 mean=1.00 p95={seed}.50 p99=9.00 worst=9.00 mode=logic")
(ROOT / "calls").mkdir(exist_ok=True)   # a file per call: parallel appends to one file can lose lines on Windows
(ROOT / "calls" / f"{os.getpid()}-{time.time_ns()}.json").write_text(
    json.dumps({"argv": argv, "start": start, "end": time.time()}), encoding="utf-8")
sys.exit(1 if lost else 0)
'''


def load_tool():
    spec = importlib.util.spec_from_file_location("seed_sweep_under_test", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Units(unittest.TestCase):
    def setUp(self):
        self.t = load_tool()

    def test_seed_specs(self):
        self.assertEqual(self.t.parse_seeds("1-4,10"), [1, 2, 3, 4, 10])
        self.assertEqual(self.t.parse_seeds("3"), [3])
        for bad in ("4-1", "a", "1-", ""):
            with self.assertRaises(self.t.UsageError, msg=bad):
                self.t.parse_seeds(bad)

    def test_set_specs(self):
        self.assertEqual(self.t.parse_set("bot=skilled, reckless"), ("bot", ["skilled", "reckless"]))
        for bad in ("bot", "=a", "seed=1,2", "bot=", "two words=a"):
            with self.assertRaises(self.t.UsageError, msg=bad):
                self.t.parse_set(bad)

    def test_every_combination_seed_fastest(self):
        cases = self.t.cases([1, 2], [("bot", ["a", "b"]), ("diff", ["easy"])])
        self.assertEqual([(c["seed"], c["bot"]) for c in cases], [("1", "a"), ("2", "a"), ("1", "b"), ("2", "b")])
        self.assertEqual(self.t.cases([], []), [{}])

    def test_placeholders(self):
        self.assertEqual(self.t.fill(["--seed", "{seed}", "x={bot}{bot}"], {"seed": "3", "bot": "a"}),
                         ["--seed", "3", "x=aa"])
        with self.assertRaises(self.t.UsageError):
            self.t.check_placeholders(["--level", "{level}"], ["seed"])
        self.assertEqual(self.t.check_placeholders(["{seed}"], ["seed", "bot"]), ["bot"])

    def test_outcome_comes_from_the_games_lines_not_dev_pys(self):
        out = ("[debug] run: game --until RUN_WON\n[FAIL] marker 'RUN_WON' not seen\n"
               "[console.log] [INFO][game] CAUGHT score=30 lap=2 time=40s hp=50% id=a1b\nFRAME_TIMES frames=9 mean=1 p95=4.25 p99=5 worst=6\n")
        outcome, counts, numbers, p95 = self.t.read_run(out, ["RUN_WON", "CAUGHT"])
        self.assertEqual(outcome, "CAUGHT")
        self.assertEqual(counts, {"RUN_WON": 0, "CAUGHT": 1})
        self.assertEqual(numbers, {"score": 30.0, "lap": 2.0, "time": 40.0, "hp": 50.0})   # units dropped, ids not
        self.assertEqual(p95, 4.25)


class Sweeps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "game"
        (self.root / "tools").mkdir(parents=True)
        shutil.copy2(TOOL, self.root / "tools" / "seed_sweep.py")
        (self.root / "tools" / "dev.py").write_text(FAKE_DEV, encoding="utf-8")
        self.engine("cpp-sdl2")

    def tearDown(self):
        self.tmp.cleanup()

    def engine(self, name):
        (self.root / ".game-kit.json").write_text(json.dumps({"engine": name}), encoding="utf-8")

    def sweep(self, *args, env=None):
        r = subprocess.run([sys.executable, str(self.root / "tools" / "seed_sweep.py"), *args], cwd=self.root,
                           capture_output=True, encoding="utf-8", errors="replace", timeout=300,
                           env=dict(os.environ, **(env or {})))
        return r.returncode, r.stdout + r.stderr

    def calls(self):
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((self.root / "calls").glob("*.json"))]

    BOTS = ["--seeds", "1-4", "--set", "bot=skilled,reckless", "--collect", "RUN_WON,CAUGHT", "--jobs", "3",
            "--", "--until", "RUN_WON", "--", "--seed", "{seed}", "--bot", "{bot}"]

    def test_a_bot_pair_sweep(self):
        rc, out = self.sweep("--json", "captures/sweep/out.json", *self.BOTS)
        self.assertEqual(rc, 1, out)                       # reckless loses on seeds 1 and 3
        data = json.loads((self.root / "captures/sweep/out.json").read_text(encoding="utf-8"))
        per = {s["setting"]["bot"]: s for s in data["per_setting"]}
        self.assertEqual((per["skilled"]["passed"], per["skilled"]["runs"]), (4, 4))
        self.assertEqual((per["reckless"]["passed"], per["reckless"]["outcomes"]), (2, {"RUN_WON": 2, "CAUGHT": 2}))
        self.assertEqual(per["skilled"]["means"]["score"], 25.0)
        runs = {(r["case"]["seed"], r["case"]["bot"]): r for r in data["runs"]}
        self.assertEqual(runs[("3", "reckless")]["outcome"], "CAUGHT")
        self.assertEqual(runs[("3", "reckless")]["status"], "fail")
        self.assertEqual(runs[("2", "skilled")]["p95_ms"], 2.5)
        self.assertIn("2/4", out)
        self.assertIn("50%", out)
        self.assertTrue((self.root / runs[("1", "skilled")]["log"]).is_file())
        # the first run builds; the others reuse it, each with a data folder of its own, game options after `--`
        calls = sorted(self.calls(), key=lambda c: c["start"])
        self.assertEqual(len(calls), 8)
        self.assertNotIn("--no-build", calls[0]["argv"])
        self.assertTrue(all("--no-build" in c["argv"] for c in calls[1:]))
        dirs = [c["argv"][c["argv"].index("--data-dir") + 1] for c in calls]
        self.assertEqual(len(set(dirs)), 8)
        for c in calls:
            a = c["argv"]
            self.assertEqual(a[:2], ["--debug", "smoke"])
            self.assertLess(a.index("--data-dir"), a.index("--"), "smoke's options stay before the game's")

    def test_runs_overlap_up_to_the_job_limit(self):
        rc, out = self.sweep(*self.BOTS, env={"FAKE_SLEEP": "0.6"})
        calls = self.calls()
        later = calls[1:]
        most = max(sum(1 for o in later if o["start"] < c["end"] and c["start"] < o["end"]) for c in later)
        self.assertGreater(most, 1, "nothing ran in parallel")
        self.assertLessEqual(most, 3, "more runs at once than --jobs")
        first = min(calls, key=lambda c: c["start"])
        self.assertTrue(all(o["start"] >= first["end"] for o in calls if o is not first), "the first run goes alone")

    def test_min_pass(self):
        self.assertEqual(self.sweep(*self.BOTS[:-8], "--min-pass", "0.5", *self.BOTS[-8:])[0], 0)
        rc, out = self.sweep(*self.BOTS[:-8], "--min-pass", "0.75", *self.BOTS[-8:])
        self.assertEqual(rc, 1)
        self.assertIn("bot=reckless: 2/4 passed, under --min-pass 0.75", out)

    def test_unity_runs_one_at_a_time_without_data_folders(self):
        self.engine("unity")
        rc, out = self.sweep(*self.BOTS, env={"FAKE_SLEEP": "0.2"})
        self.assertIn("one run at a time", out)
        calls = sorted(self.calls(), key=lambda c: c["start"])
        self.assertTrue(all(b["start"] >= a["end"] for a, b in zip(calls, calls[1:])), "runs overlapped on Unity")
        self.assertFalse(any("--data-dir" in c["argv"] for c in calls))

    def test_a_smoke_without_the_flags_gets_none(self):
        rc, out = self.sweep("--seeds", "1-2", "--", "--", "--seed", "{seed}", env={"FAKE_NO_FLAGS": "1"})
        self.assertEqual(rc, 0, out)
        self.assertFalse(any("--no-build" in c["argv"] or "--data-dir" in c["argv"] for c in self.calls()))

    def test_a_first_run_that_cannot_start_stops_the_sweep(self):
        rc, out = self.sweep(*self.BOTS, env={"FAKE_ENV_FAIL": "1"})
        self.assertEqual(rc, 2, out)
        self.assertIn("the engine is not installed", out)
        self.assertEqual(len(list((self.root / "captures/sweep/runs").glob("*/smoke.log"))), 1)

    def test_a_run_over_its_timeout_is_stopped(self):
        rc, out = self.sweep("--seeds", "2", "--run-timeout", "1", "--", "--", "--seed", "{seed}",
                             env={"FAKE_SLEEP": "20"})
        self.assertEqual(rc, 1, out)
        self.assertIn("timeout", out)

    def test_spec_file_and_the_command_line_winning(self):
        spec = {"seeds": "1-2", "set": {"bot": ["reckless"]}, "collect": ["RUN_WON", "CAUGHT"],
                "smoke": ["--", "--seed", "{seed}", "--bot", "{bot}"]}
        (self.root / "bots.json").write_text(json.dumps(spec), encoding="utf-8")
        rc, out = self.sweep("--spec", "bots.json", "--json", "a.json")
        self.assertEqual(rc, 1, out)                       # seed 1 reckless loses
        rc, out = self.sweep("--spec", "bots.json", "--seeds", "2,4", "--json", "a.json")
        self.assertEqual(rc, 0, out)
        data = json.loads((self.root / "a.json").read_text(encoding="utf-8"))
        self.assertEqual([r["case"]["seed"] for r in data["runs"]], ["2", "4"])
        (self.root / "bad.json").write_text('{"seeds": "1", "colect": []}', encoding="utf-8")
        rc, out = self.sweep("--spec", "bad.json")
        self.assertEqual(rc, 2)
        self.assertIn("colect", out)

    def test_usage_errors(self):
        rc, out = self.sweep("--seeds", "1-2", "--", "--level", "{level}")
        self.assertEqual(rc, 2)
        self.assertIn("{level}", out)
        self.assertEqual(self.sweep()[0], 2)
        self.assertEqual(self.sweep("--seeds", "1", "--min-pass", "2", "--", "x")[0], 2)
        self.assertEqual(self.calls(), [])

    def test_web_query_and_dry_run(self):
        self.engine("web")
        rc, out = self.sweep("--seeds", "1-2", "--set", "bot=reckless", "--dry-run", "--",
                             "--query", "autoplay&seed={seed}&bot={bot}")
        self.assertEqual(rc, 0, out)
        self.assertIn("--query autoplay&seed=2&bot=reckless --no-build --data-dir", out)
        self.assertEqual(self.calls(), [], "a dry run runs nothing")

    def test_a_runs_folder_it_did_not_make_is_left_alone(self):
        mine = self.root / "captures" / "sweep" / "runs"
        mine.mkdir(parents=True)
        (mine / "notes.txt").write_text("keep me", encoding="utf-8")
        rc, out = self.sweep("--seeds", "1", "--", "--", "--seed", "{seed}")
        self.assertEqual(rc, 2, out)
        self.assertEqual((mine / "notes.txt").read_text(encoding="utf-8"), "keep me")


if __name__ == "__main__":
    unittest.main(verbosity=1)
