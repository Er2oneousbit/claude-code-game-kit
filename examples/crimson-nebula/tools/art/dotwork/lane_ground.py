#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_ground.py
# Purpose : layered ground for top-down maps: base textures with seamless variants, overlay terrains as 47-tile blob
#           sets (organic, roof, facade, wallface, walltop, cliff styles; connectors; animated water), decals,
#           fixtures (doors, windows, furniture); one Godot TileSet for every ground layer; optional maps
#           (mapbuild).
# Usage   : pack spec "ground": {"name": "town", "base": [{"material": "grass_lush"}], "overlays": [{"material":
#           "cobble", "relief": "raised"}], "fixtures": [...], "map": {...}}
# Notes   : Textures render at native pixel scale (1024 px on an 8 px grid); seams and variants are repainted with the tile
#           repeated 4x4 on one canvas, variants share the outer ring. Blob tiles are computed on a 3x3 canvas and cropped,
#           so neighbours agree exactly. Overlay keys: relief, style, solid, surface, variants, tint, animate.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import numpy as np
from PIL import Image

import connectors
import fcore as core
import godot
from lane_props import fit_sprite
import qa
from lane_tiles import KTEX_TPL, wrap_error

import engine as lib  # noqa: E402

DECAL_TPL = ("pixel art sprite, top-down view from above, a small {s} lying on the ground, single small object, "
             "centered, {style} top-down {genre} style, crisp pixels, simple shading")
SHADOW_A = 90  # drop/inner shadow alpha (0-255) over whatever layer is below
FIXTURE_TOP_TPL = ("pixel art sprite, high three-quarter top-down view of {s}, furniture or object for a {style} "
                   "{genre} interior, drawn in the exact pixel art style, palette, outline and shading of "
                   "image 1, {setting}, crisp dark outline, centered")
FIXTURE_FLAT_TPL = ("pixel art sprite, seen from directly above, a flat axis-aligned {s} lying on the floor, square to "
                    "the image edges, no perspective, {style} {genre} interior, drawn in the exact pixel "
                    "art style, palette and shading of image 1, crisp dark outline, centered")
FIXTURE_TPL = ("pixel art sprite, straight-on front view of {s}, a building part for a {style} {genre} "
               "town, drawn in the exact pixel art style, palette, outline and shading of image 1, {setting}, crisp "
               "dark outline, centered")


GRID = 8      # render pixel scale: 1024 px render on an 8 px grid = 128 real pixels (a 4x4 block of 32 px tiles)
CANVAS = 1024
MARGIN = 8    # klein paints a frame around texture renders: crop this many real pixels on every side


def _sample(path):
    rgb = np.array(Image.open(path).convert("RGB"))
    n = CANVAS // GRID
    return lib.sample(rgb, np.ones(rgb.shape[:2], bool), GRID, 0, GRID, 0, 0.5)[:n, :n, :3]


def _ctx_inpaint(tile, keep, prompt, seed, tag, denoise, tpl="ground"):
    """Repaint the ~keep pixels of `tile` with the tile repeated 4x4 on one canvas (so klein sees real neighbours at
    native pixel scale). Returns 16 candidate tiles; ~keep pixels are restored exactly in every candidate."""
    N = tile.shape[0]
    reps = (CANVAS // GRID) // N
    ctx = np.tile(tile, (reps, reps, 1))
    m = np.tile(np.where(keep, 0, 255).astype(np.uint8), (reps, reps))
    fn, mf = f"dotwork_g_{tag}.png", f"dotwork_gm_{tag}.png"
    fn = lib.put(Image.fromarray(ctx).resize((CANVAS, CANVAS), Image.NEAREST), fn)
    mf = lib.put(Image.fromarray(m).resize((CANVAS, CANVAS), Image.NEAREST), mf)
    out, _ = lib.run(lib.klein(core.prompt(TPL[tpl], s=prompt), seed, CANVAS, CANVAS, f"dotwork_work/ground/{tag}",
                               init_fn=fn, denoise=denoise, lora=0.6, mask_fn=mf))
    big = _sample(out)
    cands = []
    for ty in range(reps):
        for tx in range(reps):
            c = big[ty * N:(ty + 1) * N, tx * N:(tx + 1) * N].copy()
            c[keep] = tile[keep]
            cands.append(c)
    return cands


TPL = {"ground": KTEX_TPL,
       "facade": ("pixel art sprite, straight-on front view of {s}, a flat wall texture that fills the entire image "
                  "edge to edge, {style} {genre} town style, clean readable clusters, simple shading, "
                  "limited palette, no windows, no doors, no border, no perspective"),
       "roof": ("pixel art sprite, view from above of a roof covered in {s}, a flat roof texture that fills the "
                "entire image edge to edge, {style} {genre} town style, clean readable clusters, "
                "simple shading, limited palette, no chimneys, no border, no perspective")}


def render_raw(name, prompt, work, seed=800, tpl="ground"):
    """The material's native-scale 128 px render, unpaletted (cached). Also feeds the palette extension."""
    raw_p = os.path.join(work, f"{name}_{core.key(core.prompt(TPL[tpl], s=prompt), seed, tpl)}_raw128.png")
    if not os.path.exists(raw_p):
        core.ensure_comfy()
        out, _ = lib.run(lib.klein(core.prompt(TPL[tpl], s=prompt), seed, CANVAS, CANVAS, f"dotwork_work/ground/{name}_raw",
                                   lora=0.6))
        os.makedirs(work, exist_ok=True)
        Image.fromarray(_sample(out)).save(raw_p)
    return np.array(Image.open(raw_p).convert("RGB"))


def _stats(a):
    f = a.reshape(-1, 3).astype(np.float32)
    return np.concatenate([f.mean(0), f.std(0)])


def texture(name, prompt, N, palette, work, seed=800, variants=1, tpl="ground"):
    """Seamless N px tile + (variants - 1) interior variants, all at native pixel scale. Cached in work/.
    1. txt2img 1024 on the 8 px grid -> 128 px texture; crop the frame; pick the most typical N px window
    2. roll it by N/2 (the outer ring now wraps by construction); repaint the centre cross in a 4x4 context
    3. variants: repaint everything inside the N/8 ring in a 4x4 context; the ring is shared, so any variant
       borders any other without a seam. Palette snap happens once on the base, variants restore the ring after."""
    if variants > 11:   # the base plus the 10 best candidates; asking for more emptied the pool and crashed
        core.log(f"ground texture {name}: {variants} variants asked, 11 is the most a texture gives")
        variants = 11
    tag = core.key(prompt, seed, tpl, core.palette_key(palette))
    paths = [os.path.join(work, f"{name}_{tag}_{N}.png")] + [os.path.join(work, f"{name}_{tag}_{N}_v{k}.png")
                                                             for k in range(1, variants)]
    if all(os.path.exists(p) for p in paths):
        return [np.array(Image.open(p).convert("RGB")) for p in paths]
    core.ensure_comfy()
    raw = render_raw(name, prompt, work, seed, tpl)[MARGIN:-MARGIN, MARGIN:-MARGIN]
    target = _stats(raw)
    best = None
    for y in range(0, raw.shape[0] - N + 1, 4):
        for x in range(0, raw.shape[1] - N + 1, 4):
            d = float(np.abs(_stats(raw[y:y + N, x:x + N]) - target).sum())
            if best is None or d < best[0]:
                best = (d, raw[y:y + N, x:x + N])
    rolled = np.roll(best[1], (N // 2, N // 2), (0, 1))
    band = max(2, N * 12 // 128)
    keep = np.ones((N, N), bool)
    keep[:, N // 2 - band:N // 2 + band] = False
    keep[N // 2 - band:N // 2 + band, :] = False
    cands = _ctx_inpaint(rolled, keep, prompt, seed + 1, f"{name}_seam", 0.7, tpl)
    # most typical candidate: the repainted cross should look like the rest of the texture
    base = min(cands, key=lambda c: float(np.abs(_stats(c[~keep]) - _stats(c[keep])).sum()))
    base = lib.finish(np.dstack([base, np.full((N, N), 255, np.uint8)]), palette=palette, outline="",
                      max_colors=24 if N >= 64 else 16)[..., :3]
    Image.fromarray(base).save(paths[0])
    out = [base]
    if variants > 1:
        ring = np.ones((N, N), bool)
        ring[N // 8:N - N // 8, N // 8:N - N // 8] = False
        vc = _ctx_inpaint(base, ring, prompt, seed + 2, f"{name}_var", 0.6, tpl)
        snapped = []
        for c in vc:
            s = lib.finish(np.dstack([c, np.full((N, N), 255, np.uint8)]), palette=palette, outline="",
                           max_colors=24 if N >= 64 else 16)[..., :3]
            s[ring] = base[ring]
            snapped.append(s)
        # keep candidates whose look matches the base, then greedily take the most distinct ones
        tb = _stats(base)
        pool = sorted(snapped, key=lambda c: float(np.abs(_stats(c) - tb).sum()))[:10]
        chosen = []
        for _ in range(variants - 1):
            pick = max(pool, key=lambda c: min(float(np.abs(c.astype(int) - o.astype(int)).mean())
                                               for o in [base] + chosen))
            chosen.append(pick)
            pool = [c for c in pool if c is not pick]
        for p, c in zip(paths[1:], chosen):
            Image.fromarray(c).save(p)
        out += chosen
    core.log(f"ground texture {name}: {N}px + {variants - 1} variants")
    return out


# 47-tile blob (Godot "Match Corners and Sides"). Bit order N, NE, E, SE, S, SW, W, NW; (dx, dy) per bit.
NB8 = [(0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1)]
PEERS = ("top_side", "top_right_corner", "right_side", "bottom_right_corner", "bottom_side", "bottom_left_corner",
         "left_side", "top_left_corner")


def canon(m):
    """A corner bit only counts when both sides next to it are set (Godot picks tiles by these 47 masks)."""
    for c in (1, 3, 5, 7):
        if not ((m >> ((c + 7) % 8)) & 1 and (m >> ((c + 1) % 8)) & 1):
            m &= ~(1 << c)
    return m


BLOB = sorted({canon(m) for m in range(256)})  # the 47 masks; 255 = full tile


def _wobble(T, seed, amp):
    """T-periodic noise on the 3x3 canvas: equal at x and x + T, so every tile of a terrain agrees at its seams."""
    rng = np.random.default_rng(seed)
    v = (np.arange(-T, 2 * T) + 0.5) / T
    yy, xx = np.meshgrid(v, v, indexing="ij")
    w = np.zeros_like(xx)
    for k in (1, 2, 3):
        a, b, c, d = rng.uniform(0, 2 * np.pi, 4)
        w += np.sin(2 * np.pi * k * xx + a) * np.cos(2 * np.pi * k * yy + b) / k
        w += np.sin(2 * np.pi * k * yy + c) * np.cos(2 * np.pi * k * xx + d) / k
    return w / np.abs(w).max() * amp


def _disk(r):
    return [(dy, dx) for dy in range(-r, r + 1) for dx in range(-r, r + 1) if dx * dx + dy * dy <= r * r]


def blob_canvas(m, T, band, rr, wob):
    """Coverage on the 3x3 canvas (3T x 3T) for canonical mask m: inset `band` px from unpainted neighbours
    (dropped corners count as unpainted), convex corners rounded by `rr`, edge wobble from `wob`."""
    painted = {(0, 0): True}
    for b, (dx, dy) in enumerate(NB8):
        painted[(dx, dy)] = bool((m >> b) & 1)
    ys, xs = np.mgrid[-T:2 * T, -T:2 * T] + 0.5
    d = np.full(xs.shape, 1e9)
    for (cx, cy), on in painted.items():
        if on:
            continue
        x0, x1, y0, y1 = cx * T, (cx + 1) * T, cy * T, (cy + 1) * T
        dd = np.hypot(np.maximum(0, np.maximum(x0 - xs, xs - x1)), np.maximum(0, np.maximum(y0 - ys, ys - y1)))
        d = np.minimum(d, dd)
    core_ = d >= band + rr + wob
    cov = np.zeros_like(core_)
    H = core_.shape[0]
    for dy, dx in _disk(rr):  # dilation by a disk: rounds the convex corners
        cov[max(0, dy):H + min(0, dy), max(0, dx):H + min(0, dx)] |= \
            core_[max(0, -dy):H + min(0, -dy), max(0, -dx):H + min(0, -dx)]
    return cov


def _sh(a, dy):
    """a shifted down by dy rows (dy < 0: up), zero fill (the canvas is big enough that the fill never shows)."""
    out = np.zeros_like(a)
    if dy > 0:
        out[dy:] = a[:-dy]
    elif dy < 0:
        out[:dy] = a[-dy:]
    else:
        out[:] = a
    return out


def blob_tile(m, A, T, relief, wob, band=None, rr=4, shadow=2):
    """RGBA tile for mask m: texture A inside the coverage, dark rim on its edge, relief shading. Everything is
    computed on the 3x3 canvas and cropped, so shading that crosses a tile seam matches on both sides."""
    band = band if band is not None else max(3, T * 5 // 32)
    cov = blob_canvas(m, T, band, rr, wob)
    tex = np.tile(A, (3, 3, 1))
    out = np.zeros(cov.shape + (4,), np.uint8)
    out[cov, :3] = tex[cov]
    out[cov, 3] = 255
    am = np.median(A.reshape(-1, 3), axis=0)
    inner = cov & _sh(cov, 1) & _sh(cov, -1) & np.roll(cov, 1, 1) & np.roll(cov, -1, 1)
    edge = cov & ~inner
    out[edge, :3] = (am * (0.75 if relief == "flat" else 0.5)).astype(np.uint8)
    if relief == "raised":
        hl = inner & ~(_sh(inner, 1))  # top row of the interior catches the light
        out[hl, :3] = np.minimum(255, am * 1.3).astype(np.uint8)
        sh = np.zeros_like(cov)
        for k in range(1, shadow + 1):
            sh |= _sh(cov, k)
        sh &= ~cov
        out[sh] = (0, 0, 0, SHADOW_A)
    elif relief == "sunken":
        ins = np.zeros_like(cov)
        for k in range(1, shadow + 2):
            ins |= cov & ~_sh(cov, k)  # just below the top bank: in shadow
        ins &= ~edge
        out[ins, :3] = (tex[ins].astype(np.float32) * 0.6).astype(np.uint8)
        hl = cov & ~_sh(cov, -1) & ~edge  # bottom bank catches light
        out[hl, :3] = np.minimum(255, tex[hl].astype(np.float32) * 1.2).astype(np.uint8)
    return out[T:2 * T, T:2 * T]


def _band(T, side, w):
    """Mask of the w px band along one side of a T x T tile (side: N, E, S, W)."""
    b = np.zeros((T, T), bool)
    if side == "N":
        b[:w] = True
    elif side == "S":
        b[T - w:] = True
    elif side == "W":
        b[:, :w] = True
    else:
        b[:, T - w:] = True
    return b


def structure_tile(m, A, T, style):
    """Blob tile for built things (no inset, no wobble): the texture fills the cell and every OPEN side (no painted
    neighbour) gets the trim of its direction, so one painted region reads as a roof, a facade or a wall top.
      roof:    S = front eave (fascia + lip), N = ridge cap, E/W = verge; inner corners = valley notch
      facade:  N = eave shadow under the roof, S = stone foundation, E/W = corner posts
      cliff:   (rock face under a plateau) top lit, base darker, N = lip shadow, S = rocky base, E/W = turned ends
      wallface: (interior north wall, front view) N = shadow under the wall top, S = baseboard
      walltop: (interior wall tops seen from above) every open side = lit edge + dark outline"""
    t = A.astype(np.float32).copy()
    am = np.median(A.reshape(-1, 3), axis=0).astype(np.float32)
    ink = np.minimum(am * 0.25, 40)  # outline: near-black tinted by the material
    open_ = {s: not ((m >> b) & 1) for s, b in (("N", 0), ("E", 2), ("S", 4), ("W", 6))}
    u = max(1, T // 32)  # trim unit: 1 px at 32 px tiles

    def paint(mask, rgb=None, mul=None):
        if mul is not None:
            t[mask] = t[mask] * mul
        else:
            t[mask] = rgb

    if style == "roof":
        # shingle band: every roof tile runs light (top) to dark (bottom), so middle rows read as a slope too
        t *= np.linspace(1.1, 0.88, T, dtype=np.float32)[:, None, None]
        # slope light: the ridge row is lighter, the eave row darker (a tile only knows its own row's open sides)
        if open_["N"]:
            t *= 1.12
        if open_["S"]:
            t *= 0.86
            paint(_band(T, "S", 9 * u) & ~_band(T, "S", 6 * u), mul=0.8)  # overhang shading above the fascia
        if open_["S"]:
            paint(_band(T, "S", 6 * u), mul=0.62)                       # fascia board
            paint(_band(T, "S", 6 * u) & ~_band(T, "S", 5 * u), rgb=np.minimum(255, am * 1.35))  # lit lip
            paint(_band(T, "S", 1 * u), rgb=ink)
        if open_["N"]:
            paint(_band(T, "N", 3 * u), rgb=np.minimum(255, am * 1.3))  # ridge cap
            paint(_band(T, "N", 1 * u), rgb=ink)
        for s in ("E", "W"):
            if open_[s]:
                paint(_band(T, s, 3 * u), mul=0.7)
                paint(_band(T, s, 1 * u), rgb=ink)
    elif style == "facade":
        if open_["N"]:
            paint(_band(T, "N", 5 * u), mul=0.55)                       # shadow under the eave
        if open_["S"]:
            paint(_band(T, "S", 5 * u), rgb=np.array([86, 82, 78], np.float32))  # stone foundation
            paint(_band(T, "S", 5 * u) & ~_band(T, "S", 4 * u), rgb=np.array([128, 122, 114], np.float32))
            paint(_band(T, "S", 1 * u), rgb=ink)
        for s in ("E", "W"):
            if open_[s]:
                paint(_band(T, s, 4 * u), mul=0.72)                     # corner post
                paint(_band(T, s, 1 * u), rgb=ink)
    elif style == "cliff":
        # natural rock face under a raised plateau: lit from above, darker toward the base, no masonry
        t *= np.linspace(1.12, 0.82, T, dtype=np.float32)[:, None, None] if open_["N"] and open_["S"] else (
            np.linspace(1.12, 0.97, T, dtype=np.float32)[:, None, None] if open_["N"] else
            np.linspace(0.97, 0.82, T, dtype=np.float32)[:, None, None] if open_["S"] else 1.0)
        if open_["N"]:
            paint(_band(T, "N", 3 * u), mul=0.5)                       # shadow under the plateau lip
        if open_["S"]:
            paint(_band(T, "S", 4 * u), mul=0.62)                      # rocky base in shadow
            paint(_band(T, "S", 1 * u), rgb=ink)
        for side in ("E", "W"):
            if open_[side]:
                paint(_band(T, side, 4 * u), mul=0.68)                 # the face turns away at its ends
                paint(_band(T, side, 1 * u), rgb=ink)
    elif style == "wallface":
        # interior north wall seen from the front: shadow under the wall top, wooden baseboard on the floor side
        if open_["N"]:
            paint(_band(T, "N", 4 * u), mul=0.55)
        if open_["S"]:
            paint(_band(T, "S", 5 * u), mul=0.5)                        # baseboard
            paint(_band(T, "S", 5 * u) & ~_band(T, "S", 4 * u), rgb=np.minimum(255, am * 1.25))
            paint(_band(T, "S", 1 * u), rgb=ink)
        for side in ("E", "W"):
            if open_[side]:
                paint(_band(T, side, 3 * u), mul=0.7)
    elif style == "walltop":
        t *= 0.45  # wall tops read as dark mass against the floor (classic 16-bit RPG interiors)
        for s in ("N", "E", "S", "W"):
            if open_[s]:
                paint(_band(T, s, 3 * u), rgb=np.minimum(255, am * 1.4))
                paint(_band(T, s, 1 * u), rgb=ink)
    # inner corners (both sides painted, the diagonal not): a small notch so L-shapes read as joined parts
    for c, (sa, sb) in ((1, ("N", "E")), (3, ("S", "E")), (5, ("S", "W")), (7, ("N", "W"))):
        if not open_[sa] and not open_[sb] and not ((m >> c) & 1):
            k = 3 * u
            ys = slice(0, k) if sa == "N" else slice(T - k, T)
            xs = slice(T - k, T) if sb == "E" else slice(0, k)
            t[ys, xs] = t[ys, xs] * 0.55
    return np.dstack([np.clip(t, 0, 255).astype(np.uint8), np.full((T, T), 255, np.uint8)])


def blob_atlas(A, T, relief, seed, variants=(), style="organic"):
    """12-column atlas: the 47 blob tiles drawn with the base texture (order = BLOB), then the 47 again for every
    texture variant. Godot picks among tiles with identical bits by probability, so long edges (paths, shores,
    cliff faces, eaves) stop repeating every tile. Seam-safe: coverage depends only on the mask and the
    per-terrain wobble, and every variant shares the base's outer ring."""
    wob = _wobble(T, seed, 3.0)  # organic edges; rr=4 + amp 3 = 0 seam px on random maps (rr=5: ~11 px)
    tiles = []
    for tex in [A] + list(variants):
        if style == "organic":
            tiles += [blob_tile(m, tex, T, relief, wob) for m in BLOB]
        else:
            tiles += [structure_tile(m, tex, T, style) for m in BLOB]
    rows = (len(tiles) + 11) // 12
    atlas = np.zeros((rows * T, 12 * T, 4), np.uint8)
    for i, t in enumerate(tiles):
        atlas[(i // 12) * T:(i // 12 + 1) * T, (i % 12) * T:(i % 12 + 1) * T] = t
    return atlas


def _solid_rects(m, T, band):
    """Collision for a blob tile: the 3x3 sub-rectangles (tile-centre coords) that the terrain covers."""
    h = T // 2
    if band == 0:
        return [(-h, -h, h, h)]
    g = [-h, -h + band, h - band, h]
    cell = {(0, 0): True}
    for b, (dx, dy) in enumerate(NB8):
        cell[(dx, dy)] = bool((m >> b) & 1)
    return [(g[cx + 1], g[cy + 1], g[cx + 2], g[cy + 2]) for (cx, cy), on in cell.items() if on]


def blob_rows(tid, T, surface=None, solid=False, n_variants=0, style="organic"):
    """Tile rows for godot.tileset_layers, matching blob_atlas: (1 + n_variants) sets of the 47 blob tiles, every
    tile center = terrain with 8 peering bits (terrain / -1); variant sets at probability 0.5.
    Probed 2026-10-29: painting any shape on an empty layer gives exactly the painted cells, each with the tile
    whose bits are its painted neighbours (single cells, rings, diagonals, 1-wide lines; both paint modes)."""
    band = max(3, T * 5 // 32) if style == "organic" else 0  # structures fill the whole cell
    rows = []
    for k in range(1 + n_variants):
        for j, m in enumerate(BLOB):
            i = k * len(BLOB) + j
            rows.append({"x": i % 12, "y": i // 12, "terrain": tid, "probability": 1.0 if k == 0 else 0.5,
                         "peers": tuple(tid if (m >> b) & 1 else -1 for b in range(8)),
                         "custom": surface, "solid_rects": _solid_rects(m, T, band) if solid else None})
    return rows


def _median_rgb(a):
    return tuple(int(c) for c in np.median(a.reshape(-1, 3), axis=0))


def _from_catalog(e):
    """{"material": "cobble", ...} -> prompt / seed / template from catalog/materials.json (spec keys win).
    Connector overlays ({"name": "fence", "style": "fence_wood"}) need no material."""
    if "material" not in e:
        return e
    import json
    cat = json.load(open(os.path.join(core.HERE, "catalog", "materials.json"), encoding="utf-8"))
    for tpl, group in cat.items():
        if not tpl.startswith("_") and e["material"] in group:
            return {"name": e["material"], "tpl": tpl, **group[e["material"]], **e}
    raise KeyError(f"material {e['material']} is not in catalog/materials.json")


def run(spec, pack, man, conf):
    spec = dict(spec, base=[_from_catalog(e) for e in spec.get("base", [])],
                overlays=[_from_catalog(e) for e in spec.get("overlays", [])])
    T = conf["design"]["tile_px"]
    pal = conf["fixed"]["env_palette"]
    name = core.snake(spec["name"])
    work = os.path.join(core.WORK, "ground")
    os.makedirs(work, exist_ok=True)
    art = core.art(conf, "tiles", name)
    src = core.src(conf, "art", "tiles", name)
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/tiles/{name}'
    man.drop_dir(art)
    terrains, sources, tex = [], [], {}
    # ---- base: one atlas row per base texture, the variants side by side, all full tiles of that terrain
    for e in spec.get("base", []):
        tn = core.snake(e["name"])
        seed = int(e.get("seed", 800))
        vs = texture(tn, e["prompt"], T, pal, work, seed, int(e.get("variants", 4)), e.get("tpl", "ground"))
        A = vs[0]
        tex[tn] = A
        tid = len(terrains)
        terrains.append((tn, _median_rgb(A)))
        p = core.save_clean(Image.fromarray(np.concatenate(vs, axis=1)), os.path.join(art, f"base_{tn}.png"))
        man.add(p, "tile_atlas", prompt=e["prompt"], seed=seed, routes=("klein",), tile_px=T, terrains=[tn],
                layout=f"1x{len(vs)}: variants of one seamless tile; the outer {T // 8} px ring is shared, so any "
                       "variant borders any other", wrap_ratio=round(wrap_error(A), 2))
        sources.append({"atlas_res": f"{res}/base_{tn}.png", "kind": "base", "name": tn, "tiles": [
            {"x": k, "y": 0, "terrain": None, "probability": 1.0 if k == 0 else 0.6,
             "custom": e.get("surface")} for k in range(len(vs))]})
    # ---- overlays: one 8x4 atlas each, terrain vs empty
    solid_any = False
    for e in spec.get("overlays", []):
        tn = core.snake(e["name"])
        seed = core.seed_of(e, 820)
        style = e.get("style", "organic")
        if style in connectors.STYLES:
            # fences / railings / pipes / rails: drawn in code from the side connections, no texture, no model
            tiles = [connectors.tile(m, T, style, e.get("colors")) for m in BLOB]
            atlas = np.zeros((4 * T, 12 * T, 4), np.uint8)
            for i, t_ in enumerate(tiles):
                atlas[(i // 12) * T:(i // 12 + 1) * T, (i % 12) * T:(i % 12 + 1) * T] = t_
            tid = len(terrains)
            terrains.append((tn, tuple(int(v) for v in connectors.ramp(style, e.get("colors"))["mid"][:3])))
            p = core.save_clean(Image.fromarray(atlas), os.path.join(art, f"overlay_{tn}.png"))
            solid = bool(e.get("solid", style != "rail"))
            solid_any |= solid
            man.add(p, "tile_atlas", tile_px=T, terrains=[tn], style=style, solid=solid, routes=(),
                    workflow="Dotwork connector (drawn in code)", layout="12 columns: the 47 blob tiles; only the "
                    "side bits shape the drawing (straight, elbow, tee, cross, dead end)")
            rows = [{"x": i % 12, "y": i // 12, "terrain": tid,
                     "peers": tuple(tid if (m >> b) & 1 else -1 for b in range(8)), "custom": e.get("surface"),
                     "solid_rects": connectors.solid_rects(m, T, style) if solid else None}
                    for i, m in enumerate(BLOB)]
            sources.append({"atlas_res": f"{res}/overlay_{tn}.png", "kind": "overlay", "name": tn, "tiles": rows})
            continue
        vs = texture(tn, e["prompt"], T, pal, work, seed, int(e.get("variants", 3)), e.get("tpl", "ground"))
        if e.get("tint"):  # e.g. a plateau top in lighter grass: same multiplier on every variant keeps rings shared
            k = np.array(e["tint"] if isinstance(e["tint"], list) else [e["tint"]] * 3, np.float32)
            vs = [lib.finish(np.dstack([np.clip(v * k, 0, 255).astype(np.uint8), np.full(v.shape[:2], 255, np.uint8)]),
                             palette=pal, outline="", max_colors=24 if T >= 64 else 16)[..., :3] for v in vs]
            ring = np.ones((T, T), bool)
            ring[T // 8:T - T // 8, T // 8:T - T // 8] = False
            for v in vs[1:]:  # the per-image color cap may snap ring pixels differently: re-share the base ring
                v[ring] = vs[0][ring]
        A = vs[0]
        tex[tn] = A
        tid = len(terrains)
        terrains.append((tn, _median_rgb(A)))
        relief = e.get("relief", "raised")
        anim = e.get("animate")
        if anim:
            # animated overlay (water, sludge, lava): the seamless texture rolls a full tile over N frames inside the
            # fixed edge coverage; every tile shows the same frame at once, so seams hold in space and in time.
            # No texture variants here: rolling would break the ring they share.
            n, dx, dy = int(anim.get("frames", 4)), int(anim.get("dx", 1)), int(anim.get("dy", 0))
            frames = []
            for f in range(n):
                af = np.roll(A, (dy * f * T // n, dx * f * T // n), (0, 1))
                if anim.get("pulse"):
                    af = np.clip(af.astype(np.float32) * (1 + float(anim["pulse"]) * np.sin(2 * np.pi * f / n)),
                                 0, 255).astype(np.uint8)
                frames.append(blob_atlas(af, T, relief, seed, (), style))
            rows_ = frames[0].shape[0] // T
            atlas = np.zeros((rows_ * T, 12 * n * T, 4), np.uint8)
            for i in range(len(BLOB)):
                cx, cy = i % 12, i // 12
                for f in range(n):
                    atlas[cy * T:(cy + 1) * T, (cx * n + f) * T:(cx * n + f + 1) * T] =                         frames[f][cy * T:(cy + 1) * T, cx * T:(cx + 1) * T]
            vs = [A]
        else:
            atlas = blob_atlas(A, T, relief, seed, vs[1:], style)
        p = core.save_clean(Image.fromarray(atlas), os.path.join(art, f"overlay_{tn}.png"))
        core.save_clean(Image.fromarray(A), os.path.join(art, f"spr_tile_{tn}.png"))
        solid_any |= bool(e.get("solid"))
        man.add(p, "tile_atlas", prompt=e["prompt"], seed=seed, routes=("klein",), tile_px=T, terrains=[tn],
                relief=relief, solid=bool(e.get("solid")), layout="12 columns: the 47 blob tiles (Godot Match "
                "Corners and Sides; peering bits in the TileSet), repeated once per texture variant (random pick); "
                "transparent outside",
                wrap_ratio=round(wrap_error(A), 2))
        rows = blob_rows(tid, T, e.get("surface"), bool(e.get("solid")), len(vs) - 1, style)
        if anim:  # base tiles move to column cx * n; their frames follow to the right
            n = int(anim.get("frames", 4))
            for r_ in rows:
                r_["x"] = r_["x"] * n
                r_["anim"] = {"frames": n, "fps": float(anim.get("fps", 6))}
        sources.append({"atlas_res": f"{res}/overlay_{tn}.png", "kind": "overlay", "name": tn, "tiles": rows})
    # ---- decals: one row of small transparent sprites, no terrain (scatter with the editor's random paint)
    if spec.get("decals"):
        ims = []
        for k, e in enumerate(spec["decals"]):
            dn = core.snake(e["name"])
            seed = core.seed_of(e, 900)
            cp = os.path.join(work, f"decal_{dn}_s{seed}_{T}_{core.key(e['prompt'], e.get('size'), core.palette_key(pal))}.png")
            if not os.path.exists(cp):
                core.ensure_comfy()
                o = fit_sprite(core.prompt(DECAL_TPL, s=e["prompt"]), seed, f"dotwork/ground/{dn}",
                               int(e.get("size", T * 5 // 8)), T, baseline=T - T // 8, fit="longest",
                               palette=pal, outline="", max_colors=12)  # fits its cell: no rescaling of pixels
                Image.open(o["path"]).convert("RGBA").save(cp)
            ims.append(np.array(Image.open(cp).convert("RGBA")))
        p = core.save_clean(Image.fromarray(np.concatenate(ims, axis=1)), os.path.join(art, f"decals_{name}.png"))
        man.add(p, "tile_atlas", tile_px=T, layout=f"1x{len(ims)} decals: " +
                ", ".join(core.snake(e["name"]) for e in spec["decals"]), routes=("klein",))
        sources.append({"atlas_res": f"{res}/decals_{name}.png", "kind": "decals", "name": "decals",
                        "tiles": [{"x": k, "y": 0, "terrain": None} for k in range(len(ims))]})
    # ---- fixtures: doors, windows, signs, chimneys ... rendered as sprites, cut into tiles (no terrain)
    fixtures = {}
    if spec.get("fixtures"):
        core.ensure_comfy()
        ref = lib.ref(conf["design"]["character"].get("style_ref", "cast"))
        cells = []
        for k, e in enumerate(spec["fixtures"]):
            fname = core.snake(e["name"])
            w, h = e.get("cells", [1, 1])
            seed = core.seed_of(e, 950)
            cp = os.path.join(work, f"fixture_{fname}_s{seed}_{w}x{h}_{T}_{e.get('view', 'front')}_{e.get('fit', 'box')}_"
                                    f"{core.key(e['prompt'], e.get('solid'), lib.ref_key(conf), core.palette_key(pal))}.png")
            if not os.path.exists(cp):
                big = max(w, h) * T
                # view: front (wall pieces, doors), top (furniture, beds), flat (rugs, mats: straight overhead)
                tpl = {"top": FIXTURE_TOP_TPL, "flat": FIXTURE_FLAT_TPL}.get(e.get("view"), FIXTURE_TPL)
                # fit: box (whole object inside its cells, default), height (fill the height, crop the sides: doors),
                # width (fill the width, crop top/bottom)
                fm = e.get("fit", "box")
                box = {"box": (w * T - 2, h * T - 2), "height": (10 ** 4, h * T - 2), "width": (w * T - 2, 10 ** 4)}[fm]
                o = fit_sprite(core.prompt(tpl, s=e["prompt"]), seed, f"dotwork/ground/fx_{fname}", big - 2, big,
                               baseline=big - 1, ref_fn=ref, fit=box, palette=pal, max_colors=24)
                im = Image.open(o["path"]).convert("RGBA")
                x0 = (big - w * T) // 2
                im.crop((x0, big - h * T, x0 + w * T, big)).save(cp)  # bottom-aligned, centred
            pim, _, note = qa.white_pockets(Image.open(cp).convert("RGBA"))
            if note:
                core.log(f"fixture {fname}: {note}")
            im = np.array(pim)
            start = len(cells)
            for cy in range(h):
                for cx in range(w):
                    cells.append(im[cy * T:(cy + 1) * T, cx * T:(cx + 1) * T])
            fixtures[fname] = {"w": w, "h": h, "first": start, "solid": bool(e.get("solid"))}
        cols = 12
        atl = np.zeros((((len(cells) + cols - 1) // cols) * T, cols * T, 4), np.uint8)
        for i, c in enumerate(cells):
            atl[(i // cols) * T:(i // cols + 1) * T, (i % cols) * T:(i % cols + 1) * T] = c
        p = core.save_clean(Image.fromarray(atl), os.path.join(art, f"fixtures_{name}.png"))
        man.add(p, "tile_atlas", tile_px=T, routes=("klein",), layout="12 columns; fixture tiles in reading order: "
                + ", ".join(f"{n} {f['w']}x{f['h']} from slot {f['first']}" for n, f in fixtures.items()))
        solid_any |= any(f["solid"] for f in fixtures.values())
        tiles = []
        for n, f in fixtures.items():
            for j in range(f["w"] * f["h"]):
                i = f["first"] + j
                tiles.append({"x": i % cols, "y": i // cols, "terrain": None,
                              "solid_rects": [(-T // 2, -T // 2, T // 2, T // 2)] if f["solid"] else None})
        sources.append({"atlas_res": f"{res}/fixtures_{name}.png", "kind": "fixtures", "name": "fixtures",
                        "tiles": tiles, "fixtures": fixtures, "cols": cols})
    custom = "surface" if any(e.get("surface") for e in spec.get("base", []) + spec.get("overlays", [])) else None
    overlay_ids = [s["tiles"][0]["terrain"] for s in sources if s["kind"] == "overlay"]
    ts = godot.tileset_layers(os.path.join(art, f"ground_{name}_tileset.tres"), T, sources, terrains, custom=custom,
                              physics=solid_any, overlays=overlay_ids, mode="match_corners_and_sides")
    man.add(ts, "tileset", tile_px=T, terrain_mode="match_corners_and_sides", terrains=[t[0] for t in terrains],
            sources=[{"id": i, "kind": s["kind"], "name": s["name"]} for i, s in enumerate(sources)],
            custom_data=custom, physics=solid_any,
            usage="one TileMapLayer per source kind: base (plain tiles; random paint or mapbuild), one per overlay "
                  "terrain (terrain paint, default settings: what you paint is what you get), decals (random paint)")
    core.log(f"ground {name}: {len(terrains)} terrains, {len(sources)} sources -> "
             f"{os.path.basename(ts) if ts else 'no TileSet (--engine none)'}")   # basename(None) crashed engine none
    return {"tileset": ts, "res": f"{res}/ground_{name}_tileset.tres", "sources": sources, "terrains": terrains,
            "art": art, "src": src, "tile_px": T}
