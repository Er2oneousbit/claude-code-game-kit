#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_enemies.py
# Purpose : battle enemies and bosses: static sprites facing right, feet at the scene origin; trapped white
#           background removed (skipped for white subjects).
# Usage   : pack spec "enemies": [{"name": "hound", "prompt": "a brass guard hound", "size": 80, "boss": false}]
# Notes   : size = longest side (regular 64-112, bosses ~192); flip, keep_white, holes.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

from PIL import Image, ImageOps

import fcore as core
import godot
import qa
from lane_props import fit_sprite

import engine as lib  # noqa: E402

TPL = ("pixel art sprite, 16-bit era JRPG battle enemy: {s}, full body, side view facing right, "
       "dramatic shading, rich detail, drawn in the exact pixel art style, palette, outline and shading of image 1, "
       "steampunk fantasy")


def run(entries, pack, man, conf):
    art = core.art(conf, "battle", "enemies")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/battle/enemies'
    work = os.path.join(core.WORK, "enemies")
    os.makedirs(work, exist_ok=True)
    man.drop_dir(art)  # clean re-export: a renamed or removed enemy must not linger in the pack
    ref = None
    for k, e in enumerate(entries):
        name = core.snake(e["name"])
        seed = core.seed_of(e, 8300)
        size = int(e.get("size", 96))
        canvas = (size + 15) // 8 * 8
        ck = core.key(e['prompt'], e.get('max_colors', 48), lib.ref_key(conf),
                      core.palette_key(conf['fixed']['env_palette']))
        cp = os.path.join(work, f"{name}_s{seed}_{size}_{ck}.png")
        if not os.path.exists(cp):
            core.ensure_comfy()
            ref = ref or lib.ref(conf["design"]["character"].get("style_ref", "cast"))
            o = fit_sprite(TPL.format(s=e["prompt"]), seed, f"dotwork/enemies/{name}", size, canvas,
                           baseline=canvas - 2, ref_fn=ref, fit="longest", palette=conf["fixed"]["env_palette"],
                           max_colors=int(e.get("max_colors", 48)))
            Image.open(o["path"]).convert("RGBA").save(cp)
            core.log(f"enemy {name}: {size}px {o['seconds']}s")
        im = Image.open(cp).convert("RGBA")
        im, removed, note = qa.white_pockets(im, force=(False if e.get("keep_white") else (True if e.get("holes")
                                                                                          else None)))
        if note:
            core.log(f"enemy {name}: {note}")
        if e.get("flip"):
            im = ImageOps.mirror(im)
        dst = core.save_clean(im, os.path.join(art, f"spr_enemy_{name}.png"))
        bb = im.getbbox() or (0, 0, im.width, im.height)
        man.add(dst, "enemy", prompt=e["prompt"], seed=seed, routes=("klein",), size=[im.width, im.height],
                content_bbox=list(bb), boss=bool(e.get("boss")), facing="right", anchor="feet_bottom_center",
                qa=[note] if note else [],
                workflow="Dotwork enemy lane (klein + style ref, sprite refine)")
        scn = godot.sprite_scene(os.path.join(art, f"enemy_{name}.tscn"), f"{res}/spr_enemy_{name}.png",
                                 node_name=f"Enemy{name.title().replace('_', '')}", centered=True,
                                 offset=(0, -(im.height // 2)))
        man.add(scn, "scene", node="Sprite2D", anchor="feet at the node origin")
