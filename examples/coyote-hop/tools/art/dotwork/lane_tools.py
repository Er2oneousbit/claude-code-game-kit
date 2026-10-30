#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_tools.py
# Purpose : sprite tools on an existing sprite: instruction edits, region inpaint, normal map with lit previews
#           (SpriteKiln workflows, klein VAE).
# Usage   : pack spec "tools": [{"name": "guard_edit", "source": "assets/art/characters/guard/frames/
#           spr_guard_idle_s_00.png", "edits": ["give him a red scarf"], "inpaint": {"prompt": "a tall top hat",
#           "region_box": [x, y, w, h]}, "normal": true}]
# Notes   : source is relative to the game and must exist. region_box is optional: the default is the top third of
#           the sprite (the head). The normal map is computed from the sprite (no model). Resumes per entry: an
#           unchanged source and job list keeps its files.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import json
import os
import shutil

import numpy as np
from PIL import Image

import fcore as core
import qa
from lane_character import _wf, _saves

import engine as lib  # noqa: E402

COMFY_OUT = lib.comfy_out("dotwork_work", "tools")


def _run(g):
    return lib.run_job(g, timeout=1800)


def _first(pattern):
    fs = sorted(glob.glob(pattern))
    if not fs:
        raise core.JobError(f"no output matched {pattern}")
    return fs[0]


def _settle(path, src_img, conf):
    """Edits came back with ~95 soft colours around a 37-colour sprite (2026-10-30 art audit). Snap to the source's
    own colours plus the object palette, so untouched pixels map back exactly while a new element (a red scarf)
    still finds its hue, then cap at the source's count + 12."""
    src_cols = qa.palette_of(src_img)
    pal = lib.load_hex(conf["fixed"]["palette"])
    pal = np.concatenate([src_cols.astype(np.uint8), pal]) if len(src_cols) else pal
    a = lib.quantize(np.array(Image.open(path).convert("RGBA")), pal)
    a[..., 3] = np.where(a[..., 3] >= 128, 255, 0).astype(np.uint8)
    return Image.fromarray(lib.cap_colors(a, len(src_cols) + 12))


def run(entries, pack, man, conf):
    for e in entries:
        name = core.snake(e["name"])
        art = core.art(conf, "tools", name)
        src_dir = core.src(conf, "art", "tools", name)
        sp = core.source_path(e["source"])
        # resume: one stamp per entry over the source image and every job; an unchanged entry keeps its files and rows
        req = core.key(core.sha256_file(sp)[:12] if os.path.exists(sp) else sp,
                       json.dumps(e.get("edits", [])), json.dumps(e.get("inpaint"), sort_keys=True), bool(e.get("normal")))
        stamp = core.work("tools", f"{name}.stamp")
        if os.path.isdir(art) and os.listdir(art) and os.path.exists(stamp):
            with open(stamp, encoding="utf-8") as f:
                if f.read() == req:
                    core.log(f"tools {name}: up to date")
                    continue
        core.ensure_comfy()
        man.drop_dir(art)
        os.makedirs(src_dir, exist_ok=True)
        src = core.save_clean(Image.open(sp).convert("RGBA"), os.path.join(src_dir, "source.png"))
        fn = f"dotwork_tools_{name}.png"
        fn = lib.put(Image.open(src), fn)
        work = os.path.join(COMFY_OUT, name)
        shutil.rmtree(work, ignore_errors=True)
        for k, instr in enumerate(e.get("edits", [])):
            g = _saves(_wf("04_edit_pixel_art"), f"dotwork_work/tools/{name}/edit{k}/e")
            g["2"]["inputs"]["image"] = fn
            g["5"]["inputs"]["image"] = fn
            g["13"]["inputs"]["text"] = (f"Edit the pixel art sprite in image 1: {instr}. Keep everything else "
                                         "identical: same pose, same size, same pixel art style, same outline and colors.")
            r = _run(g)
            out = _first(os.path.join(work, f"edit{k}", "e_*31*.png")) if glob.glob(os.path.join(work, f"edit{k}", "e_*31*.png")) \
                else _first(os.path.join(work, f"edit{k}", "e_*.png"))
            dst = core.save_clean(_settle(out, Image.open(src), conf), os.path.join(art, f"spr_{name}_edit_{k:02d}.png"))
            man.add(dst, "edit", prompt=instr, workflow="SpriteKiln wf04 (klein reference edit)", routes=("klein",),
                    source="assets_src/art/tools/%s/source.png" % name)
            core.log(f"tools {name}: edit {k} '{instr[:40]}' {r['seconds']:.0f}s")
        if e.get("inpaint"):
            ip = e["inpaint"]
            im = Image.open(src)
            bb = im.getbbox()
            x, y, w, h = ip.get("region_box") or (bb[0], max(0, bb[1] - 4), bb[2] - bb[0], (bb[3] - bb[1]) // 3 + 4)
            g = _saves(_wf("05_inpaint_pixel_art"), f"dotwork_work/tools/{name}/inpaint/i")
            g["2"]["inputs"]["image"] = fn
            g["4"]["inputs"].update(x=int(x), y=int(y), width=int(w), height=int(h))
            g["12"]["inputs"]["text"] = (f"Pixel art sprite: {ip['prompt']}. Same pixel art style, same palette, "
                                         "same outline, gray background.")
            r = _run(g)
            out = _first(os.path.join(work, "inpaint", "i_*.png"))
            dst = core.save_clean(_settle(out, Image.open(src), conf), os.path.join(art, f"spr_{name}_inpaint.png"))
            man.add(dst, "inpaint", prompt=ip["prompt"], workflow="SpriteKiln wf05 (klein masked inpaint + merge)",
                    routes=("klein",), region=[int(x), int(y), int(w), int(h)])
            core.log(f"tools {name}: inpaint {r['seconds']:.0f}s")
        if e.get("normal"):
            g = _saves(_wf("28_sprite_normal_maps"), f"dotwork_work/tools/{name}/normal/n")
            g["2"]["inputs"]["image"] = fn
            r = _run(g)
            outs = sorted(glob.glob(os.path.join(work, "normal", "n_*.png")))
            nm = [o for o in outs if "_5_" in os.path.basename(o) or os.path.basename(o).startswith("n_5")]
            normal_png = nm[0] if nm else outs[0]
            dst = core.save_clean(Image.open(normal_png).convert("RGBA"), os.path.join(art, f"spr_{name}_normal.png"))
            man.add(dst, "normal_map", workflow="SpriteKiln wf28 (height from sprite, OpenGL convention)",
                    convention="opengl", pairs_with=os.path.basename(src))
            for i, o in enumerate(o for o in outs if o != normal_png):
                core.save_clean(Image.open(o).convert("RGBA"), os.path.join(src_dir, f"lit_preview_{i:02d}.png"))
            core.log(f"tools {name}: normal map {r['seconds']:.0f}s")
        with open(stamp, "w", encoding="utf-8") as f:   # written last: a failed job leaves no stamp, so it re-runs
            f.write(req)
