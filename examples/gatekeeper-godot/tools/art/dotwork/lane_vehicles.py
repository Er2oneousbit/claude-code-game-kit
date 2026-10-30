#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_vehicles.py
# Purpose : overworld vehicles with 8 facing directions (Qwen multi-angle, directions 8) and a code-drawn ground
#           shadow; a scene with the hull raised by an altitude.
# Usage   : pack spec "vehicles": [{"name": "airship", "prompt": "a steampunk airship", "size": 72, "altitude": 24}]
# Notes   : The 8-way output order is assumed (east / west swapped like the verified 4-way run): check the review sheet,
#           set rot_order if a direction is wrong.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import os
import shutil

import numpy as np
from PIL import Image

import fcore as core
import godot
from lane_character import COMFY_WORK, _saves, _wf
from lane_props import fit_sprite

import engine as lib  # noqa: E402

TPL = ("pixel art sprite, top-down RPG overworld vehicle: {s}, seen from a high three-quarter top-down angle, facing "
       "the viewer, centered, drawn in the exact pixel art style, palette, outline and shading of image 1, crisp "
       "dark outline")
ROT8 = ["s", "sw", "w", "nw", "n", "ne", "e", "se"]


def shadow(width, height):
    """Dithered dark ellipse (alpha via a checker so it stays pixel art over any ground)."""
    w, h = max(8, width), max(4, height)
    yy, xx = np.mgrid[0:h, 0:w]
    inside = ((xx - (w - 1) / 2) / (w / 2)) ** 2 + ((yy - (h - 1) / 2) / (h / 2)) ** 2 <= 1
    core_ = ((xx - (w - 1) / 2) / (w / 2.6)) ** 2 + ((yy - (h - 1) / 2) / (h / 2.6)) ** 2 <= 1
    a = np.where(core_, 120, np.where(inside & ((xx + yy) % 2 == 0), 120, 0)).astype(np.uint8)
    return np.dstack([np.full((h, w, 3), 12, np.uint8), a])


def run(entries, pack, man, conf):
    root = core.art(conf, "vehicles")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/vehicles'
    for k, e in enumerate(entries):
        name = core.snake(e["name"])
        seed = core.seed_of(e, 9600)
        size = int(e.get("size", 72))
        canvas = (size + 16 + 7) // 8 * 8
        work = os.path.join(core.WORK, "vehicles", name)
        os.makedirs(work, exist_ok=True)
        tag = core.key(e["prompt"], seed, size, core.palette_key(conf["fixed"]["palette"]), lib.ref_key(conf))
        south = os.path.join(work, f"south_{tag}.png")
        if not os.path.exists(south):
            core.ensure_comfy()
            ref = lib.ref(conf["design"]["character"].get("style_ref", "cast"))
            o = fit_sprite(TPL.format(s=e["prompt"]), seed, f"dotwork/vehicles/{name}", size, canvas,
                           baseline=canvas - 2, ref_fn=ref, fit="longest", palette=conf["fixed"]["palette"])
            shutil.copyfile(o["path"], south)
        order = e.get("rot_order") or ROT8
        rtag = core.key(tag, e.get("asymmetric", False))
        have = {d: os.path.join(work, f"{d}_{rtag}.png") for d in order}
        if not all(os.path.exists(p) for p in have.values()):
            core.ensure_comfy()
            core.require_ram()   # Qwen-Image-Edit + its 7B text encoder load next
            fn = f"dotwork_vehicle_{name}.png"
            fn = lib.put(Image.open(south), fn)
            g = _saves(_wf("07_rotate_hq_qwen_multiangle"), f"dotwork_work/vehicles/{name}/r")
            shutil.rmtree(os.path.join(COMFY_WORK, "vehicles", name), ignore_errors=True)
            g["2"]["inputs"]["image"] = fn
            g["5"]["inputs"].update(directions="8", mirror_west=not e.get("asymmetric", False))
            r = lib.run_job(g, timeout=3600)
            files = sorted(glob.glob(os.path.join(COMFY_WORK, "vehicles", name, "r_*.png")))
            if len(files) < 8:
                raise core.JobError(f"vehicle {name}: rotation returned {len(files)} images, expected 8")
            for d, f in zip(order, files):
                shutil.copyfile(f, have[d])
            core.free_models()
            core.log(f"vehicle {name}: 8-way rotation {r['seconds']:.0f}s")
        out = os.path.join(root, name)
        man.drop_dir(out)
        ims = {d: Image.open(p).convert("RGBA") for d, p in have.items()}
        W = max(i.width for i in ims.values())
        H = max(i.height for i in ims.values())
        anims, widths = {}, []
        for d, im in ims.items():
            bb = im.getbbox()
            c = im.crop(bb)
            widths.append(c.width)
            can = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            can.alpha_composite(c, ((W - c.width) // 2, H - c.height))
            fn = f"spr_{name}_{d}.png"
            dst = core.save_clean(can, os.path.join(out, fn))
            man.add(dst, "frame", animation=f"idle_{d}", canvas=[W, H], anchor="hull_bottom_center",
                    routes=("klein", "qwen_rotate"))
            anims[f"idle_{d}"] = ([fn], 1, False)
        sw = int(np.median(widths) * 0.8)
        sp = core.save_clean(Image.fromarray(shadow(sw, max(4, sw // 3))), os.path.join(out, f"spr_{name}_shadow.png"))
        man.add(sp, "shadow", routes=(), workflow="Dotwork vehicle shadow (drawn in code)")
        tres = godot.sprite_frames(os.path.join(out, f"{name}_frames.tres"), f"{res}/{name}", anims)
        man.add(tres, "sprite_frames", animations=sorted(anims), canvas=[W, H])
        alt = int(e.get("altitude", 24))
        scn = godot._write(os.path.join(out, f"{name}.tscn"), "\n".join([
            '[gd_scene load_steps=3 format=3]', "",
            f'[ext_resource type="SpriteFrames" path="{res}/{name}/{name}_frames.tres" id="1_sf"]',
            f'[ext_resource type="Texture2D" path="{res}/{name}/spr_{name}_shadow.png" id="2_sh"]', "",
            f'[node name="{name.title().replace("_", "")}" type="Node2D"]', "",
            '[node name="Shadow" type="Sprite2D" parent="."]', "texture_filter = 1", 'texture = ExtResource("2_sh")', "",
            '[node name="Hull" type="AnimatedSprite2D" parent="."]', "texture_filter = 1",
            'sprite_frames = ExtResource("1_sf")', 'animation = &"idle_s"',
            f"offset = Vector2(0, {-(H // 2) - alt})", ""]))
        man.add(scn, "scene", node="Node2D (Shadow + Hull)", altitude=alt, directions=order)
        lib.sheet([("dirs " + " ".join(order), [os.path.join(out, f"spr_{name}_{d}.png") for d in order])],
                  core.src(conf, "art", "vehicles", f"{name}_review.png"), scale=2)
        core.log(f"vehicle {name}: 8 directions + shadow, canvas {W}x{H}")
