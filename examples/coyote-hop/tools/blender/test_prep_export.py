#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_prep_export.py
# Purpose : The exam for prep_export.py: a model with unapplied scale and rotation,
#           a pivot floating above it, an off-center location and a bad name must come
#           out clean, the LODs must really have fewer triangles, and the validator
#           verdict and usage errors must reach the exit code.
# Usage   : With the bpy module:  python tools/blender/test_prep_export.py [--keep] [--debug]
#           Inside Blender:       blender -b --python-exit-code 1 -P tools/blender/test_prep_export.py -- [--keep] [--debug]
# Exit    : 0 all cases pass, 1 some case failed, 2 bpy not available
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   build a messy fixture (scaled, rotated, origin above the mesh, off-center, "Rock 01.001")
#   run prep_export as a separate process with --lods 0.5,0.25
#   re-import the outputs with bpy and measure: scale, base height, center, origin, names, triangles
#   check validation failures and usage errors reach the exit code
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE / "prep_export.py"


def script_argv():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else argv[1:]


def tool_cmd():
    try:
        import bpy
        binary = getattr(bpy.app, "binary_path", "") or ""
    except ImportError:
        binary = ""
    if binary and Path(binary).stem.lower().startswith("blender"):
        return [binary, "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(TOOL), "--"]
    return [sys.executable, str(TOOL)]


def run_tool(*args):
    proc = subprocess.run(tool_cmd() + [str(a) for a in args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout + proc.stderr


def build_messy(bpy, path):
    """A UV sphere ('Rock 01.001'): scale 2, rotated, origin 3 m above it, sitting at x=4."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=0.5, location=(4, -2, 1))
    obj = bpy.context.active_object
    obj.name = "Rock 01.001"
    obj.scale = (2, 2, 2)
    obj.rotation_euler = (0.3, 0.2, 0.7)
    bpy.context.scene.cursor.location = (4, -2, 4)
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB")


def build_no_uv(bpy, path):
    """A cube with no UV map: validate_asset must fail it, so prep_export must exit 1."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=1, calc_uvs=False)
    obj = bpy.context.active_object
    obj.name = "NoUV"
    while obj.data.uv_layers:
        obj.data.uv_layers.remove(obj.data.uv_layers[0])
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB")


def measure(bpy, path):
    """Import a .glb and report what an engine would see."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path))
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    obj = meshes[0]
    pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    obj.data.calc_loop_triangles()
    return {
        "name": obj.name, "scale": tuple(obj.scale), "rot": tuple(obj.rotation_euler),
        "lo": lo, "hi": hi, "origin": tuple(obj.matrix_world.translation),
        "tris": len(obj.data.loop_triangles), "meshes": len(meshes),
    }


def main():
    ap = argparse.ArgumentParser(description="Exam for prep_export.py (builds fixtures with bpy).")
    ap.add_argument("--keep", action="store_true", help="keep the generated files")
    ap.add_argument("--debug", action="store_true", help="print tool output for every case")
    args = ap.parse_args(script_argv())
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        import bpy
    except ImportError:
        print("[ENV ] bpy not available (run inside Blender or install the bpy module)", file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="prep_exam_"))
    src = tmp / "messy.glb"
    build_messy(bpy, src)
    results = []

    def case(name, ok, detail=""):
        results.append(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else '  ' + str(detail)}")

    rc, out = run_tool(src, "--out", tmp / "rock.glb", "--lods", "0.5,0.25")
    if args.debug:
        print(out)
    case("messy asset exports and validates (exit 0)", rc == 0, out[-600:])
    case("validator ran on the result", "validate_asset" in out, out[-300:])
    if rc == 0:
        m = measure(bpy, tmp / "rock.glb")
        case("scale applied (1, 1, 1)", all(abs(s - 1) < 1e-4 for s in m["scale"]), m["scale"])
        case("rotation applied (0, 0, 0)", all(abs(r) < 1e-4 for r in m["rot"]), m["rot"])
        case("asset sits on the ground (min z = 0)", abs(m["lo"][2]) < 1e-3, m["lo"])
        cx, cy = (m["lo"][0] + m["hi"][0]) / 2, (m["lo"][1] + m["hi"][1]) / 2
        case("asset centered on the origin in x and y", abs(cx) < 1e-3 and abs(cy) < 1e-3, (cx, cy))
        case("object origin at the bottom center", all(abs(c) < 1e-3 for c in m["origin"]), m["origin"])
        case("size kept (scale 2 sphere is about 2 m)", abs((m["hi"][2] - m["lo"][2]) - 2.0) < 0.1, m["hi"][2] - m["lo"][2])
        case("name cleaned (no spaces or dots)", " " not in m["name"] and "." not in m["name"], m["name"])
        l1, l2 = measure(bpy, tmp / "rock_LOD1.glb"), measure(bpy, tmp / "rock_LOD2.glb")
        case("LOD1 and LOD2 have fewer triangles, in order", m["tris"] > l1["tris"] > l2["tris"],
             (m["tris"], l1["tris"], l2["tris"]))
        case("source file untouched", measure(bpy, src)["name"].startswith("Rock 01"))

    rc, out = run_tool(src, "--out", tmp / "rock.glb")
    case("existing output is not overwritten without --overwrite (exit 2)", rc == 2, out[-200:])
    no_uv = tmp / "no_uv.glb"
    build_no_uv(bpy, no_uv)
    rc, out = run_tool(no_uv, "--out", tmp / "no_uv_out.glb")
    case("a validation failure reaches the exit code (no UV map -> exit 1)", rc == 1 and "no UV map" in out, out[-300:])
    rc, out = run_tool(no_uv, "--out", tmp / "no_uv_skip.glb", "--no-validate")
    case("--no-validate exports anyway (exit 0)", rc == 0, out[-300:])
    rc, out = run_tool(src, "--out", tmp / "fail.glb", "--class", "any", "--overwrite", "--lods", "2")
    case("bad LOD ratio exits 2", rc == 2, out[-200:])
    sys.path.insert(0, str(Path(__file__).resolve().parent))  # blender -P does not add the script's folder
    from test_validate_asset import build_external_texture_glb  # same folder
    glb, image = build_external_texture_glb(bpy, tmp / "external")
    image.unlink()
    rc, out = run_tool(glb, "--out", tmp / "external_out.glb")
    case("a source whose texture file is missing stops before export (exit 1)",
         rc == 1 and "not next to it" in out and not (tmp / "external_out.glb").exists(), out[-300:])
    rc, out = run_tool(tmp / "missing.glb", "--out", tmp / "x.glb")
    case("missing asset exits 2", rc == 2, out[-200:])

    passed = sum(results)
    print(f"{passed}/{len(results)} cases passed")
    if args.keep:
        print(f"files kept in {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
