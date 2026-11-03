#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_bdf.py
# Purpose : offline exam for the bdf lane (lane_bdf.py): BDF parsing, the BMFont offsets, page pixels that match
#           the glyph bits, cutting the font down to the game's strings, the coverage check naming a missing
#           character and where it is used, string files (JSON / CSV / PO with continuation lines and escapes / text,
#           read as fonts-check reads them, in composed form), and the licence rule.
# Usage   : python tools/art/dotwork/tests/test_bdf.py   (test_dotwork.py runs it too)
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DOTWORK = os.path.dirname(HERE)
sys.path.insert(0, DOTWORK)
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

# a tiny BDF: "A" (5x7), the CJK character for bread's first half (U+9762, 8x8) and the full stop U+3002
BDF = """STARTFONT 2.1
FONT -Test-Tiny-Medium-R-Normal--10-100-75-75-P-60-ISO10646-1
SIZE 10 75 75
FONTBOUNDINGBOX 8 10 0 -2
STARTPROPERTIES 3
FAMILY_NAME "Tiny"
FONT_ASCENT 8
FONT_DESCENT 2
ENDPROPERTIES
CHARS 3
STARTCHAR A
ENCODING 65
DWIDTH 6 0
BBX 5 7 0 0
BITMAP
70
88
88
F8
88
88
88
ENDCHAR
STARTCHAR uni9762
ENCODING 38754
DWIDTH 9 0
BBX 8 8 0 -1
BITMAP
FF
81
BD
A5
A5
BD
81
FF
ENDCHAR
STARTCHAR uni3002
ENCODING 12290
DWIDTH 4 0
BBX 3 3 0 -1
BITMAP
40
A0
40
ENDCHAR
ENDFONT
"""


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class BdfExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_bdf_")
        self.bdf = os.path.join(self.tmp, "tiny.bdf")
        with open(self.bdf, "w", encoding="utf-8") as f:
            f.write(BDF)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_parse_and_bmfont_offsets(self):
        import lane_bdf
        meta, g = lane_bdf.parse_bdf(self.bdf)
        self.assertEqual((meta["ascent"], meta["descent"], meta["family"]), (8, 2, "Tiny"))
        self.assertEqual(sorted(g), [65, 12290, 38754])
        bm, xo, yo, dw = g[65]
        self.assertEqual(bm.shape, (7, 5))
        self.assertEqual("".join("#" if v else "." for v in bm[3]), "#####")   # F8 = the crossbar
        out = os.path.join(self.tmp, "out")
        fnt, pages = lane_bdf.build("t", meta, g, {65, 38754}, out)
        t = read(fnt)
        self.assertIn("common lineHeight=10 base=8", t)
        a = dict(kv.split("=") for kv in re.search(r"char id=65 .*", t).group(0).split()[1:])
        self.assertEqual((a["width"], a["height"], a["xadvance"], a["yoffset"]), ("5", "7", "6", "1"))  # 8 - (0 + 7)
        c = dict(kv.split("=") for kv in re.search(r"char id=38754 .*", t).group(0).split()[1:])
        self.assertEqual(c["yoffset"], "1")                                       # 8 - (-1 + 8): one row below base
        self.assertNotIn("char id=12290", t)                                      # not asked for
        page = np.array(Image.open(pages[0]))
        x, y = int(a["x"]), int(a["y"])
        self.assertTrue(((page[y:y + 7, x:x + 5, 3] == 255) == bm).all())       # the page holds exactly the bits

    def test_strings_and_coverage(self):
        import lane_bdf
        _, g = lane_bdf.parse_bdf(self.bdf)
        js = os.path.join(self.tmp, "s.json")
        with open(js, "w", encoding="utf-8") as f:
            json.dump({"menu": {"start": "A面。"}, "list": ["AB"]}, f)
        po = os.path.join(self.tmp, "s.po")
        with open(po, "w", encoding="utf-8") as f:
            f.write('msgid "x"\nmsgstr "A A"\n')
        csvf = os.path.join(self.tmp, "s.csv")
        with open(csvf, "w", encoding="utf-8") as f:
            f.write("keys,en\nt1,AAA\n")
        src = lane_bdf.strings_of(js) + lane_bdf.strings_of(po) + lane_bdf.strings_of(csvf)
        self.assertIn(("s.json:menu.start", "A面。"), src)
        self.assertIn(("s.json:list.0", "AB"), src)
        self.assertIn(("s.po:x", "A A"), src)
        self.assertIn(("s.csv:t1", "AAA"), src)                                 # the key column is not text
        miss = lane_bdf.coverage(g, src)
        self.assertEqual(set(miss), {"B"})
        self.assertEqual(miss["B"], ["s.json:list.0"])

    def test_po_continuation_escapes_and_nfc(self):
        # the form gettext tools write long strings in: msgstr "" then continuation lines (#96)
        import lane_bdf
        _, g = lane_bdf.parse_bdf(self.bdf)
        po = os.path.join(self.tmp, "fr.po")
        with open(po, "w", encoding="utf-8") as f:
            f.write('msgid "hello"\nmsgstr ""\n"A\\"面"\n"。Ω\\n"\n\nmsgid "bye"\nmsgstr "A"\n')
        src = lane_bdf.strings_of(po)
        self.assertIn(("fr.po:hello", 'A"面。Ω\n'), src)
        miss = lane_bdf.coverage(g, src)
        self.assertEqual(set(miss), {'"', "Ω"})                                  # not "\\", not the line break
        self.assertEqual(miss["Ω"], ["fr.po:hello"])
        # composed form: "e" + a combining acute is drawn with the font's "é"
        g2 = dict(g)
        g2[0xE9] = g[65]
        self.assertEqual(lane_bdf.coverage(g2, [("x", "é")]), {})

    def test_pack_reads_po_continuation_lines(self):
        entry = {"name": "tiny", "source": "assets_src/tiny.bdf", "license": "assets_src/OFL.txt",
                 "strings": ["assets_src/s_fr.po"], "ascii": False}
        po = os.path.join(self.tmp, "assets_src", "s_fr.po")

        def write_po(body):
            os.makedirs(os.path.dirname(po), exist_ok=True)
            with open(po, "w", encoding="utf-8") as f:
                f.write(body)
        write_po('msgid "hello"\nmsgstr ""\n"A面"\n"。"\n')
        code, out = self.pack(entry, {})
        self.assertEqual(code, 0, out)
        t = read(os.path.join(self.tmp, "assets", "art", "fonts", "tiny", "font_tiny.fnt"))
        self.assertEqual(sorted(int(x) for x in re.findall(r"char id=(\d+)", t)), [65, 12290, 38754])
        write_po('msgid "hello"\nmsgstr ""\n"A, Ωmega"\n')
        code, out = self.pack(entry, {})
        self.assertEqual(code, 1, out)
        self.assertIn("'Ω' U+03A9 in s_fr.po:hello", out)

    def pack(self, entry, strings):
        import test_dotwork as td
        import dotwork
        td.make_project(self.tmp)
        os.makedirs(os.path.join(self.tmp, "assets_src"), exist_ok=True)
        shutil.copy(self.bdf, os.path.join(self.tmp, "assets_src", "tiny.bdf"))
        with open(os.path.join(self.tmp, "assets_src", "OFL.txt"), "w", encoding="utf-8") as f:
            f.write("SIL Open Font License 1.1 (test copy)\n")
        with open(os.path.join(self.tmp, "assets_src", "s.json"), "w", encoding="utf-8") as f:
            json.dump(strings, f)
        spec = os.path.join(self.tmp, "f.json")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"name": "f", "bdf": [entry]}, f)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = dotwork.main(["pack", "--spec", spec, "--project", self.tmp, "--no-verify"])
        return code, out.getvalue()

    def test_pack_subset_license_and_missing_glyph(self):
        entry = {"name": "tiny", "source": "assets_src/tiny.bdf", "license": "assets_src/OFL.txt",
                 "strings": ["assets_src/s.json"], "ascii": False}
        code, out = self.pack(entry, {"title": "A面。"})
        self.assertEqual(code, 0, out)
        d = os.path.join(self.tmp, "assets", "art", "fonts", "tiny")
        t = read(os.path.join(d, "font_tiny.fnt"))
        self.assertEqual(sorted(int(x) for x in re.findall(r"char id=(\d+)", t)), [65, 12290, 38754])
        self.assertIn("Open Font License", read(os.path.join(d, "font_tiny_LICENSE.txt")))   # travels with the font
        # a planted character the font lacks stops the run and says where it is used
        code, out = self.pack(entry, {"title": "A面", "menu": ["Z"]})
        self.assertEqual(code, 1, out)
        self.assertIn("'Z' U+005A in s.json:menu.0", out)
        # no licence file: a usage error
        entry.pop("license")
        code, out = self.pack(entry, {"title": "A"})
        self.assertEqual(code, 2)
        self.assertIn("licence", out)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)
