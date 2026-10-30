#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# materials.py
# Purpose : render the material catalog (catalog/materials.json) at native pixel scale for review; optionally grow
#           the environment palette from those renders.
# Usage   : dotwork.py materials [--only NAME ...] [--extend-palette --add 32]
# Notes   : Outputs: <work>/ground/<name>_<key>_raw128.png and materials_sheet.png; the extended palette under <work>/palettes/.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import json
import os

import numpy as np
from PIL import Image, ImageDraw

import fcore as core
import lane_ground

CATALOG = os.path.join(core.HERE, "catalog", "materials.json")
WORK = os.path.join(core.WORK, "ground")


def items():
    cat = json.load(open(CATALOG, encoding="utf-8"))
    return [(tpl, n, e) for tpl, group in cat.items() if not tpl.startswith("_") for n, e in group.items()]


def render(only=None):
    src = os.path.join(WORK, "palette_src")
    os.makedirs(src, exist_ok=True)
    done = []
    for tpl, n, e in items():
        if only and n not in only:
            continue
        raw = lane_ground.render_raw(n, e["prompt"], WORK, int(e["seed"]), tpl)
        m = lane_ground.MARGIN
        Image.fromarray(raw[m:-m, m:-m]).save(os.path.join(src, f"{n}.png"))
        done.append((tpl, n, raw))
        core.log(f"materials: {n} ({tpl})")
    # contact sheet: 6 per row, 2x, labelled
    cols, cell = 6, 128 * 2 + 8
    sheet = Image.new("RGB", (cols * cell, ((len(done) + cols - 1) // cols) * (cell + 14)), (58, 58, 68))
    d = ImageDraw.Draw(sheet)
    for i, (tpl, n, raw) in enumerate(done):
        x, y = (i % cols) * cell, (i // cols) * (cell + 14)
        sheet.paste(Image.fromarray(raw).resize((256, 256), Image.NEAREST), (x + 4, y + 14))
        d.text((x + 4, y + 1), f"{n} ({tpl})", fill=(240, 220, 160))
    p = os.path.join(WORK, "materials_sheet.png")
    sheet.save(p)
    return p, len(done)


def extend_palette(add=32, out=None):
    """Grow the environment palette with the colours the rendered catalog needs (palette.extend); writes
    <work>/palettes/env_<N>.hex unless --out. Point env_palette at it in dotwork.config.json."""
    import palette
    from engine import load_hex
    conf = core.cfg()
    base = load_hex(conf["fixed"]["env_palette"])
    if not glob.glob(os.path.join(WORK, "palette_src", "*.png")):
        raise core.ToolError("no material renders yet: run `dotwork.py materials` first, then --extend-palette")
    pal, before, after, nf, na = palette.extend(base, [os.path.join(WORK, "palette_src", "*.png")], add)
    dst = out or core.work("palettes", f"env_{len(pal)}.hex")
    palette.write(pal, dst)
    print(f"[ OK ] {len(base)} + {na} = {len(pal)} colours -> {dst}; mean OKLab error on {nf} renders "
          f"{before:.4f} -> {after:.4f}")
    return 0
