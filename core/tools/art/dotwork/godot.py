#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# godot.py
# Purpose : write Godot 4 text resources (format 3): SpriteFrames, additive material, effect / sprite / prop scenes,
#           TileSets (one terrain set, or layered with probability, animation and per-tile collision).
# Usage   : imported by the lanes; ENABLED = False (--engine none) turns every writer into a no-op
# Notes   : Never writes .godot/, *.import or *.uid: Godot creates those on import.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

MODE = {"match_corners_and_sides": 0, "match_corners": 1, "match_sides": 2}
CORNERS = ("top_left_corner", "top_right_corner", "bottom_left_corner", "bottom_right_corner")
PEERS8 = ("top_side", "top_right_corner", "right_side", "bottom_right_corner", "bottom_side", "bottom_left_corner",
          "left_side", "top_left_corner")  # blob bit order N, NE, E, SE, S, SW, W, NW (lane_ground.NB8)


ENABLED = True   # dotwork.py sets False for --engine none: PNGs, sheets and JSON still ship


def _write(path, text):
    if not ENABLED:
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def sprite_frames(path, res_dir, animations):
    """animations: {name: (list_of_png_basenames, fps, loop)}; textures live in res_dir (a res:// folder)."""
    ext, anims, n = [], [], 0
    for name, (files, fps, loop) in animations.items():
        refs = []
        for fn in files:
            n += 1
            rid = f"{n}_{name}"
            ext.append(f'[ext_resource type="Texture2D" path="{res_dir.rstrip("/")}/{fn}" id="{rid}"]')
            refs.append(rid)
        fr = ", ".join('{\n"duration": 1.0,\n"texture": ExtResource("%s")\n}' % r for r in refs)
        anims.append('{\n"frames": [%s],\n"loop": %s,\n"name": &"%s",\n"speed": %.1f\n}'
                     % (fr, "true" if loop else "false", name, fps))
    text = (f'[gd_resource type="SpriteFrames" load_steps={len(ext) + 1} format=3]\n\n' + "\n".join(ext) +
            "\n\n[resource]\nanimations = [" + ", ".join(anims) + "]\n")
    return _write(path, text)


def additive_material(path):
    # CanvasItemMaterial.blend_mode: 0 mix, 1 add, 2 sub, 3 mul, 4 premult alpha
    return _write(path, '[gd_resource type="CanvasItemMaterial" format=3]\n\n[resource]\nblend_mode = 1\n')


def effect_scene(path, frames_res, material_res, anim, node_name="Effect"):
    text = (f'[gd_scene load_steps=3 format=3]\n\n'
            f'[ext_resource type="SpriteFrames" path="{frames_res}" id="1_frames"]\n'
            f'[ext_resource type="Material" path="{material_res}" id="2_mat"]\n\n'
            f'[node name="{node_name}" type="AnimatedSprite2D"]\n'
            f'material = ExtResource("2_mat")\n'
            f'sprite_frames = ExtResource("1_frames")\n'
            f'animation = &"{anim}"\n'
            f'autoplay = "{anim}"\n')
    return _write(path, text)


def tileset(path, atlas_res, tile_px, cols, tiles, terrains, mode="match_corners", custom=None):
    """tiles: list of dicts {index, corners: (tl, tr, bl, br) terrain ids, terrain: center id, custom: value}.
    terrains: list of (name, (r, g, b)) in id order. custom: name of a String custom data layer (or None)."""
    lines = [f'[gd_resource type="TileSet" load_steps=3 format=3]', "",
             f'[ext_resource type="Texture2D" path="{atlas_res}" id="1_atlas"]', "",
             '[sub_resource type="TileSetAtlasSource" id="TileSetAtlasSource_1"]',
             'texture = ExtResource("1_atlas")',
             f"texture_region_size = Vector2i({tile_px}, {tile_px})"]
    for t in tiles:
        x, y = t["index"] % cols, t["index"] // cols
        k = f"{x}:{y}/0"
        lines.append(f"{k} = 0")
        lines.append(f"{k}/terrain_set = 0")
        lines.append(f"{k}/terrain = {t['terrain']}")
        for bit, tid in zip(CORNERS, t["corners"]):
            lines.append(f"{k}/terrains_peering_bit/{bit} = {tid}")
        if custom and t.get("custom") is not None:
            lines.append(f'{k}/custom_data_0 = "{t["custom"]}"')
    lines += ["", "[resource]", f"tile_size = Vector2i({tile_px}, {tile_px})",
              f"terrain_set_0/mode = {MODE[mode]}"]
    for i, (name, (r, g, b)) in enumerate(terrains):
        lines.append(f'terrain_set_0/terrain_{i}/name = "{name}"')
        lines.append(f"terrain_set_0/terrain_{i}/color = Color({r / 255:.3f}, {g / 255:.3f}, {b / 255:.3f}, 1)")
    if custom:
        lines += [f'custom_data_layer_0/name = "{custom}"', "custom_data_layer_0/type = 4"]  # TYPE_STRING
    lines.append('sources/0 = SubResource("TileSetAtlasSource_1")')
    return _write(path, "\n".join(lines) + "\n")


def sprite_scene(path, tex_res, node_name="Sprite", scale=1, centered=False, offset=(0, 0)):
    """Sprite2D scene: one texture, integer scale, nearest filtering (battle backgrounds, enemies)."""
    text = "\n".join([
        '[gd_scene load_steps=2 format=3]', "",
        f'[ext_resource type="Texture2D" path="{tex_res}" id="1_tex"]', "",
        f'[node name="{node_name}" type="Sprite2D"]',
        "texture_filter = 1",
        'texture = ExtResource("1_tex")',
        f"centered = {'true' if centered else 'false'}",
        f"offset = Vector2({offset[0]}, {offset[1]})",
        f"scale = Vector2({scale}, {scale})", ""])
    return _write(path, text)


def prop_scene(path, tex_res, size, bbox, node_name="Prop", solid=True, footprint="base"):
    """Y-sortable prop: the node origin is at the object's feet (bottom-centre of its content), the sprite is
    offset to match, and a StaticBody2D footprint box blocks movement. Put props under a Node2D with
    y_sort_enabled so characters pass behind / in front by their feet.
    footprint: base (80% of the content width x 12 px), trunk (25% x 8 px: trees, posts, lamps), or [w, h]."""
    w, h = size
    x0, y0, x1, y1 = bbox
    cx, bottom = (x0 + x1) / 2, y1
    off = (round(w / 2 - cx), round(h / 2 - bottom))  # Sprite2D is centred: shift so (cx, bottom) lands on 0,0
    cw = x1 - x0
    fw, fh = {"base": (max(4, round(cw * 0.8)), 12), "trunk": (max(4, round(cw * 0.25)), 8)}.get(
        footprint, footprint if isinstance(footprint, (list, tuple)) else (round(cw * 0.8), 12))
    root = "StaticBody2D" if solid else "Node2D"
    lines = [f'[gd_scene load_steps={3 if solid else 2} format=3]', "",
             f'[ext_resource type="Texture2D" path="{tex_res}" id="1_tex"]', ""]
    if solid:
        lines += ['[sub_resource type="RectangleShape2D" id="RectangleShape2D_1"]', f"size = Vector2({fw}, {fh})", ""]
    lines += [f'[node name="{node_name}" type="{root}"]', "",
              '[node name="Sprite2D" type="Sprite2D" parent="."]', "texture_filter = 1",
              'texture = ExtResource("1_tex")', f"offset = Vector2({off[0]}, {off[1]})", ""]
    if solid:
        lines += ['[node name="CollisionShape2D" type="CollisionShape2D" parent="."]',
                  f"position = Vector2(0, {-fh // 2})", 'shape = SubResource("RectangleShape2D_1")', ""]
    return _write(path, "\n".join(lines)), (fw, fh)


# quadrant boxes (tile-center coordinates) for per-corner collision, in CORNERS order
def _quad(h, i):
    x0, y0 = (-h if i in (0, 2) else 0), (-h if i in (0, 1) else 0)
    return f"PackedVector2Array({x0}, {y0}, {x0 + h}, {y0}, {x0 + h}, {y0 + h}, {x0}, {y0 + h})"


def tileset_layers(path, tile_px, sources, terrains, custom=None, physics=False, mode="match_corners",
                   overlays=()):
    """One TileSet for stacked TileMapLayers (base fill, one layer per overlay terrain, decals, roofs ...).
    sources: [{"atlas_res": res path, "tiles": [{"x", "y", "terrain": id or -1 (or None = no terrain),
               "corners": (tl, tr, bl, br) ids or -1, "probability": float, "custom": str, "solid": [corner idx]}]}]
    terrains: [(name, (r, g, b))] in id order, all in terrain set 0 (each overlay layer paints one of them).
    solid: corners whose quadrant gets a collision box on physics layer 0 (water, walls)."""
    n = len(sources)
    lines = [f'[gd_resource type="TileSet" load_steps={2 * n + 1} format=3]', ""]
    for i, s in enumerate(sources):
        lines.append(f'[ext_resource type="Texture2D" path="{s["atlas_res"]}" id="{i + 1}_atlas"]')
    lines.append("")
    h = tile_px // 2
    for i, s in enumerate(sources):
        lines += [f'[sub_resource type="TileSetAtlasSource" id="TileSetAtlasSource_{i + 1}"]',
                  f'texture = ExtResource("{i + 1}_atlas")', f"texture_region_size = Vector2i({tile_px}, {tile_px})"]
        for t in s["tiles"]:
            if t.get("anim"):  # atlas animation: frames sit to the right of the base tile (probed Godot 4.7 syntax)
                ak = f'{t["x"]}:{t["y"]}'
                nf = int(t["anim"]["frames"])   # not n: n is the source count used for sources/ below
                lines += [f"{ak}/animation_columns = {nf}", f'{ak}/animation_speed = {float(t["anim"]["fps"]):.1f}']
                lines += [f"{ak}/animation_frame_{f}/duration = 1.0" for f in range(nf)]
            k = f'{t["x"]}:{t["y"]}/0'
            lines.append(f"{k} = 0")
            if t.get("probability", 1.0) != 1.0:
                lines.append(f'{k}/probability = {t["probability"]:.3f}')
            if t.get("terrain") is not None:
                lines += [f"{k}/terrain_set = 0", f'{k}/terrain = {t["terrain"]}']
                # blob tiles carry 8 "peers" (N, NE, E, SE, S, SW, W, NW); corner tiles carry 4 "corners"
                bits = zip(PEERS8, t["peers"]) if "peers" in t else zip(CORNERS, t["corners"])
                for bit, tid in bits:
                    lines.append(f"{k}/terrains_peering_bit/{bit} = {tid}")
            if custom and t.get("custom") is not None:
                lines.append(f'{k}/custom_data_0 = "{t["custom"]}"')
            if physics:
                polys = [_quad(h, ci) for ci in t.get("solid") or []]
                polys += [f"PackedVector2Array({x0}, {y0}, {x1}, {y0}, {x1}, {y1}, {x0}, {y1})"
                          for x0, y0, x1, y1 in t.get("solid_rects") or []]
                for j, poly in enumerate(polys):
                    lines.append(f"{k}/physics_layer_0/polygon_{j}/points = {poly}")
        lines.append("")
    lines += ["[resource]", f"tile_size = Vector2i({tile_px}, {tile_px})"]
    if physics:
        lines += ["physics_layer_0/collision_layer = 1", "physics_layer_0/collision_mask = 1"]
    lines.append(f"terrain_set_0/mode = {MODE[mode]}")
    for i, (name, (r, g, b)) in enumerate(terrains):
        lines.append(f'terrain_set_0/terrain_{i}/name = "{name}"')
        lines.append(f"terrain_set_0/terrain_{i}/color = Color({r / 255:.3f}, {g / 255:.3f}, {b / 255:.3f}, 1)")
    if custom:
        lines += [f'custom_data_layer_0/name = "{custom}"', "custom_data_layer_0/type = 4"]  # TYPE_STRING
    for i in range(n):
        lines.append(f'sources/{i} = SubResource("TileSetAtlasSource_{i + 1}")')
    if overlays:  # verify paints these terrain ids on an empty layer (overlay test) instead of the pair test
        lines.append(f"metadata/dotwork_overlays = PackedInt32Array({', '.join(str(i) for i in overlays)})")
    return _write(path, "\n".join(lines) + "\n")
