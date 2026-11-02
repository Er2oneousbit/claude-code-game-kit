#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_lighting.py
# Purpose : offline exam for the lighting lane: normals.py (unit length, z > 0, a flat interior faces the camera, rims
#           point outward, deterministic, tileable textures give tileable maps, opaque tiles get no border rim), the
#           occluder outline (corners on the silhouette, a sane count), and lane_lighting end to end on a throwaway
#           game folder (lit SpriteFrames with a repeated pose, lit TileSet copy, lit prop scene, demo scene), plus
#           the dotwork.py and verify.py hooks. No Godot, no ComfyUI, no network.
# Usage   : python -I -B tools/art/dotwork/tests/test_lighting.py
#           DOTWORK_TEST_DIR=<another dotwork folder> runs the same exam against that copy (the base-fails proof).
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import os
import re
import shutil
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DOTWORK = os.environ.get("DOTWORK_TEST_DIR") or os.path.dirname(HERE)
sys.path.insert(0, DOTWORK)   # -I drops the script folder, so the dotwork folder is put on the path by hand
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import fcore  # noqa: E402
import godot  # noqa: E402

try:   # missing on a Dotwork without the lighting lane: every test then fails on its own, with this reason
    import normals
    import lane_lighting
    MISSING = None
except ImportError as exc:
    normals = lane_lighting = None
    MISSING = f"lighting lane not present: {exc}"

FLAT = (128, 128, 255)


# ---- fixtures ----------------------------------------------------------------------
def figure(w=24, h=32, seed=1):
    """A small sprite: a two-tone ellipse body with a dark outline, a highlight and a few speckles, on clear."""
    yy, xx = np.mgrid[:h, :w]
    body = ((xx - w / 2 + 0.5) / (w * 0.42)) ** 2 + ((yy - h / 2 + 0.5) / (h * 0.45)) ** 2 < 1
    a = np.zeros((h, w, 4), np.uint8)
    a[body] = (150, 90, 60, 255)
    a[body & (yy < h // 2)] = (190, 150, 90, 255)
    ring = body & ~(np.roll(body, 1, 0) & np.roll(body, -1, 0) & np.roll(body, 1, 1) & np.roll(body, -1, 1))
    a[ring, :3] = (20, 16, 24)
    rng = np.random.RandomState(seed)
    spots = body & ~ring & (rng.rand(h, w) < 0.08)
    a[spots, :3] = (240, 230, 200)
    return a


def square(n=20, lo=4, hi=16, rgb=(200, 100, 50)):
    a = np.zeros((n, n, 4), np.uint8)
    a[lo:hi, lo:hi] = rgb + (255,)
    return a


def tileable(n=16, seed=3):
    """Random opaque texture: under wrap-around every array tiles with itself, so 2x2 copies are seamless."""
    rng = np.random.RandomState(seed)
    rgb = (rng.rand(n, n, 3) * 255).astype(np.uint8)
    return np.dstack([rgb, np.full((n, n), 255, np.uint8)])


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def need(case):
    case.assertIsNone(MISSING, MISSING)


class Game:
    """A throwaway game folder with Dotwork's settings bound to it."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="dotwork_lit_")
        open(os.path.join(self.dir, "project.godot"), "w").close()
        self.s = fcore.Settings(self.dir)
        self.s.ensure_work()
        fcore.bind(self.s)
        godot.ENABLED = True
        self.man = fcore.Manifest(self.s, "lit_test")

    def path(self, *p):
        return os.path.join(self.dir, *p)

    def png(self, rel, arr):
        p = self.path(*rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        Image.fromarray(np.asarray(arr, np.uint8)).save(p)
        return p

    def run(self, entry):
        with contextlib.redirect_stdout(io.StringIO()):
            lane_lighting.run([entry], self.dir, self.man, self.s.conf)

    def read(self, rel):
        with open(self.path(*rel.split("/")), encoding="utf-8") as f:
            return f.read()

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


# ---- normals.py ----------------------------------------------------------------------
class TestNormals(unittest.TestCase):
    def test_unit_length_within_8bit(self):
        need(self)
        for a in (figure(), square(), tileable()):
            for cells in (None, [(0, 0, a.shape[1], a.shape[0])]):
                n = normals.decode(normals.normal_map(a, 3, 1.0, 1.0, cells=cells))
                err = np.abs(np.linalg.norm(n, axis=2) - 1.0)
                # each channel rounds to 1/255 of its 0..1 range: at most sqrt(3) * (1/255) off unit length
                self.assertLessEqual(float(err.max()), np.sqrt(3) / 255 + 1e-6)

    def test_z_positive_everywhere(self):
        need(self)
        rng = np.random.RandomState(7)
        noise = np.dstack([(rng.rand(24, 24, 3) * 255).astype(np.uint8), np.full((24, 24), 255, np.uint8)])
        for a, strength in ((figure(), 1.0), (noise, 8.0), (square(), 8.0)):   # strength 8: the steepest slopes
            nm = normals.normal_map(a, 4, 4.0, strength)
            self.assertGreater(int(nm[..., 2].min()), 128)
            self.assertGreater(float(normals.decode(nm)[..., 2].min()), 0.0)

    def test_flat_interior_faces_camera(self):
        need(self)
        nm = normals.normal_map(square(30, 4, 26), bevel=3, detail=1.0)
        inner = nm[9:21, 9:21].reshape(-1, 3)   # more than bevel + 1 px from every edge
        self.assertTrue((inner == FLAT).all())
        self.assertTrue((nm[:4] == FLAT).all() and (nm[:, :4] == FLAT).all())   # clear pixels are flat too

    def test_edges_point_outward(self):
        need(self)
        nm = normals.normal_map(square(20, 4, 16), bevel=3, detail=1.0).astype(int)
        mid = slice(6, 14)                                   # the rims, away from the corners
        self.assertTrue((nm[mid, 4, 0] < 128).all())         # left rim points left (x < 0)
        self.assertTrue((nm[mid, 15, 0] > 128).all())        # right rim points right
        self.assertTrue((nm[4, mid, 1] > 128).all())         # top rim points up (OpenGL: green up)
        self.assertTrue((nm[15, mid, 1] < 128).all())        # bottom rim points down
        self.assertTrue((np.abs(nm[mid, 4, 1] - 128) <= 1).all())   # and only sideways
        # a disc: every rim pixel's normal leans away from the centre
        yy, xx = np.mgrid[:40, :40]
        disc = np.zeros((40, 40, 4), np.uint8)
        inside = (xx - 19.5) ** 2 + (yy - 19.5) ** 2 < 15 ** 2
        disc[inside] = (120, 160, 90, 255)
        n = normals.decode(normals.normal_map(disc, 3, 1.0))
        rim = inside & ~(np.roll(inside, 1, 0) & np.roll(inside, -1, 0) & np.roll(inside, 1, 1) & np.roll(inside, -1, 1))
        out_x, out_y = (xx - 19.5)[rim], -(yy - 19.5)[rim]   # outward, y up
        self.assertTrue((n[..., 0][rim] * out_x + n[..., 1][rim] * out_y > 0).all())

    def test_deterministic(self):
        need(self)
        a = figure()
        self.assertEqual(normals.normal_map(a).tobytes(), normals.normal_map(a.copy()).tobytes())
        b = figure(seed=2)
        self.assertNotEqual(normals.normal_map(a).tobytes(), normals.normal_map(b).tobytes())

    def test_tileable_texture_gives_tileable_map(self):
        need(self)
        t = tileable()
        n = 16
        one = normals.normal_map(t, 2, 1.0, cells=[(0, 0, n, n)])
        # the map of 2x2 copies, taken as one wrapping texture (what an endless floor shows), is the tile's map 2x2:
        # nothing changes across the tile edges, so there is no seam
        big = normals.normal_map(np.tile(t, (2, 2, 1)), 2, 1.0, cells=[(0, 0, 2 * n, 2 * n)])
        self.assertEqual(big.tobytes(), np.tile(one, (2, 2, 1)).tobytes())
        # and an atlas of four copies, each lit as its own tile, gives the same picture
        atlas = normals.normal_map(np.tile(t, (2, 2, 1)), 2, 1.0, cells=normals_cells(2, 2, n))
        self.assertEqual(atlas.tobytes(), big.tobytes())
        # shifting the texture shifts the map (no position along the tile is special)
        shifted = normals.normal_map(np.roll(t, (5, 3), (0, 1)), 2, 1.0, cells=[(0, 0, n, n)])
        self.assertEqual(shifted.tobytes(), np.roll(one, (5, 3), (0, 1)).tobytes())
        # sprite mode on the same pixels would put a rim along the border: the tile mode is what removes it
        sprite = normals.normal_map(t, 2, 1.0)
        self.assertNotEqual(sprite[:, 0].tobytes(), one[:, 0].tobytes())

    def test_opaque_tile_has_no_border_rim(self):
        need(self)
        atlas = np.zeros((32, 32, 4), np.uint8)
        atlas[:16, :16] = (90, 140, 60, 255)
        atlas[:16, 16:] = (90, 140, 60, 255)
        atlas[16:, :16] = (150, 120, 80, 255)
        atlas[16:, 16:] = (60, 60, 70, 255)
        nm = normals.normal_map(atlas, bevel=4, detail=1.0, cells=normals_cells(2, 2, 16))
        self.assertTrue((nm.reshape(-1, 3) == FLAT).all())                 # uniform tiles: flat, borders included
        self.assertFalse((normals.normal_map(atlas, 4, 1.0).reshape(-1, 3) == FLAT).all())   # sprite mode: rims
        # an overlay tile, clear on its left half: a rim at the real edge, none at the tile border on the right
        cell = np.zeros((16, 16, 4), np.uint8)
        cell[:, 8:] = (120, 100, 80, 255)
        tn = normals.normal_map(cell, bevel=3, detail=1.0, cells=[(0, 0, 16, 16)]).astype(int)
        self.assertTrue((tn[:, 8, 0] < 128).all())                          # the real edge points left
        self.assertTrue((tn[:, 12:].reshape(-1, 3) == FLAT).all())          # the opaque side runs on into the next tile


def normals_cells(cols, rows, n):
    return [(x * n, y * n, n, n) for y in range(rows) for x in range(cols)]


# ---- occluder outline ---------------------------------------------------------------
def touches(mask, x, y):
    """A pixel-corner point lies on (or inside) the silhouette when one of its four pixels is opaque."""
    H, W = mask.shape
    return any(0 <= py < H and 0 <= px < W and mask[py, px] for px in (x - 1, x) for py in (y - 1, y))


class TestOccluder(unittest.TestCase):
    def shape(self):
        """A lamp-post-like prop: a base block, a thin post, a lantern box and an arm with a notch."""
        a = np.zeros((48, 32, 4), np.uint8)
        a[40:46, 8:24] = (90, 80, 70, 255)     # base
        a[10:40, 14:18] = (60, 50, 40, 255)    # post
        a[4:14, 10:22] = (200, 180, 90, 255)   # lantern
        a[16:19, 18:26] = (60, 50, 40, 255)    # arm
        a[4:9, 14:18] = 0                      # a notch from the top (the polygon must not invent corners there)
        return a

    def test_full_outline_points_on_silhouette(self):
        need(self)
        a = self.shape()
        mask = a[..., 3] >= 128
        for k in (6, 12, 24):
            pts = lane_lighting.occluder_points(a, "full", max_points=k)
            self.assertTrue(3 <= len(pts) <= k, pts)
            self.assertTrue(all(touches(mask, x, y) for x, y in pts), pts)
        loop = normals.trace_outline(mask)
        self.assertAlmostEqual(abs(normals.polygon_area(loop)), float(mask.sum()))   # no holes: the outline is exact
        pts = lane_lighting.occluder_points(a, "full", max_points=24)
        self.assertGreater(abs(normals.polygon_area(pts)) / mask.sum(), 0.6)            # still the silhouette's size

    def test_base_outline_stays_at_the_foot(self):
        need(self)
        a = self.shape()
        mask = a[..., 3] >= 128
        pts = lane_lighting.occluder_points(a, "base", band=0.25, max_points=12)
        top, bottom = 4, 46
        band = max(4, round((bottom - top) * 0.25))
        self.assertTrue(3 <= len(pts) <= 12)
        self.assertTrue(all(y >= bottom - band and touches(mask, x, y) for x, y in pts), pts)
        self.assertEqual(lane_lighting.occluder_points(np.zeros((8, 8, 4), np.uint8)), [])
        # a bench: a seat on two legs. The base outline spans both feet (each corner still at a row end, so on the
        # silhouette), instead of shadowing from one leg
        bench = np.zeros((24, 32, 4), np.uint8)
        bench[6:12, 2:30] = (120, 80, 50, 255)
        bench[12:22, 4:7] = (40, 40, 40, 255)
        bench[12:22, 25:28] = (40, 40, 40, 255)
        bmask = bench[..., 3] >= 128
        pts = lane_lighting.occluder_points(bench, "base", band=0.25, max_points=12)
        xs = [x for x, _ in pts]
        self.assertEqual((min(xs), max(xs)), (4, 28))
        self.assertTrue(all(y >= 22 - 4 and touches(bmask, x, y) for x, y in pts), pts)

    def test_simplified_outline_never_crosses_itself(self):
        need(self)
        # ragged random blobs: Douglas-Peucker alone folds some of these into self-crossing polygons (checked while
        # building this); the result must always be a simple polygon, with corners on the silhouette and in budget
        rng = np.random.RandomState(0)
        crossed = 0
        for _ in range(300):
            m = rng.rand(14, 14) < 0.55
            m[0] = m[-1] = False
            m[:, 0] = m[:, -1] = False
            loop = normals.trace_outline(m)
            if len(loop) < 8:
                continue
            for k in (4, 6, 8):
                crossed += not normals.is_simple(normals._fit(loop, k, 1.0))
                pts = normals.simplify(loop, k)
                self.assertTrue(normals.is_simple(pts), pts)
                self.assertTrue(3 <= len(pts) <= k)
                self.assertTrue(all(touches(m, x, y) for x, y in pts))
        self.assertGreater(crossed, 0)   # the fixture does reach the fallback
        self.assertFalse(normals.is_simple([(0, 0), (4, 0), (0, 4), (4, 4)]))   # a bow tie
        self.assertTrue(normals.is_simple([(0, 0), (4, 0), (4, 4), (0, 4)]))

    def test_trace_closes_on_tricky_shapes(self):
        need(self)
        m = np.zeros((6, 6), bool)
        m[1, 1] = True
        self.assertEqual(normals.trace_outline(m), [(1, 1), (1, 2), (2, 2), (2, 1)])
        m[2, 2] = True        # a diagonal neighbour is another region (4-connected): the first one is traced
        self.assertEqual(len(normals.trace_outline(m)), 4)
        ring = np.zeros((9, 9), bool)
        ring[1:8, 1:8] = True
        ring[3:6, 3:6] = False   # a hole: only the outer edge is traced
        self.assertEqual(abs(normals.polygon_area(normals.trace_outline(ring))), 49.0)


# ---- the lane, end to end on a throwaway game -------------------------------------------
class TestLane(unittest.TestCase):
    def setUp(self):
        need(self)
        self.g = Game()

    def tearDown(self):
        self.g.close()

    def frames(self):
        """A SpriteFrames whose idle repeats one pose: frames A, A (another file), B, A."""
        g = self.g
        a, b = figure(seed=1), figure(seed=5)
        for name, arr in (("hero_idle_00", a), ("hero_idle_01", a), ("hero_idle_02", b), ("hero_idle_03", a)):
            g.png(f"assets/art/characters/hero/frames/{name}.png", arr)
        godot.sprite_frames(g.path("assets", "art", "characters", "hero", "hero_frames.tres"),
                            "res://assets/art/characters/hero/frames",
                            {"idle": ([f"hero_idle_0{i}.png" for i in range(4)], 8, True),
                             "walk": (["hero_idle_02.png"], 8, True)})
        return "assets/art/characters/hero/hero_frames.tres"

    def test_lit_frames_repeated_pose_identical(self):
        g = self.g
        src = self.frames()
        before = g.read(src)
        g.run({"name": "town_lit", "frames": [src], "demo": False})
        self.assertEqual(g.read(src), before)                                   # the original is untouched
        nd = g.path("assets", "art", "lit", "town_lit", "hero_frames")
        maps = [read_bytes(os.path.join(nd, f"hero_idle_0{i}_normal.png")) for i in range(4)]
        self.assertEqual(maps[0], maps[1])
        self.assertEqual(maps[0], maps[3])
        self.assertNotEqual(maps[0], maps[2])
        n0 = np.array(Image.open(os.path.join(nd, "hero_idle_00_normal.png")))
        self.assertEqual(n0.shape, (32, 24, 3))
        self.assertEqual(n0.tobytes(), normals.normal_map(figure(seed=1), 3, 1.0).tobytes())   # the defaults
        lit = g.read("assets/art/lit/town_lit/hero_frames_lit.tres")
        self.assertIn("SpriteFrames", lit.splitlines()[0])
        # every frame is a CanvasTexture of the original diffuse and its own normal map
        cts = re.findall(r'\[sub_resource type="CanvasTexture" id="([^"]+)"\]\ndiffuse_texture = ExtResource\("([^"]+)"\)'
                         r'\nnormal_texture = ExtResource\("([^"]+)"\)', lit)
        self.assertEqual(len(cts), 5)          # one per frame texture: walk names frame 02 again, as its own resource
        ext = dict((i, p) for p, i in re.findall(r'\[ext_resource type="Texture2D" path="([^"]+)" id="([^"]+)"\]', lit))
        for sid, d, n in cts:
            stem = ext[d].rsplit("/", 1)[1][:-4]
            self.assertTrue(ext[d].startswith("res://assets/art/characters/hero/frames/"))
            self.assertEqual(ext[n], f"res://assets/art/lit/town_lit/hero_frames/{stem}_normal.png")
        body = lit.split("[resource]")[1]
        self.assertNotIn("ExtResource", body)                                   # frames point at the CanvasTextures
        self.assertEqual(body.count("SubResource(\"CanvasTexture_"), 5)
        first_use = lit.index('SubResource("CanvasTexture_')
        self.assertTrue(all(lit.index(f'id="{sid}"') < first_use for sid, _, _ in cts))
        steps = int(re.search(r"load_steps=(\d+)", lit).group(1))
        self.assertEqual(steps, 1 + lit.count("[ext_resource") + lit.count("[sub_resource"))
        # a re-run with nothing changed keeps the files
        stamp = os.path.getmtime(g.path("assets", "art", "lit", "town_lit", "hero_frames_lit.tres"))
        g.run({"name": "town_lit", "frames": [src], "demo": False})
        self.assertEqual(os.path.getmtime(g.path("assets", "art", "lit", "town_lit", "hero_frames_lit.tres")), stamp)

    def test_lit_tileset_copy(self):
        g = self.g
        base = np.zeros((16, 32, 4), np.uint8)
        base[:, :16] = (80, 140, 70, 255)
        base[:, 16:] = (90, 150, 60, 255)
        over = np.zeros((16, 32, 4), np.uint8)   # two overlay tiles, each clear on its left 4 px
        over[:, 4:16] = (130, 110, 80, 255)
        over[:, 20:32] = (130, 110, 80, 255)
        g.png("assets/art/tiles/t/base.png", base)
        g.png("assets/art/tiles/t/overlay.png", over)
        ts = g.path("assets", "art", "tiles", "t", "t_tileset.tres")
        godot.tileset_layers(ts, 16, [
            {"atlas_res": "res://assets/art/tiles/t/base.png",
             "tiles": [{"x": 0, "y": 0, "custom": "grass"}, {"x": 1, "y": 0, "probability": 0.5, "custom": "grass"}]},
            {"atlas_res": "res://assets/art/tiles/t/overlay.png",
             "tiles": [{"x": k, "y": 0, "terrain": 0, "peers": [0, -1, 0, -1, 0, -1, -1, -1], "custom": "dirt"}
                       for k in range(2)]}],
            [("dirt", (130, 110, 80))], custom="surface", overlays=(0,))
        before = g.read("assets/art/tiles/t/t_tileset.tres")
        g.run({"name": "ground_lit", "tilesets": ["res://assets/art/tiles/t/t_tileset.tres"], "tile_bevel": 3})
        self.assertEqual(g.read("assets/art/tiles/t/t_tileset.tres"), before)
        lit = g.read("assets/art/lit/ground_lit/t_tileset_lit.tres")
        # tile data, terrains, custom data and verify's metadata are copied line for line
        keep = [l for l in before.splitlines() if l and not l.startswith(("[gd_resource", "[ext_resource", "texture ="))]
        for l in keep:
            self.assertIn(l, lit.splitlines())
        self.assertEqual(lit.count('texture = SubResource("CanvasTexture_'), 2)
        self.assertFalse([l for l in lit.splitlines() if l.startswith("texture = ExtResource")])
        first_use = lit.index('texture = SubResource("CanvasTexture_')
        self.assertLess(lit.rindex('[sub_resource type="CanvasTexture"'), first_use)
        nb = np.array(Image.open(g.path("assets", "art", "lit", "ground_lit", "t_tileset", "base_normal.png")))
        no = np.array(Image.open(g.path("assets", "art", "lit", "ground_lit", "t_tileset", "overlay_normal.png")))
        self.assertEqual(nb.shape, (16, 32, 3))
        self.assertTrue((nb.reshape(-1, 3) == FLAT).all())          # opaque plain tiles: no rim at any tile border
        self.assertTrue((no[:, 4, 0] < 128).all() and (no[:, 20, 0] < 128).all())   # each overlay tile's real edge
        self.assertTrue((no[:, 10:16].reshape(-1, 3) == FLAT).all())  # ...and nothing where it meets the next tile

    def test_lit_prop_scene_and_demo(self):
        g = self.g
        a = TestOccluder().shape()
        png = g.png("assets/art/props/spr_lamp.png", a)
        bb = Image.fromarray(a).getbbox()
        godot.prop_scene(g.path("assets", "art", "props", "prop_lamp.tscn"), "res://assets/art/props/spr_lamp.png",
                         (32, 48), bb, node_name="Lamp", footprint="trunk")
        g.png("assets/art/props/spr_rock.png", square(16, 3, 13))           # no scene of its own
        src = self.frames()
        g.png("assets/art/tiles/t/base.png", np.dstack([np.full((16, 32, 3), 100, np.uint8),
                                                        np.full((16, 32), 255, np.uint8)]))
        godot.tileset_layers(g.path("assets", "art", "tiles", "t", "t_tileset.tres"), 16,
                             [{"atlas_res": "res://assets/art/tiles/t/base.png",
                               "tiles": [{"x": 0, "y": 0}, {"x": 1, "y": 0}]}], [])
        g.run({"name": "yard", "props": ["assets/art/props/spr_*.png"], "frames": [src],
               "tilesets": ["assets/art/tiles/t/t_tileset.tres"], "occluder": "full", "occluder_points": 10,
               "light_color": "#ff8800", "light_energy": 2, "light_height": 30, "ambient": "#202040"})
        out = g.path("assets", "art", "lit", "yard")
        scene = g.read("assets/art/lit/yard/props/spr_lamp_lit.tscn")
        self.assertIn('[node name="Lamp" type="StaticBody2D"]', scene)        # the prop's own scene, collision kept
        self.assertIn("CollisionShape2D", scene)
        self.assertIn('path="res://assets/art/lit/yard/props/spr_lamp_canvas.tres"', scene)
        self.assertIn('[node name="LightOccluder2D" type="LightOccluder2D" parent="."]', scene)
        off = [float(v) for v in re.search(r"offset = Vector2\(([-\d.]+), ([-\d.]+)\)", scene).groups()]
        poly = [float(v) for v in re.search(r"polygon = PackedVector2Array\(([^)]*)\)", scene).group(1).split(",")]
        pts = list(zip(poly[0::2], poly[1::2]))
        self.assertTrue(3 <= len(pts) <= 10)
        mask = a[..., 3] >= 128
        # back from node space to texture pixels (the Sprite2D is centred and offset): every corner on the silhouette
        tex = [(x + 16 - off[0], y + 24 - off[1]) for x, y in pts]
        self.assertTrue(all(float(x).is_integer() and float(y).is_integer() and touches(mask, int(x), int(y))
                            for x, y in tex), tex)
        canvas = g.read("assets/art/lit/yard/props/spr_lamp_canvas.tres")
        self.assertIn('[gd_resource type="CanvasTexture"', canvas)
        self.assertIn('path="res://assets/art/props/spr_lamp.png"', canvas)
        self.assertIn('path="res://assets/art/lit/yard/props/spr_lamp_normal.png"', canvas)
        rock = g.read("assets/art/lit/yard/props/spr_rock_lit.tscn")
        self.assertIn('type="Node2D"', rock)
        self.assertIn("LightOccluder2D", rock)
        demo = g.read("assets/art/lit/yard/yard_demo.tscn")
        for want in ('type="CanvasModulate"', "color = Color(0.125, 0.125, 0.251, 1)", 'type="PointLight2D"',
                     "shadow_enabled = true", "height = 30", "energy = 2", "color = Color(1, 0.533, 0, 1)",
                     'type="TileMapLayer"', 'type="AnimatedSprite2D"', "y_sort_enabled = true",
                     'path="res://assets/art/lit/yard/t_tileset_lit.tres"',
                     'path="res://assets/art/lit/yard/hero_frames_lit.tres"',
                     'path="res://assets/art/lit/yard/props/spr_lamp_lit.tscn"', 'type="GradientTexture2D"'):
            self.assertIn(want, demo)
        data = [int(v) for v in re.search(r"tile_map_data = PackedByteArray\(([^)]*)\)", demo).group(1).split(",")]
        raw = bytes(data)
        self.assertEqual(struct.unpack("<H", raw[:2])[0], 0)
        cells = [struct.unpack("<hhHHHH", raw[i:i + 12]) for i in range(2, len(raw), 12)]
        self.assertEqual(len(cells), 12 * 8)
        self.assertTrue(all(c[2] == 0 and (c[3], c[4]) in ((0, 0), (1, 0)) and c[5] == 0 for c in cells))
        self.assertTrue(os.path.isfile(g.path("assets_src", "art", "lit", "yard", "yard_review.png")))
        rows = [r["file"] for r in g.man.data["assets"]]
        self.assertIn("assets/art/lit/yard/yard_demo.tscn", rows)
        self.assertTrue(all(r.startswith("assets/art/lit/yard/") for r in rows))
        self.assertTrue(os.path.isdir(out))

    def test_godot_saved_scene_with_uids(self):
        # Godot 4.7 writes uids into headers and ext_resources and unique_ids into nodes: the copy must drop the
        # header uid (two files, one uid) and the uid of the swapped texture (Godot loads by uid before path)
        g = self.g
        g.png("assets/art/props/spr_pot.png", square(16, 3, 13))
        scene = g.path("assets", "art", "props", "prop_pot.tscn")
        lines = ['[gd_scene format=3 uid="uid://bscene0001"]', "",
                 '[ext_resource type="Texture2D" uid="uid://btex00001" path="res://assets/art/props/spr_pot.png" '
                 'id="1_ab12c"]', "",
                 '[node name="Pot" type="Node2D" unique_id=1234]', "",
                 '[node name="Sprite2D" type="Sprite2D" parent="." unique_id=5678]',
                 'texture = ExtResource("1_ab12c")', "offset = Vector2(0, -6.5)", ""]
        with open(scene, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        g.run({"name": "pots", "props": ["assets/art/props/spr_pot.png"], "demo": False})
        lit = g.read("assets/art/lit/pots/props/spr_pot_lit.tscn")
        self.assertNotIn("uid://", lit)
        self.assertEqual(lit.splitlines()[0], "[gd_scene format=3]")              # no load_steps invented either
        self.assertIn('[ext_resource type="Texture2D" path="res://assets/art/lit/pots/props/spr_pot_canvas.tres" '
                      'id="1_ab12c"]', lit)
        self.assertIn("unique_id=5678", lit)
        poly = [float(v) for v in re.search(r"polygon = PackedVector2Array\(([^)]*)\)", lit).group(1).split(",")]
        # base corners in node space: texture y - 8 (centred, 16 px) - 6.5 (offset); the square ends at row 13
        self.assertEqual(max(poly[1::2]), 13 - 8 - 6.5)

    def test_spec_paths_stay_in_the_game(self):
        g = self.g
        g.png("assets/art/props/spr_a.png", square())
        for bad in ("../outside/*.png", "/etc/x.png", "C:/x.png", "\\\\host\\share\\x.png"):
            with self.assertRaises(fcore.ToolError):
                g.run({"name": "x", "props": [bad]})
        with self.assertRaises(fcore.ToolError):              # a pattern that matches nothing says so
            g.run({"name": "x", "props": ["assets/art/props/nothing_*.png"]})
        with self.assertRaises(fcore.ToolError):
            g.run({"name": "x", "props": ["assets/art/props/spr_a.png"], "occluder": "half"})
        with self.assertRaises(fcore.ToolError):
            g.run({"name": "x", "props": ["assets/art/props/spr_a.png"], "light_color": "orange"})


# ---- the hooks in shared files -----------------------------------------------------------
class TestHooks(unittest.TestCase):
    def test_dotwork_registers_the_lane(self):
        import dotwork   # no need(): this checks the shared file itself, lane or not
        self.assertIn("lighting", dotwork.LANES)
        self.assertIn("lighting", getattr(dotwork, "LATE", ()))   # runs after the lanes whose output it reads
        keys = dotwork.entry_keys("lighting")
        for k in ("frames", "tilesets", "props", "bevel", "tile_bevel", "detail", "occluder", "light_color",
                  "light_energy", "light_height", "light_range", "ambient", "demo"):
            self.assertIn(k, keys)

    def test_verify_loader_checks_lit_resources(self):
        import verify
        src = verify.LOADER
        for want in ("r is CanvasTexture", "_lit_frames(r)", "_lit_sources(r)", "_lit_scene(n)", "LightOccluder2D",
                     "PointLight2D", "get_cell_tile_data", "normal_texture.get_size()", "_normal_bad",
                     # the older resource kinds still print exactly the lines they printed before
                     '"" if lf[0] == 0 else', 'if lit[0] != "":'):
            self.assertTrue(want in src, f"verify.LOADER lacks {want!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
