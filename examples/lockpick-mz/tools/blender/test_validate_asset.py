#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_validate_asset.py
# Purpose : The exam for validate_asset.py (see docs/sop/SOP-09, "Exams for tools").
#           Builds known-good and known-bad assets with bpy, exports them as .glb,
#           runs the validator on each, and checks it gives the expected verdict.
# Usage   : With the bpy module:  python tools/blender/test_validate_asset.py [--keep] [--debug]
#           Inside Blender:       blender -b --python-exit-code 1 -P tools/blender/test_validate_asset.py -- [--keep] [--debug]
# Exit    : 0 all cases pass, 1 some case failed, 2 bpy not available
# Notes   : Every case runs the validator as a separate process with the same Python,
#           so it exercises the real command line and exit codes.
#           --keep leaves the generated .glb files in a temp folder for inspection.
#           Add a case here whenever the validator misses a real-world problem.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   for each case: reset scene -> build fixture -> export glb -> run validator
#                  -> compare exit code and an expected phrase in the output
#   print a score line "N/M cases passed", exit 0 only when all pass
import argparse
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
VALIDATOR = HERE / "validate_asset.py"


def script_argv():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else argv[1:]


# ---------------------------------------------------------------- fixtures
def reset(bpy):
    bpy.ops.wm.read_factory_settings(use_empty=True)


def smart_unwrap(bpy, obj):
    """Blender's own unwrap and pack: the recommended path in SOP-11."""
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(island_margin=0.02)
    bpy.ops.uv.pack_islands(margin=0.01)
    bpy.ops.object.mode_set(mode="OBJECT")


def cube(bpy, name="Crate", size=1.0, unwrap=True):
    bpy.ops.mesh.primitive_cube_add(size=size, location=(0, 0, size / 2))
    obj = bpy.context.active_object
    obj.name = name
    if unwrap:
        smart_unwrap(bpy, obj)
    return obj


def build_good(bpy):
    cube(bpy)


def build_flat_lowpoly(bpy):
    # Faceted low-poly (SOP-11's recommended stylized look): glTF splits every vertex at the hard edges
    # A UV sphere: hard edges everywhere once flat-shaded, but one continuous lat-long UV layout
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=0.5, location=(0, 0, 0.5))
    obj = bpy.context.active_object
    obj.name = "Crate"
    bpy.ops.object.shade_flat()


def build_no_uv(bpy):
    obj = cube(bpy, unwrap=False)
    while obj.data.uv_layers:
        obj.data.uv_layers.remove(obj.data.uv_layers[0])


def build_heavy(bpy):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=128, ring_count=64, radius=0.5, location=(0, 0, 0.5))
    obj = bpy.context.active_object
    obj.name = "Rock"
    smart_unwrap(bpy, obj)


def build_giant(bpy):
    cube(bpy, size=200.0)


def build_tiny(bpy):
    cube(bpy, size=0.001)


def build_fragmented(bpy):
    """A 10x10 grid where every face is its own tiny UV island: the classic AI unwrap failure."""
    import bmesh
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=10, y_subdivisions=10, size=2.0, location=(0, 0, 0))
    obj = bpy.context.active_object
    obj.name = "Floor"
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    uv = bm.loops.layers.uv.verify()
    for i, face in enumerate(bm.faces):
        ox, oy = (i % 20) * 0.05, (i // 20) * 0.05
        for k, loop in enumerate(face.loops):
            corner = [(0, 0), (1, 0), (1, 1), (0, 1)][k % 4]
            loop[uv].uv = (ox + corner[0] * 0.01, oy + corner[1] * 0.01)
    bm.to_mesh(me)
    bm.free()


def build_unapplied_scale(bpy):
    obj = cube(bpy)
    obj.scale = (2.0, 2.0, 2.0)


def build_bad_name(bpy):
    cube(bpy, name="My Crate.001")


def build_off_pivot(bpy):
    obj = cube(bpy)
    # move the mesh 3 m away from the object origin
    for v in obj.data.vertices:
        v.co.x += 3.0


def build_overlap(bpy):
    """Two unwrapped cubes joined into one object: identical UVs, so islands sit on top of each other."""
    a = cube(bpy, name="Stack")
    bpy.ops.object.select_all(action="DESELECT")
    b = cube(bpy, name="StackTop")
    b.location.z += 1.0
    bpy.ops.object.select_all(action="DESELECT")
    a.select_set(True)
    b.select_set(True)
    bpy.context.view_layer.objects.active = a
    bpy.ops.object.join()


def image_material(bpy, name="Colormap"):
    """A material that samples an image texture (what palette-textured packs ship)."""
    img = bpy.data.images.new(name + "Img", 4, 4)
    mat = bpy.data.materials.new(name)
    if bpy.app.version < (5, 0, 0):   # 5.x always uses nodes; use_nodes goes away in 6.0
        mat.use_nodes = True
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def build_palette(bpy):
    """Kenney-style colormap texturing: every face's UVs collapsed onto one swatch of a small palette image."""
    import bmesh
    obj = cube(bpy, name="Crate", unwrap=False)
    obj.data.materials.append(image_material(bpy))
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    uv = bm.loops.layers.uv.verify()
    for i, face in enumerate(bm.faces):
        for loop in face.loops:
            loop[uv].uv = (0.125 + 0.25 * (i % 4), 0.125 + 0.25 * (i // 4 % 4))
    bm.to_mesh(obj.data)
    bm.free()


def build_untextured_fragmented(bpy):
    """The fragmented floor again, but its material is a plain color: UV layout does not matter."""
    build_fragmented(bpy)
    mat = bpy.data.materials.new("PlainGray")
    bpy.context.active_object.data.materials.append(mat)


def add_back_faces(bpy, obj):
    """Store every face a second time, flipped: double-sided geometry baked into the mesh."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    dup = bmesh.ops.duplicate(bm, geom=list(bm.faces))
    bmesh.ops.reverse_faces(bm, faces=[g for g in dup["geom"] if isinstance(g, bmesh.types.BMFace)])
    bm.to_mesh(obj.data)
    bm.free()


def build_double_sided(bpy):
    add_back_faces(bpy, cube(bpy))


def build_rigged(bpy):
    """A cube skinned to a one-bone armature. On re-import Blender's glTF importer adds an 'Icosphere' bone shape
    with junk UVs; the validator must not judge that importer artifact (it is not in the file)."""
    obj = cube(bpy, name="Body")
    bpy.ops.object.armature_add(location=(0, 0, 0))
    arm = bpy.context.active_object
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")


# name, builder, extra args, expected exit, phrase expected in output
CASES = [
    ("good crate passes", build_good, ["--class", "prop"], 0, "passes every check"),
    ("flat-shaded low-poly is not fragmented", build_flat_lowpoly, ["--class", "prop"], 0, "passes every check"),
    ("missing UVs fail", build_no_uv, ["--class", "prop"], 1, "no UV map"),
    ("triangle budget fails", build_heavy, ["--class", "prop"], 1, "over the budget"),
    ("giant scale fails", build_giant, ["--class", "prop"], 1, "is over 3.0 m"),
    ("tiny scale fails", build_tiny, ["--class", "prop"], 1, "is under 0.01 m"),
    ("fragmented UVs fail coverage", build_fragmented, ["--class", "kit"], 1, "UV coverage"),
    ("fragmented UVs warn islands", build_fragmented, ["--class", "kit"], 1, "UV islands"),
    ("unapplied scale warns", build_unapplied_scale, ["--class", "prop"], 0, "unapplied scale"),
    ("unapplied scale fails with --strict", build_unapplied_scale, ["--class", "prop", "--strict"], 1, "unapplied scale"),
    ("bad name warns", build_bad_name, ["--class", "prop"], 0, "name does not match"),
    ("off pivot warns", build_off_pivot, ["--class", "kit"], 0, "origin is"),
    ("overlapping UV islands warn", build_overlap, ["--class", "kit"], 0, "overlaps"),
    ("palette (colormap) texturing passes", build_palette, ["--class", "prop"], 0, "palette (colormap) texturing"),
    ("color-only material skips UV layout checks", build_untextured_fragmented, ["--class", "kit"], 0, "no image texture"),
    ("faces stored twice back to back warn", build_double_sided, ["--class", "prop"], 0, "stored twice, back to back"),
    ("rigged model: the importer's bone-shape Icosphere is not judged", build_rigged, ["--class", "prop"], 0, "Tris   : 12"),
]


def export_glb(bpy, path):
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB")


def build_external_texture_glb(bpy, folder):
    """A .glb whose image lives in a separate file beside it (how Kenney packs ship), built from a
    separate-files glTF export. Returns (glb path, image path)."""
    reset(bpy)
    build_palette(bpy)
    folder.mkdir(parents=True, exist_ok=True)
    gltf = folder / "crate.gltf"
    bpy.ops.export_scene.gltf(filepath=str(gltf), export_format="GLTF_SEPARATE")
    doc = json.loads(gltf.read_text(encoding="utf-8"))
    bin_data = (folder / doc["buffers"][0].pop("uri")).read_bytes()
    bin_data += b"\0" * (-len(bin_data) % 4)
    js = json.dumps(doc).encode("utf-8")
    js += b" " * (-len(js) % 4)
    glb = folder / "crate.glb"
    glb.write_bytes(struct.pack("<4sII", b"glTF", 2, 28 + len(js) + len(bin_data))
                    + struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(bin_data), b"BIN\0") + bin_data)
    return glb, folder / doc["images"][0]["uri"]


def validator_cmd():
    """How to launch validate_asset.py: through Blender when we run inside it, else this Python.

    Inside Blender, sys.executable is Blender's bundled python.exe, which cannot import bpy.
    """
    try:
        import bpy
        binary = getattr(bpy.app, "binary_path", "") or ""
    except ImportError:
        binary = ""
    if binary and Path(binary).stem.lower().startswith("blender"):
        return [binary, "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(VALIDATOR), "--"]
    return [sys.executable, str(VALIDATOR)]


def run_validator(asset, extra):
    cmd = validator_cmd() + [str(asset)] + extra
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout + proc.stderr


def main():
    ap = argparse.ArgumentParser(description="Exam for validate_asset.py (builds fixtures with bpy).")
    ap.add_argument("--keep", action="store_true", help="keep generated .glb files")
    ap.add_argument("--debug", action="store_true", help="print validator output for every case")
    args = ap.parse_args(script_argv())
    try:
        import bpy
    except ImportError:
        print("[ENV ] bpy not available. pip install bpy (matching Python, 3.13 for bpy 5.2) or run inside Blender.\n"
              "       With uv: uv run --python 3.13 --with bpy python tools/blender/test_validate_asset.py", file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="validate_asset_exam_"))
    passed = 0
    try:
        # extra environment cases that need no fixture
        env_cases = [
            ("missing file exits 2", [str(tmp / "nope.glb")], 2, "not found"),
            ("unsupported type exits 2", [str(VALIDATOR)], 2, "unsupported file type"),
            ("help exits 0", ["-h"], 0, "Validate a 3D asset"),
            ("bad option exits 2", [str(VALIDATOR), "--class", "spaceship"], 2, "invalid choice"),
        ]
        total = len(CASES) + len(env_cases) + 3
        for i, (name, builder, extra, want_code, phrase) in enumerate(CASES):
            reset(bpy)
            builder(bpy)
            asset = tmp / f"case_{i:02d}.glb"
            export_glb(bpy, asset)
            code, out = run_validator(asset, extra)
            ok = code == want_code and phrase in out
            passed += ok
            print(f"[{'PASS' if ok else 'FAIL'}] {name} (exit {code}, wanted {want_code})")
            if args.debug or not ok:
                print("        " + out.replace("\n", "\n        "))
        # FBX in centimeters: Blender imports the unit as object scale 0.01. Info, not a warning.
        reset(bpy)
        fbx_obj = cube(bpy)
        fbx_obj.scale = (0.01, 0.01, 0.01)
        fbx_path = tmp / "centimeters.fbx"
        bpy.ops.export_scene.fbx(filepath=str(fbx_path), apply_unit_scale=False, use_space_transform=False)
        code, out = run_validator(fbx_path, ["--class", "prop", "--min-dim", "0.001"])
        scale_line = [l for l in out.splitlines() if "scale" in l.lower() and l.startswith("[")]
        ok = code == 0 and not any(l.startswith("[WARN]") for l in scale_line)
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] FBX unit scale 0.01 is not an unapplied-scale warning (exit {code})")
        if args.debug or not ok:
            print("        " + out.replace("\n", "\n        "))
        glb, image = build_external_texture_glb(bpy, tmp / "external")
        for name, want_code, phrase in [
            ("external texture beside the .glb passes", 0, "palette (colormap) texturing"),
            ("external texture missing fails (moved without its folder)", 1, "which is not next to it"),
        ]:
            if want_code == 1:
                image.unlink()
            code, out = run_validator(glb, ["--class", "prop"])
            ok = code == want_code and phrase in out
            passed += ok
            print(f"[{'PASS' if ok else 'FAIL'}] {name} (exit {code}, wanted {want_code})")
            if args.debug or not ok:
                print("        " + out.replace("\n", "\n        "))
        for name, argv, want_code, phrase in env_cases:
            proc = subprocess.run(validator_cmd() + argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
            out = proc.stdout + proc.stderr
            ok = proc.returncode == want_code and phrase in out
            passed += ok
            print(f"[{'PASS' if ok else 'FAIL'}] {name} (exit {proc.returncode}, wanted {want_code})")
            if args.debug or not ok:
                print("        " + out.replace("\n", "\n        "))
    finally:
        if args.keep:
            print(f"fixtures kept in {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"{passed}/{total} cases passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
