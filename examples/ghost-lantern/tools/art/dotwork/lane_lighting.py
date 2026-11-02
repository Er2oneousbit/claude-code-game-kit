#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_lighting.py
# Purpose : 2D lighting for art already in the game, drawn in code (normals.py: numpy, no model, no ComfyUI): a normal
#           map for every frame of a SpriteFrames plus a lit copy whose frames are CanvasTextures (diffuse + normal);
#           a lit copy of a TileSet whose atlases are CanvasTextures (normals lit tile by tile, so they stay seamless
#           across tile edges); for prop PNGs a normal map, a CanvasTexture and a lit scene with a LightOccluder2D
#           traced from the alpha; a demo scene (tiles, props and a character under a CanvasModulate and a
#           PointLight2D that casts shadows); a numpy review sheet in assets_src.
# Usage   : pack spec "lighting": [{"name": "town_lit", "frames": ["assets/art/characters/*/*_frames.tres"],
#           "tilesets": ["res://assets/art/tiles/street/ground_street_tileset.tres"],
#           "props": ["assets/art/props/spr_barrel.png", "assets/art/props/spr_crate.png"], "bevel": 3,
#           "light_color": "#ffd8a0", "light_energy": 1.2}]
# Notes   : Inputs: res:// paths, or paths and globs relative to the game (inside it). The originals are never
#           changed; everything goes to <assets>/art/lit/<name>/ (lit copies point at the original diffuse PNGs).
#           Keys: frames (SpriteFrames .tres), tilesets (TileSet .tres), props (PNGs); bevel (sprite and prop rim in
#           px, default 3), tile_bevel (rim along clear pixels inside a tile, default 2; an opaque tile never gets
#           one), detail (luminance height in px, default 1), strength (default 1); occluder "base" (default: the
#           bottom occluder_band of the silhouette, default 0.25 of its height) | "full" | "none", occluder_points
#           (most corners, default 12); demo (default true), light_color (default "#ffe2b0"), light_energy (default
#           1.2), light_height (px above the floor, default 48), light_range (px, default 160), ambient (the
#           CanvasModulate colour, default "#5a5a78"). The demo shows the first tileset, the first SpriteFrames and
#           up to four props. Resumes per entry: unchanged inputs and keys keep their files.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import hashlib
import json
import os
import re
import struct

import numpy as np
from PIL import Image, ImageDraw

import fcore as core
import godot
import normals

import engine as lib  # noqa: E402

WF = "Dotwork lighting lane (numpy normals: alpha bevel + luminance detail, Sobel; drawn in code)"
TAGS = ("gd_resource", "gd_scene", "ext_resource", "sub_resource", "resource", "node", "connection", "editable")
HEAD = re.compile(r"^\[(\w+)(\s.*)?\]\s*$")
ATTR = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|[^\s\]]+)')
EXTREF = re.compile(r'ExtResource\(\s*"([^"]+)"\s*\)')
VEC2 = re.compile(r"Vector2i?\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)")
DEMO_CELLS = (12, 8)    # the demo floor, in tiles


# ---- inputs ------------------------------------------------------------------------
def _res(path):
    """res:// path of a file inside the game."""
    return "res://" + os.path.relpath(path, core.PROJECT).replace(os.sep, "/")


def _inside(path, root):
    """True when path lies in the folder root."""
    a, r = os.path.normcase(os.path.abspath(path)), os.path.normcase(root)
    try:
        return os.path.commonpath([a, r]) == r
    except ValueError:   # another drive
        return False


def _from_res(p, base_file=None):
    """A file path from a resource reference: res://... is the game folder; anything else is relative to the file
    that names it (Godot allows both). Never outside the game."""
    if p.startswith("res://"):
        return core.project_path(p[len("res://"):])
    if base_file is None:
        return core.project_path(p)
    full = os.path.normpath(os.path.join(os.path.dirname(base_file), p))
    return core.project_path(os.path.relpath(full, core.PROJECT))


def _rel(path):
    """A game-relative path with forward slashes (logs and manifest rows)."""
    return os.path.relpath(path, core.PROJECT).replace(os.sep, "/")


def _inputs(entry, k, items, exts):
    """Absolute files for an entry's input list `k`: res:// paths or game-relative paths / globs, each inside the
    game (spec paths may not escape it), sorted, without repeats. A pattern that matches nothing stops the run."""
    items = [items] if isinstance(items, str) else (items or [])
    out = []
    for it in items:
        s = str(it)
        s = s[len("res://"):] if s.startswith("res://") else s
        full = core.project_path(s)                  # refuses .., absolute and network paths
        hits = sorted(glob.glob(full)) if any(c in s for c in "*?[") else ([full] if os.path.isfile(full) else [])
        # each hit re-checked: a glob must not reach out of the game through a link
        hits = [core.project_path(_rel(h)) for h in hits if h.lower().endswith(exts)]
        if not hits:
            raise core.ToolError(f"lighting {entry}: {k} {it!r} matches no {' / '.join(exts)} file in the game "
                                 "(paths are res:// or relative to the game folder)")
        out += [h for h in hits if h not in out]
    return out


def _color(entry, k, v):
    v = str(v)
    if not re.fullmatch(r"#?[0-9a-fA-F]{6}", v):
        raise core.ToolError(f"lighting {entry}: {k} {v!r} is not a #RRGGBB colour")
    return tuple(int(c) for c in lib.hexrgb(v))


def _num(entry, k, v, lo, hi):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise core.ToolError(f"lighting {entry}: {k} {v!r} is not a number")
    if not lo <= f <= hi:
        raise core.ToolError(f"lighting {entry}: {k} {f:g} is outside {lo:g}..{hi:g}")
    return f


def options(e):
    """The entry's lighting settings, checked (a bad value stops the run before anything is written). Every key is
    read as e.get("key", default) so dotwork.py's spec check knows them."""
    n = e["name"]
    occ = str(e.get("occluder", "base"))
    if occ not in ("base", "full", "none"):
        raise core.ToolError(f"lighting {n}: occluder {occ!r}: use base, full or none")
    return {"bevel": _num(n, "bevel", e.get("bevel", 3), 0, 16),
            "tile_bevel": _num(n, "tile_bevel", e.get("tile_bevel", 2), 0, 16),
            "detail": _num(n, "detail", e.get("detail", 1.0), 0, 8),
            "strength": _num(n, "strength", e.get("strength", 1.0), 0, 8),
            "occluder": occ, "band": _num(n, "occluder_band", e.get("occluder_band", 0.25), 0.05, 1.0),
            "points": int(_num(n, "occluder_points", e.get("occluder_points", 12), 3, 64)),
            "demo": bool(e.get("demo", True)),
            "light_color": _color(n, "light_color", e.get("light_color", "#ffe2b0")),
            "light_energy": _num(n, "light_energy", e.get("light_energy", 1.2), 0, 16),
            "light_height": _num(n, "light_height", e.get("light_height", 48), 0, 4096),
            "light_range": _num(n, "light_range", e.get("light_range", 160), 8, 8192),
            "ambient": _color(n, "ambient", e.get("ambient", "#5a5a78"))}


# ---- Godot text resources ----------------------------------------------------------
def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def blocks(text):
    """A Godot text resource as [header, [body lines]] blocks (the first is the file header). Only Godot's own section
    tags open a block, so an array value on a line of its own is never mistaken for one."""
    out = []
    for line in text.splitlines():
        m = HEAD.match(line)
        if m and m.group(1) in TAGS:
            out.append([line, []])
        elif out:
            out[-1][1].append(line)
    return out


def attrs(header):
    """{name: value} of a section header, quotes removed."""
    return {k: (v[1:-1] if v.startswith('"') else v) for k, v in ATTR.findall(header)}


def _tag(header):
    return HEAD.match(header).group(1)


def _strip_uid(header):
    """A copy must not reuse the uid of the file it was copied from (Godot would see two files with one uid), and an
    ext_resource whose path is replaced must lose the uid that still names the old file (Godot loads by uid first)."""
    return re.sub(r'\s+uid="[^"]*"', "", header)


def _bump_steps(header, n):
    """load_steps grows by the resources added; Godot 4.7 writes files without it, and then none is added."""
    return re.sub(r"load_steps=(\d+)", lambda m: f"load_steps={int(m.group(1)) + n}", header)


def _join(head, ext_lines, sub_blocks, rest_blocks):
    """Reassemble: header, ext_resources, sub_resources, then the remaining sections, one blank line apart."""
    out = [head, ""] + ext_lines + [""]
    for h, body in list(sub_blocks) + list(rest_blocks):
        while body and not body[-1].strip():
            body = body[:-1]
        out += [h] + list(body) + [""]
    return "\n".join(out).rstrip("\n") + "\n"


def _free_id(want, used):
    i, rid = 1, want
    while rid in used:
        i += 1
        rid = f"{want}{i}"
    used.add(rid)
    return rid


def _sid(kind, rid):
    return f"{kind}_" + re.sub(r"[^A-Za-z0-9_]", "_", rid)


def _ext_line(path_res, rid, kind="Texture2D"):
    return f'[ext_resource type="{kind}" path="{path_res}" id="{rid}"]'


def _canvas_block(sid, diffuse_id, normal_id):
    return [f'[sub_resource type="CanvasTexture" id="{sid}"]',
            [f'diffuse_texture = ExtResource("{diffuse_id}")', f'normal_texture = ExtResource("{normal_id}")']]


def _ext_table(bl, src_file):
    """{id: (header, attrs, absolute path or None)} of a resource's ext_resources; relative paths resolved against the
    file that names them."""
    out = {}
    for h, _ in bl[1:]:
        if _tag(h) == "ext_resource":
            at = attrs(h)
            p = at.get("path", "")
            try:
                full = _from_res(p, src_file) if p else None
            except core.ToolError:
                full = None
            out[at.get("id", "")] = (h, at, full)
    return out



# ---- normal maps -------------------------------------------------------------------
def _png(path):
    return np.array(Image.open(path).convert("RGBA"))


def _save_normal(nm, path, man, pairs, opt, extra=None):
    core.save_clean(Image.fromarray(nm, "RGB"), path)
    man.add(path, "normal_map", routes=(), workflow=WF, convention="opengl (green up, as Godot 4 expects)",
            pairs_with=_rel(pairs),
            bevel=opt.get("bevel_used"), detail=opt["detail"], **(extra or {}))
    return path


def sprite_normal(a, opt, cache):
    """One sprite's normal map, computed once per distinct picture: a still pose repeated across frames gets the
    very same map (normals.py is deterministic; the cache only saves the work)."""
    k = ("sprite", hashlib.sha256(a.tobytes()).hexdigest(), a.shape, opt["bevel"], opt["detail"], opt["strength"])
    if k not in cache:
        cache[k] = normals.normal_map(a, opt["bevel"], opt["detail"], opt["strength"])
    return cache[k]


# ---- SpriteFrames --------------------------------------------------------------------
def lit_frames(tres, out, man, opt, cache):
    """A normal map for every frame texture of a SpriteFrames, and <out>/<stem>_lit.tres: the same animations whose
    frames are CanvasTextures (the original diffuse PNG + its normal map). Returns (lit .tres or None, frame count,
    first (diffuse, normal) pair for the review sheet)."""
    bl = blocks(_read(tres))
    if not bl or "SpriteFrames" not in bl[0][0]:
        raise core.ToolError(f"lighting: {_rel(tres)} is not a SpriteFrames resource")
    stem = os.path.splitext(os.path.basename(tres))[0]
    ext = _ext_table(bl, tres)
    used = set(ext)
    used_sub = {attrs(h).get("id") for h, _ in bl[1:] if _tag(h) == "sub_resource"}
    in_subs = {i for h, body in bl[1:] if _tag(h) == "sub_resource" for i in EXTREF.findall("\n".join(body))}
    in_res = {i for h, body in bl[1:] if _tag(h) == "resource" for i in EXTREF.findall("\n".join(body))}
    new_ext, new_sub, repl, first = [], [], {}, None
    for rid, (h, at, full) in ext.items():
        # frames only: a texture inside a sub_resource (an AtlasTexture) is left alone, it would draw no normals
        if at.get("type") != "Texture2D" or rid in in_subs or rid not in in_res or not full \
                or not full.lower().endswith(".png") or not os.path.isfile(full):
            continue
        a = _png(full)
        nm = sprite_normal(a, opt, cache)
        npath = os.path.join(out, stem, os.path.splitext(os.path.basename(full))[0] + "_normal.png")
        _save_normal(nm, npath, man, full, dict(opt, bevel_used=opt["bevel"]))
        nid = _free_id(f"{rid}_n", used)
        new_ext.append(_ext_line(_res(npath), nid))
        sid = _free_id(_sid("CanvasTexture", rid), used_sub)
        new_sub.append(_canvas_block(sid, rid, nid))
        repl[rid] = sid
        first = first or (a, nm)
    if not repl:
        raise core.ToolError(f"lighting: {_rel(tres)} has no PNG frame textures to light")
    head = _bump_steps(_strip_uid(bl[0][0]), 2 * len(repl))
    ext_lines = [_absolute(h, at, tres) for h, at, _ in ext.values()] + new_ext
    rest = []
    for h, body in bl[1:]:
        if _tag(h) == "ext_resource":
            continue
        if _tag(h) == "resource":
            body = [EXTREF.sub(lambda m: f'SubResource("{repl[m.group(1)]}")' if m.group(1) in repl else m.group(0), l)
                    for l in body]
        rest.append([h, body])
    subs = [b for b in rest if _tag(b[0]) == "sub_resource"]
    others = [b for b in rest if _tag(b[0]) != "sub_resource"]
    dst = godot._write(os.path.join(out, f"{stem}_lit.tres"), _join(head, ext_lines, new_sub + subs, others))
    man.add(dst, "sprite_frames", routes=(), workflow=WF, lit_from=_rel(tres),
            frames_lit=len(repl), note="frames are CanvasTextures: the original diffuse PNG + a normal map")
    return dst, len(repl), first


def _absolute(h, at, src_file):
    """An ext_resource header with a relative path made res:// (the copy lives in another folder)."""
    p = at.get("path", "")
    if p and not p.startswith(("res://", "uid://")):
        return h.replace(f'path="{p}"', f'path="{_res(_from_res(p, src_file))}"')
    return h


# ---- TileSets ----------------------------------------------------------------------
def _vec(body, key, default, cast=int):
    """The (x, y) of a `key = Vector2(...)` / `Vector2i(...)` line in a section body, else default."""
    for l in body:
        if l.startswith(key + " ="):
            m = VEC2.search(l)
            if m:
                return cast(float(m.group(1))), cast(float(m.group(2)))
    return default


def atlas_cells(size, region, margins=(0, 0), sep=(0, 0), big=None):
    """Tile rects (x, y, w, h) covering an atlas grid: every cell, except that a tile bigger than one cell
    (size_in_atlas) is one rect. Animation frames are plain cells to the right of their tile, so they are covered."""
    W, H = size
    (rw, rh), (mx, my), (sx, sy) = region, margins, sep
    cols = max(0, (W - mx + sx) // (rw + sx))
    rows = max(0, (H - my + sy) // (rh + sy))
    rects, covered = [], set()
    for (cx, cy), (bw, bh) in sorted((big or {}).items()):
        rects.append((mx + cx * (rw + sx), my + cy * (rh + sy), bw * rw + (bw - 1) * sx, bh * rh + (bh - 1) * sy))
        covered |= {(cx + i, cy + j) for i in range(bw) for j in range(bh)}
    for cy in range(rows):
        for cx in range(cols):
            if (cx, cy) not in covered:
                rects.append((mx + cx * (rw + sx), my + cy * (rh + sy), rw, rh))
    return rects


def tile_normal(a, rects, opt, cache):
    k = ("tiles", hashlib.sha256(a.tobytes()).hexdigest(), a.shape, tuple(rects), opt["tile_bevel"], opt["detail"],
         opt["strength"])
    if k not in cache:
        cache[k] = normals.normal_map(a, opt["tile_bevel"], opt["detail"], opt["strength"], cells=rects)
    return cache[k]


def lit_tileset(tres, out, man, opt, cache):
    """<out>/<stem>_lit.tres: the TileSet with every atlas source's texture swapped for a CanvasTexture (the original
    atlas + a normal atlas lit tile by tile). Terrains, collision, probabilities and metadata are copied as they are,
    so verify paints the lit TileSet exactly like the original. Returns (lit .tres or None, sources lit, review info)."""
    bl = blocks(_read(tres))
    if not bl or "TileSet" not in bl[0][0]:
        raise core.ToolError(f"lighting: {_rel(tres)} is not a TileSet resource")
    stem = os.path.splitext(os.path.basename(tres))[0]
    ext = _ext_table(bl, tres)
    used = set(ext)
    used_sub = {attrs(h).get("id") for h, _ in bl[1:] if _tag(h) == "sub_resource"}
    new_ext, new_sub, done, info = [], [], {}, []
    rest = []
    for h, body in bl[1:]:
        if _tag(h) == "ext_resource":
            continue
        at = attrs(h)
        if _tag(h) == "sub_resource" and at.get("type") == "TileSetAtlasSource":
            tex = next((EXTREF.search(l).group(1) for l in body if l.startswith("texture =") and EXTREF.search(l)), None)
            full = ext.get(tex, (None, None, None))[2]
            if full and full.lower().endswith(".png") and os.path.isfile(full):
                region = _vec(body, "texture_region_size", (16, 16))
                margins, sep = _vec(body, "margins", (0, 0)), _vec(body, "separation", (0, 0))
                big = {}
                for l in body:
                    m = re.match(r"^(\d+):(\d+)/size_in_atlas = Vector2i\((\d+), (\d+)\)", l)
                    if m:
                        big[(int(m.group(1)), int(m.group(2)))] = (int(m.group(3)), int(m.group(4)))
                a = _png(full)
                rects = atlas_cells((a.shape[1], a.shape[0]), region, margins, sep, big)
                gkey = (full, tuple(rects))
                if gkey not in done:
                    nm = tile_normal(a, rects, opt, cache)
                    base = os.path.splitext(os.path.basename(full))[0]
                    npath = os.path.join(out, stem, f"{base}_normal.png")
                    if any(v[0] == npath for v in done.values()):   # one atlas cut two ways: one file per grid
                        npath = os.path.join(out, stem, f"{base}_{len(done)}_normal.png")
                    _save_normal(nm, npath, man, full, dict(opt, bevel_used=opt["tile_bevel"]),
                                 {"tile_px": list(region), "per_tile": True})
                    done[gkey] = (npath, _free_id(f"{tex}_n", used))
                    new_ext.append(_ext_line(_res(npath), done[gkey][1]))
                    info.append((a, nm, rects, region))
                sid = _free_id(_sid("CanvasTexture", at.get("id", tex)), used_sub)
                new_sub.append(_canvas_block(sid, tex, done[gkey][1]))
                body = [f'texture = SubResource("{sid}")' if l.startswith("texture =") else l for l in body]
        rest.append([h, body])
    if not new_sub:
        raise core.ToolError(f"lighting: {_rel(tres)} has no PNG atlas source to light")
    head = _bump_steps(_strip_uid(bl[0][0]), len(new_ext) + len(new_sub))
    ext_lines = [_absolute(h, at, tres) for h, at, _ in ext.values()] + new_ext
    subs = [b for b in rest if _tag(b[0]) == "sub_resource"]
    others = [b for b in rest if _tag(b[0]) != "sub_resource"]
    dst = godot._write(os.path.join(out, f"{stem}_lit.tres"), _join(head, ext_lines, new_sub + subs, others))
    man.add(dst, "tileset", routes=(), workflow=WF, lit_from=_rel(tres),
            sources_lit=len(new_sub), note="atlas textures are CanvasTextures; normals lit tile by tile (wrapping "
            "inside each tile, rims only along clear pixels inside a tile)")
    return dst, len(new_sub), info


# ---- props -------------------------------------------------------------------------
def occluder_points(a, mode="base", band=0.25, max_points=12):
    """OccluderPolygon2D corners in texture pixels (pixel-corner coordinates) traced from the alpha of the largest
    4-connected opaque region. "full": its whole outline. "base": only its bottom `band` of the height (at least
    4 px), each row filled from its leftmost to its rightmost pixel, so a bench or a wolf shadows the ground from
    the span of all its feet, not from one leg; a top-down prop then casts from its foot instead of its canopy.
    Marching squares, then Douglas-Peucker down to max_points corners. Every corner touches an opaque pixel (a row
    end in base mode). [] when nothing is opaque."""
    mask = np.asarray(a)[..., 3] >= 128
    if not mask.any():
        return []

    def biggest(m):
        lab, n = lib.label(m, 4)
        if n == 0:
            return m
        return lab == int(np.argmax(np.bincount(lab.ravel())[1:]) + 1)

    m = biggest(mask)
    if mode == "base":
        rows = np.nonzero(m.any(1))[0]
        top, bottom = int(rows.min()), int(rows.max()) + 1
        bh = max(4, int(round((bottom - top) * band)))
        span = np.zeros_like(m)
        for y in range(max(top, bottom - bh), bottom):
            xs = np.nonzero(m[y])[0]
            if len(xs):
                span[y, xs.min():xs.max() + 1] = True
        m = biggest(span)
    return normals.simplify(normals.trace_outline(m), max_points)


def _poly_text(pts):
    return "PackedVector2Array(" + ", ".join(f"{_g(x)}, {_g(y)}" for x, y in pts) + ")"


def _g(v):
    """A number as Godot writes it: no trailing .0 for whole values."""
    v = round(float(v), 3)
    return str(int(v)) if v == int(v) else repr(v)


def _scene_for(png):
    """The scene next to a prop PNG that draws it (lane_props' prop_<name>.tscn, lane_enemies' enemy_<name>.tscn),
    found by its ext_resource path; None when there is none."""
    want = f'path="{_res(png)}"'
    for s in sorted(glob.glob(os.path.join(os.path.dirname(png), "*.tscn"))):
        if want in _read(s):
            return s
    return None


SKIP_NODE_KEYS = ("scale", "rotation", "flip_h", "flip_v", "hframes", "vframes", "region_enabled", "skew")


def _lit_from_scene(scene, png, canvas_res, pts, size):
    """The prop's own scene with its texture swapped for the CanvasTexture and a LightOccluder2D added under the root,
    the polygon placed where the sprite draws (its offset, centring and position). None when the sprite node is
    transformed in a way this does not follow (scaled, flipped, nested, a region): a fresh scene is written then."""
    bl = blocks(_read(scene))
    want = _res(png)
    tid = next((attrs(h).get("id") for h, _ in bl[1:] if _tag(h) == "ext_resource" and attrs(h).get("path") == want),
               None)
    node = next(((h, body) for h, body in bl[1:] if _tag(h) == "node"
                 and any(l.strip() == f'texture = ExtResource("{tid}")' for l in body)), None)
    if tid is None or node is None:
        return None
    nat, body = attrs(node[0]), node[1]
    if nat.get("parent") not in (None, ".") or any(l.split(" =")[0] in SKIP_NODE_KEYS for l in body):
        return None
    off = _vec(body, "offset", (0.0, 0.0), float)
    pos = _vec(body, "position", (0.0, 0.0), float) if nat.get("parent") == "." else (0.0, 0.0)
    centered = not any(l.strip() == "centered = false" for l in body)
    w, h = size
    cx, cy = ((-w / 2.0, -h / 2.0) if centered else (0.0, 0.0))
    local = [(x + cx + off[0] + pos[0], y + cy + off[1] + pos[1]) for x, y in pts]
    head = _bump_steps(_strip_uid(bl[0][0]), 1)
    ext_lines, subs, others = [], [], []
    for hh, bb in bl[1:]:
        t = _tag(hh)
        if t == "ext_resource":
            at = attrs(hh)
            ext_lines.append(_strip_uid(hh).replace(f'path="{want}"', f'path="{canvas_res}"')
                             if at.get("id") == tid else _absolute(hh, at, scene))
        elif t == "sub_resource":
            subs.append([hh, bb])
        else:
            others.append([hh, bb])
    if pts:
        subs.append(['[sub_resource type="OccluderPolygon2D" id="OccluderPolygon2D_lit"]',
                     [f"polygon = {_poly_text(local)}"]])
        others.append(['[node name="LightOccluder2D" type="LightOccluder2D" parent="."]',
                       ['occluder = SubResource("OccluderPolygon2D_lit")']])
    else:
        head = _bump_steps(head, -1)
    return _join(head, ext_lines, subs, others)


def _fresh_scene(stem, canvas_res, pts, size, bbox):
    """A Node2D with the lit sprite (feet at the origin, as lane_props places props) and the occluder."""
    w, h = size
    x0, y0, x1, y1 = bbox
    off = (round(w / 2 - (x0 + x1) / 2), round(h / 2 - y1))
    local = [(x - w / 2.0 + off[0], y - h / 2.0 + off[1]) for x, y in pts]
    name = "".join(p.title() for p in re.split(r"[^0-9A-Za-z]+", stem) if p) or "Prop"
    subs = [['[sub_resource type="OccluderPolygon2D" id="OccluderPolygon2D_lit"]', [f"polygon = {_poly_text(local)}"]]] \
        if pts else []
    nodes = [[f'[node name="{name}" type="Node2D"]', []],
             ['[node name="Sprite2D" type="Sprite2D" parent="."]',
              ["texture_filter = 1", 'texture = ExtResource("1_tex")', f"offset = Vector2({off[0]}, {off[1]})"]]]
    if pts:
        nodes.append(['[node name="LightOccluder2D" type="LightOccluder2D" parent="."]',
                      ['occluder = SubResource("OccluderPolygon2D_lit")']])
    head = f"[gd_scene load_steps={2 + len(subs)} format=3]"
    return _join(head, [_ext_line(canvas_res, "1_tex")], subs, nodes)


def lit_prop(png, out, man, opt, cache):
    """A prop PNG: normal map, CanvasTexture (.tres) and a lit scene (its own scene's copy, or a fresh Node2D) with a
    LightOccluder2D. Returns (lit scene or None, occluder corner count, (diffuse, normal))."""
    stem = os.path.splitext(os.path.basename(png))[0]
    a = _png(png)
    nm = sprite_normal(a, opt, cache)
    pts = [] if opt["occluder"] == "none" else occluder_points(a, opt["occluder"], opt["band"], opt["points"])
    npath = os.path.join(out, "props", f"{stem}_normal.png")
    _save_normal(nm, npath, man, png, dict(opt, bevel_used=opt["bevel"]),
                 {"occluder": [[x, y] for x, y in pts] if pts else None, "occluder_mode": opt["occluder"]})
    ct = godot._write(os.path.join(out, "props", f"{stem}_canvas.tres"),
                      "\n".join(['[gd_resource type="CanvasTexture" load_steps=3 format=3]', "",
                                 _ext_line(_res(png), "1_diffuse"), _ext_line(_res(npath), "2_normal"), "",
                                 "[resource]", 'diffuse_texture = ExtResource("1_diffuse")',
                                 'normal_texture = ExtResource("2_normal")', ""]))
    man.add(ct, "canvas_texture", routes=(), workflow=WF, diffuse=_rel(png))
    if ct is None:   # --engine none: the PNG normal map (with the occluder corners in its row) is the output
        return None, len(pts), (a, nm)
    scene = _scene_for(png)
    bbox = Image.fromarray(a).getbbox() or (0, 0, a.shape[1], a.shape[0])
    text = _lit_from_scene(scene, png, _res(ct), pts, (a.shape[1], a.shape[0])) if scene else None
    text = text or _fresh_scene(stem, _res(ct), pts, (a.shape[1], a.shape[0]), bbox)
    dst = godot._write(os.path.join(out, "props", f"{stem}_lit.tscn"), text)
    man.add(dst, "scene", routes=(), workflow=WF, node="lit prop + LightOccluder2D" if pts else "lit prop",
            from_scene=_rel(scene) if scene and text else None,
            occluder=opt["occluder"], occluder_points=len(pts))
    return dst, len(pts), (a, nm)


# ---- demo scene ----------------------------------------------------------------------
def tile_map_data(cells):
    """TileMapLayer.tile_map_data bytes: format 0, then per cell x, y (int16), source, atlas x, atlas y, alternative
    (uint16), little endian (the layout Godot 4.7 saves; checked against a saved map)."""
    b = struct.pack("<H", 0)
    for (x, y), (src, ax, ay) in cells:
        b += struct.pack("<hhHHHH", x, y, src, ax, ay, 0)
    return b


def _floor_tiles(tres_text):
    """(source id, [(atlas x, atlas y)], tile size) for the demo floor: the first source's plain tiles (no terrain),
    else its full tiles (every peering bit = its own terrain), else its first tile."""
    bl = blocks(tres_text)
    res_body = next((b for h, b in bl if _tag(h) == "resource"), [])
    tile = _vec(res_body, "tile_size", (16, 16))
    src = next((re.match(r"^sources/(\d+) = SubResource\(\"([^\"]+)\"\)", l) for l in res_body
                if re.match(r"^sources/\d+ = SubResource", l)), None)
    if src is None:
        return None, [], tile
    body = next((b for h, b in bl if _tag(h) == "sub_resource" and attrs(h).get("id") == src.group(2)), [])
    tiles, terrain, peers = [], {}, {}
    for l in body:
        m = re.match(r"^(\d+):(\d+)/0 = 0$", l)
        if m:
            tiles.append((int(m.group(1)), int(m.group(2))))
        m = re.match(r"^(\d+):(\d+)/0/terrain = (-?\d+)$", l)
        if m:
            terrain[(int(m.group(1)), int(m.group(2)))] = m.group(3)
        m = re.match(r"^(\d+):(\d+)/0/terrains_peering_bit/\w+ = (-?\d+)$", l)
        if m:
            peers.setdefault((int(m.group(1)), int(m.group(2))), set()).add(m.group(3))
    plain = [t for t in tiles if t not in terrain]
    full = [t for t in tiles if t in terrain and peers.get(t, set()) <= {terrain[t]}]
    return int(src.group(1)), (plain or full or tiles[:1]), tile


def _color_text(rgb):
    return "Color(%s, %s, %s, 1)" % tuple(_g(c / 255.0) for c in rgb)


def demo_scene(path, name, tileset, frames, props, opt):
    """A lit demo: CanvasModulate dims the scene, a TileMapLayer floor from the lit TileSet, the lit props and the
    lit character on a y-sorted Node2D, one PointLight2D with shadows (its height makes the normal maps read), and a
    Camera2D at 2x."""
    ext, subs, nodes = [], [], []
    tw, th = 32, 32
    if tileset:
        src, floor, (tw, th) = _floor_tiles(_read(tileset))
        ext.append(_ext_line(_res(tileset), "1_tiles", "TileSet"))
    W, H = DEMO_CELLS[0] * tw, DEMO_CELLS[1] * th
    nodes.append([f'[node name="{name}" type="Node2D"]', []])
    nodes.append(['[node name="CanvasModulate" type="CanvasModulate" parent="."]',
                  [f"color = {_color_text(opt['ambient'])}"]])
    if tileset and floor:
        cells = [((x, y), (src, *floor[(x * 7 + y * 13) % len(floor)])) for y in range(DEMO_CELLS[1])
                 for x in range(DEMO_CELLS[0])]
        data = ", ".join(str(v) for v in tile_map_data(cells))
        nodes.append(['[node name="Floor" type="TileMapLayer" parent="."]',
                      [f"tile_map_data = PackedByteArray({data})", 'tile_set = ExtResource("1_tiles")']])
    nodes.append(['[node name="Objects" type="Node2D" parent="."]', ["y_sort_enabled = true"]])
    for k, p in enumerate(props[:4]):
        rid = f"{k + 2}_prop"
        ext.append(_ext_line(_res(p), rid, "PackedScene"))
        x, y = W * (0.2 + 0.2 * k), H * (0.45 if k % 2 == 0 else 0.75)
        nodes.append([f'[node name="Prop{k + 1}" parent="Objects" instance=ExtResource("{rid}")]',
                      [f"position = Vector2({_g(round(x))}, {_g(round(y))})"]])
    if frames:
        ext.append(_ext_line(_res(frames), "9_frames", "SpriteFrames"))
        anim = re.search(r'"name": &"([^"]+)"', _read(frames))
        body = [f"position = Vector2({_g(round(W * 0.5))}, {_g(round(H * 0.6))})", "texture_filter = 1",
                'sprite_frames = ExtResource("9_frames")']
        if anim:
            body += [f'animation = &"{anim.group(1)}"', f'autoplay = "{anim.group(1)}"']
        nodes.append(['[node name="Character" type="AnimatedSprite2D" parent="Objects"]', body])
    subs.append(['[sub_resource type="Gradient" id="Gradient_light"]',
                 ["offsets = PackedFloat32Array(0, 1)", "colors = PackedColorArray(1, 1, 1, 1, 0, 0, 0, 1)"]])
    subs.append(['[sub_resource type="GradientTexture2D" id="GradientTexture2D_light"]',
                 ['gradient = SubResource("Gradient_light")', "width = 256", "height = 256", "fill = 1",
                  "fill_from = Vector2(0.5, 0.5)", "fill_to = Vector2(1, 0.5)"]])
    nodes.append(['[node name="Light" type="PointLight2D" parent="."]',
                  [f"position = Vector2({_g(round(W * 0.42))}, {_g(round(H * 0.5))})",
                   f"color = {_color_text(opt['light_color'])}", f"energy = {_g(opt['light_energy'])}",
                   "shadow_enabled = true", 'texture = SubResource("GradientTexture2D_light")',
                   f"texture_scale = {_g(opt['light_range'] / 128.0)}", f"height = {_g(opt['light_height'])}"]])
    nodes.append(['[node name="Camera2D" type="Camera2D" parent="."]',
                  [f"position = Vector2({_g(W / 2)}, {_g(H / 2)})", "zoom = Vector2(2, 2)"]])
    head = f"[gd_scene load_steps={len(ext) + len(subs) + 1} format=3]"
    return godot._write(path, _join(head, ext, subs, nodes))


# ---- review sheet --------------------------------------------------------------------
LIGHTS = ((-1.0, 1.0, 0.6), (1.0, 0.15, 0.4))   # from the top left, from the right (x right, y up, z out)


def _tile_block(a, nm, rect):
    """(label, diffuse, normal): the first tile repeated 3x3 (a square tile: a seam would show as a line), or alone
    (iso diamonds do not tile on a square grid)."""
    x, y, w, h = rect
    reps = 3 if w == h else 1
    return (f"tile {reps}x{reps}", np.tile(a[y:y + h, x:x + w], (reps, reps, 1)),
            np.tile(nm[y:y + h, x:x + w], (reps, reps, 1)))


def review_sheet(rows, path, cell=168):
    """rows: [(label, diffuse RGBA, normal RGB)] -> one PNG: diffuse | normal | lit from the top left | lit from the
    right (numpy Lambert, ambient 0.25), each scaled up by a whole factor onto a dark backdrop. Review only: Godot
    does the real lighting (PointLight2D height, CanvasModulate)."""
    cols = ("diffuse", "normal", "lit top-left", "lit right")
    cell = max([cell] + [max(a.shape[:2]) for _, a, _ in rows])   # a big atlas crop widens every cell
    lw, top = 120, 18
    sheet = Image.new("RGBA", (lw + len(cols) * (cell + 6), top + len(rows) * (cell + 6)), (40, 40, 48, 255))
    d = ImageDraw.Draw(sheet)
    for c, t in enumerate(cols):
        d.text((lw + c * (cell + 6) + 4, 3), t, fill=(240, 220, 160))
    for r, (label, a, nm) in enumerate(rows):
        y = top + r * (cell + 6)
        d.text((4, y + cell // 2 - 6), label[:19], fill=(240, 220, 160))
        alpha = a[..., 3:4]
        ims = [a, np.dstack([nm, alpha[..., 0]])] + [normals.shade(a, nm, L, 0.25) for L in LIGHTS]
        for c, im in enumerate(ims):
            pic = Image.fromarray(im.astype(np.uint8), "RGBA")
            k = max(1, min(cell // pic.width, cell // pic.height))
            pic = pic.resize((pic.width * k, pic.height * k), Image.NEAREST)
            sheet.alpha_composite(pic, (lw + c * (cell + 6) + (cell - pic.width) // 2, y + (cell - pic.height) // 2))
    core.save_clean(sheet, path)
    return path


# ---- the lane ------------------------------------------------------------------------
def _deps(frames, tilesets, props):
    """Every file the entry's output depends on: the inputs, the PNGs their .tres name, the props' own scenes."""
    deps = list(frames) + list(tilesets) + list(props)
    for t in list(frames) + list(tilesets):
        bl = blocks(_read(t))
        deps += [f for _, at, f in _ext_table(bl, t).values() if f and os.path.isfile(f) and f.lower().endswith(".png")]
    deps += [s for s in (_scene_for(p) for p in props) if s]
    return sorted(set(deps))


def run(entries, pack, man, conf):
    for e in entries:
        name = core.snake(e["name"])
        opt = options(e)
        frames = _inputs(e["name"], "frames", e.get("frames"), (".tres",))
        tilesets = _inputs(e["name"], "tilesets", e.get("tilesets"), (".tres",))
        props = _inputs(e["name"], "props", e.get("props"), (".png",))
        if not (frames or tilesets or props):
            raise core.ToolError(f"lighting {e['name']}: give at least one of frames, tilesets or props")
        out = core.art(conf, "lit", name)
        lit_root = core.art(conf, "lit")
        for f in frames + tilesets + props:   # a lit copy is never lit again (and never deleted by its own re-run)
            if _inside(f, lit_root):
                raise core.ToolError(f"lighting {e['name']}: {_rel(f)} is already lit output "
                                     "(name the original under assets/art)")
        deps = _deps(frames, tilesets, props)
        req = core.key(json.dumps(e, sort_keys=True), godot.ENABLED,   # --engine none writes no .tres / .tscn
                       *[_rel(f) + ":" + core.sha256_file(f)[:12] for f in deps])
        stamp = core.work("lighting", f"{name}.stamp")
        if os.path.isdir(out) and os.listdir(out) and os.path.exists(stamp):
            with open(stamp, encoding="utf-8") as f:
                if f.read() == req:
                    core.log(f"lighting {name}: up to date")
                    continue
        man.drop_dir(out)
        cache, review = {}, []
        lit_frames_out, lit_tiles_out, lit_props_out = [], [], []
        for t in frames:
            dst, n, first = lit_frames(t, out, man, opt, cache)
            lit_frames_out.append(dst)
            review.append((os.path.basename(t)[:-5], first[0], first[1]))
            core.log(f"lighting {name}: {_rel(t)}: {n} frames lit")
        for t in tilesets:
            dst, n, info = lit_tileset(t, out, man, opt, cache)
            lit_tiles_out.append(dst)
            if info:   # a 3x3 block of the first tile (seams show here), and of the second atlas's corner
                a, nm, rects, _ = info[0]
                review.append(_tile_block(a, nm, rects[0]))
                if len(info) > 1:
                    a2, nm2, rects2, (rw, rh) = info[1]
                    review.append(("atlas corner", a2[:rh * 3, :rw * 3], nm2[:rh * 3, :rw * 3]))
            core.log(f"lighting {name}: {_rel(t)}: {n} atlas sources lit")
        for p in props:
            dst, npts, pair = lit_prop(p, out, man, opt, cache)
            lit_props_out.append(dst)
            review.append((os.path.basename(p)[:-4], pair[0], pair[1]))
            core.log(f"lighting {name}: {_rel(p)}: normal map" + (", CanvasTexture, lit scene" if dst else "") +
                     f", occluder {opt['occluder']} ({npts} corners)")
        if opt["demo"] and godot.ENABLED:
            demo = demo_scene(os.path.join(out, f"{name}_demo.tscn"), "".join(x.title() for x in name.split("_")) + "Demo",
                              next(iter(lit_tiles_out), None), next(iter(lit_frames_out), None),
                              [p for p in lit_props_out if p], opt)
            man.add(demo, "scene", routes=(), workflow=WF, node="Node2D: CanvasModulate, TileMapLayer, props, "
                    "AnimatedSprite2D, PointLight2D (shadows), Camera2D", light_energy=opt["light_energy"],
                    light_height=opt["light_height"])
        if review:
            review_sheet(review[:10], core.src(conf, "art", "lit", name, f"{name}_review.png"))
        with open(core.safe_dest(stamp), "w", encoding="utf-8") as f:   # written last: a failed run re-runs
            f.write(req)
        core.log(f"lighting {name}: {len(frames)} SpriteFrames, {len(tilesets)} TileSets, {len(props)} props -> "
                 f"{_rel(out)}")
