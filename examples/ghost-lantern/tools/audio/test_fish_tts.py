#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_fish_tts.py
# Purpose : Exam for fish_tts.py, offline: the HTTP call is replaced by canned responses, so no key or
#           balance is used. Checks the balance check, voice search, the TTS request (model header, body),
#           saving, error mapping, and that the API key never lands in any output.
# Usage   : python tools/audio/test_fish_tts.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fish_tts as ft  # noqa: E402

KEY = "fish_exam_DO_NOT_LEAK_5678"


class Fake:
    def __init__(self, status=200, body=b"\xff\xfbfake-mp3"):
        self.calls, self.status, self.body = [], status, body

    def __call__(self, method, url, key, body=None, extra_headers=None):
        self.calls.append((method, url, key, body, extra_headers or {}))
        if self.status != 200:
            return self.status, {}, json.dumps({"status": self.status, "message": "nope"}).encode()
        if "/wallet/" in url:
            return 200, {}, json.dumps({"credit": "1.50", "cumulative_top_up": "5", "has_free_credit": True}).encode()
        if url.split("?")[0].endswith("/model"):
            return 200, {}, json.dumps({"total": 1, "items": [{"_id": "v1", "title": "Calm Voice", "languages": ["en"],
                                                               "like_count": 3, "licensed": True}]}).encode()
        return 200, {}, self.body


class FishTtsExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.real_http, self.real_key = ft.http, ft.get_key
        ft.get_key = lambda: KEY

    def tearDown(self):
        ft.http, ft.get_key = self.real_http, self.real_key
        self.tmp.cleanup()

    def run_tool(self, fake, *args):
        ft.http = fake
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = ft.main([str(a) for a in args])
        return rc, out.getvalue() + err.getvalue()

    def test_check_shows_balance(self):
        fake = Fake()
        rc, out = self.run_tool(fake, "check")
        self.assertEqual(rc, 0, out)
        self.assertIn("API credit 1.50", out)
        self.assertIn("/wallet/self/api-credit", fake.calls[0][1])

    def test_voices_search_sends_filters(self):
        fake = Fake()
        rc, out = self.run_tool(fake, "voices", "--search", "old knight", "--language", "en", "--licensed")
        self.assertEqual(rc, 0, out)
        url = fake.calls[0][1]
        for part in ("title=old+knight", "language=en", "licensed=true"):
            self.assertIn(part, url)
        self.assertIn("v1  Calm Voice", out)

    def test_say_sends_model_header_and_saves_with_sidecar(self):
        fake = Fake()
        out_path = self.dir / "voice" / "halt.mp3"
        rc, out = self.run_tool(fake, "say", "--voice", "v1", "--text", "Halt.", "--out", out_path,
                                "--model", "s2.1-pro-free")
        self.assertEqual(rc, 0, out)
        method, url, key, body, headers = fake.calls[0]
        self.assertEqual((method, key, headers), ("POST", KEY, {"model": "s2.1-pro-free"}))
        self.assertTrue(url.endswith("/v1/tts"))
        self.assertEqual(body["reference_id"], "v1")
        self.assertEqual(body["format"], "mp3")
        self.assertEqual(out_path.read_bytes(), b"\xff\xfbfake-mp3")
        side = json.loads(out_path.with_suffix(".gen.json").read_text(encoding="utf-8"))
        self.assertEqual(side["text_bytes"], 5)

    def test_format_from_extension(self):
        fake = Fake()
        self.run_tool(fake, "say", "--voice", "v", "--text", "x", "--out", self.dir / "a.wav")
        self.assertEqual(fake.calls[0][3]["format"], "wav")
        rc, out = self.run_tool(Fake(), "say", "--voice", "v", "--text", "x", "--out", self.dir / "a.flac")
        self.assertEqual(rc, 2)

    def test_dry_run_sends_nothing(self):
        fake = Fake()
        rc, out = self.run_tool(fake, "say", "--voice", "v", "--text", "Halt.", "--out", self.dir / "a.mp3", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertEqual(fake.calls, [])
        self.assertIn("5 bytes of text", out)

    def test_errors_map_to_exit_codes(self):
        for status, code, text in ((401, 2, "rejected"), (402, 2, "s2.1-pro-free"), (429, 2, "rate limited"),
                                   (503, 1, "try again")):
            rc, out = self.run_tool(Fake(status=status), "check")
            self.assertEqual(rc, code, status)
            self.assertIn(text, out)

    def test_missing_key(self):
        ft.get_key = lambda: None
        rc, out = self.run_tool(Fake(), "check")
        self.assertEqual(rc, 2)
        self.assertIn(ft.KEY_ENV, out)

    def test_several_lines_one_log_row(self):
        (self.dir / "docs").mkdir()
        (self.dir / "docs" / "ASSET_LOG.md").write_text(
            "# Asset Log\n\n| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) "
            "| AI-assisted? | Modified? | Date added | Notes |\n|---|---|---|---|---|---|---|---|---|---|---|\n"
            "| A-0001 | | | | | | | no | no | 2026-01-01 | |\n", encoding="utf-8")
        fake = Fake()
        out = self.dir / "audio" / "ghost.wav"
        rc, text = self.run_tool(fake, "say", "--voice", "v1", "--text", "Who's there?", "--text", "Gotcha.",
                                 "--out", out, "--log", "--root", self.dir)
        self.assertEqual(rc, 0, text)
        self.assertEqual(sum(1 for c in fake.calls if c[0] == "POST"), 2)
        self.assertTrue((self.dir / "audio" / "ghost_1.wav").is_file())
        self.assertTrue((self.dir / "audio" / "ghost_2.wav").is_file())
        log = (self.dir / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8")
        self.assertIn("| A-0001 | voice | `audio/ghost_1.wav`, `audio/ghost_2.wav` | Fish Audio API", log)
        self.assertIn("pre-generated", log)
        self.assertIn("Who's there?", (self.dir / "docs" / "licenses" / "A-0001.txt").read_text(encoding="utf-8"))
        self.assertNotIn(KEY, log)

    def test_log_outside_a_project_is_usage_error(self):
        rc, text = self.run_tool(Fake(), "say", "--voice", "v", "--text", "x", "--out", self.dir / "a.wav",
                                 "--log", "--root", self.dir)
        self.assertEqual(rc, 2)
        self.assertIn("ASSET_LOG.md not found", text)

    def test_key_never_written_or_printed(self):
        out_path = self.dir / "a.mp3"
        rc, out = self.run_tool(Fake(), "say", "--voice", "v", "--text", "x", "--out", out_path, "--debug")
        self.assertEqual(rc, 0, out)
        self.assertNotIn(KEY, out)
        self.assertNotIn(KEY, out_path.with_suffix(".gen.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
