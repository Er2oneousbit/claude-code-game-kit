#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# rig_chain.py
# Purpose : Secondary motion in Blender: select a part of a rigged character (a scarf tail, cape, ponytail, tail),
#           give it its own chain of bones weighted along it, key a sway into every looping clip that keeps the clip
#           looping exactly, optionally bake a cloth simulation into one-shot clips, run rig_finish.py's rig checks
#           and write one .glb plus a JSON report (and a contact sheet).
# Usage   : Inside Blender: blender -b --python-exit-code 1 -P tools/bozzetto/rig_chain.py -- <rigged.glb> --out <out.glb>
#             --part colour:#c8202a~0.15 [--part ...] [--bones 4] [--parent Neck] [--sway 8,idle=4] [--lag 0.12]
#             [--cloth hit,death|oneshots|none] [--loop CLIPS] [--rebuild auto|strip|no] [--report r.json]
#             [--sheet chain.png] [--debug]
#           With the bpy module: python tools/bozzetto/rig_chain.py <rigged.glb> --out <out.glb> ...
#           Usually run by `bozzetto.py rig chain` (chain.py), which keeps the backup and the record.
# Needs   : Blender 4.2+ or the bpy module (numpy comes with both)
# Exit    : 0 written, 1 the part was refused or the result failed a check, 2 usage or environment
# Notes   : Selectors are parsed by chain.py (standard library). A selection is made of faces: by colour (the base
#           texture sampled at each face's UVs, else the colour attribute, else the material colour), vertex group,
#           material or a box. Only its largest connected piece is used (vertices at the same place count as
#           joined: glTF splits them at every seam); smaller pieces are named in the report and left alone.
#           The part's length runs from the point nearest its parent bone, measured over the surface (so a curled
#           tail is followed, not cut across); a centreline is the middle of each slice along that length.
#           Refusals: nothing selected (the closest colour found is named), more than MAX_PART_SHARE of a mesh, or a
#           lump (not longer than it is wide, and not a thin sheet either).
#           Shapes: a part that is its own shell is separated from the body. With too few rows along its length to
#           bend (a box with two ends), it is cut by planes across the centreline: the look does not change at all.
#           A part fused to the body along its length (a generated mesh where the scarf is just a red area of one
#           surface) cannot swing without tearing: it is rebuilt as a strip (a box section along the centreline,
#           width and thickness measured slice by slice, texture coordinates or colours projected from the
#           original, its material reused), laid on top; the original surface stays on the body. A strip keeps the
#           colours and pattern seen from the front, not folds, fringes, knots or tassels.
#           Weights: a "hat" blend between neighbouring chain bones, and the first half bone blended into the parent
#           so the root never leaves the body. The parent is the nearest bone of the spine line (root to the
#           highest bone: hips, spine, neck, head) unless --parent names one.
#           Motion: a clip loops when its first and last poses match (LOOP_TOL); its sway is a whole number of
#           cycles over the clip's own frame range, each bone --lag of a cycle behind its parent, swinging outward
#           (away from the parent bone, never into the body: a symmetric swing put a scarf on the back inside the
#           torso half the time) and half as much sideways; keys on every frame, the phase taken modulo the loop
#           length, so the last frame is the first. One-shots named in --cloth: a ribbon proxy pinned to the parent
#           bone gets Blender's cloth simulation over the clip's frames, colliding with the body meshes, then each
#           chain bone is turned to follow the ribbon, frame by frame. Other one-shots: the chain follows the body.
#           The sway itself collides with nothing. Body bones' keys are never touched: the report checks it.
#           Blender 4.2: its glTF importer names an action "<clip>_<armature>" while the NLA track keeps the clip's
#           name, so actions are renamed from their tracks. The bpy module crashes while the process ends on
#           Windows (4.2 after a glTF export, 5.3 after a render), so with the module the script ends the process
#           itself once its files are written.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   import -> one armature, skinned meshes (others dropped as rig_finish does) -> clips noted, NLA strips cleared
#   per part: select faces (terms intersected) on every mesh, keep the mesh with the most, largest piece
#             -> refuse empty / most of the mesh -> parent bone -> root point -> distances over the surface
#             -> centreline from slices -> lump? refuse -> fused along its length? (or --rebuild strip) -> strip
#             else separate; rows < needed -> cut across the centreline
#             -> N bones along the centreline, parented -> weights along it
#   clips: loop? -> sway keys | one-shot in --cloth -> cloth ribbon, follow it | else nothing
#   checks: rig_finish weights + deform, chain weights, every chain bone used, loops still exact, body keys equal
#   export (clips as glTF animations) -> report -> --sheet
import argparse
import heapq
import json
import math
import sys
from pathlib import Path

import bpy  # first: with the bpy module, bmesh and mathutils exist only once bpy is imported
import bmesh
import numpy as np
from mathutils import Matrix, Quaternion, Vector, interpolate
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import chain as ch  # noqa: E402  (selector parsing, standard library)
import rig_finish as rf  # noqa: E402  (the rig checks, the biped frame)

# --- tunables -------------------------------------------------------------------------------------------------
MAX_PART_SHARE = 0.40       # a part may hold at most this share of its mesh's faces
NEAR_MISS = 0.35            # an empty colour selection this close to a colour suggests a wider tolerance
MIN_ELONGATION = 1.6        # longest / middle extent: under this AND ...
SHEET_RATIO = 3.0           # ... middle / thinnest extent under this too, the part is a lump (refused)
FUSED_SHARE = 0.35          # the part shares vertices with the body beyond this share of its length: fused
ROWS_PER_BONE, MIN_ROWS = 2, 8   # rows along the part needed to bend: per bone, and at least
ROOT_BLEND = 0.5            # the first half bone blends into the parent bone
ROOT_BAND = 0.5             # root vertices: within this share of the part's width of the nearest to the parent
THICK_MIN, THICK_MAX = 0.08, 0.5  # a rebuilt strip's thickness, as a share of its width
LIFT = 0.004                # a strip laid on a fused surface floats this share of its length above it
WELD = 1e-5                 # vertices closer than this (metres) count as one when following the surface
LOOP_TOL = 2e-3             # first and last pose of a loop: largest channel difference allowed
SWAY_SECONDS = 1.5          # about one sway cycle this long; a loop always gets a whole number of cycles
SWAY_SIDE = 0.5             # the second swing axis gets this share of the amplitude, a quarter cycle apart
# the cloth bake; air damping and the impulse clamp were raised after a fast lean-and-return flung the scarf
# straight out behind the back (a pendulum, the body pushing it out at full speed)
CLOTH = {"quality": 8, "mass": 0.2, "tension_stiffness": 30.0, "compression_stiffness": 30.0,
         "bending_stiffness": 0.8, "air_damping": 3.0, "pin_stiffness": 1.0}
COLLIDE = 0.006             # metres the cloth keeps from the body while it is simulated
CLOTH_COLLIDE = {"distance_min": COLLIDE, "impulse_clamp": 0.02, "collision_quality": 3}
SHEET_W, SHEET_FRAMES = 192, 6
SIDE, FRONT, UP = rf.SIDE, rf.FRONT, rf.UP
DEBUG = False


class Refuse(Exception):
    """Exit 1: the part cannot get a chain (said plainly)."""


class Usage(Exception):
    """Exit 2: an option names something the file does not have."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}")


def parse():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser(prog="rig_chain.py", description="Bone chains and secondary motion for a rig.")
    ap.add_argument("rigged", help="a rigged .glb (rig make's <name>_rigged.glb)")
    ap.add_argument("--out", required=True, help="the .glb to write")
    ap.add_argument("--part", action="append", required=True, help="[label=]selector (chain.py lists them)")
    ap.add_argument("--bones", type=int, default=ch.BONES_DEFAULT)
    ap.add_argument("--parent")
    ap.add_argument("--sway", default=ch.SWAY_DEFAULT)
    ap.add_argument("--lag", type=float, default=ch.LAG_DEFAULT)
    ap.add_argument("--cloth", default="none")
    ap.add_argument("--loop", default="none")
    ap.add_argument("--rebuild", choices=("auto", "strip", "no"), default="auto")
    ap.add_argument("--report")
    ap.add_argument("--sheet")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args(argv)
    try:
        a.parts = [ch.parse_part(p, i) for i, p in enumerate(a.part, 1)]
        a.sway_default, a.sway_per = ch.parse_sway(a.sway)
    except ValueError as e:
        ap.error(str(e))
    if not 2 <= a.bones <= ch.BONES_MAX:
        ap.error(f"--bones from 2 to {ch.BONES_MAX}")
    a.cloth_clips = ch.parse_clips(a.cloth)
    a.loop_clips = ch.parse_clips(a.loop)
    return a


# --- colours --------------------------------------------------------------------------------------------------
def to_srgb(c):
    c = np.clip(np.asarray(c, dtype=np.float64), 0.0, 1.0)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def base_image(mat):
    """The image feeding the material's base colour (through any mix or multiply nodes), or None."""
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return None
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return None
    stack, seen = [l.from_node for l in bsdf.inputs["Base Color"].links], set()
    while stack:
        n = stack.pop()
        if n.name in seen:
            continue
        seen.add(n.name)
        if n.type == "TEX_IMAGE" and n.image is not None:
            return n.image
        for i in n.inputs:
            stack += [l.from_node for l in i.links]
    return None


def material_colour(mat):
    if mat is None:
        return np.array([0.8, 0.8, 0.8])
    if mat.use_nodes and mat.node_tree:
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is not None:
            return to_srgb(list(bsdf.inputs["Base Color"].default_value)[:3])
    return to_srgb(list(mat.diffuse_color)[:3])


def image_rgb(img):
    """(h, w, 3) sRGB array of an image (8-bit images are stored as sRGB already; float ones are linear)."""
    w, h = img.size
    if w == 0 or h == 0:
        return None
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    rgb = px.reshape(h, w, 4)[:, :, :3].astype(np.float64)
    return to_srgb(rgb) if img.is_float else rgb


def loop_faces(me):
    """The face each loop (face corner) belongs to."""
    F = len(me.polygons)
    start = np.empty(F, dtype=np.int64)
    total = np.empty(F, dtype=np.int64)
    me.polygons.foreach_get("loop_start", start)
    me.polygons.foreach_get("loop_total", total)
    first = np.concatenate([[0], np.cumsum(total)[:-1]]) if F else total
    idx = np.repeat(start - first, total) + np.arange(int(total.sum()))
    out = np.zeros(len(me.loops), dtype=np.int64)
    out[idx] = np.repeat(np.arange(F), total)
    return out


def face_colours(obj):
    """(F, 3) sRGB colour per face and the source used ('texture', 'colour attribute', 'material')."""
    me = obj.data
    F = len(me.polygons)
    out = np.zeros((F, 3))
    src = np.full(F, "material", dtype=object)
    mi = np.empty(F, dtype=np.int64)
    me.polygons.foreach_get("material_index", mi)
    mats = list(me.materials) or [None]
    face_of_loop = loop_faces(me)
    counts = np.maximum(np.bincount(face_of_loop, minlength=F), 1)[:, None]
    uv = me.uv_layers.active
    luv = None
    if uv is not None:
        luv = np.empty(len(me.loops) * 2)
        uv.data.foreach_get("uv", luv)
        luv = luv.reshape(-1, 2)
    attr = me.color_attributes.active_color if hasattr(me.color_attributes, "active_color") else None
    attr = attr or (me.color_attributes[0] if len(me.color_attributes) else None)
    attr_face = None
    if attr is not None:
        n = len(attr.data)
        buf = np.empty(n * 4)
        key = "color_srgb" if hasattr(attr.data[0], "color_srgb") else "color"
        attr.data.foreach_get(key, buf)
        col = buf.reshape(-1, 4)[:, :3]
        if key == "color":
            col = to_srgb(col)
        if attr.domain == "POINT":
            lv = np.empty(len(me.loops), dtype=np.int64)
            me.loops.foreach_get("vertex_index", lv)
            col = col[lv]
        attr_face = np.zeros((F, 3))
        np.add.at(attr_face, face_of_loop, col)
        attr_face /= counts
    for k, mat in enumerate(mats):
        sel = mi == k if len(mats) > 1 else np.ones(F, dtype=bool)
        if not sel.any():
            continue
        img = base_image(mat)
        rgb = image_rgb(img) if (img is not None and luv is not None) else None
        if rgb is not None:
            h, w, _ = rgb.shape
            cen = np.zeros((F, 2))
            np.add.at(cen, face_of_loop, luv)
            cen /= counts
            # the centre and each corner pulled halfway to it: a face across a colour edge averages to neither
            pts = 0.5 * luv + 0.5 * cen[face_of_loop]
            def sample(p):
                x = np.clip((np.mod(p[:, 0], 1.0) * w).astype(np.int64), 0, w - 1)
                y = np.clip((np.mod(p[:, 1], 1.0) * h).astype(np.int64), 0, h - 1)
                return rgb[y, x]
            acc = sample(cen) + 0
            np.add.at(acc, face_of_loop, sample(pts))
            tex = acc / (counts + 1)
            out[sel], src[sel] = tex[sel], "texture"
        elif attr_face is not None:
            out[sel], src[sel] = attr_face[sel], "colour attribute"
        else:
            out[sel], src[sel] = material_colour(mat), "material"
    return out, src


# --- selection ------------------------------------------------------------------------------------------------
def gltf_to_blender(p):
    x, y, z = p
    return np.array([x, -z, y])


def face_centres_world(obj):
    me = obj.data
    c = np.empty(len(me.polygons) * 3)
    me.polygons.foreach_get("center", c)
    c = c.reshape(-1, 3)
    m = np.array(obj.matrix_world)
    return c @ m[:3, :3].T + m[:3, 3]


def vertex_world(obj):
    me = obj.data
    c = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", c)
    c = c.reshape(-1, 3)
    m = np.array(obj.matrix_world)
    return c @ m[:3, :3].T + m[:3, 3]


def select(obj, terms, hint):
    """Boolean mask of faces matching every term."""
    me = obj.data
    F = len(me.polygons)
    mask = np.ones(F, dtype=bool)
    for t in terms:
        if t["kind"] == "colour":
            cols, src = face_colours(obj)
            d = np.linalg.norm(cols - np.array(t["rgb"]), axis=1)
            mask &= d <= t["tol"]
            if F:
                i = int(np.argmin(d))
                hexes = ["#" + "".join(f"{int(round(v * 255)):02x}" for v in c) for c in cols]
                if hint.get("dist") is None or d[i] < hint["dist"]:
                    hint.update(dist=float(d[i]), hex=hexes[i], source=str(src[i]))
                counts = hint.setdefault("colours", {})
                for h in hexes:
                    counts[h] = counts.get(h, 0) + 1
        elif t["kind"] == "material":
            want = t["name"].lower()
            idx = [i for i, m in enumerate(me.materials) if m and m.name.lower() == want]
            mi = np.empty(F, dtype=np.int64)
            me.polygons.foreach_get("material_index", mi)
            mask &= np.isin(mi, idx)
            hint.setdefault("materials", sorted({m.name for m in me.materials if m}))
        elif t["kind"] == "group":
            vg = obj.vertex_groups.get(t["name"]) or next(
                (g for g in obj.vertex_groups if g.name.lower() == t["name"].lower()), None)
            hint.setdefault("groups", sorted(g.name for g in obj.vertex_groups)[:12])
            if vg is None:
                mask &= False
                continue
            w = np.zeros(len(me.vertices))
            for v in me.vertices:
                for g in v.groups:
                    if g.group == vg.index:
                        w[v.index] = g.weight
            mask &= np.array([all(w[i] >= 0.5 for i in p.vertices) for p in me.polygons], dtype=bool)
        elif t["kind"] == "box":
            a, b = gltf_to_blender(t["lo"]), gltf_to_blender(t["hi"])
            lo, hi = np.minimum(a, b), np.maximum(a, b)
            c = face_centres_world(obj)
            mask &= np.all((c >= lo) & (c <= hi), axis=1)
    return mask


def weld_ids(pos):
    """One id per distinct position (glTF splits vertices at seams; following the surface must not stop there)."""
    keys = np.round(pos / WELD).astype(np.int64)
    _, inv = np.unique(keys, axis=0, return_inverse=True)
    return inv.reshape(-1)


def largest_piece(obj, mask, wid):
    """Keep the largest connected piece (by area) of the selected faces; return (mask, dropped piece areas)."""
    me = obj.data
    faces = np.nonzero(mask)[0]
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for f in faces:
        ids = [wid[v] for v in me.polygons[f].vertices]
        r = find(ids[0])
        for i in ids[1:]:
            parent[find(i)] = r
    area = {}
    for f in faces:
        r = find(wid[me.polygons[f].vertices[0]])
        area[r] = area.get(r, 0.0) + me.polygons[f].area
    if not area:
        return mask, []
    best = max(area, key=area.get)
    keep = np.zeros_like(mask)
    for f in faces:
        if find(wid[me.polygons[f].vertices[0]]) == best:
            keep[f] = True
    dropped = sorted((a for r, a in area.items() if r != best), reverse=True)
    return keep, dropped


# --- shape along the part ---------------------------------------------------------------------------------------
def spine_line(arm):
    """Bones from the root to the highest bone (hips, spine, neck, head on a biped), without chains."""
    bones = [b for b in arm.data.bones if b.name != rf.PLACEHOLDER]
    b = max(bones, key=lambda x: x.tail_local.z)
    out = []
    while b is not None:
        out.insert(0, b)
        b = b.parent
    return out


def seg_dist(p, a, b):
    """Distances from points p (n,3) to segment a-b."""
    d = b - a
    u = np.clip(((p - a) @ d) / max(float(d @ d), 1e-12), 0.0, 1.0)
    return np.linalg.norm(p - (a + u[:, None] * d), axis=1)


def pick_parent(arm, pts, want):
    """The body bone the chain hangs from, and every part point's distance to it."""
    mw = np.array(arm.matrix_world)
    def world(v):
        return np.array(v) @ mw[:3, :3].T + mw[:3, 3]
    if want:
        names = [b.name for b in arm.data.bones]
        name = want if want in names else next((n for n in names if n.split(":")[-1].lower() == want.lower()), None)
        if name is None:
            raise Usage(f"--parent {want}: the rig has no such bone (it has {', '.join(names[:8])} ...)")
        cands = [arm.data.bones[name]]
    else:
        cands = spine_line(arm)
    best = None
    for b in cands:
        d = seg_dist(pts, world(b.head_local), world(b.tail_local))
        if best is None or d.min() < best[0].min():
            best = (d, b.name)
    return best[1], best[0]


def surface_distance(me, faces, wid, pos, roots):
    """Distance from the root vertices to every vertex of the part, along its edges (Dijkstra on welded
    positions)."""
    adj = {}
    for f in faces:
        vs = list(me.polygons[f].vertices)
        for a, b in zip(vs, vs[1:] + vs[:1]):
            ia, ib = wid[a], wid[b]
            if ia == ib:
                continue
            L = float(np.linalg.norm(pos[a] - pos[b]))
            adj.setdefault(ia, {})[ib] = min(adj.get(ia, {}).get(ib, L), L)
            adj.setdefault(ib, {})[ia] = min(adj.get(ib, {}).get(ia, L), L)
    dist = {wid[r]: 0.0 for r in roots}
    heap = [(0.0, n) for n in dist]
    while heap:
        d, n = heapq.heappop(heap)
        if d > dist.get(n, math.inf):
            continue
        for m, L in adj.get(n, {}).items():
            nd = d + L
            if nd < dist.get(m, math.inf):
                dist[m] = nd
                heapq.heappush(heap, (nd, m))
    return dist


def polyline_info(poly):
    seg = poly[1:] - poly[:-1]
    L = np.linalg.norm(seg, axis=1)
    cum = np.concatenate([[0.0], np.cumsum(L)])
    return seg, L, cum


def project(points, poly):
    """Arc-length parameter (0..1) of each point's nearest place on the polyline."""
    seg, L, cum = polyline_info(poly)
    ap = points[:, None, :] - poly[None, :-1, :]
    u = np.clip(np.einsum("nmk,mk->nm", ap, seg) / np.maximum(L ** 2, 1e-12), 0.0, 1.0)
    near = poly[None, :-1, :] + u[..., None] * seg[None]
    d = np.linalg.norm(points[:, None, :] - near, axis=2)
    j = d.argmin(axis=1)
    s = cum[j] + u[np.arange(len(points)), j] * L[j]
    return s / max(cum[-1], 1e-12)


def point_at(poly, t):
    seg, L, cum = polyline_info(poly)
    s = np.clip(t, 0.0, 1.0) * cum[-1]
    j = min(int(np.searchsorted(cum, s, side="right")) - 1, len(L) - 1)
    j = max(j, 0)
    u = (s - cum[j]) / max(L[j], 1e-12)
    return poly[j] + u * seg[j]


def tangent_at(poly, t, eps=0.02):
    d = point_at(poly, min(1.0, t + eps)) - point_at(poly, max(0.0, t - eps))
    n = np.linalg.norm(d)
    return d / n if n > 1e-12 else np.array([0.0, 0.0, -1.0])


def resample(poly, n):
    return np.array([point_at(poly, k / (n - 1)) for k in range(n)])


def centreline(pos, t_surface, S):
    """Middle of each of S slices by surface distance; empty slices filled in; ends stretched half a slice."""
    bins = np.minimum((t_surface * S).astype(int), S - 1)
    cents = [pos[bins == k].mean(axis=0) if np.any(bins == k) else None for k in range(S)]
    known = [k for k, c in enumerate(cents) if c is not None]
    for k in range(S):
        if cents[k] is None:
            lo = max((j for j in known if j < k), default=None)
            hi = min((j for j in known if j > k), default=None)
            if lo is None:
                cents[k] = cents[hi]
            elif hi is None:
                cents[k] = cents[lo]
            else:
                cents[k] = cents[lo] + (cents[hi] - cents[lo]) * (k - lo) / (hi - lo)
    c = np.array(cents)
    if len(c) > 2:
        c[1:-1] = 0.25 * c[:-2] + 0.5 * c[1:-1] + 0.25 * c[2:]
    if len(known) < 2:
        return None
    first = c[0] - (c[1] - c[0]) * 0.5
    last = c[-1] + (c[-1] - c[-2]) * 0.5
    poly = np.vstack([first, c, last])
    keep = [0] + [i for i in range(1, len(poly)) if np.linalg.norm(poly[i] - poly[i - 1]) > 1e-9]
    return poly[keep]


def follow(pos, t_surface, S):
    """The part's centreline: slices by surface distance first, then twice re-sliced across the line itself (so the
    slices end up square to it), then trimmed to where the part really starts and ends."""
    poly = centreline(pos, t_surface, S)
    for _ in range(2):
        if poly is None:
            return None
        t = project(pos, poly)
        span = max(t.max() - t.min(), 1e-9)
        poly = centreline(pos, (t - t.min()) / span, S)
    if poly is None:
        return None
    t = project(pos, poly)
    lo, hi = float(t.min()), float(t.max())
    return np.array([point_at(poly, lo + (hi - lo) * k / (2 * S)) for k in range(2 * S + 1)])


def extents(pos):
    c = pos - pos.mean(axis=0)
    _, _, vt = np.linalg.svd(c, full_matrices=False)
    proj = c @ vt.T
    return sorted((proj.max(axis=0) - proj.min(axis=0)).tolist(), reverse=True)


def rows_occupied(t, S):
    return int(len(np.unique(np.minimum((t * S).astype(int), S - 1))))


# --- shapes -----------------------------------------------------------------------------------------------------
def delete_faces(obj, faces):
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in faces], context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(me)
    bm.free()
    me.update()


def separate(body, mask, label):
    part = body.copy()
    part.data = body.data.copy()
    part.name = part.data.name = label
    for c in body.users_collection:
        c.objects.link(part)
    delete_faces(part, np.nonzero(~mask)[0])
    delete_faces(body, np.nonzero(mask)[0])
    return part


def cut_rows(obj, poly, S):
    """Planes across the centreline at every slice boundary: new rows, the same shape, texture and colours."""
    inv = obj.matrix_world.inverted_safe()
    nrm = obj.matrix_world.to_3x3().transposed()
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    for k in range(1, S):
        co = inv @ Vector(point_at(poly, k / S))
        no = (nrm @ Vector(tangent_at(poly, k / S))).normalized()
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=co, plane_no=no)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def strip_frames(pos, t, fnormals_at, poly, S, fused):
    """Per row j = 0..S: centre, width axis, normal axis, width, thickness (all world, metres)."""
    L = polyline_info(poly)[2][-1]
    rows = []
    for j in range(S + 1):
        tj = j / S
        C, T = point_at(poly, tj), tangent_at(poly, tj)
        near = np.abs(t - tj) <= 0.5 / S
        if near.sum() < 3:
            near = np.abs(t - tj) <= 1.0 / S
        P = pos[near] - C if near.sum() >= 3 else pos - C
        P = P - np.outer(P @ T, T)
        w, v = np.linalg.eigh(P.T @ P)
        W = v[:, 2]
        N = np.cross(T, W)
        N /= max(np.linalg.norm(N), 1e-12)
        width = 2 * float(np.quantile(np.abs(P @ W), 0.95)) if len(P) else 0.0
        thick = 2 * float(np.quantile(np.abs(P @ N), 0.95)) if len(P) else 0.0
        rows.append([C, T, W, N, width, thick, fnormals_at(tj)])
    for j in range(1, len(rows)):                       # no flips from one row to the next
        if rows[j][2] @ rows[j - 1][2] < 0:
            rows[j][2], rows[j][3] = -rows[j][2], -rows[j][3]
    if fused:                                           # the normal side faces out of the body
        if sum(r[3] @ r[6] for r in rows) < 0:
            for r in rows:
                r[2], r[3] = -r[2], -r[3]
    widths = np.array([max(r[4], 0.02 * L) for r in rows])
    widths = np.convolve(np.pad(widths, 1, mode="edge"), [1 / 3] * 3, mode="valid")
    out = []
    for r, wd in zip(rows, widths):
        th = min(max(r[5], THICK_MIN * wd), THICK_MAX * wd)
        C = r[0] + (r[3] * (th / 2 + LIFT * L) if fused else 0)
        out.append((C, r[2], r[3], float(wd), float(th)))
    return out


def build_strip(body, mask, rows, label, arm):
    """A box-section strip along the rows; texture coordinates or colours projected from the original faces."""
    me = body.data
    mw = body.matrix_world
    vpos = [mw @ v.co for v in me.vertices]
    tris, tri_face, tri_loops = [], [], []
    for f in np.nonzero(mask)[0]:
        p = me.polygons[f]
        lv, ll = list(p.vertices), list(p.loop_indices)
        for k in range(1, len(lv) - 1):
            tris.append((lv[0], lv[k], lv[k + 1]))
            tri_loops.append((ll[0], ll[k], ll[k + 1]))
            tri_face.append(f)
    bvh = BVHTree.FromPolygons(vpos, tris)
    verts = []
    for C, W, N, wd, th in rows:
        for a, b in ((1, 1), (-1, 1), (-1, -1), (1, -1)):
            verts.append(Vector(C + W * (a * wd / 2) + N * (b * th / 2)))
    S = len(rows) - 1
    faces = []
    for j in range(S):
        for k in range(4):
            a, b = 4 * j + k, 4 * j + (k + 1) % 4
            faces.append((a, b, b + 4, a + 4))
    faces.append((3, 2, 1, 0))
    faces.append(tuple(4 * S + k for k in range(4)))
    inv = arm.matrix_world.inverted()
    me2 = bpy.data.meshes.new(label)
    me2.from_pydata([tuple(inv @ v) for v in verts], [], faces)
    bm = bmesh.new()
    bm.from_mesh(me2)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(me2)
    bm.free()
    for m in me.materials:
        me2.materials.append(m)
    # each strip vertex takes what the original surface has at its nearest point
    near = []
    for v in verts:
        loc, _, idx, _ = bvh.find_nearest(v)
        tri = tris[idx]
        wts = interpolate.poly_3d_calc([vpos[i] for i in tri], loc)
        near.append((idx, wts))
    mi = np.empty(len(me.polygons), dtype=np.int64)
    me.polygons.foreach_get("material_index", mi)
    for p in me2.polygons:
        loc, _, idx, _ = bvh.find_nearest(arm.matrix_world @ p.center)
        p.material_index = int(mi[tri_face[idx]]) if len(me.materials) else 0
    look = []
    uv = me.uv_layers.active
    has_tex = any(base_image(m) is not None for m in me.materials)
    if uv is not None:
        src = np.empty(len(me.loops) * 2)
        uv.data.foreach_get("uv", src)
        src = src.reshape(-1, 2)
        per_v = [sum((src[tri_loops[i][k]] * w for k, w in enumerate(wts)), np.zeros(2)) for i, wts in near]
        dst = me2.uv_layers.new(name=uv.name)
        for lp in me2.loops:
            dst.data[lp.index].uv = tuple(per_v[lp.vertex_index])
        if has_tex:
            look.append("texture projected from the original")
    attr = me.color_attributes.active_color if hasattr(me.color_attributes, "active_color") else None
    attr = attr or (me.color_attributes[0] if len(me.color_attributes) else None)
    if attr is not None:
        key = "color_srgb" if hasattr(attr.data[0], "color_srgb") else "color"
        buf = np.empty(len(attr.data) * 4)
        attr.data.foreach_get(key, buf)
        col = buf.reshape(-1, 4)
        if attr.domain == "POINT":
            per_loop = lambda li: col[me.loops[li].vertex_index]   # noqa: E731
        else:
            per_loop = lambda li: col[li]   # noqa: E731
        per_v = [sum((per_loop(tri_loops[i][k]) * w for k, w in enumerate(wts)), np.zeros(4)) for i, wts in near]
        new = me2.color_attributes.new(attr.name, attr.data_type, "POINT")
        for i, c in enumerate(per_v):
            setattr(new.data[i], key, tuple(float(x) for x in c))
        try:
            me2.color_attributes.active_color = new
        except (AttributeError, TypeError):
            pass
        look.append("colours projected from the original")
    if not look:
        if has_tex:                                     # a texture without coordinates: its average colour
            cols, _ = face_colours(body)
            avg = cols[mask].mean(axis=0)
            mat = bpy.data.materials.new(label + "_average")
            mat.use_nodes = True
            lin = np.where(avg <= 0.04045, avg / 12.92, ((avg + 0.055) / 1.055) ** 2.4)
            mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*lin.tolist(), 1.0)
            me2.materials.clear()
            me2.materials.append(mat)
            for p in me2.polygons:
                p.material_index = 0
            look.append("the part's average colour")
        else:
            look.append("its own material colours")
    obj = bpy.data.objects.new(label, me2)
    for c in body.users_collection:
        c.objects.link(obj)
    obj.parent = arm
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.matrix_world = arm.matrix_world.copy()
    md = obj.modifiers.new("Armature", "ARMATURE")
    md.object = arm
    return obj, "; ".join(look)


# --- bones and weights -------------------------------------------------------------------------------------------
def add_bones(arm, joints, parent, label):
    inv = arm.matrix_world.inverted()
    for o in list(bpy.context.scene.objects):
        if o is not None:
            o.select_set(False)
    arm.hide_set(False)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    prev, names = eb[parent], []
    for i in range(len(joints) - 1):
        b = eb.new(f"{label}_{i + 1:02d}")
        b.head, b.tail = inv @ Vector(joints[i]), inv @ Vector(joints[i + 1])
        b.parent = prev
        b.use_connect = i > 0
        b.use_deform = True
        prev = b
        names.append(b.name)
    bpy.ops.object.mode_set(mode="OBJECT")
    return names


def chain_weights(t, n):
    """(len(t), n + 1) weights: column 0 the parent, then each chain bone; rows sum to 1."""
    s = np.clip(t, 0.0, 1.0) * n
    w = np.zeros((len(t), n + 1))
    for r, x in enumerate(s):
        if x <= 0.5:
            w[r, 1] = 1.0
        elif x >= n - 0.5:
            w[r, n] = 1.0
        else:
            i = int(math.floor(x - 0.5))
            f = x - 0.5 - i
            w[r, i + 1], w[r, i + 2] = 1.0 - f, f
        if x < ROOT_BLEND:
            p = 1.0 - x / ROOT_BLEND
            w[r, 1:] *= 1.0 - p
            w[r, 0] = p
    return w / w.sum(axis=1, keepdims=True)


def set_weights(obj, parent, names, poly):
    obj.vertex_groups.clear()
    groups = [obj.vertex_groups.new(name=parent)] + [obj.vertex_groups.new(name=n) for n in names]
    pos = vertex_world(obj)
    w = chain_weights(project(pos, poly), len(names))
    for col, g in enumerate(groups):
        for i in np.nonzero(w[:, col] > 1e-6)[0]:
            g.add([int(i)], float(w[i, col]), "REPLACE")
    return w


# --- clips -------------------------------------------------------------------------------------------------------
def fcurves_of(act):
    """Every F-curve of an action: the legacy list before Blender 5.0, the layered channel bags after."""
    if hasattr(act, "fcurves"):
        return list(act.fcurves)
    out = []
    for layer in getattr(act, "layers", []):
        for strip in layer.strips:
            for bag in strip.channelbags:
                out += list(bag.fcurves)
    return out


def assign(arm, act):
    ad = arm.animation_data or arm.animation_data_create()
    ad.action = act
    if act is not None and hasattr(ad, "action_slot") and ad.action_slot is None:
        slots = list(getattr(ad, "action_suitable_slots", [])) or list(getattr(act, "slots", []))
        if slots:
            ad.action_slot = slots[0]


def frames_of(act):
    f0, f1 = act.frame_range
    return int(round(f0)), int(round(f1))


def pose_error(fcs, fa, fb, only=None):
    """Largest channel difference between frames fa and fb (quaternions compared up to sign)."""
    groups = {}
    for fc in fcs:
        if only is not None and not any(f'"{n}"' in fc.data_path for n in only):
            continue
        groups.setdefault(fc.data_path, {})[fc.array_index] = fc
    err = 0.0
    for path, chans in groups.items():
        a = np.array([chans[i].evaluate(fa) for i in sorted(chans)])
        b = np.array([chans[i].evaluate(fb) for i in sorted(chans)])
        d = np.abs(a - b).max()
        if path.endswith("rotation_quaternion") and len(chans) == 4:
            d = min(d, np.abs(a + b).max())
        err = max(err, float(d))
    return err


def keys_snapshot(act, skip):
    """Every key of the action's channels except those of bones in `skip`: proof the body clips were not changed."""
    out = []
    for fc in fcurves_of(act):
        if any(f'"{n}"' in fc.data_path for n in skip):
            continue
        out.append((fc.data_path, fc.array_index, tuple(round(c, 6) for k in fc.keyframe_points for c in k.co)))
    return sorted(out)


def outward(arm, names, parent):
    """Armature-space direction from the parent bone to the chain's root, square to the parent (behind the neck
    for a scarf on the back): the swing that would push the chain into the body is never keyed."""
    p = arm.data.bones[parent]
    root = arm.data.bones[names[0]].head_local
    a, b = p.head_local, p.tail_local
    d = b - a
    u = max(0.0, min(1.0, (root - a).dot(d) / max(d.dot(d), 1e-12)))
    out = root - (a + d * u)
    out -= d.normalized() * out.dot(d.normalized()) if d.length > 1e-9 else Vector()
    return out.normalized() if out.length > 1e-6 else -FRONT


def swing_axes(bone, out):
    """Two axes across the bone: turning about the first by a positive angle moves its tip outward (away from the
    body), the second swings it sideways. A bone pointing straight out swings up and down and sideways instead."""
    d = (bone.tail_local - bone.head_local).normalized()
    side = out - d * out.dot(d)
    if side.length > 0.2:
        return d.cross(side).normalized(), True
    ref = UP if abs(d.dot(UP)) < 0.9 else FRONT
    return d.cross(ref).normalized(), False


def key_sway(arm, act, names, parent, amp, lag):
    f0, f1 = frames_of(act)
    P = max(1, f1 - f0)
    fps = bpy.context.scene.render.fps or 24
    cycles = max(1, int(round(P / fps / SWAY_SECONDS)))
    assign(arm, act)
    bones = [arm.data.bones[n] for n in names]
    out = outward(arm, names, parent)
    axes = []
    for b in bones:
        a1, one_way = swing_axes(b, out)
        d = (b.tail_local - b.head_local).normalized()
        axes.append((a1, d.cross(a1).normalized(), one_way))
    for f in range(f0, f1 + 1):
        u = ((f - f0) % P) / P                      # the last frame is the first: the loop stays exact
        for i, (b, (a1, a2, one_way)) in enumerate(zip(bones, axes)):
            ph = 2 * math.pi * (cycles * u - i * lag)
            main = amp * (1 - math.cos(ph)) / 2 if one_way else amp * math.sin(ph)
            q = Quaternion(a1, math.radians(main)) @ \
                Quaternion(a2, math.radians(SWAY_SIDE * amp * math.sin(ph + math.pi / 2)))
            pb = arm.pose.bones[b.name]
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = rf.local_q(b, q)
            pb.keyframe_insert("rotation_quaternion", frame=f)
    assign(arm, None)
    return cycles


def ribbon(arm, joints, parent, label):
    """A cloth proxy along the chain: two rows per bone, two vertices across, pinned at the root row."""
    rows = []
    for i in range(len(joints) - 1):
        rows += [joints[i], (joints[i] + joints[i + 1]) / 2]
    rows.append(joints[-1])
    seg = np.linalg.norm(joints[1] - joints[0])
    T = joints[-1] - joints[0]
    T /= max(np.linalg.norm(T), 1e-12)
    ref = np.array(UP) if abs(T @ np.array(UP)) < 0.9 else np.array(FRONT)
    W = np.cross(T, ref)
    W /= max(np.linalg.norm(W), 1e-12)
    hw = 0.25 * seg
    inv = arm.matrix_world.inverted()
    verts = [tuple(inv @ Vector(r + s * hw * W)) for r in rows for s in (1, -1)]
    faces = [(2 * j, 2 * j + 1, 2 * j + 3, 2 * j + 2) for j in range(len(rows) - 1)]
    me = bpy.data.meshes.new(label + "_cloth")
    me.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new(label + "_cloth", me)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = arm
    obj.matrix_parent_inverse = Matrix.Identity(4)
    g = obj.vertex_groups.new(name=parent)
    g.add(list(range(len(verts))), 1.0, "REPLACE")
    pin = obj.vertex_groups.new(name="pin")
    pin.add([0, 1], 1.0, "REPLACE")
    md = obj.modifiers.new("Armature", "ARMATURE")
    md.object = arm
    cl = obj.modifiers.new("Cloth", "CLOTH")
    for k, v in CLOTH.items():
        setattr(cl.settings, k, v)
    cl.settings.vertex_group_mass = "pin"
    return obj, cl, len(rows)


def key_cloth(arm, act, names, parent, joints, label, body):
    """Cloth on a ribbon over the clip's frames, the body meshes as colliders; each chain bone is turned to follow
    it. Returns the largest bend from rest in degrees."""
    f0, f1 = frames_of(act)
    sc = bpy.context.scene
    obj, cl, nrows = ribbon(arm, joints, parent, label)
    cl.point_cache.frame_start, cl.point_cache.frame_end = f0, f1
    for k, v in CLOTH_COLLIDE.items():
        setattr(cl.collision_settings, k, v)
    colliders = []
    for m in body:
        md = m.modifiers.new("chain_collide", "COLLISION")
        m.collision.thickness_outer = COLLIDE
        colliders.append((m, md))
    sc.frame_start, sc.frame_end = f0, f1
    assign(arm, act)
    inv = arm.matrix_world.inverted()
    frames = []
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        co = [inv @ (obj.matrix_world @ v.co) for v in me.vertices]
        ev.to_mesh_clear()
        centres = [(co[2 * r] + co[2 * r + 1]) / 2 for r in range(nrows)]
        frames.append((f, arm.pose.bones[parent].matrix.copy(), centres[::2]))
    for m, md in colliders:
        m.modifiers.remove(md)
    bones = [arm.data.bones[n] for n in names]
    par = arm.data.bones[parent]
    worst, prev = 0.0, [None] * len(bones)
    keyed = []
    for f, Pm, pts in frames:
        posed_parent, rest_parent = Pm, par.matrix_local
        qs = []
        for i, b in enumerate(bones):
            base = posed_parent @ (rest_parent.inverted() @ b.matrix_local)
            cur = (base.to_3x3() @ Vector((0, 1, 0))).normalized()
            want = (pts[i + 1] - pts[i])
            want = want.normalized() if want.length > 1e-9 else cur
            r = cur.rotation_difference(want)
            br = base.to_quaternion()
            q = br.inverted() @ r @ br
            if prev[i] is not None and q.dot(prev[i]) < 0:
                q = -q
            prev[i] = q
            worst = max(worst, math.degrees(q.angle if q.angle <= math.pi else 2 * math.pi - q.angle))
            qs.append(q)
            posed_parent, rest_parent = base @ q.to_matrix().to_4x4(), b.matrix_local
        keyed.append((f, qs))
    for f, qs in keyed:
        for b, q in zip(bones, qs):
            pb = arm.pose.bones[b.name]
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = q
            pb.keyframe_insert("rotation_quaternion", frame=f)
    assign(arm, None)
    m = obj.data
    bpy.data.objects.remove(obj)
    bpy.data.meshes.remove(m)
    return worst


# --- preview -------------------------------------------------------------------------------------------------------
def render_sheet(arm, meshes, clips, path):
    """SHEET_FRAMES frames of each clip from behind and to the side (where scarves and capes hang)."""
    sc = bpy.context.scene
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    mid, size = (lo + hi) / 2, max(hi - lo)
    cam = bpy.data.objects.new("chain_cam", bpy.data.cameras.new("chain_cam"))
    sc.collection.objects.link(cam)
    cam.location = mid + Vector((size * 1.8, size * 1.1, size * 0.2))
    cam.rotation_euler = (mid - cam.location).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam
    sc.render.engine = "BLENDER_WORKBENCH"
    textured = any(base_image(s.material) is not None for o in meshes for s in o.material_slots)
    coloured = any(len(o.data.color_attributes) for o in meshes)
    sc.display.shading.color_type = "TEXTURE" if textured else ("VERTEX" if coloured else "MATERIAL")
    sc.world = sc.world or bpy.data.worlds.new("preview")
    sc.world.color = (0.82, 0.82, 0.82)
    W = SHEET_W
    sc.render.resolution_x = sc.render.resolution_y = W
    sc.render.resolution_percentage = 100
    tmp = Path(path).with_suffix("")
    tmp.mkdir(parents=True, exist_ok=True)
    rows = max(1, len(clips))
    sheet = np.ones((W * rows, W * SHEET_FRAMES, 4), dtype=np.float32)
    for r, act in enumerate(clips):
        assign(arm, act)
        f0, f1 = frames_of(act)
        for i in range(SHEET_FRAMES):
            sc.frame_set(f0 + i * max(1, f1 - f0) // SHEET_FRAMES)
            sc.render.filepath = str(tmp / f"{r}_{i}.png")
            bpy.ops.render.render(write_still=True)
            img = bpy.data.images.load(sc.render.filepath)
            px = np.empty(W * W * 4, dtype=np.float32)
            img.pixels.foreach_get(px)
            bpy.data.images.remove(img)
            row = rows - 1 - r
            sheet[row * W:(row + 1) * W, i * W:(i + 1) * W] = px.reshape(W, W, 4)
    assign(arm, None)
    out = bpy.data.images.new("chain_sheet", W * SHEET_FRAMES, W * rows)
    out.pixels.foreach_set(sheet.reshape(-1))
    out.filepath_raw = str(path)
    out.file_format = "PNG"
    out.save()
    for f in tmp.glob("*.png"):
        f.unlink()
    tmp.rmdir()
    bpy.data.objects.remove(cam)
    print(f"[ OK ] preview {path} (one row per clip, {SHEET_FRAMES} frames each, seen from behind)")


# --- one part ----------------------------------------------------------------------------------------------------
def make_part(a, part, arm, meshes, report):
    label = part["label"]
    if any(b.name.startswith(label + "_") for b in arm.data.bones):
        raise Usage(f"the rig already has bones named {label}_..: give this part another label (--part name=...)")
    hint, best = {}, None
    for m in meshes:
        mask = select(m, part["terms"], hint)
        if best is None or mask.sum() > best[1].sum():
            best = (m, mask)
    body, mask = best
    sel_text = part["text"]
    if not mask.any():
        why = f"--part {sel_text} selected nothing"
        if hint.get("dist") is not None and hint["dist"] <= NEAR_MISS:
            why += (f"; the closest colour on the model is {hint['hex']} (distance {hint['dist']:.2f}, from its "
                    f"{hint['source']}): widen the tolerance (~{hint['dist'] + 0.03:.2f}) or pick that colour")
        elif hint.get("dist") is not None:
            top = sorted(hint["colours"].items(), key=lambda kv: -kv[1])[:6]
            why += (f"; nothing on the model is near that colour (closest {hint['hex']}, distance "
                    f"{hint['dist']:.2f}); its most common face colours: {', '.join(h for h, _ in top)}")
        if hint.get("materials") is not None:
            why += f"; materials: {', '.join(hint['materials']) or 'none'}"
        if hint.get("groups") is not None:
            why += f"; vertex groups include {', '.join(hint['groups'])}"
        raise Refuse(why)
    share = mask.sum() / len(mask)
    if share > MAX_PART_SHARE:
        raise Refuse(f"--part {sel_text} selects {share * 100:.0f}% of {body.name}'s faces: that is most of the "
                     f"character, not a scarf or a tail (at most {MAX_PART_SHARE * 100:.0f}%); narrow it (a "
                     "smaller tolerance, or & box:...)")
    me = body.data
    pos_all = vertex_world(body)
    wid = weld_ids(pos_all)
    mask, dropped = largest_piece(body, mask, wid)
    faces = np.nonzero(mask)[0]
    vids = np.unique(np.concatenate([np.array(me.polygons[f].vertices) for f in faces]))
    pos = pos_all[vids]
    e = extents(pos)
    if e[0] / max(e[1], 1e-9) < MIN_ELONGATION and e[1] / max(e[2], 1e-9) < SHEET_RATIO:
        raise Refuse(f"--part {sel_text} is a lump ({e[0]:.2f} x {e[1]:.2f} x {e[2]:.2f} m): a chain needs a part "
                     "longer than it is wide (a scarf tail, ponytail, tail) or a thin sheet (a cape)")
    parent, dpar = pick_parent(arm, pos, a.parent)
    roots = vids[dpar <= dpar.min() + ROOT_BAND * e[1]]        # the whole edge nearest the parent, not a corner
    dist = surface_distance(me, faces, wid, pos_all, [int(r) for r in roots])
    dmax = max(dist.values()) or 1.0
    t_surf = np.array([dist.get(wid[v], dmax) for v in vids]) / dmax
    S = max(a.bones * ROWS_PER_BONE, MIN_ROWS)
    poly = follow(pos, t_surf, S)
    if poly is None or len(poly) < 2:
        raise Refuse(f"--part {sel_text}: no length to follow (all of it is about as far from {parent})")
    t = project(pos, poly)
    dbg(f"{label}: {len(roots)} root vertices, centreline {poly[::2].round(3).tolist()}")
    # fused: the part shares vertices with the rest of the mesh beyond its root
    other = np.ones(len(me.polygons), dtype=bool)
    other[faces] = False
    other_ids = set(wid[v] for f in np.nonzero(other)[0] for v in me.polygons[f].vertices)
    shared = np.array([wid[v] in other_ids for v in vids])
    shared_reach = float(np.quantile(t[shared], 0.9)) if shared.any() else 0.0
    fused = shared_reach > FUSED_SHARE
    rows_before = rows_occupied(t, S)
    info = {"label": label, "selector": sel_text, "mesh": body.name, "faces": int(mask.sum()),
            "share": round(float(share), 3), "dropped_pieces": len(dropped), "parent": parent,
            "size_m": [round(x, 3) for x in e], "length_m": round(float(polyline_info(poly)[2][-1]), 3),
            "fused_reach": round(shared_reach, 2), "rows_before": rows_before, "rows_needed": S}
    if dropped:
        print(f"[info] {label}: {len(dropped)} smaller piece(s) of the selection left on the body "
              f"(largest {dropped[0] * 1e4:.0f} cm2)")
    strip = fused or a.rebuild == "strip"
    if strip and a.rebuild == "no":
        raise Refuse(f"--part {sel_text} is fused to the body along {shared_reach * 100:.0f}% of its length, so it "
                     "cannot swing without tearing; --rebuild no forbids the strip it needs")
    if strip:
        fn = np.empty(len(me.polygons) * 3)
        me.polygons.foreach_get("normal", fn)
        fn = fn.reshape(-1, 3) @ np.array(body.matrix_world.to_3x3()).T
        fc = face_centres_world(body)
        ft = project(fc[faces], poly)

        def normal_at(tj):
            near = np.abs(ft - tj) <= 1.0 / S
            n = fn[faces][near].sum(axis=0) if near.any() else fn[faces].sum(axis=0)
            return n / max(np.linalg.norm(n), 1e-12)
        rows = strip_frames(pos, t, normal_at, poly, S, fused)
        obj, look = build_strip(body, mask, rows, label, arm)
        if not fused:                                    # forced strip on a free part: the original goes
            delete_faces(body, faces)
        poly = np.array([r[0] for r in rows])
        info.update(rebuild="strip", look=look, rows_after=S + 1,
                    reason=(f"fused to the body along {shared_reach * 100:.0f}% of its length; the original "
                            "surface stays on the body" if fused else "--rebuild strip"),
                    width_m=round(float(np.median([r[3] for r in rows])), 3),
                    thickness_m=round(float(np.median([r[4] for r in rows])), 3))
        print(f"[ OK ] {label}: rebuilt as a strip ({info['reason']}), {S} segments, "
              f"{info['width_m']:.2f} m wide, {info['thickness_m']:.3f} m thick; look: {look}")
    else:
        obj = separate(body, mask, label)
        info.update(rebuild="none", rows_after=rows_before)
        if rows_before < S:
            if a.rebuild == "no":
                print(f"[WARN] {label}: only {rows_before} of {S} rows along its length; with --rebuild no it "
                      "bends in steps")
            else:
                cut_rows(obj, poly, S)
                info["rows_after"] = rows_occupied(project(vertex_world(obj), poly), S)
                info["rebuild"] = "cuts"
                print(f"[ OK ] {label}: {rows_before} rows along its length, cut to {info['rows_after']} so it "
                      "can bend (the shape and texture do not change)")
        print(f"[ OK ] {label}: separated from {body.name} ({info['faces']} faces, "
              f"{info['share'] * 100:.1f}% of it)")
    joints = resample(poly, a.bones + 1)
    names = add_bones(arm, joints, parent, label)
    w = set_weights(obj, parent, names, poly)
    info.update(bones=names, vertices=len(obj.data.vertices), object=obj.name,
                weights_sum_error=round(float(np.abs(w.sum(axis=1) - 1).max()), 6),
                joints=[[round(float(x), 4) for x in j] for j in joints])
    print(f"[ OK ] {label}: {len(names)} bones from {parent}, {info['length_m']:.2f} m long, weighted along it")
    report["parts"].append(info)
    return obj, names, parent, joints


# --- main --------------------------------------------------------------------------------------------------------
def main():
    global DEBUG
    a = parse()
    DEBUG = a.debug
    report = {"input": Path(a.rigged).name, "parts": [], "clips": {}, "failures": []}
    code = 0
    try:
        code = run(a, report)
    except Refuse as e:
        report["failures"].append(str(e))
        print(f"[FAIL] {e}")
        code = 1
    except Usage as e:
        report["failures"].append(str(e))
        print(f"[error] {e}")
        code = 2
    if a.report:
        Path(a.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return code


def run(a, report):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=a.rigged)
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if len(arms) != 1:
        raise Refuse(f"expected one armature, found {len(arms)}")
    arm = arms[0]
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and any(md.type == "ARMATURE" for md in o.modifiers)]
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o not in meshes]:
        bpy.data.objects.remove(o)                       # the importer's bone display shape and other strays
    if not meshes:
        raise Refuse("no skinned mesh in the file")
    clips = list(bpy.data.actions)
    if arm.animation_data:
        for tr in list(arm.animation_data.nla_tracks):   # the importer stacks every clip on NLA tracks
            # a track keeps the glTF clip's name; Blender 4.2 names the action itself "<clip>_<armature>" (hit_rig):
            # the action takes the clip's name back, so --cloth hit finds it and the export keeps "hit"
            for st in tr.strips:
                if st.action is not None and st.action.name != tr.name and tr.name not in bpy.data.actions:
                    st.action.name = tr.name
            arm.animation_data.nla_tracks.remove(tr)
    assign(arm, None)
    for c in clips:
        c.use_fake_user = True
    names_lower = {c.name.lower(): c for c in clips}
    loops = {}
    for c in clips:
        f0, f1 = frames_of(c)
        err = pose_error(fcurves_of(c), f0, f1)
        loops[c.name] = (err <= LOOP_TOL or c.name.lower() in a.loop_clips) and f1 > f0
        report["clips"][c.name] = {"frames": [f0, f1], "kind": "loop" if loops[c.name] else "one-shot",
                                   "end_mismatch": round(err, 5)}
    for want in a.loop_clips + [x for x in a.cloth_clips if x != "*oneshots*"]:
        if want not in names_lower:
            raise Usage(f"no clip named {want!r}; the file has {', '.join(c.name for c in clips) or 'none'}")
    cloth = [c for c in clips if (c.name.lower() in a.cloth_clips or ("*oneshots*" in a.cloth_clips
                                                                         and not loops[c.name]))]
    for c in cloth:
        if loops[c.name]:
            raise Usage(f"--cloth {c.name}: that clip loops; looping clips get the sway, which keeps them looping "
                        "(a simulation would not end where it began)")
    before = {}
    parts = []
    for part in a.parts:
        parts.append(make_part(a, part, arm, meshes, report))
        meshes = [o for o in bpy.data.objects if o.type == "MESH"
                  and any(md.type == "ARMATURE" for md in o.modifiers)]
    chain_names = [n for _, names, _, _ in parts for n in names]
    for c in clips:
        before[c.name] = keys_snapshot(c, chain_names)
    bpy.context.scene.render.fps = bpy.context.scene.render.fps or 24
    for c in clips:
        info = report["clips"][c.name]
        if loops[c.name]:
            amp = a.sway_per.get(c.name.lower(), a.sway_default)
            cyc = 0
            for obj, names, parent, joints in parts:
                cyc = key_sway(arm, c, names, parent, amp, a.lag)
            f0, f1 = frames_of(c)
            info.update(motion="sway", amplitude_deg=amp, cycles=cyc,
                        loop_error=pose_error(fcurves_of(c), f0, f1, only=chain_names))
        elif c in cloth:
            worst = 0.0
            body = [o for o in meshes if o not in [p[0] for p in parts]]
            for obj, names, parent, joints in parts:
                worst = max(worst, key_cloth(arm, c, names, parent, joints, names[0].rsplit("_", 1)[0], body))
            info.update(motion="cloth", max_deg=round(worst, 1))
        else:
            info.update(motion="none")
    # checks: rig_finish's, then the chain's own
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and any(md.type == "ARMATURE" for md in o.modifiers)]
    rep = rf.check_weights(arm, meshes)
    if not rep["failures"]:
        moved = rf.deform_check(arm, meshes)
        rep["deform_max_share"] = round(moved, 3)
        if moved < rf.MIN_DEFORM:
            rep["failures"].append(f"the rig does not deform the mesh ({moved * 100:.1f}% of its height)")
    report["checks"] = rep
    fails = list(rep["failures"])
    for obj, names, parent, joints in parts:
        info = next(p for p in report["parts"] if p["object"] == obj.name)
        used = set()
        gname = {g.index: g.name for g in obj.vertex_groups}
        for v in obj.data.vertices:
            gs = [(gname[g.group], g.weight) for g in v.groups if g.weight > 0]
            if gs:
                used.add(max(gs, key=lambda x: x[1])[0])
        idle = [n for n in names if n not in used]
        info["bones_holding_vertices"] = len(names) - len(idle)
        if idle:
            fails.append(f"{info['label']}: bones {', '.join(idle)} hold no vertex (fewer --bones for this part)")
        if info["weights_sum_error"] > rf.SUM_TOLERANCE:
            fails.append(f"{info['label']}: weights do not sum to 1")
    for c in clips:
        info = report["clips"][c.name]
        if info.get("motion") == "sway" and info["loop_error"] > 1e-5:
            fails.append(f"clip {c.name}: the chain's first and last frame differ ({info['loop_error']:.1e})")
        info["body_keys_unchanged"] = keys_snapshot(c, chain_names) == before[c.name]
        if not info["body_keys_unchanged"]:
            fails.append(f"clip {c.name}: keys of body bones changed")
    for f in fails:
        print(f"[FAIL] {f}")
    report["failures"] += fails
    print(f"[{'FAIL' if fails else ' OK '}] rig checks: {rep['vertices']} vertices, {rep['bones']} bones, "
          f"{rep['bones_used']} in use, unweighted {rep['unweighted']}, deforms "
          f"{rep.get('deform_max_share', 0) * 100:.0f}%")
    if fails:
        return 1
    assign(arm, None)
    # slide to zero, as rig_finish.py exports: a clip whose keys start after 0 s holds its first pose an extra
    # frame every time an engine loops it (#290)
    bpy.ops.export_scene.gltf(filepath=a.out, export_format="GLB", export_yup=True,
                              export_animations=bool(clips), export_animation_mode="ACTIONS",
                              export_anim_slide_to_zero=True)
    report["clips_written"] = [c.name for c in clips]
    print(f"[ OK ] wrote {a.out}" + (f" with clips {', '.join(report['clips_written'])}" if clips else ""))
    if a.sheet and clips:
        render_sheet(arm, meshes, clips, a.sheet)
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        code = main()
    except SystemExit as exc:          # argparse: usage errors
        code = exc.code if isinstance(exc.code, int) else 2
    except Exception as exc:  # noqa: BLE001
        print(f"[error] {exc!r}")
        if DEBUG:
            import traceback
            traceback.print_exc()
        code = 2
    if not bpy.app.binary_path:
        # the bpy module (no Blender executable) crashes while the process ends on Windows (0xC0000005, seen
        # 2026-11-11): bpy 4.2 after any glTF export, bpy 5.3 after a render, which would hide this exit code.
        # Everything is written by now; end the process without unloading its libraries (os._exit crashed 5.3 the
        # same way). The handle types matter: an untyped GetCurrentProcess() came back truncated and the call failed.
        sys.stdout.flush()
        sys.stderr.flush()
        import os
        if os.name == "nt":
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            k32.TerminateProcess(k32.GetCurrentProcess(), code)
    sys.exit(code)
