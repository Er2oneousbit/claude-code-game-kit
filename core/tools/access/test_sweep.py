#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_sweep.py
# Purpose : Exam for tools/access/sweep.py (#91, #85), offline: canned `smoke --drive access` logs, one rule broken
#           at a time (text size at 1080p and on a Steam Deck, contrast in a menu, text over the game with and
#           without a panel or outline, clipping, unreachable controls, focus that looks like hover, a missing
#           gamepad binding, a wrong subtitle, keyboard glyphs during gamepad play, a drive that did not finish), and
#           the command line on a saved log.
# Usage   : python tools/access/test_sweep.py      (in a game)   python core/tools/access/test_sweep.py (kit)
# Notes   : Standard library only; no engine runs. The engines' own drives are run by sweep.py itself (README).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sweep  # noqa: E402

GOOD_TEXT = {"text": "Play", "state": "normal", "px": 12, "fg": "#e8edf7", "bg": "#2b3050", "outline": None,
             "fits": True}
GOOD = {
    "input": {"pad": False, "actions": {a: {"keyboard": True, "gamepad": True} for a in ("ui_up", "ui_accept")}},
    "screens": [{"screen": "main_menu", "design": [640, 360], "scaling": "integer", "texts": [GOOD_TEXT],
                 "focus": {"start": "/root/Play", "controls": 1, "reached": 1, "unreached": [], "focus_like_hover": []}}],
    "subtitle": {"visible": True, "speaker": "Guide", "text": "Hello there.", "id": "guide.intro"},
    "prompts": {"device": "pad_other", "actions": {"jump": {"keyboard": "Space", "shown": "South"}}},
    "hold": {"held": True, "dismissed": True},
    "preset": {"applied": True, "reset": True},
    "done": True,
}


def check(log, resolution="1920x1080", pad=False, root=None):
    return sweep.check_run(log, resolution, pad, root or HERE)


def with_text(**changes):
    log = copy.deepcopy(GOOD)
    log["screens"][0]["texts"][0].update(changes)
    return log


def as_log(log):
    """The parsed form back to drive output lines."""
    lines = ["ACCESS_INPUT " + json.dumps(log["input"])]
    lines += ["ACCESS_SCREEN " + json.dumps(s) for s in log["screens"]]
    lines += ["ACCESS_SUBTITLE " + json.dumps(log["subtitle"]), "ACCESS_PROMPTS " + json.dumps(log["prompts"]),
              "ACCESS_HOLD " + json.dumps(log["hold"]), "ACCESS_PRESET " + json.dumps(log["preset"])]
    if log["done"]:
        lines.append("DRIVE_DONE access:res=1920x1080")
    return "\n".join("  " + line for line in lines) + "\n"


class SweepExam(unittest.TestCase):
    def test_a_good_screen_passes_at_both_sizes(self):
        self.assertEqual(check(GOOD)[0], [])
        self.assertEqual(check(GOOD, "1280x800", pad=True)[0], [])

    def test_text_size_is_scaled_by_whole_numbers(self):
        self.assertEqual(sweep.scale_for("1920x1080", [640, 360], "integer"), 3)
        self.assertEqual(sweep.scale_for("1280x800", [640, 360], "integer"), 2)
        self.assertAlmostEqual(sweep.scale_for("1280x800", [640, 360], "fractional"), 2.0)
        self.assertTrue(check(with_text(px=5))[0][0].endswith("15 px at 1920x1080 (under 18, F36)"))
        self.assertEqual(check(with_text(px=6))[0], [])                                 # 18 px passes
        problems, warnings, _ = check(with_text(px=5), "1280x800")                      # 10 px on a Deck: warn
        self.assertEqual(problems, [])
        self.assertIn("12 recommended", warnings[0])
        self.assertIn("under 9", check(with_text(px=4), "1280x800")[0][0])               # 8 px: fail

    def test_contrast_in_a_menu(self):
        problems = check(with_text(fg="#777777", bg="#ffffff"))[0]   # 4.48:1
        self.assertEqual(len(problems), 1)
        self.assertIn("needs 4.5:1", problems[0])
        self.assertEqual(check(with_text(fg="#767676", bg="#ffffff"))[0], [])
        log = with_text(fg="#949494", bg="#ffffff", px=18)                          # a heading, 1.5 x the body
        log["screens"][0]["texts"].append(dict(GOOD_TEXT))
        self.assertEqual(check(log)[0], [])                                          # large: 3:1 is enough
        self.assertIn("needs 4.5:1", check(with_text(fg="#949494", bg="#ffffff", px=18))[0][0])  # alone: body

    def test_text_over_the_game(self):
        # no panel and no outline: whatever the game draws behind it decides (the Godot demo's HUD, found by the
        # sweep before its labels got an outline)
        self.assertIn("no panel or outline", check(with_text(bg=None))[0][0])
        self.assertEqual(check(with_text(bg=None, outline="#000000"))[0], [])
        # a 60 % black panel: white text stays readable over a white game
        self.assertEqual(check(with_text(bg=None, fg="#ffffff", over_game=[["#000000", 0.6]]))[0], [])
        # a 30 % one does not
        self.assertIn("worst case", check(with_text(bg=None, fg="#ffffff", over_game=[["#000000", 0.3]]))[0][0])

    def test_clipped_text(self):
        # the Godot settings tabs ran off the screen at 200 % text before they wrapped
        self.assertIn("clipped or off screen", check(with_text(fits=False))[0][0])
        self.assertIn("(wraps to 5 lines", check(with_text(fits=False, why="wraps to 5 lines, the box holds 2"))[0][0])

    def two_texts(self, ink_b, card_a=None, card_b=None, covered_b=False):
        log = with_text(ink=[0, 0, 100, 20], node="a", card=card_a or {})
        log["screens"][0]["texts"].append(dict(GOOD_TEXT, text="Other", node="b", ink=ink_b, card=card_b or {},
                                               covered=covered_b))
        return log

    def test_text_that_runs_into_other_text(self):
        # LÖVE's demo HUD rows collided at 200 % text before their height followed the font
        self.assertIn("runs into", check(self.two_texts([50, 10, 100, 20]))[0][0])
        self.assertEqual(check(self.two_texts([0, 20, 100, 20]))[0], [])          # touching rows: fine
        self.assertEqual(check(self.two_texts([50, 10, 100, 20], covered_b=True))[0], [])   # hidden: not checked
        # the HUD under a pause panel: the later panel covers the spot, so nothing collides on screen
        panel = {"order": 9, "rect": [40, 0, 200, 100]}
        self.assertEqual(check(self.two_texts([50, 10, 100, 20], card_b=panel))[0], [])
        # the same texts beside the panel: a real collision
        self.assertIn("runs into", check(self.two_texts([50, 10, 100, 20],
                                                        card_b={"order": 9, "rect": [500, 0, 10, 10]}))[0][0])

    def test_covered_text_is_skipped(self):
        # text under a dialog cannot be seen: no contrast, size or fit check for it
        self.assertEqual(check(with_text(px=1, fg="#000000", bg="#000000", fits=False, covered=True))[0], [])

    def test_focus(self):
        log = copy.deepcopy(GOOD)
        log["screens"][0]["focus"]["unreached"] = ["/root/Credits"]
        self.assertIn("cannot be reached", check(log)[0][0])
        log = copy.deepcopy(GOOD)
        log["screens"][0]["focus"]["focus_like_hover"] = ["/root/Play"]
        self.assertIn("same focused as hovered", check(log)[0][0])
        log = copy.deepcopy(GOOD)
        log["screens"][0]["focus"]["start"] = ""
        self.assertIn("nothing has focus", check(log)[0][0])

    def test_both_devices_bound(self):
        log = copy.deepcopy(GOOD)
        log["input"]["actions"]["ui_accept"]["gamepad"] = False
        self.assertEqual(check(log)[0], ["input: ui_accept has no gamepad binding"])

    def test_subtitles(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "data" / "dialogue").mkdir(parents=True)
            (Path(d) / "data/dialogue/x.built.json").write_text(json.dumps(
                {"lines": {"guide.intro": {"text": "Hello there."}}}), encoding="utf-8")
            self.assertEqual(check(GOOD, root=Path(d))[0], [])
            log = copy.deepcopy(GOOD)
            log["subtitle"]["text"] = "Hello."
            self.assertIn("the dialogue file says", check(log, root=Path(d))[0][0])
        log = copy.deepcopy(GOOD)
        log["subtitle"]["visible"] = False
        self.assertIn("not on screen", check(log)[0][0])
        log["subtitle"] = None
        self.assertIn("no subtitle", check(log)[0][0])

    def test_keyboard_glyphs_during_gamepad_play(self):
        log = copy.deepcopy(GOOD)
        log["prompts"]["actions"]["jump"]["shown"] = "Space"
        self.assertEqual(check(log)[0], [])                        # a keyboard run: not checked
        self.assertIn("keyboard's 'Space'", check(log, "1280x800", pad=True)[0][0])
        log = copy.deepcopy(GOOD)
        log["prompts"]["device"] = "keyboard"
        self.assertIn("device is 'keyboard'", check(log, "1280x800", pad=True)[0][0])

    def test_a_held_subtitle_must_wait_and_then_go(self):
        # #167, found live: Godot's bar kept the line but missed the accept the drive pressed
        log = copy.deepcopy(GOOD)
        log["hold"] = {"held": True, "dismissed": False}
        self.assertIn("subtitle_hold", check(log)[0][0])
        log["hold"] = {"held": False, "dismissed": True}
        self.assertIn("held False", check(log)[0][0])

    def test_every_focusable_control_says_something(self):
        # #165: a control with no label would be narrated as "unlabelled, button"
        log = copy.deepcopy(GOOD)
        log["screens"][0]["focus"]["narration"] = {"/root/Play": "Play, button"}
        self.assertEqual(check(log)[0], [])
        log["screens"][0]["focus"]["narration"]["/root/Icon"] = "unlabelled, button"
        self.assertIn("give it a label", check(log)[0][0])

    def test_the_one_handed_layout_must_apply_and_reset(self):
        log = copy.deepcopy(GOOD)
        log["preset"] = {"applied": False, "reset": True}
        self.assertIn("one-handed layout", check(log)[0][0])

    def test_a_drive_that_did_not_finish_fails(self):
        log = copy.deepcopy(GOOD)
        log["done"] = False
        self.assertIn("did not finish", check(log)[0][0])

    def test_a_game_without_the_shells_screens_is_a_clear_exit_2(self):
        # two Godot examples build their own main scene: the drive never starts, which is not a failed check
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "tools").mkdir()
            (Path(d) / "tools" / "dev.py").write_text("print('BOOT_OK my game')\n", encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sweep.main(["--runs", "pc", "--root", d]), 2)
            self.assertIn("never started", err.getvalue())

    def test_every_run_starts_from_a_fresh_data_folder(self):
        # found live on web: the drive saves settings, and the next run started at the last run's text size, so
        # the "100 %" run checked 200 % text and missed every row scrolled out of view
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "tools").mkdir()
            (Path(d) / "tools" / "dev.py").write_text(
                "import sys, pathlib\n"
                "i = sys.argv.index('--data-dir')\n"
                "folder = pathlib.Path(sys.argv[i + 1])\n"
                "with open('runs.txt', 'a') as f: f.write(sys.argv[i + 1] + ' ' + str(folder.exists()) + '\\n')\n"
                "folder.mkdir(parents=True, exist_ok=True)\n"
                "(folder / 'settings.json').write_text('{}')\n", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                sweep.main(["--runs", "pc", "--root", d])       # exits 2 (no drive): the folders are what counts
                sweep.main(["--runs", "pc", "--root", d])       # again: the folder from the first time must go
            runs = (Path(d) / "runs.txt").read_text(encoding="utf-8").split()
            self.assertEqual(runs[0], "captures/access/pc")
            self.assertEqual(runs[1:4:2], ["False", "False"])    # never an old folder, even on the second sweep

    def test_browser_console_lines_are_read(self):
        # the web shell's lines arrive with the browser's own prefix
        text = "".join("[console.info] [INFO][drive] " + line.strip() + "\n" for line in as_log(GOOD).splitlines())
        self.assertEqual(sweep.parse(text), GOOD)

    def test_parse_and_the_command_line(self):
        self.assertEqual(sweep.parse(as_log(GOOD)), GOOD)
        with self.assertRaises(sweep.UsageError):
            sweep.parse("ACCESS_SCREEN {broken")
        with tempfile.TemporaryDirectory() as d:
            good, bad = Path(d) / "good.log", Path(d) / "bad.log"
            good.write_text(as_log(GOOD), encoding="utf-8")
            bad.write_text(as_log(with_text(fits=False)), encoding="utf-8")
            report = Path(d) / "out" / "access.md"
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(sweep.main(["--log", str(good), "--root", d, "--report", str(report)]), 0)
                self.assertEqual(sweep.main(["--log", str(bad), "--root", d]), 1)
            self.assertIn("# Accessibility sweep", report.read_text(encoding="utf-8"))
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sweep.main(["--root", d]), 2)          # no tools/dev.py here
            self.assertIn("[error]", err.getvalue())


class SweepDataOutsideThePlayer(unittest.TestCase):
    """#263: the runs' settings folders went to build/access/, which on Windows and macOS is Unity's player folder
    Build/, so a shipped Build/ carried Build/access/<run>/settings.json next to game.exe."""

    def test_a_unity_player_folder_gets_none_of_the_runs_data(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "Build").mkdir()
            (root / "Build" / "game.exe").write_bytes(b"MZ player")
            (root / "tools").mkdir()
            (root / "tools" / "dev.py").write_text(       # a stand-in dev.py: records the folder, writes settings
                "import sys, pathlib\n"
                "folder = pathlib.Path(sys.argv[sys.argv.index('--data-dir') + 1])\n"
                "with open('runs.txt', 'a') as f: f.write(folder.as_posix() + '\\n')\n"
                "folder.mkdir(parents=True, exist_ok=True)\n"
                "(folder / 'settings.json').write_text('{}')\n"
                "print('ACCESS_INPUT {\"actions\": {}}')\n", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                sweep.main(["--runs", "all", "--root", d])       # the checks fail (no screens): where the data went counts
            runs = (root / "runs.txt").read_text(encoding="utf-8").split()
            self.assertEqual(len(runs), len(sweep.RUNS))
            for run in runs:                                    # build/ and Build/ are one folder on Windows
                self.assertNotEqual(Path(run).parts[0].lower(), "build", run)
            self.assertEqual(sorted(p.name for p in (root / "Build").iterdir()), ["game.exe"])


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=1)
