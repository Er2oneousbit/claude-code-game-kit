#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_iso.py
# Purpose : isometric (2:1) terrain: floor diamonds and raised blocks made from the ground lane's seamless material
#           textures by an exact projection, so neighbouring diamonds continue each other's texture; an isometric Godot
#           TileSet (floors and blocks as two atlas sources, blocks taller with a texture origin) and a preview.
# Usage   : pack spec "iso": [{"name": "village", "floors": [{"material": "grass_lush", "variants": 3},
#           {"material": "cobble"}], "blocks": [{"name": "wall", "top": {"material": "cobble"},
#           "side": {"material": "brick_red"}, "height": 16}]}]
#           tile: diamond width in px (default 2 x design.tile_px: 64 x 32); floors / blocks: catalog materials or
#           {"prompt": ...}; variants per floor (default 1); height per block in px (default tile / 4).
# Notes   : Floors and blocks are tiles to place; terrain transitions between iso materials are not generated (paint
#           edges by hand, or lay a block row along them). Single iso objects stay in the props lane (template "iso").
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import numpy as np
from PIL import Image

import fcore as core
import godot
from lane_ground import _from_catalog, texture

OUTLINE = np.array([5, 4, 7], np.uint8)


def _mat(e, key, who):
    m = e.get(key) if key else e
    if not m:
        raise core.ToolError(f"iso {who}: \"{key}\" needs {{\"material\": ...}} or {{\"prompt\": ...}}")
    m = _from_catalog(dict(m, name=m.get("material") or m.get("name") or f"{who}_{key}"))
    return m["name"], m["prompt"], int(m.get("seed", 800)), m.get("tpl", "ground")


def project(tex, W):
    """A seamless top-down texture (N x N, N = W / 2) as a 2:1 floor diamond W x W/2. Screen pixel (sx, sy) shows world
    point tx = sy + (sx - N) / 2, ty = sy - (sx - N) / 2 (pixel centres), sampled with wrap-around, so the diamond
    next door continues the same texture."""
    N = W // 2
    H = W // 2
    sy, sx = np.mgrid[0:H, 0:W].astype(np.float64) + 0.5
    tx = sy + (sx - N) / 2
    ty = sy - (sx - N) / 2
    inside = (tx >= 0) & (tx < N) & (ty >= 0) & (ty < N)
    out = np.zeros((H, W, 4), np.uint8)
    xi, yi = np.floor(tx).astype(int) % tex.shape[1], np.floor(ty).astype(int) % tex.shape[0]
    out[..., :3] = tex[yi, xi]
    out[..., 3] = np.where(inside, 255, 0)
    return out


def block(top, side, W, h):
    """A raised block: the top diamond lifted by h, two side faces from the side texture (left 75 %, right 55 %
    brightness), an outline round the silhouette and along the front edges."""
    H = W // 2
    can = np.zeros((H + h, W, 4), np.uint8)
    N = W // 2
    st = side.shape[0]
    for x in range(W):
        y_edge = H // 2 + (x if x < N else W - 1 - x) // 2   # the top diamond's lower edge at this column
        for y in range(y_edge, y_edge + h + 1):
            if 0 <= y < H + h:
                sx = (x % st)
                sy = ((y - y_edge) * st // max(1, h)) % st
                k = 0.75 if x < N else 0.55
                can[y, x, :3] = (side[sy, sx].astype(np.float32) * k).astype(np.uint8)
                can[y, x, 3] = 255
    t = project(top, W)
    m = t[..., 3] == 255
    can[:H][m] = t[m]
    op = can[..., 3] == 255
    ring = op & ~(np.roll(op, 1, 0) & np.roll(op, -1, 0) & np.roll(op, 1, 1) & np.roll(op, -1, 1))
    can[ring, :3] = OUTLINE
    for x in range(W):   # the front vertical edge and the top's front corners
        if x in (N - 1, N):
            ys = np.nonzero(op[:, x])[0]
            if len(ys):
                can[H - 1:ys.max() + 1, x, :3] = OUTLINE
    return can


def _atlas(tiles):
    w, h = tiles[0].shape[1], tiles[0].shape[0]
    at = np.zeros((h, w * len(tiles), 4), np.uint8)
    for i, t in enumerate(tiles):
        at[:, i * w:(i + 1) * w] = t
    return at


def tileset(path, floors_res, n_floor, blocks_res, n_block, W, bh):
    """Isometric TileSet: source 0 the floor diamonds (W x W/2), source 1 the blocks (W x W/2 + bh, the texture origin
    lifted so the block's base sits on its cell)."""
    H = W // 2
    n_src = 1 + bool(n_block)
    lines = [f'[gd_resource type="TileSet" load_steps={2 * n_src + 1} format=3]', "",
             f'[ext_resource type="Texture2D" path="{floors_res}" id="1_floor"]']
    if n_block:
        lines.append(f'[ext_resource type="Texture2D" path="{blocks_res}" id="2_block"]')
    lines += ["", '[sub_resource type="TileSetAtlasSource" id="TileSetAtlasSource_1"]', 'texture = ExtResource("1_floor")',
              f"texture_region_size = Vector2i({W}, {H})"]
    lines += [f"{i}:0/0 = 0" for i in range(n_floor)]
    if n_block:
        lines += ["", '[sub_resource type="TileSetAtlasSource" id="TileSetAtlasSource_2"]',
                  'texture = ExtResource("2_block")', f"texture_region_size = Vector2i({W}, {H + bh})"]
        for i in range(n_block):
            lines += [f"{i}:0/0 = 0", f"{i}:0/0/texture_origin = Vector2i(0, {bh // 2})"]
    lines += ["", "[resource]", "tile_shape = 1", "tile_layout = 5", f"tile_size = Vector2i({W}, {H})",
              'sources/0 = SubResource("TileSetAtlasSource_1")']
    if n_block:
        lines.append('sources/1 = SubResource("TileSetAtlasSource_2")')
    return godot._write(path, "\n".join(lines) + "\n")


def preview(floors, blocks, W, out):
    """A 6 x 6 iso patch: floors in stripes, a wall of blocks across the back."""
    H = W // 2
    bh = blocks[0].shape[0] - H if blocks else 0
    n = 6
    can = Image.new("RGBA", (W * n + W, H * n + H + bh + 8), (58, 58, 68, 255))
    ox, oy = W * n // 2, bh + 4
    for gy in range(n):
        for gx in range(n):
            sx, sy = ox + (gx - gy) * W // 2, oy + (gx + gy) * H // 2
            f = floors[(gx // 2 + gy) % len(floors)]
            can.alpha_composite(Image.fromarray(f), (sx, sy))
    for gx in range(n) if blocks else []:
        sx, sy = ox + (gx - 0) * W // 2, oy + gx * H // 2
        can.alpha_composite(Image.fromarray(blocks[gx % len(blocks)]), (sx, sy - bh))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    can.resize((can.width * 2, can.height * 2), Image.NEAREST).save(out)
    return out


def run(entries, pack, man, conf):
    T = int(conf["design"]["tile_px"])
    pal = conf["fixed"]["env_palette"]
    gw = core.work("ground")
    for e in entries:
        name = core.snake(e["name"])
        W = int(e.get("tile", 2 * T))
        if W % 4 or not 16 <= W <= 256:
            raise core.ToolError(f"iso {name}: tile {W} px: a multiple of 4 between 16 and 256 (the diamond width)")
        N = W // 2
        floors, labels = [], []
        for f in e.get("floors") or []:
            fn, fp, fs, ft = _mat(f, None, name)
            for k, t in enumerate(texture(fn, fp, N, pal, gw, fs, int(f.get("variants", 1)), ft)):
                floors.append(project(t, W))
                labels.append(f"{fn}_{k}")
        blocks = []
        for b in e.get("blocks") or []:
            bname = core.snake(b.get("name", "block"))
            tn, tp, ts, tt = _mat(b, "top", bname)
            sn, sp, ss, st = _mat(b, "side", bname)
            top = texture(tn, tp, N, pal, gw, ts, 1, tt)[0]
            side = texture(sn, sp, N, pal, gw, ss, 1, st)[0]
            blocks.append(block(top, side, W, int(b.get("height", W // 4))))
        if not floors:
            raise core.ToolError(f"iso {name}: at least one floor material")
        if len({bl.shape for bl in blocks}) > 1:
            raise core.ToolError(f"iso {name}: every block in one set shares one height (make another iso entry)")
        art = core.art(conf, "tiles", "iso", name)
        res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/tiles/iso/{name}'
        man.drop_dir(art)
        fp_ = core.save_clean(Image.fromarray(_atlas(floors)), os.path.join(art, f"iso_{name}_floors.png"))
        man.add(fp_, "tileset_atlas", tile=[W, W // 2], tiles=labels, routes=("klein",), projection="2:1 isometric",
                workflow="Dotwork iso (ground textures, projected in code)")
        bh = blocks[0].shape[0] - W // 2 if blocks else 0
        if blocks:
            bp = core.save_clean(Image.fromarray(_atlas(blocks)), os.path.join(art, f"iso_{name}_blocks.png"))
            man.add(bp, "tileset_atlas", tile=[W, W // 2 + bh], tiles=len(blocks), routes=("klein",),
                    origin_lift=bh // 2, workflow="Dotwork iso (ground textures, projected in code)")
        ts_ = tileset(os.path.join(art, f"iso_{name}_tileset.tres"), f"{res}/iso_{name}_floors.png", len(floors),
                      f"{res}/iso_{name}_blocks.png", len(blocks), W, bh)
        man.add(ts_, "tileset", tile_shape="isometric", tile_size=[W, W // 2])
        pv = preview(floors, blocks, W, core.src(conf, "art", "tiles", f"iso_{name}_preview.png"))
        core.log(f"iso {name}: {len(floors)} floors, {len(blocks)} blocks, {W}x{W // 2}; preview {pv}")
