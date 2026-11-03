#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_sync_examples.py
# Purpose : Exam for sync_examples.py. Builds a tiny fake kit (the real new_game.py and sync_examples.py, a three-file
#           core, one fake engine) and a fake example inside it, all under a temp folder, then checks: a kit file
#           changed in core comes back to the example; a file the game edited does not (a .gold is reported, exit 1);
#           .claude/settings.json and .gitignore come back merged, keeping the game's own rules; a binary kit file
#           syncs; a second run reports 0 synced and leaves .game-kit.json byte for byte as it was (no history entry
#           per no-op run); a CRLF checkout of a kit file is not a change; a failed upgrade copies nothing back;
#           usage errors exit 2.
# Usage   : python scripts/test_sync_examples.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only, offline. Never touches the kit's real examples/: sync_examples.py finds the kit
#           from its own location, so the exam runs the copy inside the fake kit. About 10 s (one scaffold per case).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   setUp: temp/kit = new_game.py + sync_examples.py + core/ + engines/fake/ + profiles/default.json
#          scaffold "Fake Game" into temp/seed, copy it to temp/kit/examples/fake-game (the example)
#   each case: change the fake kit and/or the example -> run the fake kit's sync_examples.py into a fresh work
#          folder outside the fake kit -> check the example's files, the report and the exit code
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = ("new_game.py", "sync_examples.py")          # the real tools under test, copied into the fake kit
NAME = "Fake Game"
PNG_V1 = b"\x89PNG\r\n\x1a\n" + bytes(range(200, 256)) + b"v1"   # a CRLF inside, not UTF-8: must hash raw
PNG_V2 = b"\x89PNG\r\n\x1a\n" + bytes(range(200, 256)) + b"v2"
CORE = {
    "CLAUDE.md": "# {{GAME_NAME}}\nKit memory v1.\n",
    "docs/GDD.md": "# {{GAME_NAME}} design\nFill this in.\n",
    "tools/kit_tool.py": "print('kit tool v1')\n",
    ".gitignore": "*.tmp\n",
}
CORE_SETTINGS = {"permissions": {"allow": ["Bash(python tools/dev.py check)"]}}
ENGINE = {"id": "fake", "label": "Fake Engine", "summary": "for the exam", "skeleton_dir": "skeleton",
          "engine_md": "ENGINE.md", "flow_md": "FLOW.md", "assets_dir": "assets"}


def write(path, text):
    """UTF-8, LF line ends on every OS (write_bytes: Path.write_text has no newline= before Python 3.10)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def run(args):
    r = subprocess.run([sys.executable, "-B", *[str(a) for a in args]], capture_output=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


class SyncExamplesExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.kit = self.root / "kit"
        self.runs = 0
        for name in TOOLS:
            dst = self.kit / "scripts" / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(HERE / name, dst)
        for rel, text in CORE.items():
            write(self.kit / "core" / rel, text)
        (self.kit / "core" / "art").mkdir(parents=True)
        (self.kit / "core" / "art" / "logo.png").write_bytes(PNG_V1)
        self.set_core_settings(CORE_SETTINGS)
        eng = self.kit / "engines" / "fake"
        write(eng / "engine.json", json.dumps(ENGINE, indent=2))
        write(eng / "ENGINE.md", "# Fake engine\n")
        write(eng / "FLOW.md", "# Fake flow\n")
        write(eng / "skeleton" / "main.txt", "starter for {{GAME_NAME}}\n")
        write(self.kit / "profiles" / "default.json", json.dumps({"author": "", "footer": "", "style": []}))
        # The example: a real scaffold made outside the fake kit (new_game.py refuses a dest inside it), moved in
        seed = self.root / "seed"
        code, out = run([self.kit / "scripts" / "new_game.py", "--name", NAME, "--engine", "fake",
                         "--dest", seed, "--author", "Tester"])
        self.assertEqual(code, 0, out)
        self.ex = self.kit / "examples" / "fake-game"
        shutil.copytree(seed, self.ex)

    def tearDown(self):
        self.tmp.cleanup()

    # ---- helpers ------------------------------------------------------------
    def set_core_settings(self, data):
        write(self.kit / "core" / ".claude" / "settings.json", json.dumps(data, indent=2) + "\n")

    def sync(self, *extra):
        """One sync_examples.py run into a fresh work folder outside the fake kit."""
        self.runs += 1
        return run([self.kit / "scripts" / "sync_examples.py", self.root / f"work{self.runs}", *extra])

    def ex_text(self, rel):
        return (self.ex / rel).read_bytes().decode("utf-8")

    def meta_bytes(self):
        return (self.ex / ".game-kit.json").read_bytes()

    # ---- cases --------------------------------------------------------------
    def test_noop_run_reports_zero_and_leaves_the_example_alone(self):
        before = self.meta_bytes()
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertIn("[ OK ] fake-game: 0 synced", out)
        self.assertEqual(self.meta_bytes(), before, ".game-kit.json changed on a run with nothing to sync")

    def test_kit_change_comes_back_and_second_run_is_zero(self):
        write(self.kit / "core" / "tools" / "kit_tool.py", "print('kit tool v2')\n")
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertIn("1 synced ['tools/kit_tool.py']", out)
        self.assertEqual(self.ex_text("tools/kit_tool.py"), "print('kit tool v2')\n")
        meta = json.loads(self.meta_bytes())
        self.assertEqual(len(meta["history"]), 2, "the synced upgrade is recorded once")
        after_first = self.meta_bytes()
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertIn("[ OK ] fake-game: 0 synced", out)
        self.assertEqual(self.meta_bytes(), after_first, "a second, no-op run grew .game-kit.json")

    def test_game_edit_is_kept_and_gold_reported(self):
        write(self.ex / "docs" / "GDD.md", "# Fake Game design\nThe game's own plan.\n")
        write(self.kit / "core" / "docs" / "GDD.md", "# {{GAME_NAME}} design\nFill this in. New kit section.\n")
        write(self.kit / "core" / "tools" / "kit_tool.py", "print('kit tool v2')\n")
        code, out = self.sync()
        self.assertEqual(code, 1, out)
        self.assertIn("[warn] fake-game: hand-merge", out)
        self.assertIn("docs/GDD.md.gold", out)
        self.assertEqual(self.ex_text("docs/GDD.md"), "# Fake Game design\nThe game's own plan.\n")
        self.assertFalse((self.ex / "docs" / "GDD.md.gold").exists(), "the .gold belongs in the work folder")
        self.assertEqual(self.ex_text("tools/kit_tool.py"), "print('kit tool v2')\n", "untouched files still sync")

    def test_settings_come_back_merged_keeping_the_game_rules(self):
        own = json.loads(self.ex_text(".claude/settings.json"))
        own["permissions"]["allow"].append("Bash(python tools/game_only.py)")
        own["env"] = {"GAME_FLAG": "1"}
        write(self.ex / ".claude" / "settings.json", json.dumps(own, indent=2) + "\n")
        new = json.loads(json.dumps(CORE_SETTINGS))
        new["permissions"]["allow"].append("Bash(python tools/dev.py test)")
        self.set_core_settings(new)
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertIn(".claude/settings.json", out)
        merged = json.loads(self.ex_text(".claude/settings.json"))
        allow = merged["permissions"]["allow"]
        for rule in ("Bash(python tools/dev.py check)", "Bash(python tools/game_only.py)",
                     "Bash(python tools/dev.py test)"):
            self.assertIn(rule, allow)
        self.assertEqual(merged["env"], {"GAME_FLAG": "1"})
        self.assertIn("0 synced", self.sync()[1])

    def test_gitignore_rule_comes_back_appended(self):
        write(self.ex / ".gitignore", self.ex_text(".gitignore") + "game_only/\n")
        write(self.kit / "core" / ".gitignore", "*.tmp\n*.bak\n")
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        text = self.ex_text(".gitignore")
        self.assertIn("game_only/", text)
        self.assertIn("*.bak", text)
        self.assertIn("0 synced", self.sync()[1])

    def test_binary_kit_file_syncs(self):
        (self.kit / "core" / "art" / "logo.png").write_bytes(PNG_V2)
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual((self.ex / "art" / "logo.png").read_bytes(), PNG_V2)
        self.assertIn("0 synced", self.sync()[1])

    def test_crlf_checkout_is_not_a_change(self):
        p = self.ex / "tools" / "kit_tool.py"
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertIn("0 synced", out)
        self.assertIn(b"\r\n", p.read_bytes(), "a CRLF copy of the kit's version was overwritten")

    def test_failed_upgrade_copies_nothing_back(self):
        write(self.kit / "core" / "tools" / "kit_tool.py", "print('kit tool v2')\n")
        write(self.kit / "core" / "docs" / "BROKEN.md", "{{NOT_A_PLACEHOLDER}}\n")
        before = self.meta_bytes()
        code, out = self.sync()
        self.assertEqual(code, 1, out)
        self.assertIn("[FAIL] fake-game: upgrade failed (exit 1)", out)
        self.assertEqual(self.ex_text("tools/kit_tool.py"), "print('kit tool v1')\n")
        self.assertFalse((self.ex / "docs" / "BROKEN.md").exists())
        self.assertEqual(self.meta_bytes(), before)

    def test_usage_errors_exit_2(self):
        (self.root / "taken").mkdir()
        code, out = run([self.kit / "scripts" / "sync_examples.py", self.root / "taken"])
        self.assertEqual(code, 2, out)
        self.assertIn("use a fresh folder", out)
        code, out = run([self.kit / "scripts" / "sync_examples.py", self.kit / "inside"])
        self.assertEqual(code, 2, out)
        self.assertIn("outside the kit", out)
        code, out = self.sync("--only", "no-such-game")
        self.assertEqual(code, 2, out)
        self.assertIn("not an example: no-such-game", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
