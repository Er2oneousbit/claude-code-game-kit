#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_ui.py
# Purpose : UI panels and buttons as 9-slice textures + NinePatchRect scenes (margins found from the art).
# Usage   : pack spec "ui": [{"name": "dialog_panel", "prompt": "..."}]
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import numpy as np
from PIL import Image

import fcore as core
import godot
import engine as lib  # noqa: E402

UI_TPL = ("pixel art sprite, pixel art game UI element: {s}, a rectangular frame seen straight on, perfectly "
          "symmetric border of even thickness on all four sides, plain flat single-color interior fill, crisp "
          "edges, front view, centered, steampunk")


def margins(img):
    """Border thickness per side: scan from each edge along the middle row/column until the interior color
    (the center pixel) appears for 3 pixels in a row."""
    a = np.array(img.convert("RGBA"))
    h, w = a.shape[:2]
    c = a[h // 2, w // 2, :3].astype(int)

    def scan(line):
        run = 0
        for i, px in enumerate(line):
            run = run + 1 if (np.abs(px[:3].astype(int) - c).sum() < 24 and px[3] == 255) else 0
            if run == 3:
                return max(1, i - 2)
        return len(line) // 3

    return {"left": scan(a[h // 2]), "right": scan(a[h // 2][::-1]),
            "top": scan(a[:, w // 2]), "bottom": scan(a[:, w // 2][::-1])}


def symmetry(img):
    a = np.array(img.convert("RGBA")).astype(np.float32)
    lr = np.abs(a - a[:, ::-1]).mean() / 255
    tb = np.abs(a - a[::-1]).mean() / 255
    return round(float(1 - (lr + tb) / 2), 3)


def scene(path, tex_res, m, size):
    text = (f'[gd_scene load_steps=2 format=3]\n\n[ext_resource type="Texture2D" path="{tex_res}" id="1_tex"]\n\n'
            f'[node name="{os.path.basename(path)[:-5].title().replace("_", "")}" type="NinePatchRect"]\n'
            f'offset_right = {size * 3}.0\noffset_bottom = {size * 2}.0\ntexture = ExtResource("1_tex")\n'
            f'patch_margin_left = {m["left"]}\npatch_margin_top = {m["top"]}\n'
            f'patch_margin_right = {m["right"]}\npatch_margin_bottom = {m["bottom"]}\n')
    return godot._write(path, text)   # None under --engine none: the 9-slice PNG + margins in the manifest remain


def run(entries, pack, man, conf):
    man.assume("UI font: not generated; fetch an OFL pixel font (e.g. Pixelify Sans or Press Start 2P from Google "
               "Fonts) with the kit's tools/fetch_asset.py so the licence lands in ASSET_LOG")
    art = core.art(conf, "ui")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/ui'
    for k, e in enumerate(entries):
        name, size, seed = core.snake(e["name"]), int(e.get("size", 48)), core.seed_of(e, 9200)
        dst = os.path.join(art, f"ui_{name}.png")
        prompt = UI_TPL.format(s=e["prompt"])
        req = core.key(prompt, seed, size)   # resume: an unchanged entry is not re-rendered
        if man.current(dst, req) and (os.path.exists(os.path.join(art, f"ui_{name}.tscn")) or not godot.ENABLED):
            core.log(f"ui {name}: up to date")
            continue
        core.ensure_comfy()
        o = lib.sprite(prompt, seed, f"dotwork/ui/{name}", fig=size, canvas=size, baseline=size, fit="longest",
                       outline="")
        im = Image.open(o["path"]).convert("RGBA")
        bb = im.getbbox()
        if bb is None:
            raise core.JobError(f"ui {name}: the render came out empty; give the entry another seed")
        im = im.crop(bb)  # 9-slice art should be tight to the frame
        core.save_clean(im, dst)
        m, sym = margins(im), symmetry(im)
        notes = [] if sym >= 0.85 else [f"low symmetry {sym}: check corners before stretching"]
        man.add(dst, "ui_9slice", prompt=prompt, seed=seed, workflow="Dotwork sprite lane (klein refine loop)",
                routes=("klein",), size=[im.width, im.height], margins=m, symmetry=sym, qa=notes, request=req)
        sp = scene(os.path.join(art, f"ui_{name}.tscn"), f"{res}/ui_{name}.png", m, max(im.size))
        man.add(sp, "scene", node="NinePatchRect", margins=m)
        core.log(f"ui {name}: {im.size} margins {m} symmetry {sym}")
