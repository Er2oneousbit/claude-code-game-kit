#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_qapack.py
# Purpose : offline exam for `dotwork.py qa pack` (qa_pack.py): a clean synthetic game (props lit from the upper left,
#           characters with direction sprites, a ground texture, a HUD gauge set, all on a small palette) must give
#           zero findings, and each planted outlier must be caught by its check: a 2x nearest-upscaled prop, an
#           off-palette prop, a prop lit from the wrong side (a correctly lit prop mirrored), a red / green gauge pair.
#           Also: mirrored character views are not light-checked, a 2 px outline, a missing outline, a character at
#           twice the height, a prop that melts into the ground, the CLI exit codes, the lineup, and lit TileSet
#           normal maps (tile_px a [w, h] list) that must not vote on the tile size, and store / brand art (scaled
#           up on purpose) that no style check applies to.
# Usage   : python -I -B tools/art/dotwork/tests/test_qapack.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
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

try:
    import qa_pack  # noqa: E402
except ImportError:   # the base code has no qa_pack: every test below then fails on its first line
    qa_pack = None

OUTLINE = (5, 4, 7)
RAMPS = {   # light to dark, 4 steps each
    "wood": [(196, 140, 84), (160, 108, 60), (122, 80, 44), (86, 56, 32)],
    "stone": [(186, 186, 192), (146, 146, 154), (108, 108, 118), (72, 72, 82)],
    "grass": [(120, 190, 80), (96, 160, 64), (72, 128, 50), (52, 98, 40)],
    "red": [(232, 110, 96), (200, 64, 52), (156, 40, 36), (110, 28, 30)],
    "blue": [(120, 160, 236), (72, 112, 208), (48, 78, 160), (32, 50, 112)],
}
ENV = RAMPS["wood"] + RAMPS["stone"] + RAMPS["grass"]
OBJ = ENV + RAMPS["red"] + RAMPS["blue"]
GAUGES = {"hp": ["8ef07a", "3cc03c", "1e7a2a"], "mp": ["8ad0ff", "3a8ae8", "1e4aa0"],
          "atb": ["fff2a0", "f0c830", "a07a10"]}   # the widgets lane's built-in ramps


def write_hex(path, cols):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join("%02x%02x%02x\n" % c for c in cols))


def mask_edge(op):
    """Silhouette edge (4-neighbour), the border counting as outside."""
    p = np.pad(op, 1)
    inner = p[1:-1, 1:-1] & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
    return op & ~inner


def shade(w, h, ramp, shape="ellipse", light=(-1, -1), outline=1):
    """A w x h RGBA shape: an ellipse or box filled with a 4-step ramp lit from `light` (x, y: -1 = left / top),
    then a 1 px (or `outline` px, 0 = none) outline in OUTLINE."""
    yy, xx = np.mgrid[0:h, 0:w]
    u, v = (xx + 0.5) / w * 2 - 1, (yy + 0.5) / h * 2 - 1
    op = (u * u + v * v <= 1) if shape == "ellipse" else np.ones((h, w), bool)
    t = (u * -light[0] + v * -light[1]) / 2   # -1 lit .. +1 dark
    step = np.clip(((t + 1) / 2 * 4).astype(int), 0, 3)
    a = np.zeros((h, w, 4), np.uint8)
    a[op, :3] = np.array(ramp, np.uint8)[step[op]]
    a[op, 3] = 255
    ring = op.copy()
    for _ in range(outline):
        e = mask_edge(ring)
        a[e, :3] = OUTLINE
        ring &= ~e
    return a


def shaded(w, h, ramp, shape="ellipse", light=(-1, -1), outline=1, canvas=64):
    """shade() on a canvas x canvas transparent canvas, centred, feet 2 px above the bottom (the props lane's
    baseline)."""
    can = np.zeros((canvas, canvas, 4), np.uint8)
    x0, y0 = (canvas - w) // 2, canvas - 2 - h
    can[y0:y0 + h, x0:x0 + w] = shade(w, h, ramp, shape, light, outline)
    return can


def figure(ramp, height=60):
    """A standing character on a 72 px wide canvas (taller when it must be): a head in wood tones over a body in a
    ramp, lit from the left, one 1 px outline around the whole silhouette."""
    H = max(72, height + 4)
    a = np.zeros((H, 72, 4), np.uint8)
    top = H - 1 - height
    a[top + 14:H - 1, 23:49] = shade(26, height - 14, ramp, shape="box", outline=0)
    head = shade(16, 16, RAMPS["wood"], outline=0)
    m = head[..., 3] > 0
    a[top:top + 16, 28:44][m] = head[m]
    a[mask_edge(a[..., 3] == 255), :3] = OUTLINE
    return a


def gauge_fill(ramp, scale=2):
    """A gauge's fill texture as the widgets lane draws it (light top row, base, shade bottom row), scaled."""
    import lane_widgets
    _, fill, _ = lane_widgets.gauge(56, 8, ["101018", "c8a040", "806020"], ramp)
    return np.kron(fill, np.ones((scale, scale, 1), np.uint8))


class Game:
    """A synthetic game folder with Dotwork manifests: props, characters (frames + direction sprites), a base ground
    texture, icons and a gauge set, all on a small palette."""

    def __init__(self, root):
        self.root = root
        self.rows = []
        os.makedirs(os.path.join(root, "assets_src", "dotwork"), exist_ok=True)
        with open(os.path.join(root, "project.godot"), "w", encoding="utf-8") as f:
            f.write("config_version=5\n")
        self.pal, self.env = os.path.join(root, "obj.hex"), os.path.join(root, "env.hex")
        write_hex(self.pal, OBJ)
        write_hex(self.env, ENV)
        os.makedirs(os.path.join(root, "art_src", "dotwork"), exist_ok=True)
        with open(os.path.join(root, "art_src", "dotwork", "dotwork.config.json"), "w", encoding="utf-8") as f:
            json.dump({"palette": "obj.hex", "env_palette": "env.hex"}, f)

    def put(self, rel, arr, kind, **meta):
        p = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        Image.fromarray(arr).save(p)
        self.rows.append(dict({"file": rel, "kind": kind}, **meta))
        return rel

    def prop(self, name, arr):
        return self.put(f"assets/art/props/spr_{name}.png", arr, "prop", size=[arr.shape[1], arr.shape[0]],
                        workflow="Dotwork sprite lane (klein refine loop)")

    def character(self, name, ramp, height=60, mirror_light=False):
        fig = figure(ramp, height)
        src = os.path.join(self.root, "assets_src", "art", "characters", name)
        os.makedirs(src, exist_ok=True)
        views = {"s": fig, "e": fig, "w": fig[:, ::-1].copy() if mirror_light else fig}
        for d, im in views.items():
            Image.fromarray(im).save(os.path.join(src, f"rot_{d}.png"))
            for i in range(2):
                self.put(f"assets/art/characters/{name}/frames/spr_{name}_idle_{d}_{i:02d}.png", im, "frame",
                         animation=f"idle_{d}", canvas=[im.shape[1], im.shape[0]])

    def gauges(self, setname, ramps):
        for g, ramp in ramps.items():
            self.put(f"assets/art/ui/widgets/{setname}/ui_gauge_{g}_fill.png", gauge_fill(ramp), "ui_gauge", gauge=g,
                     part="fill", scale=2, workflow="Dotwork widgets (drawn in code)")

    def save(self):
        with open(os.path.join(self.root, "assets_src", "dotwork", "manifest_test.json"), "w", encoding="utf-8") as f:
            json.dump({"pack": "test", "tool": "dotwork", "assets": self.rows, "assumptions": []}, f, indent=1)

    def analyse(self):
        self.save()
        return qa_pack.analyse(self.root, os.path.join(self.root, "assets_src"), self.pal, self.env)


def clean_game(root):
    """The clean synthetic pack: five props lit from the upper left, three characters, a grass ground texture, two
    icons, and the widgets lane's hp / mp / atb gauge fills."""
    g = Game(root)
    g.prop("barrel", shaded(20, 28, RAMPS["wood"]))
    g.prop("crate", shaded(28, 26, RAMPS["wood"], shape="box"))
    g.prop("boulder", shaded(30, 24, RAMPS["stone"]))
    g.prop("lamp", shaded(14, 46, RAMPS["stone"], shape="box"))
    g.prop("shrub", shaded(26, 22, RAMPS["red"]))
    for name, ramp in (("knight", "stone"), ("baker", "red"), ("smith", "blue")):
        g.character(name, RAMPS[ramp])
    rng = np.random.default_rng(7)
    tiles = np.array(RAMPS["grass"], np.uint8)[rng.integers(0, 4, (32, 128))]
    g.put("assets/art/tiles/meadow/base_grass.png", np.dstack([tiles, np.full((32, 128), 255, np.uint8)]),
          "tile_atlas", tile_px=32)
    for name, ramp in (("item_potion", "red"), ("item_gem", "blue")):
        g.put(f"assets/art/ui/icons/ui_icon_{name}_32.png", shaded(26, 26, RAMPS[ramp], canvas=32), "icon",
              size=[32, 32])
    g.gauges("classic_hud", GAUGES)
    return g


class QaPackExam(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(qa_pack, "qa_pack.py is missing (dotwork.py qa pack)")
        self.tmp = tempfile.mkdtemp(prefix="dotwork_qapack_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def by(self, ctx, check, needle=None):
        return [f for f in ctx.findings if f["check"] == check and (needle is None or needle in f["file"]
                                                                      or needle in f.get("detail", ""))]

    # ---- the clean pack ------------------------------------------------------------------------
    def test_clean_pack_has_zero_findings(self):
        ctx = clean_game(self.tmp).analyse()
        self.assertEqual(ctx.findings, [], "\n".join(f"{f['check']}: {f['detail']} ({f['file']})" for f in ctx.findings))
        # every check really ran on it
        for c in ("scale", "palette", "outline", "light", "height", "contrast", "colourblind"):
            self.assertGreater(ctx.checked[c], 0, c)
        self.assertEqual(ctx.pack_light["side"], "left")
        self.assertEqual(ctx.pack_outline, OUTLINE)
        self.assertEqual(ctx.tile_px, 32)

    def test_lit_tileset_normal_maps_do_not_vote_on_the_tile_size(self):
        """The lighting lane's TileSet normal maps carry tile_px as the atlas region, a [w, h] list (an iso tile is
        [64, 32]); qa pack read every row's tile_px as an int and stopped with a TypeError (exit 2) on any game with
        a lit TileSet (2026-11-03, a full rehearsal game). Normal maps are data, not art: they never vote."""
        g = clean_game(self.tmp)
        nm = np.zeros((32, 128, 4), np.uint8)
        nm[..., 2] = nm[..., 3] = 255
        for rel, region in (("assets/art/lit/town_lit/ground/base_grass_normal.png", [32, 32]),
                            ("assets/art/lit/town_lit/iso/floor_cobble_normal.png", [64, 32])):
            g.put(rel, nm, "normal_map", tile_px=region, per_tile=True, workflow="Dotwork lighting (numpy)")
        ctx = g.analyse()
        self.assertEqual(ctx.tile_px, 32)
        self.assertEqual(ctx.findings, [], "\n".join(f"{f['check']}: {f['detail']}" for f in ctx.findings))

    def test_store_and_brand_art_are_not_style_checked(self):
        """The store lane scales its key art, icon and boot splash up by whole numbers on purpose (README, Store art);
        qa pack read them as accidental upscales of 1x game art (2026-11-03, a full rehearsal game: 5 scale
        findings). Store art, the game icon and the boot splash are not game-scale art: no style check applies."""
        g = clean_game(self.tmp)
        art = np.kron(shaded(30, 20, RAMPS["wood"], canvas=40), np.ones((3, 3, 1), np.uint8))
        g.put("assets_src/store/demo/steam/page_background.png", art, "store_art", size=[120, 120], k=3)
        g.put("assets/art/brand/demo/icon_demo.png", np.kron(art, np.ones((2, 2, 1), np.uint8)), "game_icon")
        g.put("assets/art/brand/demo/boot_splash_demo.png", art, "boot_splash", size=[120, 120])
        ctx = g.analyse()
        self.assertEqual(ctx.findings, [], "\n".join(f"{f['check']}: {f['detail']} ({f['file']})"
                                                     for f in ctx.findings))

    # ---- the four planted outliers -------------------------------------------------------------------
    def test_planted_2x_upscale(self):
        g = clean_game(self.tmp)
        small = shaded(22, 24, RAMPS["wood"], canvas=32)
        rel = g.prop("big_crate", np.kron(small, np.ones((2, 2, 1), np.uint8)))
        f = self.by(g.analyse(), "scale", rel)
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["value"], 2)
        self.assertIn("2x upscale", f[0]["detail"])

    def test_planted_off_palette_prop(self):
        g = clean_game(self.tmp)
        a = shaded(20, 28, RAMPS["wood"])
        op = np.argwhere(a[..., 3] == 255)
        for y, x in op[len(op) // 2:len(op) // 2 + 30]:
            a[y, x, :3] = (200, 30, 200)   # a magenta that is in neither palette
        rel = g.prop("odd_barrel", a)
        ctx = g.analyse()
        f = self.by(ctx, "palette", rel)
        self.assertEqual(len(f), 1)
        self.assertIn("#c81ec8", f[0]["detail"])
        self.assertGreater(f[0]["value"], 0)
        self.assertEqual([x for x in ctx.findings if x["file"] != rel], [])   # nothing else is blamed

    def test_planted_prop_lit_from_the_wrong_side(self):
        g = clean_game(self.tmp)
        rel = g.prop("barrel_mirrored", shaded(20, 28, RAMPS["wood"])[:, ::-1].copy())
        ctx = g.analyse()
        f = self.by(ctx, "light", rel)
        self.assertEqual(len(f), 1, ctx.findings)
        self.assertIn("lit from the right", f[0]["detail"])
        self.assertGreaterEqual(f[0]["value"], qa_pack.LIGHT_FLAG)
        self.assertEqual(self.by(ctx, "light", "spr_barrel.png"), [])   # its correctly lit twin is not flagged

    def test_planted_red_green_gauge_pair(self):
        g = clean_game(self.tmp)
        g.gauges("duel_hud", {"hp": ["7ad07a", "3ca03c", "1e6a2a"], "rage": ["f08070", "d03c30", "8a1c14"]})
        ctx = g.analyse()
        f = self.by(ctx, "colourblind")
        self.assertEqual(len(f), 1, ctx.findings)
        self.assertEqual(f[0]["group"], "gauge fills duel_hud")
        self.assertIn("hp #3ca03c", f[0]["detail"])
        self.assertIn("rage #d03c30", f[0]["detail"])
        self.assertIn("deuteranopia", f[0]["detail"])
        self.assertLess(f[0]["value"], qa_pack.CVD_SIM)

    # ---- the other checks -------------------------------------------------------------------------------
    def test_mirrored_character_views_are_not_light_checked(self):
        g = clean_game(self.tmp)
        g.character("ranger", RAMPS["wood"], mirror_light=True)   # walk_w made by mirroring walk_e
        ctx = g.analyse()
        self.assertEqual(self.by(ctx, "light"), [])
        # and the mirrored view really is lit from the other side: a light check would have flagged it
        w = os.path.join(self.tmp, "assets_src", "art", "characters", "ranger", "rot_w.png")
        e = w.replace("rot_w", "rot_e")
        vw, ve = qa_pack.light_vector(qa_pack.rgba(w))[0], qa_pack.light_vector(qa_pack.rgba(e))[0]
        self.assertLess(ve, 0)
        self.assertGreater(vw, 0)

    def test_outline_thick_and_missing(self):
        g = clean_game(self.tmp)
        thick = g.prop("thick_crate", shaded(28, 26, RAMPS["wood"], shape="box", outline=2))
        bare = g.prop("bare_barrel", shaded(20, 28, RAMPS["wood"], outline=0))
        ctx = g.analyse()
        t, b = self.by(ctx, "outline", thick), self.by(ctx, "outline", bare)
        self.assertEqual(len(t), 1)
        self.assertIn("2 px", t[0]["detail"])
        self.assertEqual(len(b), 1)
        self.assertLess(b[0]["value"], qa_pack.OUTLINE_MIN_SHARE)

    def test_character_far_off_the_class_height(self):
        g = clean_game(self.tmp)
        g.character("giant", RAMPS["blue"], height=130)
        ctx = g.analyse()
        f = [x for x in self.by(ctx, "height") if x["group"] == "giant"]
        self.assertEqual(len(f), 1, ctx.findings)
        self.assertGreater(f[0]["value"], qa_pack.HEIGHT_CHAR)

    def test_prop_melting_into_the_ground(self):
        g = clean_game(self.tmp)
        rng = np.random.default_rng(3)
        a = np.zeros((64, 64, 4), np.uint8)
        a[30:62, 16:48, :3] = np.array(RAMPS["grass"], np.uint8)[rng.integers(0, 4, (32, 32))]
        a[30:62, 16:48, 3] = 255
        rel = g.prop("grass_tuft", a)   # grass on grass, no outline
        f = self.by(g.analyse(), "contrast", rel)
        self.assertEqual(len(f), 1)
        self.assertIn("base_grass.png", f[0]["detail"])

    def test_pixel_scale_and_simulation(self):
        a = shaded(22, 24, RAMPS["wood"], canvas=32)
        self.assertEqual(qa_pack.pixel_scale(a)[0], 1)
        self.assertEqual(qa_pack.pixel_scale(np.kron(a, np.ones((3, 3, 1), np.uint8)))[0], 3)
        ring = np.zeros((32, 32, 4), np.uint8)   # a hollow 2x focus ring: the plain shape must still read 2x
        ring[0:2, 2:30] = ring[30:32, 2:30] = ring[2:30, 0:2] = ring[2:30, 30:32] = (200, 180, 90, 255)
        self.assertEqual(qa_pack.pixel_scale(ring)[0], 2)
        # Machado 2009 deuteranopia, severity 1, in linear RGB: pure red becomes an olive yellow
        self.assertEqual(qa_pack.simulate([255, 0, 0], "deuteranopia").astype(int).tolist(), [[163, 144, 0]])
        self.assertLess(qa_pack.cvd_pair([60, 160, 60], [208, 60, 48])[1], qa_pack.CVD_SIM)

    def test_light_estimators_follow_a_hue_shifted_ramp(self):
        # warm highlight to cool shadow, the usual pixel-art ramp: OKLab hues 86, 68, 45 and 12 degrees, so its shades
        # sit in three different 30 degree hue sectors (which read no shading in a ramp cut that way)
        ramp = [(236, 206, 140), (200, 150, 96), (150, 96, 72), (96, 60, 64)]
        lit = shaded(22, 30, ramp)
        for est in (lambda a: qa_pack.light_vector(a)[0], lambda a: qa_pack.light_vector_materials(a)[0]):
            self.assertLess(est(lit), -qa_pack.LIGHT_FLAG)
            self.assertGreater(est(lit[:, ::-1].copy()), qa_pack.LIGHT_FLAG)
        lab = qa_pack.oklab(np.array(ramp))
        self.assertEqual(len(set(qa_pack.materials(lab).tolist())), 1)   # one material, not four

    def test_lane_of_reads_the_manifest_rows(self):
        lo = qa_pack.lane_of
        self.assertEqual(lo({"file": "assets/art/characters/baker/frames/spr_baker_walk_e_00.png", "kind": "frame"}),
                         ("characters", "baker"))
        self.assertEqual(lo({"file": "assets/art/props/anim/chest/spr_chest_open_00.png", "kind": "frame"}),
                         ("animprops", "chest"))
        self.assertEqual(lo({"file": "assets/art/tiles/yard/overlay_rail.png", "kind": "tile_atlas",
                             "workflow": "Dotwork connector (drawn in code)"}), ("connectors", "overlay_rail"))
        self.assertEqual(lo({"file": "assets/art/characters/baker/baker_walk_e_sheet.png", "kind": "sheet"}),
                         (None, ""))
        self.assertEqual(lo({"file": "assets/art/fx/fire/spr_fx_fire_00.png", "kind": "fx_frame",
                             "workflow": "Dotwork effect lane (klein first frame + Wan 2.2)"}), ("effects", "fire"))

    def test_cli_exit_codes_and_lineup(self):
        import dotwork
        g = clean_game(self.tmp)
        g.save()
        out, js = os.path.join(self.tmp, "lineup.png"), os.path.join(self.tmp, "qa.json")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = dotwork.main(["qa", "pack", "--project", self.tmp, "--lineup", out, "--json", js])
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertIn("[ OK ] the pack is consistent", buf.getvalue())
        im = Image.open(out)
        self.assertEqual(im.width, 1800)                  # 900 game px at 2x
        self.assertIn("lineup of 8 characters and props", buf.getvalue())
        with open(js, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["findings"], [])
        self.assertEqual(data["thresholds"]["CVD_SIM"], qa_pack.CVD_SIM)
        # a planted outlier: exit 1
        g.prop("barrel_mirrored", shaded(20, 28, RAMPS["wood"])[:, ::-1].copy())
        g.save()
        with contextlib.redirect_stdout(io.StringIO()) as o, contextlib.redirect_stderr(io.StringIO()):
            rc = dotwork.main(["qa", "pack", "--project", self.tmp])
        self.assertEqual(rc, 1, o.getvalue())
        # usage: no manifests, not a game, an unknown action -> 2
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        with open(os.path.join(empty, "project.godot"), "w") as f:
            f.write("")
        for argv in (["qa", "pack", "--project", empty], ["qa", "pack", "--project", os.path.join(self.tmp, "assets")]):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
                rc = dotwork.main(argv)
            self.assertEqual(rc, 2, err.getvalue())
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                dotwork.main(["qa", "everything", "--project", self.tmp])
        self.assertEqual(cm.exception.code, 2)
        self.assertFalse(os.path.exists(os.path.join(empty, "art_src")))   # read only: no work folder made


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False, verbosity=2).result.wasSuccessful() else 1)
