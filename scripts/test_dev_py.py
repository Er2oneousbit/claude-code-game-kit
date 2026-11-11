#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_dev_py.py
# Purpose : Exam for the engines' tools/dev.py wrappers (engines/<id>/skeleton/tools/dev.py), the parts that can be
#           checked without the engine: each module is loaded from its file and its helpers run against a temp
#           folder with the engine call faked. Covers smoke and capture checks (a run that ended early, a stale or
#           missing screenshot, no recorded frames; #33), `run` exiting 2 when the launcher is missing, and on
#           Windows that a timeout ends a grandchild whose parent already exited (the job object, #36), and on
#           Linux and macOS (process-group calls faked) that killing an untimed command kills what it started (#37),
#           that the Godot build fails on a .pck holding .game-kit.json or a dev-only folder (#161), and that the
#           web, web-3d and RPG Maker MZ smoke.mjs --record leaves only this run's frames (#134; needs node), that
#           web's pseudo-plant says it fails on purpose only for the planted label (#175), a
#           refused --drive is one error (#135), web-3d's -h names the shell's scenarios as web's does (#135,
#           #175), and RPG Maker MZ's setup names the project file it copied (#136), that Unreal's test/smoke exit 1 when the editor
#           crashes before any result, not 2 "no tests matched" (#176), and that smoke --drive runs the shell's
#           drive on Unity (the drive test, run options in the environment), Bevy and Unreal (the Drive test),
#           echoes its markers and fails without DRIVE_DONE (#168), and on C++ (the scenario, data folder and
#           locale after `--`, the drive's frame budget; #269; the crash, pseudo and bug drives' lines, #275), that
#           Unreal's --screenshot and --data-dir reach the editor quoted when the path has a space (#267), and every
#           editor path from a project folder with a space too (#273), that Unreal's crash and pseudo-plant drives
#           exit 1 on purpose with their proof checked and its bug drive gets a renderer (#275), and that every smoke
#           refuses a --data-dir inside its player or build output (#263), or inside a folder its build packs into
#           the game (#271), and that Godot's dev.py refuses a Godot older than its 4.6 floor with exit 2, and that
#           Unreal's package replaces the platform's last package instead of archiving over it (#278), and that
#           Unreal's test also runs the Dotwork importer's two checks through the commandlet (#58).
# Usage   : python scripts/test_dev_py.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only, offline, no engine needed. The live checks (a real smoke with each toolchain) are
#           in the kit's release routine; this exam keeps the logic honest between them.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import argparse
import base64
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
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


# ---- #269: C++ smoke --drive (the shell's screens) --------------------------------
class CppDrive(TempRoot):
    """smoke --drive on C++: the scenario, the data folder and the locale go to the game after `--` (Game::configure
    takes them), the run gets the drive's frame budget, the proof lines are echoed and DRIVE_DONE is required."""
    DONE = ("[INFO][core] BOOT_OK Test v0.1.0\nnoise\nSETTINGS_WRITTEN D:/x/build/smoke-data/settings.json\n"
            "DRIVE_DONE menus\n[INFO][core] smoke ended early: the game quit after 900 of 6000 frames\n")

    def drive(self, out, rc=0, **opts):
        """cmd_smoke with the build and the game faked: returns (rc, text, the game's command line)."""
        dev = load("cpp-sdl2")
        dev.ROOT = self.root
        dev.cmd_check = lambda args: 0
        dev.find_exe = lambda preset: "game.exe"
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = [str(c) for c in cmd]
            seen["env"] = kwargs.get("env") or {}
            return rc, out
        dev.run = fake_run
        args = argparse.Namespace(preset="debug", frames=None, screenshot=None, record=None, record_every=4,
                                  game_args=[], timeout=60, until=None, fail_on=None, drive="menus", data_dir="",
                                  locale="")
        for k, v in opts.items():
            setattr(args, k, v)
        result, text = quiet(dev.cmd_smoke, args)
        return result, text, seen.get("cmd", []), dev

    def game_options(self, cmd):
        """What the game gets after the `--` separator."""
        return cmd[cmd.index("--") + 1:]

    def test_the_drive_goes_to_the_game_after_the_separator(self):
        stale = self.root / "build" / "smoke-data" / "settings.json"
        stale.parent.mkdir(parents=True)
        stale.write_text('{"old": true}', encoding="utf-8")
        rc, text, cmd, dev = self.drive(self.DONE, locale="fr", game_args=["--autoplay", "careful"])
        self.assertEqual(rc, 0, text)
        self.assertEqual(cmd[:3], ["game.exe", "--smoke", str(dev.DRIVE_FRAMES)], "a drive gets its own frame budget")
        data = str((self.root / "build" / "smoke-data").resolve())
        self.assertEqual(self.game_options(cmd),
                         ["--data-dir", data, "--drive", "menus", "--locale", "fr", "--autoplay", "careful"])
        self.assertFalse(stale.exists(), "the run's data folder starts empty")
        self.assertTrue(stale.parent.is_dir())
        self.assertIn("SETTINGS_WRITTEN D:/x/build/smoke-data/settings.json\n", text, "proof lines are echoed")
        self.assertIn("DRIVE_DONE menus\n", text)
        self.assertNotIn("noise", text)
        self.assertIn("drive menus", text)

    def test_no_drive_done_fails_although_the_frames_ran(self):
        out = "[INFO][core] BOOT_OK Test v0.1.0\n[INFO][core] smoke complete after 6000 frames\n"
        rc, text, _, _ = self.drive(out)
        self.assertEqual(rc, 1, text)
        self.assertIn("did not finish", text)

    def test_a_failed_drive_fails(self):
        out = "[INFO][core] BOOT_OK Test v0.1.0\nDRIVE_FAIL could not focus quit\nDRIVE_DONE menus\n"
        rc, text, _, _ = self.drive(out, rc=1)
        self.assertEqual(rc, 1, text)
        self.assertIn("DRIVE_FAIL could not focus quit", text)

    def test_a_given_data_dir_is_kept_and_relative_to_the_project(self):
        keep = self.root / "build" / "access" / "deck"
        keep.mkdir(parents=True)
        (keep / "settings.json").write_text("{}", encoding="utf-8")
        rc, text, cmd, _ = self.drive(self.DONE.replace("menus", "access:res=1280x800,pad"),
                                      drive="access:res=1280x800,pad", data_dir="build/access/deck")
        self.assertEqual(rc, 0, text)
        opts = self.game_options(cmd)
        self.assertEqual(Path(opts[opts.index("--data-dir") + 1]), keep.resolve())
        self.assertTrue((keep / "settings.json").is_file(), "--data-dir is never wiped")

    def test_an_explicit_until_beats_drive_done(self):
        out = "[INFO][core] BOOT_OK Test v0.1.0\nRUN_WON\n[INFO][core] smoke ended early: the game quit after 9 of 6000 frames\n"
        rc, text, _, _ = self.drive(out, until="RUN_WON")
        self.assertEqual(rc, 0, text)

    def test_a_plain_smoke_has_no_drive(self):
        out = "[INFO][core] BOOT_OK Test v0.1.0\n[INFO][core] smoke complete after 120 frames\n"
        rc, text, cmd, dev = self.drive(out, drive="")
        self.assertEqual(rc, 0, text)
        self.assertEqual(cmd[2], str(dev.SMOKE_FRAMES))
        self.assertNotIn("--drive", cmd)
        self.assertEqual(self.game_options(cmd)[0], "--data-dir", "a plain smoke has its own data folder too")


# ---- #275: C++ crash files, the F8 bug report and the pseudo locale -------------------
class CppReports(TempRoot):
    """The #275 drives on C++: their proof lines are echoed, crash and pseudo-plant fail on purpose and say so, a
    pseudo pass and a bug report pass."""
    BOOT = "[INFO][core] BOOT_OK Test v0.1.0\n"
    drive = CppDrive.drive                     # the same faked build and game as CppDrive
    game_options = CppDrive.game_options

    def test_crash_echoes_the_file_and_fails_on_purpose(self):
        out = (self.BOOT + "CRASH_WRITTEN D:/x/build/smoke-data/crashes/crash_20261110_101500.txt\n"
               "[ERROR][core] the game stopped: exception: drive crash (expected)\n")
        rc, text, cmd, _ = self.drive(out, rc=1, drive="crash")
        self.assertEqual(rc, 1, text)
        self.assertEqual(self.game_options(cmd)[2:4], ["--drive", "crash"])
        self.assertIn("CRASH_WRITTEN D:/x/build/smoke-data/crashes/crash_20261110_101500.txt\n", text)
        self.assertIn("fails on purpose", text)

    def test_a_crash_in_another_drive_is_not_called_on_purpose(self):
        out = self.BOOT + "CRASH_WRITTEN D:/x/crashes/crash_1.txt\n[ERROR][core] the game stopped: exception: oops\n"
        rc, text, _, _ = self.drive(out, rc=1, drive="menus")
        self.assertEqual(rc, 1, text)
        self.assertIn("CRASH_WRITTEN D:/x/crashes/crash_1.txt", text)
        self.assertNotIn("on purpose", text)

    def test_pseudo_pass_and_the_planted_failure(self):
        ok = (self.BOOT + "PSEUDO_SCREEN title labels 3 problems 0\nPSEUDO_PASS 21 screens, 389 labels, nothing truncated"
              " or untranslated\nDRIVE_DONE pseudo\n")
        rc, text, cmd, _ = self.drive(ok, drive="pseudo", locale="pseudo")
        self.assertEqual(rc, 0, text)
        self.assertEqual(self.game_options(cmd)[2:], ["--drive", "pseudo", "--locale", "pseudo"])
        self.assertIn("PSEUDO_PASS 21 screens", text)
        planted = (self.BOOT + 'PSEUDO_FAIL main_menu label plant.too_small: wider than its box ("[Settings~~~~]")\n'
                   "PSEUDO_FAILED 1 problem(s) on 21 screens\n[ERROR][pseudo] 1 label problem(s)\nDRIVE_DONE pseudo-plant\n")
        rc, text, _, _ = self.drive(planted, drive="pseudo-plant", locale="pseudo")
        self.assertEqual(rc, 1, text)
        self.assertIn("PSEUDO_FAIL main_menu label plant.too_small", text)
        self.assertIn("fails on purpose", text)

    def test_the_bug_report_lines_are_echoed(self):
        out = (self.BOOT + "BUG_REPORT D:/x/build/smoke-data/bug_20261110_101500\n"
               "DRIVE_BUG D:/x/build/smoke-data/bug_20261110_101500\nDRIVE_DONE bug\n")
        rc, text, _, _ = self.drive(out, drive="bug")
        self.assertEqual(rc, 0, text)
        self.assertIn("BUG_REPORT D:/x/build/smoke-data/bug_20261110_101500\n", text)
        self.assertIn("DRIVE_BUG D:/x/build/smoke-data/bug_20261110_101500\n", text)

    def test_help_names_the_new_drives(self):
        dev = load("cpp-sdl2")
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            try:
                dev.build_parser().parse_args(["smoke", "-h"])
            except SystemExit:
                pass
        text = " ".join(buf.getvalue().split())
        for name in ("crash (", "pseudo (", "pseudo-plant (", "bug (", "show:<title|menu|settings|pause|subtitle|play|juice>"):
            self.assertIn(name, text)


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


# ---- #168: Unity smoke --drive (the shell's screens) ------------------------------
class UnityDrive(TempRoot):
    def drive(self, drive, **opts):
        """cmd_smoke with run_tests faked: returns (rc, text, the run_tests call's keyword arguments)."""
        dev = load("unity")
        dev.ROOT = self.root
        dev.LOG_FILE = self.root / "Logs" / "dev_unity.log"
        seen = {}

        def fake_tests(platform, filt, graphics=False, env=None, until=None, fail_on=None):
            seen.update(platform=platform, filt=filt, env=dict(env or {}), until=until, fail_on=list(fail_on or []))
            dev.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            dev.LOG_FILE.write_text(f"noise\nDRIVE_DONE {drive}\nUnityEngine.Debug:Log (object)\n", encoding="utf-8")
            return 0
        dev.run_tests = fake_tests
        args = argparse.Namespace(screenshot=None, record=None, record_every=6, graphics=False, fail_on=None,
                                  until=None, filter="Smoke", drive=drive, data_dir="", locale="")
        for k, v in opts.items():
            setattr(args, k, v)
        rc, text = quiet(dev.cmd_smoke, args)
        return rc, text, seen

    def test_a_drive_runs_its_test_with_the_run_options(self):
        rc, text, seen = self.drive("menus", locale="pseudo")
        self.assertEqual(rc, 0)
        self.assertEqual(seen["filt"], "Smoke_ShellDrive")        # not the boot test too (it would run the scene twice)
        self.assertEqual(seen["env"]["GAMEKIT_DRIVE"], "menus")
        self.assertEqual(seen["env"]["GAMEKIT_LOCALE"], "pseudo")
        self.assertEqual(seen["env"]["GAMEKIT_SMOKE"], "1")
        self.assertTrue((self.root / "Logs" / "smoke_data").is_dir(), "a fresh settings folder for the run")
        self.assertEqual(seen["until"], "DRIVE_DONE menus")
        self.assertIn("DRIVE_FAIL", seen["fail_on"])
        self.assertIn("DRIVE_DONE menus", text)                    # the marker is echoed from the Unity log
        self.assertNotIn("noise", text)

    def test_data_dir_is_kept_and_relative_to_the_project(self):
        rc, text, seen = self.drive("access:res=1280x800,pad", data_dir="captures/access/deck")
        self.assertEqual(rc, 0)
        self.assertEqual(Path(seen["env"]["GAMEKIT_DATA_DIR"]), (self.root / "captures" / "access" / "deck").resolve())

    def test_drive_names_are_checked(self):
        dev = load("unity")
        for ok in ("", "menus", "show:settings", "access", "access:res=1920x1080,scale=2,pad,read",
                   "crash", "pseudo", "pseudo-plant", "bug", "show:juice"):          # #275
            self.assertEqual(dev.drive_name(ok), ok)
        for bad in ("crashes", "show:nothing", "access:res=big", "access:pad,"):
            with self.assertRaises(argparse.ArgumentTypeError):
                dev.drive_name(bad)

    # ---- #275: the drives that fail on purpose, the new markers ----
    def planted(self, drive, log, rc):
        """cmd_smoke for a drive whose run fails on purpose: the faked test run returns rc and leaves log behind."""
        dev = load("unity")
        dev.ROOT = self.root
        dev.LOG_FILE = self.root / "Logs" / "dev_unity.log"

        def fake_tests(platform, filt, graphics=False, env=None, until=None, fail_on=None):
            dev.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            dev.LOG_FILE.write_text(log, encoding="utf-8")
            return rc
        dev.run_tests = fake_tests
        args = argparse.Namespace(screenshot=None, record=None, record_every=6, graphics=False, fail_on=None,
                                  until=None, filter="Smoke", drive=drive, data_dir="", locale="")
        return quiet(dev.cmd_smoke, args)

    def test_the_crash_drive_fails_on_purpose_with_its_proof(self):
        rc, text = self.planted("crash", "BOOT_OK title\nCRASH_WRITTEN D:/data/crashes/crash_1.txt\n", 1)
        self.assertEqual(rc, 1)
        self.assertIn("CRASH_WRITTEN D:/data/crashes/crash_1.txt", text)
        self.assertIn("fails on purpose", text)

    def test_a_crash_drive_without_a_crash_file_is_a_plain_failure(self):
        rc, text = self.planted("crash", "BOOT_OK title\n", 1)
        self.assertEqual(rc, 1)
        self.assertNotIn("fails on purpose", text)
        self.assertIn("no CRASH_WRITTEN line", text)

    def test_a_crash_drive_cannot_pass(self):
        """Even a test run that passed (the exception was not caught as a failure) is exit 1: a crash run proves a crash."""
        self.assertEqual(self.planted("crash", "CRASH_WRITTEN x\n", 0)[0], 1)

    def test_the_plant_drive_names_its_label_and_an_environment_problem_stays_exit_2(self):
        rc, text = self.planted("pseudo-plant", "PSEUDO_FAIL main_menu label /Root/PlantedLabel: clipped\n", 1)
        self.assertEqual(rc, 1)
        self.assertIn("PSEUDO_FAIL main_menu label /Root/PlantedLabel", text)
        self.assertIn("fails on purpose", text)
        self.assertEqual(self.planted("pseudo-plant", "", 2)[0], 2)

    def test_pseudo_and_bug_markers_are_echoed(self):
        log = ("PSEUDO_SCREEN title labels 3 problems 0\nPSEUDO_PASS 20 screens, 300 labels\nBUG_REPORT D:/d/bug_1\n"
               "DRIVE_BUG D:/d/bug_1\nDRIVE_DONE bug\nnoise\n")
        rc, text = self.planted("bug", log, 0)
        self.assertEqual(rc, 0)
        for line in ("PSEUDO_SCREEN title", "PSEUDO_PASS 20", "BUG_REPORT D:/d/bug_1", "DRIVE_BUG"):
            self.assertIn(line, text)
        self.assertNotIn("noise", text)

    def test_a_plain_smoke_keeps_the_old_shape(self):
        dev = load("unity")
        dev.ROOT = self.root
        dev.LOG_FILE = self.root / "Logs" / "dev_unity.log"
        seen = {}
        dev.run_tests = lambda platform, filt, **kw: seen.update(filt=filt, env=kw.get("env")) or 0
        args = argparse.Namespace(screenshot=None, record=None, record_every=6, graphics=False, fail_on=None,
                                  until=None, filter="Smoke", drive="", data_dir="", locale="")
        self.assertEqual(quiet(dev.cmd_smoke, args)[0], 0)
        self.assertEqual(seen["filt"], "Smoke")
        self.assertEqual(seen["env"], {})


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


# ---- #176: Unreal test/smoke tell a crash from an empty filter -----------------
class UnrealAutomation(TempRoot):
    def automation(self, rc, log=""):
        dev = load("unreal")
        dev.ROOT = self.root
        dev.AUTOMATION_LOG = self.root / "Saved" / "Logs" / "dev_automation.log"
        exe = self.root / "UnrealEditor-Cmd.exe"
        exe.write_bytes(b"")
        dev.preflight = lambda *a, **kw: None
        dev.editor_cmd = lambda plat: exe
        dev.find_uproject = lambda: self.root / "Test.uproject"

        def fake_run(cmd, **kwargs):            # the editor writes its results to -abslog, then exits rc
            dev.AUTOMATION_LOG.write_text(log, encoding="utf-8")
            return rc, ""
        dev.run = fake_run
        return quiet(dev.run_automation, "Test", argparse.Namespace(platform=None))

    def test_crash_before_any_result_exits_1(self):
        rc, text = self.automation(3, "LogInit: Display: Starting\n")
        self.assertEqual(rc, 1, text)
        self.assertIn("exited with code 3 before any test finished", text)
        self.assertNotIn("no tests matched", text)

    def test_empty_filter_stays_exit_2(self):
        rc, text = self.automation(0, "LogInit: Display: Starting\n")
        self.assertEqual(rc, 2, text)
        self.assertIn("no tests matched", text)
        # UE 5.8 exits 255 on an empty filter, after logging that nothing matched: still a setup gap
        rc, text = self.automation(255, "LogAutomationCommandLine: Error: No automation tests matched 'Test'\n")
        self.assertEqual(rc, 2, text)
        self.assertIn("no tests matched", text)

    def test_passing_tests_pass(self):
        rc, text = self.automation(0, "Test Completed. Result={Success} Name={A}\n")
        self.assertEqual(rc, 0, text)

    def test_a_crash_after_some_passed_tests_fails(self):
        """#250: a non-zero exit counted only when no test had passed: a crash after two passes was [ OK ]."""
        log = ("Test Completed. Result={Success} Name={A}\nTest Completed. Result={Success} Name={B}\n"
               "LogWindows: Error: Unhandled Exception: EXCEPTION_ACCESS_VIOLATION\n")
        rc, text = self.automation(3, log)
        self.assertEqual(rc, 1, text)
        self.assertIn("after 2 test(s) passed", text)

    def test_a_test_named_test_failed_is_not_a_failure(self):
        """#250: the pattern \\bTest Failed\\b matched a passing test's own name."""
        rc, text = self.automation(0, "Test Completed. Result={Success} Name={Test Failed Handling}\n")
        self.assertEqual(rc, 0, text)


# ---- #58: Unreal test also runs the Dotwork importer's checks through the commandlet ----------
class UnrealDotworkChecks(TempRoot):
    def dev(self, plugins=("PythonScriptPlugin",), folder=True, auto=0, nothing_ran=False, checks=0):
        dev = load("unreal")
        dev.ROOT = self.root
        (self.root / "Test.uproject").write_text(
            '{"Plugins": [%s]}' % ",".join('{"Name": "%s", "Enabled": true}' % p for p in plugins), encoding="utf-8")
        dev.find_uproject = lambda: self.root / "Test.uproject"
        if folder:
            (self.root / dev.DOTWORK_DIR).mkdir(parents=True, exist_ok=True)
        else:
            shutil.rmtree(self.root / dev.DOTWORK_DIR, ignore_errors=True)
        ran = []

        def fake_automation(filter_, args, **kw):
            dev.NOTHING_RAN[0] = nothing_ran
            return auto
        dev.run_automation = fake_automation
        dev.exec_script = lambda script, args: ran.append(script.name) or checks
        self.ran = ran
        return dev

    def run_test(self, dev, filter_=None):
        return quiet(dev.cmd_test, argparse.Namespace(filter=filter_, platform=None))

    def test_both_checks_run_after_the_automation(self):
        rc, text = self.run_test(self.dev())
        self.assertEqual(rc, 0, text)
        self.assertEqual(self.ran, ["test_dotwork_golden.py", "test_dotwork_manifests.py"])

    def test_a_failing_check_fails_test(self):
        self.assertEqual(self.run_test(self.dev(checks=1))[0], 1)
        self.assertEqual(self.run_test(self.dev(auto=1))[0], 1)

    def test_no_automation_tests_but_passing_checks_pass(self):
        """A Blueprint-only game without tests of its own: the Dotwork checks still ran, so not "nothing ran"."""
        self.assertEqual(self.run_test(self.dev(auto=2, nothing_ran=True))[0], 0)
        self.assertEqual(self.run_test(self.dev(auto=2, nothing_ran=False))[0], 2)   # a setup problem stays 2

    def test_skipped_without_python_or_importer_or_with_a_filter(self):
        rc, text = self.run_test(self.dev(plugins=()))
        self.assertEqual((rc, self.ran), (0, []))
        self.assertIn("PythonScriptPlugin", text)
        rc, _ = self.run_test(self.dev(folder=False))
        self.assertEqual((rc, self.ran), (0, []))
        rc, _ = self.run_test(self.dev(), filter_="Test.Logic")
        self.assertEqual((rc, self.ran), (0, []))


class UnrealRunTeeTimeout(TempRoot):
    def test_a_hung_build_is_stopped(self):
        """#250: build, package and project files had no timeout; run_tee now stops a hang."""
        dev = load("unreal")
        dev.ROOT = self.root
        start = time.monotonic()
        rc, _ = quiet(dev.run_tee, [sys.executable, "-c", "import time; print('x', flush=True); time.sleep(60)"],
                      timeout=2)[0]
        self.assertEqual(rc, 124)
        self.assertLess(time.monotonic() - start, 30)


# ---- #168: Unreal smoke --drive runs the shell's screens through the plugin's Drive test ----------
class UnrealDrive(TempRoot):
    def drive(self, log, rc=0, plugin="enabled", writes=(), **opts):
        dev = load("unreal")
        dev.ROOT = self.root
        dev.AUTOMATION_LOG = self.root / "Saved" / "Logs" / "dev_automation.log"
        exe = self.root / "UnrealEditor-Cmd.exe"
        exe.write_bytes(b"")
        dev.preflight = lambda *a, **kw: None
        dev.editor_cmd = lambda plat: exe
        dev.find_uproject = lambda: self.root / "Test.uproject"
        dev.kit_plugin_state = lambda: plugin
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = [str(c) for c in cmd]
            dev.AUTOMATION_LOG.parent.mkdir(parents=True, exist_ok=True)
            dev.AUTOMATION_LOG.write_text(log, encoding="utf-8")
            for rel in writes:
                p = self.root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"\x89PNG fake")
            return rc, ""
        dev.run = fake_run
        args = argparse.Namespace(platform=None, filter=None, until=None, fail_on=None, shaders=False, drive="menus",
                                  screenshot="", data_dir="", locale="")
        for k, v in opts.items():
            setattr(args, k, v)
        result, text = quiet(dev.cmd_smoke, args)
        return result, text, seen.get("cmd", [])

    PASS = ("[2026.11.09-10.00.00:000][  0]LogGameKitShell: Display: SETTINGS_WRITTEN D:/x/Saved/GameKitSmoke/settings.json\n"
            "[2026.11.09-10.00.00:000][  0]LogGameKitShell: Display: DRIVE_DONE menus\n"
            "Test Completed. Result={Success} Name={Drive} Path={GameKit.Screens.Drive}\n")

    def test_the_drive_test_runs_with_the_name_and_echoes_markers(self):
        rc, text, cmd = self.drive(self.PASS)
        self.assertEqual(rc, 0, text)
        self.assertIn("Automation RunTests GameKit.Screens.Drive;", " ".join(cmd))
        self.assertIn("-GameKitDrive=menus", cmd)
        self.assertTrue(any(c.startswith("-GameKitDataDir=") and c.endswith("Saved/GameKitSmoke") for c in cmd), cmd)
        self.assertIn("-NullRHI", cmd)
        self.assertIn("SETTINGS_WRITTEN D:/x/Saved/GameKitSmoke/settings.json\n", text)
        self.assertIn("DRIVE_DONE menus\n", text)
        self.assertNotIn("LogGameKitShell", text, "the log prefix is stripped from the echoed lines")

    def test_no_drive_done_fails(self):
        rc, text, _ = self.drive("Test Completed. Result={Success} Name={Drive}\n")
        self.assertEqual(rc, 1, text)
        self.assertIn("did not finish", text)

    def test_a_failed_drive_fails(self):
        log = "LogGameKitShell: Display: DRIVE_FAIL could not focus quit\nLogGameKitShell: Display: DRIVE_DONE menus\nResult={Fail} Name={Drive}\n"
        rc, text, _ = self.drive(log, rc=255)
        self.assertEqual(rc, 1, text)

    def test_the_plugin_must_be_enabled(self):
        rc, text, cmd = self.drive(self.PASS, plugin="disabled")
        self.assertEqual(rc, 2, text)
        self.assertEqual(cmd, [], "the editor is never started")
        self.assertIn("GameKitShell plugin enabled", text)

    def test_unsafe_names_are_refused(self):
        rc, text, cmd = self.drive(self.PASS, drive="menus; Quit")
        self.assertEqual(rc, 2, text)
        self.assertEqual(cmd, [])

    def test_a_screenshot_runs_the_show_test_with_a_renderer(self):
        log = "LogGameKitShell: Display: DRIVE_DONE show:settings\nResult={Success} Name={Show}\n"
        rc, text, cmd = self.drive(log, drive="show:settings", screenshot="captures/s.png", writes=["captures/s.png"])
        self.assertEqual(rc, 0, text)
        self.assertIn("Automation RunTests GameKit.Screens.Show;", " ".join(cmd))
        self.assertIn("-RenderOffScreen", cmd)
        self.assertNotIn("-NullRHI", cmd)
        self.assertTrue(any(c.startswith("-GameKitScreenshot=") and c.endswith("captures/s.png") for c in cmd), cmd)
        self.assertIn("screenshot:", text)

    def test_a_missing_screenshot_fails(self):
        log = "LogGameKitShell: Display: DRIVE_DONE show:settings\nResult={Success} Name={Show}\n"
        rc, text, _ = self.drive(log, drive="show:settings", screenshot="captures/s.png")
        self.assertEqual(rc, 1, text)
        self.assertIn("no screenshot was written", text)

    def test_a_screenshot_needs_a_show_drive(self):
        rc, text, cmd = self.drive(self.PASS, drive="menus", screenshot="captures/s.png")
        self.assertEqual(rc, 2, text)
        self.assertEqual(cmd, [])
        rc, text, cmd = self.drive(self.PASS, drive="", screenshot="captures/s.png")
        self.assertEqual(rc, 2, text)

    def test_the_crash_drive_fails_on_purpose_with_its_file(self):
        """#275: crash exits 1 either way; the crash file named by CRASH_WRITTEN must be on disk to count as proof."""
        crash = self.root / "Saved" / "GameKitSmoke" / "crashes" / "crash_1.txt"
        log = (f"LogGameKitShell: Display: CRASH_WRITTEN {crash.as_posix()}\n"
               "LogGameKitShell: Display: DRIVE_FAIL drive crash: a planted error (expected)\n"
               "LogGameKitShell: Display: DRIVE_DONE crash\nResult={Fail} Name={Drive}\n"
               f"LogGameKitShell: Display: CRASH_WRITTEN {crash.as_posix()} [log] \n")   # the automation's echo
        rc, text, cmd = self.drive(log, rc=255, drive="crash", writes=["Saved/GameKitSmoke/crashes/crash_1.txt"])
        self.assertEqual(rc, 1, text)
        self.assertIn("-NullRHI", cmd)
        self.assertIn("CRASH_WRITTEN ", text)
        self.assertIn("fails on purpose", text)
        rc, text, _ = self.drive(log.replace("crash_1", "crash_gone"), rc=255, drive="crash")
        self.assertEqual(rc, 1, text)
        self.assertIn("wrote no crash file", text)

    def test_pseudo_plant_must_name_the_planted_label(self):
        log = ("LogGameKitShell: Display: PSEUDO_FAIL main_menu label plant.too_small: wider than its column\n"
               "LogGameKitShell: Display: DRIVE_DONE pseudo-plant\nResult={Fail} Name={Drive}\n")
        rc, text, _ = self.drive(log, rc=255, drive="pseudo-plant", locale="pseudo")
        self.assertEqual(rc, 1, text)
        self.assertIn("names the planted label", text)
        rc, text, _ = self.drive("LogGameKitShell: Display: DRIVE_DONE pseudo-plant\nResult={Fail} Name={Drive}\n", rc=255,
                                 drive="pseudo-plant", locale="pseudo")
        self.assertEqual(rc, 1, text)
        self.assertIn("did not name", text)

    def test_pseudo_passes_and_echoes_its_lines(self):
        log = ("LogGameKitShell: Display: PSEUDO_SCREEN title labels 3 problems 0\n"
               "LogGameKitShell: Display: PSEUDO_PASS 20 screens, 300 labels, nothing truncated or untranslated\n"
               "LogGameKitShell: Display: DRIVE_DONE pseudo\nResult={Success} Name={Drive}\n")
        rc, text, cmd = self.drive(log, drive="pseudo", locale="pseudo")
        self.assertEqual(rc, 0, text)
        self.assertIn("-GameKitLocale=pseudo", cmd)
        self.assertIn("PSEUDO_PASS 20 screens", text)

    def test_the_bug_drive_gets_a_renderer(self):
        log = ("LogGameKitShell: Display: BUG_REPORT D:/x/bug_1\nLogGameKitShell: Display: DRIVE_BUG D:/x/bug_1\n"
               "LogGameKitShell: Display: DRIVE_DONE bug\nResult={Success} Name={Drive}\n")
        rc, text, cmd = self.drive(log, drive="bug")
        self.assertEqual(rc, 0, text)
        self.assertIn("-RenderOffScreen", cmd)
        self.assertIn("Automation RunTests GameKit.Screens.Drive;", " ".join(cmd))
        self.assertIn("DRIVE_BUG D:/x/bug_1", text)
        self.assertIn("BUG_REPORT D:/x/bug_1", text)

    def test_a_stale_screenshot_is_removed_first(self):
        shot = self.root / "captures" / "s.png"
        shot.parent.mkdir()
        shot.write_bytes(b"old")
        log = "LogGameKitShell: Display: DRIVE_DONE show:title\nResult={Success} Name={Show}\n"
        rc, text, _ = self.drive(log, drive="show:title", screenshot="captures/s.png")
        self.assertEqual(rc, 1, text)
        self.assertFalse(shot.exists())


# ---- #278: Unreal package replaces the last package, so a dropped file never ships again ----------
class UnrealPackage(TempRoot):
    def package(self, rc=0, archived=("Windows/Game/data/i18n/en.json",)):
        """cmd_package with UAT faked: it writes `archived` under its -archivedirectory, as -archive does."""
        dev = load("unreal")
        dev.ROOT = self.root
        uat = self.root / "RunUAT.bat"
        uat.write_bytes(b"")
        dev.preflight = lambda *a, **kw: None
        dev.batch_file = lambda name: uat
        dev.find_uproject = lambda: self.root / "Game.uproject"
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = [str(c) for c in cmd]
            arch = Path(next(c for c in seen["cmd"] if c.startswith("-archivedirectory=")).split("=", 1)[1])
            for rel in archived:
                p = arch / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("new", encoding="utf-8")
            return rc, ""
        dev.run = fake_run
        result, text = quiet(dev.cmd_package, argparse.Namespace(platform="Win64", config="Development"))
        return result, text

    def old_package(self):
        for rel in ("Windows/Game/data/credits.md", "Windows/Game/data/i18n/en.json", "Linux/Game/keep.txt"):
            p = self.root / "Packaged" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("old", encoding="utf-8")

    def test_a_file_the_game_dropped_does_not_ship_again(self):
        self.old_package()
        rc, text = self.package()
        self.assertEqual(rc, 0, text)
        out = self.root / "Packaged"
        self.assertFalse((out / "Windows/Game/data/credits.md").exists(), "UAT -archive never empties its folder")
        self.assertEqual((out / "Windows/Game/data/i18n/en.json").read_text(encoding="utf-8"), "new")
        self.assertTrue((out / "Linux/Game/keep.txt").exists(), "another platform's package stays")
        self.assertFalse((out / ".next").exists(), "the staging folder is gone after the swap")

    def test_a_failed_package_keeps_the_last_good_one(self):
        self.old_package()
        rc, text = self.package(rc=1)
        self.assertEqual(rc, 1, text)
        out = self.root / "Packaged"
        self.assertEqual((out / "Windows/Game/data/credits.md").read_text(encoding="utf-8"), "old")
        self.assertFalse((out / ".next").exists())

    def test_success_with_nothing_archived_fails(self):
        rc, text = self.package(archived=())
        self.assertEqual(rc, 1, text)
        self.assertIn("archived nothing", text)


# ---- #267: Unreal smoke --screenshot and --data-dir take a path with a space ----------
class UnrealSpacedPaths(TempRoot):
    drive = UnrealDrive.drive               # the same faked editor, without running UnrealDrive's cases again
    PASS = UnrealDrive.PASS

    def test_a_plain_value_stays_plain(self):
        dev = load("unreal")
        arg = dev.unreal_arg("GameKitDrive", "show:settings")
        self.assertEqual(arg, "-GameKitDrive=show:settings")
        self.assertNotIsInstance(arg, dev.UnrealValue)

    def test_a_value_with_a_space_is_quoted_for_unreal(self):
        dev = load("unreal")
        arg = dev.unreal_arg("GameKitDataDir", "D:/my games/x")
        self.assertEqual(arg, '-GameKitDataDir="D:/my games/x"')
        self.assertIsInstance(arg, dev.UnrealValue)

    def test_spaced_screenshot_and_data_dir_reach_the_editor_quoted(self):
        log = "LogGameKitShell: Display: DRIVE_DONE show:settings\nResult={Success} Name={Show}\n"
        rc, text, cmd = self.drive(log, drive="show:settings", screenshot="my shots/s.png", data_dir="smoke data",
                                   writes=["my shots/s.png"])
        self.assertEqual(rc, 0, text)
        root = self.root.resolve().as_posix()
        self.assertIn(f'-GameKitScreenshot="{root}/my shots/s.png"', cmd)
        self.assertIn(f'-GameKitDataDir="{root}/smoke data"', cmd)
        self.assertTrue((self.root / "smoke data").is_dir())

    def test_a_quote_is_still_refused(self):
        rc, text, cmd = self.drive(self.PASS, locale='fr"x')
        self.assertEqual(rc, 2, text)
        self.assertEqual(cmd, [], "the editor is never started")
        self.assertIn("double quotes", text)

    def spaced_editor(self):
        """#273: dev.py loaded with its project in a folder holding a space, the editor faked. Returns (dev, calls),
        calls collecting every command the editor would get."""
        dev = load("unreal")
        dev.ROOT = self.root / "g ue"
        dev.ROOT.mkdir()
        dev.AUTOMATION_LOG = dev.ROOT / "Saved" / "Logs" / "dev_automation.log"
        dev.EXEC_LOG = dev.ROOT / "Saved" / "Logs" / "dev_exec.log"
        dev.SHADER_LOG = dev.ROOT / "Saved" / "Logs" / "dev_shaders.log"
        exe = dev.ROOT / "UnrealEditor-Cmd.exe"
        exe.write_bytes(b"")
        dev.preflight = lambda *a, **kw: None
        dev.editor_cmd = lambda plat: exe
        dev.find_uproject = lambda: dev.ROOT / "Test.uproject"
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            log = "Result={Success} Name={A}\nLogPython: SHADER_CHECK_DONE 3 0\n"
            for path in (dev.AUTOMATION_LOG, dev.EXEC_LOG, dev.SHADER_LOG):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(log, encoding="utf-8")
            return 0, ""
        dev.run = fake_run
        return dev, calls

    def test_every_editor_path_from_a_spaced_project_folder_is_quoted(self):
        """#273: -abslog= (test, smoke, exec, the shader check) and -script= reach the editor as -Key="a b" with
        forward slashes; the shader script goes by its name on sys.path, so no absolute path splits -ExecCmds."""
        dev, calls = self.spaced_editor()
        root = dev.ROOT.as_posix()
        args = argparse.Namespace(platform=None)
        self.assertEqual(quiet(dev.run_automation, "Test", args)[0], 0)
        script = dev.ROOT / "tools" / "x.py"
        script.parent.mkdir()
        script.write_text("print(1)\n", encoding="utf-8")
        self.assertEqual(quiet(dev.cmd_exec, argparse.Namespace(platform=None, script="tools/x.py"))[0], 0)
        self.assertEqual(quiet(dev.shader_editor, args, "compile")[0], 0)
        test_cmd, exec_cmd, shader_cmd = calls
        self.assertIn(f'-abslog="{root}/Saved/Logs/dev_automation.log"', test_cmd)
        self.assertIn(f'-abslog="{root}/Saved/Logs/dev_exec.log"', exec_cmd)
        self.assertIn(f'-script="{root}/tools/x.py"', exec_cmd)
        self.assertIn(f'-abslog="{root}/Saved/Logs/dev_shaders.log"', shader_cmd)
        self.assertIn("-ExecCmds=py kit_shaders/shader_check.py", shader_cmd)
        for cmd in calls:
            for c in cmd:
                if str(c).startswith(("-abslog=", "-script=")):
                    self.assertIsInstance(c, dev.UnrealValue, c)
                    self.assertNotIn("\\", str(c), "backslashes are escapes inside Unreal's quotes")

    def test_a_plain_project_folder_keeps_plain_paths(self):
        if re.search(r"\s", str(self.root)):
            self.skipTest("the temp folder itself holds a space")
        dev, calls = self.spaced_editor()
        dev.ROOT = self.root
        dev.AUTOMATION_LOG = self.root / "Saved" / "Logs" / "dev_automation.log"
        quiet(dev.run_automation, "Test", argparse.Namespace(platform=None))
        log = [c for c in calls[0] if str(c).startswith("-abslog=")]
        self.assertEqual(log, [f"-abslog={dev.AUTOMATION_LOG.as_posix()}"])
        self.assertNotIsInstance(log[0], dev.UnrealValue)

    def test_a_quote_in_the_project_folder_is_refused(self):
        dev = load("unreal")
        with self.assertRaises(ValueError):
            dev.unreal_path("abslog", 'D:/a"b/x.log')

    def test_run_passes_the_quoted_value_as_is(self):
        """The real command line the child sees: on Windows -Key="a b" exactly (no \\" escapes, not the whole
        argument in quotes), elsewhere one argv entry holding the quotes, which BuildFromArgV keeps."""
        dev = load("unreal")
        dev.ROOT = self.root
        arg = dev.unreal_arg("GameKitDataDir", "C:/a b/c")
        if sys.platform == "win32":
            probe = ("import ctypes; f = ctypes.windll.kernel32.GetCommandLineW; f.restype = ctypes.c_wchar_p; "
                     "print(f())")
        else:
            probe = "import sys; print(sys.argv[-1])"
        rc, out = quiet(dev.run, [sys.executable, "-c", probe, "-plain=x y", arg], capture=True, timeout=60)[0]
        self.assertEqual(rc, 0, out)
        self.assertIn('-GameKitDataDir="C:/a b/c"', out)
        self.assertNotIn('\\"', out)
        if sys.platform == "win32":
            self.assertIn('"-plain=x y"', out, "other arguments keep subprocess's usual quoting")


class GodotCaptureFiles(TempRoot):
    """#250: --record deleted every f*.png in its folder; capture folders were imported by Godot on every run."""

    def test_only_the_tools_own_frames_are_cleared_and_the_folder_is_ignored(self):
        dev = load("godot")
        dev.ROOT = self.root
        rec = self.root / "captures"
        rec.mkdir()
        for name in ("fox.png", "f00003.png", "frame.png", "f00003.png.import"):
            (rec / name).write_bytes(b"x")
        dev.run = lambda cmd, **kw: (0, "CAPTURE_DONE frames=1 saved=0\n")
        args = argparse.Namespace(drive="", record_every=66, screenshot="", record="captures")
        quiet(dev.capture, args, "godot", 1, [])
        left = sorted(p.name for p in rec.iterdir())
        self.assertIn("fox.png", left)
        self.assertIn("frame.png", left)
        self.assertNotIn("f00003.png", left)
        self.assertNotIn("f00003.png.import", left)
        self.assertNotIn(".gdignore", left, "#257: a folder with files of the game's own gets no .gdignore")

    def test_a_gdignore_only_in_a_folder_of_captures(self):
        """#257: --screenshot assets/shot.png wrote assets/.gdignore and hid every asset from Godot."""
        dev = load("godot")
        dev.ROOT = self.root
        dev.run = lambda cmd, **kw: (0, "CAPTURE_DONE frames=1 saved=0\n")
        (self.root / "assets").mkdir()
        (self.root / "assets" / "hero.png").write_bytes(b"x")
        args = argparse.Namespace(drive="", record_every=66, screenshot="assets/shot.png", record="")
        quiet(dev.capture, args, "godot", 1, [])
        self.assertFalse((self.root / "assets" / ".gdignore").exists())
        args = argparse.Namespace(drive="", record_every=66, screenshot="captures/shot.png", record="captures/rec")
        quiet(dev.capture, args, "godot", 1, [])
        self.assertTrue((self.root / "captures" / ".gdignore").exists())
        self.assertTrue((self.root / "captures" / "rec" / ".gdignore").exists())

    def test_a_change_just_after_an_import_is_seen(self):
        """#257: a one-second grace hid an asset changed right after the last import."""
        import os
        dev = load("godot")
        dev.ROOT = self.root
        (self.root / ".godot").mkdir()
        art = self.root / "assets" / "a.png"
        art.parent.mkdir()
        art.write_bytes(b"x")
        side = self.root / "assets" / "a.png.import"
        side.write_bytes(b"x")
        stamp = self.root / dev.CLASS_STAMP
        stamp.write_text("", encoding="utf-8")
        t0 = time.time() - 100
        for p in (side, stamp):
            os.utime(p, (t0, t0))
        os.utime(art, (t0 + 0.5, t0 + 0.5))
        self.assertEqual(dev.unimported_assets(), ["assets/a.png"])

    def test_a_touched_but_imported_asset_is_not_imported_again(self):
        import os
        dev = load("godot")
        dev.ROOT = self.root
        (self.root / ".godot").mkdir()
        art = self.root / "assets" / "a.png"
        art.parent.mkdir()
        art.write_bytes(b"x")
        (self.root / "assets" / "a.png.import").write_bytes(b"x")
        old = time.time() - 600
        os.utime(self.root / "assets" / "a.png.import", (old, old))
        self.assertEqual(dev.unimported_assets(), ["assets/a.png"])     # newer than its sidecar, no stamp yet
        (self.root / dev.CLASS_STAMP).write_text("", encoding="utf-8")   # an import ran after the touch
        self.assertEqual(dev.unimported_assets(), [])

    def test_check_resolves_files_against_the_project(self):
        dev = load("godot")
        dev.ROOT = self.root
        (self.root / "scripts").mkdir()
        (self.root / "scripts" / "a.gd").write_text("extends Node\n", encoding="utf-8")
        seen = []
        dev.ensure_imported = lambda godot: 0
        dev.run = lambda cmd, **kw: seen.append(cmd) or (0, "CHECK_DONE\n")
        args = argparse.Namespace(files=["scripts/a.gd"])
        sub = self.root / "tools"
        sub.mkdir()
        cwd = Path.cwd()
        import os
        os.chdir(sub)                                    # run from tools/, as the review did
        try:
            rc, text = quiet(dev.cmd_check, args, "godot")
            rc_out, text_out = quiet(dev.cmd_check, argparse.Namespace(files=[str(self.tmp.name) + "/../x.gd"]),
                                     "godot")
        finally:
            os.chdir(cwd)
        self.assertEqual(rc, 0, text)
        self.assertIn("res://scripts/a.gd", " ".join(" ".join(map(str, c)) for c in seen))
        self.assertEqual(rc_out, 2, text_out)


# ---- #161: Godot build lists the .pck ------------------------------------------
def fake_pck(paths, fmt=4, res_prefix=False):
    """A Godot .pck with a readable file list (the file data itself is left out: only the list is read)."""
    import struct
    entries = b""
    for p in paths:
        name = (("res://" + p) if res_prefix else p).encode("utf-8")
        name += b"\0" * (4 - len(name) % 4)                 # Godot pads each path to a multiple of 4
        entries += struct.pack("<I", len(name)) + name + struct.pack("<QQ", 0, 0) + b"\0" * 16 + struct.pack("<I", 0)
    head = b"GDPC" + struct.pack("<5I", fmt, 4, 7, 2, 0) + struct.pack("<Q", 0)
    if fmt >= 3:
        head += struct.pack("<Q", len(head) + 8)              # the list follows right after this field
    else:
        head += b"\0" * 64
    return head + struct.pack("<I", len(paths)) + entries


class GodotCheckFiles(TempRoot):
    def test_folders_godot_ignores_are_not_checked(self):
        # Dotwork ships a Pixelorama extension (Pixelorama's classes) under tools/art/dotwork/, which has a
        # .gdignore: check compiled it anyway and failed every new Godot game
        dev = load("godot")
        for rel in ("scripts/player.gd", "tools/capture.gd", "tools/art/dotwork/pixelorama_extension/Main.gd",
                    "tools/art/dotwork/.gdignore", "addons/gut/gut.gd", "assets_src/.gdignore", "assets_src/x.gd"):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text("extends Node\n", encoding="utf-8")
        old, dev.ROOT = dev.ROOT, self.root
        try:
            got = sorted(p.relative_to(self.root).as_posix() for p in dev.game_scripts())
        finally:
            dev.ROOT = old
        self.assertEqual(got, ["scripts/player.gd", "tools/capture.gd"])


class GodotImport(TempRoot):
    """#195: ensure_imported looked at class_name scripts only, so a new asset was not imported before test/smoke."""

    def setup_game(self):
        dev = load("godot")
        dev.ROOT = self.root
        calls = []
        dev.cmd_import = lambda args, godot: calls.append(godot) or 0
        (self.root / ".godot").mkdir()
        (self.root / dev.CLASS_STAMP).write_text(dev.class_names(), encoding="utf-8")
        return dev, calls

    def test_a_new_asset_is_imported_first(self):
        dev, calls = self.setup_game()
        self.assertEqual(quiet(dev.ensure_imported, "godot")[0], 0)
        self.assertEqual(calls, [], "nothing new: no import")
        (self.root / "assets").mkdir()
        (self.root / "assets" / "hero.png").write_bytes(b"\x89PNG")
        rc, text = quiet(dev.ensure_imported, "godot")
        self.assertEqual(calls, ["godot"], text)
        self.assertIn("assets/hero.png", text)

    def test_imported_ignored_and_hidden_assets_are_left_alone(self):
        dev, calls = self.setup_game()
        for rel in ("assets/a.png", "assets/a.png.import", "assets_src/.gdignore", "assets_src/raw.png",
                    ".hidden/x.wav", "build/web/icon.png", "docs/notes.txt"):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_bytes(b"x")
        old = (self.root / "assets" / "a.png").stat().st_mtime - 60
        os.utime(self.root / "assets" / "a.png", (old, old))
        self.assertEqual(dev.unimported_assets(), [])
        quiet(dev.ensure_imported, "godot")
        self.assertEqual(calls, [])
        new = (self.root / "assets" / "a.png.import").stat().st_mtime + 30   # changed after its last import
        os.utime(self.root / "assets" / "a.png", (new, new))
        self.assertEqual(dev.unimported_assets(), ["assets/a.png"])


class GodotPck(TempRoot):
    SHIPPED = ["project.binary", "scripts/core/spring.gdc", "data/i18n/en.json", ".godot/uid_cache.bin"]

    def check(self, paths, **kw):
        dev = load("godot")
        pck = self.root / "game.pck"
        pck.write_bytes(fake_pck(paths, **kw))
        return quiet(dev.check_pck, pck)

    def test_kit_record_in_the_pck_fails_the_build(self):
        rc, text = self.check(self.SHIPPED + [".game-kit.json", "tests/test_x.gd", "tools/dev.py"])
        self.assertEqual(rc, 1)
        self.assertIn("holds files that must not ship: .game-kit.json, tests/test_x.gd, tools/dev.py", text)

    def test_clean_pck_passes_in_every_format(self):
        for fmt, prefix in ((4, False), (3, False), (2, True)):
            dev = load("godot")
            pck = self.root / f"f{fmt}.pck"
            pck.write_bytes(fake_pck(self.SHIPPED, fmt=fmt, res_prefix=prefix))
            self.assertEqual(dev.pck_paths(pck), self.SHIPPED, fmt)
            self.assertEqual(quiet(dev.check_pck, pck)[0], 0, fmt)

    def test_unreadable_or_missing_pck_is_not_a_failure(self):
        dev = load("godot")
        self.assertEqual(quiet(dev.check_pck, self.root / "none.pck")[0], 0)
        (self.root / "cut.pck").write_bytes(fake_pck(self.SHIPPED)[:40])
        rc, text = quiet(dev.check_pck, self.root / "cut.pck")
        self.assertEqual(rc, 0)
        self.assertIn("could not list", text)

    def test_shipped_presets_exclude_the_kit_record(self):
        cfg = (KIT / "engines" / "godot" / "skeleton" / "export_presets.cfg").read_text(encoding="utf-8")
        filters = [l for l in cfg.splitlines() if l.startswith("exclude_filter=")]
        self.assertEqual(len(filters), 3)
        for line in filters:
            self.assertIn(".game-kit.json", line)


class GodotVersionFloor(TempRoot):
    """The floor is MIN_GODOT (4.6): 4.3 to 4.5 do not compile the shell (Control.has_focus(true) is new in 4.6), so
    every command but clean and ship, and doctor, must exit 2 with a clear message instead of parse errors."""

    def setup_dev(self, version_text):
        dev = load("godot")
        dev.ROOT = self.root
        dev.find_godot = lambda cli=None: "godot"
        calls = []

        def fake_run(cmd, capture=True, echo="fail", timeout=None):
            calls.append([str(c) for c in cmd])
            return (0, version_text) if cmd[1:] == ["--version"] else (0, "")
        dev.run = fake_run
        ran = []
        for name in ("cmd_check", "cmd_test", "cmd_smoke", "cmd_clean"):
            setattr(dev, name, lambda args, godot, name=name: ran.append(name) or 0)
        return dev, calls, ran

    def test_the_floor_is_4_6_and_project_godot_agrees(self):
        dev = load("godot")
        self.assertEqual(dev.MIN_GODOT, (4, 6))
        cfg = (KIT / "engines" / "godot" / "skeleton" / "project.godot").read_text(encoding="utf-8")
        self.assertIn('config/features=PackedStringArray("4.6")', cfg)

    def test_older_godot_is_refused_with_exit_2(self):
        for text in ("4.5.stable.official.876b29033\n", "4.4.stable.official.4c311cbee\n", "4.3.stable.official.77dcf97d8"):
            dev, calls, ran = self.setup_dev(text)
            for command in ("check", "test", "smoke"):
                rc, out = quiet(dev.main, [command])
                self.assertEqual(rc, 2, (text, command, out))
                self.assertIn("too old: this project needs Godot 4.6 or newer", out)
                self.assertIn(text.strip(), out)
                self.assertNotIn("Traceback", out)
            self.assertEqual(ran, [], "no command ran on a too old Godot")

    def test_supported_and_unknown_versions_run(self):
        for text in ("4.6.stable.official.89cea1439\n", "4.7.2.stable.official.ed1daf0bf\n", "5.0.dev1.custom\n",
                     "some custom build\n", ""):
            dev, calls, ran = self.setup_dev(text)
            rc, out = quiet(dev.main, ["smoke"])
            self.assertEqual((rc, ran), (0, ["cmd_smoke"]), (text, out))

    def test_version_after_other_lines_is_still_read(self):
        dev, calls, ran = self.setup_dev("Godot Engine v4.5.stable - https://godotengine.org\n4.5.stable.official\n")
        self.assertEqual(quiet(dev.check_godot_version, "godot")[0], 2)

    def test_clean_does_not_ask_godot(self):
        dev, calls, ran = self.setup_dev("4.3.stable.official\n")
        rc, out = quiet(dev.main, ["clean", "--yes"])
        self.assertEqual((rc, ran, calls), (0, ["cmd_clean"], []), out)

    def test_doctor_reports_and_exits_2(self):
        dev, calls, ran = self.setup_dev("4.4.stable.official.4c311cbee\n")
        (self.root / "project.godot").write_text("", encoding="utf-8")
        rc, out = quiet(dev.main, ["doctor"])
        self.assertEqual(rc, 2, out)
        self.assertIn("[FAIL] Godot 4.4.stable.official.4c311cbee is too old", out)
        self.assertIn("project.godot", out, "doctor still reports the rest")
        dev, calls, ran = self.setup_dev("4.6.stable.official.89cea1439\n")
        (self.root / "addons" / "gut").mkdir(parents=True)
        (self.root / dev.GUT_CMDLN).write_text("", encoding="utf-8")
        (self.root / ".godot").mkdir()
        rc, out = quiet(dev.main, ["doctor"])
        self.assertEqual(rc, 0, out)
        self.assertIn("[ OK ] godot: godot (4.6.stable.official.89cea1439)", out)


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


# ---- #136: RPG Maker MZ setup names the project file it copied -----------------
class RpgMakerSetup(TempRoot):
    def test_setup_names_the_copied_project_file(self):
        src = self.root / "new_mz"                   # a project the editor made, named as MZ names it
        dev = load("rpgmaker-mz")
        for rel in ("Project1.rmmzproject", "js/plugins.js") + dev.CORE_FILES:
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            (src / rel).write_text("")
        dev.ROOT = self.root / "game_proj"
        dev.ROOT.mkdir()
        dev.node_problem = lambda: None
        dev.register_own_plugins = lambda g: "plugins registered"
        dev.deps_stale = lambda: False
        dev.run = lambda *a, **kw: (0, "")
        rc, text = quiet(dev.cmd_setup, argparse.Namespace(source=str(src)))
        self.assertEqual(rc, 0, text)
        self.assertTrue((dev.ROOT / "game" / "Project1.rmmzproject").is_file())
        self.assertIn("open game/Project1.rmmzproject in RPG Maker MZ", text)


# ---- #134, #135: web, web-3d and RPG Maker MZ smoke.mjs ------------------------
# smoke.mjs runs for real under node; vite, Playwright and MZ's serve.mjs are stand-ins that boot at once,
# "screenshot" by writing a small file, and answer any ?drive= with DRIVE_ABORT (as a game without a shell does).
FAKE_PLAYWRIGHT = """import { writeFileSync } from "node:fs";
export const chromium = {
  async launch() {
    return {
      async newPage() {
        const handlers = {};
        return {
          on(ev, fn) { (handlers[ev] ||= []).push(fn); },
          async addInitScript() {},
          async goto(url) {
            const emit = (type, text) => (handlers.console || []).forEach((fn) => fn({ type: () => type, text: () => text, location: () => ({}) }));
            setTimeout(() => {
              emit("log", "BOOT_OK");
              const drive = new URL(url).searchParams.get("drive");
              if (drive && process.env.FAKE_DRIVE_ERROR) emit("error", process.env.FAKE_DRIVE_ERROR);   // #175
              else if (drive) emit("error", `[ERROR][drive] DRIVE_ABORT ${drive}: no scripted runs here`);
            }, 10);
          },
          async screenshot({ path }) { writeFileSync(path, "new"); },
          async evaluate() {
            if (process.env.FAKE_FREEZE) { setInterval(() => {}, 1000); return new Promise(() => {}); }   // #251
            await new Promise((r) => setTimeout(r, 300)); return {};
          },
        };
      },
      async close() {},
    };
  },
};
"""
FAKE_VITE = 'export async function preview() { return { resolvedUrls: { local: ["http://127.0.0.1:9/"] }, async close() {} }; }\n'
FAKE_SERVE = 'export async function serve() { return { url: "http://127.0.0.1:9/", async close() {} }; }\n'
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not on PATH")
class WebSmokeRecord(TempRoot):
    def project(self, engine):
        root = self.root / engine
        (root / "tools").mkdir(parents=True)
        shutil.copy2(KIT / "engines" / engine / "skeleton" / "tools" / "smoke.mjs", root / "tools" / "smoke.mjs")
        for name, text in (("vite", FAKE_VITE), ("playwright", FAKE_PLAYWRIGHT)):
            pkg = root / "node_modules" / name
            pkg.mkdir(parents=True)
            (pkg / "package.json").write_text('{"name": "%s", "type": "module", "main": "index.js"}' % name)
            (pkg / "index.js").write_text(text)
        if engine == "rpgmaker-mz":
            (root / "tools" / "serve.mjs").write_text(FAKE_SERVE)
            (root / "game" / "js").mkdir(parents=True)
            (root / "game" / "index.html").write_text("<html></html>")
            (root / "game" / "js" / "rmmz_core.js").write_text("")
        else:
            (root / "dist").mkdir()
            (root / "dist" / "index.html").write_text("<html></html>")
        return root

    def test_record_keeps_only_this_runs_frames(self):
        for engine in ("web", "web-3d", "rpgmaker-mz"):
            with self.subTest(engine=engine):
                root = self.project(engine)
                frames = root / "build" / "frames"
                frames.mkdir(parents=True)
                for i in range(30):                    # an earlier, longer run
                    (frames / f"f{i:05d}.png").write_text("old")
                (frames / "notes.txt").write_text("mine")
                r = subprocess.run([NODE, str(root / "tools" / "smoke.mjs"), "--record", "build/frames",
                                    "--record-every", "20", "--frames", "1"], cwd=root, capture_output=True,
                                   encoding="utf-8", errors="replace", timeout=60)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                n = int(re.search(r"\[ OK \] (\d+) frame\(s\)", r.stdout).group(1))
                left = sorted(p.name for p in frames.glob("f*.png"))
                self.assertEqual(left, [f"f{i:05d}.png" for i in range(n)], f"{n} frame(s) reported")
                self.assertTrue(all((frames / name).read_text() == "new" for name in left))
                self.assertTrue((frames / "notes.txt").is_file(), "only f<digits>.png is cleared")

    def test_a_refused_drive_is_one_error(self):
        # #135: DRIVE_ABORT fails the run; the data-dir checks of the scenario it never ran add nothing
        for engine in ("web", "web-3d"):
            with self.subTest(engine=engine):
                root = self.project(engine)
                r = subprocess.run([NODE, str(root / "tools" / "smoke.mjs"), "--drive", "menus"], cwd=root,
                                   capture_output=True, encoding="utf-8", errors="replace", timeout=60)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("DRIVE_ABORT menus", r.stdout)
                self.assertNotIn("[drive menus]", r.stdout)


    def test_pseudo_plant_says_it_fails_on_purpose_only_for_the_planted_label(self):
        # #175: the planted label is the proof; any other PSEUDO_FAIL is a real failure
        import os
        planted = '[ERROR][i18n] PSEUDO_FAIL menu: "plant.too_small" clipped (needs 114x22 px, has 41x22): "[x]"'
        other = '[ERROR][i18n] PSEUDO_FAIL menu: "menu.play" clipped (needs 114x22 px, has 41x22): "[x]"'
        for engine in ("web", "web-3d"):
            for line, note in ((planted, True), (other, False)):
                with self.subTest(engine=engine, note=note):
                    root = self.project(engine)
                    r = subprocess.run([NODE, str(root / "tools" / "smoke.mjs"), "--drive", "pseudo-plant"], cwd=root,
                                       capture_output=True, encoding="utf-8", errors="replace", timeout=60,
                                       env=dict(os.environ, FAKE_DRIVE_ERROR=line))
                    self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                    self.assertEqual("fails on purpose" in r.stdout, note, r.stdout)
                    shutil.rmtree(root)


@unittest.skipUnless(NODE, "node is not on PATH")
class WebSmokeReviewFixes(WebSmokeRecord):
    """#251: --data-dir rewrote binary files as UTF-8 text (or deleted them), a project folder could be the data dir,
    and the wait for N frames had no timeout."""

    def test_a_binary_file_in_the_data_dir_is_left_alone(self):
        for engine in ("web", "web-3d"):
            with self.subTest(engine=engine):
                root = self.project(engine)
                data = root / "build" / "sd"
                data.mkdir(parents=True)
                blob = bytes([0xFF, 0xFE, 0x80, 0x00, 0x01, 0xC3, 0x28])
                (data / "save.bin").write_bytes(blob)
                subprocess.run([NODE, str(root / "tools" / "smoke.mjs"), "--data-dir", "build/sd", "--frames", "1"],
                               cwd=root, capture_output=True, encoding="utf-8", errors="replace", timeout=60)
                self.assertTrue((data / "save.bin").is_file(), "the binary file was deleted")
                self.assertEqual((data / "save.bin").read_bytes(), blob)

    def test_a_project_folder_is_refused_as_the_data_dir(self):
        for engine in ("web", "web-3d"):
            with self.subTest(engine=engine):
                root = self.project(engine)
                (root / "src").mkdir()
                (root / "src" / "main.ts").write_text("x")
                r = subprocess.run([NODE, str(root / "tools" / "smoke.mjs"), "--data-dir", "src", "--frames", "1"],
                                   cwd=root, capture_output=True, encoding="utf-8", errors="replace", timeout=60)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual((root / "src" / "main.ts").read_text(), "x")

    def test_the_data_dir_guard_ignores_letter_case_and_hangs_on_nothing(self):
        """#256: --data-dir SRC passed on Windows; a frozen page still hung on the localStorage read-back."""
        import os
        for engine in ("web", "web-3d"):
            with self.subTest(engine=engine):
                root = self.project(engine)
                (root / "src").mkdir()
                (root / "src" / "main.ts").write_text("x")
                if (root / "SRC").exists():               # a case-insensitive file system: SRC is src/
                    r = subprocess.run([NODE, str(root / "tools" / "smoke.mjs"), "--data-dir", "SRC", "--frames", "1"],
                                       cwd=root, capture_output=True, encoding="utf-8", errors="replace", timeout=60)
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    self.assertEqual((root / "src" / "main.ts").read_text(), "x")
                env = dict(os.environ, FAKE_FREEZE="1")
                r = subprocess.run([NODE, str(root / "tools" / "smoke.mjs"), "--frames", "1", "--timeout-ms", "1000",
                                    "--data-dir", "build/sd"], cwd=root, capture_output=True, encoding="utf-8",
                                   errors="replace", timeout=60, env=env)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_a_frozen_page_fails_instead_of_hanging(self):
        import os
        for engine in ("web", "web-3d", "rpgmaker-mz"):
            with self.subTest(engine=engine):
                root = self.project(engine)
                env = dict(os.environ, FAKE_FREEZE="1")
                r = subprocess.run([NODE, str(root / "tools" / "smoke.mjs"), "--frames", "1", "--timeout-ms", "1000"],
                                   cwd=root, capture_output=True, encoding="utf-8", errors="replace", timeout=60,
                                   env=env)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("did not run within", r.stdout + r.stderr)


class CaptureChecks(TempRoot):
    """#251: Bevy and LOVE passed a stale screenshot; Bevy counted old frames, LOVE passed a recording of none."""

    def bevy(self, **opts):
        dev = load("bevy")
        dev.ROOT = self.root
        dev.preflight = lambda: None
        dev.build = lambda args: 0
        dev.run = lambda cmd, **kw: (0, "BOOT_OK x 0.1.0\nSMOKE_DONE frames=5\n")
        args = argparse.Namespace(frames=5, screenshot="", record="", record_every=66, record_from=0, game_args=[],
                                  timeout=60, until="", fail_on="", release=False)
        for k, v in opts.items():
            setattr(args, k, v)
        return quiet(dev.cmd_smoke, args)

    def love(self, **opts):
        dev = load("love2d")
        dev.ROOT = self.root
        dev.compile_check = lambda love, files: ([], True, [])
        dev.run = lambda cmd, **kw: (0, "BOOT_OK\nSMOKE_DONE 120\n")
        args = argparse.Namespace(frames=120, headless=False, screenshot="", record="", record_every=66, drive="",
                                  locale="", data_dir="", debug=False, game_args=[], compare="", tolerance=0)
        for k, v in opts.items():
            setattr(args, k, v)
        return quiet(dev.cmd_smoke, args, "love")

    def test_bevy_stale_captures_fail(self):
        (self.root / "cap").mkdir()
        (self.root / "cap" / "s.png").write_bytes(b"old picture")
        for i in range(30):
            (self.root / "cap" / f"frame_{i:05d}.png").write_bytes(b"old")
        rc, text = self.bevy(screenshot="cap/s.png")
        self.assertEqual(rc, 1, text)
        self.assertIn("no screenshot", text)
        rc, text = self.bevy(record="cap")
        self.assertEqual(rc, 1, text)
        self.assertIn("no frames recorded", text)

    def test_love_stale_screenshot_and_empty_recording_fail(self):
        (self.root / "cap").mkdir()
        (self.root / "cap" / "s.png").write_bytes(b"old picture")
        rc, text = self.love(screenshot="cap/s.png")
        self.assertEqual(rc, 1, text)
        rc, text = self.love(record="rec")
        self.assertEqual(rc, 1, text)
        self.assertIn("no frames recorded", text)

    def test_mz_port_out_of_range_is_a_usage_error(self):
        dev = load("rpgmaker-mz")
        with self.assertRaises(argparse.ArgumentTypeError):
            dev.port_number("70000")
        self.assertEqual(dev.port_number("8080"), 8080)


class WebDriveHelp(unittest.TestCase):
    def test_web_and_web_3d_promise_the_shell_scenarios(self):
        # #135: web-3d had no shell screens and its -h said its --drive aborts; #175: it runs web's shell now, so both
        # name the scenarios and neither promises an abort
        for engine, want, not_want in (("web", "menus, crash", "DRIVE_ABORT"), ("web-3d", "menus, crash", "DRIVE_ABORT")):
            with self.subTest(engine=engine):
                dev_py = KIT / "engines" / engine / "skeleton" / "tools" / "dev.py"
                r = subprocess.run([sys.executable, str(dev_py), "smoke", "-h"], capture_output=True,
                                   encoding="utf-8", errors="replace", timeout=60)
                self.assertEqual(r.returncode, 0, r.stderr)
                text = " ".join(r.stdout.split())
                self.assertIn(want, text)
                self.assertNotIn(not_want, text)


# ---- #36: Windows, a grandchild whose parent already exited ---------------------
# The parent starts a grandchild that inherits stdout (so it holds the pipe), writes its pid, and exits at once.
ORPHAN_PARENT = (
    "import subprocess, sys, time\n"
    "time.sleep(0.3)\n"                      # join the job first (dev.py assigns it right after starting us)
    "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "open(sys.argv[1], 'w').write(str(g.pid))\n"
)
STILL_ACTIVE = 259


def win_alive(pid):
    """True while a Windows process runs (os.kill(pid, 0) would terminate it there)."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = wintypes.DWORD()
    ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return bool(ok) and code.value == STILL_ACTIVE


@unittest.skipUnless(sys.platform == "win32", "Windows job objects")
class WindowsOrphanOnTimeout(TempRoot):
    def grandchild(self, pidfile):
        """The orphan's pid, read once its parent wrote it; registered for cleanup in any case."""
        for _ in range(100):
            if pidfile.is_file() and pidfile.read_text().strip():
                pid = int(pidfile.read_text())
                self.addCleanup(lambda: subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True))
                return pid
            time.sleep(0.05)
        self.fail("the parent never wrote the grandchild's pid")

    def test_run_timeout_ends_the_orphan(self):
        for engine in [e for e in ENGINES if e != "unity"]:   # Unity's run_unity starts the editor itself
            with self.subTest(engine=engine):
                dev = load(engine)
                dev.ROOT = self.root
                dev.KILL_TIMEOUT_S = 2
                pidfile = self.root / f"{engine}.pid"
                started = time.monotonic()
                (rc, _), _ = quiet(dev.run, [sys.executable, "-c", ORPHAN_PARENT, str(pidfile)], capture=True,
                                   timeout=2)
                self.assertEqual(rc, 124)
                self.assertLess(time.monotonic() - started, 3.5, f"{engine}: waited on the orphan's pipe")
                pid = self.grandchild(pidfile)
                time.sleep(0.2)
                self.assertFalse(win_alive(pid), f"{engine}: the grandchild outlived the timeout")

    def test_winjob_in_every_module(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                dev = load(engine)
                pidfile = self.root / f"job-{engine}.pid"
                proc = subprocess.Popen([sys.executable, "-c", ORPHAN_PARENT, str(pidfile)])
                job = dev.WinJob(proc, 30)
                self.assertTrue(job.handle, f"{engine}: no job object")
                proc.wait(10)
                pid = self.grandchild(pidfile)
                self.assertTrue(win_alive(pid))
                job.kill()
                time.sleep(0.2)
                self.assertFalse(win_alive(pid), f"{engine}: WinJob.kill left the grandchild running")
                self.assertIsNone(job.handle)

    def test_untimed_and_normal_exit_leave_processes_alone(self):
        dev = load("web")
        self.assertIsNone(dev.WinJob(subprocess.Popen([sys.executable, "-c", "pass"]), None).handle)
        pidfile = self.root / "normal.pid"
        proc = subprocess.Popen([sys.executable, "-c", ORPHAN_PARENT, str(pidfile)])
        job = dev.WinJob(proc, 30)
        proc.wait(10)
        job.close()                              # what run() does after a normal exit
        pid = self.grandchild(pidfile)
        time.sleep(0.2)
        self.assertTrue(win_alive(pid), "closing the job must not end what the command left running")


# ---- #37: Linux / macOS, killing an untimed command ------------------------------
class FakeProc:
    def __init__(self, pid):
        self.pid, self.killed = pid, False

    def kill(self):
        self.killed = True


class PosixKillTree(unittest.TestCase):
    """kill_tree with the process-group calls faked, as on Linux: dev.py is pid 50 and leads group 50."""
    # 100 is the command; 101 and 104 its children, 102 a grandchild under 101; 103 belongs to someone else
    PS = [(50, 1), (100, 50), (101, 100), (102, 101), (103, 1), (104, 100)]

    def kill(self, engine, group_of_100):
        dev = load(engine)
        calls = []

        def kill(pid, sig):
            calls.append(("kill", pid))
            if pid == 104:
                raise ProcessLookupError(pid)   # ended between ps and the kill: the rest must still go
        dev.os = argparse.Namespace(getpgid=lambda pid: {100: group_of_100}[pid],
                                    killpg=lambda pg, sig: calls.append(("killpg", pg)), kill=kill)
        dev.sys = argparse.Namespace(platform="linux")
        dev.signal = argparse.Namespace(SIGKILL=9)
        dev.ps_pairs = lambda: list(self.PS)
        proc = FakeProc(100)
        dev.kill_tree(proc)
        return calls, proc.killed

    def test_untimed_command_loses_its_descendants(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                calls, killed = self.kill(engine, group_of_100=50)   # shares dev.py's group (no new session)
                self.assertEqual(sorted(calls), [("kill", 101), ("kill", 102), ("kill", 104)])
                self.assertTrue(killed)

    def test_timed_command_is_killed_as_a_group(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                calls, killed = self.kill(engine, group_of_100=100)  # start_new_session: it leads its group
                self.assertEqual(calls, [("killpg", 100)])
                self.assertTrue(killed)

    def test_ps_output_parsing(self):
        dev = load("web")
        out = "    1     0\n  100    50\nnot a row\n  101   100\n"
        dev.subprocess = argparse.Namespace(run=lambda *a, **k: argparse.Namespace(stdout=out), DEVNULL=-3,
                                            SubprocessError=subprocess.SubprocessError)
        self.assertEqual(dev.ps_pairs(), [(1, 0), (100, 50), (101, 100)])

        def no_ps(*a, **k):
            raise FileNotFoundError("ps")
        dev.subprocess.run = no_ps
        self.assertEqual(dev.ps_pairs(), [])
        dev.ps_pairs = lambda: [(7, 3), (8, 7), (9, 8), (3, 9)]          # a cycle (pid reuse) must not loop
        self.assertEqual(dev.descendants(3), [7, 8, 9])


# ---- #249: RPG Maker MZ shader recipes ---------------------------------------------
class MzShaders(TempRoot):
    """check compiles the KitShaders.js filters, smoke --shaders renders and compares them, even before
    `setup --from` (the render needs no MZ project)."""

    def dev(self, results):
        dev = load("rpgmaker-mz")
        dev.ROOT = self.root
        plugin = self.root / "game" / "js" / "plugins" / "KitShaders.js"
        plugin.parent.mkdir(parents=True, exist_ok=True)
        plugin.write_text("// generated\n", encoding="utf-8")
        dev.node_problem = lambda: None
        dev.deps_stale = lambda: False
        dev.check_plugins = lambda g, problems: 1
        self.calls = []

        def fake_run(cmd, **kwargs):
            line = " ".join(str(c) for c in cmd)
            self.calls.append(line)
            for key, result in results.items():
                if key in line:
                    return result
            return 0, ""
        dev.run = fake_run
        return dev

    def smoke(self, dev, **opts):
        args = argparse.Namespace(frames=1, query="", until="", fail_on="", timeout=1, screenshot="", record="",
                                  record_every=66, headed=False, shaders=True)
        for k, v in opts.items():
            setattr(args, k, v)
        return quiet(dev.cmd_smoke, args)

    def test_smoke_shaders_runs_without_a_project(self):
        dev = self.dev({"shader_ref.py": (0, "[ OK ] all 11 effect(s) match the reference")})
        rc, text = self.smoke(dev)
        self.assertEqual(rc, 0, text)
        self.assertTrue(any("shader_render.mjs" in c for c in self.calls), self.calls)
        self.assertTrue(any("shader_ref.py compare" in c for c in self.calls), self.calls)
        self.assertIn("only the shaders were checked", text)

    def test_a_differing_recipe_fails_smoke(self):
        dev = self.dev({"shader_ref.py": (1, "[FAIL] flash: 9 pixel(s) past 2")})
        rc, text = self.smoke(dev)
        self.assertEqual(rc, 1, text)
        self.assertIn("differs from its golden image", text)

    def test_a_render_without_playwright_is_an_environment_problem(self):
        dev = self.dev({"shader_render.mjs": (2, "[error] playwright is not installed")})
        self.assertEqual(self.smoke(dev)[0], 2)
        self.assertFalse(any("shader_ref.py" in c for c in self.calls))

    def check(self, dev, **opts):
        args = argparse.Namespace(no_shaders=False)
        for k, v in opts.items():
            setattr(args, k, v)
        return quiet(dev.cmd_check, args)

    def test_check_compiles_the_plugin_it_checks(self):
        dev = self.dev({"shader_compile.mjs": (0, "[ OK ] 11 shader recipe(s) compile")})
        rc, text = self.check(dev)
        self.assertEqual(rc, 0, text)
        plugins = str(self.root / "game" / "js" / "plugins")
        gen = next(c for c in self.calls if "shader_gen.py" in c)
        self.assertIn("--check", gen)
        self.assertIn(f"--out {plugins}", gen)
        self.assertIn(f"--file {plugins}", next(c for c in self.calls if "shader_compile.mjs" in c))

    def test_a_filter_that_does_not_compile_fails_check(self):
        dev = self.dev({"shader_compile.mjs": (1, "[FAIL] shader flash:\n  ERROR: 0:12: syntax error")})
        rc, text = self.check(dev)
        self.assertEqual(rc, 1, text)
        self.assertIn("shader flash", text)
        self.assertEqual(self.check(self.dev({"shader_gen.py": (1, "[FAIL] stale")}))[0], 1)

    def test_no_shaders_skips_the_compile(self):
        dev = self.dev({"shader_compile.mjs": (1, "[FAIL] shader flash")})
        self.assertEqual(self.check(dev, no_shaders=True)[0], 0)
        self.assertFalse(any("shader" in c for c in self.calls), self.calls)

    def test_unreadable_recipes_are_an_environment_problem(self):
        self.assertEqual(self.check(self.dev({"shader_gen.py": (2, "[error] recipes.json is malformed")}))[0], 2)


# ---- #249: LÖVE shader recipes -----------------------------------------------------
class LoveShaders(TempRoot):
    """check compiles shaders/kit through tools/shadercheck; smoke --shaders writes its SHADER_PNG pictures to
    build/shader_check/ and compares them; --headless cannot draw shaders."""
    PNG = base64.b64encode(b"\x89PNG fake").decode("ascii")

    def dev(self, results):
        dev = load("love2d")
        dev.ROOT = self.root
        (self.root / "shaders" / "kit").mkdir(parents=True, exist_ok=True)
        dev.compile_check = lambda love, files: ([], True, 0)
        dev.lua_files = lambda paths=None: [self.root / "main.lua"]
        self.calls = []

        def fake_run(cmd, **kwargs):
            line = " ".join(str(c) for c in cmd)
            self.calls.append(line)
            for key, result in results.items():
                if key in line:
                    return result
            return 0, "BOOT_OK\nSMOKE_DONE 120\n"
        dev.run = fake_run
        return dev

    def check(self, dev, **opts):
        args = argparse.Namespace(files=[], no_shaders=False)
        for k, v in opts.items():
            setattr(args, k, v)
        return quiet(dev.cmd_check, args, "love")

    def smoke(self, dev, **opts):
        args = argparse.Namespace(frames=120, headless=False, screenshot="", record="", record_every=66, drive="",
                                  locale="", data_dir="", debug=False, game_args=[], compare="", tolerance=0,
                                  shaders=True)
        for k, v in opts.items():
            setattr(args, k, v)
        return quiet(dev.cmd_smoke, args, "love")

    def test_check_compiles_the_shaders(self):
        dev = self.dev({"shadercheck": (0, "SHADER_OK flash\nSHADER_CHECK_DONE 1 0\n")})
        rc, text = self.check(dev)
        self.assertEqual(rc, 0, text)
        self.assertIn("1 shader recipe(s) compile", text)
        line = next(c for c in self.calls if "shadercheck" in c)
        self.assertNotIn("--render", line)

    def test_a_shader_that_does_not_compile_fails_check(self):
        dev = self.dev({"shadercheck": (1, "SHADER_FAIL flash Line 10: syntax error\nSHADER_CHECK_DONE 1 1\n")})
        rc, text = self.check(dev)
        self.assertEqual(rc, 1, text)
        self.assertIn("shader flash Line 10", text)
        self.assertEqual(self.check(self.dev({"shader_gen.py": (1, "[FAIL] stale")}))[0], 1)

    def test_no_shaders_and_named_files_skip_the_shaders(self):
        for opts in ({"no_shaders": True}, {"files": ["main.lua"]}):
            with self.subTest(**opts):
                dev = self.dev({"shadercheck": (1, "SHADER_CHECK_DONE 1 1\n")})
                self.assertEqual(self.check(dev, **opts)[0], 0)
                self.assertFalse(any("shader" in c for c in self.calls), self.calls)

    def test_smoke_shaders_writes_and_compares_the_pictures(self):
        dev = self.dev({"shadercheck": (0, f"SHADER_OK flash\nSHADER_PNG flash {self.PNG}\nSHADER_CHECK_DONE 1 0\n"),
                        "shader_ref.py": (0, "[ OK ] all 1 effect(s) match the reference")})
        rc, text = self.smoke(dev)
        self.assertEqual(rc, 0, text)
        self.assertEqual((self.root / "build" / "shader_check" / "flash.png").read_bytes(), b"\x89PNG fake")
        self.assertIn("--render", next(c for c in self.calls if "shadercheck" in c))
        self.assertTrue(any("shader_ref.py compare" in c for c in self.calls), self.calls)

    def test_a_differing_picture_fails_smoke(self):
        dev = self.dev({"shadercheck": (0, f"SHADER_PNG flash {self.PNG}\nSHADER_CHECK_DONE 1 0\n"),
                        "shader_ref.py": (1, "[FAIL] flash: 9 pixel(s) past 2")})
        rc, text = self.smoke(dev)
        self.assertEqual(rc, 1, text)
        self.assertIn("differs from its golden image", text)

    def test_headless_cannot_draw_shaders(self):
        rc, text = self.smoke(self.dev({}), headless=True)
        self.assertEqual(rc, 2, text)
        self.assertFalse(self.calls)

    def test_unreadable_recipes_are_an_environment_problem(self):
        self.assertEqual(self.check(self.dev({"shader_gen.py": (2, "[error] recipes.json is malformed")}))[0], 2)


# ---- #249: Bevy shader recipes ------------------------------------------------------
class BevyShaders(TempRoot):
    """smoke --shaders builds and runs examples/shader_check.rs and compares its pictures; a logged pipeline error
    fails it although the example exits 0 (Bevy logs a broken shader and draws nothing); check checks the
    generated files."""
    SMOKE = "BOOT_OK x 0.1.0\nSMOKE_DONE frames=5\n"
    ALL_OK = "SHADER_OK flash\nSHADER_CHECK_DONE 1 0\n"

    def dev(self, results):
        dev = load("bevy")
        dev.ROOT = self.root
        (self.root / "src").mkdir(exist_ok=True)
        (self.root / "src" / "kit_shaders.rs").write_text("// generated\n", encoding="utf-8")
        dev.preflight = lambda: None
        dev.cargo = lambda: "cargo"
        self.calls, self.builds = [], []
        dev.build = lambda args, extra=(): self.builds.append(list(extra)) or 0

        def fake_run(cmd, **kwargs):
            line = " ".join(str(c) for c in cmd)
            self.calls.append(line)
            for key, result in results.items():
                if key in line:
                    return result
            return 0, self.SMOKE
        dev.run = fake_run
        return dev

    def smoke(self, dev, **opts):
        args = argparse.Namespace(frames=5, screenshot="", record="", record_every=4, record_from=1, game_args=[],
                                  timeout=60, until="", fail_on="", release=False, shaders=True)
        for k, v in opts.items():
            setattr(args, k, v)
        return quiet(dev.cmd_smoke, args)

    def test_smoke_shaders_runs_the_example_and_compares(self):
        dev = self.dev({"--example": (0, self.ALL_OK), "shader_ref.py": (0, "[ OK ] all 1 effect(s) match")})
        rc, text = self.smoke(dev)
        self.assertEqual(rc, 0, text)
        self.assertIn(["--example", "shader_check"], self.builds)
        self.assertTrue(any("shader_ref.py compare" in c for c in self.calls), self.calls)

    def test_a_logged_shader_error_fails_although_the_example_exits_0(self):
        broken = "2026-11-06T06:41:35Z ERROR bevy_render::render_resource::pipeline_cache: failed to process shader\n"
        dev = self.dev({"--example": (0, broken + self.ALL_OK)})
        rc, text = self.smoke(dev)
        self.assertEqual(rc, 1, text)
        self.assertIn("failed to process shader", text)
        self.assertFalse(any("shader_ref.py" in c for c in self.calls))

    def test_a_differing_picture_fails(self):
        dev = self.dev({"--example": (0, self.ALL_OK), "shader_ref.py": (1, "[FAIL] flash: 9 pixel(s) past 2")})
        self.assertEqual(self.smoke(dev)[0], 1)

    def test_check_checks_the_generated_files(self):
        dev = self.dev({"shader_gen.py": (1, "[FAIL] stale: src/kit_shaders.rs")})
        rc, text = quiet(dev.cmd_check, argparse.Namespace(release=False, no_shaders=False))
        self.assertEqual(rc, 1, text)
        self.assertIn("do not match their recipes", text)
        dev = self.dev({"shader_gen.py": (1, "[FAIL] stale")})
        self.assertEqual(quiet(dev.cmd_check, argparse.Namespace(release=False, no_shaders=True))[0], 0)

    def test_unreadable_recipes_are_an_environment_problem(self):
        dev = self.dev({"shader_gen.py": (2, "[error] recipes.json is malformed")})
        self.assertEqual(quiet(dev.cmd_check, argparse.Namespace(release=False, no_shaders=False))[0], 2)

    # ---- #168: the shell's scripted runs ----------------------------------------------
    def test_smoke_drive_goes_to_the_game_after_the_separator_with_its_own_data_folder(self):
        drive_out = "BOOT_OK x 0.1.0\nSETTINGS_WRITTEN build/smoke-data/settings.json\nDRIVE_DONE menus\nSMOKE_DONE frames=9\n"
        dev = self.dev({"--drive menus": (0, drive_out)})
        rc, text = self.smoke(dev, shaders=False, drive="menus", locale="pseudo", game_args=["--autoplay", "right"])
        self.assertEqual(rc, 0, text)
        run = next(c for c in self.calls if "--smoke" in c)
        tail = run.split(" -- ", 2)[2]           # cargo run ... -- --smoke 5 -- <game options>
        self.assertTrue(tail.startswith("--drive menus --data-dir "), tail)
        self.assertIn("smoke-data --locale pseudo --autoplay right", tail)
        self.assertIn("SETTINGS_WRITTEN", text, "the proof lines are echoed")
        self.assertTrue((self.root / "build" / "smoke-data").is_dir(), "a fresh data folder of the run's own")

    def test_a_drive_without_drive_done_fails_although_the_frames_ran(self):
        dev = self.dev({"--drive menus": (0, "BOOT_OK x 0.1.0\nSMOKE_DONE frames=5\n")})
        rc, text = self.smoke(dev, shaders=False, drive="menus")
        self.assertEqual(rc, 1, text)
        self.assertIn("did not finish", text)
        # a plain run (no drive) still needs only BOOT_OK and SMOKE_DONE
        self.assertEqual(self.smoke(self.dev({}), shaders=False)[0], 0)

    def test_a_given_data_dir_is_kept_between_runs(self):
        dev = self.dev({})
        keep = self.root / "keep"
        keep.mkdir()
        (keep / "settings.json").write_text("{}", encoding="utf-8")
        rc, text = self.smoke(dev, shaders=False, data_dir="keep")
        self.assertEqual(rc, 0, text)
        self.assertTrue((keep / "settings.json").is_file(), "--data-dir is never wiped")


# ---- #275: Bevy crash files and the pseudo-locale drives --------------------------------
class BevyShellDrives(TempRoot):
    """The crash drive fails on purpose and names its crash file, pseudo-plant fails naming the planted label, the
    pseudo drive's PSEUDO_ lines are echoed, and a panic in any run points at its crash file."""
    SMOKE = BevyShaders.SMOKE
    dev = BevyShaders.dev                   # the same faked cargo, without running the shader cases again
    smoke = BevyShaders.smoke
    CRASH = ("BOOT_OK x 0.1.0\nCRASH_WRITTEN build/smoke-data/crashes/crash_20261110_120000.txt\n"
             "thread 'main' panicked at src/shell/drive.rs:9:9:\ndrive crash: a planted panic\n")

    def drive(self, name, out, rc=0, **opts):
        dev = self.dev({"--drive " + name: (rc, out)})
        return self.smoke(dev, shaders=False, drive=name, **opts)

    def test_the_crash_drive_fails_and_names_the_crash_file(self):
        rc, text = self.drive("crash", self.CRASH, rc=101)
        self.assertEqual(rc, 1, text)
        self.assertIn("CRASH_WRITTEN build/smoke-data/crashes/crash_20261110_120000.txt", text, "echoed")
        self.assertIn("crash report: build/smoke-data/crashes/crash_20261110_120000.txt", text)
        self.assertIn("fails on purpose", text)

    def test_a_panic_in_a_plain_run_points_at_its_crash_file(self):
        dev = self.dev({"--smoke": (101, self.CRASH)})
        rc, text = self.smoke(dev, shaders=False)
        self.assertEqual(rc, 1, text)
        self.assertIn("crash report:", text)
        self.assertNotIn("fails on purpose", text)

    def test_pseudo_lines_are_echoed_and_the_plant_fails_on_purpose(self):
        ok = "BOOT_OK x\nPSEUDO_SCREEN title labels 3 problems 0\nPSEUDO_PASS 1 screens, 3 labels\nDRIVE_DONE pseudo\nSMOKE_DONE frames=9\n"
        rc, text = self.drive("pseudo", ok, locale="pseudo")
        self.assertEqual(rc, 0, text)
        self.assertIn("PSEUDO_PASS", text)
        plant = ("BOOT_OK x\nPSEUDO_FAIL main_menu label plant.too_small: text 145 px is wider than its box 30 px\n"
                 "PSEUDO_FAILED 1 problem(s) on 1 screens\n2026-11-10T00:00:00Z ERROR x: pseudo: 1 label problem(s)\n"
                 "DRIVE_DONE pseudo-plant\n")
        rc, text = self.drive("pseudo-plant", plant, rc=1, locale="pseudo")
        self.assertEqual(rc, 1, text)
        self.assertIn("plant.too_small", text)
        self.assertIn("fails on purpose", text)

    def test_the_help_names_the_new_drives(self):
        dev = load("bevy")
        p = dev.build_parser()
        sub = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction)).choices["smoke"]
        help_text = sub.format_help()
        for name in ("crash", "pseudo", "pseudo-plant", "bug", "juice"):
            self.assertIn(name, help_text)


# ---- #249: Unity shader recipes -----------------------------------------------------
class UnityShaders(TempRoot):
    """check runs GameKitShaders.Check in its editor run and fails on a SHADER_FAIL line; smoke --shaders runs
    GameKitShaders.Render with a graphics device after the Smoke tests, then the compare."""
    OK_LOG = "SHADER_OK flash\nUnityEngine.Debug:Log (object)\nSHADER_CHECK_DONE 1 0\n"

    def dev(self, log, tool=None):
        dev = load("unity")
        dev.ROOT = self.root
        (self.root / "Assets" / "Shaders" / "Kit").mkdir(parents=True, exist_ok=True)
        dev.preflight = lambda: None
        self.unity, self.tools = [], []

        def fake_unity(extra, label, graphics=False, env=None):
            self.unity.append((list(extra), graphics))
            return 0, log
        dev.run_unity = fake_unity

        def fake_tool(cmd):
            line = " ".join(str(c) for c in cmd)
            self.tools.append(line)
            for key, result in (tool or {}).items():
                if key in line:
                    return result
            return 0, ""
        dev.run_tool = fake_tool
        dev.run_tests = lambda *a, **kw: 0
        return dev

    def check(self, dev, **opts):
        args = argparse.Namespace(no_shaders=False)
        for k, v in opts.items():
            setattr(args, k, v)
        return quiet(dev.cmd_check, args)

    def smoke(self, dev):
        args = argparse.Namespace(screenshot=None, record=None, record_every=6, graphics=False, fail_on=None,
                                  until=None, filter="Smoke", shaders=True)
        return quiet(dev.cmd_smoke, args)

    def test_check_runs_the_shader_check_in_the_same_editor_run(self):
        dev = self.dev(self.OK_LOG)
        rc, text = self.check(dev)
        self.assertEqual(rc, 0, text)
        self.assertEqual(self.unity, [(["-quit", "-executeMethod", "GameKitShaders.Check"], False)])
        self.assertTrue(any("shader_gen.py --check" in c for c in self.tools), self.tools)

    def test_a_shader_error_fails_check(self):
        dev = self.dev("SHADER_FAIL flash line 12: syntax error\nSHADER_CHECK_DONE 1 1\n")
        rc, text = self.check(dev)
        self.assertEqual(rc, 1, text)
        self.assertIn("shader flash line 12", text)
        self.assertEqual(self.check(self.dev("no report at all\n"))[0], 1)
        self.assertEqual(self.check(self.dev(self.OK_LOG, {"shader_gen.py": (1, "[FAIL] stale")}))[0], 1)

    def test_no_shaders_is_a_plain_compile(self):
        dev = self.dev("")
        self.assertEqual(self.check(dev, no_shaders=True)[0], 0)
        self.assertEqual(self.unity, [(["-quit"], False)])

    def test_smoke_shaders_draws_with_graphics_and_compares(self):
        dev = self.dev(self.OK_LOG, {"shader_ref.py": (0, "[ OK ] all 1 effect(s) match")})
        rc, text = self.smoke(dev)
        self.assertEqual(rc, 0, text)
        extra, graphics = self.unity[-1]
        self.assertTrue(graphics)
        self.assertIn("GameKitShaders.Render", extra)
        self.assertEqual(extra[extra.index("-shaderOut") + 1], str(self.root / "Logs" / "shader_check"))
        self.assertTrue(any("shader_ref.py compare" in c for c in self.tools), self.tools)

    def test_a_differing_picture_fails_smoke(self):
        dev = self.dev(self.OK_LOG, {"shader_ref.py": (1, "[FAIL] flash: 9 pixel(s) past 2")})
        rc, text = self.smoke(dev)
        self.assertEqual(rc, 1, text)
        self.assertIn("differs from its golden image", text)

    def test_unreadable_recipes_are_an_environment_problem(self):
        self.assertEqual(self.check(self.dev(self.OK_LOG, {"shader_gen.py": (2, "[error] recipes.json is malformed")}))[0], 2)


# ---- #249: Unreal shader recipes ----------------------------------------------------
class UnrealShaders(TempRoot):
    """The shader check runs in the full editor through -ExecCmds=py (the pythonscript commandlet has the Null RHI,
    and -ExecutePythonScript quits before the materials compile); the log's SHADER_ lines decide."""
    OK = "[2026.11.06][  2]LogPython: SHADER_OK flash\n[2026.11.06][  2]LogPython: SHADER_CHECK_DONE 1 0\n"
    BROKEN = ("[2026.11.06][  2]LogShaderCompilers: Warning: Failed to compile Material /Game/KitShaders/Check/M\n"
              "\t/Engine/Generated/Material.ush:3749:59: error: expected expression\n"
              "[2026.11.06][502]LogPython: SHADER_FAIL flash the material did not compile\n"
              "[2026.11.06][502]LogPython: SHADER_CHECK_DONE 1 1\n")

    def dev(self, log, tool=None, automation=0):
        dev = load("unreal")
        dev.ROOT = self.root
        dev.SHADER_LOG = self.root / "Saved" / "Logs" / "dev_shaders.log"
        script = self.root / "Content" / "Python" / "kit_shaders" / "shader_check.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("# check\n", encoding="utf-8")
        exe = self.root / "UnrealEditor-Cmd.exe"
        exe.write_bytes(b"")
        dev.preflight = lambda *a, **kw: None
        dev.editor_cmd = lambda plat: exe
        dev.find_uproject = lambda: self.root / "Test.uproject"
        dev.kit_plugin_state = lambda: "absent"
        self.editor, self.tools = [], []

        def fake_run(cmd, capture=False, timeout=None, env=None):
            self.editor.append(([str(c) for c in cmd], env))
            dev.SHADER_LOG.parent.mkdir(parents=True, exist_ok=True)
            dev.SHADER_LOG.write_text(log, encoding="utf-8")
            return 0, ""
        dev.run = fake_run

        def fake_tool(cmd):
            line = " ".join(str(c) for c in cmd)
            self.tools.append(line)
            for key, result in (tool or {}).items():
                if key in line:
                    return result
            return 0, ""
        dev.run_tool = fake_tool
        dev.run_automation = lambda *a, **kw: automation
        return dev

    def check(self, dev, **opts):
        args = argparse.Namespace(config="Development", platform=None, no_shaders=False)
        for k, v in opts.items():
            setattr(args, k, v)
        return quiet(dev.cmd_check, args)

    def test_a_blueprint_project_still_checks_its_shaders(self):
        dev = self.dev(self.OK)
        rc, text = self.check(dev)
        self.assertEqual(rc, 0, text)
        self.assertIn("1 shader recipe(s) compile as materials", text)
        cmd, env = self.editor[0]
        self.assertIn("-ExecCmds=py kit_shaders/shader_check.py", cmd)   # by its name on sys.path (#273)
        self.assertIn("-RenderOffScreen", cmd)
        self.assertNotIn("-run=pythonscript", cmd)
        self.assertNotIn("-NullRHI", cmd)
        self.assertEqual(env["GAMEKIT_SHADER_MODE"], "compile")

    def test_a_material_that_does_not_compile_fails_check(self):
        rc, text = self.check(self.dev(self.BROKEN))
        self.assertEqual(rc, 1, text)
        self.assertIn("shader flash the material did not compile", text)
        self.assertIn("Material.ush:3749:59: error: expected expression", text)
        self.assertEqual(self.check(self.dev("no shader lines\n"))[0], 1)
        self.assertEqual(self.check(self.dev(self.OK, {"shader_gen.py": (1, "[FAIL] stale")}))[0], 1)

    def test_no_shaders_skips_the_editor(self):
        dev = self.dev(self.BROKEN)
        self.assertEqual(self.check(dev, no_shaders=True)[0], 0)
        self.assertEqual(self.editor, [])

    def smoke(self, dev):
        args = argparse.Namespace(config="Development", platform=None, filter=None, until=None, fail_on=None,
                                  shaders=True)
        return quiet(dev.cmd_smoke, args)

    def test_smoke_shaders_renders_then_runs_the_smoke_tests(self):
        dev = self.dev(self.OK, {"shader_ref.py": (0, "[ OK ] all 1 effect(s) match")})
        rc, text = self.smoke(dev)
        self.assertEqual(rc, 0, text)
        cmd, env = self.editor[0]
        self.assertEqual(env["GAMEKIT_SHADER_MODE"], "render")
        self.assertEqual(env["GAMEKIT_SHADER_OUT"], str(self.root / "Saved" / "ShaderCheck"))
        self.assertTrue(any("shader_ref.py compare" in c for c in self.tools), self.tools)

    def test_a_differing_picture_fails_before_the_smoke_tests(self):
        dev = self.dev(self.OK, {"shader_ref.py": (1, "[FAIL] flash: 9 pixel(s) past 2")}, automation=0)
        rc, text = self.smoke(dev)
        self.assertEqual(rc, 1, text)
        self.assertIn("differs from its golden image", text)

    def test_unreadable_recipes_are_an_environment_problem(self):
        self.assertEqual(self.check(self.dev(self.OK, {"shader_gen.py": (2, "[error] recipes.json is malformed")}))[0], 2)


# ---- #249: C++ / SDL3 shader recipes --------------------------------------------------
class CppShaders(TempRoot):
    """check fails on stale shader files before building; smoke --shaders runs kit_shader_check after the smoke and
    compares; a machine without a GPU renderer is an environment problem (exit 2), not a failed recipe."""
    SMOKE = "[INFO][core] BOOT_OK Test v0.1.0\n[INFO][core] smoke complete after 120 frames\n"
    CHECK = "[info] GPU driver: vulkan\nSHADER_OK flash\nSHADER_CHECK_DONE 1 0\n"

    def dev(self, results):
        dev = load("cpp-sdl2")
        dev.ROOT = self.root
        (self.root / "shaders" / "kit").mkdir(parents=True, exist_ok=True)
        dev.preflight = lambda: None
        dev.configure_and_build = lambda preset: 0
        dev.find_exe = lambda preset, name=None: (name or "game") + ".exe"
        self.calls = []

        def fake_run(cmd, env=None, capture=False, timeout=None):
            line = " ".join(str(c) for c in cmd)
            self.calls.append(line)
            for key, result in results.items():
                if key in line:
                    return result
            return 0, self.SMOKE
        dev.run = fake_run
        return dev

    def smoke(self, dev, **opts):
        args = argparse.Namespace(preset="debug", frames=120, screenshot=None, record=None, record_every=4,
                                  game_args=[], timeout=60, until=None, fail_on=None, shaders=True)
        for k, v in opts.items():
            setattr(args, k, v)
        return quiet(dev.cmd_smoke, args)

    def test_smoke_shaders_runs_the_check_tool_and_compares(self):
        dev = self.dev({"kit_shader_check": (0, self.CHECK), "shader_ref.py": (0, "[ OK ] all 1 effect(s) match")})
        rc, text = self.smoke(dev)
        self.assertEqual(rc, 0, text)
        self.assertIn("GPU driver: vulkan", text)
        tool = next(c for c in self.calls if "kit_shader_check" in c)
        self.assertIn(str(self.root / "build" / "debug" / "shader_check"), tool)
        self.assertTrue(any("shader_ref.py compare" in c for c in self.calls), self.calls)

    def test_no_gpu_renderer_is_an_environment_problem(self):
        dev = self.dev({"kit_shader_check": (2, "[error] no GPU renderer on this machine\n")})
        rc, text = self.smoke(dev)
        self.assertEqual(rc, 2, text)
        self.assertIn("no GPU renderer", text)

    def test_a_failed_recipe_or_picture_fails_smoke(self):
        dev = self.dev({"kit_shader_check": (1, "SHADER_FAIL flash the shader did not load\nSHADER_CHECK_DONE 1 1\n")})
        rc, text = self.smoke(dev)
        self.assertEqual(rc, 1, text)
        self.assertIn("shader flash the shader did not load", text)
        dev = self.dev({"kit_shader_check": (0, self.CHECK), "shader_ref.py": (1, "[FAIL] flash: 9 pixel(s) past 2")})
        self.assertEqual(self.smoke(dev)[0], 1)

    def test_check_refuses_stale_shader_files_before_building(self):
        dev = self.dev({"shader_gen.py": (1, "[FAIL] stale: shaders/kit/flash.frag.hlsl")})
        built = []
        dev.configure_and_build = lambda preset: built.append(preset) or 0
        rc, text = quiet(dev.cmd_check, argparse.Namespace(preset="debug"))
        self.assertEqual(rc, 1, text)
        self.assertIn("do not match their recipes", text)
        self.assertEqual(built, [])

    def test_unreadable_recipes_are_an_environment_problem(self):
        dev = self.dev({"shader_gen.py": (2, "[error] recipes.json is malformed")})
        self.assertEqual(quiet(dev.cmd_check, argparse.Namespace(preset="debug"))[0], 2)


# ---- #249 review: Godot's shader check without a window -----------------------------
class GodotShaderWindow(TempRoot):
    """A shader check that drew nothing at all (no window, no desktop session) is an environment problem (exit 2);
    one that drew some recipes and then failed is a task failure (exit 1)."""

    def shader_pass(self, check_out, gen=(0, "")):
        dev = load("godot")
        dev.ROOT = self.root
        (self.root / "shaders" / "kit").mkdir(parents=True)

        def fake_run(cmd, **kwargs):
            line = " ".join(str(c) for c in cmd)
            return gen if "shader_gen.py" in line else (1, check_out)
        dev.run = fake_run
        return quiet(dev.shader_pass, "godot", False)

    def test_nothing_drawn_is_exit_2(self):
        self.assertEqual(self.shader_pass("")[0], 2)

    def test_a_partial_run_is_exit_1(self):
        self.assertEqual(self.shader_pass("SHADER_OK flash\n")[0], 1)

    def test_unreadable_recipes_are_exit_2(self):
        self.assertEqual(self.shader_pass("", gen=(2, "[error] malformed"))[0], 2)


# ---- #264: a Godot crash during the windowed shader check is not "it needs a window" -------
class GodotShaderCrash(TempRoot):
    """Godot 4.7.2 died with heap corruption (exit 3221226356) after some SHADER_OK lines while other engines used
    the GPU; dev.py blamed a missing window and exited 2."""

    def shader_pass(self, rc, check_out):
        dev = load("godot")
        dev.ROOT = self.root
        (self.root / "shaders" / "kit").mkdir(parents=True, exist_ok=True)
        dev.run = lambda cmd, **kw: (0, "") if "shader_gen.py" in " ".join(map(str, cmd)) else (rc, check_out)
        return quiet(dev.shader_pass, "godot", False)

    def test_a_crash_after_some_recipes_names_the_crash(self):
        out = "Godot Engine v4.7.2.stable\nSHADER_OK flash\nSHADER_OK dissolve\nSHADER_OK palette_swap\n"
        rc, text = self.shader_pass(3221226356, out)
        self.assertEqual(rc, 1, text)
        self.assertIn("Godot crashed after 3 recipe(s) (exit 3221226356 = 0xC0000374)", text)
        self.assertIn("check --no-shaders", text)
        self.assertNotIn("needs a window", text)

    def test_a_crash_before_the_first_recipe_names_the_crash(self):
        # 2026-11-11: two runs in a row died with 0xC0000374 and 0xC0000005 before any SHADER_OK line (a Unity
        # editor and other tests running); dev.py said "it needs a window"
        for rc, hexcode in ((3221225477, "0xC0000005"), (3221226356, "0xC0000374")):
            with self.subTest(rc=hexcode):
                out = "Godot Engine v4.7.2.stable\nVulkan 1.4.341 - Forward+ - Using Device #0\n"
                code, text = self.shader_pass(rc, out)
                self.assertEqual(code, 1, text)
                self.assertIn(f"Godot crashed before drawing a recipe (exit {rc} = {hexcode})", text)
                self.assertNotIn("needs a window", text)

    def test_a_run_that_never_started_keeps_the_window_message(self):
        rc, text = self.shader_pass(1, "Godot Engine v4.7.2.stable\n")
        self.assertEqual(rc, 2, text)
        self.assertIn("it needs a window", text)
        self.assertNotIn("crashed", text)


# ---- #263: no engine's smoke keeps its --data-dir inside the player or build output ---------
class DataDirInBuildOutput(TempRoot):
    """The access sweep kept its runs' settings in build/access/, which is Unity's Build/ on Windows and macOS, so
    the player folder shipped them. Every dev.py now refuses such a --data-dir (exit 2) before it runs or builds
    anything, ignoring letter case, and creates nothing there."""

    def engine(self, name):
        dev = load(name)
        dev.ROOT = self.root
        self.calls = []

        def called(*a, **kw):
            self.calls.append(a)
            raise AssertionError("ran past the --data-dir guard")
        return dev, called

    def refused(self, fn, *args, folder):
        rc, text = quiet(fn, *args)
        self.assertEqual(rc, 2, text)
        self.assertIn("[error] --data-dir", text)
        self.assertNotIn("Traceback", text)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / folder).exists(), f"{folder} was created")
        return text

    def test_godot_refuses_its_export_folders(self):
        dev, called = self.engine("godot")
        dev.run = dev.ensure_imported = called
        shutil.copy2(KIT / "engines" / "godot" / "skeleton" / "export_presets.cfg", self.root / "export_presets.cfg")
        args = argparse.Namespace(data_dir="BUILD/Windows/access", compare="", screenshot="", drive="", locale="",
                                  debug=False)
        self.assertIn("build/windows/", self.refused(dev.cmd_smoke, args, "godot", folder="build/windows"))
        args.data_dir = "build/web/sd"
        self.refused(dev.cmd_run, args, "godot", folder="build/web")
        for ok in ("captures/access/pc", "build/smoke-data", "build/access"):   # not an export folder
            self.assertFalse(dev.data_dir_in_build(ok), ok)

    def test_unity_refuses_its_player_folder(self):
        dev, called = self.engine("unity")
        dev.run_tests = called
        args = argparse.Namespace(screenshot=None, record=None, record_every=6, graphics=False, fail_on=None,
                                  until=None, filter="Smoke", drive="access:res=1280x800,pad",
                                  data_dir="build/access/deck", locale="")
        self.assertIn("player build folder", self.refused(dev.cmd_smoke, args, folder="build/access"))
        args.data_dir = str(self.root / "Build" / "access")                      # an absolute path, too
        self.refused(dev.cmd_smoke, args, folder="Build/access")

    def test_unreal_refuses_packaged_staged_and_binaries(self):
        dev, called = self.engine("unreal")
        dev.preflight = lambda *a, **kw: None
        dev.kit_plugin_state = lambda: "enabled"
        dev.run_automation = dev.run = called
        for folder in ("packaged/access", "Saved/StagedBuilds/x", "Binaries/Win64/x"):
            args = argparse.Namespace(platform=None, filter=None, until=None, fail_on=None, shaders=False,
                                      drive="menus", screenshot="", data_dir=folder, locale="")
            self.refused(dev.cmd_smoke, args, folder=folder)
        self.assertIsNone(dev.build_output_of((self.root / "Saved" / "GameKitSmoke").resolve()))

    def test_cpp_refuses_its_build_trees(self):
        dev, called = self.engine("cpp-sdl2")
        dev.cmd_check = called
        shutil.copy2(KIT / "engines" / "cpp-sdl2" / "skeleton" / "CMakePresets.json", self.root / "CMakePresets.json")
        args = argparse.Namespace(preset="debug", frames=None, screenshot=None, record=None, record_every=4,
                                  game_args=[], timeout=60, until=None, fail_on=None, drive="access",
                                  data_dir="Build/Release/access", locale="")
        self.refused(dev.cmd_smoke, args, folder="Build/Release/access")
        for ok in ("build/smoke-data", "captures/access/pc"):
            self.assertFalse(dev.data_dir_in_build(ok), ok)

    def test_bevy_refuses_cargos_target_folder(self):
        dev, called = self.engine("bevy")
        dev.preflight = dev.build = called
        args = argparse.Namespace(data_dir="target/release/access", drive="access", locale="", frames=None,
                                  timeout=60, game_args=[])
        old = os.environ.pop("CARGO_TARGET_DIR", None)
        try:
            self.refused(dev.cmd_smoke, args, folder="target")
            elsewhere = self.root / "shared-target"
            os.environ["CARGO_TARGET_DIR"] = str(elsewhere)
            args.data_dir = str(elsewhere / "access")
            self.refused(dev.cmd_smoke, args, folder="shared-target")
            self.assertFalse(dev.data_dir_in_build("target/x"))      # target/ is not cargo's folder then
        finally:
            os.environ.pop("CARGO_TARGET_DIR", None)
            if old is not None:
                os.environ["CARGO_TARGET_DIR"] = old

    def test_love_refuses_its_fused_build(self):
        dev, called = self.engine("love2d")
        dev.compile_check = called
        args = argparse.Namespace(data_dir="build/WINDOWS/access", drive="access", locale="", frames=120,
                                  headless=True, screenshot="", record="", compare="", debug=False, game_args=[])
        self.refused(dev.cmd_smoke, args, "love", folder="build/windows")
        self.assertFalse(dev.data_dir_in_build("build/smoke-data"))

    def test_web_overlays_refuse_dist_before_building(self):
        for name in ("web", "web-3d"):
            with self.subTest(engine=name):
                dev, called = self.engine(name)
                dev.cmd_build = dev.run = called
                args = argparse.Namespace(data_dir="Dist/sd", drive="menus", locale="")
                self.refused(dev.cmd_smoke, args, folder="dist")
                self.assertFalse(dev.data_dir_in_build("build/smoke-data"))

    def test_rpgmaker_has_no_data_dir_to_misplace(self):
        # MZ's smoke keeps no user-data folder (no --data-dir): the option is a usage error, not a silent one
        dev = load("rpgmaker-mz")
        with self.assertRaises(SystemExit) as cm:
            quiet(dev.build_parser().parse_args, ["smoke", "--data-dir", "build/web/sd"])
        self.assertEqual(cm.exception.code, 2)


# ---- #271: nor inside a folder the build packs into the game ------------------------------------
class DataDirInPackedFolders(TempRoot):
    """#263 guarded the build outputs only; folders copied INTO a build were not, so a --data-dir there still shipped
    (LÖVE packs src/, assets/ and data/ into the .love, Godot's include_filter takes data/access/*, Unity's
    GameKitBuild copies its DATA_DIRS into StreamingAssets). Every dev.py now refuses those too (exit 2, nothing run
    or created), read from the place the build reads them."""

    def engine(self, name):
        dev = load(name)
        dev.ROOT = self.root
        self.calls = []

        def called(*a, **kw):
            self.calls.append(a)
            raise AssertionError("ran past the --data-dir guard")
        return dev, called

    def refused(self, fn, *args, folder):
        rc, text = quiet(fn, *args)
        self.assertEqual(rc, 2, text)
        self.assertIn("[error] --data-dir", text)
        self.assertNotIn("Traceback", text)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / folder).exists(), f"{folder} was created")
        return text

    def allowed(self, dev, *paths):
        for rel in paths:
            ok, text = quiet(dev.data_dir_in_pack, rel)
            self.assertFalse(ok, f"{rel} refused: {text}")

    def skeleton(self, engine, *rels):
        """Copy files or folders of an engine's skeleton into the temp project (the build's own sources)."""
        for rel in rels:
            src, dst = KIT / "engines" / engine / "skeleton" / rel, self.root / rel
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

    def test_love_refuses_what_the_love_packs(self):
        dev, called = self.engine("love2d")
        dev.compile_check = called
        args = argparse.Namespace(data_dir="data/access/deck", drive="access", locale="", frames=120,
                                  headless=True, screenshot="", record="", compare="", debug=False, game_args=[])
        self.assertIn("data/", self.refused(dev.cmd_smoke, args, "love", folder="data/access/deck"))
        for rel in ("SRC/sd", "assets", "lib/x", "shaders/kit/x"):
            args.data_dir = rel
            self.refused(dev.cmd_smoke, args, "love", folder=rel)
        self.allowed(dev, "captures/access/deck", "build/smoke-data", "data/golden/x", "data/shaders/x", "tests/x")

    def test_godot_reads_the_export_filters(self):
        dev, called = self.engine("godot")
        dev.run = dev.ensure_imported = called
        self.skeleton("godot", "export_presets.cfg")
        args = argparse.Namespace(data_dir="data/access/deck", compare="", screenshot="", drive="", locale="",
                                  debug=False)
        text = self.refused(dev.cmd_smoke, args, "godot", folder="data/access/deck")
        self.assertIn("'data/access/*'", text)
        args.data_dir = "DATA/I18N/x"
        self.refused(dev.cmd_run, args, "godot", folder="DATA/I18N/x")
        self.allowed(dev, "captures/access/pc", "build/smoke-data", "data/golden/x", "data/levels/x")
        # a game's own filter counts, and an exclude_filter wins over it
        cfg = self.root / "export_presets.cfg"
        cfg.write_text(cfg.read_text(encoding="utf-8").replace('include_filter="CREDITS.md,',
                                                               'include_filter="*.json, CREDITS.md,', 1),
                       encoding="utf-8")
        args.data_dir = "captures/pc"
        self.assertIn("'*.json'", self.refused(dev.cmd_smoke, args, "godot", folder="captures/pc"))
        self.allowed(dev, "tests/sd", "data/golden/sd")     # excluded by every preset
        self.allowed(dev, str(Path(tempfile.gettempdir()) / "elsewhere"))   # outside the project: never exported

    def test_godot_smoke_keeps_its_data_folder_out_of_all_resources(self):
        # Godot 4.7.2 exported build/smoke-data/settings.json and captures/pc/settings.json (all_resources takes
        # every .json); a .gdignore keeps a folder out of the import and the export
        dev = load("godot")
        dev.ROOT = self.root
        dev.ensure_imported = lambda godot: 0
        dev.run = lambda *a, **kw: (1, "")
        args = argparse.Namespace(data_dir="", compare="", screenshot="", record="", drive="", locale="", frames=10,
                                  debug=False)
        quiet(dev.cmd_smoke, args, "godot")
        self.assertTrue((self.root / "build" / "smoke-data" / ".gdignore").is_file())
        args.data_dir = "captures/access/pc"
        quiet(dev.cmd_smoke, args, "godot")
        self.assertTrue((self.root / "captures" / "access" / "pc" / ".gdignore").is_file())
        game = self.root / "levels"                          # a folder of the game's own: never hidden
        game.mkdir()
        (game / "one.tscn").write_text("[gd_scene]\n", encoding="utf-8")
        args.data_dir = "levels"
        _, text = quiet(dev.cmd_smoke, args, "godot")
        self.assertFalse((game / ".gdignore").exists())
        self.assertIn("[warn] levels/ holds files of the game (one.tscn)", text)
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(outside), True)
        dev.keep_out_of_export(outside)
        self.assertFalse((outside / ".gdignore").exists())
        dev.keep_out_of_export(self.root)                    # never the whole project
        self.assertFalse((self.root / ".gdignore").exists())

    def test_unity_reads_data_dirs_from_gamekitbuild(self):
        dev, called = self.engine("unity")
        dev.run_tests = called
        self.skeleton("unity", "Assets/Editor/GameKitBuild.cs")
        args = argparse.Namespace(screenshot=None, record=None, record_every=6, graphics=False, fail_on=None,
                                  until=None, filter="Smoke", drive="access:res=1280x800,pad",
                                  data_dir="data/access/deck", locale="")
        self.assertIn("data/access/", self.refused(dev.cmd_smoke, args, folder="data/access/deck"))
        for rel in ("Data/I18n/x", "Assets/StreamingAssets/sd", "Assets/Art/Resources/sd"):
            args.data_dir = rel
            self.refused(dev.cmd_smoke, args, folder=rel)
        self.allowed(dev, "Logs/access/deck", "data/golden/x", "Assets/Art/sd")
        build = self.root / "Assets" / "Editor" / "GameKitBuild.cs"   # a game that adds a folder to DATA_DIRS
        build.write_text(build.read_text(encoding="utf-8").replace('"data/dialogue" }', '"data/dialogue", "data/levels" }'),
                         encoding="utf-8")
        args.data_dir = "data/levels/sd"
        self.refused(dev.cmd_smoke, args, folder="data/levels/sd")

    def test_bevy_refuses_the_asset_folder(self):
        dev, called = self.engine("bevy")
        dev.preflight = dev.build = called
        args = argparse.Namespace(data_dir="Assets/sd", drive="access", locale="", frames=None, timeout=60,
                                  game_args=[])
        self.assertIn("assets/", self.refused(dev.cmd_smoke, args, folder="Assets/sd"))
        self.allowed(dev, "captures/sd", "build/smoke-data", "data/i18n/sd")   # include_str! names files, not folders
        main = self.root / "src" / "main.rs"
        main.parent.mkdir(parents=True)
        main.write_text('fn main() { App::new().add_plugins(DefaultPlugins.set(AssetPlugin { file_path: "content"'
                        '.into(), ..default() })); }\n', encoding="utf-8")
        args.data_dir = "content/sd"
        self.refused(dev.cmd_smoke, args, folder="content/sd")
        self.allowed(dev, "assets/sd")

    def test_cpp_refuses_assets_and_the_shells_data(self):
        dev, called = self.engine("cpp-sdl2")
        dev.cmd_check = called
        self.skeleton("cpp-sdl2", "src/shell/Shell.cpp")
        args = argparse.Namespace(preset="debug", frames=None, screenshot=None, record=None, record_every=4,
                                  game_args=[], timeout=60, until=None, fail_on=None, drive="access",
                                  data_dir="data/i18n/sd", locale="")
        self.refused(dev.cmd_smoke, args, folder="data/i18n/sd")
        for rel in ("assets/sd", "data/access/sd", "Data/Input/sd", "data/dialogue/sd"):
            args.data_dir = rel
            self.refused(dev.cmd_smoke, args, folder=rel)
        self.allowed(dev, "captures/access/pc", "build/smoke-data", "data/golden/sd", "data/shaders/sd")

    def test_web_overlays_refuse_public_and_globbed_folders(self):
        for name in ("web", "web-3d"):
            with self.subTest(engine=name):
                self.tearDown()
                self.setUp()
                dev, called = self.engine(name)
                dev.cmd_build = dev.run = called
                self.skeleton(name, "src", "vite.config.ts")
                args = argparse.Namespace(data_dir="Public/sd", drive="menus", locale="")
                self.assertIn("public/", self.refused(dev.cmd_smoke, args, folder="Public/sd"))
                args.data_dir = "data/shaders/inputs/sd"           # import.meta.glob in src/shaders/shaderCheck.ts
                self.refused(dev.cmd_smoke, args, folder="data/shaders/inputs/sd")
                self.allowed(dev, "build/smoke-data", "build/access/pc")
                if name == "web":                                    # the 2D shell globs its string tables
                    args.data_dir = "data/i18n/sd"
                    self.refused(dev.cmd_smoke, args, folder="data/i18n/sd")
                cfg = self.root / "vite.config.ts"
                cfg.write_text(cfg.read_text(encoding="utf-8").replace('base: "./",', 'base: "./", publicDir: "static",'),
                               encoding="utf-8")
                args.data_dir = "static/sd"
                self.refused(dev.cmd_smoke, args, folder="static/sd")
                self.allowed(dev, "public/sd")


# ---- #252: dev.py ship forwards to tools/cloud/ship.py --------------------------------
class ShipCommand(TempRoot):
    """Every engine's `dev.py ship ...` hands its arguments to tools/cloud/ship.py untouched (its own --target, --plan
    would trip dev.py's parser), adds the engine's web build as --site for a static site, and needs no engine."""
    WEB_BUILDS = {"web": "dist", "web-3d": "dist", "godot": "build/web", "rpgmaker-mz": "build/web"}

    def ship(self, engine, *argv):
        dev = load(engine)
        dev.ROOT = self.root
        tool = self.root / "tools" / "cloud" / "ship.py"
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.write_text("# stand-in\n", encoding="utf-8")
        calls = []
        dev.subprocess.call, saved = (lambda cmd, cwd=None: calls.append([str(c) for c in cmd]) or 0), dev.subprocess.call
        for name in ("find_godot", "find_love"):                 # ship must not need the engine
            if hasattr(dev, name):
                setattr(dev, name, lambda *a, **k: None)
        try:
            rc, text = quiet(dev.main, list(argv))
        finally:
            dev.subprocess.call = saved
        return rc, text, calls

    def test_every_engine_forwards_ship(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                rc, text, calls = self.ship(engine, "ship", "--target", "aws", "--kind", "container", "--plan",
                                            "--image", "me/server:1", "--port", "8080")
                self.assertEqual(rc, 0, text)
                self.assertEqual(len(calls), 1, text)
                self.assertTrue(calls[0][1].endswith("ship.py"))
                self.assertEqual(calls[0][2:], ["--target", "aws", "--kind", "container", "--plan", "--image",
                                                "me/server:1", "--port", "8080"])

    def test_a_static_site_defaults_to_the_engines_web_build(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                rc, text, calls = self.ship(engine, "--debug", "ship", "--target", "do", "--kind", "static", "--plan")
                if engine in self.WEB_BUILDS:
                    self.assertEqual(rc, 0, text)
                    self.assertEqual(calls[0][-2:], ["--site", str(self.root / self.WEB_BUILDS[engine])])
                else:
                    self.assertEqual(rc, 2, text)                 # no web build of its own: --site is required
                    self.assertIn("pass --site", text)
                    self.assertEqual(calls, [])
                rc, text, calls = self.ship(engine, "ship", "--target", "do", "--kind", "static", "--plan",
                                            "--site", "my/site")
                self.assertEqual(calls[0][-2:], ["--site", "my/site"])   # an explicit --site wins

    def test_ship_is_not_taken_from_another_commands_value(self):
        dev = load("cpp-sdl2")
        parser = dev.build_parser()
        self.assertEqual(dev.split_ship(parser, ["smoke", "--until", "ship"]), (["smoke", "--until", "ship"], []))
        self.assertEqual(dev.split_ship(parser, ["--preset", "release", "ship", "--plan"]),
                         (["--preset", "release", "ship"], ["--plan"]))

    def test_the_equals_spellings_are_understood(self):
        # second-model review: "--site=custom" got the engine's default appended after it, which argparse let win
        rc, text, calls = self.ship("web", "ship", "--target", "do", "--kind=static", "--plan", "--site=custom")
        self.assertEqual(rc, 0, text)
        self.assertEqual(calls[0][2:], ["--target", "do", "--kind=static", "--plan", "--site=custom"])
        rc, text, calls = self.ship("web", "ship", "--target", "do", "--kind=static", "--plan")
        self.assertEqual(calls[0][-2:], ["--site", str(self.root / "dist")])


# ---- #90: frame-time budgets in smoke ------------------------------------------------------------
FRAMES_OK = "FRAME_TIMES frames=119 mean=4.10 p95=6.50 p99=9.00 worst=12.25 mode=logic\n"
BUDGET_DOC_ROW = ("| Budget | Target | Measured on | Last measured |\n|---|---|---|---|\n"
                  "| Smoke frame time (p95) | {} | dev.py smoke | |\n")


class FrameBudget(TempRoot):
    """Every engine's smoke reports the FRAME_TIMES line as numbers, fails a p95 over --frame-budget (or the "Smoke
    frame time" row of docs/ARCHITECTURE.md), and says so when nothing was measured instead of passing silently."""

    def module(self, engine):
        dev = load(engine)
        dev.ROOT = self.root
        return dev

    def doc(self, cell):
        (self.root / "docs").mkdir(exist_ok=True)
        (self.root / "docs" / "ARCHITECTURE.md").write_text(BUDGET_DOC_ROW.format(cell), encoding="utf-8")

    def test_the_block_is_the_same_in_every_dev_py(self):
        def block(engine):
            text = (KIT / "engines" / engine / "skeleton" / "tools" / "dev.py").read_text(encoding="utf-8")
            start = text.index("# ---- Frame-time budget (#90)")
            return text[start:text.index("def frame_ms", start)]
        first = block(ENGINES[0])
        for engine in ENGINES[1:]:
            self.assertEqual(block(engine), first, f"{engine}'s frame-time block differs from {ENGINES[0]}'s")

    def test_the_line_is_read_and_reported(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                dev = self.module(engine)
                stats = dev.frame_times("noise\n[INFO][core] " + FRAMES_OK + "SMOKE_DONE\n")
                self.assertEqual(stats, {"frames": 119, "mode": "logic", "mean": 4.1, "p95": 6.5, "p99": 9.0,
                                         "worst": 12.25})
                self.assertIsNone(dev.frame_times("FRAME_TIMES frames=0 mean=0 p95=0 worst=0"))
                self.assertIsNone(dev.frame_times("FRAME_TIMES frames=3 mean=x p95=1 worst=1"))
                rc, text = quiet(dev.frame_budget_report, FRAMES_OK, None, "why")
                self.assertEqual(rc, 0, text)
                self.assertIn("mean 4.10 ms, p95 6.50 ms, p99 9.00 ms, worst 12.25 ms", text)
                self.assertIn("a logic budget, not a render budget", text)

    def test_a_p95_over_budget_fails_with_the_numbers(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                dev = self.module(engine)
                rc, text = quiet(dev.frame_budget_report, FRAMES_OK, 5.0, "why")
                self.assertEqual(rc, 1, text)
                self.assertIn("[FAIL] frame budget: p95 6.50 ms is over 5 ms (--frame-budget)", text)
                rc, text = quiet(dev.frame_budget_report, FRAMES_OK, 6.5, "why")
                self.assertEqual(rc, 0, text)                       # at the budget is within it
                self.assertIn("[ OK ] frame budget", text)

    def test_nothing_measured_says_so_and_why(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                dev = self.module(engine)
                rc, text = quiet(dev.frame_budget_report, "BOOT_OK\n", None, "headless, no clock")
                self.assertEqual(rc, 0, text)
                self.assertIn("frame time: not measured (headless, no clock)", text)
                self.assertNotIn("[WARN]", text)
                rc, text = quiet(dev.frame_budget_report, "BOOT_OK\n", 16.7, "headless, no clock")
                self.assertEqual(rc, 0, text)
                self.assertIn("[WARN] frame budget 16.7 ms (--frame-budget) not checked", text)

    def test_the_budget_row_in_architecture_md(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                dev = self.module(engine)
                self.assertIsNone(dev.doc_frame_budget())             # no docs/ at all
                self.doc("e.g. 20 ms (the template's placeholder)")
                self.assertIsNone(dev.doc_frame_budget())
                self.doc("as fast as possible")
                self.assertIsNone(dev.doc_frame_budget())
                self.doc("5 ms on this machine")
                self.assertEqual(dev.doc_frame_budget(), 5.0)
                rc, text = quiet(dev.frame_budget_report, FRAMES_OK, None, "why")
                self.assertEqual(rc, 1, text)
                self.assertIn("over 5 ms (docs/ARCHITECTURE.md)", text)
                rc, text = quiet(dev.frame_budget_report, FRAMES_OK, 50.0, "why")
                self.assertEqual(rc, 0, text)                       # --frame-budget wins over the row
                (self.root / "docs" / "ARCHITECTURE.md").unlink()

    def test_the_kit_template_has_the_row_unset(self):
        text = (KIT / "core" / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
        dev = load("godot")
        m = dev.BUDGET_ROW.search(text)
        self.assertIsNotNone(m, "core/docs/ARCHITECTURE.md lost its Smoke frame time row")
        self.assertTrue(m.group(1).strip().startswith("e.g."), "the template must not set a budget for every game")

    def test_frame_budget_option_on_every_smoke(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                dev = load(engine)
                parser = dev.build_parser()
                args = parser.parse_args(dev.hoist_global_options(parser, ["smoke", "--frame-budget", "16.7"]))
                self.assertEqual(args.frame_budget, 16.7)
                self.assertIsNone(parser.parse_args(["smoke"]).frame_budget)
                for bad in ("0", "-3", "abc", "nan", "20000"):
                    with self.assertRaises(SystemExit, msg=bad):
                        quiet(parser.parse_args, ["smoke", "--frame-budget", bad])

    def test_the_overlays_that_build_in_smoke_take_no_build(self):
        for engine in ("web", "web-3d", "cpp-sdl2"):
            with self.subTest(engine=engine):
                parser = load(engine).build_parser()
                self.assertTrue(parser.parse_args(["smoke", "--no-build"]).no_build)


class FrameBudgetSmoke(TempRoot):
    """cmd_smoke on each engine with the engine faked: the frame report runs after a passing smoke, and a slow p95
    turns the pass into a failure."""

    def godot(self, out, **opts):
        dev = load("godot")
        dev.ROOT = self.root
        dev.ensure_imported = lambda godot: 0
        dev.run = lambda cmd, **kw: (0, out)
        args = argparse.Namespace(data_dir="", compare="", screenshot="", record="", frames=120, drive="", locale="",
                                  shaders=False, frame_budget=None)
        for k, v in opts.items():
            setattr(args, k, v)
        return quiet(dev.cmd_smoke, args, "godot")

    def test_godot(self):
        out = "[INFO][core] BOOT_OK Test\n" + FRAMES_OK
        rc, text = self.godot(out)
        self.assertEqual(rc, 0, text)
        self.assertIn("frame time over 119 frames (logic", text)
        self.assertEqual(self.godot(out, frame_budget=5.0)[0], 1)
        rc, text = self.godot("[INFO][core] BOOT_OK Test\n", frame_budget=5.0)
        self.assertEqual(rc, 0, text)
        self.assertIn("frame_times.gd", text)                         # says why nothing was measured
        self.assertIn("[WARN] frame budget 5 ms", text)
        self.assertEqual(self.godot("SCRIPT ERROR: x\n" + FRAMES_OK, frame_budget=50.0)[0], 1)   # errors still fail

    def cpp(self, out, **opts):
        dev = load("cpp-sdl2")
        dev.ROOT = self.root
        self.built = []
        dev.cmd_check = lambda args: self.built.append(1) or 0
        dev.find_exe = lambda preset: "game.exe"
        dev.run = lambda cmd, **kw: (0, out)
        args = argparse.Namespace(preset="debug", frames=120, screenshot=None, record=None, record_every=4,
                                  game_args=[], timeout=60, until=None, fail_on=None, frame_budget=None, no_build=False)
        for k, v in opts.items():
            setattr(args, k, v)
        return quiet(dev.cmd_smoke, args)

    def test_cpp(self):
        out = CppSmoke.FULL + FRAMES_OK.replace("logic", "software")
        rc, text = self.cpp(out)
        self.assertEqual(rc, 0, text)
        self.assertIn("software, drawn on the CPU without a display", text)
        self.assertEqual(self.built, [1])
        rc, text = self.cpp(out, frame_budget=6.0, no_build=True)
        self.assertEqual(rc, 1, text)
        self.assertEqual(self.built, [], "--no-build ran the build")
        rc, text = self.cpp(CppSmoke.FULL)
        self.assertIn("main.cpp printed no FRAME_TIMES line", text)

    def test_bevy(self):
        dev = load("bevy")
        dev.ROOT = self.root
        dev.preflight = lambda: None
        dev.build = lambda args: 0
        dev.run = lambda cmd, **kw: (0, "BOOT_OK x 0.1.0\n" + FRAMES_OK + "SMOKE_DONE frames=120\n")
        args = argparse.Namespace(frames=120, screenshot="", record="", record_every=66, record_from=0, game_args=[],
                                  timeout=60, until="", fail_on="", release=False, frame_budget=None)
        rc, text = quiet(dev.cmd_smoke, args)
        self.assertEqual(rc, 0, text)
        self.assertIn("p95 6.50 ms", text)
        args.frame_budget = 1.0
        self.assertEqual(quiet(dev.cmd_smoke, args)[0], 1)

    def test_love(self):
        dev = load("love2d")
        dev.ROOT = self.root
        dev.compile_check = lambda love, files: ([], True, [])
        dev.run = lambda cmd, **kw: (0, "BOOT_OK\n" + FRAMES_OK.replace("logic", "render") + "SMOKE_DONE 120\n")
        args = argparse.Namespace(frames=120, headless=False, screenshot="", record="", record_every=66, drive="",
                                  locale="", data_dir="", debug=False, game_args=[], compare="", tolerance=0,
                                  frame_budget=None)
        rc, text = quiet(dev.cmd_smoke, args, "love")
        self.assertEqual(rc, 0, text)
        self.assertIn("render, drawn in a window", text)
        args.frame_budget = 6.0
        self.assertEqual(quiet(dev.cmd_smoke, args, "love")[0], 1)

    def test_unity_reads_the_unity_log(self):
        dev = load("unity")
        dev.ROOT = self.root
        dev.LOG_FILE = self.root / "Logs" / "dev_unity.log"
        dev.LOG_FILE.parent.mkdir()
        dev.run_tests = lambda *a, **kw: 0
        args = argparse.Namespace(screenshot=None, record=None, record_every=6, graphics=False, fail_on=None,
                                  until=None, filter="Smoke", frame_budget=None)
        dev.LOG_FILE.write_text("Loading\n" + FRAMES_OK + "(Filename: BootSmokeTests.cs Line: 50)\n", encoding="utf-8")
        rc, text = quiet(dev.cmd_smoke, args)
        self.assertEqual(rc, 0, text)
        self.assertIn("p95 6.50 ms", text)
        args.frame_budget = 2.0
        self.assertEqual(quiet(dev.cmd_smoke, args)[0], 1)
        dev.LOG_FILE.write_text("Loading\n", encoding="utf-8")
        rc, text = quiet(dev.cmd_smoke, args)
        self.assertEqual(rc, 0, text)
        self.assertIn("BootSmokeTests", text)

    def test_unreal_reads_the_automation_log(self):
        dev = load("unreal")
        dev.ROOT = self.root
        dev.game_name = lambda: "Test"

        def fake_automation(filter_, args, **kw):
            dev.LAST_LOG[0] = self.log
            return 0
        dev.run_automation = fake_automation
        args = argparse.Namespace(filter="", until="", fail_on="", shaders=False, screenshot="", drive="",
                                  frame_budget=3.0)
        self.log = "Test Completed. Result={Success} Name={Boot}\nLogTemp: " + FRAMES_OK
        rc, text = quiet(dev.cmd_smoke, args)
        self.assertEqual(rc, 1, text)
        self.log = "Test Completed. Result={Success} Name={Boot}\n"
        rc, text = quiet(dev.cmd_smoke, args)
        self.assertEqual(rc, 0, text)
        self.assertIn("-NullRHI draw nothing", text)
        self.assertIn("[WARN] frame budget 3 ms (--frame-budget) not checked", text)

    def test_web_overlays_and_mz_pass_the_line_on(self):
        for engine in ("web", "web-3d", "rpgmaker-mz"):
            with self.subTest(engine=engine):
                dev = load(engine)
                dev.ROOT = self.root
                dev.node_problem = lambda: None
                dev.deps_stale = lambda: False
                dev.cmd_build = lambda args: 0
                dev.need_project = lambda: self.root
                out = "[ OK ] boot marker seen, 120 frames, no errors\n" + FRAMES_OK.replace("logic", "software")
                dev.run = lambda cmd, **kw: (0, out)
                args = argparse.Namespace(frames=120, query="", until="", fail_on="", timeout=30, screenshot="",
                                          record="", record_every=66, drive="", data_dir="", locale="", compare="",
                                          tolerance=0, shaders=False, headed=False, gpu=False, frame_budget=6.0,
                                          no_build=True)
                rc, text = quiet(dev.cmd_smoke, args)
                self.assertEqual(rc, 1, text)
                self.assertIn("p95 6.50 ms is over 6 ms", text)
                args.frame_budget = None
                self.assertEqual(quiet(dev.cmd_smoke, args)[0], 0)


FAKE_PLAYWRIGHT_FRAMES = FAKE_PLAYWRIGHT.replace(
    "          async evaluate() {",
    "          async evaluate(fn) {\n"
    "            if (String(fn).includes(\"s.on = false\")) return [16, 17, 40];   // #90: the frame sampler's read\n")


@unittest.skipUnless(NODE, "node is not on PATH")
class WebSmokeFrameTimes(WebSmokeRecord):
    """#90: smoke.mjs samples the time between animation frames and prints the FRAME_TIMES line dev.py reads; a project
    without tools/frame_times.mjs still runs, measuring nothing."""

    def project(self, engine, sampler=True):
        root = super().project(engine)
        (root / "node_modules" / "playwright" / "index.js").write_text(FAKE_PLAYWRIGHT_FRAMES)
        if sampler:
            shutil.copy2(KIT / "engines" / engine / "skeleton" / "tools" / "frame_times.mjs",
                         root / "tools" / "frame_times.mjs")
        return root

    def test_the_line_after_a_passing_run(self):
        for engine in ("web", "web-3d", "rpgmaker-mz"):
            with self.subTest(engine=engine):
                root = self.project(engine)
                r = subprocess.run([NODE, str(root / "tools" / "smoke.mjs"), "--frames", "1"], cwd=root,
                                   capture_output=True, encoding="utf-8", errors="replace", timeout=60)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("FRAME_TIMES frames=3 mean=24.33 p95=40.00 p99=40.00 worst=40.00 mode=software", r.stdout)
                self.assertEqual(load(engine).frame_times(r.stdout)["p95"], 40.0)

    def test_without_the_sampler_file_the_run_still_passes(self):
        for engine in ("web", "rpgmaker-mz"):
            with self.subTest(engine=engine):
                root = self.project(engine, sampler=False)
                r = subprocess.run([NODE, str(root / "tools" / "smoke.mjs"), "--frames", "1"], cwd=root,
                                   capture_output=True, encoding="utf-8", errors="replace", timeout=60)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertNotIn("FRAME_TIMES", r.stdout)

    def test_a_frozen_page_gives_no_numbers_and_no_hang(self):
        import os
        root = self.project("web")
        r = subprocess.run([NODE, str(root / "tools" / "smoke.mjs"), "--frames", "1", "--timeout-ms", "1000"],
                           cwd=root, capture_output=True, encoding="utf-8", errors="replace", timeout=60,
                           env=dict(os.environ, FAKE_FREEZE="1"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("FRAME_TIMES", r.stdout)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=2)
