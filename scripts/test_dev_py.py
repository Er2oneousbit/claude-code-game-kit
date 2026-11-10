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
#           web, web-3d and RPG Maker MZ smoke.mjs --record leaves only this run's frames (#134; needs node), a
#           refused --drive is one error (#135), web-3d's -h says its --drive aborts (#135), and RPG Maker MZ's
#           setup names the project file it copied (#136), that Unreal's test/smoke exit 1 when the editor
#           crashes before any result, not 2 "no tests matched" (#176), and that Unity's smoke --drive runs the
#           shell's drive test with the run options in the environment and echoes its markers (#168).
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
        rc, text, seen = self.drive("access:res=1280x800,pad", data_dir="build/access/deck")
        self.assertEqual(rc, 0)
        self.assertEqual(Path(seen["env"]["GAMEKIT_DATA_DIR"]), (self.root / "build" / "access" / "deck").resolve())

    def test_drive_names_are_checked(self):
        dev = load("unity")
        for ok in ("", "menus", "show:settings", "access", "access:res=1920x1080,scale=2,pad,read"):
            self.assertEqual(dev.drive_name(ok), ok)
        for bad in ("crash", "show:juice", "access:res=big", "access:pad,"):
            with self.assertRaises(argparse.ArgumentTypeError):
                dev.drive_name(bad)

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
# "screenshot" by writing a small file, and answer any ?drive= with DRIVE_ABORT (as the web-3d skeleton does).
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
              if (drive) emit("error", `[ERROR][drive] DRIVE_ABORT ${drive}: no scripted runs here`);
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
    def test_web_3d_says_its_drive_aborts(self):
        # #135: web-3d has no shell screens, so its -h must not promise the web overlay's scenarios
        for engine, want, not_want in (("web", "menus, crash", "DRIVE_ABORT"), ("web-3d", "DRIVE_ABORT", "menus, crash")):
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
        self.assertIn("-ExecCmds=py " + (self.root / "Content/Python/kit_shaders/shader_check.py").as_posix(), cmd)
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


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=2)
