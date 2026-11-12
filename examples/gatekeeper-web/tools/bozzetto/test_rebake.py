#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_rebake.py
# Purpose : The exam for the UV rebake (#293, #203): make's --rebake and --accept-uv, `bozzetto.py rebake <name>`,
#           the waiver on the asset log row, and (part 2) tools/blender/rebake_uvs.py on a real mesh.
# Usage   : python tools/bozzetto/test_rebake.py
#           BOZZETTO_TEST_BLENDER=skip|bpy|<path to blender>  picks part 2's Blender (skip: part 1 only)
# Exit    : 0 all cases pass, 1 a case failed
# Notes   : Part 1 (standard library): a stand-in Blender records what make hands cleanup.py and plays the
#           validator's verdicts; a stand-in Tripo API (test_tripo's) serves `make --with tripo`, where the rebake is
#           on by default. Part 2 (when Blender or the bpy module is found): a cube whose 96 faces are each a tiny
#           UV island in the quadrant of a four-colour texture that matches the face's direction, plus a constant
#           metallic-roughness map and a flat normal map. The old cleanup.py leaves it at 1% coverage (the prop floor
#           is 50%, so the validator fails it, and the old code has no --rebake: exit 2); after the rebake the
#           coverage is over the floor, the triangle count is unchanged, every face still reads its quadrant's colour
#           from the new texture, the normal map is still flat and the metallic-roughness constants survive.
# Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bozzetto as bz  # noqa: E402
import cleanup  # noqa: E402  (its argument parser needs no bpy)
import rebake  # noqa: E402
import test_bozzetto as tb  # noqa: E402
import test_tripo as tt  # noqa: E402

cl = bz.cl
UV_FAIL = "prop_crate: UV coverage 29% is under 50% (tiny islands waste texture space)"
SIZE_FAIL = "prop_crate: largest side 5.00 m is over 3.0 m (wrong units? 1 unit = 1 m)"
REBAKE_REPORT = {"texture_px": 2048, "uv_coverage_before": 0.294, "uv_islands_before": 6805,
                 "uv_coverage_after": 0.46, "uv_islands_after": 3120,
                 "maps": [{"source": "Color", "kind": "transfer", "alpha": False},
                          {"source": "Normal", "kind": "normal", "alpha": False}],
                 "bake": {"samples": 4, "margin_px": 4, "island_gap_px": 2, "uv_angle_deg": 66.0},
                 "check": {"views": 4, "pixels": 35000, "mean_levels": 0.26, "max_levels": 55.0},
                 "check_lit": {"views": 4, "pixels": 35000, "mean_levels": 1.15, "max_levels": 60.0}, "seconds": 16.0}


class Fake(tb.FakeBlender):
    """test_bozzetto's stand-in Blender, plus: the validator's failure lines are chosen here, cleanup.json carries a
    rebake entry when cleanup was asked for one, and rebake_uvs.py is played too."""

    def __init__(self):
        super().__init__()
        self.failures = [SIZE_FAIL]
        self.rebake_report = REBAKE_REPORT

    def __call__(self, blender, script, argv, what):
        argv = [str(a) for a in argv]
        name = Path(script).name
        if name == "validate_asset.py":
            self.calls.append((name, argv))
            report = {"asset": str(Path(argv[0]).resolve()), "total_tris": 2600, "objects": [],
                      "failures": list(self.failures) if self.validate_rc else [], "warnings": [], "notes": []}
            Path(argv[argv.index("--json") + 1]).write_text(json.dumps(report), encoding="utf-8")
            return self.validate_rc, ""
        if name == "rebake_uvs.py":
            self.calls.append((name, argv))
            Path(argv[argv.index("--out") + 1]).write_bytes(Path(argv[0]).read_bytes())
            Path(argv[argv.index("--json") + 1]).write_text(json.dumps(dict(self.rebake_report, tris=2600)),
                                                              encoding="utf-8")
            return 0, ""
        rc, out = super().__call__(blender, script, argv, what)
        if name == "cleanup.py":
            rep_path = Path(argv[argv.index("--json") + 1])
            rep = json.loads(rep_path.read_text(encoding="utf-8"))
            rep["rebake"] = dict(self.rebake_report) if "--rebake" in argv else None
            rep_path.write_text(json.dumps(rep), encoding="utf-8")
        return rc, out


class TripoBase(tt.Base):
    def setUp(self):
        super().setUp()
        self.fake = Fake()
        bz.run_bpy = self.fake


class LocalBase(tb.Base):
    def setUp(self):
        super().setUp()
        self.fake = Fake()
        bz.run_bpy = self.fake

    def cleanup_argv(self):
        return [a for s, a in self.fake.calls if s == "cleanup.py"][-1]

    def record(self, name="prop_crate"):
        return json.loads((self.root / "assets_src" / "bozzetto" / name / "bozzetto.json").read_text(encoding="utf-8"))

    def row(self, path):
        return [l for l in (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8").splitlines()
                if f"`{path}`" in l][0]

    def evidence(self, path):
        aid = self.row(path).split("|")[1].strip()
        return (self.root / "docs" / "licenses" / f"{aid}.txt").read_text(encoding="utf-8")


# ---- part 1: the routes' defaults -----------------------------------------------------------------------------------
class RouteDefaults(TripoBase):
    def test_tripo_rebakes_by_default_at_the_class_texture_size(self):
        rc, out = self.make("--image", "art_src/crate.png", "--class", "hero")
        self.assertEqual(rc, 0, out)
        argv = self.cleanup_argv()
        self.assertIn("--rebake", argv)
        self.assertEqual(argv[argv.index("--texture") + 1], "2048", "the hero class texture")
        self.assertTrue(self.record()["rebake"])
        self.assertIn("UV rebaked 29% -> 46% at 2048 px", self.row("assets/models/prop_crate.glb"))
        self.nothing_secret_written()

    def test_no_rebake_keeps_the_vendor_atlas(self):
        rc, out = self.make("--image", "art_src/crate.png", "--no-rebake")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("--rebake", self.cleanup_argv())
        self.assertFalse(self.record()["rebake"])
        self.assertNotIn("UV rebaked", self.row("assets/models/prop_crate.glb"))

    def test_texture_override_reaches_the_rebake(self):
        rc, out = self.make("--image", "art_src/crate.png", "--texture", "512")
        self.assertEqual(rc, 0, out)
        argv = self.cleanup_argv()
        self.assertEqual(argv[argv.index("--texture") + 1], "512")


class LocalDefaults(LocalBase):
    def test_local_route_is_opt_in(self):
        rc, out = self.make()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("--rebake", self.cleanup_argv())
        self.assertFalse(self.record()["rebake"])
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "7", "--rebake", "--overwrite")
        self.assertEqual(rc, 0, out)
        argv = self.cleanup_argv()
        self.assertIn("--rebake", argv)
        self.assertEqual(argv[argv.index("--texture") + 1], "1024", "the prop class texture")
        self.assertTrue(self.record()["rebake"])
        self.assertIn("Rebake   : UV coverage 29% (6805 islands) -> 46% (3120 islands), texture 2048 px",
                      self.evidence("assets/models/prop_crate.glb"))

    def test_rebake_with_vertex_colours_is_refused_before_any_job(self):
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "7", "--rebake", "--material", "vertex")
        self.assertEqual(rc, 2, out)
        self.assertIn("nothing to bake", out)
        self.assertEqual(self.fake.calls, [])


# ---- part 1: the waiver ---------------------------------------------------------------------------------------------
class Waiver(LocalBase):
    def test_uv_coverage_alone_needs_accept_uv_and_is_logged(self):
        self.fake.validate_rc, self.fake.failures = 1, [UV_FAIL]
        rc, out = self.make()
        self.assertEqual(rc, 1, out)
        self.assertIn("--accept-uv", out, "the failure names the way through")
        self.assertFalse((self.root / "assets" / "models").exists())
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "7", "--accept-uv")
        self.assertEqual(rc, 0, out)
        self.assertIn("UV coverage waived: 29% under the prop floor 50% (--accept-uv)", out)
        self.assertTrue((self.root / "assets" / "models" / "prop_crate.glb").is_file())
        row = self.row("assets/models/prop_crate.glb")
        self.assertIn("UV coverage waived: 29% under the prop floor 50% (--accept-uv)", row)
        self.assertIn("Waiver   : UV coverage waived: 29% under the prop floor 50% (--accept-uv)",
                      self.evidence("assets/models/prop_crate.glb"))
        rec = self.record()
        self.assertTrue(rec["accept_uv"])
        self.assertEqual(rec["validation"]["failures"], [])
        self.assertEqual(rec["validation"]["waived"], [UV_FAIL])
        val = json.loads((self.root / "assets_src/bozzetto/prop_crate/validate.json").read_text(encoding="utf-8"))
        self.assertEqual(val["waived"], [UV_FAIL])

    def test_accept_uv_waives_nothing_else(self):
        self.fake.validate_rc, self.fake.failures = 1, [UV_FAIL, SIZE_FAIL]
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "7", "--accept-uv")
        self.assertEqual(rc, 1, out)
        self.assertIn("over 3.0 m", out)
        self.assertNotIn("--accept-uv ships", out)
        self.assertFalse((self.root / "assets" / "models").exists())

    def test_waive_uv_is_a_pure_function(self):
        v = {"failures": [UV_FAIL]}
        self.assertTrue(rebake.waive_uv(v))
        self.assertEqual((v["failures"], v["waived"]), ([], [UV_FAIL]))
        v = {"failures": [UV_FAIL, SIZE_FAIL]}
        self.assertFalse(rebake.waive_uv(v))
        self.assertEqual(v["failures"], [UV_FAIL, SIZE_FAIL])
        self.assertFalse(rebake.waive_uv({"failures": []}))
        self.assertEqual(rebake.hint({"failures": [SIZE_FAIL]}), "")
        self.assertIn("--accept-uv", rebake.hint({"failures": [UV_FAIL]}))


# ---- part 1: the subcommand -----------------------------------------------------------------------------------------
class Subcommand(LocalBase):
    def placed(self):
        rc, out = self.make()
        self.assertEqual(rc, 0, out)
        self.fake.calls.clear()
        return self.root / "assets" / "models" / "prop_crate.glb"

    def test_rebake_a_placed_model_in_place(self):
        dst = self.placed()
        before = dst.read_bytes()
        rc, out = self.run_tool("rebake", "prop_crate", "--no-preview", url=False)
        self.assertEqual(rc, 0, out)
        scripts = [s for s, _ in self.fake.calls]
        self.assertEqual(scripts, ["rebake_uvs.py", "prep_export.py", "validate_asset.py"])
        argv = self.fake.calls[0][1]
        self.assertEqual(argv[argv.index("--texture") + 1], "1024", "the make record's texture size")
        self.assertIn("--overwrite", argv)
        self.assertEqual(self.fake.calls[1][1][self.fake.calls[1][1].index("--class") + 1], "prop")
        work = self.root / "assets_src" / "bozzetto" / "prop_crate" / "rebake"
        self.assertEqual((work / "before_rebake.glb").read_bytes(), before)
        self.assertTrue(dst.is_file())
        rec = json.loads((work / "rebake_record.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["output"], "assets/models/prop_crate.glb")
        self.assertEqual(rec["output_sha256"], bz.sha256_bytes(dst.read_bytes()))
        made = self.record()
        self.assertEqual(made["rebake"]["report"]["uv_coverage_after"], 0.46)
        self.assertEqual(made["files"][0]["sha256"], rec["output_sha256"])
        row = self.row("assets/models/prop_crate.glb")
        self.assertIn("rebaked: UV 29% -> 46% at 2048 px, record `assets_src/bozzetto/prop_crate/rebake/rebake_record.json`", row)
        self.assertIn("Rebake   : ", self.evidence("assets/models/prop_crate.glb"))
        self.assertIn("UV coverage 29% (6805 islands) -> 46% (3120 islands)", out)
        # a re-run starts from the backup, not from the rebaked file, and notes once
        self.fake.calls.clear()
        rc, out = self.run_tool("rebake", "prop_crate", "--no-preview", "--texture", "512", url=False)
        self.assertEqual(rc, 0, out)
        self.assertIn("a re-run replaces the bake", out)
        self.assertEqual(Path(self.fake.calls[0][1][0]).name, "before_rebake.glb")
        self.assertEqual(self.row("assets/models/prop_crate.glb").count("rebaked: "), 1)
        self.no_local_paths()

    def test_no_replace_and_a_failed_budget_leave_the_model_alone(self):
        dst = self.placed()
        before = dst.read_bytes()
        rc, out = self.run_tool("rebake", "prop_crate", "--no-replace", "--no-preview", url=False)
        self.assertEqual(rc, 0, out)
        self.assertIn("--no-replace", out)
        self.assertEqual(dst.read_bytes(), before)
        self.assertTrue((self.root / "assets_src/bozzetto/prop_crate/rebake/export/prop_crate.glb").is_file())
        self.assertNotIn("rebaked: ", self.row("assets/models/prop_crate.glb"))
        self.fake.validate_rc, self.fake.failures = 1, [UV_FAIL]
        rc, out = self.run_tool("rebake", "prop_crate", "--no-preview", url=False)
        self.assertEqual(rc, 1, out)
        self.assertIn("--accept-uv", out)
        self.assertEqual(dst.read_bytes(), before)
        rc, out = self.run_tool("rebake", "prop_crate", "--no-preview", "--accept-uv", url=False)
        self.assertEqual(rc, 0, out)
        self.assertIn("UV coverage waived: 29% under the prop floor 50% (--accept-uv)",
                      self.row("assets/models/prop_crate.glb"))
        self.assertIn("Waiver   : UV coverage waived", self.evidence("assets/models/prop_crate.glb"))

    def test_any_glb_with_input_and_the_usage_errors(self):
        (self.root / "statue.glb").write_bytes(tb.canned_glb(8, 4))
        rc, out = self.run_tool("rebake", "statue", "--input", "statue.glb", "--class", "prop", "--no-preview",
                                "--no-log", url=False)
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "assets_src/bozzetto/statue/rebake/before_rebake.glb").is_file())
        self.assertNotIn("--texture", self.fake.calls[0][1], "no record, no size: the largest source image")
        rc, out = self.run_tool("rebake", "prop_missing", "--no-preview", url=False)
        self.assertEqual(rc, 2, out)
        self.assertIn("not found", out)
        rc, out = self.run_tool("rebake", "prop_crate", "--texture", "300", url=False)
        self.assertEqual(rc, 2)
        with self.assertRaises(SystemExit):
            cleanup.parse_args(["raw.glb", "--out", "c.glb", "--texture", "2048"])   # --texture needs --rebake
        with self.assertRaises(SystemExit):
            cleanup.parse_args(["raw.glb", "--out", "c.glb", "--rebake", "--texture", "300"])
        self.assertTrue(cleanup.parse_args(["raw.glb", "--out", "c.glb", "--rebake", "--texture", "2048"]).rebake)

    def test_list_and_help_name_the_step(self):
        rc, out = self.run_tool("list", url=False)
        self.assertEqual(rc, 0)
        self.assertIn("rebake", out)
        rc, out = self.run_tool("make", "-h", url=False)
        self.assertIn("--accept-uv", out)
        self.assertIn("--no-rebake", out)


# ---- part 2: the real rebake_uvs.py ---------------------------------------------------------------------------------
END = textwrap.dedent('''
    if not bpy.app.binary_path and sys.platform == "win32":
        # the bpy module crashes while the process ends on Windows (rig_chain.py says more): end it here
        import ctypes
        sys.stdout.flush()
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k.TerminateProcess(k.GetCurrentProcess(), 0)
''')

# the fixture: a cube of 96 quads, each its own 0.01-wide UV island inside the quadrant of a four-colour texture
# chosen by the face's direction (coverage about 1%), with a constant metallic-roughness map and a flat normal map
BUILD = textwrap.dedent('''
    import sys, bpy, bmesh
    sys.path.insert(0, sys.argv[-1])
    import prep_export as pe
    ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    out_dir = ARGV[0]
    QUAD = {"+X": (0, 0), "-X": (0, 0), "+Y": (1, 0), "-Y": (1, 0), "+Z": (0, 1), "-Z": (1, 1)}
    COLOURS = {(0, 0): (0.8, 0.1, 0.1), (1, 0): (0.1, 0.7, 0.1), (0, 1): (0.1, 0.2, 0.9), (1, 1): (0.9, 0.8, 0.1)}

    def direction(n):
        axis = max(range(3), key=lambda i: abs(n[i]))
        return ("+" if n[axis] > 0 else "-") + "XYZ"[axis]

    def image(name, px, data, fill):
        img = bpy.data.images.new(name, px, px, alpha=False, is_data=data)
        img.colorspace_settings.name = "Non-Color" if data else "sRGB"
        buf = [0.0] * (px * px * 4)
        for i in range(px * px):
            c = fill(i % px, i // px)
            buf[4 * i:4 * i + 4] = [c[0], c[1], c[2], 1.0]
        img.pixels.foreach_set(buf)
        img.pack()
        return img

    def build(n_cubes, path):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        objs = []
        for k in range(n_cubes):
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(k * 1.5, 0, 0.5))
            obj = bpy.context.active_object
            obj.name = f"prop_cube{k}"
            bm = bmesh.new(); bm.from_mesh(obj.data)
            bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=3, use_grid_fill=True)
            bm.faces.ensure_lookup_table()
            uv = bm.loops.layers.uv.verify()
            for i, f in enumerate(bm.faces):
                qx, qy = QUAD[direction(f.normal)]
                ox, oy = qx * 0.5 + 0.05 + (i % 8) * 0.05, qy * 0.5 + 0.05 + ((i // 8) % 8) * 0.05
                for j, l in enumerate(f.loops):
                    cx, cy = [(0, 0), (1, 0), (1, 1), (0, 1)][j % 4]
                    l[uv].uv = (ox + cx * 0.01, oy + cy * 0.01)
            bm.to_mesh(obj.data); bm.free()
            objs.append(obj)
        px = 256
        base = image("fixture_base", px, False, lambda x, y: COLOURS[(x // (px // 2), y // (px // 2))])
        orm = image("fixture_orm", px, True, lambda x, y: (1.0, 0.6, 0.2))
        nrm = image("fixture_normal", px, True, lambda x, y: (0.5, 0.5, 1.0))
        mat = bpy.data.materials.new("fixture_mat"); mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = nodes["Principled BSDF"]
        tb = nodes.new("ShaderNodeTexImage"); tb.image = base; links.new(tb.outputs["Color"], bsdf.inputs["Base Color"])
        to = nodes.new("ShaderNodeTexImage"); to.image = orm
        sep = nodes.new("ShaderNodeSeparateColor"); links.new(to.outputs["Color"], sep.inputs["Color"])
        links.new(sep.outputs["Green"], bsdf.inputs["Roughness"]); links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
        tn = nodes.new("ShaderNodeTexImage"); tn.image = nrm
        nm = nodes.new("ShaderNodeNormalMap"); links.new(tn.outputs["Color"], nm.inputs["Color"]); links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
        for obj in objs:
            obj.data.materials.append(mat)
        bpy.ops.export_scene.gltf(filepath=path, **pe.GLTF_PRESET)
        print("BUILT", path, flush=True)

    build(1, out_dir + "/fixture.glb")
    build(2, out_dir + "/two.glb")
''')

# the probe: every face's colour from the base image at its UV centre against the quadrant its direction names;
# the normal and metallic-roughness maps sampled there too
PROBE = textwrap.dedent('''
    import sys, json, bpy
    import numpy as np
    ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    QUAD = {"+X": (0, 0), "-X": (0, 0), "+Y": (1, 0), "-Y": (1, 0), "+Z": (0, 1), "-Z": (1, 1)}
    COLOURS = {(0, 0): (0.8, 0.1, 0.1), (1, 0): (0.1, 0.7, 0.1), (0, 1): (0.1, 0.2, 0.9), (1, 1): (0.9, 0.8, 0.1)}
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=ARGV[0])
    obj = [o for o in bpy.context.scene.objects if o.type == "MESH"][0]
    mesh = obj.data
    mesh.calc_loop_triangles()
    mat = obj.material_slots[0].material
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    def image_of(sock):
        n = sock.links[0].from_node
        while n.type != "TEX_IMAGE":   # through Separate Color or Normal Map: the first linked input
            n = next(i.links[0].from_node for i in n.inputs if i.is_linked)
        return n.image
    def pixels(img):
        w, h = img.size
        px = np.empty(w * h * 4, dtype=np.float32); img.pixels.foreach_get(px)
        return px.reshape(h, w, 4), w, h
    base, bw, bh = pixels(image_of(bsdf.inputs["Base Color"]))
    orm, ow, oh = pixels(image_of(bsdf.inputs["Roughness"]))
    nrm, nw, nh = pixels(image_of(bsdf.inputs["Normal"]))
    uv = mesh.uv_layers.active.data
    bad, orm_err, nrm_err, n = 0, 0.0, 0.0, 0
    for p in mesh.polygons:
        u = sum(uv[l].uv[0] for l in p.loop_indices) / len(p.loop_indices)
        v = sum(uv[l].uv[1] for l in p.loop_indices) / len(p.loop_indices)
        nn = obj.matrix_world.to_3x3() @ p.normal
        axis = max(range(3), key=lambda i: abs(nn[i]))
        want = np.array(COLOURS[QUAD[("+" if nn[axis] > 0 else "-") + "XYZ"[axis]]])
        got = base[min(bh - 1, int(v * bh)), min(bw - 1, int(u * bw)), :3]
        # a byte image's pixels are its stored values, as the fixture wrote them and as the bake writes them back
        if np.abs(want - got).max() > 0.12:
            bad += 1
        orm_err = max(orm_err, float(np.abs(orm[min(oh - 1, int(v * oh)), min(ow - 1, int(u * ow)), :3] - (1.0, 0.6, 0.2)).max()))
        nrm_err = max(nrm_err, float(np.abs(nrm[min(nh - 1, int(v * nh)), min(nw - 1, int(u * nw)), :3] - (0.5, 0.5, 1.0)).max()))
        n += 1
    print("PROBE" + json.dumps({"faces": n, "bad": bad, "orm_err": orm_err, "normal_err": nrm_err,
                                "images": len([i for i in bpy.data.images if i.type == "IMAGE" and i.name != "Render Result"]),
                                "uv_layers": len(mesh.uv_layers), "base_px": [bw, bh]}), flush=True)
''')

BLENDER = tb.part2_blender()


def blender_run(script, argv, timeout=900):
    kind, path = BLENDER
    cmd = ([path, "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(script), "--"] if kind == "blender"
           else [path, str(script)]) + [str(a) for a in argv]
    return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)


@unittest.skipIf(BLENDER is None, "no Blender or bpy module found (part 2 skipped)")
class RealRebake(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="bz_rebake_bpy_")
        cls.d = Path(cls.tmp.name)
        (cls.d / "build.py").write_text(BUILD + END, encoding="utf-8")
        (cls.d / "probe.py").write_text(PROBE + END, encoding="utf-8")
        p = blender_run(cls.d / "build.py", [cls.d, str(bz.TOOLS / "blender")])
        assert p.returncode == 0 and p.stdout.count("BUILT") == 2, p.stdout[-2000:] + p.stderr[-2000:]
        cls.fixture = cls.d / "fixture.glb"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def probe(self, path):
        q = blender_run(self.d / "probe.py", [path])
        line = next((l for l in q.stdout.splitlines() if l.startswith("PROBE")), None)
        self.assertIsNotNone(line, q.stdout[-3000:] + q.stderr[-2000:])
        return json.loads(line[5:])

    def validate(self, path):
        rep = self.d / (path.stem + "_validate.json")
        rc, out = bz.run_bpy(BLENDER, bz.TOOLS / "blender" / "validate_asset.py",
                             [path, "--class", "prop", "--json", rep], "validate")
        return rc, json.loads(rep.read_text(encoding="utf-8")), out

    def test_cleanup_rebake_lifts_the_fixture_over_the_floor_and_keeps_its_look(self):
        # without the rebake: the fixture's own atlas fails the prop floor (and the old cleanup.py had no --rebake)
        old = self.d / "old.glb"
        rc, out = bz.run_bpy(BLENDER, HERE / "cleanup.py", [self.fixture, "--out", old, "--height", "1", "--json",
                                                            self.d / "old.json"], "cleanup")
        self.assertEqual(rc, 0, out)
        rc, val, out = self.validate(old)
        self.assertEqual(rc, 1, out)
        self.assertTrue(any("UV coverage" in f for f in val["failures"]), val["failures"])
        self.assertLess(val["objects"][0]["uv_coverage"], 0.1)
        before = self.probe(old)
        self.assertEqual(before["bad"], 0, "the fixture reads its quadrant colours before the rebake")
        # with it
        new = self.d / "new.glb"
        rc, out = bz.run_bpy(BLENDER, HERE / "cleanup.py", [self.fixture, "--out", new, "--height", "1", "--rebake",
                                                            "--texture", "256", "--json", self.d / "new.json"], "cleanup")
        self.assertEqual(rc, 0, out)
        rep = json.loads((self.d / "new.json").read_text(encoding="utf-8"))
        rb = rep["rebake"]
        self.assertEqual(rep["tris_out"], rep["tris_in"], "the rebake changes no geometry")
        self.assertEqual(rep["tris_in"], 96 * 2)
        self.assertLess(rb["uv_coverage_before"], 0.1)
        self.assertGreaterEqual(rb["uv_coverage_after"], 0.5, "over the prop floor")
        self.assertLessEqual(rb["uv_islands_after"], 12, "a cube unwraps to a few islands, not 96")
        self.assertEqual(rb["texture_px"], 256)
        self.assertEqual(sorted(m["kind"] for m in rb["maps"]), ["normal", "transfer", "transfer"])
        self.assertLessEqual(rb["check"]["mean_levels"], 4.0, rb["check"])
        self.assertLessEqual(rb["check_lit"]["mean_levels"], 8.0, rb["check_lit"])
        self.assertEqual(rb["bake"]["normal_space"], "TANGENT")
        rc, val, out = self.validate(new)
        self.assertEqual(rc, 0, out)
        self.assertEqual(val["failures"], [])
        after = self.probe(new)
        self.assertEqual(after["faces"], 192, "glTF stores the 96 quads as triangles")
        self.assertLessEqual(after["bad"], 2, f"faces reading the wrong quadrant after the rebake: {after}")
        self.assertLess(after["orm_err"], 0.03, "metallic-roughness constants survive the transfer")
        self.assertLess(after["normal_err"], 0.06, "a flat normal map stays flat in the new tangent space")
        self.assertEqual(after["images"], 3)
        self.assertEqual(after["uv_layers"], 1, "the vendor layer does not ship")
        self.assertEqual(after["base_px"], [256, 256])
        doc = cl.read_glb(new.read_bytes())[0]
        self.assertNotIn("TEXCOORD_1", doc["meshes"][0]["primitives"][0]["attributes"])

    def test_standalone_script_and_its_usage_errors(self):
        out = self.d / "standalone.glb"
        rc, text = bz.run_bpy(BLENDER, bz.TOOLS / "blender" / "rebake_uvs.py",
                              [self.fixture, "--out", out, "--json", self.d / "standalone.json"], "rebake")
        self.assertEqual(rc, 0, text)
        rep = json.loads((self.d / "standalone.json").read_text(encoding="utf-8"))
        self.assertEqual(rep["tris"], 192)
        self.assertEqual(rep["texture_px"], 256, "the largest source image, when --texture is not given")
        self.assertGreaterEqual(rep["uv_coverage_after"], 0.5)
        self.assertLessEqual(self.probe(out)["bad"], 2)
        rc, text = bz.run_bpy(BLENDER, bz.TOOLS / "blender" / "rebake_uvs.py", [self.fixture, "--out", out], "rebake")
        self.assertEqual(rc, 2, "an existing --out needs --overwrite")
        rc, text = bz.run_bpy(BLENDER, bz.TOOLS / "blender" / "rebake_uvs.py",
                              [self.d / "two.glb", "--out", self.d / "two_out.glb"], "rebake")
        self.assertEqual(rc, 2, "two meshes need --join")
        self.assertIn("--join", text)
        rc, text = bz.run_bpy(BLENDER, bz.TOOLS / "blender" / "rebake_uvs.py",
                              [self.d / "two.glb", "--out", self.d / "two_out.glb", "--join", "--no-check"], "rebake")
        self.assertEqual(rc, 0, text)

    def test_the_subcommand_on_a_real_model(self):
        root = self.d / "game"
        (root / "docs" / "licenses").mkdir(parents=True)
        (root / "docs" / "ASSET_LOG.md").write_text(tb.LOG, encoding="utf-8")
        models = root / "assets" / "models"
        models.mkdir(parents=True)
        (models / "prop_cube.glb").write_bytes(self.fixture.read_bytes())
        saved = (bz.find_blender, os.getcwd())
        bz.find_blender = lambda choice=None: BLENDER
        os.chdir(root)
        try:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = bz.main(["rebake", "prop_cube", "--class", "prop", "--no-preview", "--texture", "256"])
            text = out.getvalue() + err.getvalue()
        finally:
            bz.find_blender, cwd = saved
            os.chdir(cwd)
        self.assertEqual(rc, 0, text)
        self.assertIn("no row in", text, "a model without a row gets no note")
        self.assertNotEqual((models / "prop_cube.glb").read_bytes(), self.fixture.read_bytes())
        work = root / "assets_src" / "bozzetto" / "prop_cube" / "rebake"
        self.assertEqual((work / "before_rebake.glb").read_bytes(), self.fixture.read_bytes())
        rec = json.loads((work / "rebake_record.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(rec["report"]["uv_coverage_after"], 0.5)
        self.assertEqual(rec["validation"]["failures"], [])
        self.assertLessEqual(self.probe(models / "prop_cube.glb")["bad"], 2)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    print(f"[info] part 2 Blender: {BLENDER[0] + ' ' + Path(BLENDER[1]).name if BLENDER else 'none (skipped)'}")
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)
