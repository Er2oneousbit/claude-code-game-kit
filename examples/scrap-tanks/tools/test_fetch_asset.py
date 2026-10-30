#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_fetch_asset.py
# Purpose : Exam for fetch_asset.py, offline: a local zip served by file:// URL is
#           listed, picked files are copied, license evidence and the ASSET_LOG row
#           are written; NC licenses, overwrites and zip path escapes are refused.
#           Security regressions: ".." / absolute / drive entries refuse the pack, --to and
#           --license-file stay inside the project and the pack, URL credentials and query
#           strings are not recorded (--page keeps its query, loses its login), names Windows cannot
#           store and case-only duplicates are refused.
# Usage   : python tools/test_fetch_asset.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_asset  # noqa: E402

LOG = """# Asset Log

| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) | AI-assisted? | Modified? | Date added | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | | | | | | | no | no | 2026-01-01 | |

## Rules
"""


class FetchAssetExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "game"
        (self.root / "docs").mkdir(parents=True)
        (self.root / "docs" / "ASSET_LOG.md").write_text(LOG, encoding="utf-8")
        self.zip = base / "pack.zip"
        with zipfile.ZipFile(self.zip, "w") as zf:
            zf.writestr("License.txt", "License: (Creative Commons Zero, CC0)\n")
            zf.writestr("Tiles/tile_0001.png", b"\x89PNG fake")
            zf.writestr("Tiles/tile_0002.png", b"\x89PNG fake")
            zf.writestr("Audio/jump.ogg", b"OggS fake")
            zf.writestr("Models/GLB format/crate.glb", b"glTF fake")
            zf.writestr("Models/GLB format/Textures/colormap.png", b"PNG fake")
        self.url = self.zip.as_uri()

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = fetch_asset.main(["--url", self.url, "--root", str(self.root), *extra])
        return rc, out.getvalue() + err.getvalue()

    def good(self, *extra):
        return self.fetch("--page", "https://example.org/pack", "--author", "Kenney", "--license", "CC0",
                          "--type", "tileset", "--to", "assets/art", *extra)

    def log(self):
        return (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8")

    def test_list_shows_pack_files(self):
        rc, out = self.fetch("--list")
        self.assertEqual(rc, 0, out)
        self.assertIn("Tiles/tile_0001.png", out)

    def test_take_glob_copies_logs_and_saves_evidence(self):
        rc, out = self.good("--take", "Tiles/*.png")
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "assets/art/tile_0001.png").is_file())
        self.assertTrue((self.root / "assets/art/tile_0002.png").is_file())
        log = self.log()
        self.assertIn("| A-0001 | tileset | `assets/art/tile_0001.png`, `assets/art/tile_0002.png` | https://example.org/pack | Kenney | CC0 |", log)
        self.assertEqual(log.count("| A-0001 |"), 1, "template row must be filled, not duplicated")
        evidence = (self.root / "docs/licenses/A-0001.txt").read_text(encoding="utf-8")
        self.assertIn("Creative Commons Zero", evidence)
        self.assertIn("SHA-256", evidence)

    def test_second_fetch_gets_next_id_after_last_row(self):
        self.good("--take", "Tiles/tile_0001.png")
        rc, out = self.fetch("--page", "p", "--author", "Kenney", "--license", "CC0", "--type", "sfx",
                             "--to", "assets/audio", "--take", "Audio/jump.ogg")
        self.assertEqual(rc, 0, out)
        log = self.log()
        self.assertIn("| A-0002 | sfx | `assets/audio/jump.ogg`", log)
        self.assertLess(log.index("A-0001"), log.index("A-0002"))
        self.assertLess(log.index("A-0002"), log.index("## Rules"))

    def test_nc_license_refused_unless_placeholder(self):
        rc, out = self.fetch("--license", "CC BY-NC 4.0", "--to", "assets/art", "--take", "Tiles/tile_0001.png")
        self.assertEqual(rc, 1)
        self.assertIn("NC/ND", out)
        rc, out = self.fetch("--license", "CC BY-NC 4.0", "--to", "assets/art", "--take", "Tiles/tile_0001.png", "--placeholder")
        self.assertEqual(rc, 0, out)
        self.assertIn("PLACEHOLDER", self.log())

    def test_weak_copyleft_plugin_license_accepted(self):
        rc, out = self.fetch("--page", "p", "--author", "Dev", "--license", "EUPL-1.2", "--type", "plugin",
                             "--to", "addons/x", "--take", "Tiles/tile_0001.png")
        self.assertEqual(rc, 0, out)
        self.assertIn("| plugin |", self.log())

    def test_base_keeps_relative_paths(self):
        rc, out = self.fetch("--page", "p", "--author", "Kenney", "--license", "CC0", "--type", "3d", "--to", "public/m",
                             "--base", "Models/GLB format", "--take", "Models/GLB format/*.glb",
                             "--take", "Models/GLB format/Textures/*.png")
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "public/m/crate.glb").is_file())
        self.assertTrue((self.root / "public/m/Textures/colormap.png").is_file(), "texture keeps its sub-folder")

    def test_take_outside_base_fails(self):
        rc, out = self.good("--base", "Models/GLB format", "--take", "Audio/jump.ogg")
        self.assertEqual(rc, 1)
        self.assertIn("not inside --base", out)

    def test_existing_file_not_overwritten(self):
        self.good("--take", "Tiles/tile_0001.png")
        rc, out = self.good("--take", "Tiles/tile_0001.png")
        self.assertEqual(rc, 1)
        self.assertIn("not overwriting", out)

    def test_take_that_matches_nothing_fails(self):
        rc, out = self.good("--take", "Nope/*.png")
        self.assertEqual(rc, 1)
        self.assertIn("matches nothing", out)

    def test_missing_required_args_is_usage_error(self):
        rc, _ = self.fetch("--take", "Tiles/tile_0001.png")
        self.assertEqual(rc, 2)

    def test_dry_run_changes_nothing(self):
        before = self.log()
        rc, out = self.good("--take", "Tiles/tile_0001.png", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.log(), before)
        self.assertFalse((self.root / "assets").exists())

    # Regressions from the 2026-10-22 sanity audit
    def test_license_words_not_substrings(self):
        for text in ("Not permitted to redistribute", "Custom limited license", "Simple custom license"):
            with self.assertRaises(fetch_asset.FetchError, msg=text):
                fetch_asset.judge_license(text, False)
        for text in ("CC0", "CC-BY 4.0", "CC BY 4.0", "MIT", "MPL-2.0", "SIL Open Font License 1.1"):
            self.assertEqual(fetch_asset.judge_license(text, False), "ok", text)

    def test_single_file_keeps_its_name(self):
        single = Path(self.tmp.name) / "jump.ogg"
        single.write_bytes(b"OggS fake")
        self.url = single.as_uri()
        rc, out = self.good("--take", "jump.ogg")
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "assets/art/jump.ogg").is_file())

    def test_same_file_name_different_url_not_shared(self):
        other = Path(self.tmp.name) / "other" / "pack.zip"
        other.parent.mkdir()
        with zipfile.ZipFile(other, "w") as zf:
            zf.writestr("only_in_other.txt", "x")
        self.fetch("--list")
        self.url = other.as_uri()
        rc, out = self.fetch("--list")
        self.assertEqual(rc, 0, out)
        self.assertIn("only_in_other.txt", out)

    def test_log_without_rows_gets_its_first_row(self):
        path = self.root / "docs" / "ASSET_LOG.md"
        path.write_text(LOG.replace("| A-0001 | | | | | | | no | no | 2026-01-01 | |\n", ""), encoding="utf-8")
        rc, out = self.good("--take", "Tiles/tile_0001.png")
        self.assertEqual(rc, 0, out)
        self.assertIn("| A-0001 | tileset |", self.log())

    # Regressions from Kimi's audit of the kit tools (2026-10-22)
    def test_wrong_root_is_usage_error_before_downloading(self):
        empty = Path(self.tmp.name) / "not_a_project"
        empty.mkdir()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = fetch_asset.main(["--url", self.url, "--root", str(empty), "--page", "p", "--author", "Kenney",
                                   "--license", "CC0", "--type", "tileset", "--to", "assets/art",
                                   "--take", "Tiles/tile_0001.png"])
        self.assertEqual(rc, 2, out.getvalue())
        self.assertIn("ASSET_LOG.md not found", out.getvalue())
        self.assertFalse((empty / fetch_asset.CACHE_DIR).exists(), "nothing downloaded for a wrong --root")

    def test_log_without_table_is_usage_error(self):
        (self.root / "docs" / "ASSET_LOG.md").write_text("# Asset Log\n\nno table here\n", encoding="utf-8")
        rc, out = self.good("--take", "Tiles/tile_0001.png")
        self.assertEqual(rc, 2, out)
        self.assertIn("no table", out)

    def test_zip_path_escape_refused(self):
        evil = Path(self.tmp.name) / "evil.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("../../escaped.txt", "x")
        self.url = evil.as_uri()
        rc, out = self.fetch("--list")
        self.assertEqual(rc, 2)
        self.assertIn("unsafe path", out)
        self.assertFalse((Path(self.tmp.name) / "escaped.txt").exists())

    # Regressions from the 2026-10-30 security pass
    def evil_pack(self, entries):
        evil = Path(self.tmp.name) / "evil.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            for name, data in entries:
                zf.writestr(name, data)
        self.url = evil.as_uri()

    def test_dotdot_inside_base_cannot_plant_project_files(self):
        # zipfile drops the ".." on extract (source = the root-level file) while --base kept it (dest = project root)
        self.evil_pack([("License.txt", "CC0"), ("Models/GLB format/crate.glb", b"glb"),
                        (".claude/settings.local.json", b'{"hooks": "PWNED"}'),
                        ("Models/GLB format/../../.claude/settings.local.json", b"x")])
        rc, out = self.good("--take", "Models/GLB format/*", "--base", "Models/GLB format", "--to", "assets/models")
        self.assertEqual(rc, 2, out)
        self.assertIn("unsafe path", out)
        self.assertFalse((self.root / ".claude").exists(), "nothing planted in the project")
        self.assertFalse((self.root / "assets").exists())
        self.assertNotIn("A-0001 | tileset", self.log())

    def test_absolute_drive_and_backslash_entries_refused(self):
        for name in ("/etc/x.txt", "C:/Windows/x.txt", "c:x.txt", "\\x.txt", "a\\..\\..\\x.txt"):
            self.evil_pack([(name, b"x")])
            rc, out = self.fetch("--list")
            self.assertEqual(rc, 2, f"{name}: {out}")
            self.assertIn("unsafe path", out, name)

    def test_to_outside_project_is_usage_error(self):
        for to in ("../outside", str(Path(self.tmp.name) / "elsewhere"), "assets/../..", "."):
            rc, out = self.fetch("--page", "p", "--author", "K", "--license", "CC0", "--to", to,
                                 "--take", "Tiles/tile_0001.png")
            self.assertEqual(rc, 2, f"{to}: {out}")
            self.assertIn("not a folder inside the project", out, to)
        self.assertFalse((Path(self.tmp.name) / "outside").exists())
        self.assertFalse((Path(self.tmp.name) / "elsewhere").exists())

    def test_license_file_must_be_a_pack_entry(self):
        local = Path(self.tmp.name) / "local_secret.txt"
        local.write_text("CC0 but really a local file", encoding="utf-8")
        for name in (str(local), "../../local_secret.txt"):
            rc, out = self.good("--take", "Tiles/tile_0001.png", "--license-file", name)
            self.assertEqual(rc, 2, out)
            self.assertIn("is not in the pack", out)
        self.assertFalse((self.root / "docs/licenses").exists())
        rc, out = self.good("--take", "Tiles/tile_0001.png", "--license-file", "License.txt")
        self.assertEqual(rc, 0, out)
        self.assertIn("Creative Commons Zero", (self.root / "docs/licenses/A-0001.txt").read_text(encoding="utf-8"))

    def test_url_credentials_and_query_not_recorded(self):
        real = fetch_asset.download
        fetch_asset.download = lambda url, cache: real(self.zip.as_uri(), cache)   # stand-in host, offline
        try:
            self.url = "https://user:hunter2@cdn.example/dl/pack.zip?X-Amz-Signature=SECRETSIG#frag"
            rc, out = self.fetch("--author", "K", "--license", "CC0", "--to", "assets/art",
                                 "--take", "Tiles/tile_0001.png")   # no --page: the URL goes into the row
        finally:
            fetch_asset.download = real
        self.assertEqual(rc, 0, out)
        evidence = (self.root / "docs/licenses/A-0001.txt").read_text(encoding="utf-8")
        for text in (evidence, self.log(), out):
            for secret in ("hunter2", "user:", "SECRETSIG", "X-Amz", "frag"):
                self.assertNotIn(secret, text)
        self.assertIn("Download : https://cdn.example/dl/pack.zip\n", evidence)
        self.assertIn("| https://cdn.example/dl/pack.zip |", self.log())

    def test_page_recorded_without_login_but_with_query(self):
        page = "https://me:hunter2@store.example/asset?id=42&lang=en#license"
        rc, out = self.fetch("--page", page, "--author", "K", "--license", "CC0", "--to", "assets/art",
                             "--take", "Tiles/tile_0001.png")
        self.assertEqual(rc, 0, out)
        evidence = (self.root / "docs/licenses/A-0001.txt").read_text(encoding="utf-8")
        for text in (evidence, self.log(), out):
            self.assertNotIn("hunter2", text)
            self.assertNotIn("me:", text)
        self.assertIn("Page     : https://store.example/asset?id=42&lang=en#license\n", evidence)
        self.assertIn("| https://store.example/asset?id=42&lang=en#license |", self.log())
        self.assertEqual(fetch_asset.redact_page("the itch.io page, see notes"), "the itch.io page, see notes")

    def test_names_windows_cannot_store_refused(self):
        self.evil_pack([("License.txt", "CC0"), ("evil|x.png", b"x"), ("a\nb.png", b"x"), ("ads.png:stream", b"x")])
        for name in ("evil|x.png", "a\nb.png", "ads.png:stream"):
            rc, out = self.good("--take", name)
            self.assertEqual(rc, 1, out)
            self.assertIn("Windows cannot store", out)
        self.assertNotIn("evil", self.log())
        self.assertFalse((self.root / "assets").exists())

    def test_row_cells_escaped(self):
        rc, out = self.good("--take", "Tiles/tile_0001.png", "--notes", "a | b")
        self.assertEqual(rc, 0, out)
        row = next(l for l in self.log().splitlines() if l.startswith("| A-0001"))
        self.assertEqual(row.replace("\\|", "").count("|"), 12, row)
        self.assertEqual(fetch_asset.md_cell("x|y\nz"), "x\\|y z")

    def test_case_folded_duplicate_destinations_refused(self):
        self.evil_pack([("License.txt", "CC0"), ("Tiles/A.png", b"FIRST"), ("tiles2/a.png", b"SECOND")])
        rc, out = self.good("--take", "Tiles/A.png", "--take", "tiles2/a.png")
        self.assertEqual(rc, 1, out)
        self.assertIn("share a name (ignoring case)", out)
        self.assertFalse((self.root / "assets").exists(), "refused before copying")


if __name__ == "__main__":
    unittest.main(verbosity=1)
