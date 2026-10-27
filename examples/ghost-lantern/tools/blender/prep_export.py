#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# prep_export.py
# Purpose : Get a 3D asset game-ready in one step (SOP-11 stages 4 and 5): apply
#           rotation and scale, move the pivot to the bottom center, clean names,
#           export glTF with ONE fixed preset, optionally write decimated LODs,
#           then run validate_asset.py on the result.
# Usage   : Inside Blender (any OS):
#             blender -b --python-exit-code 1 -P tools/blender/prep_export.py -- <asset> --out <file.glb> [options]
#           With the bpy module (pip install bpy, needs the matching Python version):
#             python tools/blender/prep_export.py <asset> --out <file.glb> [options]
#           Examples:
#             ... -- assets_src/crate.blend --out assets/models/crate.glb --class prop
#             ... -- tree.fbx --out assets/models/tree.glb --lods 0.5,0.25 --class kit
#             ... -- statue.obj --out statue.glb --pivot center --join --no-validate
# Needs   : Blender 4.2+ or the bpy module
# Exit    : 0 exported (and validation passed), 1 export or validation failed, 2 usage/environment
# Notes   : The source file is never modified or saved. Cameras and lights are dropped.
#           --pivot bottom (default) puts every mesh origin at its own bottom center and the whole
#           asset's bottom center at the world origin; center uses the bounds center; keep changes nothing.
#           --lods 0.5,0.25 writes <name>_LOD1.glb, <name>_LOD2.glb with a Decimate (collapse) modifier
#           at those ratios. Check LODs by eye: decimation can wreck UVs and silhouettes.
#           Skinned meshes: rotation and scale are applied to armatures too; check the rig after export.
#           --ignore NAME drops helper objects (a stray sphere, a ground plane) before anything else.
#           Validation uses the same rules as validate_asset.py (--class picks the budget; default any).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   import into an empty scene, drop cameras and lights
#   apply rotation and scale on meshes and armatures; optionally join meshes
#   pivot: each mesh's origin to its bottom center (data moves the other way, world shape unchanged),
#          then shift the roots so the asset's bottom center sits at the world origin
#   names: spaces and dots to underscores (engines choke on them)
#   export .glb (Y-up, modifiers applied, animations kept); for each LOD ratio: decimate, export, undo
#   validate the main export with validate_asset's rules, return its verdict
import argparse
import fnmatch
import re
import sys
from pathlib import Path

DEBUG = False
GLTF_PRESET = {  # the ONE export preset (SOP-11: never ad hoc)
    "export_format": "GLB", "export_yup": True, "export_apply": True, "export_animations": True,
    "export_cameras": False, "export_lights": False, "use_selection": False,
}


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}")


def script_argv():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else argv[1:]


def ratio_list(text):
    try:
        ratios = [float(x) for x in text.split(",") if x.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(f"--lods must look like 0.5,0.25, got {text!r}")
    if not ratios or any(not 0 < r < 1 for r in ratios):
        raise argparse.ArgumentTypeError("every LOD ratio must be between 0 and 1 (exclusive)")
    return ratios


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="prep_export.py",
                                 description="Apply transforms, fix the pivot, export glTF with one preset, make LODs, validate.")
    ap.add_argument("asset", help="source model: .glb .gltf .fbx .obj .blend")
    ap.add_argument("--out", required=True, help="output .glb (LODs go next to it as <name>_LOD1.glb, ...)")
    ap.add_argument("--pivot", choices=["bottom", "center", "keep"], default="bottom", help="origin placement (default bottom)")
    ap.add_argument("--join", action="store_true", help="join all meshes into one object (fewer draw calls)")
    ap.add_argument("--ignore", action="append", default=[], metavar="NAME",
                    help="drop objects whose name matches (wildcards ok, repeatable): stray helper meshes in downloaded models")
    ap.add_argument("--lods", type=ratio_list, default=[], help="decimate ratios for LOD files, e.g. 0.5,0.25")
    ap.add_argument("--class", dest="asset_class", default="any", help="validate_asset budget class (default any)")
    ap.add_argument("--no-validate", action="store_true", help="skip validate_asset on the result")
    ap.add_argument("--overwrite", action="store_true", help="replace existing output files")
    ap.add_argument("--debug", action="store_true", help="verbose output")
    return ap.parse_args(argv)


def load_modules():
    """bpy plus validate_asset (same folder). Returns (bpy, va) or (None, None)."""
    try:
        import bpy  # noqa: F401
    except ImportError:
        print("[ENV ] bpy not available. Run inside Blender:\n"
              "         blender -b --python-exit-code 1 -P tools/blender/prep_export.py -- <asset> --out <file.glb>\n"
              "       or with the bpy module for your Python version (pip install bpy)", file=sys.stderr)
        return None, None
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import validate_asset as va  # noqa: E402
    return bpy, va


def select_only(bpy, objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    if objs:
        bpy.context.view_layer.objects.active = objs[0]


def apply_transforms(bpy, scene):
    targets = [o for o in scene.objects if o.type in ("MESH", "ARMATURE")]
    if targets:
        select_only(bpy, targets)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)


def join_meshes(bpy, scene):
    meshes = [o for o in scene.objects if o.type == "MESH"]
    if len(meshes) > 1:
        select_only(bpy, meshes)
        bpy.ops.object.join()


def set_pivots(bpy, scene, mode, va):
    """Move each mesh origin to its bottom (or bounds) center without moving the geometry in the world,
    then shift the root objects so the whole asset's anchor sits at the world origin."""
    from mathutils import Matrix, Vector
    if mode == "keep":
        return
    meshes = [o for o in scene.objects if o.type == "MESH" and len(o.data.vertices) > 0]
    for obj in meshes:
        lo, hi = va.world_bounds(obj)
        anchor_w = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2] if mode == "bottom" else (lo[2] + hi[2]) / 2))
        delta_w = anchor_w - obj.matrix_world.translation
        delta_local = obj.matrix_world.to_3x3().inverted() @ delta_w
        if obj.data.users > 1:
            obj.data = obj.data.copy()              # shared mesh data: give this object its own copy
        obj.data.transform(Matrix.Translation(-delta_local))
        obj.matrix_world.translation = anchor_w
    bpy.context.view_layer.update()
    los = [va.world_bounds(o)[0] for o in meshes]
    his = [va.world_bounds(o)[1] for o in meshes]
    if not los:
        return
    lo = [min(v[i] for v in los) for i in range(3)]
    hi = [max(v[i] for v in his) for i in range(3)]
    shift = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2] if mode == "bottom" else (lo[2] + hi[2]) / 2))
    for root in [o for o in scene.objects if o.parent is None]:
        root.location -= shift
    bpy.context.view_layer.update()


def clean_names(scene):
    renamed = []
    for obj in scene.objects:
        new = re.sub(r"[^A-Za-z0-9_-]", "_", obj.name)
        if new and not new[0].isalpha():
            new = "Obj_" + new
        if new != obj.name:
            renamed.append(f"{obj.name} -> {new}")
            obj.name = new
    return renamed


def triangles(bpy, scene):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    total = 0
    for obj in scene.objects:
        if obj.type == "MESH":
            mesh = obj.evaluated_get(depsgraph).to_mesh()
            mesh.calc_loop_triangles()
            total += len(mesh.loop_triangles)
            obj.evaluated_get(depsgraph).to_mesh_clear()
    return total


def export(bpy, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(path), **GLTF_PRESET)


def run(args):
    src, out = Path(args.asset), Path(args.out)
    if not src.exists():
        print(f"[ENV ] asset not found: {src}", file=sys.stderr)
        return 2
    if out.suffix.lower() != ".glb":
        print("[ENV ] --out must end in .glb", file=sys.stderr)
        return 2
    lod_paths = [out.with_name(f"{out.stem}_LOD{i}.glb") for i in range(1, len(args.lods) + 1)]
    existing = [p for p in [out] + lod_paths if p.exists()]
    if existing and not args.overwrite:
        print(f"[ENV ] {', '.join(str(p) for p in existing)} exists (use --overwrite)", file=sys.stderr)
        return 2
    if src.resolve() == out.resolve():
        print("[ENV ] --out must not be the source file", file=sys.stderr)
        return 2
    bpy, va = load_modules()
    if bpy is None:
        return 2
    if args.asset_class not in va.CLASS_BUDGETS:
        print(f"[ENV ] unknown --class {args.asset_class!r} (one of {', '.join(sorted(va.CLASS_BUDGETS))})", file=sys.stderr)
        return 2
    missing = va.gltf_missing_files(src)
    if missing:
        # Exporting now would bake a model without its texture into the game.
        print(f"[FAIL] {src.name} refers to {', '.join(missing)}, which is not next to it. Copy the pack's folder "
              "(for Kenney: Textures/) beside the source file, then run again.", file=sys.stderr)
        return 1
    try:
        va.import_asset(bpy, src.resolve())
    except ValueError as exc:
        print(f"[ENV ] {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"[FAIL] import failed: {exc}", file=sys.stderr)
        return 1

    scene = bpy.context.scene
    for obj in [o for o in scene.objects if o.type in ("CAMERA", "LIGHT")]:
        bpy.data.objects.remove(obj, do_unlink=True)
    for obj in [o for o in scene.objects if any(fnmatch.fnmatch(o.name, p) for p in args.ignore)]:
        print(f"[info] dropped {obj.name}")
        bpy.data.objects.remove(obj, do_unlink=True)
    if not any(o.type == "MESH" for o in scene.objects):
        print("[FAIL] no mesh objects found in the file", file=sys.stderr)
        return 1
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    apply_transforms(bpy, scene)
    if args.join:
        join_meshes(bpy, scene)
    set_pivots(bpy, scene, args.pivot, va)
    for r in clean_names(scene):
        print(f"[info] renamed {r}")
    base_tris = triangles(bpy, scene)
    export(bpy, out)
    print(f"[ OK ] {out} ({base_tris} triangles, pivot {args.pivot})")

    for ratio, path in zip(args.lods, lod_paths):
        mods = []
        for obj in [o for o in scene.objects if o.type == "MESH"]:
            m = obj.modifiers.new(name="LOD_Decimate", type="DECIMATE")
            m.ratio = ratio
            mods.append((obj, m))
        tris = triangles(bpy, scene)
        export(bpy, path)
        for obj, m in mods:
            obj.modifiers.remove(m)
        print(f"[ OK ] {path} ({tris} triangles, ratio {ratio})")

    if args.no_validate:
        return 0
    print(f"--- validate_asset ({args.asset_class}) ---")
    vargs = va.parse_args([str(out), "--class", args.asset_class] + (["--debug"] if DEBUG else []))
    return va.run(vargs)


def main():
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        args = parse_args(script_argv())
    except SystemExit as exc:
        return int(exc.code or 0)
    DEBUG = args.debug
    try:
        return run(args)
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ENV ] prep_export crashed: {exc!r}. Re-run with --debug and paste the output.", file=sys.stderr)
        if DEBUG:
            raise
        return 2


if __name__ == "__main__":
    sys.exit(main())
