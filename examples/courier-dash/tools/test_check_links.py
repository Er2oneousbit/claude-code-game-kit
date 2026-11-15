#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_check_links.py
# Purpose : Exam for check_links.py: a good reference passes, a broken one is
#           caught, template names and URLs are ignored.
# Usage   : python tools/test_check_links.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): --baseline write, compare, new, fixed, missing (#299)
# Updated : 2026-11-14 with Claude (Opus 5.5, claude-opus-5-5): --baseline counts repeated hits; a BOM is ignored
# Updated : 2026-11-14 with Claude (Opus 5.5, claude-opus-5-5): the crafted-file case checks how the scan time grows
#           (n against 4n), not a 5 s wall clock that coverage and load tipped over (#282)
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


class CheckLinksReviewFixes(CheckLinksExam):
    """#247: a markdown file that is not UTF-8 was skipped; an indented fence was read as prose; "[Bug]: crash" was
    a reference definition."""

    def test_a_cp1252_file_is_checked(self):
        (self.root / "README.md").write_bytes("caf\u00e9 [x](docs/NOPE.md)\n".encode("cp1252"))
        self.assertIn("link: docs/NOPE.md", check_links.scan(self.root, [], []).get("README.md", []))

    def test_an_indented_fence_holds_examples(self):
        text = "- step one:\n\n   ```\n   [x](docs/NOPE.md) `docs/NOPE2.md`\n   ```\n"
        self.assertEqual(self.scan_text(text), {})

    def test_a_bracketed_label_in_prose_is_not_a_definition(self):
        self.assertEqual(self.scan_text("[Bug]: crash on load\n"), {})
        self.assertIn("link: docs/ALSO_NOPE.md", self.scan_text("[ref]: docs/ALSO_NOPE.md \"t\"\n")["README.md"])


class CheckLinksKimiFixes(unittest.TestCase):
    """#258: a dangling symlink counted as an existing file."""

    def test_a_dangling_symlink_is_not_a_file(self):
        import os
        root = Path(tempfile.mkdtemp())
        try:
            os.symlink(str(root / "gone.md"), str(root / "GDD.md"))
        except (OSError, NotImplementedError):
            self.skipTest("cannot make a symlink here")
        self.assertFalse(check_links.exact_exists(root, "GDD.md"))
        (root / "gone.md").write_text("x", encoding="utf-8")
        self.assertTrue(check_links.exact_exists(root, "GDD.md"))


class CheckLinksSecondModelFixes(CheckLinksExam):
    """#261: a crafted file hung the link regexes (quadratic in the file size); a path written with backslashes
    passed on Windows and failed on Linux and GitHub."""

    def test_a_crafted_file_is_scanned_in_bounded_time(self):
        # Unclosed "[a](" with no ")" or space: the destination class ate the rest of the file and backtracked once
        # per link (a minute at 80 KB, hours at 1 MB); the same for a "[" label that ran across lines. What matters is
        # how the time grows, not a wall-clock number: the bounded regexes take about 2.7 s for 20000 "[a](" on one
        # machine and 5.1 s under coverage, linear either way. So each text is scanned at n and at 4n, the two runs
        # taken in turn three times (a busy moment slows both sizes, not one) and the best of each kept, and the
        # ratio must stay under GROWTH_LIMIT: linear measured 3.7 to 4.6 at these sizes, quadratic is about 16; 10
        # leaves room on both sides. Sizes keep the small run at 25 ms or more, where timer noise is small.
        import time
        GROWTH_LIMIT = 10.0

        def scan(text):
            started = time.perf_counter()
            list(check_links.references(text))
            return time.perf_counter() - started

        for unit, n in (("[a](", 2500), ("[x\n", 120000)):
            small_text, big_text = unit * n, unit * (4 * n)
            small, big = [], []
            for _ in range(3):
                small.append(scan(small_text))
                big.append(scan(big_text))
            ratio = min(big) / max(min(small), 1e-4)
            self.assertLess(ratio, GROWTH_LIMIT,
                            "the regexes are quadratic again: %r x%d took %.3f s, x%d %.3f s (x%.1f)"
                            % (unit, n, min(small), 4 * n, min(big), ratio))

    def test_a_link_text_wrapped_over_two_lines_is_still_checked(self):
        self.assertIn("link: docs/NOPE.md", self.scan_text("see [the design\ndocument](docs/NOPE.md) first")["README.md"])

    def test_a_backslash_path_is_broken_everywhere(self):
        # GitHub and Linux read "docs\GDD.md" as one file name, so it is broken there whatever Windows thinks
        broken = self.scan_text("see `docs\\GDD.md` and [x](docs\\GDD.md)")
        self.assertEqual(sorted(broken.get("README.md", [])), ["link: docs\\GDD.md", "path: docs\\GDD.md"])


class CheckLinksBaseline(unittest.TestCase):
    """#299: --baseline FILE tells a new break from the known ones (a template tree's scaffold-time paths)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.root.mkdir()
        (self.root / "README.md").write_text("[a](docs/OLD.md) `docs/GONE.md`\n", encoding="utf-8")
        self.baseline = Path(self.tmp.name) / "known.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *extra):
        import contextlib
        import io
        out = io.StringIO()
        argv = sys.argv
        sys.argv = ["check_links.py", "--root", str(self.root), "--baseline", str(self.baseline), *extra]
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                rc = check_links.main()
        finally:
            sys.argv = argv
        return rc, out.getvalue()

    def test_write_then_compare_passes(self):
        rc, out = self.run_main("--write-baseline")
        self.assertEqual(rc, 0, out)
        lines = [l for l in self.baseline.read_text(encoding="utf-8").splitlines() if not l.startswith("#")]
        self.assertEqual(lines, ["README.md: link: docs/OLD.md", "README.md: path: docs/GONE.md"])   # sorted
        self.assertNotIn(b"\r\n", self.baseline.read_bytes())
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out)
        self.assertIn("none new", out)

    def test_a_new_break_fails_and_only_it_is_listed(self):
        self.run_main("--write-baseline")
        (self.root / "NEW.md").write_text("[b](docs/NOPE.md)\n", encoding="utf-8")
        rc, out = self.run_main()
        self.assertEqual(rc, 1, out)
        self.assertIn("[FAIL] NEW.md: link: docs/NOPE.md", out)
        self.assertNotIn("[FAIL] README.md", out)          # the known ones stay quiet

    def test_a_fixed_hit_is_info_not_a_failure(self):
        self.run_main("--write-baseline")
        (self.root / "README.md").write_text("[a](docs/OLD.md)\n", encoding="utf-8")
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out)
        self.assertIn("[info] fixed since the baseline: README.md: path: docs/GONE.md", out)

    def test_a_second_copy_of_a_known_hit_is_new(self):
        """The same broken target twice in one file is two lines: a set compare hid the second copy (a new break in
        a file that already had one) and counted a hit as known that the baseline never listed."""
        self.baseline.write_text("# header only\n", encoding="utf-8")
        (self.root / "README.md").write_text("[a](docs/X.md) and [b](docs/X.md)\n", encoding="utf-8")
        rc, out = self.run_main()
        self.assertEqual(rc, 1, out)
        self.assertIn("2 broken reference(s), 0 known in known.txt, 2 new", out)
        self.run_main("--write-baseline")
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out)
        (self.root / "README.md").write_text("[a](docs/X.md) [b](docs/X.md) [c](docs/X.md)\n", encoding="utf-8")
        rc, out = self.run_main()
        self.assertEqual(rc, 1, out)                       # a third link to the same missing file is a new break
        self.assertIn("3 broken reference(s), 2 known in known.txt, 1 new", out)

    def test_a_baseline_saved_with_a_byte_order_mark_reads_the_same(self):
        self.run_main("--write-baseline")
        self.baseline.write_bytes(b"\xef\xbb\xbf" +self.baseline.read_bytes())   # Notepad's "UTF-8 with BOM"
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("fixed since the baseline", out)

    def test_a_missing_baseline_is_a_usage_problem(self):
        rc, out = self.run_main()
        self.assertEqual(rc, 2, out)
        self.assertIn("--write-baseline", out)

    def test_write_baseline_needs_a_file(self):
        argv = sys.argv
        sys.argv = ["check_links.py", "--root", str(self.root), "--write-baseline"]
        try:
            import contextlib
            import io
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(check_links.main(), 2)
        finally:
            sys.argv = argv


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)
