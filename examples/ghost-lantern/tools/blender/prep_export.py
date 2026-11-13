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
#           LOD textures (#196): every LOD is a whole .glb, so each carries its own textures; --lod-textures half
#           (default) gives LOD n its images at 1/2^n of their size (longest edge never under LOD_TEXTURE_MIN), so a
#           set of LODs adds about a third of the textures' bytes instead of a full copy each. A rebaked 2048 px
#           character: 11.5 + 10.8 + 10.3 MB before, 11.5 + 4.6 + 1.8 MB after; Godot 4.7 loads all three (K01).
#           Shared external images (.gltf) would save more but change what every engine import and record expects.
#           Skinned meshes: rotation and scale are applied to armatures too; check the rig after export.
#           Linked duplicates (objects sharing one mesh) get their own mesh copy each, so the export
#           has one mesh per object instead of a shared one.
#           --ignore NAME drops helper objects (a stray sphere, a ground plane) before anything else.
#           Validation uses the same rules as validate_asset.py (--class picks the budget; default any).
#           Clips (#292, bpy_common.py): an action Blender 4.2's importer named "<clip>_<object>" takes its clip's
#           name back, and clips keyed at another frame rate than the scene's (30 fps) move the scene to their rate
#           first, so the sampled export keeps a loop's closing key and its length. With the bpy module on Windows
#           the process is ended through bpy_common.end_process: a plain exit after a glTF export crashed (bpy 4.2)
#           and hid the exit code.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): the bpy module's exit crash, clip names, clips at
#           30 fps (#292)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): LOD textures at half the size per level (#196)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   import into an empty scene, drop cameras and lights
#   apply rotation and scale on meshes and armatures (shared mesh data copied per object first); optionally join
#   pivot: each mesh's origin to its bottom center (data moves the other way, world shape unchanged),
#          then shift the roots so the asset's bottom center sits at the world origin
#   names: spaces and dots to underscores (engines choke on them)
#   export .glb (Y-up, modifiers applied, animations kept); for each LOD ratio: decimate, the materials' images
#   swapped for copies at 1/2^n of their size (--lod-textures half), export, undo both
#   validate the main export with validate_asset's rules, return its verdict
import argparse
import fnmatch
import os
import re
import sys
from pathlib import Path

DEBUG = False
GLTF_PRESET = {  # the ONE export preset (SOP-11: never ad hoc)
    "export_format": "GLB", "export_yup": True, "export_apply": True, "export_animations": True,
    "export_cameras": False, "export_lights": False, "use_selection": False,
}
LOD_TEXTURE_MIN = 256   # px: --lod-textures half never takes a texture's longest edge below this


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
    ap.add_argument("--lod-textures", choices=["half", "keep"], default="half",
                    help="half (default): each LOD file's textures at half the size of the one before (2048, 1024, "
                         f"512 ..., never under {LOD_TEXTURE_MIN} px); keep: every LOD carries the full-size textures")
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
    for obj in targets:
        # Linked duplicates share one mesh (or armature) data block. Blender applies the transform to the
        # shared data once and leaves the other users with a compensating scale and rotation, so give every
        # extra user its own copy first. The last user keeps the original block.
        if obj.data.users > 1:
            dbg(f"{obj.name}: {obj.data.name} has {obj.data.users} users, copying it")
            obj.data = obj.data.copy()
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


def texture_nodes(scene):
    """{image name: (image, [Image Texture nodes reading it])} over the meshes' materials (#196)."""
    found = {}
    for obj in [o for o in scene.objects if o.type == "MESH"]:
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or mat.node_tree is None:
                continue
            for node in mat.node_tree.nodes:
                img = getattr(node, "image", None) if node.type == "TEX_IMAGE" else None
                if img is None or img.source == "TILED" or min(img.size) == 0:
                    continue
                entry = found.setdefault(img.name, (img, []))
                if node not in entry[1]:
                    entry[1].append(node)
    return found


def lod_size(size, factor):
    """An image's (width, height) at `factor` of its size, the longest edge kept at LOD_TEXTURE_MIN or more; None when
    the image is already at or under that edge (it stays as it is)."""
    longest = max(size)
    if longest <= LOD_TEXTURE_MIN:
        return None
    scale = max(factor, LOD_TEXTURE_MIN / longest)
    return max(1, round(size[0] * scale)), max(1, round(size[1] * scale))


def shrink_textures(bpy, found, factor):
    """Point every Image Texture node at a copy of its image scaled to `factor` (lod_size) and return what undo_shrink
    needs. The copy is a generated image: a scaled file image keeps its packed bytes and is not marked changed, and
    the glTF exporter would write those full-size bytes (its encode_image.py; T95616), so the scaled pixels go into a
    new image the exporter has to encode. Colour space and alpha follow the source. Every copy is made from the full
    image, so LOD2 is not a resample of LOD1."""
    from array import array
    swaps = []
    for img, nodes in found.values():
        size = lod_size(tuple(img.size), factor)
        if size is None:
            continue
        w, h = size
        tmp = img.copy()
        tmp.scale(w, h)
        buf = array("f", bytes(4 * w * h * 4))
        tmp.pixels.foreach_get(buf)
        bpy.data.images.remove(tmp)
        new = bpy.data.images.new(f"{img.name}_lod", w, h, alpha=img.depth in (16, 32, 64, 128),
                                  float_buffer=img.is_float)
        new.colorspace_settings.name = img.colorspace_settings.name
        new.alpha_mode = img.alpha_mode
        new.pixels.foreach_set(buf)
        new.pack()
        name = img.name
        img.name = f"{name}_full"
        new.name = name                    # the LOD's image keeps the name the main file's has
        for node in nodes:
            node.image = new
        swaps.append((img, new, nodes, name))
        dbg(f"{name}: {img.size[0]}x{img.size[1]} -> {w}x{h} for this LOD")
    return swaps


def undo_shrink(bpy, swaps):
    for img, new, nodes, name in swaps:
        for node in nodes:
            node.image = img
        bpy.data.images.remove(new)
        img.name = name


def run(args):
    src, out = Path(args.asset), Path(args.out)
    if not src.exists():
        print(f"[ENV ] asset not found: {src}", file=sys.stderr)
        return 2
    if out.suffix.lower() != ".glb":
        print("[ENV ] --out must end in .glb", file=sys.stderr)
        return 2
    lod_paths = [out.with_name(f"{out.stem}_LOD{i}.glb") for i in range(1, len(args.lods) + 1)]
    same = [p for p in [out] + lod_paths if os.path.normcase(str(p.resolve())) == os.path.normcase(str(src.resolve()))]
    if same:                              # an LOD path too: tree_LOD1.glb as the source, --overwrite replaced it
        print(f"[ENV ] {'--out' if same[0] == out else 'an LOD output'} ({same[0]}) is the source file", file=sys.stderr)
        return 2
    existing = [p for p in [out] + lod_paths if p.exists()]
    if existing and not args.overwrite:
        print(f"[ENV ] {', '.join(str(p) for p in existing)} exists (use --overwrite)", file=sys.stderr)
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
    bc = common()
    if bc is not None and bpy.data.actions:
        # Blender 4.2 names an imported clip's action "<clip>_<object>"; clips keyed at 30 fps sit every 0.8 frames
        # in the 24 fps scene and the sampled export would drop a loop's closing key (#292)
        bc.adopt_clip_names(bpy)
        bc.conform_clip_fps(bpy, scene, list(bpy.data.actions))
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

    found = texture_nodes(scene) if args.lods and args.lod_textures == "half" else {}
    for level, (ratio, path) in enumerate(zip(args.lods, lod_paths), 1):
        mods = []
        for obj in [o for o in scene.objects if o.type == "MESH"]:
            m = obj.modifiers.new(name="LOD_Decimate", type="DECIMATE")
            m.ratio = ratio
            mods.append((obj, m))
        tris = triangles(bpy, scene)
        # #196: every LOD file is a whole .glb (any engine loads it alone), so each one carries its textures; at half
        # the size of the level before, the copies add a third of the textures' bytes instead of a full set per LOD
        swaps = shrink_textures(bpy, found, 0.5 ** level) if found else []
        px = sorted({max(new.size) for _, new, _, _ in swaps})
        try:
            export(bpy, path)
        finally:
            undo_shrink(bpy, swaps)
        for obj, m in mods:
            obj.modifiers.remove(m)
        print(f"[ OK ] {path} ({tris} triangles, ratio {ratio}"
              + (f", textures {'/'.join(str(p) for p in px)} px" if px else "") + ")")

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


def common():
    """bpy_common.py from this folder (clip names, clip frame rate, the exit), or None for a lone copy of this script."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import bpy_common
    except ImportError:
        return None
    return bpy_common


def exit_with(code):
    """sys.exit, or with the bpy module on Windows the process end that does not crash after a glTF export (#292)."""
    try:
        import bpy
    except ImportError:
        sys.exit(code)
    bc = common()
    if bc is None:
        sys.exit(code)
    bc.end_process(bpy, code)


def end_process(code):
    """The name cleanup.py and rebake_uvs.py call (#293): the same exit as exit_with."""
    exit_with(code)


if __name__ == "__main__":
    exit_with(main())
