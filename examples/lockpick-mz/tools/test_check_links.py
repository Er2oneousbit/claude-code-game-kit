#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_check_links.py
# Purpose : Exam for check_links.py: a good reference passes, a broken one is
#           caught, template names and URLs are ignored.
# Usage   : python tools/test_check_links.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_links  # noqa: E402


class CheckLinksExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs" / "sop").mkdir(parents=True)
        (self.root / "docs" / "GDD.md").write_text("# GDD\n", encoding="utf-8")
        (self.root / "docs" / "sop" / "SOP-01.md").write_text("# SOP\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def scan_text(self, text):
        (self.root / "README.md").write_text(text, encoding="utf-8")
        return check_links.scan(self.root, [], [])

    def test_good_link_and_path_pass(self):
        self.assertEqual(self.scan_text("[gdd](docs/GDD.md) and `docs/sop/SOP-01.md`"), {})

    def test_broken_link_caught(self):
        broken = self.scan_text("see [x](docs/NOPE.md)")
        self.assertIn("link: docs/NOPE.md", broken["README.md"])

    def test_broken_backtick_path_caught(self):
        broken = self.scan_text("read `docs/sop/SOP-99.md` first")
        self.assertIn("path: docs/sop/SOP-99.md", broken["README.md"])

    def test_bare_name_found_anywhere(self):
        self.assertEqual(self.scan_text("open `SOP-01.md`"), {})

    # ---- audit pass 7: false positives that must stay quiet ----
    def test_uri_schemes_anchors_and_angle_links_pass(self):
        (self.root / "docs" / "a b.md").write_text("# spaced\n", encoding="utf-8")
        text = ("`res://scenes/main.tscn` `user://save.json` `docs/GDD.md#pillars` [x](<docs/a b.md>) [y](docs/a%20b.md)\n"
                "~~~\n[z](docs/NOPE.md)\n~~~\n`[w](docs/NOPE.md)` [t](docs/GDD.md \"title\")\n")
        self.assertEqual(self.scan_text(text), {})

    # ---- audit pass 7: false negatives that must be caught ----
    def test_titled_and_reference_links_are_checked(self):
        broken = self.scan_text('[t](docs/NOPE.md "title")\n\n[ref]: docs/ALSO_NOPE.md\n')
        self.assertIn("link: docs/NOPE.md", broken["README.md"])
        self.assertIn("link: docs/ALSO_NOPE.md", broken["README.md"])

    def test_wrong_case_is_reported(self):
        broken = self.scan_text("see `docs/gdd.md` and [x](Docs/GDD.md)")
        self.assertIn("path: docs/gdd.md", broken["README.md"])
        self.assertIn("link: Docs/GDD.md", broken["README.md"])

    def test_links_resolve_from_their_own_file(self):
        # GitHub and VS Code resolve a link from the file holding it, so this is dead inside docs/sop/
        (self.root / "docs" / "sop" / "SOP-02.md").write_text("[gdd](docs/GDD.md) [ok](../GDD.md)\n", encoding="utf-8")
        (self.root / "README.md").write_text("", encoding="utf-8")
        broken = check_links.scan(self.root, [], [])
        self.assertEqual(broken, {"docs/sop/SOP-02.md": ["link: docs/GDD.md"]})

    def test_vendored_and_ignored_folders_are_skipped(self):
        for d in ("addons/gut", "Plugins/Vendor", "Library/PackageCache", "third_party"):
            (self.root / d).mkdir(parents=True)
            (self.root / d / "README.md").write_text("[x](docs/NOPE.md)\n", encoding="utf-8")
        (self.root / "tools").mkdir()
        (self.root / "tools" / "check_links.ignore").write_text("# vendored\nthird_party\n", encoding="utf-8")
        self.assertEqual(self.scan_text("fine"), {})

    def test_templates_urls_and_fences_ignored(self):
        text = ("`docs/adr/NNNN-title.md` [site](https://example.com/x.md) `tools/<script>.py` "
                "`CREDITS.md`\n```\ncat docs/missing.md `docs/missing.md`\n```\n")
        self.assertEqual(self.scan_text(text), {})

    def test_generated_folder_refs_skipped(self):
        # node_modules/ and build/ appear only after setup or a build: not checkable, not broken
        text = "`node_modules/phaser/skills/tilemaps/SKILL.md` and `build/debug/bin/game.exe` but `docs/NOPE.md`"
        broken = self.scan_text(text)
        self.assertEqual(broken, {"README.md": ["path: docs/NOPE.md"]})
        # a leading dot belongs to the folder name: ".godot/" is a generated folder, "./x" is just a prefix
        broken = self.scan_text("`.godot/imported/x.ctex` and `./build/x.exe` but `./docs/NOPE.md`")
        self.assertEqual(broken, {"README.md": ["path: ./docs/NOPE.md"]})


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)
