#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_run_exams.py
# Purpose : Exam for run_exams.py. Points the runner at fake exams in a temp folder and checks: unique test names
#           are counted (a class loaded twice is 2 tests, not `Ran 4`); a cases exam's [PASS] lines and its own
#           total are counted and it gets no -v; a failing exam is FAIL with its output tail and exit 1; an exam
#           that exits 2 for a missing tool it declares is SKIP naming the tool, one that exits 2 without a declared
#           need is FAIL; a missing module or PATH tool is SKIP before anything runs; live exams run only with
#           --live, and the live env vars are hidden without it; a [SKIP] line on exit 0 is a skip; a timeout is a
#           failure; --only (name, path, unknown), --changed (cover patterns, plus a real git diff when git is here),
#           --python through a fake uv (one pass per version, --with for modules, pinned rows run once), --jobs
#           keeps table order, --list prints the table. The real table is checked against the kit tree: every row's
#           file exists, names are unique, every exam file has a row (or is loaded by another), and CLAUDE.md
#           points here.
# Usage   : python scripts/test_run_exams.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only, offline. Never runs the kit's real exams: EXAMS, KIT and UV are swapped for the
#           fake kit's for each case. About 25 s (the timeout case waits for its SLOW_LIMIT_S limit).
# Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   setUp: temp/kit/fake/test_*.py (one small script per behaviour) + a fake uv that runs the real interpreter
#   each case: swap run_exams.KIT / EXAMS / UV (and TIMEOUT_S) -> run_exams.main([...]) with stdout captured
#              -> check the lines, the summary and the exit code
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
sys.path.insert(0, str(HERE))
import run_exams as rx  # noqa: E402

UNITTEST_TWICE = """\
import unittest
class Twice(unittest.TestCase):
    def test_a(self): pass
    def test_b(self):
        \"\"\"A docstring: unittest prints the verdict on the next line.\"\"\"
        pass
Alias = Twice   # the loader finds the class under both names and runs it twice
if __name__ == "__main__":
    unittest.main(verbosity=1)
"""
UNITTEST_BAD = """\
import unittest
class Bad(unittest.TestCase):
    def test_ok(self): pass
    def test_boom(self): self.assertEqual(1, 2, "the boom message")
if __name__ == "__main__":
    unittest.main(verbosity=1)
"""
EXIT2_ENV = """\
import sys
print("[ENV ] Foo 3 not installed: exam skipped", file=sys.stderr)
sys.exit(2)
"""
EXIT2_PLAIN = "import sys\nsys.exit(2)\n"
CASES = """\
import argparse, sys
argparse.ArgumentParser().parse_args()   # no options: a stray -v would exit 2 here
print("[PASS] one")
print("[PASS] two")
print("[FAIL] three (counted in the total, the exit code says the rest)")
print("2/3 cases passed")
sys.exit(0)
"""
CASES_LIVE = "print('[ OK ] the live run')\n"
OPT_SKIP = "print('[SKIP] live exam not run: no server here')\n"
ENV_PEEK = """\
import os, sys, unittest
class Peek(unittest.TestCase):
    def test_peek(self):
        print("FAKE_LIVE_BIN=" + os.environ.get("FAKE_LIVE_BIN", "unset"))
if __name__ == "__main__":
    unittest.main(verbosity=1)
"""
SLOW_LIMIT_S = 8                         # the default-run case's limit; quick fake exams must finish well under it
SLOW = "import time\ntime.sleep(60)\n"   # far past SLOW_LIMIT_S, so the timeout case is never close
# `uv run --no-project --python X [--with M]... python ARGS...`: log the call, then run ARGS on this interpreter
FAKE_UV = """\
import json, subprocess, sys
argv = sys.argv[1:]
with open(%r, "a", encoding="utf-8") as f:
    f.write(json.dumps(argv) + "\\n")
rest = argv[argv.index("python") + 1:]
sys.exit(subprocess.run([sys.executable] + rest).returncode)
"""


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


class RunExamsExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kit = Path(self.tmp.name) / "kit"
        self.uv_log = Path(self.tmp.name) / "uv_calls.jsonl"
        for name, text in (("twice", UNITTEST_TWICE), ("bad", UNITTEST_BAD), ("needs_foo", EXIT2_ENV),
                           ("usage", EXIT2_PLAIN), ("cases", CASES), ("live", CASES_LIVE), ("optskip", OPT_SKIP),
                           ("envpeek", ENV_PEEK), ("slow", SLOW), ("nomodule", "pass\n"), ("notool", "pass\n"),
                           ("pinned", UNITTEST_TWICE), ("withmod", UNITTEST_TWICE)):
            write(self.kit / "fake" / ("test_%s.py" % name), text)
        write(self.kit / "docs" / "GUIDE.md", "# guide\n")
        write(self.kit / "tool.py", "pass\n")
        write(Path(self.tmp.name) / "fake_uv.py", FAKE_UV % self.uv_log.as_posix())
        self.fake_uv = [sys.executable, str(Path(self.tmp.name) / "fake_uv.py")]
        E = rx.Exam
        self.rows = [
            E("fake/test_twice.py", "class loaded twice", covers=("tool.py",)),
            E("fake/test_bad.py", "one failing test"),
            E("fake/test_needs_foo.py", "exit 2 with [ENV ]", needs=(rx.exam_checks("Foo 3"),), style="cases"),
            E("fake/test_usage.py", "exit 2, nothing declared", style="cases"),
            E("fake/test_cases.py", "argparse, [PASS] lines", style="cases"),
            E("fake/test_live.py", "live only", style="cases", live=True),
            E("fake/test_optskip.py", "[SKIP] on exit 0", style="cases"),
            E("fake/test_envpeek.py", "sees the live var?", env=("FAKE_LIVE_BIN",)),
            E("fake/test_nomodule.py", needs=(rx.module("nosuchpackage_xyz"),), covers=("*.md",)),
            E("fake/test_notool.py", needs=(rx.tool("no_such_tool_xyz"),)),
        ]
        self.saved = (rx.KIT, rx.EXAMS, rx.UV, rx.TIMEOUT_S)
        rx.KIT, rx.EXAMS, rx.UV = self.kit, self.rows, None

    def tearDown(self):
        rx.KIT, rx.EXAMS, rx.UV, rx.TIMEOUT_S = self.saved
        self.tmp.cleanup()

    # ---- helpers ------------------------------------------------------------
    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rx.main(list(args))
        return code, out.getvalue() + err.getvalue()

    def line_for(self, out, path):
        hits = [ln for ln in out.splitlines() if re.match(r"^\[(?: OK |FAIL|SKIP)\] \S*%s " % re.escape(path), ln)]
        self.assertEqual(len(hits), 1, "one table line for %s in:\n%s" % (path, out))
        return hits[0]

    @staticmethod
    def exam_paths(out):
        """The exam paths of the table lines, in print order."""
        return [m.group(1) for m in (re.match(r"^\[(?: OK |FAIL|SKIP)\] (fake/\S+)", ln) for ln in out.splitlines()) if m]

    # ---- the default run ----------------------------------------------------
    def test_default_run_judges_every_kind_of_exam(self):
        # The limit covers every fake exam in this run, not only the slow one: 1 s failed a quick exam on a busy
        # machine (1.1 s while engine builds ran), so it leaves room for a loaded Python start.
        rx.TIMEOUT_S = SLOW_LIMIT_S
        rx.EXAMS = self.rows + [rx.Exam("fake/test_slow.py", "sleeps past the limit")]
        code, out = self.run_main()
        self.assertEqual(code, 1, out)
        self.assertRegex(self.line_for(out, "test_twice.py"), r"^\[ OK \].* 2 tests +\d+\.\d s$",
                         "unique names, not the Ran 4 line")
        self.assertRegex(self.line_for(out, "test_bad.py"), r"^\[FAIL\].* 2 tests .*exit 1")
        self.assertIn("---- fake/test_bad.py (exit 1) ----", out)
        self.assertIn("the boom message", out, "the failed exam's tail is printed")
        self.assertRegex(self.line_for(out, "test_needs_foo.py"), r"^\[SKIP\].*Foo 3 not installed.*\(exam exit 2\)")
        self.assertRegex(self.line_for(out, "test_usage.py"), r"^\[FAIL\].*exit 2")
        self.assertRegex(self.line_for(out, "test_cases.py"), r"^\[ OK \].* 3 cases ", "its own total, no -v sent")
        self.assertRegex(self.line_for(out, "test_live.py"), r"^\[SKIP\].*--live")
        self.assertRegex(self.line_for(out, "test_optskip.py"), r"^\[SKIP\] .*live exam not run: no server here")
        self.assertRegex(self.line_for(out, "test_envpeek.py"), r"^\[ OK \]")
        self.assertRegex(self.line_for(out, "test_nomodule.py"), r"^\[SKIP\].*needs nosuchpackage_xyz")
        self.assertRegex(self.line_for(out, "test_notool.py"), r"^\[SKIP\].*needs no_such_tool_xyz \(not on PATH\)")
        self.assertRegex(self.line_for(out, "test_slow.py"), r"^\[FAIL\].*timed out after %d s" % SLOW_LIMIT_S)
        self.assertRegex(out, r"\[FAIL\] Python \d+\.\d+: 11 exams, 3 passed, 3 failed, 5 skipped; 6 unique tests")

    def test_lines_come_in_table_order_with_jobs(self):
        code, out = self.run_main("--jobs", "3")
        self.assertEqual(code, 1, out)
        self.assertEqual(self.exam_paths(out), [r.path for r in self.rows])

    def test_all_passing_with_skips_exits_0(self):
        rx.EXAMS = [r for r in self.rows if r.name not in ("bad", "usage")]
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"\[ OK \] Python \d+\.\d+: 8 exams, 3 passed, 0 failed, 5 skipped; 6 unique tests")

    # ---- live ---------------------------------------------------------------
    def test_live_env_is_hidden_without_live_and_passed_with_it(self):
        rx.EXAMS = [r for r in self.rows if r.name in ("envpeek", "live")]
        with mock.patch.dict(os.environ, {"FAKE_LIVE_BIN": "here"}):
            code, out = self.run_main("--debug")
            self.assertEqual(code, 0, out)
            self.assertIn("FAKE_LIVE_BIN=unset", out, "the live var reaches the exam without --live")
            self.assertRegex(self.line_for(out, "test_live.py"), r"^\[SKIP\]")
            code, out = self.run_main("--live", "--debug")
            self.assertEqual(code, 0, out)
            self.assertIn("FAKE_LIVE_BIN=here", out)
            self.assertRegex(self.line_for(out, "test_live.py"), r"^\[ OK \].* 1 cases ")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FAKE_LIVE_BIN", None)
            code, out = self.run_main("--live")
            self.assertEqual(code, 0, out)
            self.assertIn("FAKE_LIVE_BIN unset: live part skipped", self.line_for(out, "test_envpeek.py"))

    # ---- selection ----------------------------------------------------------
    def test_only_by_name_and_path_and_unknown(self):
        code, out = self.run_main("--only", "twice", "--only", "fake/test_cases.py")
        self.assertEqual(code, 0, out)
        self.assertEqual(len([ln for ln in out.splitlines() if "fake/test_" in ln]), 2)
        self.assertIn("test_twice.py", out)
        self.assertIn("test_cases.py", out)
        code, out = self.run_main("--only", "no_such_exam")
        self.assertEqual(code, 2, out)
        self.assertIn("[error] no exam named 'no_such_exam'", out)
        self.assertIn("twice", out, "the error lists the names")

    def test_changed_selects_by_cover_patterns(self):
        rows = self.rows
        by = lambda files: [r.name for r in rx.select_changed(rows, files)]   # noqa: E731
        self.assertEqual(by(["tool.py"]), ["twice"], "an exact covered file")
        self.assertEqual(by(["docs/GUIDE.md"]), ["nomodule"], "a *.md pattern matches by file name anywhere")
        self.assertEqual(by(["fake/test_bad.py"]), [r.name for r in rows if r.name not in ("twice", "nomodule")],
                         "the exams' folder is the default cover; an explicit covers= replaces it")
        self.assertEqual(by(["README.txt"]), [])
        self.assertTrue(rx.covers(rx.Exam("x/test_a.py", covers=("engines/",)), "engines/godot/skeleton/tools/dev.py"))
        self.assertFalse(rx.covers(rx.Exam("x/test_a.py", covers=("engines/",)), "core/engines.md"))
        self.assertTrue(rx.covers(rx.Exam("x/test_a.py", covers=()), "x/test_a.py"), "an exam always covers itself")

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_changed_against_a_real_ref(self):
        git = ["git", "-c", "user.name=exam", "-c", "user.email=exam@example.com", "-c", "commit.gpgsign=false"]
        for cmd in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "seed"]):
            r = subprocess.run(git + cmd, cwd=str(self.kit), capture_output=True, encoding="utf-8", errors="replace")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        write(self.kit / "tool.py", "print('changed')\n")             # covered by twice (tracked, unstaged)
        write(self.kit / "docs" / "NEW.md", "# new\n")                 # covered by nomodule's *.md (untracked)
        code, out = self.run_main("--changed", "HEAD")
        self.assertEqual(code, 0, out)
        self.assertIn("[info] 2 file(s) changed since HEAD: 2 exam(s) cover them", out)
        self.assertEqual(sorted(self.exam_paths(out)), ["fake/test_nomodule.py", "fake/test_twice.py"])
        code, out = self.run_main("--changed", "no-such-ref-xyz")
        self.assertEqual(code, 2, out)
        self.assertIn("[error] git could not diff", out)

    def test_changed_with_nothing_covered_runs_nothing(self):
        with mock.patch.object(rx, "changed_files", lambda ref, kit: ["LICENSE"]):
            code, out = self.run_main("--changed", "main")
        self.assertEqual(code, 0, out)
        self.assertIn("0 exam(s) cover them", out)
        self.assertIn("[info] nothing to run", out)

    # ---- --python through uv --------------------------------------------------
    def test_python_versions_run_through_uv_once_each(self):
        rx.UV = self.fake_uv
        rx.EXAMS = [self.rows[0],
                    rx.Exam("fake/test_pinned.py", "bpy-like", needs=(rx.module("bpyfake"),), python="3.13"),
                    rx.Exam("fake/test_withmod.py", needs=(rx.module("pillowfake"),))]
        code, out = self.run_main("--python", "3.8,3.9")
        self.assertEqual(code, 0, out)
        self.assertIn("== Python 3.8 via uv ==", out)
        self.assertIn("== Python 3.9 via uv ==", out)
        calls = [json.loads(ln) for ln in self.uv_log.read_text(encoding="utf-8").splitlines()]
        versions = [c[c.index("--python") + 1] for c in calls]
        self.assertEqual(sorted(versions), ["3.13", "3.8", "3.8", "3.9", "3.9"], "pinned rows run once")
        withs = [c[c.index("--with") + 1] for c in calls if "--with" in c]
        self.assertEqual(sorted(withs), ["bpyfake", "pillowfake", "pillowfake"], "--with per module need")
        self.assertTrue(all(c[:2] == ["run", "--no-project"] for c in calls))
        pinned = [ln for ln in out.splitlines() if "test_pinned.py" in ln]
        self.assertEqual(len(pinned), 2)
        self.assertRegex(pinned[0], r"^\[ OK \].*\[Python 3\.13\]$")
        self.assertRegex(pinned[1], r"^\[SKIP\].*pinned to Python 3\.13: ran on the first pass")
        self.assertRegex(out, r"\[ OK \] Python 3\.8 via uv: 3 exams, 3 passed")
        self.assertRegex(out, r"\[ OK \] Python 3\.9 via uv: 3 exams, 2 passed, 0 failed, 1 skipped")

    def test_python_without_uv_runs_once_here_with_a_warning(self):
        rx.EXAMS = [self.rows[0]]
        code, out = self.run_main("--python", "3.8,3.9")
        self.assertEqual(code, 0, out)
        self.assertIn("[warn] uv not found: running once on this interpreter", out)
        self.assertEqual(out.count("test_twice.py"), 1)
        self.assertNotIn("via uv", out)

    def test_missing_module_goes_through_uv_when_present(self):
        rx.UV = self.fake_uv
        rx.EXAMS = [rx.Exam("fake/test_withmod.py", needs=(rx.module("nosuchpackage_xyz"),))]
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        line = self.line_for(out, "test_withmod.py")
        self.assertRegex(line, r"^\[ OK \].*\[Python %d\.%d\]$" % sys.version_info[:2])
        calls = [json.loads(ln) for ln in self.uv_log.read_text(encoding="utf-8").splitlines()]
        self.assertIn("nosuchpackage_xyz", calls[0])

    def test_bad_python_and_jobs_exit_2(self):
        self.assertEqual(self.run_main("--python", "three")[0], 2)
        self.assertEqual(self.run_main("--python", "")[0], 2)
        self.assertEqual(self.run_main("--jobs", "0")[0], 2)

    # ---- counting ----------------------------------------------------------
    def test_count_tests_dedupes_both_verbose_formats(self):
        row = rx.Exam("x/test_x.py")
        old = "test_a (test_x.C) ... ok\ntest_b (test_x.C) ... skipped 'no'\ntest_a (test_x.C) ... ok\nRan 3 tests\n"
        self.assertEqual(rx.count_tests(row, old), (2, 1), "Python 3.8's format")
        new = ("test_a (__main__.C.test_a) ... ok\ntest_b (__main__.C.test_b)\nA docstring ... ok\n"
               "test_a (__main__.C.test_a) ... ok\nRan 3 tests\n")
        self.assertEqual(rx.count_tests(row, new), (2, 0), "Python 3.11+'s format, a docstring line")
        self.assertEqual(rx.count_tests(row, "...\nRan 7 tests in 0.1s\nOK\n"), (7, 0), "the Ran line only as a fallback")
        self.assertEqual(rx.count_tests(row, "nothing\n"), (0, 0))
        cases = rx.Exam("x/test_c.py", style="cases")
        self.assertEqual(rx.count_tests(cases, "[PASS] a\n[FAIL] b\n[ OK ] c\n"), (3, 0))
        self.assertEqual(rx.count_tests(cases, "[PASS] a\n5/9 cases passed\n"), (9, 0))
        self.assertEqual(rx.count_tests(cases, "[ OK ] a\nscore: 13/14\n"), (14, 0))

    # ---- --list and the real table ---------------------------------------------
    def test_list_prints_every_row(self):
        code, out = self.run_main("--list")
        self.assertEqual(code, 0, out)
        for r in self.rows:
            self.assertIn(r.path, out)
        self.assertIn("Foo 3", out)
        self.assertIn("FAKE_LIVE_BIN (live part)", out)
        self.assertIn("--live", out)
        self.assertNotIn("[warn]", out)
        write(self.kit / "fake" / "test_orphan.py", "pass\n")
        rx.EXAM_ROOTS, saved = ("fake",), rx.EXAM_ROOTS
        try:
            self.assertIn("[warn] no row for fake/test_orphan.py", self.run_main("--list")[1])
        finally:
            rx.EXAM_ROOTS = saved

    def test_the_real_table_matches_the_kit_tree(self):
        rows = self.saved[1]
        names = [r.name for r in rows]
        self.assertEqual(sorted(set(names)), sorted(names), "--only names must be unique")
        missing = [r.path for r in rows if not (KIT / r.path).is_file()]
        self.assertEqual(missing, [], "rows naming files that are not there")
        self.assertEqual([p for p in rx.LOADED_BY_ANOTHER if not (KIT / p).is_file()], [])
        self.assertEqual(rx.untracked_exams(KIT, rows), [], "exam files in the tree without a row")
        self.assertIn("scripts/run_exams.py", (KIT / "CLAUDE.md").read_text(encoding="utf-8"),
                      "CLAUDE.md points maintainers at the runner")
        for r in rows:
            for kind, name in r.needs:
                self.assertIn(kind, ("tool", "module", "exam"))
            self.assertIn(r.style, ("unittest", "cases"))
            if r.python:
                self.assertRegex(r.python, r"^3\.\d+$")
        live = sorted(r.name for r in rows if r.live)
        self.assertEqual(live, ["bozzetto_live", "render_sprites"], "the opt-in exams")
        self.assertEqual(sorted({v for r in rows for v in r.env}), ["ASEPRITE_BIN", "PIXELORAMA_BIN", "REAPER_BIN"])

    def test_needs_text_reads_well(self):
        self.assertEqual(rx.Exam("x/test_a.py").needs_text(), "standard library")
        row = rx.Exam("x/test_b.py", needs=(rx.module("bpy"),), python="3.13", live=True, env=("R_BIN",))
        self.assertEqual(row.needs_text(), "bpy on Python 3.13, R_BIN (live part), --live")
        self.assertEqual(re.sub(r"\s+", " ", rx.Exam("core/tools/art/dotwork/tests/test_d.py").covers[0]),
                         "core/tools/art/dotwork/", "a tests/ folder covers its parent")


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=1)
