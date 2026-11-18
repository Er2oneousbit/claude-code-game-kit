#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_l10n.py
# Purpose : Exam for the localization round trip (tools/i18n/l10n.py): export (XLIFF and CSV, context, length
#           budgets, plural forms a language needs that English lacks), machine drafts from stand-in backends (a
#           command and an OpenAI-compatible server on 127.0.0.1; a draft that invents a placeholder is rejected),
#           review, import with every refusal (placeholders, length, changed English, unknown key, lost lines,
#           unfinished plural group, unreviewed draft, an XLIFF with a DOCTYPE), tables written in en.json's layout,
#           the pseudo-locale against data/golden/shell.json, and the font check (a hand-built TrueType cmap, a
#           Dotwork glyph file). In the kit it also rewrites every overlay's fr.json byte for byte and reads the
#           shell fonts' cmaps.
# Usage   : python tools/i18n/test_l10n.py      (in the kit: python core/tools/i18n/test_l10n.py)
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only, offline. Set L10N_LIVE_URL (an OpenAI-compatible server on this machine, e.g.
#           http://127.0.0.1:1234/v1) and optionally L10N_LIVE_MODEL to also draft three lines with a real model.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): the plural categories agree with the engines' CLDR
#           plural() in tools/golden_vectors.py, which now has a rule for every language (no helper-gap warning);
#           a data/i18n/ with only the word lists passes check
# ---------------------------------------------------------------------------
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import l10n  # noqa: E402
import l10n_exchange as ex  # noqa: E402
import l10n_fonts as fonts  # noqa: E402
import l10n_rules as rules  # noqa: E402
import l10n_tables as tables  # noqa: E402

KIT = HERE.parents[2]
GOLDEN_SHELL = HERE.parents[1] / "data" / "golden" / "shell.json"   # core/data/... in the kit, data/... in a game

EN = """{
 "language.name": "English",

 "menu.play": "Play",
 "menu.quit": "Quit",
 "greet": "Hello, {name}!",
 "score": "Score: %d%%",
 "size": "{w} × {h}",

 "hits.one": "{n} hit",
 "hits.other": "{n} hits"
}
"""
FR = """{
 "language.name": "Français",

 "menu.play": "Jouer",
 "only.fr": "gardé",

 "hits.one": "{n} coup",
 "hits.other": "{n} coups"
}
"""
CONTEXT = {"_comment": "skipped", "menu.play": {"note": "main menu button", "max": 8}, "greet": "a speech bubble"}
# what a careful translator returns for Russian (the stand-in translator's answers)
RU = {"language.name": "Русский", "menu.play": "Играть", "menu.quit": "Выход", "greet": "Привет, {name}!",
      "score": "Счёт: %d%%", "hits.one": "{n} удар", "hits.few": "{n} удара", "hits.many": "{n} ударов",
      "hits.other": "{n} удара"}
STAND_IN = r'''
import json, sys
req = json.loads(sys.stdin.read())
RU = %s
if req["target"] == "en":                                  # the back-translation of --back-check
    back = {v: k for k, v in RU.items()}
    print(json.dumps({"text": "Leave" if req["text"] == "Выход" else req["text"]}))
elif req["key"] == "greet":
    print(json.dumps({"text": "Привет, {имя}!"}))          # a model that translated the placeholder
else:
    print(json.dumps({"text": RU.get(req["key"], "?")}, ensure_ascii=False))
''' % json.dumps(RU, ensure_ascii=False)


def put(path, text, encoding="utf-8"):
    """Write text as given (Path.write_text translates newlines on Windows and has no newline= on Python 3.8)."""
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(text)


def get(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def make_ttf(chars):
    """A minimal TrueType file whose only table is a cmap: format 4 for the BMP characters, format 12 for all."""
    cps = sorted(ord(c) for c in chars)
    bmp = [c for c in cps if c < 0x10000]
    segs = [(c, c, (i + 1 - c) & 0xFFFF) for i, c in enumerate(bmp)] + [(0xFFFF, 0xFFFF, 1)]
    n = len(segs)
    f4 = struct.pack(">HHHHHHH", 4, 0, 0, 2 * n, 0, 0, 0)
    f4 += struct.pack(f">{n}H", *[e for s, e, d in segs]) + b"\0\0"
    f4 += struct.pack(f">{n}H", *[s for s, e, d in segs])
    f4 += struct.pack(f">{n}H", *[d for s, e, d in segs]) + struct.pack(f">{n}H", *[0] * n)
    f4 = f4[:2] + struct.pack(">H", len(f4)) + f4[4:]
    groups = [(c, c, i + 1) for i, c in enumerate(cps)] + [(0x41, 0x41, 0)]   # 'A' -> glyph 0: never counts
    f12 = struct.pack(">HHIII", 12, 0, 16 + 12 * len(groups), 0, len(groups))
    f12 += b"".join(struct.pack(">III", *g) for g in groups)
    cmap = struct.pack(">HH", 0, 2) + struct.pack(">HHI", 3, 1, 20) + struct.pack(">HHI", 3, 10, 20 + len(f4))
    cmap += f4 + f12
    head = struct.pack(">IHHHH", 0x00010000, 1, 16, 0, 0) + b"cmap" + struct.pack(">III", 0, 28, len(cmap))
    return head + cmap


class Live(object):
    """A stand-in OpenAI-compatible server on 127.0.0.1 (the reply carries a <think> block and quotes)."""

    def __init__(self, reply):
        outer = self
        self.requests = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj):
                body = json.dumps(obj).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._send({"data": [{"id": "embed-x"}, {"id": "stand-in-7b"}]})

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(req)
                self._send({"choices": [{"message": {"content": reply(req)}}]})

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class L10nExam(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="l10n_"))
        (self.tmp / "data" / "i18n").mkdir(parents=True)
        put(self.tmp / "data" / "i18n" / "en.json", EN)
        put(self.tmp / "data" / "i18n" / "fr.json", FR)
        (self.tmp / "l10n").mkdir()
        put(self.tmp / "l10n" / "context.json", json.dumps(CONTEXT))
        (self.tmp / "assets" / "fonts").mkdir(parents=True)
        latin = "".join(chr(c) for c in range(0x20, 0x7F)) + "çáéíóúñýÁÉÍÓÚÇÑÝ×"
        (self.tmp / "assets" / "fonts" / "ui.ttf").write_bytes(make_ttf(latin))
        self.stand_in = self.tmp / "stand_in.py"
        put(self.stand_in, STAND_IN)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = l10n.main([str(a) for a in args] + ["--project", str(self.tmp)])
        return rc, buf.getvalue()

    def units(self, locale="ru", ext=".xlf"):
        return {u.key: u for u in ex.read(self.tmp / "l10n" / f"{locale}{ext}")[0]}

    def draft_ru(self, *extra):
        self.assertEqual(self.cli("export", "ru")[0], 0)
        return self.cli("draft", "ru", "--backend", "command", "--command", sys.executable, self.stand_in, *extra)

    # ---- rules ---------------------------------------------------------------------------------------------
    def test_pseudo_matches_the_engines_golden_vectors(self):
        if not GOLDEN_SHELL.is_file():
            self.skipTest("no data/golden/shell.json")
        case = [c for c in json.loads(GOLDEN_SHELL.read_text(encoding="utf-8"))["cases"] if c["type"] == "pseudo"][0]
        for src, want in case["points"]:
            self.assertEqual(rules.pseudo(src), want, src)
        self.assertEqual(rules.pseudo_budget("Play"), 6)
        self.assertEqual(rules.visible_len("Hi {name}%d"), 3)

    def test_placeholders_and_plural_rules(self):
        self.assertIsNone(rules.placeholder_problem("{a} {b} %d", "%d {b} {a}"))
        self.assertEqual(rules.placeholder_problem("{n} hits", "{count} coups"), "placeholders: lost {n}, added {count}")
        self.assertIn("lost %d", rules.placeholder_problem("%d %d", "%d"))      # a multiset, not a set
        self.assertEqual(rules.categories("ru"), ("one", "few", "many", "other"))
        self.assertEqual(rules.categories("pt-BR"), ("one", "many", "other"))
        self.assertEqual(rules.required_categories("pt-BR"), ("one", "other"))
        self.assertEqual(rules.categories("ja"), ("other",))
        self.assertIsNone(rules.categories("xx"))
        self.assertEqual(rules.categories("fr"), ("one", "many", "other"))    # whole millions (CLDR 46)
        self.assertEqual(rules.categories("cs"), ("one", "few", "other"))     # many is for fractions only
        self.assertIsNone(rules.helper_gap("fr"))
        self.assertIsNone(rules.helper_gap("ru"))                         # the engines' plural() knows ru now
        self.assertEqual(rules.split_plural("hits.few@clean"), ("hits", "few"))
        self.assertEqual(rules.plural_groups({"hits.one": "a", "hits.one@clean": "b", "hits.other": "c"}),
                         {"hits": ["one", "other"]})

    def test_the_categories_agree_with_the_engines_plural(self):
        """The round trip asks translators for exactly the forms the engines' plural() can pick (#87 found ru few and
        many imported but never shown): same languages, same categories, in the reference and here."""
        ref = HERE.parent / "golden_vectors.py"
        if not ref.is_file():
            self.skipTest("the shell's reference is not in this project")
        sys.path.insert(0, str(ref.parent))
        import golden_vectors as gv
        self.assertEqual(set(rules.CATEGORIES), set(gv.PLURAL_FAMILY_OF))
        self.assertEqual(rules.HELPER_RULES, set(gv.PLURAL_FAMILY_OF))
        for lang in sorted(rules.CATEGORIES):
            reached = {gv.plural(lang, n) for n in list(range(0, 2001)) + [k * 1000000 for k in range(1, 11)]}
            self.assertEqual(set(rules.categories(lang)), reached | {"other"}, lang)
            self.assertEqual(rules.categories(lang), gv.plural_categories(lang), lang)
        self.assertEqual(rules.plural_groups(json.loads(EN)), {"hits": ["one", "other"]})

    def test_draft_problems_a_small_model_makes(self):
        # what a 1B model did in the first live run: echoed the string id, answered in JSON or a code block, and
        # added lines; each is rejected, a clean draft is not
        u = ex.Unit("settings.revert", "Revert")
        self.assertIn("the draft contains the string id", l10n.draft_problems(u, "settings.revert"))
        self.assertIn("the draft is markup, not a translation",
                      l10n.draft_problems(u, '{"settings.tab": "Назад"}'))
        self.assertIn("the draft is markup, not a translation", l10n.draft_problems(u, "```\nНазад\n```"))
        self.assertIn("the draft has line breaks the English does not have", l10n.draft_problems(u, "Назад\nОК"))
        self.assertEqual(l10n.draft_problems(u, "Вернуть"), [])
        import l10n_drafts as drafts
        self.assertEqual(drafts.clean("<think>a\nb</think>\n«Играть»"), "Играть")
        self.assertEqual(drafts.clean('Translation: "Jouer"'), "Jouer")

    # ---- tables written in en.json's layout ----------------------------------------------------------------
    def test_render_keeps_layout_and_extra_keys(self):
        en_text = EN
        table = json.loads(FR)
        self.assertEqual(tables.render(en_text, table, FR), FR)     # unchanged table: the same bytes
        table["menu.quit"] = "Quitter"
        out = tables.render(en_text, table, FR)
        self.assertIn(' "menu.play": "Jouer",\n "only.fr": "gardé",\n "menu.quit": "Quitter",', out)
        self.assertEqual(json.loads(out), table)
        crlf = FR.replace("\n", "\r\n")
        self.assertEqual(tables.render(en_text, json.loads(FR), crlf), crlf)
        # an en.json with two pairs on a line: written with json.dumps, still exactly the table
        odd = '{"a": "A", "b": "B",\n  "c": "C"}\n'
        out = tables.render(odd, {"a": "1", "c": "3"})
        self.assertEqual(json.loads(out), {"a": "1", "c": "3"})
        self.assertTrue(out.startswith('{\n  "a"'))

    def test_render_every_overlay_table_byte_for_byte(self):
        found = sorted((KIT / "engines").glob("*/skeleton/data/i18n/fr.json"))
        if not found:
            self.skipTest("not in the kit")
        for fr in found:
            en_text = get(fr.parent / "en.json")
            text = get(fr)
            self.assertEqual(tables.render(en_text, json.loads(text), text), text, fr)

    # ---- export --------------------------------------------------------------------------------------------
    def test_export_xliff_and_csv(self):
        rc, out = self.cli("export", "ru")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("no ru rule", out)                            # the engines' plural() picks few and many
        self.assertTrue((self.tmp / "l10n" / ".gdignore").is_file())
        u = self.units()
        self.assertEqual(list(u)[-4:], ["hits.one", "hits.other", "hits.few", "hits.many"])
        self.assertEqual(u["hits.few"].source, "{n} hits")
        self.assertIn("few (in Russian 2-4", u["hits.few"].note)
        self.assertEqual((u["menu.play"].note, u["menu.play"].max_len), ("main menu button", 8))
        self.assertEqual((u["size"].target, u["size"].state), ("{w} × {h}", "translated"))   # nothing to translate
        self.assertEqual(u["language.name"].target, "")      # "English" is on check_i18n's list, but not the same here
        self.assertEqual(u["menu.quit"].state, ex.STATE_EMPTY)
        text = get(self.tmp / "l10n" / "ru.xlf")
        self.assertIn('maxwidth="8" size-unit="char"', text)
        # French: the existing translations come along, translated; the CSV reads back the same
        rc, out = self.cli("export", "fr", "--format", "csv")
        self.assertEqual(rc, 0, out)
        raw = (self.tmp / "l10n" / "fr.csv").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))                # Excel reads the accents
        c = self.units("fr", ".csv")
        self.assertEqual((c["menu.play"].target, c["menu.play"].state), ("Jouer", "translated"))
        self.assertEqual(c["menu.quit"].target, "")
        units, meta = ex.read(self.tmp / "l10n" / "fr.csv")
        self.assertEqual((meta["target"], meta["record"][0]), ("fr", len(units)))

    def test_reexport_keeps_pending_drafts(self):
        self.draft_ru()
        self.assertTrue(self.units()["menu.quit"].is_draft())
        rc, out = self.cli("export", "ru")
        self.assertIn("drafts or reviews kept", out)
        self.assertEqual(self.units()["menu.quit"].target, "Выход")

    # ---- draft, review, import -----------------------------------------------------------------------------
    def test_round_trip(self):
        rc, out = self.draft_ru("--back-check")
        self.assertEqual(rc, 1, out)                                     # one draft rejected
        self.assertIn("[rejected] greet: placeholders: lost {name}, added {имя}", out)
        u = self.units()
        self.assertEqual(u["greet"].target, "")                          # never stored
        self.assertTrue(any("draft rejected" in n for n in u["greet"].tool_notes))
        self.assertTrue(u["menu.play"].is_draft() and u["menu.play"].qualifier == ex.DRAFT_QUALIFIER)
        self.assertTrue(any("back-translation differs" in n for n in u["menu.quit"].tool_notes))
        # drafts are not imported
        rc, out = self.cli("import", "ru")
        self.assertEqual(rc, 0, out)
        self.assertIn("not reviewed yet", out)
        self.assertFalse((self.tmp / "data" / "i18n" / "ru.json").exists())
        # review: a bad edit is refused, good ones and accepts go through
        rc, out = self.cli("review", "ru", "--set", "greet=Привет!")
        self.assertEqual(rc, 1, out)
        self.assertIn("lost {name}", out)
        rc, out = self.cli("review", "ru", "--list")
        self.assertIn("drafts to review", out)
        accept = []
        for k in ("language.name", "menu.play", "menu.quit", "score", "hits.one", "hits.few", "hits.many",
                  "hits.other"):
            accept += ["--accept", k]
        rc, out = self.cli("review", "ru", "--set", "greet=Привет, {name}!", *accept)
        self.assertEqual(rc, 0, out)
        rc, out = self.cli("import", "ru")
        self.assertEqual(rc, 0, out)
        ru = json.loads(get(self.tmp / "data" / "i18n" / "ru.json"))
        self.assertEqual(ru, dict(RU, size="{w} × {h}"))
        text = get(self.tmp / "data" / "i18n" / "ru.json")
        self.assertIn('"size": "{w} × {h}",\n\n "hits.one"', text)            # en.json's grouping
        self.assertLess(text.index('"hits.other"'), text.index('"hits.few"'))
        # the font check now sees Cyrillic the (Latin) font lacks; a glyph file with it passes
        rc, out = self.cli("check")
        self.assertEqual(rc, 1, out)
        self.assertIn("assets", out)
        self.assertIn("U+0418 'И' CYRILLIC CAPITAL LETTER I (menu.play)", out)
        glyphs = self.tmp / "cyr.txt"
        put(glyphs, "height 1\n" + "".join(f"char {c}\n#\n" for c in sorted(set("".join(RU.values()) + "".join(
            json.loads(EN).values()) + "".join(json.loads(FR).values()) + "".join(rules.pseudo(v) for v in
                                                                               json.loads(EN).values())))),
                          encoding="utf-8")
        rc, out = self.cli("check", "--font", glyphs)
        self.assertEqual(rc, 0, out)

    def test_import_refusals(self):
        self.cli("export", "ru")
        path = self.tmp / "l10n" / "ru.xlf"
        units, meta = ex.read(path)
        by = {u.key: u for u in units}
        good = {"language.name": "Русский", "menu.quit": "Выход", "hits.one": "{n} удар", "hits.other": "{n} удара"}
        for k, v in good.items():
            by[k].target, by[k].state = v, "translated"
        by["greet"].target, by["greet"].state = "Привет, {nom}!", "translated"            # placeholder changed
        by["menu.play"].target, by["menu.play"].state = "Начать игру", "translated"       # 11 > max 8
        by["score"].target, by["score"].state = "Счёт: %d%%", "translated"
        by["score"].source = "Points: %d%%"                                                # English changed since
        ex.write(path, units, meta)
        rc, out = self.cli("import", "ru")
        self.assertEqual(rc, 1, out)
        self.assertIn("greet: placeholders: lost {name}, added {nom}", out)
        self.assertIn("menu.play: 11 characters, the budget is 8", out)
        self.assertIn("score: the English changed since export", out)
        self.assertIn("hits: plural forms hits.few, hits.many missing", out)               # half a plural group
        ru = json.loads(get(self.tmp / "data" / "i18n" / "ru.json"))
        self.assertEqual(ru, {"language.name": "Русский", "menu.quit": "Выход", "size": "{w} × {h}"})
        # a key en.json no longer has; then a file that lost a line (record mismatch: nothing imported)
        units.append(ex.Unit("gone.key", "Old", "Старый", "translated"))
        ex.write(path, units, meta)
        rc, out = self.cli("import", "ru", "--dry-run")
        self.assertIn("gone.key: not a key of en.json", out)
        units, meta = ex.read(path)
        text = ex.to_xliff(units, meta)
        start = text.index('   <trans-unit id="menu.quit"')
        put(path, text[:start] + text[text.index("</trans-unit>", start) + 14:])
        rc, out = self.cli("import", "ru")
        self.assertEqual(rc, 1, out)
        self.assertIn("lines lost or added", out)
        self.assertIn("lost: menu.quit", out)
        # an XLIFF with a DOCTYPE (an entity bomb or an external entity) is refused before parsing
        put(path, '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><xliff/>')
        rc, out = self.cli("import", "ru")
        self.assertEqual(rc, 2, out)
        self.assertIn("DOCTYPE or ENTITY", out)

    def test_budget_and_reexport_keep_the_games_rules_and_the_translators_work(self):
        self.cli("export", "fr")
        path = self.tmp / "l10n" / "fr.xlf"
        units, meta = ex.read(path)
        by = {u.key: u for u in units}
        by["menu.play"].max_len = 999                                   # the file's budget edited
        by["menu.play"].target, by["menu.play"].state = "Commencer la partie", "translated"
        by["language.name"].target = "Français (France)"              # a reviewed fix, not imported yet
        ex.write(path, units, meta)
        rc, out = self.cli("import", "fr", "--dry-run")
        self.assertEqual(rc, 1, out)
        self.assertIn("menu.play: 19 characters, the budget is 8", out)   # context.json's 8 wins
        rc, out = self.cli("export", "fr")
        self.assertIn("2 drafts or reviews kept", out)
        self.assertEqual(self.units("fr")["language.name"].target, "Français (France)")
        # a CSV stays a CSV when exported again without --format
        os.remove(path)
        self.cli("export", "de", "--format", "csv")
        self.cli("export", "de")
        self.assertFalse((self.tmp / "l10n" / "de.xlf").exists())

    def test_no_scaffold_placeholder_in_the_tool(self):
        # new_game.py fails a scaffold on a doubled brace pair around a capital name (an f-string once made one)
        import re
        for f in sorted(HERE.glob("*.py")):
            self.assertIsNone(re.search(r"\{\{[A-Z_]+\}\}", get(f)), f.name)

    def test_import_keeps_target_only_keys_and_french_plurals(self):
        self.cli("export", "fr")
        path = self.tmp / "l10n" / "fr.xlf"
        units, meta = ex.read(path)
        for u in units:
            if u.key == "menu.quit":
                u.target, u.state = "Quitter", "signed-off"
        ex.write(path, units, meta)
        rc, out = self.cli("import", "fr")
        self.assertEqual(rc, 0, out)
        text = get(self.tmp / "data" / "i18n" / "fr.json")
        self.assertEqual(json.loads(text)["only.fr"], "gardé")
        self.assertEqual(text, FR.replace(' "only.fr": "gardé",\n',
                                          ' "only.fr": "gardé",\n "menu.quit": "Quitter",\n "size": "{w} × {h}",\n'))

    def test_openai_backend_against_a_stand_in_server(self):
        live = Live(lambda req: "<think>hmm</think>\n«Играть»" if "Play" in req["messages"][1]["content"]
                    else "Выход")
        try:
            self.cli("export", "ru")
            rc, out = self.cli("draft", "ru", "--backend", "openai", "--url", live.url, "--key", "menu.play",
                               "--key", "menu.quit")
            self.assertEqual(rc, 0, out)
            self.assertIn("with stand-in-7b", out)                      # the first listed model that is not an embedder
            u = self.units()
            self.assertEqual(u["menu.play"].target, "Играть")
            self.assertIn("Context: main menu button", live.requests[0]["messages"][1]["content"])
            self.assertIn("Maximum length: 8", live.requests[0]["messages"][1]["content"])
            self.assertIn("to Russian", live.requests[0]["messages"][0]["content"])
        finally:
            live.close()
        rc, out = self.cli("draft", "ru", "--backend", "openai", "--url", "https://api.example.com/v1")
        self.assertEqual(rc, 2, out)
        self.assertIn("not this machine", out)
        rc, out = self.cli("draft", "ru", "--backend", "openai", "--url", live.url)
        self.assertEqual(rc, 2, out)                                    # the server is gone
        self.assertIn("no model server answering", out)

    @unittest.skipUnless(os.environ.get("L10N_LIVE_URL"), "set L10N_LIVE_URL for a real local model")
    def test_live_model(self):
        self.cli("export", "fr")
        args = ["draft", "fr", "--backend", "openai", "--url", os.environ["L10N_LIVE_URL"], "--key", "menu.quit",
                "--key", "greet", "--key", "score", "--back-check"]
        if os.environ.get("L10N_LIVE_MODEL"):
            args += ["--model", os.environ["L10N_LIVE_MODEL"]]
        rc, out = self.cli(*args)
        print(out)
        self.assertIn(rc, (0, 1), out)                                  # 1: a draft rejected, which is the point
        for k in ("menu.quit", "greet", "score"):
            u = self.units("fr")[k]
            self.assertTrue(u.is_draft() or any("rejected" in n for n in u.tool_notes), k)
            if u.is_draft():
                self.assertIsNone(rules.placeholder_problem(u.source, u.target), k)

    # ---- check and the fonts -------------------------------------------------------------------------------
    def test_check(self):
        rc, out = self.cli("check")
        self.assertEqual(rc, 0, out)
        self.assertIn("with 1 fonts", out)
        # a table with a changed placeholder, half a plural group, and a budget the pseudo-locale overflows
        put(self.tmp / "data" / "i18n" / "ru.json", json.dumps(
            {"greet": "Привет, {nom}!", "hits.one": "{n} удар", "hits.other": "{n} удара"}, ensure_ascii=False),
            encoding="utf-8")
        ctx = dict(CONTEXT, **{"menu.quit": {"max": 5}})
        put(self.tmp / "l10n" / "context.json", json.dumps(ctx))
        rc, out = self.cli("check", "--locale", "ru", "--no-fonts")
        self.assertEqual(rc, 1, out)
        self.assertIn("ru greet: placeholders", out)
        self.assertIn("ru hits: plural forms hits.few, hits.many missing", out)
        self.assertIn("pseudo menu.quit: the budget 5 is below the pseudo-locale's 6", out)
        self.assertNotIn("no ru rule", out)
        self.assertEqual(self.cli("check", "--font", "nope.ttf")[0], 2)
        # a project with no tables at all passes (the tool ships into every game), and so does one that holds only
        # the clean-language word lists core ships (#207: RPG Maker MZ has data/i18n/mature/en.json and no en.json)
        shutil.rmtree(self.tmp / "data")
        self.assertEqual(self.cli("check")[0], 0)
        (self.tmp / "data" / "i18n" / "mature").mkdir(parents=True)
        put(self.tmp / "data" / "i18n" / "mature" / "en.json", '{"words": []}', encoding="utf-8")
        self.assertEqual(self.cli("check")[0], 0)
        self.assertEqual(self.cli("export", "ru")[0], 2)

    def test_font_readers(self):
        ttf = self.tmp / "t.ttf"
        ttf.write_bytes(make_ttf("AbПж\U0001F600"))
        have = fonts.font_chars(ttf)
        self.assertEqual(have, set("AbПж\U0001F600"))                   # format 4 + 12; glyph 0 never counts
        self.assertEqual(fonts.missing(have, "Пиво\n‍A­"), ["и", "в", "о", "­"])
        fnt = self.tmp / "f.fnt"
        put(fnt, "info face=x\nchar id=65 x=0\nchar id=1046 x=1\n")
        self.assertEqual(fonts.font_chars(fnt), {"A", "Ж"})
        bad = self.tmp / "bad.ttf"
        bad.write_bytes(b"not a font at all")
        with self.assertRaises(fonts.FontError):
            fonts.font_chars(bad)
        (self.tmp / "node_modules" / "x").mkdir(parents=True)
        (self.tmp / "node_modules" / "x" / "skip.ttf").write_bytes(make_ttf("A"))
        self.assertEqual([p.name for p in fonts.discover(self.tmp)], ["ui.ttf", "bad.ttf", "t.ttf"])   # assets/ first; no .fnt

    def test_kit_shell_fonts(self):
        atk = sorted((KIT / "engines").glob("*/skeleton/**/AtkinsonHyperlegible-Regular.ttf"))
        if not atk:
            self.skipTest("not in the kit")
        have = fonts.font_chars(atk[0])
        self.assertEqual(len(have), 342)                                # what fontTools' getBestCmap lists
        self.assertEqual(fonts.missing(have, "Démarrer, « Oui » – 50 €"), [])
        self.assertEqual(fonts.missing(have, "Играть"), list("Играть"))   # no Cyrillic in the shell font

    def test_cli(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as e:
                l10n.main(["-h"])
        self.assertEqual(e.exception.code, 0)
        for cmd in ("export", "draft", "review", "import", "check"):
            self.assertIn(cmd, buf.getvalue())
        rc, out = self.cli("--debug", "check")                         # a global option before the command
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.cli("export", "en")[0], 2)
        self.assertEqual(self.cli("export", "pseudo")[0], 2)
        self.assertEqual(self.cli("review", "de")[0], 2)                # no file exported yet


if __name__ == "__main__":
    unittest.main()
