#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# validate_asset.py
# Purpose : Check a 3D asset against the SOP-11 budgets before it enters the game:
#           triangle count, size in meters, unapplied scale, pivot position,
#           object naming, missing UVs, UV coverage, UV island count, UV overlap,
#           texel-density spread, and missing or unpacked texture files (including files a
#           .glb/.gltf refers to that are not next to it: a re-export drops that texture silently), and
#           faces stored twice back to back (double-sided geometry baked into the mesh).
# Usage   : Inside Blender (any OS):
#             blender -b --python-exit-code 1 -P tools/blender/validate_asset.py -- <asset> [options]
#           With the bpy module (pip install bpy, needs the matching Python version):
#             python tools/blender/validate_asset.py <asset> [options]
#           Examples:
#             ... -- assets/models/crate.glb --class prop
#             ... -- assets/models/hero.glb --class hero --json reports/hero.json
#             ... -- kit_wall.fbx --max-tris 4000 --max-dim 6 --strict
# Needs   : Blender 4.x or 5.x, or the bpy module. Standard library otherwise.
# Exit    : 0 pass, 1 failed checks (or warnings with --strict), 2 usage or environment problem
# Notes   : Supported inputs: .glb .gltf .fbx .obj .blend. The file is imported into an
#           empty scene, never modified or saved.
#           UV coverage is measured by rasterizing UV triangles onto a grid (default 128x128),
#           so it is an estimate. Good enough to catch the "tiny islands" failure that AI
#           unwrapping produces (docs/EVIDENCE.md F12).
#           Budgets per class mirror SOP-11. Override any of them with flags.
#           Exam: tools/blender/test_validate_asset.py builds known-good and known-bad assets
#           and checks this script catches each one.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-10-21 (audit pass 7): UV islands linked by vertex position, so flat-shaded glTF
#           (split vertices) no longer reads as fragmented
#           2026-10-24: launch lines pass --python-exit-code 1, else Blender exits 0 after a traceback
#           (--debug re-raises) (E64, tested on Blender 5.2)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   parse args (after "--" when run inside Blender)
#   import bpy, or exit 2 with install hints
#   reset to an empty scene, import the asset by extension
#   for every mesh object:
#       count triangles, measure world-space size, check scale applied, pivot near base
#       check name pattern
#       if no UV layer: fail
#       else: islands (union-find on UV-connected faces), coverage and overlap (raster grid),
#             texel density per island (UV area / surface area), spread = max / min
#   before import: read the glTF JSON, every image/buffer uri must exist next to the file
#   check images: missing files, empty data
#   compare totals with the budget for --class (or explicit flags)
#   print a readable report (and JSON if asked), return exit code
import argparse
import json
import math
import re
import struct
import sys
from pathlib import Path
from urllib.parse import unquote

DEBUG = False
FBX_UNIT_SCALES = (0.01, 100.0)  # centimeters <-> meters: FBX unit scale, not a modelling mistake

# Budgets from docs/sop/SOP-11-3d-pipeline.md. Triangles are totals for the file.
CLASS_BUDGETS = {
    "prop":  {"max_tris": 3000,  "max_dim": 3.0,  "min_uv_coverage": 0.50},
    "kit":   {"max_tris": 8000,  "max_dim": 12.0, "min_uv_coverage": 0.40},
    "hero":  {"max_tris": 60000, "max_dim": 3.0,  "min_uv_coverage": 0.60},
    "npc":   {"max_tris": 15000, "max_dim": 3.0,  "min_uv_coverage": 0.55},
    "any":   {"max_tris": 100000, "max_dim": 100.0, "min_uv_coverage": 0.30},
}
DEFAULT_NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]*$"  # letters, digits, underscore, hyphen; no spaces or dots
UV_EPS = 1e-5


def dbg(msg):
    """Print only with --debug."""
    if DEBUG:
        print(f"[debug] {msg}")


# ---------------------------------------------------------------- arguments
def script_argv():
    """Blender passes its own args first; ours come after a lone '--'."""
    argv = sys.argv
    if "--" in argv:
        return argv[argv.index("--") + 1:]
    return argv[1:]


def parse_args(argv):
    ap = argparse.ArgumentParser(
        prog="validate_asset.py",
        description="Validate a 3D asset against SOP-11 budgets (tris, size, scale, pivot, names, UVs, textures).",
        epilog=("Run inside Blender: blender -b --python-exit-code 1 -P tools/blender/validate_asset.py -- <asset> [options]. "
                "Or with the bpy module: python tools/blender/validate_asset.py <asset>. "
                "Exit 0 pass, 1 fail, 2 usage/environment."),
    )
    ap.add_argument("asset", help="path to .glb, .gltf, .fbx, .obj or .blend")
    ap.add_argument("--class", dest="asset_class", choices=sorted(CLASS_BUDGETS), default="any",
                    help="budget preset from SOP-11 (default: any, very loose)")
    ap.add_argument("--max-tris", type=int, help="override the triangle budget for the whole file")
    ap.add_argument("--max-dim", type=float, help="override the largest allowed size in meters")
    ap.add_argument("--min-dim", type=float, default=0.01, help="smallest sane size in meters (default 0.01)")
    ap.add_argument("--min-uv-coverage", type=float, help="override minimum UV coverage, 0 to 1")
    ap.add_argument("--max-islands", type=int, default=0,
                    help="warn above this many UV islands per mesh (default 0 = auto: over 16 and over one island per 4 triangles)")
    ap.add_argument("--max-texel-spread", type=float, default=2.0,
                    help="warn if texel density between islands differs more than this factor (default 2.0)")
    ap.add_argument("--name-pattern", default=DEFAULT_NAME_PATTERN, help="regex object names must match")
    ap.add_argument("--grid", type=int, default=128, help="UV raster grid size for coverage (default 128)")
    ap.add_argument("--json", dest="json_out", help="also write the report as JSON to this path")
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    ap.add_argument("--debug", action="store_true", help="print extra detail")
    args = ap.parse_args(argv)
    budget = dict(CLASS_BUDGETS[args.asset_class])
    if args.max_tris is not None:
        budget["max_tris"] = args.max_tris
    if args.max_dim is not None:
        budget["max_dim"] = args.max_dim
    if args.min_uv_coverage is not None:
        budget["min_uv_coverage"] = args.min_uv_coverage
    args.budget = budget
    return args


# ---------------------------------------------------------------- bpy access
def load_bpy():
    """Import bpy or explain how to get it. Returns the module or None."""
    try:
        import bpy  # noqa: F401
        return bpy
    except ImportError:
        print("[ENV ] bpy not available. Run inside Blender:\n"
              "         blender -b --python-exit-code 1 -P tools/blender/validate_asset.py -- <asset>\n"
              "       or install the module for your Python version: pip install bpy\n"
              "       (bpy 5.2 needs Python 3.13; with uv: uv run --python 3.13 --with bpy python tools/blender/validate_asset.py <asset>)",
              file=sys.stderr)
        return None


def gltf_missing_files(path):
    """Image and buffer files a .gltf/.glb refers to that do not exist next to it.

    Kenney-style packs ship .glb files that point to Textures/colormap.png. Moved without that folder, the model
    imports with an empty image and a re-export (prep_export) drops the texture without a word, so this reads the
    glTF JSON itself and prep_export runs it on the source before exporting.
    """
    path = Path(path)
    try:
        if path.suffix.lower() == ".glb":
            data = path.read_bytes()
            if data[:4] != b"glTF" or data[16:20] != b"JSON":
                return []
            (size,) = struct.unpack_from("<I", data, 12)
            doc = json.loads(data[20:20 + size].decode("utf-8"))
        elif path.suffix.lower() == ".gltf":
            doc = json.loads(path.read_text(encoding="utf-8"))
        else:
            return []
    except (OSError, ValueError, struct.error):
        return []  # unreadable here: the import itself will report it
    missing = []
    for item in doc.get("images", []) + doc.get("buffers", []):
        uri = item.get("uri")
        if uri and not uri.startswith("data:") and not (path.parent / unquote(uri)).exists():
            missing.append(uri)
    return missing


def import_asset(bpy, path):
    """Empty the scene, then import by extension. Raises ValueError on unsupported types."""
    ext = path.suffix.lower()
    if ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(path))
        return
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(path))
        drop_bone_shapes(bpy)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    elif ext == ".obj":
        # Blender 4+ uses wm.obj_import; older builds had import_scene.obj
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=str(path))
        else:
            bpy.ops.import_scene.obj(filepath=str(path))
    else:
        raise ValueError(f"unsupported file type '{ext}' (use .glb .gltf .fbx .obj .blend)")


def drop_bone_shapes(bpy):
    """Blender's glTF importer gives rigged models an 'Icosphere' object as the bones' display shape.
    It is not in the file and never reaches a game engine, so remove it before any check or render."""
    shapes = set()
    for arm in [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]:
        for pb in arm.pose.bones:
            if pb.custom_shape is not None:
                shapes.add(pb.custom_shape.name)
                pb.custom_shape = None
    for name in shapes:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)


def back_to_back_pairs(mesh):
    """Faces stored twice on the same spot, facing opposite ways (double-sided geometry baked into the mesh,
    as Kenney's Tower Defense Kit ships). Returns [(keep, drop)] face indices: keep the twin that faces away
    from the mesh's middle."""
    from collections import defaultdict
    from mathutils import Vector
    if not mesh.polygons:
        return []
    groups = defaultdict(list)
    for p in mesh.polygons:
        c = p.center
        groups[(round(c.x, 4), round(c.y, 4), round(c.z, 4))].append(p)
    if all(len(g) == 1 for g in groups.values()):
        return []
    mid = sum((p.center for p in mesh.polygons), Vector()) / len(mesh.polygons)
    pairs, used = [], set()
    for g in groups.values():
        for i, p in enumerate(g):
            for q in g[i + 1:]:
                if p.index in used or q.index in used or p.normal.dot(q.normal) > -0.99:
                    continue
                outward_p, outward_q = p.normal.dot(p.center - mid), q.normal.dot(q.center - mid)
                keep, drop = (p, q) if outward_p >= outward_q else (q, p)
                pairs.append((keep.index, drop.index))
                used.update((p.index, q.index))
    return pairs


def drop_back_to_back(bpy):
    """Delete the inner twin of every back-to-back face pair in the scene. Returns how many faces went.
    Cycles renders such pairs black (a shadow ray leaving one face hits its twin); renderers that draw both
    sides of a face, like Blender, lose nothing."""
    import bmesh
    removed = 0
    for obj in [o for o in bpy.context.scene.objects if o.type == "MESH"]:
        pairs = back_to_back_pairs(obj.data)
        if not pairs:
            continue
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[bm.faces[d] for _, d in pairs], context="FACES_ONLY")
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
        removed += len(pairs)
    return removed


# ---------------------------------------------------------------- geometry
def world_bounds(obj):
    """Axis-aligned world-space bounds (min, max) as 3-tuples."""
    pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    if not pts:
        return (0, 0, 0), (0, 0, 0)
    mins = tuple(min(p[i] for p in pts) for i in range(3))
    maxs = tuple(max(p[i] for p in pts) for i in range(3))
    return mins, maxs


def triangle_count(mesh):
    """Triangles after triangulation, the number the GPU actually draws."""
    mesh.calc_loop_triangles()
    return len(mesh.loop_triangles)


def tri_area_2d(a, b, c):
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2.0


def tri_area_3d(a, b, c):
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    cx = ab[1] * ac[2] - ab[2] * ac[1]
    cy = ab[2] * ac[0] - ab[0] * ac[2]
    cz = ab[0] * ac[1] - ab[1] * ac[0]
    return math.sqrt(cx * cx + cy * cy + cz * cz) / 2.0


# ---------------------------------------------------------------- UV analysis
class UnionFind:
    """Tiny union-find for grouping faces into UV islands."""

    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def uv_islands(mesh, uv_layer):
    """
    Pseudocode: two faces are in the same island when they share an edge AND
    both loops on that edge carry the same UVs. Union-find over those pairs.
    Returns a list with the island id for each polygon.
    Edges are keyed by vertex POSITION, not vertex index: glTF splits vertices at every
    hard-normal edge, so a flat-shaded mesh would otherwise come back as one island per face.
    """
    uf = UnionFind(len(mesh.polygons))
    pos = [tuple(round(c, 5) for c in v.co) for v in mesh.vertices]
    # map (pos_a, pos_b) sorted -> list of (poly index, uv_a, uv_b)
    edge_map = {}
    for poly in mesh.polygons:
        loops = list(poly.loop_indices)
        for i, li in enumerate(loops):
            lj = loops[(i + 1) % len(loops)]
            va, vb = pos[mesh.loops[li].vertex_index], pos[mesh.loops[lj].vertex_index]
            uva, uvb = tuple(uv_layer.data[li].uv), tuple(uv_layer.data[lj].uv)
            key = (va, vb) if va < vb else (vb, va)
            ordered = (uva, uvb) if va < vb else (uvb, uva)
            edge_map.setdefault(key, []).append((poly.index, ordered))
    for entries in edge_map.values():
        for k in range(1, len(entries)):
            p0, (a0, b0) = entries[0]
            pk, (ak, bk) = entries[k]
            if (abs(a0[0] - ak[0]) < UV_EPS and abs(a0[1] - ak[1]) < UV_EPS
                    and abs(b0[0] - bk[0]) < UV_EPS and abs(b0[1] - bk[1]) < UV_EPS):
                uf.union(p0, pk)
    return [uf.find(p.index) for p in mesh.polygons]


def raster_uv(mesh, uv_layer, grid, island_of_poly):
    """
    Pseudocode: for each UV triangle, test the grid cell centers inside its
    bounding box with a barycentric sign test; remember which island first
    covered each cell. A cell hit by a second, different island is overlap.
    (Triangles of the same island share edges, so same-island hits are not
    counted as overlap. Folds inside one island are not detected.)
    Returns (coverage 0..1, overlap fraction of covered cells, out_of_bounds tris).
    """
    owner = [-1] * (grid * grid)
    overlap_cells = set()
    out_of_bounds = 0
    for tri in mesh.loop_triangles:
        uvs = [tuple(uv_layer.data[li].uv) for li in tri.loops]
        if any(u < -UV_EPS or u > 1 + UV_EPS or v < -UV_EPS or v > 1 + UV_EPS for u, v in uvs):
            out_of_bounds += 1
        (x0, y0), (x1, y1), (x2, y2) = uvs
        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denom) < 1e-12:
            continue  # zero-area UV triangle
        isl = island_of_poly[tri.polygon_index]
        min_c = max(0, int(min(x0, x1, x2) * grid))
        max_c = min(grid - 1, int(max(x0, x1, x2) * grid))
        min_r = max(0, int(min(y0, y1, y2) * grid))
        max_r = min(grid - 1, int(max(y0, y1, y2) * grid))
        for r in range(min_r, max_r + 1):
            py = (r + 0.5) / grid
            for c in range(min_c, max_c + 1):
                px = (c + 0.5) / grid
                w0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / denom
                w1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / denom
                if w0 >= 0 and w1 >= 0 and (1 - w0 - w1) >= 0:
                    cell = r * grid + c
                    if owner[cell] == -1:
                        owner[cell] = isl
                    elif owner[cell] != isl:
                        overlap_cells.add(cell)
    covered = sum(1 for o in owner if o != -1)
    overlapped = len(overlap_cells)
    coverage = covered / float(grid * grid)
    overlap = (overlapped / float(covered)) if covered else 0.0
    return coverage, overlap, out_of_bounds


def texel_spread(mesh, uv_layer, island_of_poly, matrix):
    """Ratio between the densest and sparsest island (UV area per world area)."""
    per_island = {}
    for tri in mesh.loop_triangles:
        uvs = [tuple(uv_layer.data[li].uv) for li in tri.loops]
        pos = [tuple(matrix @ mesh.vertices[vi].co) for vi in tri.vertices]
        a_uv = tri_area_2d(*uvs)
        a_3d = tri_area_3d(*pos)
        isl = island_of_poly[tri.polygon_index]
        tot = per_island.setdefault(isl, [0.0, 0.0])
        tot[0] += a_uv
        tot[1] += a_3d
    densities = [uv / area for uv, area in per_island.values() if area > 1e-12 and uv > 1e-12]
    if len(densities) < 2:
        return 1.0
    # sqrt: area ratio -> texel (linear) ratio
    return math.sqrt(max(densities) / min(densities))


# ---------------------------------------------------------------- checks
PALETTE_SHARE = 0.9      # this share of UV triangles with (almost) zero area = palette/colormap texturing
PALETTE_AREA = 1e-6


def uv_mode(obj, mesh, uv_layer):
    """How the mesh uses its UVs: 'untextured' (it has materials, none with an image texture), 'palette'
    (UV triangles collapsed onto color swatches, the low-poly colormap technique), or 'unwrapped'.
    A mesh without any material keeps the full checks: nothing says it will not be textured later."""
    mats = [m for m in obj.data.materials if m is not None]
    if mats and not any(m.node_tree is not None and any(n.type == "TEX_IMAGE" for n in m.node_tree.nodes) for m in mats):
        return "untextured"
    mesh.calc_loop_triangles()
    tris = mesh.loop_triangles
    if not tris:
        return "unwrapped"
    data = uv_layer.data
    tiny = sum(1 for t in tris if tri_area_2d(*(data[i].uv for i in t.loops)) < PALETTE_AREA)
    return "palette" if tiny / len(tris) >= PALETTE_SHARE else "unwrapped"


def check_mesh(obj, args, report):
    """Run every per-object check and append findings to report."""
    mesh = obj.data
    name = obj.name
    tris = triangle_count(mesh)
    mins, maxs = world_bounds(obj)
    size = tuple(maxs[i] - mins[i] for i in range(3))
    info = {"object": name, "tris": tris, "size_m": [round(s, 4) for s in size]}
    twins = back_to_back_pairs(mesh)
    if twins:
        info["back_to_back_pairs"] = len(twins)
        report.warn(f"{name}: {len(twins)} faces are stored twice, back to back (double-sided geometry in the mesh): "
                    f"twice the triangles in an engine, and Cycles renders them black (render_sprites.py removes the "
                    f"inner twin; for a game mesh, delete one side in Blender and set the material double-sided if needed)")
    dbg(f"{name}: {tris} tris, size {info['size_m']}")

    if max(size) > args.budget["max_dim"]:
        report.fail(f"{name}: largest side {max(size):.2f} m is over {args.budget['max_dim']} m (wrong units? 1 unit = 1 m)")
    if max(size) < args.min_dim:
        report.fail(f"{name}: largest side {max(size):.4f} m is under {args.min_dim} m (exported in cm or mm?)")
    if any(abs(s - 1.0) > 1e-4 for s in obj.scale):
        uniform = max(obj.scale) - min(obj.scale) < 1e-6
        if Path(str(report.asset)).suffix.lower() == ".fbx" and uniform and any(
                abs(obj.scale[0] - u) < 1e-6 for u in FBX_UNIT_SCALES):
            # Blender's FBX importer turns the file's unit (centimeters) into object scale; engines convert it
            report.note(f"{name}: FBX unit scale {round(obj.scale[0], 4)} (the file is in another unit): normal, "
                        f"sizes above are already in meters")
        else:
            report.warn(f"{name}: unapplied scale {tuple(round(s, 3) for s in obj.scale)} (apply scale before export)")
    # Pivot: object origin should sit near the base center or the bounds center.
    origin = obj.matrix_world.translation
    cx, cy = (mins[0] + maxs[0]) / 2, (mins[1] + maxs[1]) / 2
    base_center = (cx, cy, mins[2])
    bounds_center = (cx, cy, (mins[2] + maxs[2]) / 2)
    dist = min(math.dist(tuple(origin), base_center), math.dist(tuple(origin), bounds_center))
    if max(size) > 0 and dist > 0.25 * max(size) + 0.01:
        report.warn(f"{name}: origin is {dist:.2f} m from both the base center and the bounds center "
                    "(pivot off; placement and rotation will look wrong)")
    if not re.match(args.name_pattern, name):
        report.warn(f"{name}: name does not match {args.name_pattern!r} (spaces or dots break engine imports)")

    if not mesh.uv_layers:
        report.fail(f"{name}: no UV map (texturing and lightmaps will fail)")
        report.objects.append(info)
        return tris
    uv_layer = mesh.uv_layers.active or mesh.uv_layers[0]
    mode = uv_mode(obj, mesh, uv_layer)
    info["uv_mode"] = mode
    if mode != "unwrapped":
        # Coverage, islands, overlap and texel density only mean something for an unwrapped texture
        report.note(f"{name}: {'palette (colormap) texturing: each face samples one color swatch' if mode == 'palette' else 'materials use no image texture'}; UV layout checks skipped")
        report.objects.append(info)
        return tris
    island_of_poly = uv_islands(mesh, uv_layer)
    islands = len(set(island_of_poly))
    coverage, overlap, oob = raster_uv(mesh, uv_layer, args.grid, island_of_poly)
    spread = texel_spread(mesh, uv_layer, island_of_poly, obj.matrix_world)
    info.update({"uv_islands": islands, "uv_coverage": round(coverage, 3),
                 "uv_overlap": round(overlap, 3), "uv_out_of_bounds_tris": oob,
                 "texel_spread": round(spread, 2)})
    dbg(f"{name}: islands {islands}, coverage {coverage:.3f}, overlap {overlap:.3f}, spread {spread:.2f}")

    if coverage < args.budget["min_uv_coverage"]:
        report.fail(f"{name}: UV coverage {coverage:.0%} is under {args.budget['min_uv_coverage']:.0%} (tiny islands waste texture space)")
    # Default heuristic: fragmented means many islands AND an average island under 4 triangles.
    # Triangles, not faces, because glTF and FBX imports often arrive triangulated.
    # A cube (12 tris, 6 islands) is fine; a 200-triangle floor in 100 islands is the AI-unwrap failure.
    if args.max_islands:
        max_islands = args.max_islands
        fragmented = islands > max_islands
    else:
        max_islands = max(16, tris // 4)
        fragmented = islands > max_islands
    if fragmented:
        report.warn(f"{name}: {islands} UV islands (over {max_islands}); looks fragmented, re-unwrap with fewer seams")
    if overlap > 0.05:
        report.warn(f"{name}: {overlap:.0%} of used UV space overlaps (fine only for intentional mirroring)")
    if oob:
        report.warn(f"{name}: {oob} triangles have UVs outside 0..1 (fine for tiling materials, wrong for baked maps)")
    if spread > args.max_texel_spread:
        report.warn(f"{name}: texel density varies {spread:.1f}x between islands (over {args.max_texel_spread}x)")
    report.objects.append(info)
    return tris


def check_images(bpy, report, already=()):
    """Missing or empty texture images (file names in `already` were reported by gltf_missing_files)."""
    for img in bpy.data.images:
        if img.type not in ("IMAGE",) or img.name in ("Render Result", "Viewer Node"):
            continue
        if img.packed_file is None and img.filepath:
            path = Path(bpy.path.abspath(img.filepath))
            if not path.exists() and path.name not in already:
                report.fail(f"texture '{img.name}' points to a missing file: {path}")
        elif img.packed_file is None and not img.filepath and not img.has_data:
            report.warn(f"texture '{img.name}' has no file and no data")


class Report:
    """Collects failures, warnings and per-object numbers."""

    def __init__(self, asset, budget):
        self.asset, self.budget = asset, budget
        self.failures, self.warnings, self.objects, self.notes = [], [], [], []
        self.total_tris = 0

    def fail(self, msg):
        self.failures.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def note(self, msg):
        self.notes.append(msg)

    def as_dict(self):
        return {"asset": str(self.asset), "budget": self.budget, "total_tris": self.total_tris,
                "objects": self.objects, "failures": self.failures, "warnings": self.warnings, "notes": self.notes}

    def print(self):
        print(f"Asset  : {self.asset}")
        print(f"Budget : {self.budget}")
        print(f"Tris   : {self.total_tris}")
        for o in self.objects:
            print(f"  - {o}")
        for n in self.notes:
            print(f"[info] {n}")
        for f in self.failures:
            print(f"[FAIL] {f}")
        for w in self.warnings:
            print(f"[WARN] {w}")
        if not self.failures and not self.warnings:
            print("[ OK ] asset passes every check")


def run(args):
    """Validate one asset. Returns the exit code."""
    path = Path(args.asset)
    if not path.exists():
        print(f"[ENV ] asset not found: {path}", file=sys.stderr)
        return 2
    bpy = load_bpy()
    if bpy is None:
        return 2
    try:
        import_asset(bpy, path.resolve())
    except ValueError as exc:
        print(f"[ENV ] {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:  # bpy operator errors arrive as RuntimeError
        print(f"[FAIL] import failed: {exc}", file=sys.stderr)
        return 1

    report = Report(path, args.budget)
    missing = gltf_missing_files(path)
    for uri in missing:
        report.fail(f"the file refers to '{uri}', which is not next to it: an export from here loses that texture "
                    "(keep the pack's folder layout, e.g. Textures/ beside the model)")
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        report.fail("no mesh objects found in the file")
    for obj in meshes:
        report.total_tris += check_mesh(obj, args, report)
    if report.total_tris > args.budget["max_tris"]:
        report.fail(f"total {report.total_tris} triangles is over the budget of {args.budget['max_tris']}")
    check_images(bpy, report, {Path(unquote(u)).name for u in missing})

    report.print()
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
        print(f"JSON   : {args.json_out}")
    if report.failures or (args.strict and report.warnings):
        return 1
    return 0


def main():
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # Windows pipes default to cp1252
        except (AttributeError, ValueError):
            pass
    try:
        args = parse_args(script_argv())
    except SystemExit as exc:  # argparse exits 2 on bad usage and 0 on -h
        return int(exc.code or 0)
    DEBUG = args.debug
    try:
        return run(args)
    except Exception as exc:  # keep the exit-code contract even on surprises
        print(f"[ENV ] validator crashed: {exc!r}. Re-run with --debug and paste the output.", file=sys.stderr)
        if DEBUG:
            raise
        return 2


if __name__ == "__main__":
    code = main()
    # Inside Blender, sys.exit keeps the code for the calling shell.
    sys.exit(code)
