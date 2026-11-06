#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_session_context.py
# Purpose : Exam for tools/hooks/session_context.py, the SessionStart hook, run as Claude Code runs it (a
#           subprocess with the hook JSON on stdin) in a fake project. It prints the tier, the backlog count and
#           the ROADMAP "Now" lines; it never waits on a stdin that stays open; a huge doc does not flood the
#           context; "## Nowhere" and "## Backlog archive" are not the sections they start like; it exits 0.
# Usage   : python tools/test_session_context.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only, offline (git is used when present; the hook copes without it).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "hooks" / "session_context.py"


class SessionContextExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "tools" / "hooks").mkdir(parents=True)
        shutil.copy2(HOOK, self.root / "tools" / "hooks" / HOOK.name)
        (self.root / "docs").mkdir()
        self.doc("GDD.md", "# Game\nCurrent tier: **Toy** (first playable)\n")
        self.doc("ROADMAP.md", "# Roadmap\n## Now (max 3 items)\n- [ ] jump feels good\n## Next\n- later thing\n")
        self.doc("PRODUCTION.md", "## Backlog\n| Item | Status |\n|---|---|\n| jump | done |\n| run | todo |\n")

    def tearDown(self):
        self.tmp.cleanup()

    def doc(self, name, text):
        (self.root / "docs" / name).write_bytes(text.encode("utf-8"))

    def hook(self, stdin=b'{"source": "startup"}', keep_open=0.0):
        """Run the hook; keep_open: seconds the writer holds stdin open after the JSON. (exit code, output, seconds)"""
        start = time.monotonic()
        proc = subprocess.Popen([sys.executable, str(self.root / "tools" / "hooks" / HOOK.name)], cwd=self.root,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        proc.stdin.write(stdin)
        proc.stdin.flush()
        try:
            proc.wait(timeout=keep_open if keep_open else 30)
        except subprocess.TimeoutExpired:
            pass
        took = time.monotonic() - start
        proc.stdin.close()
        with proc.stdout:
            out = proc.stdout.read().decode("utf-8", "replace")
        proc.wait(timeout=30)
        return proc.returncode, out, took

    def test_prints_tier_backlog_and_now(self):
        rc, out, _ = self.hook()
        self.assertEqual(rc, 0, out)
        self.assertIn("Tier: Toy", out)
        self.assertIn("Production backlog: 1 of 2 done", out)
        self.assertIn("- [ ] jump feels good", out)
        self.assertNotIn("later thing", out)
        self.assertIn("run /start-session", out)

    def test_an_open_stdin_does_not_stall_the_session(self):
        """#241: sys.stdin.read() waited for the pipe to close, though the JSON was already whole."""
        rc, out, took = self.hook(b'{"source": "resume"}', keep_open=20)
        self.assertEqual(rc, 0, out)
        self.assertLess(took, 15, "the hook waited for stdin to close")
        self.assertIn("continue the current task", out, "the source was read from the whole JSON")

    def test_a_huge_line_is_cut(self):
        """#241: NOW_LINES bounded the line count only; one 3 MB line went into the session context."""
        self.doc("ROADMAP.md", "## Now\n- " + "x" * 3_000_000 + "\n")
        rc, out, _ = self.hook()
        self.assertEqual(rc, 0)
        self.assertLess(len(out), 5000)

    def test_headings_match_by_their_whole_name(self):
        """#241: '## Nowhere' printed as Now, '## Backlog archive' was counted as the backlog."""
        self.doc("ROADMAP.md", "## Nowhere\n- internal notes\n")
        self.doc("PRODUCTION.md", "## Backlog archive\n| Item | Status |\n|---|---|\n| old | done |\n")
        rc, out, _ = self.hook()
        self.assertEqual(rc, 0)
        self.assertNotIn("internal notes", out)
        self.assertNotIn("Production backlog", out)

    def test_bad_input_still_exits_0(self):
        rc, out, _ = self.hook(b"\xff\xfe not json")
        self.assertEqual(rc, 0, out)
        self.assertIn("== Session context (auto) ==", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
