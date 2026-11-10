#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_check_examples.py
# Purpose : Exam for scripts/check_examples.py (#159) on fake examples in a temp git repository: each fake example
#           has a .game-kit.json, a tools/doctor.py and a tools/dev.py that does what its behavior.json says (an exit
#           code, a last line, a sleep, a file it writes, a file it needs). Covers the table and its exit codes, a
#           missing toolchain reported SKIP naming the variable from dev.py's Env lines, the expected exits, the
#           per-command timeout, GUT copied in for a Godot example and removed after, the final git status check,
#           --only, --engine and --skip-smoke, and the Env parsing on every engine's real dev.py.
# Usage   : python scripts/test_check_examples.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library and git. Offline; the fake commands are Python scripts run the way the real ones are.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]

FAKE_DEV = '''#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# dev.py (a fake for test_check_examples.py)
# Env     : {env}
# Exit    : 0 ok
# ---------------------------------------------------------------------------
import json, sys, time
from pathlib import Path
root = Path(__file__).resolve().parents[1]
spec = json.loads((root / "behavior.json").read_text(encoding="utf-8")).get(sys.argv[1], {{}})
time.sleep(spec.get("sleep", 0))
if spec.get("need") and not (root / spec["need"]).is_file():
    print("[error] missing " + spec["need"])
    sys.exit(2)
if spec.get("write"):
    (root / spec["write"]).write_text("changed by the run", encoding="utf-8")
print("some output")
print(spec.get("line", "[ OK ] " + sys.argv[1] + " passed"))
print("trailing chatter")
sys.exit(spec.get("rc", 0))
'''
FAKE_DOCTOR = 'import sys\nprint("[ OK ] doctor")\nsys.exit(0)\n'


def load():
    spec = importlib.util.spec_from_file_location("check_examples", KIT / "scripts" / "check_examples.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.TOOLS = {}                           # no node, cmake or cargo needed for the fakes
    mod.PATH_FALLBACK = {}
    mod.EXPECTED = {}
    return mod


def git(root, *args):
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True,
                   encoding="utf-8", errors="replace")


@unittest.skipUnless(shutil.which("git"), "needs git")
class CheckExamples(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.examples = self.repo / "examples"
        self.examples.mkdir()
        self.mod = load()
        self.saved_env = {k: os.environ.get(k) for k in ("GUT_DIR", "FAKE_ENGINE_BIN")}
        for k in self.saved_env:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def example(self, name, engine="web", env="none required.", behavior=None):
        d = self.examples / name
        (d / "tools").mkdir(parents=True)
        (d / ".game-kit.json").write_text(json.dumps({"engine": engine, "version": "0.14.3"}), encoding="utf-8")
        (d / "tools" / "dev.py").write_text(FAKE_DEV.format(env=env), encoding="utf-8")
        (d / "tools" / "doctor.py").write_text(FAKE_DOCTOR, encoding="utf-8")
        (d / "behavior.json").write_text(json.dumps(behavior or {}), encoding="utf-8")
        (d / "notes.txt").write_text("tracked\n", encoding="utf-8")
        return d

    def commit(self):
        (self.repo / ".gitignore").write_text("build/\n", encoding="utf-8")
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "fakes")

    def run_tool(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = self.mod.main(["--examples", str(self.examples), *args])
        return rc, buf.getvalue()

    def row(self, text, name):
        return next(l for l in text.splitlines() if l.startswith(name + " "))

    def test_all_pass_prints_one_row_per_example(self):
        self.example("alpha")
        self.example("beta", engine="godot-ish")
        self.commit()
        rc, text = self.run_tool()
        self.assertEqual(rc, 0, text)
        self.assertRegex(self.row(text, "alpha"), r"^alpha\s+web\s+0\s+0\s+0\s+0\s*$")
        self.assertIn("[ OK ] examples/ has no new changes", text)
        self.assertIn("2 example(s): 8 command(s) ran, 0 failed, 0 skipped", text)

    def test_a_failure_shows_its_last_fail_line_and_exits_1(self):
        self.example("alpha", behavior={"check": {"rc": 1, "line": "[FAIL] scripts/x.gd"}})
        self.commit()
        rc, text = self.run_tool()
        self.assertEqual(rc, 1, text)
        self.assertRegex(self.row(text, "alpha"), r"0\s+1 FAIL\s+0\s+0")
        self.assertIn("alpha check: [FAIL] [FAIL] scripts/x.gd", text)   # the FAIL line, not the chatter after it

    def test_missing_toolchain_is_skip_naming_the_variable(self):
        self.example("alpha", env="FAKE_ENGINE_BIN  path to the engine")
        self.example("beta", env="FAKE_ENGINE_BIN  optional, a second engine")
        self.commit()
        rc, text = self.run_tool()
        self.assertEqual(rc, 0, text)
        self.assertRegex(self.row(text, "alpha"), r"0\s+SKIP\s+SKIP\s+SKIP")   # doctor still runs
        self.assertIn("alpha check: [SKIP] set FAKE_ENGINE_BIN", text)
        self.assertRegex(self.row(text, "beta"), r"0\s+0\s+0\s+0")            # an optional one is not needed
        os.environ["FAKE_ENGINE_BIN"] = str(self.repo / "nowhere.exe")
        rc, text = self.run_tool("--only", "alpha")
        self.assertIn("FAKE_ENGINE_BIN=", text)
        self.assertIn("does not exist", text)
        os.environ["FAKE_ENGINE_BIN"] = sys.executable
        rc, text = self.run_tool("--only", "alpha")
        self.assertRegex(self.row(text, "alpha"), r"0\s+0\s+0\s+0")

    def test_path_fallback_counts_as_the_toolchain(self):
        self.example("alpha", engine="godot", env="FAKE_ENGINE_BIN  path (else python on PATH)")
        self.commit()
        self.mod.PATH_FALLBACK = {"godot": (Path(sys.executable).name,)}
        self.addCleanup(os.environ.__setitem__, "PATH", os.environ.get("PATH", ""))
        os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
        self.assertIsNone(self.mod.missing_toolchain(self.examples / "alpha", "godot"))
        self.mod.TOOLS = {"godot": ("no-such-program-xyz",)}
        self.assertIn("no-such-program-xyz", self.mod.missing_toolchain(self.examples / "alpha", "godot"))

    def test_expected_exit_is_not_a_failure_but_a_different_one_is(self):
        self.example("lock", behavior={"smoke": {"rc": 2, "line": "[error] MZ files missing"}})
        self.commit()
        self.mod.EXPECTED = {("lock", "smoke"): (2, "no MZ files")}
        rc, text = self.run_tool()
        self.assertEqual(rc, 0, text)
        self.assertRegex(self.row(text, "lock"), r"0\s+0\s+0\s+2 exp")
        self.assertIn("[expected: no MZ files]", text)
        (self.examples / "lock" / "behavior.json").write_text("{}", encoding="utf-8")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qam", "now passes")
        rc, text = self.run_tool()
        self.assertEqual(rc, 1, text)                    # the gap closed: EXPECTED is stale, say so
        self.assertIn("[expected exit 2]", text)

    def test_prepare_runs_once_before_test_when_its_file_is_missing(self):
        made = "build/map.txt"                           # gitignored, like Rune Delve's Content/
        self.example("delve", behavior={"exec": {"write": made, "line": "[ OK ] map made"},
                                        "test": {"need": made}})
        (self.examples / "delve" / "build").mkdir()
        self.commit()
        self.mod.PREPARE = {"delve": (made, ("exec", "tools/build_content.py"))}
        rc, text = self.run_tool()
        self.assertEqual(rc, 0, text)
        self.assertIn("prepare 0", " ".join(text.split()))
        rc, text = self.run_tool()                       # the file is there now: no second run
        self.assertNotIn("prepare", text)
        (self.examples / "delve" / made).unlink()
        spec = json.loads((self.examples / "delve" / "behavior.json").read_text(encoding="utf-8"))
        spec["exec"] = {"rc": 1, "line": "[FAIL] the script broke"}
        (self.examples / "delve" / "behavior.json").write_text(json.dumps(spec), encoding="utf-8")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qam", "broken")
        rc, text = self.run_tool()
        self.assertEqual(rc, 1, text)
        self.assertIn("delve prepare: [FAIL] [FAIL] the script broke", text)

    def test_timeout_kills_the_command(self):
        self.example("slow", behavior={"smoke": {"sleep": 60}})
        self.commit()
        start = time.time()
        rc, text = self.run_tool("--timeout", "3")
        self.assertLess(time.time() - start, 45)
        self.assertEqual(rc, 1, text)
        self.assertRegex(self.row(text, "slow"), r"T/O FAIL")
        self.assertIn("timed out", text)

    def test_gut_is_copied_for_godot_and_removed_after(self):
        need = {"check": {"need": "addons/gut/gut_cmdln.gd"}, "test": {"need": "addons/gut/gut_cmdln.gd"}}
        self.example("hop", engine="godot", behavior=need)
        self.commit()
        rc, text = self.run_tool()
        self.assertEqual(rc, 1, text)                    # check needs GUT and there is none
        self.assertIn("hop test: [SKIP] set GUT_DIR", text)
        gut = self.repo.parent / (self.repo.name + "-gut") / "addons" / "gut"
        gut.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, str(gut.parents[1]), True)
        (gut / "gut_cmdln.gd").write_text("extends Node\n", encoding="utf-8")
        os.environ["GUT_DIR"] = str(gut.parent)          # the folder holding gut/ works too
        rc, text = self.run_tool()
        self.assertEqual(rc, 0, text)
        self.assertRegex(self.row(text, "hop"), r"0\s+0\s+0\s+0")
        self.assertFalse((self.examples / "hop" / "addons").exists(), "GUT was left behind")
        own = self.examples / "hop" / "addons" / "gut"   # an example's own GUT stays
        own.mkdir(parents=True)
        (own / "gut_cmdln.gd").write_text("# mine\n", encoding="utf-8")
        self.run_tool()
        self.assertEqual((own / "gut_cmdln.gd").read_text(encoding="utf-8"), "# mine\n")
        os.environ["GUT_DIR"] = str(self.repo)           # no GUT in it: a setup error
        rc, text = self.run_tool()
        self.assertEqual(rc, 2, text)
        self.assertIn("holds no gut_cmdln.gd", text)

    def test_new_changes_in_examples_fail_the_run(self):
        self.example("alpha", behavior={"test": {"write": "notes.txt"}})
        self.example("beta", behavior={"test": {"write": "build/out.txt"}})   # ignored output is fine
        (self.examples / "beta" / "build").mkdir()
        self.commit()
        (self.examples / "beta" / "notes.txt").write_text("edited before the run\n", encoding="utf-8")
        rc, text = self.run_tool()
        self.assertEqual(rc, 1, text)
        self.assertIn("[FAIL] the run left 1 change(s) in examples/", text)
        self.assertIn("alpha/notes.txt", text)
        self.assertNotIn("beta/notes.txt\n", text.split("[FAIL] the run left")[1])   # it was there before

    def test_only_engine_and_skip_smoke(self):
        self.example("alpha", behavior={"smoke": {"rc": 1}})
        self.example("beta", engine="godot")
        self.commit()
        rc, text = self.run_tool("--engine", "web", "--skip-smoke")
        self.assertEqual(rc, 0, text)
        self.assertNotIn("smoke", text.split("example", 1)[1].splitlines()[0])
        self.assertNotIn("beta", text)
        rc, text = self.run_tool("--only", "nope")
        self.assertEqual(rc, 2)
        self.assertIn("not an example: nope", text)
        rc, text = self.run_tool("--engine", "unreal")
        self.assertEqual(rc, 2)

    def test_not_a_git_checkout_is_a_setup_error(self):
        self.example("alpha")
        rc, text = self.run_tool()
        self.assertEqual(rc, 2, text)
        self.assertIn("needs git and a checkout", text)

    def test_list_runs_nothing(self):
        self.example("alpha", env="FAKE_ENGINE_BIN  path", behavior={"check": {"write": "notes.txt"}})
        rc, text = self.run_tool("--list")
        self.assertEqual(rc, 0, text)
        self.assertIn("SKIP: set FAKE_ENGINE_BIN", text)
        self.assertEqual((self.examples / "alpha" / "notes.txt").read_text(encoding="utf-8"), "tracked\n")


class DocumentedEnv(unittest.TestCase):
    """The variables come from each engine's real dev.py header."""
    WANT = {"godot": [("GODOT_BIN", False)], "unity": [("UNITY_EDITOR", False)], "unreal": [("UE_ROOT", False)],
            "cpp-sdl2": [("VCPKG_ROOT", False)], "love2d": [("LOVE_BIN", False)],
            "bevy": [("CARGO_TARGET_DIR", True), ("RUSTUP_TOOLCHAIN", True)], "rpgmaker-mz": [("RPGMZ_EXE", True)],
            "web": [], "web-3d": []}

    def test_every_engine(self):
        mod = load()
        for engine, want in self.WANT.items():
            with self.subTest(engine=engine):
                got = mod.documented_env(KIT / "engines" / engine / "skeleton" / "tools" / "dev.py")
                self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main(verbosity=2)
