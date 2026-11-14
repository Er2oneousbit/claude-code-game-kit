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
#           #203: the local route's --rebake auto hands cleanup.py the class floor (--rebake-under) and rebakes only
#           under it; part 2 runs it on the fixture (rebaked) and on the rebaked model (kept as it is).
#           #303: the fixture again with a speckled colour map and the metallic-roughness map packed as JPEG (as
#           Tripo's come; its normal map is PNG): the rebaked colour map is JPEG at prep_export.JPEG_QUALITY, the
#           normal and metallic-roughness maps PNG, the file smaller than with --png, and the colour map still JPEG
#           in prep_export's main file and LOD; the PNG fixture stays PNG.
# Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): --rebake auto and --rebake-under (#203)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): a JPEG colour map stays JPEG, --png (#303)
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
        self.own_coverage = 0.66      # what cleanup.py --rebake-under measures on the model's own atlas

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
            if "--rebake-under" in argv:   # as cleanup.py does: the rebake only under the floor
                floor = float(argv[argv.index("--rebake-under") + 1])
                ran = self.own_coverage < floor
                rep["rebake_auto"] = {"floor": floor, "coverage": self.own_coverage, "ran": ran}
                rep["rebake"] = dict(self.rebake_report) if ran else None
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

    def test_rebake_png_reaches_cleanup(self):
        """#303: make --rebake-png hands cleanup.py --rebake-png (every baked map PNG); without it nothing extra."""
        rc, out = self.make("--image", "art_src/crate.png")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("--rebake-png", self.cleanup_argv())
        rc, out = self.make("--image", "art_src/crate.png", "--rebake-png", "--overwrite")
        self.assertEqual(rc, 0, out)
        self.assertIn("--rebake-png", self.cleanup_argv())
        self.assertTrue(cleanup.parse_args(["raw.glb", "--out", "c.glb", "--rebake", "--rebake-png"]).rebake_png)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cleanup.parse_args(["raw.glb", "--out", "c.glb", "--rebake-png"])   # nothing to bake without --rebake

    def test_texture_override_reaches_the_rebake(self):
        rc, out = self.make("--image", "art_src/crate.png", "--texture", "512")
        self.assertEqual(rc, 0, out)
        argv = self.cleanup_argv()
        self.assertEqual(argv[argv.index("--texture") + 1], "512")


class LocalDefaults(LocalBase):
    def test_local_route_rebakes_only_under_the_class_floor(self):
        """#203: the local route's default is --rebake auto: cleanup.py gets the class floor and rebakes only a model
        under it (TRELLIS.2 characters at 51 and 53% of the npc floor's 55%); one over it keeps its own atlas."""
        rc, out = self.make()
        self.assertEqual(rc, 0, out)
        argv = self.cleanup_argv()
        self.assertNotIn("--rebake", argv)
        self.assertEqual(argv[argv.index("--rebake-under") + 1], "0.5", "the prop floor")
        self.assertEqual(argv[argv.index("--texture") + 1], "1024", "the prop class texture")
        self.assertFalse(self.record()["rebake"], "66% meets the floor: no rebake")
        self.assertEqual(self.record()["rebake_mode"], "auto")
        self.assertNotIn("UV rebaked", self.row("assets/models/prop_crate.glb"))
        self.fake.own_coverage = 0.51
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "7", "--class", "npc", "--overwrite")
        self.assertEqual(rc, 0, out)
        argv = self.cleanup_argv()
        self.assertEqual(argv[argv.index("--rebake-under") + 1], "0.55", "the npc floor")
        self.assertTrue(self.record()["rebake"], "51% is under the npc floor: rebaked")
        self.assertIn("UV rebaked 29% -> 46% at 2048 px", self.row("assets/models/prop_crate.glb"))
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "7", "--rebake", "auto", "--overwrite")
        self.assertEqual(rc, 0, out)
        self.assertIn("--rebake-under", self.cleanup_argv())
        for flags in (["--no-rebake"], ["--material", "vertex"]):
            rc, out = self.make("--image", "art_src/crate.png", "--seed", "7", "--overwrite", *flags)
            self.assertEqual(rc, 0, out)
            argv = self.cleanup_argv()
            self.assertFalse("--rebake" in argv or "--rebake-under" in argv, (flags, argv))
            self.assertEqual(self.record()["rebake_mode"], "off")
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "7", "--rebake", "--overwrite")
        self.assertEqual(rc, 0, out)
        argv = self.cleanup_argv()
        self.assertIn("--rebake", argv)
        self.assertEqual(argv[argv.index("--texture") + 1], "1024", "the prop class texture")
        self.assertTrue(self.record()["rebake"])
        self.assertIn("Rebake   : UV coverage 29% (6805 islands) -> 46% (3120 islands), texture 2048 px",
                      self.evidence("assets/models/prop_crate.glb"))

    def test_rebake_with_vertex_colours_is_refused_before_any_job(self):
        for flag in (["--rebake"], ["--rebake", "auto"]):
            rc, out = self.make("--image", "art_src/crate.png", "--seed", "7", "--material", "vertex", *flag)
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

    def test_a_coverage_just_under_the_floor_reads_under_it(self):
        """#203: a TRELLIS.2 npc at 54.6% failed with "UV coverage 55% is under 55%"; one decimal when the whole
        percent would read as the floor, and the waiver reads that number back."""
        self.assertEqual(bz.va.under_text(0.546, 0.55), "54.6%")
        self.assertEqual(bz.va.under_text(0.29, 0.5), "29%")
        fail = f"npc_a: UV coverage {bz.va.under_text(0.546, 0.55)} is under 55% (tiny islands waste texture space)"
        v = {"failures": [fail]}
        self.assertTrue(rebake.waive_uv(v))
        self.assertEqual(rebake.waiver_text(v, "npc", 0.55), "UV coverage waived: 54.6% under the npc floor 55% "
                                                               "(--accept-uv)")

    def test_the_evidence_line_names_each_maps_format(self):
        """#303: a map's format and JPEG quality in the rebake line; a record from before #303 reads as it did."""
        old = rebake.rebake_line(REBAKE_REPORT)
        self.assertIn("Color (transfer), Normal (normal);", old)
        new = dict(REBAKE_REPORT, maps=[dict(REBAKE_REPORT["maps"][0], format="JPEG", quality=90),
                                        dict(REBAKE_REPORT["maps"][1], format="PNG", quality=None)])
        self.assertIn("Color (transfer, JPEG 90), Normal (normal, PNG);", rebake.rebake_line(new))

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
        self.assertNotIn("--png", self.fake.calls[0][1])
        self.fake.calls.clear()
        rc, out = self.run_tool("rebake", "prop_crate", "--no-preview", "--png", url=False)
        self.assertEqual(rc, 0, out)
        self.assertIn("--png", self.fake.calls[0][1], "#303: --png reaches rebake_uvs.py")
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
        self.assertEqual(cleanup.parse_args(["raw.glb", "--out", "c.glb", "--rebake-under", "0.55", "--texture",
                                             "1024"]).rebake_under, 0.55)
        for bad in (["--rebake", "--rebake-under", "0.5"], ["--rebake-under", "0"], ["--rebake-under", "55"]):
            with self.assertRaises(SystemExit, msg=bad), contextlib.redirect_stderr(io.StringIO()):
                cleanup.parse_args(["raw.glb", "--out", "c.glb"] + bad)

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

    def image(name, px, data, fill, jpeg=False):
        img = bpy.data.images.new(name, px, px, alpha=False, is_data=data)
        img.colorspace_settings.name = "Non-Color" if data else "sRGB"
        buf = [0.0] * (px * px * 4)
        for i in range(px * px):
            c = fill(i % px, i // px)
            buf[4 * i:4 * i + 4] = [c[0], c[1], c[2], 1.0]
        img.pixels.foreach_set(buf)
        if jpeg:   # saved as a .jpg and loaded back: JPEG bytes packed, as the glTF importer leaves a Tripo map
            path = out_dir + "/" + name + ".jpg"
            img.filepath_raw = path
            img.file_format = "JPEG"
            img.save(quality=90)
            img = bpy.data.images.load(path)
            img.colorspace_settings.name = "Non-Color" if data else "sRGB"
        img.pack()
        return img

    def speckle(x, y):
        # a fixed pseudo-random +-0.04 per texel: detail a photo-like colour map has, which PNG stores poorly
        return (((x * 73856093) ^ (y * 19349663)) % 1009) / 1009 * 0.08 - 0.04

    def build(n_cubes, path, jpeg=False):
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
        if jpeg:
            base = image("fixture_base", px, False, lambda x, y: tuple(c + speckle(x, y) for c in
                                                                         COLOURS[(x // (px // 2), y // (px // 2))]), True)
        else:
            base = image("fixture_base", px, False, lambda x, y: COLOURS[(x // (px // 2), y // (px // 2))])
        orm = image("fixture_orm", px, True, lambda x, y: (1.0, 0.6, 0.2), jpeg)
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
    build(1, out_dir + "/fixture_jpeg.glb", jpeg=True)
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


def map_mimes(path):
    """{"base", "orm", "normal": mime type} of a .glb's first material, from its JSON; the bytes must agree (a
    mismatch reads as "?")."""
    doc, binary = cl.read_glb(Path(path).read_bytes())
    mat = doc["materials"][0]
    refs = {"base": mat["pbrMetallicRoughness"].get("baseColorTexture"),
            "orm": mat["pbrMetallicRoughness"].get("metallicRoughnessTexture"), "normal": mat.get("normalTexture")}
    out = {}
    for key, ref in refs.items():
        im = doc["images"][doc["textures"][ref["index"]]["source"]]
        view = doc["bufferViews"][im["bufferView"]]
        head = binary[view.get("byteOffset", 0):view.get("byteOffset", 0) + 4]
        kind = "image/png" if head == b"\x89PNG" else "image/jpeg" if head[:3] == b"\xff\xd8\xff" else None
        out[key] = im.get("mimeType") if im.get("mimeType") == kind else "?"
    return out


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
        assert p.returncode == 0 and p.stdout.count("BUILT") == 3, p.stdout[-2000:] + p.stderr[-2000:]
        cls.fixture = cls.d / "fixture.glb"
        cls.fixture_jpeg = cls.d / "fixture_jpeg.glb"

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

    def test_rebake_under_a_floor_rebakes_only_a_model_under_it(self):
        """#203 (bozzetto.py --rebake auto): the fixture's own atlas (1%) is under the prop floor, so it is rebaked;
        the rebaked model (over the floor) run again keeps its atlas untouched."""
        auto = self.d / "auto.glb"
        rc, out = bz.run_bpy(BLENDER, HERE / "cleanup.py", [self.fixture, "--out", auto, "--height", "1",
                                                            "--rebake-under", "0.5", "--texture", "256", "--json",
                                                            self.d / "auto.json"], "cleanup")
        self.assertEqual(rc, 0, out)
        self.assertIn("is under the floor 50%: rebaking", out)
        rep = json.loads((self.d / "auto.json").read_text(encoding="utf-8"))
        self.assertTrue(rep["rebake_auto"]["ran"], rep["rebake_auto"])
        self.assertLess(rep["rebake_auto"]["coverage"], 0.1)
        self.assertGreaterEqual(rep["rebake"]["uv_coverage_after"], 0.5)
        self.assertEqual(self.validate(auto)[0], 0)
        kept = self.d / "kept.glb"
        rc, out = bz.run_bpy(BLENDER, HERE / "cleanup.py", [auto, "--out", kept, "--height", "1", "--rebake-under",
                                                            "0.5", "--json", self.d / "kept.json"], "cleanup")
        self.assertEqual(rc, 0, out)
        self.assertIn("meets the floor 50%: the model's own atlas is kept", out)
        rep2 = json.loads((self.d / "kept.json").read_text(encoding="utf-8"))
        self.assertIsNone(rep2["rebake"])
        self.assertFalse(rep2["rebake_auto"]["ran"])
        self.assertAlmostEqual(rep2["rebake_auto"]["coverage"], rep["rebake"]["uv_coverage_after"], delta=0.01)
        self.assertEqual(self.validate(kept)[0], 0)

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
        self.assertEqual(map_mimes(out), {"base": "image/png", "orm": "image/png", "normal": "image/png"},
                         "#303: PNG sources stay PNG")
        self.assertEqual({m["format"] for m in rep["maps"]}, {"PNG"})
        rc, text = bz.run_bpy(BLENDER, bz.TOOLS / "blender" / "rebake_uvs.py", [self.fixture, "--out", out], "rebake")
        self.assertEqual(rc, 2, "an existing --out needs --overwrite")
        rc, text = bz.run_bpy(BLENDER, bz.TOOLS / "blender" / "rebake_uvs.py",
                              [self.d / "two.glb", "--out", self.d / "two_out.glb"], "rebake")
        self.assertEqual(rc, 2, "two meshes need --join")
        self.assertIn("--join", text)
        rc, text = bz.run_bpy(BLENDER, bz.TOOLS / "blender" / "rebake_uvs.py",
                              [self.d / "two.glb", "--out", self.d / "two_out.glb", "--join", "--no-check"], "rebake")
        self.assertEqual(rc, 0, text)

    def test_a_jpeg_colour_map_stays_jpeg(self):
        """#303: Tripo's colour maps arrive as JPEG, and the rebake wrote them back as PNG (a character's main file 5.0
        to 11.5 MB). The colour map stays JPEG at prep_export.JPEG_QUALITY; the normal and metallic-roughness maps
        are PNG whatever their source (JPEG blocks dent normals); --png writes PNG; prep_export keeps the JPEG in the
        main file and its LOD."""
        tool = bz.TOOLS / "blender" / "rebake_uvs.py"
        jpg, png = self.d / "rebaked_jpeg.glb", self.d / "rebaked_png.glb"
        rc, text = bz.run_bpy(BLENDER, tool, [self.fixture_jpeg, "--out", jpg, "--texture", "512", "--json",
                                              self.d / "rebaked_jpeg.json"], "rebake")
        self.assertEqual(rc, 0, text)
        self.assertEqual(map_mimes(self.fixture_jpeg)["base"], "image/jpeg", "the fixture is what Tripo ships")
        self.assertEqual(map_mimes(jpg), {"base": "image/jpeg", "orm": "image/png", "normal": "image/png"})
        rep = json.loads((self.d / "rebaked_jpeg.json").read_text(encoding="utf-8"))
        fmt = {m["source"]: (m["format"], m["quality"]) for m in rep["maps"]}
        self.assertEqual(fmt, {"fixture_base": ("JPEG", 90), "fixture_orm": ("PNG", None),
                               "fixture_normal": ("PNG", None)})
        self.assertEqual(rep["bake"]["jpeg_quality"], 90)
        self.assertIn("JPEG 90", rebake.rebake_line(rep), "the evidence line names the format")
        self.assertLessEqual(rep["check"]["mean_levels"], 4.0, "the JPEG colour map still matches the original")
        self.assertLessEqual(self.probe(jpg)["bad"], 2)
        rc, text = bz.run_bpy(BLENDER, tool, [self.fixture_jpeg, "--out", png, "--texture", "512", "--no-check",
                                              "--png"], "rebake")
        self.assertEqual(rc, 0, text)
        self.assertEqual(map_mimes(png), {"base": "image/png", "orm": "image/png", "normal": "image/png"}, "--png")
        self.assertLess(jpg.stat().st_size, png.stat().st_size * 0.8,
                        f"JPEG {jpg.stat().st_size} bytes against PNG {png.stat().st_size}")
        # prep_export (make and rebake run it next): the main file and its LOD keep the JPEG colour map
        export = self.d / "export" / "rebaked_jpeg.glb"
        rc, text = bz.run_bpy(BLENDER, bz.TOOLS / "blender" / "prep_export.py",
                              [jpg, "--out", export, "--lods", "0.5", "--no-validate", "--overwrite"], "prep_export")
        self.assertEqual(rc, 0, text)
        self.assertEqual(map_mimes(export)["base"], "image/jpeg")
        lod = export.with_name("rebaked_jpeg_LOD1.glb")
        self.assertEqual(map_mimes(lod), {"base": "image/jpeg", "orm": "image/png", "normal": "image/png"})
        self.assertLess(lod.stat().st_size, export.stat().st_size)

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
