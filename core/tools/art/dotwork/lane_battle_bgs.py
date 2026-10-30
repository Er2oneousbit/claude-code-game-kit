#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_battle_bgs.py
# Purpose : battle backgrounds: klein 2560x1024 on the 8 px grid = 320x128 real pixels, shown at an exact 2x;
#           Sprite2D scene; the raw render is cached so palette changes are free.
# Usage   : pack spec "battle_bgs": [{"name": "mine", "prompt": "an underground mine with lanterns", "max_colors":
#           64}]
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import numpy as np
from PIL import Image

import fcore as core
import godot

import engine as lib  # noqa: E402

TPL = ("pixel art, 16-bit era JRPG battle background, wide side view landscape of {s}, horizon in the "
       "upper third, open flat ground across the lower half for the battle, no characters, no monsters, no text, "
       "no border, rich detailed pixel art, limited palette")
W, H, GRID = 2560, 1024, 8


def render_raw(name, prompt, seed, work, tpl=TPL, w=W, h=H, lora=0.7):
    """Cached raw grid sample (name + seed + a key of the full prompt, size and LoRA strength): palette / color-count
    changes need no re-render. Shared with lane_scenes (title / cutscene backdrops at 2560x1440)."""
    tag = core.key(tpl.format(s=prompt), w, h, lora)
    cp = os.path.join(work, f"{name}_s{seed}_{tag}_raw.png")
    if not os.path.exists(cp):
        core.ensure_comfy()
        out, sec = lib.run(lib.klein(tpl.format(s=prompt), seed, w, h, f"dotwork_work/{os.path.basename(work)}/{name}",
                                     lora=lora))
        rgb = np.array(Image.open(out).convert("RGB"))
        t = lib.sample(rgb, np.ones(rgb.shape[:2], bool), GRID, 0, GRID, 0, 0.5)[:h // GRID, :w // GRID, :3]
        Image.fromarray(t).save(cp)
        core.log(f"{os.path.basename(work)} {name}: {sec:.0f}s")
    return np.array(Image.open(cp).convert("RGB"))


def run(entries, pack, man, conf):
    art = core.art(conf, "battle", "bg")
    src = core.src(conf, "art", "battle", "bg")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/battle/bg'
    work = os.path.join(core.WORK, "battle_bg")
    os.makedirs(work, exist_ok=True)
    man.drop_dir(art)  # clean re-export
    man.drop_dir(src)
    pal = conf["fixed"]["env_palette"]
    for k, e in enumerate(entries):
        name = core.snake(e["name"])
        seed = core.seed_of(e, 8100)
        t = render_raw(name, e["prompt"], seed, work, lora=float(e.get("lora", 0.7)))
        t = lib.finish(np.dstack([t, np.full(t.shape[:2], 255, np.uint8)]), palette=pal, outline="",
                       max_colors=int(e.get("max_colors", 64)))[..., :3]
        im = Image.fromarray(t)
        dst = core.save_clean(im, os.path.join(art, f"spr_bg_{name}.png"))
        core.save_clean(im.resize((im.width * 2, im.height * 2), Image.NEAREST), os.path.join(src, f"{name}_2x.png"))
        man.add(dst, "battle_bg", prompt=e["prompt"], seed=seed, routes=("klein",), size=[im.width, im.height],
                display_scale=2, workflow="Dotwork battle bg (klein 2560x1024, 8 px grid sample, env palette)")
        scn = godot.sprite_scene(os.path.join(art, f"bg_{name}.tscn"), f"{res}/spr_bg_{name}.png",
                                 node_name=f"Bg{name.title().replace('_', '')}", scale=2)
        man.add(scn, "scene", node="Sprite2D", scale=2, anchor="top_left", texture_filter="nearest")
