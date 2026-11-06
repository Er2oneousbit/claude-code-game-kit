#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_shader_ref.py
# Purpose : Exam for shader_ref.py, the reference of the shader recipes: the inputs and golden images on disk are
#           current, each recipe does what its summary says on a few chosen pixels, and `compare` passes a matching
#           render, fails a changed one and a missing one, and honours each recipe's tolerance.
# Usage   : python tools/shaders/test_shader_ref.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import shader_ref as sr  # noqa: E402


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = sr.main([str(a) for a in argv])
    return code, out.getvalue()


class ShaderRefExam(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = sr.load_recipes()
        cls.inputs = sr.build_inputs()

    def pixel(self, name, x, y, **params):
        """RGBA floats of one recipe at one canvas pixel, with some parameters changed."""
        p = dict(self.data["recipes"][name]["params"], **params)
        return sr.EFFECTS[name](((x + 0.5) / 64, (y + 0.5) / 64), p, self.inputs)

    def test_golden_images_are_current(self):
        code, out = run("golden")
        self.assertEqual(code, 0, out)

    def test_every_recipe_has_a_reference_and_inputs_exist(self):
        self.assertEqual(set(self.data["recipes"]), set(sr.EFFECTS))
        for recipe in self.data["recipes"].values():
            for name in recipe["inputs"]:
                self.assertIn(name, self.data["inputs"])
                self.assertIn(name, self.inputs)

    def test_flash_and_clear_texels(self):
        sprite = sr.texel(self.inputs["sprite"], 32.5 / 64, 36.5 / 64)
        self.assertEqual(self.pixel("flash", 32, 36, amount=0.0), sprite)
        self.assertEqual(self.pixel("flash", 32, 36, amount=1.0)[:3], [1.0, 1.0, 1.0])
        self.assertEqual(self.pixel("flash", 0, 0), sr.CLEAR)          # a clear texel stays (0, 0, 0, 0)

    def test_dissolve_ends(self):
        self.assertEqual(self.pixel("dissolve", 32, 36, progress=0.0, edge_width=0.0)[3], 1.0)
        self.assertEqual(self.pixel("dissolve", 32, 36, progress=1.0), sr.CLEAR)

    def test_outline_rings_the_sprite(self):
        # sprite row 17 (canvas row 34): texel 5 is the body's first, texel 4 is clear (doubled: canvas x 10, 8)
        self.assertEqual(self.pixel("outline", 10, 34)[3], 1.0)
        self.assertEqual(self.pixel("outline", 10, 34)[:3], sr.texel(self.inputs["sprite"], 10.5 / 64, 34.5 / 64)[:3])
        self.assertEqual(self.pixel("outline", 8, 34)[:3], self.data["recipes"]["outline"]["params"]["outline_color"])
        self.assertEqual(self.pixel("outline", 1, 34), sr.CLEAR)

    def test_colorblind_mode_0_changes_nothing(self):
        scene = sr.texel(self.inputs["scene"], 20.5 / 64, 20.5 / 64)
        got = self.pixel("colorblind", 20, 20, mode=0)
        self.assertTrue(all(abs(a - b) < 1e-6 for a, b in zip(got, scene)))

    def test_crt_darkens_odd_rows_from_the_top(self):
        even, odd = self.pixel("crt", 30, 4), self.pixel("crt", 30, 5)
        self.assertEqual(even[:3], sr.texel(self.inputs["scene"], 30.5 / 64, 4.5 / 64)[:3])
        self.assertLess(sum(odd[:3]), sum(sr.texel(self.inputs["scene"], 30.5 / 64, 5.5 / 64)[:3]))

    def test_vignette_spares_the_centre(self):
        centre = sr.texel(self.inputs["scene"], 32.5 / 64, 32.5 / 64)
        self.assertEqual(self.pixel("vignette", 32, 32), centre)
        self.assertLess(sum(self.pixel("vignette", 0, 0)[:3]), sum(sr.texel(self.inputs["scene"], 0.5 / 64, 0.5 / 64)[:3]))

    def test_toon_bands_and_rim(self):
        lit, dark = self.pixel("toon_rim", 22, 22, rim_strength=0.0), self.pixel("toon_rim", 44, 44, rim_strength=0.0)
        self.assertGreater(lit[0], dark[0])
        self.assertGreater(self.pixel("toon_rim", 4, 32)[1], self.pixel("toon_rim", 4, 32, rim_strength=0.0)[1])

    def test_sprite_light_follows_the_light(self):
        near = self.pixel("sprite_light", 22, 22)
        far = self.pixel("sprite_light", 22, 22, light_pos=[60.0, 60.0])
        self.assertGreater(sum(near[:3]), sum(far[:3]))

    def test_compare_passes_fails_and_reports_missing(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            for name in self.data["recipes"]:
                shutil.copy2(sr.GOLDEN_DIR / f"{name}.png", out / f"{name}.png")
            code, text = run("compare", out)
            self.assertEqual(code, 0, text)
            w, h, rows = sr.image_diff.read_png(out / "flash.png")
            rows[30][30 * 4] = (rows[30][30 * 4] + 50) % 256           # one pixel off: flash allows none
            sr.image_diff.write_png(out / "flash.png", w, h, rows)
            code, text = run("compare", out, "--only", "flash")
            self.assertEqual(code, 1, text)
            w, h, rows = sr.image_diff.read_png(out / "toon_rim.png")
            rows[30][30 * 4] = (rows[30][30 * 4] + 50) % 256           # one pixel off: toon_rim allows 3 %
            sr.image_diff.write_png(out / "toon_rim.png", w, h, rows)
            code, text = run("compare", out, "--only", "toon_rim")
            self.assertEqual(code, 0, text)
            (out / "crt.png").unlink()
            code, text = run("compare", out, "--only", "crt")
            self.assertEqual(code, 1, text)
            self.assertIn("no render", text)

    def test_render_and_usage(self):
        with tempfile.TemporaryDirectory() as d:
            code, text = run("render", "vignette", "--out", Path(d) / "v.png")
            self.assertEqual(code, 0, text)
            self.assertEqual(sr.image_diff.read_png(Path(d) / "v.png")[2], sr.render("vignette")[2])
        self.assertEqual(run("render", "nope", "--out", "x.png")[0], 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
