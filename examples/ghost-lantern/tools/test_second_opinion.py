#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_second_opinion.py
# Purpose : Exam for second_opinion.py, offline: the reviewer CLI is replaced by canned results (the timeout tests run
#           plain Python processes), so no account, network or Kimi install is needed.
# Usage   : python tools/test_second_opinion.py
# Notes   : Covers the cases met for real: a login error that exits 0, error text quoted in a review or on stderr,
#           the "resume this session" line, a CLI that cannot start, a timeout with a lingering child, an empty
#           answer, a missing CLI, missing files, and --out.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import second_opinion as so  # noqa: E402


class SecondOpinionExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "a.py").write_text("print('x')\n", encoding="utf-8")
        self.cli = self.root / "kimi.exe"
        self.cli.write_text("fake", encoding="utf-8")
        self.real_run = so.run

    def tearDown(self):
        so.run = self.real_run
        self.tmp.cleanup()

    def main(self, result, *extra):
        so.run = lambda cmd, cwd, timeout: result
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = so.main(["--cli", str(self.cli), "--root", str(self.root), *extra])
        return rc, out.getvalue() + err.getvalue()

    def test_prompt_lists_files(self):
        p = so.build_prompt("Find bugs", ["a.py", "docs/b.md"])
        self.assertIn("Find bugs", p)
        self.assertIn("- a.py", p)
        self.assertIn("- docs/b.md", p)

    def test_command_uses_read_only_agent_and_model(self):
        cmd = so.build_command(Path("kimi"), "hi", "k3", so.AGENT_FILE)
        self.assertEqual(cmd[1:3], ["--agent-file", str(so.AGENT_FILE)])
        self.assertIn("-p", cmd)
        self.assertEqual(cmd[-2:], ["-m", "k3"])

    def test_agent_file_allows_only_read_tools(self):
        text = so.AGENT_FILE.read_text(encoding="utf-8")
        front = text.split("---")[1]
        self.assertIn("tools:", front)
        for tool in ("Read", "Grep", "Glob"):
            self.assertIn(f"- {tool}", front)
        for forbidden in ("Bash", "Shell", "Write", "Edit", "WebFetch", "WebSearch", "*"):
            self.assertNotIn(forbidden, front, forbidden)

    def test_login_error_with_exit_0_is_environment(self):
        rc, out = self.main((0, "Error code: 401 - {'error': {'type': 'invalid_authentication_error'}}", ""), "--ask", "x")
        self.assertEqual(rc, 2)
        self.assertIn("not logged in", out)

    def test_review_quoting_the_error_text_is_not_a_login_failure(self):
        review = ("• Finding 1: the regex matches 'Error code: 401' and invalid_authentication_error anywhere.\n"
                  "Fix: check only the first line.")
        rc, out = self.main((0, review, ""), "--ask", "x")
        self.assertEqual(rc, 0, out)
        self.assertIn("Finding 1", out)

    def test_stderr_echoing_a_read_file_is_not_a_login_failure(self):
        # The CLI writes tool activity (the text of files it read) to stderr; this tool's own source quotes the errors
        err = "ReadFile second_opinion.py\n    AUTH = r'Error code: 40[13]|not logged in'\n"
        rc, out = self.main((0, "• Nothing real.", err), "--ask", "x")
        self.assertEqual(rc, 0, out)

    def test_login_error_on_stderr_is_environment(self):
        rc, _ = self.main((0, "", "Error code: 401 - {'error': {'type': 'invalid_authentication_error'}}\n"), "--ask", "x")
        self.assertEqual(rc, 2)

    def test_answer_cleaned_and_printed(self):
        rc, out = self.main((0, "• Nothing real.\n\nTo resume this session: kimi -r session_1\n", ""), "--ask", "x",
                            "--files", "a.py")
        self.assertEqual(rc, 0, out)
        self.assertIn("Nothing real.", out)
        self.assertNotIn("To resume", out)
        self.assertNotIn("•", out)

    def test_empty_answer_fails(self):
        rc, _ = self.main((0, "To resume this session: kimi -r s\n", ""), "--ask", "x")
        self.assertEqual(rc, 1)

    def test_timeout_fails(self):
        rc, out = self.main((124, "", ""), "--ask", "x")
        self.assertEqual(rc, 1)
        self.assertIn("timeout", out)

    def test_missing_cli_is_environment(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = so.main(["--cli", str(self.root / "nope.exe"), "--root", str(self.root), "--ask", "x"])
        self.assertEqual(rc, 2)

    def test_missing_file_is_usage_error(self):
        rc, out = self.main((0, "fine", ""), "--ask", "x", "--files", "missing.py")
        self.assertEqual(rc, 2)
        self.assertIn("missing.py", out)

    def test_out_saves_the_answer(self):
        rc, out = self.main((0, "Found one thing.", ""), "--ask", "Check a.py", "--out", "docs/reviews/r.md")
        self.assertEqual(rc, 0, out)
        saved = (self.root / "docs/reviews/r.md").read_text(encoding="utf-8")
        self.assertIn("Check a.py", saved)
        self.assertIn("Found one thing.", saved)

    # Regressions from Kimi's review of this tool (2026-10-22)
    def test_column_0_error_on_stderr_with_a_real_answer_is_not_a_login_failure(self):
        # A self-review once came back as "not logged in": the CLI's thinking on stderr had the error text at column 0
        err = "• Thinking about the regex\nError code: 401 - {'error': {'type': 'invalid_authentication_error'}}\n"
        rc, out = self.main((0, "• Finding 1: real.", err), "--ask", "x")
        self.assertEqual(rc, 0, out)
        self.assertIn("Finding 1", out)

    def test_cli_that_cannot_start_is_environment(self):
        for code in (126, 127):
            rc, out = self.main((code, "", ""), "--ask", "x")
            self.assertEqual(rc, 2, code)
            self.assertIn("could not be started", out)

    def test_failed_run_prints_partial_answer_and_fails(self):
        rc, out = self.main((1, "• Half a review", ""), "--ask", "x")
        self.assertEqual(rc, 1)
        self.assertIn("Half a review", out)

    def test_quoted_resume_line_in_a_review_is_kept(self):
        review = "• The tool strips this line:\n  To resume this session: kimi -r s1\n\nTo resume this session: kimi -r s2\n"
        rc, out = self.main((0, review, ""), "--ask", "x")
        self.assertEqual(rc, 0, out)
        self.assertIn("kimi -r s1", out)
        self.assertNotIn("kimi -r s2", out)

    def test_timeout_stops_the_cli_and_its_children(self):
        # Real processes: a child that starts a grandchild holding the same pipes, then both sleep
        grandchild = "import time; time.sleep(60)"
        child = ("import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', %r]); time.sleep(60)"
                 % grandchild)
        start = time.monotonic()
        rc, _, _ = so.run([sys.executable, "-c", child], self.root, 2)
        self.assertEqual(rc, 124)
        self.assertLess(time.monotonic() - start, 30, "the timeout must not wait for a grandchild")

    def test_run_reports_a_missing_program(self):
        rc, _, _ = so.run([str(self.root / "nope.exe")], self.root, 5)
        self.assertEqual(rc, 127)

    def test_usage_limit_is_environment_and_shows_the_cli_message(self):
        # Met for real: five parallel audits after a day of reviews ran out the plan's 5-hour window
        err = ("kimi version 2.3.0\nerror: failed to run prompt: provider.api_error: 429 You've reached your 5-hour "
               "usage limit. Your quota will reset when the current 5-hour window ends.\n")
        rc, out = self.main((1, "", err), "--ask", "x")
        self.assertEqual(rc, 2)
        self.assertIn("usage or rate limit", out)
        self.assertIn("5-hour", out)

    def test_unknown_model_is_usage_error_with_the_fix(self):
        # Met for real: `--model k3` (the old help's own example) fails on Kimi Code 2.3; kimi-code/k3 works
        err = 'kimi version 2.3.0\nerror: failed to run prompt: Model "k3" is not configured in config.toml.\n'
        rc, out = self.main((1, "", err), "--ask", "x", "--model", "k3")
        self.assertEqual(rc, 2)
        self.assertIn('no model "k3"', out)
        self.assertIn("kimi-code/k3", out)

    def test_limit_hit_mid_review_is_environment_and_keeps_the_partial_notes(self):
        # Met for real: the engines audit wrote progress notes, then hit the 5-hour limit; it was reported as
        # "no answer, exit 1" and the notes were lost
        out = "• Let me read the overlays.\n• Godot dev.py looks consistent so far.\n"
        err = "error: failed to run prompt: provider.api_error: 429 You've reached your 5-hour usage limit.\n"
        rc, text = self.main((1, out, err), "--ask", "x", "--out", "docs/r.md")
        self.assertEqual(rc, 2, text)
        self.assertIn("usage or rate limit", text)
        saved = (self.root / "docs/r.md").read_text(encoding="utf-8")
        self.assertIn("INCOMPLETE", saved)
        self.assertIn("Godot dev.py looks consistent", saved)

    def test_other_cli_error_is_shown(self):
        rc, out = self.main((1, "", "error: failed to run prompt: something new\n"), "--ask", "x")
        self.assertEqual(rc, 1)
        self.assertIn("something new", out)

    def test_ask_required_unless_check(self):
        rc, _ = self.main((0, "OK", ""))
        self.assertEqual(rc, 2)
        rc, out = self.main((0, "• OK", ""), "--check")
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
