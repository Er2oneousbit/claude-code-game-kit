#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_credits.py
# Purpose : Exam for tools/credits.py: the files are built from the asset log, unknown licenses and PLACEHOLDER rows
#           stop it, --check catches a stale file, license texts are included verbatim, the template row is skipped.
# Usage   : python tools/test_credits.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import credits  # noqa: E402

HEADER = ("| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) | "
          "AI-assisted? | Modified? | Date added | Notes |\n|---|---|---|---|---|---|---|---|---|---|---|\n")
TEMPLATE_ROW = "| A-0001 | | | | | | | no | no | 2026-11-01 | |\n"
GOOD = ("| A-0002 | Music | assets/audio/theme.ogg | https://example.org/theme | Ana Sousa | CC-BY 4.0 | "
        "\"Theme\" by Ana Sousa (CC-BY 4.0) | no | yes | 2026-11-01 | |\n"
        "| A-0003 | Font | assets/fonts/pix.ttf | https://example.org/pix | Íris Nø | OFL-1.1 | | no | no | 2026-11-01 | |\n"
        "| A-0004 | Art | assets/art/hero.png | Dotwork | this project | CC0-1.0 | | pre-generated | no | 2026-11-01 | |\n")


class Credits(unittest.TestCase):
    def game(self, rows, engine="godot"):
        root = Path(tempfile.mkdtemp())
        (root / "docs" / "licenses").mkdir(parents=True)
        (root / "docs" / "ASSET_LOG.md").write_text("# Asset Log\n\n" + HEADER + TEMPLATE_ROW + rows + "\n## Rules\n",
                                                   encoding="utf-8")
        (root / "docs" / "licenses" / "OFL-1.1.txt").write_text("SIL OPEN FONT LICENSE Version 1.1\n", encoding="utf-8")
        (root / ".game-kit.json").write_text(json.dumps({"engine": engine}), encoding="utf-8")
        return root

    def run_cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = credits.main([str(a) for a in args])
        return code, buf.getvalue()

    def test_builds_both_files(self):
        root = self.game(GOOD)
        code, out = self.run_cli("--root", root)
        self.assertEqual(code, 0, out)
        c = (root / "CREDITS.md").read_text(encoding="utf-8")
        self.assertIn("Godot Engine (MIT license)", c)
        self.assertIn("\"Theme\" by Ana Sousa (CC-BY 4.0)", c)
        self.assertIn("Íris Nø", c)
        self.assertIn("made with AI assistance (pre-generated)", c)
        self.assertNotIn("A-0001", c)                                   # the empty template row
        lic = (root / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
        self.assertIn("**OFL-1.1**: A-0003", lic)
        self.assertIn("SIL OPEN FONT LICENSE Version 1.1", lic)

    def test_check_passes_then_catches_stale(self):
        root = self.game(GOOD)
        self.run_cli("--root", root)
        self.assertEqual(self.run_cli("--root", root, "--check")[0], 0)
        log = root / "docs" / "ASSET_LOG.md"
        log.write_text(log.read_text(encoding="utf-8").replace("\"Theme\" by Ana Sousa", "\"Theme\" by A. Sousa"),
                       encoding="utf-8")
        code, out = self.run_cli("--root", root, "--check")
        self.assertEqual(code, 1)
        self.assertIn("CREDITS.md is out of date", out)

    def test_unknown_license_stops_it(self):
        root = self.game(GOOD + "| A-0005 | SFX | assets/audio/hit.wav | some site | ? | unknown | | no | no | x | |\n")
        code, out = self.run_cli("--root", root)
        self.assertEqual(code, 1)
        self.assertIn("A-0005: no license recorded", out)
        self.assertFalse((root / "CREDITS.md").exists())

    def test_placeholder_needs_the_flag(self):
        root = self.game(GOOD + "| A-0006 | Art | assets/art/tmp.png | store | x | CC-BY-NC 4.0 | | no | no | x | "
                                "PLACEHOLDER until the art pass |\n")
        self.assertEqual(self.run_cli("--root", root)[0], 1)
        self.assertEqual(self.run_cli("--root", root, "--allow-placeholders")[0], 0)

    def test_engine_line_and_out_folder(self):
        root = self.game(GOOD, engine="love2d")
        out = root / "build" / "windows"
        self.assertEqual(self.run_cli("--root", root, "--out", out)[0], 0)
        self.assertIn("LÖVE (zlib license)", (out / "CREDITS.md").read_text(encoding="utf-8"))

    def test_blank_line_inside_the_table_keeps_later_rows(self):
        root = self.game(GOOD.replace("| A-0003", "\n| A-0003", 1))
        self.assertEqual(self.run_cli("--root", root)[0], 0)
        self.assertIn("Íris Nø", (root / "CREDITS.md").read_text(encoding="utf-8"))

    def test_missing_log_is_usage(self):
        self.assertEqual(self.run_cli("--root", tempfile.mkdtemp())[0], 2)

    def test_kit_template_parses(self):
        # the shipped ASSET_LOG.md (only its template row) gives an engine-only credits file
        rows = credits.parse_log((Path(__file__).resolve().parents[1] / "docs" / "ASSET_LOG.md").read_text(
            encoding="utf-8"))
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
