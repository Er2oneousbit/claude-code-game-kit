#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# pxclean.py
# Purpose : clean any image into true pixel art without a model: find the pixel grid of an upscaled or generated
#           "pixel art" image (or shrink a plain image to a width), one colour per cell, plain background keyed out,
#           colours snapped to the game palette (or reduced to N), stray specks and white halos removed, an optional
#           1 px outline. For sprites drawn elsewhere, screenshots of your own art, or a render that came out 4x.
# Usage   : python dotwork.py clean --source assets_src/concept/lamp_4x.png --out assets/art/props/lamp
#           python dotwork.py clean --source "assets_src/raw/*.png" --out assets/art/icons --colors 16 --outline none
#           python dotwork.py clean --source assets_src/concept/tower.png --width 96 --palette env
# Notes   : --cell auto (default) measures the grid from the colour edges and reports it; a smooth image with no grid
#           reports cell 1, so give --width to shrink it. Files keep their names; the review sheet (before / after)
#           lands in the work folder. No model and no ComfyUI: it runs anywhere Pillow and numpy do.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import os

import numpy as np
from PIL import Image

import fcore as core
import engine as lib

OUTLINE = "#050407"   # engine.finish's default outline colour


def grid_period(rgb, max_cell=16):
    """(cell, phase) of the pixel grid along the image's x axis (pass a transpose for y).

    The colour change between neighbouring columns is large on a cell boundary and ~0 inside a cell. For each cell
    size p and phase, score = mean change on the boundary columns / mean change overall. Twice the true cell scores
    about as well (every other boundary), half of it scores about half (half its columns sit inside cells), so the
    answer is the smallest p within 85 % of the best score. A score under 1.5 means there is no grid: (1, 0)."""
    a = rgb.astype(np.float64)
    d = np.abs(np.diff(a, axis=1)).sum(axis=(0, 2))   # d[x] = change between column x and x + 1
    if len(d) < 4 or d.mean() == 0:
        return 1, 0
    best = {}
    for p in range(2, min(max_cell, len(d) // 2) + 1):
        # a boundary between columns x and x+1 means a new cell starts at x+1: phase = (x + 1) % p
        best[p] = max(((d[ph - 1::p].mean() if ph else d[p - 1::p].mean()) / d.mean(), ph) for ph in range(p))
    if not best:
        return 1, 0
    top = max(s for s, _ in best.values())
    if top < 1.5:
        return 1, 0
    p = min(q for q, (s, _) in best.items() if s >= 0.85 * top)
    return p, best[p][1]


def find_grid(rgb, mask=None, max_cell=16):
    """((cell_x, phase_x), (cell_y, phase_y)) measured inside the figure's box (a wide plain margin has no edges and
    skews the score). Phases are relative to the whole image."""
    x0 = y0 = 0
    if mask is not None and mask.any() and not mask.all():
        ys, xs = np.nonzero(mask)
        y0, x0 = ys.min(), xs.min()
        rgb = rgb[y0:ys.max() + 1, x0:xs.max() + 1]
    (px, phx), (py, phy) = grid_period(rgb, max_cell), grid_period(rgb.transpose(1, 0, 2), max_cell)
    return (px, int(phx + x0) % px), (py, int(phy + y0) % py)


def figure_alpha(im, bg="auto", tol=0.06):
    """Boolean figure mask. An image with real transparency keeps it; otherwise a plain background is flooded in from
    the borders: white, black, or (auto) the most common border colour when at least 60 % of the border is close to
    it. bg "none" keeps every pixel."""
    a = np.array(im.convert("RGBA"))
    if (a[..., 3] < 255).any():
        return a[..., 3] >= 128
    rgb = a[..., :3]
    if bg == "none":
        return np.ones(rgb.shape[:2], bool)
    if bg in ("white", "black"):
        return lib.key_bg(rgb, bg, tol)
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]).astype(np.int32)
    vals, counts = np.unique(border, axis=0, return_counts=True)
    c = vals[counts.argmax()]
    near_border = (np.abs(border - c).max(axis=1) <= 255 * tol).mean()
    if near_border < 0.6:   # a busy border (a scene, a texture): nothing to key
        return np.ones(rgb.shape[:2], bool)
    near = np.abs(rgb.astype(np.int32) - c).max(axis=2) <= 255 * tol
    return ~lib.border_flood(near)


def clean(im, cell="auto", width=None, bg="auto", palette=None, colors=0, outline="", islands=4, max_colors=0):
    """(clean RGBA uint8 array, report dict) for one image. palette: a .hex path (snap) or None; colors: k-means to N
    when no palette; outline: #RRGGBB or "" (none)."""
    rgb = np.array(im.convert("RGB"))
    alpha = figure_alpha(im, bg)
    rep = {"size_in": list(im.size)}
    if width:
        w = int(width)
        h = max(1, round(im.height * w / im.width))
        rgba = np.dstack([rgb, alpha.astype(np.uint8) * 255])
        small = np.array(Image.fromarray(rgba, "RGBA").resize((w, h), Image.BOX))
        arr = lib.hard_alpha(small)
        rep["mode"] = f"shrunk to {w}x{h}"
    else:
        if cell == "auto":
            (px, phx), (py, phy) = find_grid(rgb, alpha)
            if px != py:   # real pixel art has square cells; generated "pixel art" often has no true grid
                raise core.ToolError(f"clean: no clear pixel grid (x looks like {px}, y like {py}); give --cell N "
                                     "(screen pixels per art pixel) or --width W (shrink to W pixels wide)")
        else:
            px = py = int(cell)
            phx = phy = 0
        rep["grid"] = [px, phx, py, phy]
        if px == 1 and py == 1:
            arr = np.dstack([rgb, alpha.astype(np.uint8) * 255])
            rep["mode"] = "no grid found (cell 1): pixels kept; give --width to shrink"
        else:
            arr = lib.sample(rgb, alpha, px, phx, py, phy, 0.5)
            rep["mode"] = f"grid {px}x{py} (phase {phx},{phy})"
        arr = lib.hard_alpha(arr)
    if palette:   # the palette plus the dark outline every Dotwork sprite shares (it is not in the .hex files)
        arr = lib.quantize(arr, np.vstack([lib.load_hex(palette), lib.hexrgb(OUTLINE)[None]]))
        if max_colors:
            arr = lib.cap_colors(arr, int(max_colors))
    elif colors:
        arr = lib.kmeans_palette(arr, int(colors))
    if outline:
        arr = lib.outline(arr, lib.hexrgb(outline))
    if bg in ("auto", "white"):
        arr = lib.defringe(arr)
    if islands:
        arr = lib.drop_islands(arr, int(islands))
    op = arr[..., 3] == 255
    rep.update(size_out=[int(arr.shape[1]), int(arr.shape[0])], colours=int(len(np.unique(arr[op][:, :3], axis=0))))
    return arr, rep


def cmd(a, s):
    """dotwork.py clean: every PNG / JPG matching --source -> --out (inside the game), same names as PNG."""
    srcs = sorted({os.path.normpath(p) for g in a.source for p in glob.glob(core.project_path(g))})
    srcs = [p for p in srcs if p.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp"))]
    if not srcs:
        raise core.ToolError(f"clean: no images match {' '.join(a.source)} (paths are relative to the game)")
    for p in srcs:   # a glob can still reach a symlink that leads out; check every match
        core.project_path(os.path.relpath(p, s.project))
    out = core.project_path(a.out)
    names = [os.path.splitext(os.path.basename(p))[0] + ".png" for p in srcs]
    if len({os.path.normcase(n) for n in names}) != len(names):   # Lamp.png / lamp.png: one file on Windows
        raise core.ToolError("clean: two sources would share an output name; clean one folder at a time")
    if a.cell != "auto" and not (a.cell.isdigit() and 1 <= int(a.cell) <= 64):
        raise core.ToolError(f"clean: --cell is auto or a whole number of screen pixels per art pixel, not {a.cell!r}")
    if a.palette == "none":
        pal = None
    elif a.palette in ("obj", "env"):
        pal = s.conf["fixed"]["env_palette" if a.palette == "env" else "palette"]
    else:
        pal = core.project_path(a.palette)
    if a.colors and a.palette not in ("none",):
        core.log("clean: --colors applies with --palette none; snapping to the palette instead")
    os.makedirs(out, exist_ok=True)
    done = []
    for p, n in zip(srcs, names):
        arr, rep = clean(Image.open(p), cell=a.cell, width=a.width, bg=a.bg, palette=pal, colors=a.colors,
                         outline="" if a.outline == "none" else a.outline, islands=a.islands,
                         max_colors=a.max_colors)
        dst = core.save_clean(Image.fromarray(arr, "RGBA"), os.path.join(out, n))
        done.append(dst)
        core.log(f"clean {os.path.basename(p)}: {rep['mode']}, {rep['size_in'][0]}x{rep['size_in'][1]} -> "
                 f"{rep['size_out'][0]}x{rep['size_out'][1]}, {rep['colours']} colours")
    sheet = os.path.join(core.WORK, "clean", f"{core.snake(os.path.basename(out))}_review.png")
    lib.sheet([("before", srcs[:6]), ("after", done[:6])], sheet, scale=2)
    print(f"[ OK ] {len(done)} cleaned -> {os.path.relpath(out, s.project)}; review {sheet}")
    return 0
