#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# cleanup.py
# Purpose : Make a generated mesh (TRELLIS.2's .glb, or any scan-like mesh) fit for a game, in Blender: join the
#           parts, merge vertices that sit on top of each other, drop loose fragments, point every face outward,
#           decimate to the class budget, turn it to face the front, scale it to a height in metres and put the
#           pivot at the bottom centre. Writes one .glb with the kit's glTF preset and a JSON report.
# Usage   : Inside Blender (any OS):
#             blender -b --python-exit-code 1 -P tools/meshwright/cleanup.py -- <raw.glb> --out <clean.glb> [options]
#           With the bpy module (pip install bpy, needs the matching Python version):
#             python tools/meshwright/cleanup.py <raw.glb> --out <clean.glb> [options]
#           Examples:
#             ... -- raw.glb --out clean.glb --name prop_chest --max-tris 2700 --height 0.8
#             ... -- raw.glb --out clean.glb --name npc_guard --max-tris 13500 --height 1.8 --turn 180 --json r.json
# Needs   : Blender 4.2+ or the bpy module
# Exit    : 0 written, 1 the mesh could not be cleaned (no faces left, import failed), 2 usage or environment
# Notes   : meshwright.py runs this between generation and tools/blender/prep_export.py; it also runs on its own.
#           The source file is never changed. Merge distance and the loose-part limit are relative to the mesh
#           (a fraction of its bounds diagonal, a fraction of its faces), so the same defaults work at any scale.
#           Merging welds the vertices glTF splits at UV seams: Blender keeps UVs per face corner, so the texture
#           is unchanged and the parts count is real (a split mesh counts every UV island as a part).
#           Normals: the custom normals from the file are cleared and the mesh is shaded smooth, which matches
#           what TRELLIS.2 bakes its normal map against (smooth normals, crease angle 180).
#           Decimation is Blender's Decimate (collapse); it keeps UVs but can blur a texture seam. Check by eye.
#           --turn rotates around the up axis (degrees, counter-clockwise seen from above) so the model's front
#           faces Blender's front (-Y), which is glTF's +Z: the direction the glTF spec calls the asset's front.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   import (validate_asset's shared importer: empty scene, glTF / FBX / OBJ / .blend)
#   drop cameras, lights and empties' children that are not meshes; join every mesh into one object; apply transforms
#   bmesh: merge by distance -> delete loose vertices and edges -> connected parts by shared edges ->
#          drop parts under --min-part of the faces (the biggest part always stays) -> recalc normals outward
#   clear custom normals, shade smooth
#   triangles > --max-tris: Decimate (collapse) at max / tris, applied (twice if the first pass lands above)
#   rotate --turn around Z -> scale so the height (Z) is --height -> bottom centre to the origin
#   name the object, mesh, materials and images after --name -> export .glb (prep_export's GLTF_PRESET) -> JSON
import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "blender"))   # the kit's Blender tools: shared importer and export preset

DEBUG = False
MERGE_DISTANCE = 0.0001   # fraction of the bounds diagonal: vertices closer than this become one
MIN_PART = 0.01           # parts with fewer than this share of all faces are dropped as fragments
DECIMATE_MARGIN = 0.97    # aim a little under the budget: collapse decimation overshoots by a few triangles


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}")


def script_argv():
    """Blender passes its own args first; ours come after a lone '--'."""
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else argv[1:]


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="cleanup.py",
                                 description="Clean a generated mesh for a game: merge, drop fragments, fix normals, "
                                             "decimate to a budget, scale to a height, pivot at the bottom centre.")
    ap.add_argument("asset", help="source mesh: .glb .gltf .fbx .obj .blend")
    ap.add_argument("--out", required=True, help="the cleaned .glb to write")
    ap.add_argument("--name", default="", help="object, mesh and material name (default: the output file's name)")
    ap.add_argument("--max-tris", type=int, default=0, help="decimate down to this many triangles (default 0: keep)")
    ap.add_argument("--height", type=float, default=0.0, help="scale so the model is this tall in metres (default 0: keep)")
    ap.add_argument("--turn", type=float, default=0.0, help="degrees to rotate around the up axis (default 0)")
    ap.add_argument("--merge", type=float, default=MERGE_DISTANCE,
                    help=f"merge distance as a fraction of the bounds diagonal (default {MERGE_DISTANCE})")
    ap.add_argument("--min-part", type=float, default=MIN_PART,
                    help=f"drop parts with less than this share of the faces (default {MIN_PART}; 0 keeps all)")
    ap.add_argument("--json", dest="json_out", help="write the report (counts before and after) as JSON here")
    ap.add_argument("--overwrite", action="store_true", help="replace --out if it exists")
    ap.add_argument("--debug", action="store_true", help="verbose output and full tracebacks")
    args = ap.parse_args(argv)
    if args.max_tris < 0 or args.height < 0 or not 0 <= args.min_part < 1 or not 0 <= args.merge < 0.1:
        ap.error("need --max-tris >= 0, --height >= 0, 0 <= --min-part < 1 and 0 <= --merge < 0.1")
    return args


def load_modules():
    """bpy plus the kit's validate_asset (importer) and prep_export (glTF preset). Returns (bpy, va, pe) or Nones."""
    try:
        import bpy  # noqa: F401
    except ImportError:
        print("[ENV ] bpy not available. Run inside Blender:\n"
              "         blender -b --python-exit-code 1 -P tools/meshwright/cleanup.py -- <raw.glb> --out <clean.glb>\n"
              "       or with the bpy module for your Python version (uv run --python 3.13 --with bpy python ...)",
              file=sys.stderr)
        return None, None, None
    import prep_export as pe  # noqa: E402
    import validate_asset as va  # noqa: E402
    return bpy, va, pe


def tri_count(mesh):
    mesh.calc_loop_triangles()
    return len(mesh.loop_triangles)


def bounds(mesh):
    """(min, max) corners of a mesh's vertices in its own space."""
    co = [v.co for v in mesh.vertices]
    if not co:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    return (tuple(min(c[i] for c in co) for i in range(3)), tuple(max(c[i] for c in co) for i in range(3)))


def join_all(bpy, scene):
    """Drop everything that is not a mesh, join the meshes into one object, apply its transforms. Returns it."""
    for obj in [o for o in scene.objects if o.type != "MESH"]:
        for child in obj.children:   # keep the world placement of meshes parented to an empty
            mw = child.matrix_world.copy()
            child.parent = None
            child.matrix_world = mw
        bpy.data.objects.remove(obj, do_unlink=True)
    meshes = [o for o in scene.objects if o.type == "MESH"]
    if not meshes:
        return None
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        if o.data.users > 1:
            o.data = o.data.copy()
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def parts(bm):
    """Connected parts of a bmesh as lists of faces (faces sharing an edge are one part)."""
    seen, out = set(), []
    for start in bm.faces:
        if start.index in seen:
            continue
        stack, part = [start], []
        seen.add(start.index)
        while stack:
            f = stack.pop()
            part.append(f)
            for e in f.edges:
                for g in e.link_faces:
                    if g.index not in seen:
                        seen.add(g.index)
                        stack.append(g)
        out.append(part)
    return out


def clean_topology(obj, args, report):
    """Merge, drop loose geometry and fragments, recalc normals. Fills report; returns faces left."""
    import bmesh
    mesh = obj.data
    lo, hi = bounds(mesh)
    diag = math.dist(lo, hi) or 1.0
    bm = bmesh.new()
    bm.from_mesh(mesh)
    before = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=args.merge * diag)
    report["merged_vertices"] = before - len(bm.verts)
    loose_edges = [e for e in bm.edges if not e.link_faces]
    bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")
    loose_verts = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")
    report["loose_removed"] = len(loose_edges) + len(loose_verts)
    bm.faces.ensure_lookup_table()
    bm.faces.index_update()
    found = sorted(parts(bm), key=len, reverse=True)
    total = sum(len(p) for p in found) or 1
    drop = [p for p in found[1:] if len(p) < args.min_part * total]
    report["parts_found"] = len(found)
    report["parts_dropped"] = len(drop)
    report["faces_dropped"] = sum(len(p) for p in drop)
    if drop:
        bmesh.ops.delete(bm, geom=[f for p in drop for f in p], context="FACES")
        orphans = [v for v in bm.verts if not v.link_faces]
        bmesh.ops.delete(bm, geom=orphans, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    left = len(bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    dbg(f"merged {report['merged_vertices']} vertices, {len(found)} parts, dropped {len(drop)}")
    return left


def smooth(bpy, obj):
    """Clear the file's custom normals and shade smooth (what TRELLIS.2 bakes its normal map against)."""
    mesh = obj.data
    if getattr(mesh, "has_custom_normals", False):
        bpy.context.view_layer.objects.active = obj
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    if hasattr(mesh, "shade_smooth"):   # Blender 4.1+
        mesh.shade_smooth()
    else:
        for p in mesh.polygons:
            p.use_smooth = True


def decimate(bpy, obj, max_tris, report):
    """Collapse-decimate until the mesh is at or under max_tris (two passes at most)."""
    for _ in range(2):
        tris = tri_count(obj.data)
        if not max_tris or tris <= max_tris:
            return
        mod = obj.modifiers.new(name="Meshwright_Decimate", type="DECIMATE")
        mod.decimate_type = "COLLAPSE"
        ratio = max(0.001, max_tris / tris * DECIMATE_MARGIN)
        mod.ratio = ratio
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=mod.name)
        report["decimated"] = True
        dbg(f"decimate {tris} -> {tri_count(obj.data)} (ratio {ratio:.4f})")


def place(obj, args, report):
    """Turn around Z, scale to the height, bottom centre at the origin (geometry moves, the object stays at 0)."""
    from mathutils import Matrix
    mesh = obj.data
    if args.turn:
        mesh.transform(Matrix.Rotation(math.radians(args.turn), 4, "Z"))
    lo, hi = bounds(mesh)
    height = hi[2] - lo[2]
    if args.height and height > 0:
        factor = args.height / height
        mesh.transform(Matrix.Scale(factor, 4))
        report["scale_factor"] = round(factor, 6)
        lo, hi = bounds(mesh)
    mesh.transform(Matrix.Translation((-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2])))
    mesh.update()
    obj.location = (0, 0, 0)
    obj.rotation_euler = (0, 0, 0)
    obj.scale = (1, 1, 1)
    lo, hi = bounds(mesh)
    report["size_m"] = [round(hi[i] - lo[i], 4) for i in range(3)]


def rename(obj, name):
    """Object and mesh get the name; materials <name>_mat (<name>_mat_2, ...); their images <name>_<socket>."""
    obj.name = name
    obj.data.name = name
    for i, slot in enumerate(obj.material_slots):
        mat = slot.material
        if mat is None:
            continue
        mat.name = f"{name}_mat" + (f"_{i + 1}" if i else "")
        if mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image is not None:
                links = node.outputs["Color"].links if "Color" in node.outputs else []
                role = links[0].to_socket.name.lower().replace(" ", "_") if links else "tex"
                node.image.name = f"{name}_{role}"


def run(args):
    src, out = Path(args.asset), Path(args.out)
    if not src.is_file():
        print(f"[ENV ] mesh not found: {src}", file=sys.stderr)
        return 2
    if out.suffix.lower() != ".glb":
        print("[ENV ] --out must end in .glb", file=sys.stderr)
        return 2
    if out.exists() and not args.overwrite:
        print(f"[ENV ] {out} exists (use --overwrite)", file=sys.stderr)
        return 2
    bpy, va, pe = load_modules()
    if bpy is None:
        return 2
    try:
        va.import_asset(bpy, src.resolve())
    except ValueError as exc:
        print(f"[ENV ] {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"[FAIL] import failed: {exc}", file=sys.stderr)
        return 1
    scene = bpy.context.scene
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    obj = join_all(bpy, scene)
    if obj is None:
        print("[FAIL] no mesh in the file", file=sys.stderr)
        return 1
    report = {"source": src.name, "tris_in": tri_count(obj.data), "vertices_in": len(obj.data.vertices),
              "decimated": False}
    if not clean_topology(obj, args, report):
        print("[FAIL] no faces left after cleanup", file=sys.stderr)
        return 1
    smooth(bpy, obj)
    decimate(bpy, obj, args.max_tris, report)
    place(obj, args, report)
    rename(obj, args.name or out.stem)
    report["tris_out"] = tri_count(obj.data)
    report["vertices_out"] = len(obj.data.vertices)
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(out.resolve()), **pe.GLTF_PRESET)
    print(f"[ OK ] {out} ({report['tris_in']} -> {report['tris_out']} triangles, "
          f"{report['merged_vertices']} vertices merged, {report['parts_dropped']} of {report['parts_found']} parts "
          f"dropped, size {report['size_m']} m)")
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


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
        if DEBUG:
            raise
        return 1
    except Exception as exc:  # keep the exit-code contract even on surprises
        print(f"[ENV ] cleanup crashed: {exc!r}. Re-run with --debug and paste the output.", file=sys.stderr)
        if DEBUG:
            raise
        return 2


if __name__ == "__main__":
    sys.exit(main())
