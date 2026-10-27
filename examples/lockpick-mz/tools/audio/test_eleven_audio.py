#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_eleven_audio.py
# Purpose : Exam for eleven_audio.py, offline: the HTTP call is replaced by canned responses, so no
#           account, key or credits are used. Checks requests, saving, loops, plan-based licensing,
#           ASSET_LOG rows, error mapping, and that the API key never lands in any output.
# Usage   : python tools/audio/test_eleven_audio.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import math
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eleven_audio as ea  # noqa: E402
from wavfile import read_wav_channels  # noqa: E402

KEY = "sk_exam_DO_NOT_LEAK_1234"
LOG = """# Asset Log

| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) | AI-assisted? | Modified? | Date added | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | | | | | | | no | no | 2026-01-01 | |

## Rules
"""


def tone_pcm(seconds, rate, freq=220.0):
    """Stereo, interleaved L R, like the real API (the right channel slightly quieter)."""
    n = int(seconds * rate)
    frames = [int(12000 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)]
    return struct.pack(f"<{2 * n}h", *(v for f in frames for v in (f, int(f * 0.8))))


class Fake:
    """Stands in for eleven_audio.http: records calls, answers from a script."""

    def __init__(self, tier="creator", status="active", audio=b"ID3fake-mp3", sub_status=200, gen_status=200,
                 gen_body=None):
        self.calls = []
        self.tier, self.status, self.audio = tier, status, audio
        self.sub_status, self.gen_status, self.gen_body = sub_status, gen_status, gen_body

    def __call__(self, method, url, key, body=None):
        self.calls.append((method, url, key, body))
        if url.endswith("/v1/user/subscription"):
            if self.sub_status != 200:
                return self.sub_status, {}, b'{"detail": {"status": "missing_permissions"}}'
            return 200, {}, json.dumps({"tier": self.tier, "status": self.status, "character_count": 100,
                                        "character_limit": 10000,
                                        "next_character_count_reset_unix": 1800000000}).encode()
        if self.gen_status != 200:
            return self.gen_status, {}, self.gen_body or b'{"detail": "nope"}'
        return 200, {"X-Trace-Id": "req_1", "character-cost": "42"}, self.audio


class ElevenAudioExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "ASSET_LOG.md").write_text(LOG, encoding="utf-8")
        self.real_http, self.real_key = ea.http, ea.get_key
        ea.get_key = lambda: KEY
        self.cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.cwd)
        ea.http, ea.get_key = self.real_http, self.real_key
        self.tmp.cleanup()

    def run_tool(self, fake, *args):
        ea.http = fake
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = ea.main([str(a) for a in args])
        return rc, out.getvalue() + err.getvalue()

    def everything_written(self):
        return "".join(p.read_text(encoding="utf-8", errors="replace") for p in self.root.rglob("*")
                       if p.is_file() and p.suffix in (".json", ".md", ".txt"))

    def test_sfx_request_and_mp3_saved_with_sidecar(self):
        fake = Fake()
        rc, out = self.run_tool(fake, "sfx", "--text", "door creaks", "--seconds", 2, "--out", "sfx/door.mp3")
        self.assertEqual(rc, 0, out)
        method, url, key, body = fake.calls[-1]
        self.assertEqual((method, key), ("POST", KEY))
        self.assertIn("/v1/sound-generation?output_format=mp3_44100_128", url)
        self.assertEqual(body, {"text": "door creaks", "model_id": ea.SFX_MODEL, "prompt_influence": 0.3,
                                "duration_seconds": 2.0})
        self.assertEqual((self.root / "sfx/door.mp3").read_bytes(), b"ID3fake-mp3")
        side = json.loads((self.root / "sfx/door.gen.json").read_text(encoding="utf-8"))
        self.assertEqual(side["request"]["text"], "door creaks")
        self.assertIn("commercial", side["license"])
        self.assertEqual(side["request_id"], "req_1")
        self.assertEqual(side["credits"], "42")
        self.assertIn("cost 42 credits", out)

    def test_music_wav_from_pcm_with_crossfade_loop(self):
        fake = Fake(audio=tone_pcm(6.0, 24000))
        rc, out = self.run_tool(fake, "music", "--prompt", "music box", "--seconds", 6, "--instrumental",
                                "--format", "pcm_24000", "--out", "m/night.wav", "--loop-crossfade", 1)
        self.assertEqual(rc, 0, out)
        body = fake.calls[-1][3]
        self.assertEqual(body["music_length_ms"], 6000)
        self.assertTrue(body["force_instrumental"])
        s, rate, loop, channels = read_wav_channels(self.root / "m/night.wav")
        self.assertEqual((rate, channels), (24000, 2), "stereo kept")
        frames = len(s) // 2
        self.assertAlmostEqual(frames / rate, 5.0, places=2, msg="crossfade shortens by its length")
        self.assertEqual(loop, (0, frames - 1), "loop points count frames, not samples")
        self.assertLess(abs(s[0] - s[-2]) + abs(s[1] - s[-1]), 0.1, "end must flow into the start, per channel")

    def test_pcm_length_is_right_and_mono_downmixes(self):
        # Met for real: reading the API's stereo PCM as mono doubled the length and garbled the sound
        rc, out = self.run_tool(Fake(audio=tone_pcm(1.0, 22050)), "sfx", "--text", "x", "--format", "pcm_22050",
                                "--out", "s.wav")
        self.assertEqual(rc, 0, out)
        s, rate, _, channels = read_wav_channels(self.root / "s.wav")
        self.assertAlmostEqual(len(s) / channels / rate, 1.0, places=2)
        rc, out = self.run_tool(Fake(audio=tone_pcm(1.0, 22050)), "sfx", "--text", "x", "--format", "pcm_22050",
                                "--out", "m.wav", "--mono")
        self.assertEqual(rc, 0, out)
        s, rate, _, channels = read_wav_channels(self.root / "m.wav")
        self.assertEqual(channels, 1)
        self.assertAlmostEqual(len(s) / rate, 1.0, places=2)

    def test_format_must_fit_the_file_before_spending(self):
        # Kimi's audit: pcm_garbage spent a request then failed; pcm into .mp3 wrote a WAV under an .mp3 name
        for out, fmt in (("a.wav", "pcm_garbage"), ("a.mp3", "pcm_44100"), ("a.wav", "mp3_44100_128"),
                         ("a.mp3", "mp3_fast")):
            fake = Fake()
            rc, text = self.run_tool(fake, "sfx", "--text", "x", "--format", fmt, "--out", out)
            self.assertEqual(rc, 2, (out, fmt))
            self.assertIn("does not fit", text)
            self.assertEqual(fake.calls, [], "nothing sent")
        rc, text = self.run_tool(Fake(), "sfx", "--text", "x", "--out", "a.ogg")
        self.assertEqual(rc, 2)

    def test_mp3_options_rejected_before_spending(self):
        fake = Fake()
        rc, out = self.run_tool(fake, "sfx", "--text", "x", "--out", "a.mp3", "--mono")
        self.assertEqual(rc, 2)
        self.assertEqual(fake.calls, [], "nothing sent")

    def test_crossfade_needs_wav(self):
        fake = Fake()
        rc, out = self.run_tool(fake, "music", "--prompt", "x", "--out", "m.mp3", "--loop-crossfade", 1)
        self.assertEqual(rc, 2)
        self.assertIn(".wav", out)
        self.assertEqual(fake.calls, [], "nothing sent")

    def test_wav_out_needs_pcm_format(self):
        rc, out = self.run_tool(Fake(), "sfx", "--text", "x", "--format", "mp3_44100_128", "--out", "a.wav")
        self.assertEqual(rc, 2)
        self.assertIn("pcm_", out)

    def test_dry_run_sends_nothing_and_needs_no_key(self):
        ea.get_key = lambda: None
        fake = Fake()
        rc, out = self.run_tool(fake, "music", "--prompt", "calm", "--out", "a.mp3", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertEqual(fake.calls, [])
        self.assertIn("/v1/music", out)
        self.assertFalse((self.root / "a.mp3").exists())

    def test_missing_key_explains_how_to_set_it(self):
        ea.get_key = lambda: None
        rc, out = self.run_tool(Fake(), "sfx", "--text", "x", "--out", "a.mp3")
        self.assertEqual(rc, 2)
        self.assertIn(ea.KEY_ENV, out)
        self.assertIn("Never put it in the project", out)

    def test_log_paid_plan_adds_row_and_evidence(self):
        rc, out = self.run_tool(Fake(), "sfx", "--text", "coin", "--out", "assets/sfx/coin.mp3", "--log")
        self.assertEqual(rc, 0, out)
        log = (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8")
        self.assertIn("| A-0001 | sfx | `assets/sfx/coin.mp3` | ElevenLabs API (/v1/sound-generation) |", log)
        self.assertIn("pre-generated", log)
        self.assertNotIn("PLACEHOLDER", log)
        ev = (self.root / "docs/licenses/A-0001.txt").read_text(encoding="utf-8")
        self.assertIn("creator (active)", ev)
        self.assertIn("SHA-256", ev)

    def test_log_free_plan_is_placeholder_with_credit(self):
        rc, out = self.run_tool(Fake(tier="free", status="free"), "sfx", "--text", "coin", "--out", "assets/c.mp3",
                                "--log")
        self.assertEqual(rc, 0, out)
        log = (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8")
        self.assertIn("PLACEHOLDER", log)
        self.assertIn(ea.FREE_ATTRIBUTION, log)
        self.assertIn("non-commercial", out)

    def test_log_with_unknown_plan_stops_before_spending(self):
        fake = Fake(sub_status=401)
        rc, out = self.run_tool(fake, "sfx", "--text", "x", "--out", "assets/x.mp3", "--log")
        self.assertEqual(rc, 2)
        self.assertIn("--plan", out)
        self.assertFalse(any(c[0] == "POST" for c in fake.calls), "no credits spent")
        rc, out = self.run_tool(Fake(sub_status=401), "sfx", "--text", "x", "--out", "assets/x.mp3", "--log",
                                "--plan", "paid")
        self.assertEqual(rc, 0, out)

    def test_variants_make_one_request_each(self):
        fake = Fake()
        rc, out = self.run_tool(fake, "sfx", "--text", "x", "--variants", 3, "--out", "a/hit.mp3")
        self.assertEqual(rc, 0, out)
        self.assertEqual(sum(1 for c in fake.calls if c[0] == "POST"), 3)
        for i in (1, 2, 3):
            self.assertTrue((self.root / f"a/hit_{i}.mp3").is_file())

    def test_errors_map_to_exit_codes(self):
        cases = [(401, b'{"detail": {"status": "invalid_api_key"}}', 2, "rejected"),
                 (422, b'{"detail": [{"loc": ["body", "text"], "msg": "field required"}]}', 2, "body.text"),
                 (429, b'{"detail": {"message": "quota exceeded"}}', 2, "quota exceeded"),
                 (402, b'{"detail": {"message": "Music API is not available for free users."}}', 2,
                  "plan does not include"),
                 (500, b"oops", 1, "try again")]
        for status, body, code, text in cases:
            rc, out = self.run_tool(Fake(gen_status=status, gen_body=body), "sfx", "--text", "x", "--out", "a.mp3",
                                    "--overwrite")
            self.assertEqual(rc, code, status)
            self.assertIn(text, out)

    def test_existing_file_not_overwritten(self):
        (self.root / "a.mp3").write_bytes(b"keep")
        rc, out = self.run_tool(Fake(), "sfx", "--text", "x", "--out", "a.mp3")
        self.assertEqual(rc, 2)
        self.assertEqual((self.root / "a.mp3").read_bytes(), b"keep")

    def test_check_reports_plan(self):
        rc, out = self.run_tool(Fake(tier="free", status="free"), "check")
        self.assertEqual(rc, 0, out)
        self.assertIn("plan free", out)
        self.assertIn("non-commercial", out)

    def test_key_never_written_or_printed(self):
        rc, out = self.run_tool(Fake(), "sfx", "--text", "x", "--out", "assets/x.mp3", "--log", "--debug")
        self.assertEqual(rc, 0, out)
        self.assertNotIn(KEY, out)
        self.assertNotIn(KEY, self.everything_written())

    def test_out_of_range_lengths_are_usage_errors(self):
        for args in (("sfx", "--text", "x", "--seconds", 31, "--out", "a.mp3"),
                     ("music", "--prompt", "x", "--seconds", 2, "--out", "a.mp3")):
            rc, _ = self.run_tool(Fake(), *args)
            self.assertEqual(rc, 2, args)


if __name__ == "__main__":
    unittest.main(verbosity=1)
