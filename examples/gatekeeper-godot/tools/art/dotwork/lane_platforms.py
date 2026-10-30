#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_platforms.py
# Purpose : side-view (platformer) terrain: a 16-tile set that matches on its sides (fill texture inside, a surface lip
#           such as grass on top, shaded rims and an outline on the exposed sides, rounded outer corners), one-way
#           platform caps, a Godot TileSet (terrain mode "match sides", full-tile collision, one-way caps) and an
#           optional horizontally seamless parallax background with its scene. A level preview shows the set in use.
# Usage   : pack spec "platforms": [{"name": "meadow", "fill": {"material": "dirt"}, "surface": {"material": "grass_lush"},
#           "background": {"prompt": "rolling green hills under a blue sky"}}]
#           fill / surface: a catalog material ({"material": ...}) or {"prompt": ...}; tile (px, default design.tile_px);
#           lip (surface depth as a share of the tile, default 0.35); background optional (prompt, seed).
# Notes   : Textures come from the ground lane (seamless, native pixel scale), so tiles join with no seam in every
#           direction. The terrain set uses side peering only (Godot "Match Sides"): paint with the terrain tool or
#           set_cells_terrain_connect. The parallax layer mirrors itself horizontally (motion_mirroring).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import numpy as np
from PIL import Image

import fcore as core
import godot
import engine as lib
from lane_ground import _from_catalog, texture

OUTLINE = np.array([5, 4, 7], np.uint8)   # the shared Dotwork outline colour
SIDES = ("top_side", "right_side", "bottom_side", "left_side")   # bit order N, E, S, W
BG_TPL = ("pixel art, {style} side-scrolling game background, a wide side view of {s}, layered depth, distant "
          "details, no characters, no text, {setting}")
LEVEL = ["..........................",
         "..............###.........",
         "......====...........##...",
         "...........#####.....##...",
         "##.....##################..",
         "##########################."]


def _mat(e, key, m):
    """(name, prompt, seed, tpl) of the entry's fill / surface m: a catalog material or a prompt. The caller reads m
    as e.get("fill"): the spec checker learns a lane's keys from literal reads, and e.get(key) warned "fill" as a typo."""
    if not m:
        raise core.ToolError(f"platforms {e['name']}: \"{key}\" needs {{\"material\": ...}} or {{\"prompt\": ...}}")
    m = _from_catalog(dict(m, name=m.get("material") or f"{core.snake(e['name'])}_{key}"))
    return m["name"], m["prompt"], int(m.get("seed", 800)), m.get("tpl", "ground")


def _noise(n, seed, amp):
    """Smooth, wrapping 1-D offsets in [-amp, amp]: the lip's lower edge and the grass tops."""
    rng = np.random.default_rng(seed)
    k = rng.normal(size=6)
    x = np.arange(n) / n * 2 * np.pi
    v = sum(k[i] * np.sin((i + 1) * x + k[-1] * i) for i in range(4))
    return np.round(v / max(1e-6, np.abs(v).max()) * amp).astype(int)


def tile(mask, fill, surf, T, lip, wave, tufts):
    """One T px tile for a 4-bit exposure mask (bit set = that side has no platform next to it: N, E, S, W)."""
    top, right, bottom, left = (bool(mask >> b & 1) for b in range(4))
    a = np.dstack([fill, np.full((T, T), 255, np.uint8)])
    shade = (fill.astype(np.float32) * 0.62).astype(np.uint8)
    rim = max(2, T // 12)
    if right:
        a[:, T - rim:T, :3] = shade[:, T - rim:T]
    if left:
        a[:, :rim, :3] = shade[:, :rim]
    if bottom:
        a[T - rim:, :, :3] = shade[T - rim:]
    if top:   # the surface lip: the surface texture's own rows, down to a wavy edge, a light top row, tufts above it
        depth = max(3, int(T * lip))
        for x in range(T):
            d = depth + wave[x]
            a[:d, x, :3] = surf[:d, x]
            a[d:d + 1, x, :3] = (surf[d - 1, x].astype(np.float32) * 0.55).astype(np.uint8)   # the lip's shadow line
        hi = np.clip(surf[1].astype(np.float32) * 1.25, 0, 255).astype(np.uint8)
        a[1, :, :3] = hi
        for x in range(T):   # a jagged grass top: some columns start a pixel lower
            if tufts[x] < 0:
                a[0, x, 3] = 0
    # the outline on every exposed side, then round the outer corners
    op = a[..., 3] == 255
    edge = np.zeros((T, T), bool)
    if top:
        first = np.argmax(op, axis=0)
        edge[first, np.arange(T)] = True
    if bottom:
        edge[T - 1, :] = True
    if left:
        edge[:, 0] = True
    if right:
        edge[:, T - 1] = True
    a[edge & op, :3] = OUTLINE
    for cond, (ys, xs) in (((top and left), (0, 0)), ((top and right), (0, T - 1)), ((bottom and left), (T - 1, 0)),
                           ((bottom and right), (T - 1, T - 1))):
        if cond:
            a[ys, xs, 3] = 0
    return a


def oneway(fill, surf, T, lip, wave, part):
    """A one-way platform piece: only the surface lip and a thin underside, transparent below (part: left / mid /
    right)."""
    m = 1 | (2 if part == "right" else 0) | 4 | (8 if part == "left" else 0)
    a = tile(m, fill, surf, T, lip, wave, np.zeros(T, int))
    depth = max(3, int(T * lip)) + 3
    a[depth:, :, 3] = 0
    a[depth - 1, :, :3] = OUTLINE
    return a


def atlas(fill, surf, T, lip, seed):
    """16 side-matching tiles (index = exposure mask) + 3 one-way pieces, in one 8-wide atlas."""
    wave = _noise(T, seed, max(1, T // 16))
    tufts = _noise(T, seed + 1, 1)
    tiles = [tile(m, fill, surf, T, lip, wave, tufts) for m in range(16)]
    tiles += [oneway(fill, surf, T, lip, wave, p) for p in ("left", "mid", "right")]
    cols = 8
    rows = (len(tiles) + cols - 1) // cols
    at = np.zeros((rows * T, cols * T, 4), np.uint8)
    for i, t in enumerate(tiles):
        at[(i // cols) * T:(i // cols + 1) * T, (i % cols) * T:(i % cols + 1) * T] = t
    return at, tiles


def tileset(path, atlas_res, T, cols, n_full=16):
    """TileSet: terrain set 0 in Match Sides mode; tile m (0-15) peers on the sides where mask bit m is clear (that
    side touches more platform); full-tile collision; the three one-way pieces collide from above only."""
    lines = ['[gd_resource type="TileSet" load_steps=3 format=3]', "",
             f'[ext_resource type="Texture2D" path="{atlas_res}" id="1_atlas"]', "",
             '[sub_resource type="TileSetAtlasSource" id="TileSetAtlasSource_1"]', 'texture = ExtResource("1_atlas")',
             f"texture_region_size = Vector2i({T}, {T})"]
    h = T // 2
    full = f"PackedVector2Array({-h}, {-h}, {h}, {-h}, {h}, {h}, {-h}, {h})"
    thin = f"PackedVector2Array({-h}, {-h}, {h}, {-h}, {h}, {-h + max(3, T // 4)}, {-h}, {-h + max(3, T // 4)})"
    for i in range(n_full + 3):
        k = f"{i % cols}:{i // cols}/0"
        lines.append(f"{k} = 0")
        if i < n_full:
            lines += [f"{k}/terrain_set = 0", f"{k}/terrain = 0"]
            for b, side in enumerate(SIDES):
                lines.append(f"{k}/terrains_peering_bit/{side} = {-1 if i >> b & 1 else 0}")
            lines.append(f"{k}/physics_layer_0/polygon_0/points = {full}")
        else:
            lines += [f"{k}/physics_layer_0/polygon_0/points = {thin}", f"{k}/physics_layer_0/polygon_0/one_way = true"]
    lines += ["", "[resource]", f"tile_size = Vector2i({T}, {T})", "physics_layer_0/collision_layer = 1",
              "physics_layer_0/collision_mask = 1", "terrain_set_0/mode = 2",
              f"terrain_set_0/terrain_0/name = {godot.q('platform')}", "terrain_set_0/terrain_0/color = Color(0.4, 0.7, 0.3, 1)",
              'sources/0 = SubResource("TileSetAtlasSource_1")',
              "metadata/dotwork_sides = PackedInt32Array(0)"]   # verify paints it and checks the four sides
    return godot._write(path, "\n".join(lines) + "\n")


def mask_at(rows, x, y):
    """Exposure mask of a solid cell in an ASCII level: '#' platform, '=' one-way, anything else air."""
    def solid(xx, yy):
        return 0 <= yy < len(rows) and 0 <= xx < len(rows[yy]) and rows[yy][xx] == "#"
    return sum(1 << b for b, (dx, dy) in enumerate(((0, -1), (1, 0), (0, 1), (-1, 0))) if not solid(x + dx, y + dy))


def preview(tiles, T, out, bg=None):
    """The set in use: a small level from LEVEL, over the background when there is one."""
    W, H = len(LEVEL[0]) * T, len(LEVEL) * T
    can = Image.new("RGBA", (W, H), (110, 150, 200, 255))
    if bg is not None:
        b = bg.resize((W, round(bg.height * W / bg.width)), Image.NEAREST)
        can.alpha_composite(b, (0, H - b.height))
    for y, row in enumerate(LEVEL):
        for x, ch in enumerate(row):
            if ch == "#":
                can.alpha_composite(Image.fromarray(tiles[mask_at(LEVEL, x, y)]), (x * T, y * T))
            elif ch == "=":
                left = x == 0 or row[x - 1] != "="
                right = x == len(row) - 1 or row[x + 1] != "="
                can.alpha_composite(Image.fromarray(tiles[16 if left else 18 if right else 17]), (x * T, y * T))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    can.resize((W * 2, H * 2), Image.NEAREST).save(out)
    return out


def background(e, conf, work, name):
    """A wide side-view backdrop, made seamless left to right: rendered, rolled by half, the seam band
    repainted, tone-matched row by row and faded in."""
    b = e["background"]
    seed = int(b.get("seed", core.seed_of(e, 8800)))
    W, H = 320, 180
    prompt = core.prompt(BG_TPL, conf, s=b["prompt"])
    key = core.key(prompt, seed, core.palette_key(conf["fixed"]["env_palette"]))
    out = os.path.join(work, f"{name}_bg_{key}.png")
    if os.path.exists(out):
        return Image.open(out).convert("RGBA")
    core.ensure_comfy()
    raw, _ = lib.run(lib.klein(prompt, seed, W * 8, H * 8, f"dotwork_work/platforms/{name}_bg", lora=0.7))
    rgb = np.array(Image.open(raw).convert("RGB").resize((W, H), Image.BOX))
    rolled = np.roll(rgb, W // 2, axis=1)
    band = W // 10
    mask = np.zeros((H, W), np.uint8)
    mask[:, W // 2 - band:W // 2 + band] = 255
    fn = lib.put(Image.fromarray(rolled).resize((W * 8, H * 8), Image.NEAREST), f"dotwork_pbg_{name}.png")
    mf = lib.put(Image.fromarray(mask).resize((W * 8, H * 8), Image.NEAREST), f"dotwork_pbgm_{name}.png")
    rep, _ = lib.run(lib.klein(prompt, seed + 1, W * 8, H * 8, f"dotwork_work/platforms/{name}_bgseam", init_fn=fn,
                               denoise=0.75, lora=0.7, mask_fn=mf))
    fixed = np.array(Image.open(rep).convert("RGB").resize((W, H), Image.BOX)).astype(np.float32)
    # each row of the repaint shifted to the tone of what it replaces: its sky came out a shade darker, and the palette
    # pass turned that fade into a hard step (2026-10-30)
    cols = slice(W // 2 - band, W // 2 + band)
    fixed += rolled[:, cols].mean(1, keepdims=True) - fixed[:, cols].mean(1, keepdims=True)
    # the repaint fades in toward the seam (all of it only at the middle column), so neither band edge shows a new
    # seam: pasted whole, the band's hills and sky stopped short at both of its edges (2026-10-30, the meadow sample)
    w = np.clip((band - np.abs(np.arange(W) + 0.5 - W / 2)) / band, 0, 1)[None, :, None]
    fixed = np.clip(np.rint(rolled * (1 - w) + fixed * w), 0, 255).astype(np.uint8)   # outside the band: the wrap columns stay exact
    arr = lib.finish(np.dstack([fixed, np.full((H, W), 255, np.uint8)]), palette=conf["fixed"]["env_palette"],
                     outline="", max_colors=48)
    im = Image.fromarray(arr)
    im.save(out)
    return im


def run(entries, pack, man, conf):
    T0 = int(conf["design"]["tile_px"])
    for e in entries:
        name = core.snake(e["name"])
        T = int(e.get("tile", T0))
        lip = float(e.get("lip", 0.35))
        work = core.work("platforms")
        art = core.art(conf, "tiles", "platforms", name)
        res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/tiles/platforms/{name}'
        pal = conf["fixed"]["env_palette"]
        fn, fp, fs, ft = _mat(e, "fill", e.get("fill"))
        sn, sp, ss, st = _mat(e, "surface", e.get("surface"))
        fill = texture(fn, fp, T, pal, core.work("ground"), fs, 1, ft)[0]
        surf = texture(sn, sp, T, pal, core.work("ground"), ss, 1, st)[0]
        at, tiles = atlas(fill, surf, T, lip, core.seed_of(e, 8700))
        man.drop_dir(art)
        ap = core.save_clean(Image.fromarray(at), os.path.join(art, f"platforms_{name}_atlas.png"))
        man.add(ap, "tileset_atlas", tile=T, tiles=16, one_way=3, layout="index = exposure mask N1 E2 S4 W8; 16-18 "
                "one-way left / mid / right", workflow="Dotwork platforms (ground textures, composed in code)",
                routes=("klein",))
        ts = tileset(os.path.join(art, f"platforms_{name}_tileset.tres"), f"{res}/platforms_{name}_atlas.png", T, 8)
        man.add(ts, "tileset", terrain_mode="match_sides", collision="full; one-way caps")
        bg = None
        if e.get("background"):
            bg = background(e, conf, work, name)
            bp = core.save_clean(bg, os.path.join(art, f"platforms_{name}_bg.png"))
            man.add(bp, "background", size=list(bg.size), routes=("klein",), seamless="horizontal")
            scn = godot._write(os.path.join(art, f"parallax_{name}.tscn"), "\n".join([
                "[gd_scene load_steps=2 format=3]", "",
                f'[ext_resource type="Texture2D" path="{res}/platforms_{name}_bg.png" id="1_bg"]', "",
                f'[node name="Parallax{name.title().replace("_", "")}" type="ParallaxBackground"]', "",
                '[node name="Far" type="ParallaxLayer" parent="."]', "motion_scale = Vector2(0.3, 0.3)",
                f"motion_mirroring = Vector2({bg.width}, 0)", "",
                '[node name="Sprite2D" type="Sprite2D" parent="Far"]', "texture_filter = 1",
                'texture = ExtResource("1_bg")', "centered = false", ""]))
            man.add(scn, "scene", node="ParallaxBackground > ParallaxLayer > Sprite2D")
        pv = preview(tiles, T, core.src(conf, "art", "tiles", f"platforms_{name}_preview.png"), bg)
        core.log(f"platforms {name}: {T} px, 16 + 3 tiles{', background' if bg is not None else ''}; preview {pv}")
