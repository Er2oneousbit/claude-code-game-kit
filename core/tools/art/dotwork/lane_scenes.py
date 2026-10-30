#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_scenes.py
# Purpose : full-screen backdrops (title, game over, cutscene stills): 2560x1440 -> 320x180 real pixels at 2x.
# Usage   : pack spec "scenes": [{"name": "title", "prompt": "a brass city at dusk under airships"}]
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import numpy as np
from PIL import Image

import fcore as core
import godot
from lane_battle_bgs import render_raw

import engine as lib  # noqa: E402

TPL = ("pixel art, {style} {genre} full-screen illustration of {s}, dramatic sky, rich detailed pixel art, wide "
       "cinematic composition, no characters in the foreground, no text, no letters, no border, limited palette")


def run(entries, pack, man, conf):
    art = core.art(conf, "scenes")
    src = core.src(conf, "art", "scenes")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/scenes'
    work = os.path.join(core.WORK, "scenes")
    os.makedirs(work, exist_ok=True)
    man.drop_owned(art, ("spr_scene_", "scene_"))   # shared with img2px and other packs
    for k, e in enumerate(entries):
        name = core.snake(e["name"])
        seed = core.seed_of(e, 8700)
        t = render_raw(name, e["prompt"], seed, work, tpl=TPL, w=2560, h=1440, lora=float(e.get("lora", 0.7)))
        t = lib.finish(np.dstack([t, np.full(t.shape[:2], 255, np.uint8)]), palette=conf["fixed"]["env_palette"],
                       outline="", max_colors=int(e.get("max_colors", 96)))[..., :3]
        im = Image.fromarray(t)
        dst = core.save_clean(im, os.path.join(art, f"spr_scene_{name}.png"))
        core.save_clean(im.resize((im.width * 2, im.height * 2), Image.NEAREST), os.path.join(src, f"{name}_2x.png"))
        man.add(dst, "scene_backdrop", prompt=e["prompt"], seed=seed, routes=("klein",), size=[im.width, im.height],
                display_scale=2, workflow="Dotwork scenes (klein 2560x1440, 8 px grid sample, env palette)")
        scn = godot.sprite_scene(os.path.join(art, f"scene_{name}.tscn"), f"{res}/spr_scene_{name}.png",
                                 node_name=f"Scene{name.title().replace('_', '')}", scale=2)
        man.add(scn, "scene", node="Sprite2D", scale=2, anchor="top_left", texture_filter="nearest")
