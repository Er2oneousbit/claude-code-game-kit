#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_diorama.py
# Purpose : 2.5D: the game's 2D art in a 3D Godot scene. Tiles become floor quads and raised blocks laid out from a
#           text map, props and characters stand on them as pixel-crisp billboards (Sprite3D / AnimatedSprite3D that
#           turn to the camera around their vertical axis), under a tilted camera with sun, ambient light and an
#           optional depth-of-field blur that makes it read as a little diorama.
# Usage   : pack spec "diorama": [{"name": "yard",
#             "legend": {"g": {"top": "assets/art/tiles/street/base_grass_lush.png"},
#                        "c": {"top": "assets/art/tiles/street/overlay_cobble.png", "tile": "solid"},
#                        "w": {"top": "assets/art/tiles/street/overlay_cobble.png", "tile": "solid",
#                              "side": "assets/art/tiles/street/overlay_stone_wall.png", "height": 1}},
#             "rows": ["ggggg", "gcwcg", "ggggg"],
#             "sprites": [{"source": "assets/art/props/spr_barrel.png", "at": [1, 0]},
#                         {"frames": "assets/art/characters/guard/guard_frames.tres", "animation": "walk_s", "at": [3, 2]}],
#             "camera": {"tilt": 40, "fov": 30, "distance": 9, "dof": true}}]
#           tile: [column, row] of the cell in the image (default [0, 0]) or "solid" (the first fully opaque cell, the
#           middle of a blob atlas); height: blocks in tiles (default 0, flat); tile_px: default design.tile_px.
# Notes   : One world unit is one tile: billboards use pixel_size 1 / tile_px, so a 32 px tile and a 64 px tall
#           sprite keep their 2D proportions. Nearest filtering and alpha-scissor everywhere (no blur, correct depth).
#           Writes <art_dir>/diorama/<name>/diorama_<name>.tscn and the cut-out tile textures beside it.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import math
import os
import re

import numpy as np
from PIL import Image

import fcore as core
import godot


def cell(img, tile_px, tile):
    """The tile_px square at tile = [col, row] of img, or the first fully opaque one for "solid"."""
    a = np.array(img.convert("RGBA"))
    cols, rows = a.shape[1] // tile_px, a.shape[0] // tile_px
    if tile == "solid":
        for r in range(rows):
            for c in range(cols):
                if (a[r * tile_px:(r + 1) * tile_px, c * tile_px:(c + 1) * tile_px, 3] == 255).all():
                    return a[r * tile_px:(r + 1) * tile_px, c * tile_px:(c + 1) * tile_px], [c, r]
        raise core.ToolError("diorama: no fully opaque tile in the image for \"tile\": \"solid\"")
    c, r = (tile or [0, 0])
    if not (0 <= c < cols and 0 <= r < rows):
        raise core.ToolError(f"diorama: tile {[c, r]} is outside the image ({cols} x {rows} tiles of {tile_px} px)")
    return a[r * tile_px:(r + 1) * tile_px, c * tile_px:(c + 1) * tile_px], [c, r]


def frame_size(frames_path):
    """(w, h) of the first texture a SpriteFrames .tres names (its files sit in the game; res:// is the game root)."""
    with open(frames_path, encoding="utf-8") as f:
        m = re.search(r'path="res://([^"]+)"', f.read())
    if not m:
        raise core.ToolError(f"diorama: {os.path.basename(frames_path)} names no texture")
    with Image.open(os.path.join(core.PROJECT, m.group(1))) as im:
        return im.size


def camera_pose(cx, cz, tilt, distance):
    """Camera position looking at (cx, 0, cz) from the south, pitched down by tilt degrees (rotation about X)."""
    t = math.radians(tilt)
    return (cx, distance * math.sin(t), cz + distance * math.cos(t)), (-tilt, 0.0, 0.0)


def _v3(v):
    return "Vector3(%s)" % ", ".join(("%.6g" % x) for x in v)


class Scene:
    def __init__(self):
        self.ext, self.sub, self.nodes = [], [], []

    def ext_res(self, kind, path):
        rid = f"{len(self.ext) + 1}_r"
        self.ext.append(f'[ext_resource type="{kind}" path="{path}" id="{rid}"]')
        return f'ExtResource("{rid}")'

    def sub_res(self, kind, **props):
        rid = f"{kind}_{len(self.sub) + 1}"
        self.sub.append("\n".join([f'[sub_resource type="{kind}" id="{rid}"]'] +
                                  [f"{k} = {v}" for k, v in props.items()]))
        return f'SubResource("{rid}")'

    def node(self, name, typ, parent=None, **props):
        head = f'[node name="{name}" type="{typ}"' + (f' parent="{parent}"' if parent else "") + "]"
        self.nodes.append("\n".join([head] + [f"{k} = {v}" for k, v in props.items()]))

    def text(self):
        return (f"[gd_scene load_steps={len(self.ext) + len(self.sub) + 1} format=3]\n\n" + "\n".join(self.ext) +
                "\n\n" + "\n\n".join(self.sub) + "\n\n" + "\n\n".join(self.nodes) + "\n")


def run(entries, pack, man, conf):
    for e in entries:
        name = core.snake(e["name"])
        tp = int(e.get("tile_px", conf["design"].get("tile_px", 32)))
        rows, legend = e.get("rows"), e.get("legend")
        if not rows or not legend:
            raise core.ToolError(f"diorama {name}: needs \"rows\" (the map as text) and \"legend\" (a tile per letter)")
        unknown = sorted({ch for r in rows for ch in r if ch != " " and ch not in legend})
        if unknown:
            raise core.ToolError(f"diorama {name}: map letters {' '.join(unknown)} are not in the legend")
        art = core.art(conf, "diorama", name)
        res = core.res(conf, "diorama", name)
        man.drop_dir(art)
        sc = Scene()
        mats, heights = {}, {}
        for ch, t in legend.items():
            if "top" not in t:
                raise core.ToolError(f"diorama {name}: legend {ch!r} needs \"top\": a tile image")
            heights[ch] = int(t.get("height", 0))
            for face in ("top", "side"):
                if face not in t:
                    continue
                with Image.open(core.source_path(t[face])) as im:
                    a, at = cell(im, tp, t.get("tile" if face == "top" else "side_tile", [0, 0]))
                fn = f"tile_{core.snake(ch) if ch.isalnum() else ord(ch)}_{face}.png"
                p = core.save_clean(Image.fromarray(a), os.path.join(art, fn))
                man.add(p, "diorama_tile", face=face, source=t[face], cell=at, tile_px=tp)
                tex = sc.ext_res("Texture2D", f"{res}/{fn}")
                props = {"albedo_texture": tex, "texture_filter": "0"}
                if face == "side":
                    props["uv1_scale"] = "Vector3(3, 2, 1)"   # BoxMesh lays its 6 faces out 3 x 2: one tile per face
                if (a[..., 3] < 255).any():
                    props["transparency"] = "2"               # alpha scissor
                mats[(ch, face)] = sc.sub_res("StandardMaterial3D", **props)
        meshes = {}
        for ch in legend:
            meshes[(ch, "top")] = sc.sub_res("PlaneMesh", size="Vector2(1, 1)", material=mats[(ch, "top")])
            if heights[ch] > 0:
                side = mats.get((ch, "side"), mats[(ch, "top")])
                meshes[(ch, "side")] = sc.sub_res("BoxMesh", size=_v3((1, heights[ch], 1)), material=side)
        W, D = max(len(r) for r in rows), len(rows)
        cam = dict(e.get("camera", {}))
        tilt, fov = float(cam.get("tilt", 40)), float(cam.get("fov", 30))
        dist = float(cam.get("distance", max(W, D) * 1.6))
        env = sc.sub_res("Environment", background_mode="1", background_color="Color(0.42, 0.62, 0.86, 1)",
                         ambient_light_source="2", ambient_light_color="Color(0.75, 0.8, 0.95, 1)",
                         ambient_light_energy="0.55")
        cam_props = {}
        if cam.get("dof", True):
            cam_props["attributes"] = sc.sub_res("CameraAttributesPractical", dof_blur_far_enabled="true",
                                                 dof_blur_far_distance="%.3g" % (dist + 2),
                                                 dof_blur_far_transition="%.3g" % max(3.0, dist * 0.5),
                                                 dof_blur_near_enabled="true",
                                                 dof_blur_near_distance="%.3g" % max(1.0, dist * 0.45),
                                                 dof_blur_near_transition="%.3g" % max(1.0, dist * 0.3),
                                                 dof_blur_amount="0.08")
        sc.node(f"Diorama{name.title().replace('_', '')}", "Node3D")
        sc.node("World", "WorldEnvironment", ".", environment=env)
        sc.node("Sun", "DirectionalLight3D", ".", rotation_degrees="Vector3(-52, -35, 0)", light_energy="1.1",
                shadow_enabled="true")
        pos, rot = camera_pose(W / 2.0, D / 2.0, tilt, dist)
        sc.node("Camera", "Camera3D", ".", position=_v3(pos), rotation_degrees=_v3(rot), fov="%.3g" % fov,
                current="true", **cam_props)
        sc.node("Tiles", "Node3D", ".")
        n_cells = n_blocks = 0
        for z, r in enumerate(rows):
            for x, ch in enumerate(r):
                if ch == " ":
                    continue
                h = heights[ch]
                sc.node(f"T{x}_{z}", "MeshInstance3D", "Tiles", position=_v3((x + 0.5, h + 0.001 * (h > 0), z + 0.5)),
                        mesh=meshes[(ch, "top")])
                n_cells += 1
                if h > 0:
                    sc.node(f"B{x}_{z}", "MeshInstance3D", "Tiles", position=_v3((x + 0.5, h / 2.0, z + 0.5)),
                            mesh=meshes[(ch, "side")])
                    n_blocks += 1
        sc.node("Sprites", "Node3D", ".")
        for i, s in enumerate(e.get("sprites", [])):
            x, z = s["at"]
            if not (0 <= z < D and 0 <= x < len(rows[z])):
                raise core.ToolError(f"diorama {name}: sprite {i + 1} at {s['at']} is outside the map")
            ch = rows[z][x]
            y = heights.get(ch, 0)
            common = {"position": _v3((x + 0.5, y, z + 0.5)), "billboard": "2", "texture_filter": "0",
                      "alpha_cut": "1", "shaded": "true", "pixel_size": "%.6g" % (1.0 / tp)}
            if s.get("frames"):
                fp = core.source_path(s["frames"])
                w, h = frame_size(fp)
                anim = s.get("animation", "idle_s")
                fr = sc.ext_res("SpriteFrames", core.linked_res(fp, f"diorama {name}: sprite {i + 1} frames"))
                sc.node(f"S{i}", "AnimatedSprite3D", "Sprites", offset=f"Vector2(0, {h / 2.0:g})", sprite_frames=fr,
                        animation=f'&"{anim}"', autoplay=godot.q(anim), **common)
            elif s.get("source"):
                sp = core.source_path(s["source"])
                with Image.open(sp) as im:
                    w, h = im.size
                tex = sc.ext_res("Texture2D", core.linked_res(sp, f"diorama {name}: sprite {i + 1} source"))
                sc.node(f"S{i}", "Sprite3D", "Sprites", offset=f"Vector2(0, {h / 2.0:g})", texture=tex, **common)
            else:
                raise core.ToolError(f"diorama {name}: sprite {i + 1} needs \"source\" (a PNG) or \"frames\" (.tres)")
        scn = godot._write(os.path.join(art, f"diorama_{name}.tscn"), sc.text())
        man.add(scn, "scene", node="Node3D", cells=n_cells, blocks=n_blocks, sprites=len(e.get("sprites", [])),
                tile_px=tp, workflow="Dotwork diorama (2D art in a 3D scene, no model)")
        core.log(f"diorama {name}: {n_cells} tiles, {n_blocks} raised blocks, {len(e.get('sprites', []))} billboards")
