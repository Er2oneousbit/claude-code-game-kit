#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_yt_transcript.py
# Purpose : Exam for yt_transcript.py, offline: canned WebVTT files and faked caption methods, never YouTube.
#           Checks video id parsing, that WebVTT cue identifiers and NOTE / STYLE / REGION blocks stay out of the
#           text (inline tags, entities, ">>" marks and repeated auto-caption lines are cleaned), and that
#           --whisper without faster-whisper still returns captions when they exist and exits 2 only when
#           transcription is reached.
# Usage   : python tools/test_yt_transcript.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only. No network: subprocess.run and the caption methods are replaced.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yt_transcript as yt  # noqa: E402

VID = "dQw4w9WgXcQ"

# The shape yt-dlp writes, plus the parts of WebVTT it may pass through: cue numbers, a named cue, NOTE and STYLE
VTT = (
    "﻿WEBVTT\nKind: captions\nLanguage: en\n\n"
    "STYLE\n::cue { color: yellow }\n\n"
    "NOTE this block is a comment\nand it spans two lines\n\n"
    "1\n00:00:00.000 --> 00:00:02.000 align:start position:0%\nHello <c>there</c> &amp; welcome\n\n"
    "2\n00:00:02.000 --> 00:00:04.000\nHello <c>there</c> &amp; welcome\n\n"
    "intro-cue\n00:00:04.000 --> 00:00:06.000\n&gt;&gt; to the show\nsecond line\n\n"
    "00:00:06.000 --> 00:00:08.000\n42 is the answer\n"
)
WANT = "Hello there & welcome to the show second line 42 is the answer"


def run_main(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = yt.main(list(argv))
    return rc, out.getvalue(), err.getvalue()


class Patch:
    """Replace module attributes for one test and put them back after."""

    def __init__(self, case):
        self.saved = []
        case.addCleanup(self.undo)

    def __call__(self, obj, name, value):
        self.saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, value in reversed(self.saved):
            setattr(obj, name, value)


class VideoIds(unittest.TestCase):
    def test_forms(self):
        for s in (VID, f"https://www.youtube.com/watch?v={VID}&t=4", f"https://youtu.be/{VID}",
                  f"https://www.youtube.com/shorts/{VID}"):
            self.assertEqual(yt.video_id(s), VID, s)
        for s in ("https://example.com/watch?v=" + VID, "short", f"https://www.youtube.com/watch?v={VID}x"):
            self.assertIsNone(yt.video_id(s), s)


class WebVtt(unittest.TestCase):
    def subs(self, vtt):
        """via_ytdlp_subs with yt-dlp replaced by a writer of this VTT file."""
        patch = Patch(self)
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)

            def fake_run(cmd, **kwargs):
                (tmp / f"{VID}.en.vtt").write_bytes(vtt.encode("utf-8"))  # as written (no newline= on 3.8)
                return subprocess.CompletedProcess(cmd, 0, "", "")
            patch(yt.subprocess, "run", fake_run)
            return yt.via_ytdlp_subs(VID, "en", tmp)

    def test_cue_ids_and_note_blocks_stay_out(self):
        text, why = self.subs(VTT)
        self.assertIsNone(why)
        self.assertEqual(text, WANT)

    def test_crlf_file(self):
        self.assertEqual(self.subs(VTT.replace("\n", "\r\n"))[0], WANT)

    def test_no_file_is_a_reason(self):
        patch = Patch(self)
        patch(yt.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "ERROR: no subs"))
        with tempfile.TemporaryDirectory() as d:
            text, why = yt.via_ytdlp_subs(VID, "en", Path(d))
        self.assertIsNone(text)
        self.assertIn("ERROR: no subs", why)


class WhisperFallback(unittest.TestCase):
    def setUp(self):
        self.patch = Patch(self)
        # captions api and yt-dlp installed, faster-whisper not
        self.patch(yt, "have", lambda module: module != "faster_whisper")
        self.patch(yt, "via_ytdlp_subs", lambda vid, lang, tmp: (None, "yt-dlp subtitles: no en captions"))

    def test_captions_win_without_faster_whisper(self):
        self.patch(yt, "via_transcript_api", lambda vid, lang: ("hello from captions", None))
        rc, out, err = run_main(VID, "--whisper")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.strip(), "hello from captions")

    def test_missing_faster_whisper_is_exit_2_once_reached(self):
        self.patch(yt, "via_transcript_api", lambda vid, lang: (None, "youtube-transcript-api: disabled"))
        rc, out, err = run_main(VID, "--whisper")
        self.assertEqual(rc, 2)
        self.assertIn("[FAIL] youtube-transcript-api: disabled", err)
        self.assertIn("faster-whisper", err)
        self.assertEqual(out, "")

    def test_no_captions_without_whisper_is_exit_1(self):
        self.patch(yt, "via_transcript_api", lambda vid, lang: (None, "youtube-transcript-api: disabled"))
        rc, _, err = run_main(VID)
        self.assertEqual(rc, 1)
        self.assertIn("--whisper", err)


class YtReviewFixes(unittest.TestCase):
    """#248: yt-dlp ran with no timeout, so a stalled download hung the tool."""

    def test_a_stalled_download_ends(self):
        patch = Patch(self)

        def stall(cmd, **kwargs):
            self.assertIn("timeout", kwargs)
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        patch(yt.subprocess, "run", stall)
        with tempfile.TemporaryDirectory() as d:
            text, why = yt.via_ytdlp_subs(VID, "en", Path(d))
        self.assertIsNone(text)
        self.assertIn("no answer", why)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=2)
