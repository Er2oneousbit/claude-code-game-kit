#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_fonts.py
# Purpose : exam for the Latin glyph fonts and the font coverage check: every glyph fits its font's height and sits
#           on the baseline, the Latin fonts keep the ASCII glyphs unchanged and cover Latin-1 Supplement + Latin
#           Extended-A, accented glyphs differ from their base letters (and contain them), fontcheck finds a planted
#           missing glyph and passes a clean string set (JSON, CSV, PO, text; the CLI and the pack's "check"), and
#           the old fonts build exactly as before (golden hashes) in the same pack as the new ones.
# Usage   : python -I -B tools/art/dotwork/tests/test_fonts.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unicodedata
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DOTWORK = os.path.dirname(HERE)
sys.path.insert(0, DOTWORK)   # -I drops the script folder
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

GLYPHS = os.path.join(DOTWORK, "glyphs")
LATIN1 = [chr(c) for c in range(0xA0, 0x100)]
EXT_A = [chr(c) for c in range(0x100, 0x180)]
PUNCT = "‘’‚“”„–…€‹›"   # curly quotes, en dash, ... euro
TITLE_PUNCT = "¡¿«»‹›„‚“”‘’–…ªº·;\"()/"
PAIRS = (("dialogue_latin.txt", "dialogue.txt"), ("title_brass_latin.txt", "title_brass.txt"))
# carons drawn as an apostrophe beside the letter (Slovak / Czech custom), so the mark is not above it
APOSTROPHE_CARONS = "ďĽľť"
COMMA_ABOVE = "ģ"   # g with cedilla: the g's descender leaves no room, so the comma turns and goes above
# one sentence per language with its accented letters, then its accented capitals
PANGRAMS = {
    "fr": "« Dès Noël, où un zéphyr haï me vêt de glaçons würmiens, je "
          "dîne d’exquis rôtis de bœuf au kir, à l’aÿ d’âge mûr et "
          "cætera ! » ÀÂÆÇÉÈÊËÎÏÔŒÙÛ"
          "ÜŸ",
    "it": "«Già», disse il cavaliere: «Perché è lì, così più pane e "
          "caffè per tutti, Niccolò!» È così. ÀÉÌÒÙ",
    "de": "„Falsches Üben von Xylophonmusik quält jeden größeren Zwerg“, sagte der "
          "Bäcker – ‚Ärger im Ölkeller? Für mich nicht!‘ ÄÖÜ",
    "es": "¿Quién añoró el pan aquí? ¡Él, el último caballero! Comió "
          "más ñame con queso, y la cigüeña voló sobre el castillo. ÁÉÍÓ"
          "ÚÜÑ",
    "pt": "À noite, vovô e o padeiro português põem açúcar no pão sob a "
          "lâmpada; vovó vê o cavaleiro órfão, já sem lã: “Ótimo, "
          "é aí!”, diz ele à mãe, após o chá. ÁÂÃÀÇÉ"
          "ÊÍÓÔÕÚ",
    "pl": "„Mężny bądź, chroń pułk twój i sześć flag” – "
          "zażółć gęślą jaźń! ĄĆĘŁŃÓ"
          "ŚŹŻ",
    "cs": "„Příliš žluťoučký kůň úpěl ďábelsk"
          "é ódy,“ řekl rytíř. ÁČĎÉĚÍŇÓŘ"
          "ŠŤÚŮÝŽ",
    "hu": "„Árvíztűrő tükörfúrógép”, mondta a pék, "
          "és öt kenyér sült a kávé mellé. ÁÉÍÓÖŐ"
          "ÚÜŰ",
    "tr": "Pijamalı hasta yağız şoföre çabucak güvendi. İyi günler, "
          "Çağrı! ÇĞİÖŞÜ",
}
# the old font entries (as examples/ui.json, plus no-effect and custom-gradient builds) and what the base code made
# of them: sha256 of each .fnt and of each PNG's decoded RGBA pixels (PNG bytes differ between Pillow versions)
OLD_FONTS = [
    {"name": "dialogue", "glyphs": "glyphs/dialogue.txt", "scale": 2, "effect": "shadow"},
    {"name": "damage", "glyphs": "glyphs/damage.txt", "scale": 2, "effect": "outline",
     "sample": ["1234  9999", "+250  -30", "MISS"]},
    {"name": "title_brass", "glyphs": "glyphs/title_brass.txt", "scale": 2, "effect": "outline", "gradient": "brass",
     "caps_only": True, "sample": ["THE MINING TOWN", "Chapter 1: The Old Mill", "LEVEL 42  GOLD 9,750",
                                   "Continue?  New Game!"]},
    {"name": "title_steel", "glyphs": "glyphs/title_brass.txt", "scale": 2, "effect": "outline", "gradient": "steel",
     "caps_only": True, "sample": ["IMPERIAL FACTORY", "Restricted Area - B3"]},
    {"name": "symbols", "glyphs": "glyphs/symbols.txt", "scale": 2, "effect": "outline",
     "sample": ["☞ Fight   ► Item   ▼ ▲ ◄", "♥ ♪ ★ ✓ ✗ … • ! ?"],
     "export": {"☞": "ui_cursor_hand", "►": "ui_arrow_right"}},
    {"name": "dialogue_plain", "glyphs": "glyphs/dialogue.txt", "scale": 1, "effect": "none"},
    {"name": "dialogue_grad", "glyphs": "glyphs/dialogue.txt", "scale": 3, "effect": "outline",
     "gradient": ["ff0000", "00ff00", "0000ff"], "caps_only": True},
]
GOLDEN = {
    "assets/art/ui/fonts/font_damage.fnt": "8c5514e08e88d99d459c08cd1832ebdb",
    "assets/art/ui/fonts/font_damage.png": "837ed87df6323e916a2f981f4f0b6188",
    "assets/art/ui/fonts/font_dialogue.fnt": "4a343483fe8dd38bb2352227369ce426",
    "assets/art/ui/fonts/font_dialogue.png": "c3e766c6f0dc4f26345b337a59c92d32",
    "assets/art/ui/fonts/font_dialogue_grad.fnt": "7d85cc4486685d88d11afd534d018ca2",
    "assets/art/ui/fonts/font_dialogue_grad.png": "9f56ad4a12a2be5f38b74074588da58f",
    "assets/art/ui/fonts/font_dialogue_plain.fnt": "e8096f7c892b7c265565ce362af0c9f7",
    "assets/art/ui/fonts/font_dialogue_plain.png": "f3242378eaee2a7c5c515e209494074c",
    "assets/art/ui/fonts/font_symbols.fnt": "223ce7eeb14b6e9ab8c71b9a78c913ce",
    "assets/art/ui/fonts/font_symbols.png": "e858039548399e4e62f6e09a06efa1a4",
    "assets/art/ui/fonts/font_title_brass.fnt": "4a542ca1568c954922fde36198af8461",
    "assets/art/ui/fonts/font_title_brass.png": "edc8a77a4af2bd3add36a0b7ba83efdc",
    "assets/art/ui/fonts/font_title_steel.fnt": "c0725ef44ce5dfcdb4b9f55f29e831ba",
    "assets/art/ui/fonts/font_title_steel.png": "e7311de4e9fb94d8f714a1d9dfd54032",
    "assets/art/ui/symbols/ui_arrow_right.png": "bd52d745286e6502be50a3d98d595018",
    "assets/art/ui/symbols/ui_cursor_hand.png": "c695a9023c19b034f757766fd8e748e2",
    "assets_src/art/ui/fonts/font_damage_preview.png": "01d9946803c87e8e28017512bbb4b69b",
    "assets_src/art/ui/fonts/font_dialogue_grad_preview.png": "d1df225adf6ddc5231cced0ca2460fd9",
    "assets_src/art/ui/fonts/font_dialogue_plain_preview.png": "bb322ac03c3225660d20b9ad458dd978",
    "assets_src/art/ui/fonts/font_dialogue_preview.png": "cc3dd339aa90cb61309d9939a60c8a90",
    "assets_src/art/ui/fonts/font_symbols_preview.png": "5f7fe0d00c63abdcfdc81e52b5ca53cc",
    "assets_src/art/ui/fonts/font_title_brass_preview.png": "579c489f6aa7e4175fac9f98a0c93a8c",
    "assets_src/art/ui/fonts/font_title_steel_preview.png": "23a9c796747e1b9dbcf5a70a17797211",
}


def raw_glyphs(path):
    """{char: [rows as written]} straight from the file text (lane_fonts.parse pads and cuts rows to the height, so
    a glyph drawn too tall would pass through it unseen)."""
    out, cur = {}, None
    with open(path, encoding="utf-8") as f:
        for line in f.read().splitlines():
            if not line or line.startswith("# "):
                continue
            if line.startswith("char "):
                cur = line[5:]
                cur = chr(int(cur[2:], 16)) if len(cur) > 2 and cur.startswith("U+") else cur
                out[cur] = []
            elif cur is not None:
                out[cur].append(line)
    return out


def ink_rows(a):
    ys = np.where(a.any(1))[0]
    return (int(ys.min()), int(ys.max())) if len(ys) else (None, None)


def contains_at(big, small):
    """Smallest x where every ink pixel of `small` is ink in `big` (same height), else None."""
    for dx in range(big.shape[1] - small.shape[1] + 1):
        if not (small & ~big[:, dx:dx + small.shape[1]]).any():
            return dx
    return None


def sha_png(path):
    with Image.open(path) as im:
        px = np.asarray(im.convert("RGBA"))
    return hashlib.sha256(px.tobytes() + repr(px.shape).encode()).hexdigest()[:32]


def sha_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:32]


def make_game(tmp):
    os.makedirs(os.path.join(tmp, "art_src", "dotwork"), exist_ok=True)
    with open(os.path.join(tmp, "project.godot"), "w") as f:
        f.write("config_version=5\n")
    return tmp


def run_cli(argv):
    import dotwork
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = dotwork.main(argv)
    return code, out.getvalue() + err.getvalue()


class FontsExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_fonts_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def parse(self, name):
        import lane_fonts
        return lane_fonts.parse(os.path.join(GLYPHS, name))

    # ---- shape: height, baseline, ASCII glyphs copied unchanged
    def test_glyphs_fit_height_and_baseline(self):
        names = sorted(n for n in os.listdir(GLYPHS) if n.endswith(".txt"))
        self.assertTrue({"dialogue_latin.txt", "title_brass_latin.txt"} <= set(names))
        for name in names:
            meta, g = self.parse(name)
            raw = raw_glyphs(os.path.join(GLYPHS, name))
            self.assertEqual(set(raw), set(g), name)
            h, base, top = meta["height"], meta["baseline"], meta.get("top", 0)
            self.assertTrue(0 < base <= h, name)
            for c, rows in raw.items():
                self.assertLessEqual(len(rows), h, f"{name} U+{ord(c):04X}: {len(rows)} rows, the font has {h}")
                self.assertTrue(rows and min(len(r) for r in rows) > 0, f"{name} U+{ord(c):04X}: empty row")
            for c in "ABCDEFGHIJKLMNOPRSTUVWXYZ0123456789abcdefhiklmnorstuvwxz":
                if c in g:   # letters and digits without descenders stand on the baseline
                    self.assertEqual(ink_rows(g[c])[1], base - 1, f"{name} U+{ord(c):04X} is not on the baseline")
            for c in "gjpqy":
                if c in g:
                    self.assertTrue(base <= ink_rows(g[c])[1] < h, f"{name} U+{ord(c):04X}: descender")
            if top:   # the accent rows above the capitals are empty in every ASCII glyph
                for c in g:
                    if ord(c) < 128:
                        self.assertFalse(g[c][:top].any(), f"{name} U+{ord(c):04X} has ink in the accent rows")
        # composed letters stand on the baseline like their base letter (marks go above, or below for cedillas)
        for name, _ in PAIRS:
            meta, g = self.parse(name)
            for c in LATIN1 + EXT_A:
                d = unicodedata.decomposition(c).split()
                if c in g and len(d) == 2 and not d[0].startswith("<") and chr(int(d[0], 16)) in "ACEGILNORSUYZacenorsuz":
                    below = d[1] in ("0327", "0328", "0326")
                    bottom = ink_rows(g[c])[1]
                    self.assertTrue(bottom >= meta["baseline"] if below else bottom == meta["baseline"] - 1,
                                    f"{name} U+{ord(c):04X}: bottom row {bottom}")

    def test_ascii_glyphs_copied_unchanged(self):
        for latin, base in PAIRS:
            lm, lg = self.parse(latin)
            bm, bg = self.parse(base)
            top, bottom = lm.get("top", 0), lm.get("bottom", 0)
            self.assertEqual(lm["height"], bm["height"] + top + bottom, latin)
            self.assertEqual(lm["baseline"], bm["baseline"] + top, latin)
            self.assertEqual((lm["spacing"], lm["space"]), (bm["spacing"], bm["space"]), latin)
            for c, a in bg.items():
                self.assertIn(c, lg, f"{latin} lost U+{ord(c):04X}")
                self.assertTrue(np.array_equal(lg[c][top:top + bm["height"]], a), f"{latin} U+{ord(c):04X} differs from {base}")
                self.assertFalse(lg[c][:top].any() or lg[c][top + bm["height"]:].any(), f"{latin} U+{ord(c):04X}: extra ink")

    # ---- coverage
    def test_latin_blocks_covered(self):
        _, g = self.parse("dialogue_latin.txt")
        missing = [f"U+{ord(c):04X}" for c in LATIN1 + EXT_A + list(PUNCT) if c not in g]
        self.assertEqual(missing, [])                       # all 224 code points of both blocks, and the punctuation
        self.assertEqual(len(g), 94 + 224 + len(PUNCT))
        for name in os.listdir(GLYPHS):
            if name.endswith(".txt"):
                self.assertNotIn("\u2014", raw_glyphs(os.path.join(GLYPHS, name)), name)   # an en dash only
        _, t = self.parse("title_brass_latin.txt")
        caps = [c for c in LATIN1 + EXT_A if unicodedata.category(c) == "Lu"]
        self.assertEqual([c for c in caps + list(TITLE_PUNCT) if c not in t], [])
        self.assertEqual([c for c in t if unicodedata.category(c) == "Ll"], [])   # capitals only
        import lane_fonts
        lane_fonts.caps_map(t)                              # caps_only: accented lowercase drawn with its capital
        self.assertTrue(np.array_equal(t["é"], t["É"]) and np.array_equal(t["ł"], t["Ł"]))
        self.assertTrue(np.array_equal(t["ÿ"], t["Ÿ"]))
        self.assertNotIn("ß", t)                       # no capital sharp s: the check reports it
        self.assertNotIn("ı", t)                       # dotless i's capital is ASCII I: left out on purpose
        _, old = self.parse("title_brass.txt")
        before = list(old)
        self.assertEqual(list(lane_fonts.caps_map(old))[len(before):], list("abcdefghijklmnopqrstuvwxyz"))

    def test_accented_glyphs_differ_and_contain_their_base(self):
        checked = 0
        for name, _ in PAIRS:
            meta, g = self.parse(name)
            top, base_row = meta.get("top", 0), meta["baseline"]
            dotless = {"i": g.get("ı"), "j": g["j"].copy() if "j" in g else None}
            if dotless["j"] is not None:
                dotless["j"][:base_row - 5] = False      # j without its dot (rows above the x-height)
            for c in LATIN1 + EXT_A:
                d = unicodedata.decomposition(c).split()
                if c not in g or len(d) != 2 or d[0].startswith("<"):
                    continue
                b, mark = chr(int(d[0], 16)), d[1]
                below = mark in ("0327", "0328", "0326") and c not in COMMA_ABOVE
                base = dotless[b] if (b in "ij" and not below) else g.get(b)
                self.assertIsNotNone(base, f"{name} U+{ord(c):04X}: no base {b!r}")
                a = g[c]
                same = a.shape == base.shape and np.array_equal(a, base)
                self.assertFalse(same, f"{name} U+{ord(c):04X} is drawn exactly like {b!r}")
                if c in APOSTROPHE_CARONS:
                    continue
                dx = contains_at(a, base)
                self.assertIsNotNone(dx, f"{name} U+{ord(c):04X}: {b!r} is not inside it unchanged")
                extra = a.copy()
                extra[:, dx:dx + base.shape[1]] &= ~base
                ys = np.where(extra.any(1))[0]
                self.assertTrue(len(ys), f"{name} U+{ord(c):04X}: no mark")
                if below:
                    self.assertTrue(ys.min() >= base_row - 1, f"{name} U+{ord(c):04X}: the cedilla / ogonek is not below")
                else:   # a mark above: over the capitals' top, or over the x-height for lowercase
                    limit = top if (c.isupper() or base[:top + 2].any()) else base_row - 5
                    limit += mark == "030A"   # a ring may dip one row between a capital's arms (U-ring)
                    self.assertTrue(ys.max() < limit, f"{name} U+{ord(c):04X}: the mark reaches row {ys.max()}")
                checked += 1
        self.assertGreater(checked, 230)   # 157 in dialogue_latin, 80 capitals in title_brass_latin

    # ---- the coverage check
    def write(self, rel, text):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return p

    def test_check_readers(self):
        import fontcheck
        j = self.write("i18n/strings.json", json.dumps(
            {"_comment": "☃ notes are skipped", "menu": {"start": {"fr": "Démarrer", "pt-BR": "Começar"}},
             "de": {"intro": ["Grüß Gott", {"line": "Tschüss"}]}}, ensure_ascii=False))
        self.assertEqual(fontcheck.read_strings(j), [("fr", "menu.start", "Démarrer"),
                                                     ("pt_BR", "menu.start", "Começar"),
                                                     ("de", "intro.0", "Grüß Gott"),
                                                     ("de", "intro.1.line", "Tschüss")])
        r = self.write("i18n/records.json", json.dumps([{"id": "start", "de": "Los", "tr": "Başla"},
                                                        {"key": "quit", "de": "Ende"}, {"de": "ohne Namen"}]))
        self.assertEqual(fontcheck.read_strings(r), [("de", "start", "Los"), ("tr", "start", "Başla"),
                                                     ("de", "quit", "Ende"), ("de", "2", "ohne Namen")])
        c = self.write("i18n/ui.csv", "keys,en,pl,?context\ngreet,Hello,Cześć,☃ note\n"
                                      "bye,Bye,\"Do widzenia, ładnie\",x\n")
        self.assertEqual(fontcheck.read_strings(c), [("en", "greet", "Hello"), ("pl", "greet", "Cześć"),
                                                     ("en", "bye", "Bye"), ("pl", "bye", "Do widzenia, ładnie")])
        p = self.write("i18n/x.po", 'msgid ""\nmsgstr ""\n"Language: hu\\n"\n\n#: menu\nmsgctxt "menu"\n'
                                    'msgid "Start"\nmsgstr "Indítás"\n\nmsgid "Long"\nmsgstr ""\n"első "\n'
                                    '"második \\"q\\""\n\nmsgid "Todo"\nmsgstr ""\n')
        self.assertEqual(fontcheck.read_strings(p), [("hu", "menu|Start", "Indítás"),
                                                     ("hu", "Long", "első második \"q\""),
                                                     ("hu", "Todo", "Todo")])
        t = self.write("i18n/menu_tr.txt", "Başla\n\nÇık\n")
        self.assertEqual(fontcheck.read_strings(t), [("tr", "line 1", "Başla"), ("tr", "line 3", "Çık")])
        self.assertEqual([fontcheck.lang_of_path(x) for x in ("a/fr/menu.json", "menu.pt-BR.csv", "ui_es.po",
                                                              "id.json", "strings.json")], ["fr", "pt_BR", "es", "", ""])
        # decomposed input is checked in its composed form; line breaks are not characters a font draws
        res = fontcheck.check({"e", "é", " "}, [self.write("d.txt", "é é\n")])
        self.assertEqual(res["missing"], {})

    def test_check_finds_planted_missing_and_passes_clean(self):
        import fontcheck
        clean = self.write("strings/pangrams.json", json.dumps({k: {"pangram": v} for k, v in PANGRAMS.items()},
                                                               ensure_ascii=False))
        have = fontcheck.font_chars(os.path.join(GLYPHS, "dialogue_latin.txt"))
        res = fontcheck.check(have, [clean])
        self.assertEqual((res["missing"], res["strings"]), ({}, 9))
        self.assertEqual(res["languages"], list(PANGRAMS))
        # planted 1: a glyph file without l-stroke; planted 2: a Romanian S-comma, outside both blocks
        with open(os.path.join(GLYPHS, "dialogue_latin.txt"), encoding="utf-8") as f:
            src = f.read()
        cut = src.index("char ł\n")
        planted_font = self.write("fonts/no_lstroke.txt", src[:cut] + src[src.index("char ", cut + 5):])
        bad = self.write("strings/bad.json", json.dumps({"pl": {"menu": {"load": "Wczytaj grę (ładnie)"}},
                                                        "ro": {"intro": ["Bună!", "Și ce?"]}},
                                                       ensure_ascii=False))
        res = fontcheck.check(fontcheck.font_chars(planted_font), [clean, bad])
        self.assertEqual(list(res["missing"]), ["ł", "Ș"])
        self.assertEqual(res["missing"]["ł"], {"pl": ["pangram", "menu.load"]})
        self.assertEqual(res["missing"]["Ș"], {"ro": ["intro.1"]})
        lines = fontcheck.report(res, "font x", ["strings/bad.json"])
        self.assertIn("U+0142 'ł' LATIN SMALL LETTER L WITH STROKE - pl: pangram, menu.load", "\n".join(lines))
        # the command line: exit 0 clean, 1 missing, 2 for a font that is not there
        code, out = run_cli(["fonts-check", "--font", "glyphs/dialogue_latin.txt", "--strings", clean,
                             "--project", self.tmp])
        self.assertEqual(code, 0, out)
        self.assertIn("[ OK ]", out)
        code, out = run_cli(["fonts-check", "--font", "glyphs/dialogue.txt", "--strings", clean, bad,
                             "--project", self.tmp])
        self.assertEqual(code, 1, out)
        self.assertIn("U+00DF 'ß' LATIN SMALL LETTER SHARP S - de: pangram", out)
        code, out = run_cli(["fonts-check", "--font", "fonts/no_lstroke.txt", "--strings", "strings/bad.json",
                             "--project", self.tmp])
        self.assertEqual(code, 1, out)
        self.assertIn("pl: menu.load", out)
        code, out = run_cli(["fonts-check", "--font", "glyphs/title_brass_latin.txt", "--caps-only", "--strings",
                             clean, "--project", self.tmp])
        self.assertEqual(code, 1, out)   # caps_only covers the accented lowercase, but not sharp s and dotless i
        self.assertIn("2 characters missing: ßı", out)
        self.assertEqual(run_cli(["fonts-check", "--font", "glyphs/nope.txt", "--strings", clean])[0], 2)

    def test_pack_check_key(self):
        game = make_game(os.path.join(self.tmp, "game"))
        os.makedirs(os.path.join(game, "i18n"))
        with open(os.path.join(game, "i18n", "fr.json"), "w", encoding="utf-8") as f:
            json.dump({"title": PANGRAMS["fr"], "quit": "Quitter ‘ici’"}, f, ensure_ascii=False)
        spec = os.path.join(game, "fonts.json")

        def pack(glyphs):
            with open(spec, "w", encoding="utf-8") as f:
                json.dump({"name": "f", "fonts": [{"name": "dialogue", "glyphs": glyphs, "check": ["i18n/fr.json"]}]}, f)
            return run_cli(["pack", "--spec", spec, "--project", game, "--engine", "none"])

        code, out = pack("glyphs/dialogue.txt")
        self.assertEqual(code, 1, out)                      # the strings need glyphs dialogue.txt does not have
        self.assertIn("missing U+00E8 'è'", out)
        self.assertIn("fr: title", out)
        self.assertIn("U+2018", out)
        self.assertNotIn("is not read by Dotwork", out)     # "check" is a known key
        self.assertTrue(os.path.exists(os.path.join(game, "assets", "art", "ui", "fonts", "font_dialogue.fnt")))
        code, out = pack("glyphs/dialogue_latin.txt")
        self.assertEqual(code, 0, out)
        with open(os.path.join(game, "assets_src", "dotwork", "manifest_f.json"), encoding="utf-8") as f:
            row = [r for r in json.load(f)["assets"] if r["file"].endswith(".fnt")][0]
        self.assertEqual((row["checked"], row["check_missing"]), (["i18n/fr.json"], ""))
        with open(spec, "w", encoding="utf-8") as f:   # a spec path may not leave the game
            json.dump({"name": "f", "fonts": [{"name": "d", "glyphs": "glyphs/dialogue.txt", "check": ["../x.json"]}]}, f)
        self.assertEqual(run_cli(["pack", "--spec", spec, "--project", game, "--engine", "none"])[0], 2)

    # ---- old fonts unchanged, built in the same pack as the new ones
    def test_old_fonts_identical_next_to_latin_fonts(self):
        game = make_game(os.path.join(self.tmp, "game"))
        spec = os.path.join(game, "all.json")
        latin = [{"name": "dialogue_latin", "glyphs": "glyphs/dialogue_latin.txt", "scale": 2, "effect": "shadow"},
                 {"name": "title_latin", "glyphs": "glyphs/title_brass_latin.txt", "scale": 2, "effect": "outline",
                  "gradient": "brass", "caps_only": True}]
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"name": "all", "fonts": OLD_FONTS[:3] + latin + OLD_FONTS[3:]}, f, ensure_ascii=False)
        code, out = run_cli(["pack", "--spec", spec, "--project", game, "--engine", "none"])
        self.assertEqual(code, 0, out)
        for rel, want in GOLDEN.items():
            p = os.path.join(game, rel)
            self.assertEqual(sha_png(p) if p.endswith(".png") else sha_file(p), want, f"{rel} changed")
        fonts = os.path.join(game, "assets", "art", "ui", "fonts")
        with open(os.path.join(fonts, "font_dialogue_latin.fnt"), encoding="utf-8") as f:
            fnt = f.read()
        self.assertIn("lineHeight=26 base=18", fnt)          # 11 rows + shadow + air, at 2x
        for c in LATIN1 + EXT_A + list(PUNCT):
            self.assertIn(f"char id={ord(c)} ", fnt)
        self.assertIn("char id=160 ", fnt)
        with open(os.path.join(fonts, "font_title_latin.fnt"), encoding="utf-8") as f:
            self.assertIn("lineHeight=34 base=24", f.read())  # 14 rows + outline + air, at 2x
        # the gradient spans the capital rows, so a capital is coloured exactly as in title_brass
        import lane_fonts
        _, _, _, old_r, _, _ = lane_fonts.build("o", os.path.join(GLYPHS, "title_brass.txt"), self.tmp, 2, "outline",
                                                "brass", True)
        _, _, _, new_r, _, _ = lane_fonts.build("n", os.path.join(GLYPHS, "title_brass_latin.txt"), self.tmp, 2,
                                                "outline", "brass", True)
        for c in "AGQ&":
            old, new = old_r[c][0], new_r[c][0]
            self.assertTrue(np.array_equal(new[6:6 + old.shape[0]], old), c)   # 3 accent rows at 2x
            self.assertFalse(new[:6, :, 3].any() or new[6 + old.shape[0]:, :, 3].any(), c)
        e_acute = new_r["É"][0]
        self.assertTrue((e_acute[:6, :, 3] > 0).any())       # the accent itself is drawn (in the top colour)
        with Image.open(os.path.join(game, "assets_src", "art", "ui", "fonts", "font_dialogue_latin_preview.png")) as im:
            with Image.open(os.path.join(game, "assets_src", "art", "ui", "fonts", "font_dialogue_preview.png")) as old:
                self.assertGreater(im.size[1], old.size[1])   # the Latin preview adds its sample lines


if __name__ == "__main__":
    unittest.main(verbosity=2)
