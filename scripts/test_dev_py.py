#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_dev_py.py
# Purpose : Exam for the engines' tools/dev.py wrappers (engines/<id>/skeleton/tools/dev.py), the parts that can be
#           checked without the engine: each module is loaded from its file and its helpers run against a temp
#           folder with the engine call faked. Covers smoke and capture checks (a run that ended early, a stale or
#           missing screenshot, no recorded frames; #33) and `run` exiting 2 when the launcher is missing.
# Usage   : python scripts/test_dev_py.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only, offline, no engine needed. The live checks (a real smoke with each toolchain) are
#           in the kit's release routine; this exam keeps the logic honest between them.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import argparse
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
ENGINES = ["bevy", "cpp-sdl2", "godot", "love2d", "rpgmaker-mz", "unity", "unreal", "web", "web-3d"]


def load(engine):
    """A fresh copy of one engine's dev.py as a module (module-level state is per test)."""
    path = KIT / "engines" / engine / "skeleton" / "tools" / "dev.py"
    spec = importlib.util.spec_from_file_location("dev_" + engine.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def quiet(fn, *args, **kwargs):
    """Call fn with stdout and stderr captured. Returns (result, printed text)."""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        result = fn(*args, **kwargs)
    return result, buf.getvalue()


class TempRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


# ---- #33: C++ smoke -----------------------------------------------------------
class CppSmoke(TempRoot):
    FULL = "[INFO][core] BOOT_OK Test v0.1.0\n[INFO][core] smoke complete after 120 frames\n"
    EARLY = "[INFO][core] BOOT_OK Test v0.1.0\nRUN_WON\n[INFO][core] smoke ended early: the game quit after 40 of 120 frames\n"

    def smoke(self, out, rc=0, writes=(), **opts):
        dev = load("cpp-sdl2")
        dev.ROOT = self.root
        dev.cmd_check = lambda args: 0
        dev.find_exe = lambda preset: "game.exe"

        def fake_run(cmd, **kwargs):
            for rel in writes:                  # what the game would save this run
                p = self.root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"BM fake")
            return rc, out
        dev.run = fake_run
        args = argparse.Namespace(preset="debug", frames=120, screenshot=None, record=None, record_every=4,
                                  game_args=[], timeout=60, until=None, fail_on=None)
        for k, v in opts.items():
            setattr(args, k, v)
        return quiet(dev.cmd_smoke, args)

    def test_full_run_passes(self):
        self.assertEqual(self.smoke(self.FULL)[0], 0)

    def test_no_end_line_fails(self):
        rc, text = self.smoke("[INFO][core] BOOT_OK Test v0.1.0\n")
        self.assertEqual(rc, 1)
        self.assertIn("no end-of-run line", text)

    def test_early_quit_needs_until(self):
        rc, text = self.smoke(self.EARLY)
        self.assertEqual(rc, 1)
        self.assertIn("quit after 40 of 120", text)
        self.assertEqual(self.smoke(self.EARLY, until="RUN_WON")[0], 0)
        # a game whose main.cpp predates the end line still passes a scenario that reached its marker
        self.assertEqual(self.smoke("BOOT_OK Test\nRUN_WON\n", until="RUN_WON")[0], 0)

    def test_stale_screenshot_fails(self):
        shot = self.root / "captures" / "shot.bmp"
        shot.parent.mkdir()
        shot.write_bytes(b"old picture")
        rc, text = self.smoke(self.FULL, screenshot="captures/shot.bmp")
        self.assertEqual(rc, 1)
        self.assertIn("no screenshot written", text)
        self.assertEqual(self.smoke(self.FULL, screenshot="captures/shot.bmp", writes=["captures/shot.bmp"])[0], 0)

    def test_no_recorded_frames_fails(self):
        rc, text = self.smoke(self.FULL, record="frames")
        self.assertEqual(rc, 1)
        self.assertIn("no frames recorded", text)
        rc, text = self.smoke(self.FULL, record="frames", writes=["frames/frame_000000.bmp"])
        self.assertEqual(rc, 0)
        self.assertIn("1 frame(s)", text)


# ---- #33: Unity smoke ---------------------------------------------------------
class UnitySmoke(TempRoot):
    def smoke(self, writes=(), rc=0, **opts):
        dev = load("unity")
        dev.ROOT = self.root

        def fake_tests(*a, **kw):
            for rel in writes:
                p = self.root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"\x89PNG fake")
            return rc
        dev.run_tests = fake_tests
        args = argparse.Namespace(screenshot=None, record=None, record_every=6, graphics=False, fail_on=None,
                                  until=None, filter="Smoke")
        for k, v in opts.items():
            setattr(args, k, v)
        return quiet(dev.cmd_smoke, args)

    def test_stale_screenshot_fails(self):
        (self.root / "Logs").mkdir()
        (self.root / "Logs" / "shot.png").write_bytes(b"from an earlier run")
        rc, text = self.smoke(screenshot="Logs/shot.png")
        self.assertEqual(rc, 1)
        self.assertIn("Finish()", text)
        self.assertEqual(self.smoke(screenshot="Logs/shot.png", writes=["Logs/shot.png"])[0], 0)

    def test_no_frames_fails(self):
        self.assertEqual(self.smoke(record="Logs/frames")[0], 1)
        self.assertEqual(self.smoke(record="Logs/frames", writes=["Logs/frames/frame_000000.png"])[0], 0)

    def test_failed_tests_pass_through(self):
        self.assertEqual(self.smoke(rc=1, screenshot="Logs/shot.png")[0], 1)


# ---- #33: Godot capture ---------------------------------------------------------
class GodotCapture(TempRoot):
    def capture(self, out="CAPTURE_DONE frames=120 saved=0\n", writes=(), **opts):
        dev = load("godot")
        dev.ROOT = self.root

        def fake_run(cmd, **kwargs):
            for rel in writes:
                p = self.root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"\x89PNG fake")
            return 0, out
        dev.run = fake_run
        args = argparse.Namespace(drive="", record_every=66, screenshot="", record="")
        for k, v in opts.items():
            setattr(args, k, v)
        return quiet(dev.capture, args, "godot", 120, [])

    def test_stale_screenshot_fails(self):
        (self.root / "captures").mkdir()
        (self.root / "captures" / "a.png").write_bytes(b"old")
        rc, text = self.capture(screenshot="captures/a.png")
        self.assertEqual(rc, 1)
        self.assertIn("no screenshot", text)
        self.assertEqual(self.capture(screenshot="captures/a.png", writes=["captures/a.png"])[0], 0)

    def test_no_frames_fails(self):
        (self.root / "rec").mkdir()
        self.assertEqual(self.capture(record="rec")[0], 1)
        self.assertEqual(self.capture(record="rec", writes=["rec/f00000.png"])[0], 0)


# ---- #33: `run` with a missing launcher ---------------------------------------
class RunLauncherMissing(TempRoot):
    def test_web_overlays_exit_2(self):
        for engine in ("web", "web-3d"):
            dev = load(engine)
            dev.ready = lambda: 0
            dev.tool = lambda *a, **kw: (127, "")
            self.assertEqual(quiet(dev.cmd_run, argparse.Namespace())[0], 2, engine)
            dev.tool = lambda *a, **kw: (130, "")
            self.assertEqual(quiet(dev.cmd_run, argparse.Namespace())[0], 0, engine)

    def test_rpgmaker_exits_2(self):
        dev = load("rpgmaker-mz")
        dev.node_problem = lambda: None
        dev.need_project = lambda: self.root
        dev.run = lambda *a, **kw: (127, "")
        self.assertEqual(quiet(dev.cmd_run, argparse.Namespace(editor=False, port=8000))[0], 2)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=2)
