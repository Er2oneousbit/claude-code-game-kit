#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_doctor.py
# Purpose : Exam for doctor.py, the engine-agnostic health check: the asset-log reminder fires in every overlay's
#           media folder (assets, Assets, Content, public/assets, game/img) and stays quiet once a row is filled;
#           the placeholder scan reads the overlays' source files and the profile tokens; a web game's src/shell/
#           that src/main.ts never reaches is reported.
# Usage   : python tools/test_doctor.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only. Each case copies doctor.py and check_links.py into a fake project under a temp
#           folder and runs it there (doctor.py checks the project its own file sits in).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG_HEAD = "# Asset log\n\n| ID | Asset | File(s) in repo | License |\n|---|---|---|---|\n"
SAMPLE_ROW = "| A-0001 | sample | | |\n"


class DoctorExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "game"
        (self.root / "tools").mkdir(parents=True)
        for name in ("doctor.py", "check_links.py"):
            shutil.copy2(HERE / name, self.root / "tools" / name)
        self.put("docs/ASSET_LOG.md", LOG_HEAD + SAMPLE_ROW)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text=""):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def doctor(self, *extra):
        r = subprocess.run([sys.executable, "-B", str(self.root / "tools" / "doctor.py"), *extra],
                           capture_output=True, encoding="utf-8", errors="replace")
        return r.stdout + r.stderr

    def test_asset_log_reminder_in_every_overlay_layout(self):
        """#104: web, web-3d (public/assets) and RPG Maker MZ (game/img) were never checked."""
        for folder, media in (("assets", "art/hero.png"), ("Assets", "Art/hero.png"), ("Content", "Audio/hit.wav"),
                              ("public/assets", "art/hero.png"), ("game/img", "characters/Actor1.png")):
            with self.subTest(folder=folder):
                self.put(f"{folder}/{media}", "not really an image")
                out = self.doctor()
                self.assertIn(f"1 media file(s) under {folder}/ but ASSET_LOG.md has no real entries", out)
                shutil.rmtree(self.root / folder.split("/")[0])

    def test_filled_row_quiets_it(self):
        self.put("public/assets/art/hero.png", "x")
        self.put("docs/ASSET_LOG.md", LOG_HEAD + "| A-0001 | hero | public/assets/art/hero.png | CC0 |\n")
        self.assertNotIn("media file(s) under", self.doctor())

    def test_raw_templates_in_source_files_are_caught(self):
        """#122: only .md .json .py ... were scanned, and only the six name tokens (not the profile ones)."""
        footer, name = "{{" + "FOOTER}}", "{{" + "GAME_NAME}}"      # split: this exam ships into games itself
        self.put("scripts/core/spring.gd", f"extends Node\n\n# {footer}\n")
        self.put("src/main.ts", f"document.title = '{name}';\n")
        self.put("src/game.lua", f"-- {footer}\n")
        self.put("data/dialogue.json", '{"line": "{{' + 'PLAYER_NAME}} wins"}\n')   # a game's own template: fine
        out = self.doctor()
        self.assertIn(f"UNRESOLVED placeholder(s) ['{footer}'] in scripts/core/spring.gd", out)
        self.assertIn(f"UNRESOLVED placeholder(s) ['{name}'] in src/main.ts", out)
        self.assertIn("in src/game.lua", out)
        self.assertNotIn("dialogue.json", out)

    def test_unwired_web_shell_is_reported(self):
        """#182: a web game kept its own main.ts, so src/shell/ (title, menus, settings, pause) never ran."""
        warn = "src/shell/app.ts is never imported from src/main.ts"
        self.assertNotIn(warn, self.doctor())                                   # no shell: nothing to say
        self.put("src/shell/app.ts", "export const shell = {};\n")
        self.put("src/shell/screens.ts", 'import type { Shell } from "./app";\n')
        self.put("src/game/MainScene.ts", 'import { shell } from "../shell/app";\n')   # a scene nothing loads
        self.put("src/main.ts", '// Usage: import { shell } from "./shell/app"\nimport * as Phaser from "phaser";\n'
                                'import type { Shell } from "./shell/app";\nimport { GateScene } from "./game/GateScene";\n')
        self.put("src/game/GateScene.ts", 'import { Log } from "../core/log";\n')
        out = self.doctor()
        self.assertIn(warn, out)
        self.assertIn("/game-shell", out)
        # Reached through another module (main -> GateScene -> shell/app), a multi-line import naming app.js: wired
        self.put("src/game/GateScene.ts", 'import {\n  shell,\n} from "../shell/app.js";\n')
        self.assertNotIn(warn, self.doctor())
        # Imported straight from main.ts, as the web skeleton does
        self.put("src/game/GateScene.ts", "export {};\n")
        self.put("src/main.ts", 'import { shell } from "./shell/app";\nimport * as Phaser from "phaser";\n')
        self.assertNotIn(warn, self.doctor())

    def test_assets_dir_option_wins(self):
        self.put("public/assets/art/hero.png", "x")
        self.put("other/hero.png", "x")
        self.assertIn("1 media file(s) under other/", self.doctor("--assets-dir", "other"))


class DoctorReviewFixes(DoctorExam):
    """#247: Path.exists() ignores case on Windows; a UTF-16 file was skipped, so its placeholder passed."""

    def test_a_required_file_in_the_wrong_case_is_missing(self):
        import doctor
        self.put("docs/gdd.md", "# GDD\n")
        if not (self.root / "docs" / "GDD.md").exists():
            self.skipTest("case-sensitive file system: the bug cannot happen here")
        self.assertIn("other letter case", self.doctor())

    def test_a_utf16_file_is_scanned(self):
        footer = "{{" + "FOOTER}}"
        path = self.root / "scripts" / "wide.gd"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"extends Node\n# {footer}\n".encode("utf-16"))
        self.assertIn("in scripts/wide.gd", self.doctor())


if __name__ == "__main__":
    unittest.main(verbosity=2)
