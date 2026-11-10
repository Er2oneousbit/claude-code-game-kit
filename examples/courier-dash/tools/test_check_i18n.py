#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_check_i18n.py
# Purpose : Exam for tools/check_i18n.py: a missing key, an English text left in place and a changed placeholder are
#           problems; placeholder-only values, the listed names and units, --same texts, plural keys and the pseudo
#           table are not; a broken table is a usage problem (exit 2). In the kit (engines/ next to core/), also
#           checks that every engine overlay's own French table is complete (#270, #272).
# Usage   : python tools/test_check_i18n.py      (in the kit: python core/tools/test_check_i18n.py)
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only. The kit part is skipped in a game (no engines/ folder).
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
import check_i18n  # noqa: E402

KIT_ENGINES = Path(__file__).resolve().parents[2] / "engines"
# The overlays whose French table must be complete (#270, #272). Every overlay that ships a fr.json must be listed,
# so a new overlay ships a complete table too (its English fallback is tested on a partial table of the test's own).
COMPLETE = ("love2d", "unity", "unreal", "bevy", "godot", "web")


class CheckI18n(unittest.TestCase):
    def tables(self, **locales):
        folder = Path(tempfile.mkdtemp())
        for loc, table in locales.items():
            (folder / f"{loc}.json").write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
        return folder

    def cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = check_i18n.main(list(args))
        return rc, buf.getvalue()

    EN = {"menu.play": "Play", "apples.one": "{n} apple", "apples.other": "{n} apples", "title.name": "{name}",
          "value.times": "{n}x", "opt.glyphs.xbox": "Xbox", "game.title": "Courier Dash"}
    FR = {"menu.play": "Jouer", "apples.one": "{n} pomme", "apples.other": "{n} pommes", "title.name": "{name}",
          "value.times": "{n}x", "opt.glyphs.xbox": "Xbox", "game.title": "Courier Dash"}

    def test_a_complete_table_passes(self):
        folder = self.tables(en=self.EN, fr=self.FR, pseudo={"menu.play": "[Pláy]"})
        rc, text = self.cli("--dir", str(folder))
        self.assertEqual(rc, 0, text)
        self.assertIn("fr.json: every English key translated", text)
        self.assertNotIn("pseudo", text, "the pseudo table is generated, never checked")

    def test_missing_untranslated_and_placeholders_are_problems(self):
        fr = dict(self.FR, **{"menu.play": "Play", "apples.one": "{count} pomme"})
        del fr["apples.other"]                       # a plural form missing is a missing key
        problems = check_i18n.check_dir(self.tables(en=self.EN, fr=fr))["fr"]
        self.assertEqual(len(problems), 3, problems)
        self.assertTrue(any(p.startswith("menu.play: still English") for p in problems))
        self.assertTrue(any(p.startswith("apples.one: placeholders") for p in problems))
        self.assertTrue(any(p.startswith("apples.other: missing") for p in problems))
        rc, text = self.cli("--dir", str(self.tables(en=self.EN, fr=fr)))
        self.assertEqual(rc, 1, text)
        self.assertIn("[FAIL] fr.json: 3 problem(s)", text)

    def test_same_lets_a_game_keep_its_own_names(self):
        en = dict(self.EN, **{"npc.name": "Íris “Nø”"})
        fr = dict(self.FR, **{"npc.name": "Íris “Nø”"})
        folder = self.tables(en=en, fr=fr)
        self.assertEqual(self.cli("--dir", str(folder))[0], 1)
        self.assertEqual(self.cli("--dir", str(folder), "--same", "Íris “Nø”")[0], 0)

    def test_locale_picks_one_table_and_extra_keys_are_fine(self):
        fr = dict(self.FR, **{"binding.key.space": "Espace"})   # looked up with a fallback, English lacks it
        folder = self.tables(en=self.EN, fr=fr, de={"menu.play": "Spielen"})
        rc, text = self.cli("--dir", str(folder), "--locale", "fr")
        self.assertEqual(rc, 0, text)
        self.assertNotIn("de.json", text)

    def test_broken_tables_are_usage_problems(self):
        folder = self.tables(fr=self.FR)
        self.assertEqual(self.cli("--dir", str(folder))[0], 2, "no en.json")
        folder = self.tables(en=self.EN, fr={"menu.play": ["Jouer"]})
        rc, text = self.cli("--dir", str(folder))
        self.assertEqual(rc, 2)
        self.assertIn("not a JSON object of strings", text)
        self.assertEqual(self.cli("--dir", str(self.tables(en=self.EN)), "--locale", "fr")[0], 2, "no fr.json")
        (folder / "fr.json").write_text("{nope", encoding="utf-8")
        self.assertEqual(self.cli("--dir", str(folder))[0], 2)

    def test_english_only_is_fine(self):
        rc, text = self.cli("--dir", str(self.tables(en=self.EN)))
        self.assertEqual(rc, 0, text)
        self.assertIn("English only", text)

    def test_a_project_without_string_tables_passes_the_plain_run(self):
        # web-3d and RPG Maker MZ ship no data/i18n/, and the tool is in every game: the plain run must not exit 2
        # there; a --dir that does not exist is still a usage problem
        missing = Path(tempfile.mkdtemp()) / "data" / "i18n"
        saved = check_i18n.ROOT
        try:
            check_i18n.ROOT = missing.parents[1]
            rc, text = self.cli()
        finally:
            check_i18n.ROOT = saved
        self.assertEqual(rc, 0, text)
        self.assertIn("no string tables", text)
        self.assertEqual(self.cli("--dir", str(missing))[0], 2, "a --dir that does not exist")


@unittest.skipUnless(KIT_ENGINES.is_dir(), "in a game: the kit's engine tables are not here")
class KitEngineTables(unittest.TestCase):
    """The overlays' French tables (#270, #272): every overlay that ships one has it complete."""

    def test_complete_overlays_translate_every_english_key(self):
        for engine in COMPLETE:
            with self.subTest(engine=engine):
                folder = KIT_ENGINES / engine / "skeleton" / "data" / "i18n"
                problems = check_i18n.check_dir(folder, ["fr"])["fr"]
                self.assertEqual(problems, [], f"{engine} fr.json:\n  " + "\n  ".join(problems))

    def test_every_overlay_with_a_french_table_is_listed(self):
        shipped = {p.parents[3].name for p in KIT_ENGINES.glob("*/skeleton/data/i18n/fr.json")}
        self.assertEqual(shipped, set(COMPLETE))


if __name__ == "__main__":
    unittest.main(verbosity=2)
