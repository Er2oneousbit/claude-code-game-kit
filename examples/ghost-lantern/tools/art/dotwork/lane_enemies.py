#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_enemies.py
# Purpose : battle enemies and bosses: static sprites facing right, feet at the scene origin; trapped white
#           background removed (skipped for white subjects).
# Usage   : pack spec "enemies": [{"name": "hound", "prompt": "a brass guard hound", "size": 80, "boss": false}]
# Notes   : size = longest side (regular 64-112, bosses ~192); flip, keep_white, holes. A baked light-grey ground slab
#           is removed (qa.deslab, issue #28; keep_shadow true keeps whatever the model drew) and a dark dithered
#           contact shadow is drawn in code instead (spr_enemy_<name>_shadow.png, a Shadow child behind the sprite in
#           the scene; shadow false skips it). Palette swaps: an entry with
#           "recolor_of": "<another enemy in this spec>" plus hue / to / saturation / lightness / hues reuses that
#           enemy's sprite with its coloured ramps turned (recolor.py), no render: {"name": "frost_hound",
#           "recolor_of": "hound", "hue": 150}.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

from PIL import Image, ImageOps

import fcore as core
import godot
import qa
import recolor
from lane_props import fit_sprite

import engine as lib  # noqa: E402

TPL = ("pixel art sprite, {style} {genre} battle enemy: {s}, full body, side view facing right, "
       "dramatic shading, rich detail, drawn in the exact pixel art style, palette, outline and shading of image 1, "
       "{setting}")


def run(entries, pack, man, conf):
    art = core.art(conf, "battle", "enemies")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/battle/enemies'
    work = os.path.join(core.WORK, "enemies")
    os.makedirs(work, exist_ok=True)
    # clean re-export of this pack's enemies only: the folder is shared, and another pack's enemies stay
    man.drop_owned(art, ("spr_enemy_", "enemy_"))
    ref = None
    bases = {core.snake(e["name"]) for e in entries if not e.get("recolor_of")}
    swaps = [e for e in entries if e.get("recolor_of")]
    for e in swaps:   # checked before any render, so a typo costs nothing
        if core.snake(e["recolor_of"]) not in bases:
            raise core.ToolError(f"enemy {e['name']}: recolor_of {e['recolor_of']!r} is not an enemy in this spec "
                                 "(a swap of a swap is not supported: name the original)")
        recolor.options(e)
    made = {}   # name -> final sprite, for the swaps
    for k, e in enumerate([e for e in entries if not e.get("recolor_of")]):
        name = core.snake(e["name"])
        seed = core.seed_of(e, 8300)
        size = int(e.get("size", 96))
        canvas = (size + 15) // 8 * 8
        ck = core.key(core.prompt(TPL, s=e['prompt']), e.get('max_colors', 48), lib.ref_key(conf),
                      core.palette_key(conf['fixed']['env_palette']))
        cp = os.path.join(work, f"{name}_s{seed}_{size}_{ck}.png")
        if not os.path.exists(cp):
            core.ensure_comfy()
            ref = ref or lib.ref(conf["design"]["character"].get("style_ref", "cast"))
            o = fit_sprite(core.prompt(TPL, s=e["prompt"]), seed, f"dotwork/enemies/{name}", size, canvas,
                           baseline=canvas - 2, ref_fn=ref, fit="longest", palette=conf["fixed"]["env_palette"],
                           max_colors=int(e.get("max_colors", 48)))
            Image.open(o["path"]).convert("RGBA").save(cp)
            core.log(f"enemy {name}: {size}px {o['seconds']}s")
        im = Image.open(cp).convert("RGBA")
        im, removed, note = qa.white_pockets(im, force=(False if e.get("keep_white") else (True if e.get("holes")
                                                                                          else None)))
        notes = [note] if note else []
        if not e.get("keep_shadow"):
            im, _, slab = qa.deslab(im)
            if slab:
                notes.append(slab)
        for n in notes:
            core.log(f"enemy {name}: {n}")
        if e.get("flip"):
            im = ImageOps.mirror(im)
        made[name] = (im, e)
        _ship(man, art, res, name, im, e, qa=notes, prompt=e["prompt"], seed=seed,
              routes=("klein",), workflow="Dotwork enemy lane (klein + style ref, sprite refine)")
    pal = recolor.load_hex(conf["fixed"]["env_palette"])   # enemies are drawn in the environment palette
    for e in swaps:
        name, base = core.snake(e["name"]), core.snake(e["recolor_of"])
        src, be = made[base]
        (im,), mapping = recolor.recolor([src], pal, **recolor.options(e))
        _ship(man, art, res, name, im, dict(be, boss=e.get("boss", be.get("boss"))), qa=[], recolor_of=base,
              recolor=recolor.options(e),
              routes=(), workflow="Dotwork palette swap (recolor.py, drawn in code)")
        core.log(f"enemy {name}: palette swap of {base} ({len(mapping)} colours moved)")


def _ship(man, art, res, name, im, e, **row):
    """The enemy's PNG, its code-drawn contact shadow, and a Sprite2D scene (feet at the origin, the shadow a child
    drawn behind) with their manifest rows (a rendered enemy and a palette swap alike)."""
    dst = core.save_clean(im, os.path.join(art, f"spr_enemy_{name}.png"))
    bb = im.getbbox() or (0, 0, im.width, im.height)
    man.add(dst, "enemy", size=[im.width, im.height], content_bbox=list(bb), boss=bool(e.get("boss")),
            facing="right", anchor="feet_bottom_center", **row)
    shadow, dx = qa.contact_shadow(im) if e.get("shadow", True) else (None, 0)
    ext = [f'[ext_resource type="Texture2D" path="{res}/spr_enemy_{name}.png" id="1_tex"]']
    if shadow is not None:
        sp = core.save_clean(shadow, os.path.join(art, f"spr_enemy_{name}_shadow.png"))
        man.add(sp, "shadow", routes=(), workflow="Dotwork contact shadow (drawn in code)", offset_x=dx)
        ext.append(f'[ext_resource type="Texture2D" path="{res}/spr_enemy_{name}_shadow.png" id="2_sh"]')
    lines = [f"[gd_scene load_steps={len(ext) + 1} format=3]", "", *ext, "",
             f'[node name="Enemy{name.title().replace("_", "")}" type="Sprite2D"]', "texture_filter = 1",
             'texture = ExtResource("1_tex")', "centered = true",
             f"offset = Vector2(0, {round(im.height / 2 - bb[3])})", ""]   # content bottom (the feet) on y = 0
    if shadow is not None:   # the feet sit on the node origin; the shadow is centred there, under the feet
        lines += ['[node name="Shadow" type="Sprite2D" parent="."]', "show_behind_parent = true", "texture_filter = 1",
                  'texture = ExtResource("2_sh")', f"position = Vector2({dx}, 0)", ""]
    scn = godot._write(os.path.join(art, f"enemy_{name}.tscn"), "\n".join(lines))
    man.add(scn, "scene", node="Sprite2D (+ Shadow child)" if shadow is not None else "Sprite2D",
            anchor="feet at the node origin")
