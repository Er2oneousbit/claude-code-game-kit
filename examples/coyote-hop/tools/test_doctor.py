#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_doctor.py
# Purpose : Exam for doctor.py, the engine-agnostic health check: the asset-log reminder fires in every overlay's
#           media folder (assets, Assets, Content, public/assets, game/img) and stays quiet once a row is filled;
#           the placeholder scan reads the overlays' source files and the profile tokens; a web game's src/shell/
#           that src/main.ts never reaches is reported; the required files, a settings.json Claude Code would drop,
#           the HANDOFF age (its date, a UTF-16 save, the file-time fallback), doc links, --strict, --ignore, exit
#           codes and non-ASCII names in the output (#14).
# Usage   : python tools/test_doctor.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only. Each case copies doctor.py and check_links.py into a fake project under a temp
#           folder and runs it there (doctor.py checks the project its own file sits in).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
import time
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

    def test_the_kits_own_resources_are_not_the_games_media(self):
        """#168: the Unity shell ships its readable font under Assets/Resources/GameKit; a fresh project stays quiet."""
        self.put("Assets/Resources/GameKit/Fonts/AtkinsonHyperlegible-Regular.ttf", "not really a font")
        self.assertNotIn("media file(s) under", self.doctor())
        self.put("Assets/Art/hero.png", "x")
        self.assertIn("1 media file(s) under Assets/", self.doctor())

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


class DoctorKimiFixes(DoctorExam):
    """#258: a UTF-16 asset log read as having no rows."""

    def test_a_utf16_asset_log_is_read(self):
        self.put("assets/art/hero.png", "x")
        (self.root / "docs" / "ASSET_LOG.md").write_bytes(
            (LOG_HEAD + "| A-0001 | hero | assets/art/hero.png | CC0 |\n").encode("utf-16"))
        self.assertNotIn("media file(s) under", self.doctor())


REQUIRED = ["CLAUDE.md", "README.md", "docs/GDD.md", "docs/ARCHITECTURE.md", "docs/ROADMAP.md", "docs/HANDOFF.md",
            "docs/ENGINE.md", "docs/ENGINE_FLOW.md", "docs/STYLE.md", "docs/RESOURCES.md", "docs/FIRST_HOUR.md",
            "docs/EVIDENCE.md", "docs/BRIEFS.md", "docs/ASSET_LOG.md", "docs/TROUBLESHOOTING.md", "docs/sop/README.md",
            "tools/dev.py", ".claude/settings.json"]
SETTINGS = '{"permissions": {"deny": ["Read(./.env)"]}}\n'


class DoctorChecks(unittest.TestCase):
    """#14: the checks the cases above leave out: required files, settings.json, the HANDOFF age, doc links,
    --strict, --ignore, exit codes, -h, and non-ASCII names in the output. Each starts from a healthy project."""

    setUp, tearDown, put = DoctorExam.setUp, DoctorExam.tearDown, DoctorExam.put

    def healthy(self):
        for rel in REQUIRED:
            if not (self.root / rel).exists():
                self.put(rel, "# " + rel + "\n")
        self.put(".claude/settings.json", SETTINGS)
        self.put("docs/HANDOFF.md", "# Handoff\n\n**Last updated:** %s\n" % datetime.date.today().isoformat())

    def run_doctor(self, *extra):
        r = subprocess.run([sys.executable, "-B", str(self.root / "tools" / "doctor.py"), *extra],
                           capture_output=True, encoding="utf-8", errors="strict")
        return r.returncode, r.stdout + r.stderr

    def test_a_healthy_project_exits_0(self):
        self.healthy()
        code, out = self.run_doctor()
        self.assertEqual(code, 0, out)
        self.assertIn("[ OK ] project scaffold looks healthy", out)

    def test_every_missing_required_file_is_named_and_exits_1(self):
        code, out = self.run_doctor()
        self.assertEqual(code, 1, out)
        for rel in REQUIRED:
            if rel != "docs/ASSET_LOG.md":                     # setUp wrote that one
                self.assertIn("MISSING required file: " + rel, out)
        self.assertNotIn("MISSING required file: docs/ASSET_LOG.md", out)

    def test_settings_json_that_claude_code_would_drop(self):
        self.healthy()
        cases = [("{not json", "INVALID .claude/settings.json"),
                 ('{"permissions": {"allow": ["Bash(ls)"]}}', "no permissions.deny rules"),
                 ('{"permissions": {"deny": []}}', "no permissions.deny rules"),
                 # valid JSON that is not an object: the old check called .get on it and crashed (exit 2)
                 ('["Read(./.env)"]', "INVALID .claude/settings.json"),
                 ('{"permissions": ["Read(./.env)"]}', "INVALID .claude/settings.json")]
        for text, want in cases:
            with self.subTest(settings=text):
                self.put(".claude/settings.json", text)
                code, out = self.run_doctor()
                self.assertEqual(code, 1, out)
                self.assertIn(want, out)
                self.assertNotIn("crashed", out)

    def test_an_old_handoff_warns_and_strict_fails(self):
        self.healthy()
        self.put("docs/HANDOFF.md", "# Handoff\n\n**Last updated:** 2020-01-02\n")
        code, out = self.run_doctor()
        self.assertEqual(code, 0, out)                       # a warning alone passes
        self.assertIn("[WARN] HANDOFF.md is", out)
        self.assertIn("(Last updated 2020-01-02)", out)
        self.assertNotIn("looks healthy", out)
        code, out = self.run_doctor("--strict")
        self.assertEqual(code, 1, out)

    def test_handoff_without_a_good_date_falls_back_to_the_file_age(self):
        self.healthy()
        for text in ("# Handoff\n\n**Last updated:** 2026-02-30\n", "# Handoff\n\n**Last updated:** (fill in)\n"):
            with self.subTest(text=text):
                self.put("docs/HANDOFF.md", text)
                self.assertNotIn("HANDOFF.md is", self.run_doctor()[1])      # a fresh file: no warning
                old = time.time() - 40 * 86400
                os.utime(self.root / "docs" / "HANDOFF.md", (old, old))
                out = self.run_doctor()[1]
                self.assertIn("HANDOFF.md is 40 days old (file not touched)", out)

    def test_a_utf16_handoff_date_is_read(self):
        """Notepad's "Unicode" save: the old check read it as UTF-8, found no date and judged the fresh file time."""
        self.healthy()
        (self.root / "docs" / "HANDOFF.md").write_bytes("# Handoff\n\n**Last updated:** 2020-01-02\n".encode("utf-16"))
        self.assertIn("(Last updated 2020-01-02)", self.run_doctor()[1])

    def test_broken_doc_links_warn_and_ignore_skips_a_folder(self):
        self.healthy()
        self.put("docs/GDD.md", "# GDD\n\nSee [the plan](docs/NOPE.md).\n")
        code, out = self.run_doctor()
        self.assertEqual(code, 0, out)
        self.assertIn("broken doc reference in docs/GDD.md", out)
        self.assertEqual(self.run_doctor("--strict")[0], 1)
        name = "{{" + "GAME_NAME}}"
        self.put("localization/fr.json", '{"title": "%s"}\n' % name)
        self.assertIn("in localization/fr.json", self.run_doctor()[1])
        self.assertNotIn("localization/fr.json", self.run_doctor("--ignore", "localization")[1])

    def test_non_ascii_file_names_print_as_utf8(self):
        """Bytes cp1252 cannot decode (0x8D in "Í", 0x9D in a right double quote): the output must be UTF-8."""
        self.healthy()
        name = "Í”notes.md"
        self.put("docs/" + name, "{{" + "GAME_NAME}}\n")
        code, out = self.run_doctor()                          # run_doctor decodes strictly: a bad byte raises
        self.assertEqual(code, 1, out)
        self.assertIn("in docs/" + name, out)

    def test_help_names_every_option(self):
        code, out = self.run_doctor("-h")
        self.assertEqual(code, 0)
        for opt in ("--debug", "--strict", "--assets-dir", "--ignore"):
            self.assertIn(opt, out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
