#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_defaults_cvd.py
# Purpose : the built-in colours stay readable for colour-blind players and on the palette: no two built-in gauge fills
#           and no two status marks (as the status lane draws them on the default palette) collapse under qa pack's
#           colour-blind rule (Machado 2009 simulation, OKLab), and the animated-prop loops drawn in code (save-point
#           glow, chimney smoke) only use colours of the sprite or the palette.
# Usage   : python tools/art/dotwork/tests/test_defaults_cvd.py   (test_dotwork.py runs it too)
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DOTWORK = os.path.dirname(HERE)
sys.path.insert(0, DOTWORK)
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

PALETTE = os.path.join(DOTWORK, "palettes", "dotwork_default.hex")


def rgb(h):
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], float)


def collapsed(colours):
    """Pairs qa pack would flag: told apart in normal vision, but not by a simulated dichromat."""
    import qa_pack as q
    keys, out = sorted(colours), []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            normal, sim, kind = q.cvd_pair(colours[keys[i]], colours[keys[j]])
            if normal >= q.CVD_NORMAL and sim < q.CVD_SIM:
                out.append((keys[i], keys[j], kind))
    return out


class DefaultsCvdExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_cvd_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_gauge_fills_stay_apart(self):
        from lane_widgets import GAUGES
        self.assertEqual(collapsed({k: rgb(v[1]) for k, v in GAUGES.items()}), [])

    def test_status_marks_stay_apart_as_drawn(self):
        import engine
        import lane_status
        import qa_pack as q
        pal = engine.load_hex(PALETTE)
        drawn = {}
        for kind, (hint, _) in lane_status.KINDS.items():
            stack = np.concatenate([lane_status.frame(kind, i / 8, 32, pal, hint) for i in range(8)], axis=1)
            drawn[kind] = np.array(q.key_colour(stack), float)   # the colour qa pack names the mark by
        self.assertEqual(collapsed(drawn), [])

    def test_glow_stays_on_the_sprite_colours(self):
        import lane_animprops
        a = np.zeros((40, 24, 4), np.uint8)
        a[4:36, 6:18] = (40, 120, 200, 255)
        a[8:20, 8:16] = (120, 200, 240, 255)
        a[30:36, 4:20] = (70, 70, 80, 255)
        a[[3, 36], 5:19] = (5, 4, 7, 255)
        src = os.path.join(self.tmp, "crystal.png")
        Image.fromarray(a).save(src)
        own = {tuple(c) for c in a[a[..., 3] == 255][:, :3]}
        for im in lane_animprops.glow_frames(src):
            f = np.array(im.convert("RGBA"))
            self.assertLessEqual({tuple(c) for c in f[f[..., 3] >= 128][:, :3]}, own)

    def test_smoke_stays_on_the_palette(self):
        import engine
        import lane_animprops
        a = np.zeros((32, 16, 4), np.uint8)
        a[8:32, 4:12] = (120, 80, 60, 255)
        src = os.path.join(self.tmp, "chimney.png")
        Image.fromarray(a).save(src)
        pal = {tuple(int(v) for v in c) for c in engine.load_hex(PALETTE)}
        body = {tuple(c) for c in a[a[..., 3] == 255][:, :3]}
        for im in lane_animprops.smoke_frames(src, palette=PALETTE):
            f = np.array(im.convert("RGBA"))
            smoke = {tuple(c) for c in f[f[..., 3] == 255][:, :3]} - body
            self.assertTrue(smoke, "no smoke drawn")
            self.assertLessEqual(smoke, pal)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)
