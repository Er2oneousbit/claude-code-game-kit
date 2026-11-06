#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_colour.py
# Purpose : Exam for tools/access/colour.py and colour_check.py (#169): CIEDE2000 against Sharma, Wu and Dalal's 34
#           test pairs, WCAG contrast cases, the colour-vision simulation's fixed points, the Python copy of the
#           colour-blind filter against the shader recipe's own reference, the pairs check (pass, fail, refusals),
#           the picture simulation, and the colour files the kit ships for the engines with a demo.
# Usage   : python tools/access/test_colour.py        (in a game)   python core/tools/access/test_colour.py (kit)
# Notes   : Standard library only. Exit 0 all pass, 1 a case failed.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import colour as C  # noqa: E402
import colour_check  # noqa: E402

KIT = HERE.parents[2] if (HERE.parents[2] / "engines").is_dir() else None   # the kit's own clone, not a game

# Sharma, Wu and Dalal 2005, supplementary test data (L1 a1 b1 L2 a2 b2 dE00); E159
SHARMA = [
    (50.0000, 2.6772, -79.7751, 50.0000, 0.0000, -82.7485, 2.0425),
    (50.0000, 3.1571, -77.2803, 50.0000, 0.0000, -82.7485, 2.8615),
    (50.0000, 2.8361, -74.0200, 50.0000, 0.0000, -82.7485, 3.4412),
    (50.0000, -1.3802, -84.2814, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, -1.1848, -84.8006, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, -0.9009, -85.5211, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, 0.0000, 0.0000, 50.0000, -1.0000, 2.0000, 2.3669),
    (50.0000, -1.0000, 2.0000, 50.0000, 0.0000, 0.0000, 2.3669),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0009, 7.1792),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0010, 7.1792),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0011, 7.2195),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0012, 7.2195),
    (50.0000, -0.0010, 2.4900, 50.0000, 0.0009, -2.4900, 4.8045),
    (50.0000, -0.0010, 2.4900, 50.0000, 0.0010, -2.4900, 4.8045),
    (50.0000, -0.0010, 2.4900, 50.0000, 0.0011, -2.4900, 4.7461),
    (50.0000, 2.5000, 0.0000, 50.0000, 0.0000, -2.5000, 4.3065),
    (50.0000, 2.5000, 0.0000, 73.0000, 25.0000, -18.0000, 27.1492),
    (50.0000, 2.5000, 0.0000, 61.0000, -5.0000, 29.0000, 22.8977),
    (50.0000, 2.5000, 0.0000, 56.0000, -27.0000, -3.0000, 31.9030),
    (50.0000, 2.5000, 0.0000, 58.0000, 24.0000, 15.0000, 19.4535),
    (50.0000, 2.5000, 0.0000, 50.0000, 3.1736, 0.5854, 1.0000),
    (50.0000, 2.5000, 0.0000, 50.0000, 3.2972, 0.0000, 1.0000),
    (50.0000, 2.5000, 0.0000, 50.0000, 1.8634, 0.5757, 1.0000),
    (50.0000, 2.5000, 0.0000, 50.0000, 3.2592, 0.3350, 1.0000),
    (60.2574, -34.0099, 36.2677, 60.4626, -34.1751, 39.4387, 1.2644),
    (63.0109, -31.0961, -5.8663, 62.8187, -29.7946, -4.0864, 1.2630),
    (61.2901, 3.7196, -5.3901, 61.4292, 2.2480, -4.9620, 1.8731),
    (35.0831, -44.1164, 3.7933, 35.0232, -40.0716, 1.5901, 1.8645),
    (22.7233, 20.0904, -46.6940, 23.0331, 14.9730, -42.5619, 2.0373),
    (36.4612, 47.8580, 18.3852, 36.2715, 50.5065, 21.2231, 1.4146),
    (90.8027, -2.0831, 1.4410, 91.1528, -1.6435, 0.0447, 1.4441),
    (90.9257, -0.5406, -0.9208, 88.6381, -0.8985, -0.7239, 1.5381),
    (6.7747, -0.2908, -2.4247, 5.8714, -0.0985, -2.2286, 0.6377),
    (2.0776, 0.0795, -1.1350, 0.9033, -0.0636, -0.5514, 0.9082),
]


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = colour_check.main(argv)
    return code, out.getvalue()


def write(folder, d):
    p = Path(folder) / "colours.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return str(p)


class MathsExam(unittest.TestCase):
    def test_ciede2000_matches_sharmas_test_data(self):
        for row in SHARMA:
            with self.subTest(row=row):
                self.assertAlmostEqual(C.delta_e00(row[0:3], row[3:6]), row[6], places=4)

    def test_ciede2000_is_symmetric_and_zero_on_itself(self):
        for row in SHARMA:
            self.assertAlmostEqual(C.delta_e00(row[0:3], row[3:6]), C.delta_e00(row[3:6], row[0:3]), places=9)
            self.assertEqual(C.delta_e00(row[0:3], row[0:3]), 0.0)

    def test_wcag_contrast(self):
        # WCAG 2.2: white on black is 21:1, a colour on itself 1:1; #767676 on white is the usual 4.5:1 grey, and
        # #777777 just misses it (unrounded); E158
        self.assertAlmostEqual(C.contrast((255, 255, 255), (0, 0, 0)), 21.0, places=9)
        self.assertEqual(C.contrast((10, 20, 30), (10, 20, 30)), 1.0)
        self.assertGreaterEqual(C.contrast((0x76, 0x76, 0x76), (255, 255, 255)), 4.5)
        self.assertLess(C.contrast((0x77, 0x77, 0x77), (255, 255, 255)), 4.5)
        self.assertEqual(C.contrast((0, 0, 0), (255, 255, 255)), C.contrast((255, 255, 255), (0, 0, 0)))

    def test_srgb_round_trips(self):
        for v in range(256):
            self.assertEqual(C.to_srgb8(C.to_linear((v, v, v))), (v, v, v))

    def test_greys_look_the_same_to_every_player(self):
        # each Machado row sums to 1 (white stays white, a grey stays grey): a check on the copied matrices
        for kind, m in C.MACHADO.items():
            for row in m:
                self.assertAlmostEqual(sum(row), 1.0, places=5, msg=kind)
        for kind in C.KINDS:
            for v in (0, 64, 128, 200, 255):
                got = C.simulate((v, v, v), kind)
                self.assertTrue(all(abs(g - v) <= 1 for g in got), (kind, v, got))

    def test_the_confusions_each_kind_is_known_for(self):
        red, green, blue, yellow = (220, 40, 40), (40, 160, 40), (40, 40, 220), (230, 220, 40)
        rg = {k: C.difference(C.simulate(red, k), C.simulate(green, k)) for k in C.KINDS}
        by = {k: C.difference(C.simulate(blue, k), C.simulate(yellow, k)) for k in C.KINDS}
        normal_rg = C.difference(red, green)
        self.assertLess(rg["protanopia"], normal_rg / 2)      # red and green close up for protan and deutan
        self.assertLess(rg["deuteranopia"], normal_rg / 2)
        self.assertGreater(rg["tritanopia"], rg["deuteranopia"])   # not for tritan, whose confusion is elsewhere
        self.assertLess(C.difference(C.simulate((40, 120, 220), "tritanopia"), C.simulate((40, 160, 40), "tritanopia")),
                        C.difference((40, 120, 220), (40, 160, 40)) / 2)   # blue and green close up for tritan
        self.assertGreater(by["protanopia"], 40)
        self.assertEqual(C.simulate((200, 50, 50), "none"), (200, 50, 50))
        with self.assertRaises(ValueError):
            C.simulate((1, 2, 3), "monochrome")

    @unittest.skipUnless((HERE.parent / "shaders" / "shader_ref.py").is_file(), "needs tools/shaders/shader_ref.py")
    def test_the_python_filter_is_the_shader_recipes_filter(self):
        # daltonize() must be what every engine's colorblind port draws: shader_ref's fx_colorblind is the reference
        # those ports match their golden image against
        sys.path.insert(0, str(HERE.parent / "shaders"))
        import shader_ref
        img = shader_ref.build_inputs()["scene"]
        for mode, n in (("protanopia", 1), ("deuteranopia", 2), ("tritanopia", 3)):
            worst = 0
            for y in range(0, 64, 3):
                for x in range(0, 64, 3):
                    uv = ((x + 0.5) / 64, (y + 0.5) / 64)
                    src = shader_ref.texel(img, *uv)[:3]
                    ref = [round(v * 255) for v in shader_ref.fx_colorblind(uv, {"mode": n}, {"scene": img})[:3]]
                    got = C.daltonize(tuple(round(v * 255) for v in src), mode)
                    worst = max(worst, max(abs(a - b) for a, b in zip(got, ref)))
            self.assertLessEqual(worst, 2, mode)   # 8-bit input rounding only

    def test_parse(self):
        self.assertEqual(C.parse("#0072B2"), (0, 0x72, 0xB2))
        self.assertEqual(C.parse("0x0072b2"), (0, 0x72, 0xB2))
        self.assertEqual(C.parse([1, 2, 3]), (1, 2, 3))
        for bad in ("#12345", "red", "#gg0000"):
            with self.assertRaises(ValueError):
                C.parse(bad)


class CheckExam(unittest.TestCase):
    PAIRS = [["player", "enemy"]]

    def test_a_palette_swap_that_keeps_pairs_apart_passes(self):
        with tempfile.TemporaryDirectory() as d:
            p = write(d, {"min_delta_e": 20, "pairs": self.PAIRS, "palettes": {
                "none": {"player": "#29adff", "enemy": "#ff004d"},
                "protanopia": {"player": "#0072b2", "enemy": "#e69f00"},
                "deuteranopia": {"player": "#0072b2", "enemy": "#e69f00"},
                "tritanopia": {"player": "#009e73", "enemy": "#cc79a7"}}})
            code, out = run(["pairs", "--data", p])
            self.assertEqual(code, 0, out)
            self.assertIn("[info] achromatopsia", out)     # reported, never failed

    def test_red_against_green_fails_for_a_deuteranope(self):
        with tempfile.TemporaryDirectory() as d:
            p = write(d, {"pairs": self.PAIRS, "palettes": {"none": {"player": "#d03030", "enemy": "#30a030"}}})
            code, out = run(["pairs", "--data", p])
            self.assertEqual(code, 1, out)
            self.assertIn("[FAIL] deuteranopia", out)
            self.assertIn("shape, icon or label", out)

    def test_the_filter_is_applied_where_a_mode_has_no_palette(self):
        none = {"player": "#d03030", "enemy": "#30a030"}
        with tempfile.TemporaryDirectory() as d:
            data = colour_check.load(write(d, {"filter": True, "pairs": self.PAIRS, "palettes": {"none": none}}))
            want = C.simulate(C.daltonize(C.parse(none["player"]), "protanopia"), "protanopia")
            self.assertEqual(colour_check.seen(data, "protanopia", "player"), want)
            data = colour_check.load(write(d, {"filter": False, "pairs": self.PAIRS, "palettes": {"none": none}}))
            self.assertEqual(colour_check.seen(data, "protanopia", "player"),
                             C.simulate(C.parse(none["player"]), "protanopia"))

    def test_bad_files_are_one_error_line(self):
        cases = {
            "missing none": {"palettes": {"protanopia": {}}},
            "unknown mode": {"palettes": {"none": {}, "sepia": {}}},
            "pair names a missing colour": {"pairs": [["a", "b"]], "palettes": {"none": {"a": "#000000"}}},
            "bad colour": {"palettes": {"none": {"a": "blue"}}},
            "pair of three": {"pairs": [["a", "b", "c"]], "palettes": {"none": {}}},
        }
        with tempfile.TemporaryDirectory() as d:
            for what, data in cases.items():
                with self.subTest(case=what):
                    code, out = run(["pairs", "--data", write(d, data)])
                    self.assertEqual(code, 2, out)
                    self.assertIn("[error]", out)
                    self.assertNotIn("Traceback", out)
            code, out = run(["pairs", "--data", str(Path(d) / "nothing.json")])
            self.assertEqual(code, 2, out)
            (Path(d) / "broken.json").write_text("{", encoding="utf-8")
            self.assertEqual(run(["pairs", "--data", str(Path(d) / "broken.json")])[0], 2)

    def test_no_pairs_is_a_warning_not_a_failure(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = run(["pairs", "--data", write(d, {"palettes": {"none": {}}})])
            self.assertEqual(code, 0, out)
            self.assertIn("[warn]", out)

    def test_image_writes_one_picture_per_kind(self):
        import image_diff
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "shot.png"
            rows = [bytearray([220, 40, 40, 255, 40, 160, 40, 255, 128, 128, 128, 255]) for _ in range(2)]
            image_diff.write_png(src, 3, 2, rows)
            code, out = run(["image", str(src), "--out", str(Path(d) / "sim")])
            self.assertEqual(code, 0, out)
            for kind in C.KINDS:
                w, h, got = image_diff.read_png(Path(d) / "sim" / f"shot_{kind}.png")
                self.assertEqual((w, h), (3, 2))
                self.assertEqual(tuple(got[0][0:3]), C.simulate((220, 40, 40), kind))
                self.assertEqual(tuple(got[1][8:11]), C.simulate((128, 128, 128), kind))
            self.assertEqual(run(["image", str(Path(d) / "none.png")])[0], 2)


@unittest.skipUnless(KIT, "the kit's engine colour files (run from the kit)")
class KitColoursExam(unittest.TestCase):
    ENGINES = ("godot", "web", "love2d")

    def test_every_engine_demo_keeps_its_pairs_apart(self):
        for e in self.ENGINES:
            with self.subTest(engine=e):
                code, out = run(["pairs", "--data", str(KIT / "engines" / e / "skeleton/data/access/colours.json")])
                self.assertEqual(code, 0, out)
                self.assertNotIn("[warn]", out)

    def test_the_template_declares_no_pairs(self):
        code, out = run(["pairs", "--data", str(KIT / "core/data/access/colours.json")])
        self.assertEqual(code, 0, out)
        self.assertIn("[warn]", out)

    def test_godots_old_filter_over_its_demo_colours_fails(self):
        # #169: Godot ran the colour-blind filter over its demo instead of swapping palettes; on the demo's own
        # colours the filter pulled the player and the box together for protan and deutan players
        d = json.loads((KIT / "engines/godot/skeleton/data/access/colours.json").read_text(encoding="utf-8"))
        old = dict(d, filter=True, palettes={"none": d["palettes"]["none"]})
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(["pairs", "--data", write(tmp, old)])
        self.assertEqual(code, 1, out)
        self.assertIn("[FAIL] protanopia    player vs target", out)
        self.assertIn("[FAIL] deuteranopia  player vs target", out)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=1)
