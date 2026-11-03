#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_doctor.py
# Purpose : Exam for doctor.py, the engine-agnostic health check: the asset-log reminder fires in every overlay's
#           media folder (assets, Assets, Content, public/assets, game/img) and stays quiet once a row is filled.
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

    def test_assets_dir_option_wins(self):
        self.put("public/assets/art/hero.png", "x")
        self.put("other/hero.png", "x")
        self.assertIn("1 media file(s) under other/", self.doctor("--assets-dir", "other"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
