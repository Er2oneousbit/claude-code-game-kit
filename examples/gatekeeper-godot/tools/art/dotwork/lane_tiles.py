#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_tiles.py
# Purpose : two-terrain corner autotiles (wang16, 8x4 dual-centre atlas) + a Godot TileSet, from two seamless
#           textures. Prefer the layered ground (lane_ground) for new maps.
# Usage   : pack spec "tiles": [{"name": "grass_cobble", "a": {"name": "grass", "prompt": "..."}, "b": {"name":
#           "cobble", "prompt": "..."}}]
# Notes   : Godot corner mode puts the visible edge half a tile inside the painted cells; the blob overlays do not.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import numpy as np
from PIL import Image

import fcore as core
import godot

import engine as lib  # noqa: E402
import autotile  # noqa: E402  (corner coverage for the pair lane)

KTEX_TPL = ("pixel art sprite, top-down view straight from above of {s}, a flat ground texture that fills the entire "
            "image edge to edge, {style} top-down {genre} style, clean readable clusters, simple shading, "
            "limited palette, no objects, no characters, no border, no perspective")


def seamless(name, prompt, N, palette, work, seed=800):
    """N px seamless tile. 32 px renders at 512 on a 16 px grid; 64+ at 1024 / N."""
    p = os.path.join(work, f"{name}_{core.key(prompt, seed, core.palette_key(palette))}_{N}.png")
    if os.path.exists(p):
        return np.array(Image.open(p).convert("RGB"))
    core.ensure_comfy()
    S = 1024 // N if N >= 64 else 512 // N
    R = N * S
    band = max(2, N * 12 // 128)
    m = np.zeros((N, N), np.uint8)
    m[:, N // 2 - band:N // 2 + band] = 255
    m[N // 2 - band:N // 2 + band, :] = 255
    mf = f"dotwork_cross_{N}.png"
    mf = lib.put(Image.fromarray(m).resize((R, R), Image.NEAREST), mf)
    pr = core.prompt(KTEX_TPL, s=prompt)
    raw, _ = lib.run(lib.klein(pr, seed, R, R, f"dotwork_work/tiles/{name}_raw", lora=0.6))
    fn = f"dotwork_t_{name}_{N}.png"
    fn = lib.put(Image.open(raw).convert("RGB").resize((N, N), Image.BOX).resize((R, R), Image.NEAREST), fn)
    r1, _ = lib.run(lib.klein(pr, seed + 1, R, R, f"dotwork_work/tiles/{name}_ref", init_fn=fn, denoise=0.4, lora=0.6))
    rgb = np.array(Image.open(r1).convert("RGB"))
    tile = lib.sample(rgb, np.ones(rgb.shape[:2], bool), S, 0, S, 0, 0.5)[:N, :N, :3]
    rolled = np.roll(tile, (N // 2, N // 2), (0, 1))
    fn2 = f"dotwork_t_roll_{name}_{N}.png"
    fn2 = lib.put(Image.fromarray(rolled).resize((R, R), Image.NEAREST), fn2)
    r2, _ = lib.run(lib.klein(pr, seed + 2, R, R, f"dotwork_work/tiles/{name}_seam", init_fn=fn2, denoise=0.7,
                              lora=0.6, mask_fn=mf))
    rgb2 = np.array(Image.open(r2).convert("RGB"))
    fixed = lib.sample(rgb2, np.ones(rgb2.shape[:2], bool), S, 0, S, 0, 0.5)[:N, :N, :3]
    ring = np.ones((N, N), bool)
    ring[N // 8:N - N // 8, N // 8:N - N // 8] = False
    fixed[ring] = rolled[ring]
    arr = lib.finish(np.dstack([fixed, np.full((N, N), 255, np.uint8)]), palette=palette, outline="",
                     max_colors=24 if N >= 64 else 14)
    os.makedirs(work, exist_ok=True)
    Image.fromarray(arr).convert("RGB").save(p)
    core.log(f"tile texture {name} {N}px done")
    return np.array(Image.open(p).convert("RGB"))


def wrap_error(t):
    """Mean color step across the wrap seams vs inside: ~1.0 means the seam is no harsher than the interior."""
    t = t.astype(np.float32)
    inner = (np.abs(np.diff(t, axis=0)).mean() + np.abs(np.diff(t, axis=1)).mean()) / 2
    seam = (np.abs(t[0] - t[-1]).mean() + np.abs(t[:, 0] - t[:, -1]).mean()) / 2
    return float(seam / max(inner, 1e-6))


def tile_rows(names, surf):
    """Tile rows for godot.tileset on the 8x4 atlas (see run): wang index b at (b % 4, b // 4) with center 'b'
    unless all corners are 'a', and again at (4 + b % 4, b // 4) with center 'a' unless all corners are 'b'."""
    rows = []
    for copy in (0, 1):
        for b in range(16):
            bits = [(b >> 0) & 1, (b >> 1) & 1, (b >> 2) & 1, (b >> 3) & 1]  # NW, NE, SW, SE ; 1 = terrain a
            corners = tuple(0 if x else 1 for x in bits)                     # terrain id 0 = a, 1 = b
            n_a = sum(bits)
            center = (0 if n_a == 4 else 1) if copy == 0 else (1 if n_a == 0 else 0)
            idx = (b // 4) * 8 + (b % 4) + 4 * copy
            rows.append({"index": idx, "corners": corners, "terrain": center,
                         "custom": surf.get(names[0 if n_a >= 2 else 1])})
    return rows


def run(entries, pack, man, conf):
    T = conf["design"]["tile_px"]
    pal = conf["fixed"]["env_palette"]
    work = os.path.join(core.WORK, "tiles")
    art = core.art(conf, "tiles")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/tiles'
    for e in entries:
        name = core.snake(e["name"])
        A = seamless(e["a"]["name"], e["a"]["prompt"], T, pal, work, int(e["a"].get("seed", 800)))
        B = seamless(e["b"]["name"], e["b"]["prompt"], T, pal, work, int(e["b"].get("seed", 810)))
        out = os.path.join(art, name)
        for t, arr in ((e["a"]["name"], A), (e["b"]["name"], B)):
            p = core.save_clean(Image.fromarray(arr), os.path.join(out, f"spr_tile_{core.snake(t)}.png"))
            man.add(p, "tile_texture", prompt=e["a"]["prompt"] if t == e["a"]["name"] else e["b"]["prompt"],
                    workflow="Dotwork tile lane (klein + half-shift seam inpaint)", routes=("klein",),
                    size=[T, T], seamless=True, wrap_ratio=round(wrap_error(arr), 2))
        tiles = [autotile.build_tile(b, A, B, T, 2.0, 2, 3, 7 + b, autotile.edge_colors(A, B)) for b in range(16)]
        # 8x4 atlas: columns 0-3 = the 16 wang tiles with center terrain 'b' unless all four corners are 'a';
        # columns 4-7 = the same pixels with center 'a' unless all corners are 'b'. Godot's corner solver needs a
        # tile whose CENTER matches the painted terrain; with one copy, narrow shapes (single cells, 1-wide
        # lines, diagonals) of one terrain mismatched (tested 2026-10-29); with both copies every shape is clean.
        sheet = autotile.sheet(tiles, T)
        atlas = core.save_clean(Image.fromarray(np.concatenate([sheet, sheet], axis=1)),
                                os.path.join(out, f"tiles_{name}.png"))
        names = [e["a"]["name"], e["b"]["name"]]
        surf = e.get("surface", {})
        rows = tile_rows(names, surf)
        cols = [(int(c[0]), int(c[1]), int(c[2])) for c in (np.median(A.reshape(-1, 3), 0),
                                                           np.median(B.reshape(-1, 3), 0))]
        ts = godot.tileset(os.path.join(out, f"{name}_tileset.tres"), f"{res}/{name}/tiles_{name}.png", T, 8, rows,
                           list(zip(names, cols)), conf["design"]["terrain_mode"],
                           custom="surface" if surf else None)
        man.add(atlas, "tile_atlas", routes=("klein",), tile_px=T, layout="8x4: two copies of the wang16 4x4 block (index = "
                "NW*1+NE*2+SW*4+SE*8, 1 = a); left copy center b, right copy center a",
                terrains=names)
        man.add(ts, "tileset", tile_px=T, terrain_mode=conf["design"]["terrain_mode"], terrains=names,
                custom_data="surface" if surf else None)
        demo = autotile.demo(tiles, T, 20, 12, 7)
        dp = core.src(conf, "art", "tiles", name, f"{name}_demo.png")
        core.save_clean(Image.fromarray(demo), dp)
        core.log(f"tiles {name}: atlas + TileSet ({names[0]} over {names[1]})")
