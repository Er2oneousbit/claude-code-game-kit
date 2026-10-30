#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_animprops.py
# Purpose : interactive props with state animations: chest (closed -> half -> open), door (closed -> ajar -> open),
#           lever (off / on), save point (glow loop); AnimatedSprite2D scenes, footprint for solid ones.
# Usage   : pack spec "animprops": [{"name": "chest", "kind": "chest", "prompt": "a wooden treasure chest"}]
# Notes   : Chest / door states are klein edits of the closed render; the lever's on state is its mirror; the glow is code.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import json
import os
import shutil

import numpy as np
from PIL import Image, ImageOps

import fcore as core
import godot
from lane_character import COMFY_WORK, _wf
from lane_props import PROP_TPL, fit_sprite

import engine as lib  # noqa: E402

EDITS = {
    "chest": [("half", "the lid of the chest is half open, a little golden light glows inside"),
              ("open", "the lid of the chest is wide open and the chest is empty inside")],
    "door": [("ajar", "the door is slightly ajar, a thin dark gap shows at its edge"),
             ("open", "the door is swung wide open, showing a dark doorway inside the frame")],
}
FRONT_TPL = ("pixel art sprite, straight-on front view of {s}, a building part for a 16-bit RPG town, drawn in the "
             "exact pixel art style, palette, outline and shading of image 1, steampunk, crisp dark outline, centered")


def edit(src, instr, seed, tag):
    """Palette-locked klein edit of one sprite (cached by instruction + seed)."""
    os.makedirs(os.path.dirname(tag), exist_ok=True)
    out, meta = tag + ".png", tag + ".json"
    want = {"instr": instr, "seed": seed}
    if os.path.exists(out) and os.path.exists(meta) and json.load(open(meta)) == want:
        return out
    core.ensure_comfy()
    fn = f"dotwork_anim_{os.path.basename(tag)}.png"
    fn = lib.put(Image.open(src), fn)
    g = _wf("04_edit_pixel_art")
    rel = f"animprops/{os.path.basename(tag)}"
    shutil.rmtree(os.path.join(COMFY_WORK, *rel.split("/")), ignore_errors=True)
    g["31"]["inputs"].update(filename_prefix=f"dotwork_work/{rel}/free", upscale=1, as_animation=False)
    g["32"]["inputs"].update(filename_prefix=f"dotwork_work/{rel}/locked", upscale=1, as_animation=False)
    g["2"]["inputs"]["image"] = fn
    g["5"]["inputs"]["image"] = fn
    g["19"]["inputs"]["noise_seed"] = seed
    g["13"]["inputs"]["text"] = (f"Edit the pixel art sprite in image 1: {instr}. Keep the same object, same size, same "
                                 "position, same pixel art style, colors and outline.")
    lib.run_job(g, timeout=1200)
    outs = sorted(glob.glob(os.path.join(COMFY_WORK, *rel.split("/"), "locked*.png")))
    if not outs:
        raise core.JobError(f"animprops edit {tag}: no output")
    # same canvas as the source so frames line up
    im = Image.open(outs[0]).convert("RGBA")
    base = Image.open(src)
    if im.size != base.size:
        can = Image.new("RGBA", base.size, (0, 0, 0, 0))
        can.alpha_composite(im.crop(im.getbbox()), ((base.width - im.crop(im.getbbox()).width) // 2,
                                                     base.height - im.crop(im.getbbox()).height))
        im = can
    im.save(out)
    with open(meta, "w", encoding="utf-8") as fh:
        json.dump(want, fh)
    return out


def glow_frames(src, n=8, seed=3):
    """Save-point loop: bright pixels pulse, the upper 60% floats 1 px, a few sparkles twinkle."""
    base = np.array(Image.open(src).convert("RGBA")).astype(np.float32)
    a = base[..., 3] > 0
    ys, xs = np.nonzero(a)
    top, bot = ys.min(), ys.max()
    split = int(top + (bot - top) * 0.6)
    lum = base[..., :3].mean(2)
    bright = a & (lum > np.percentile(lum[a], 60))
    rng = np.random.default_rng(seed)
    spark_pts = [(int(rng.integers(top, split)), int(rng.integers(xs.min(), xs.max() + 1))) for _ in range(10)]
    out = []
    for f in range(n):
        im = base.copy()
        k = 1 + 0.18 * np.sin(2 * np.pi * f / n)
        im[bright, :3] = np.clip(im[bright, :3] * k, 0, 255)
        if f in (2, 3, 4):  # float: the crystal part rises 1 px for part of the loop
            up = np.zeros_like(im)
            up[:split - 1] = im[1:split]
            up[split - 1:] = im[split - 1:]
            im = up
        for j, (py, px) in enumerate(spark_pts):
            if (f + j) % 4 == 0 and 0 < py < im.shape[0] - 1 and 0 < px < im.shape[1] - 1:
                im[py, px] = (255, 255, 255, 255)
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    im[py + dy, px + dx] = (190, 230, 255, 255)
        out.append(Image.fromarray(im.astype(np.uint8)))
    return out


def _scene(path, frames_res, anim, name, solid, size, bb):
    w, h = size
    x0, y0, x1, y1 = bb
    off = (round(w / 2 - (x0 + x1) / 2), round(h / 2 - y1))
    fw = max(4, round((x1 - x0) * 0.8))
    lines = [f'[gd_scene load_steps={3 if solid else 2} format=3]', "",
             f'[ext_resource type="SpriteFrames" path="{frames_res}" id="1_sf"]', ""]
    if solid:
        lines += ['[sub_resource type="RectangleShape2D" id="RectangleShape2D_1"]', f"size = Vector2({fw}, 12)", ""]
    lines += [f'[node name="{name}" type="{"StaticBody2D" if solid else "Node2D"}"]', "",
              '[node name="Sprite" type="AnimatedSprite2D" parent="."]', "texture_filter = 1",
              'sprite_frames = ExtResource("1_sf")', f'animation = &"{anim}"', f'autoplay = "{anim}"',
              f"offset = Vector2({off[0]}, {off[1]})", ""]
    if solid:
        lines += ['[node name="CollisionShape2D" type="CollisionShape2D" parent="."]', "position = Vector2(0, -6)",
                  'shape = SubResource("RectangleShape2D_1")', ""]
    return godot._write(path, "\n".join(lines))


def run(entries, pack, man, conf):
    root = core.art(conf, "props", "anim")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/props/anim'
    work = os.path.join(core.WORK, "animprops")
    os.makedirs(work, exist_ok=True)
    pal = conf["fixed"]["palette"]
    ref = None
    for k, e in enumerate(entries):
        name, kind = core.snake(e["name"]), e["kind"]
        seed = core.seed_of(e, 9500)
        if kind == "door":
            w, h = e.get("cells", [1, 2])
            T = conf["design"]["tile_px"]
            W_, H_ = w * T, h * T
            canvas, fig, tpl, fit = max(W_, H_), max(W_, H_) - 2, FRONT_TPL, (10 ** 4, H_ - 2)
        else:
            size = int(e.get("size", 32))
            canvas = (size + 16 + 7) // 8 * 8
            fig, tpl, fit = size, PROP_TPL, "longest"
        # every state builds on the base render, so one key covers all of them: a new prompt, size or palette
        # re-renders the base and its states (the base used to be cached by name + seed only)
        ck = core.key(e['prompt'], kind, canvas, e.get('cells'), core.palette_key(pal), lib.ref_key(conf))
        stem = os.path.join(work, f"{name}_s{seed}_{ck}")
        base = stem + "_closed.png"
        if not os.path.exists(base):
            core.ensure_comfy()
            ref = ref or lib.ref(conf["design"]["character"].get("style_ref", "cast"))
            o = fit_sprite(tpl.format(s=e["prompt"]), seed, f"dotwork/animprops/{name}", fig, canvas,
                           baseline=canvas - 2, ref_fn=ref, fit=fit, palette=pal)
            im = Image.open(o["path"]).convert("RGBA")
            if kind == "door":  # bottom-aligned, centred door-sized crop
                x0 = (canvas - W_) // 2
                im = im.crop((x0, canvas - H_, x0 + W_, canvas))
            im.save(base)
        if Image.open(base).getbbox() is None:
            raise core.JobError(f"animprops {name}: the base render came out empty; give the entry another seed")
        states = {}
        if kind in EDITS:
            seq = [base] + [edit(base, instr, seed + 1 + i, f"{stem}_{st}")
                            for i, (st, instr) in enumerate(EDITS[kind])]
            states = {"closed": [seq[0]], "open": seq, "opened": [seq[-1]], "close": seq[::-1]}
            fps, default, solid = 8, "closed", True
        elif kind == "lever":
            on = stem + "_on.png"
            ImageOps.mirror(Image.open(base)).save(on)
            states = {"off": [base], "on": [on], "flip_on": [base, on], "flip_off": [on, base]}
            fps, default, solid = 8, "off", True
        else:  # glow
            gl = glow_frames(base)
            paths = []
            for i, f in enumerate(gl):
                p = f"{stem}_glow{i}.png"
                f.save(p)
                paths.append(p)
            states = {"idle": paths}
            fps, default, solid = 8, "idle", False
        out = os.path.join(root, name)
        man.drop_dir(out)
        anims, size_wh, bb = {}, None, None
        for st, paths in states.items():
            files = []
            for i, p in enumerate(paths):
                im = Image.open(p).convert("RGBA")
                size_wh = im.size
                bb = Image.open(base).getbbox()
                fn = f"spr_{name}_{st}_{i:02d}.png"
                dst = core.save_clean(im, os.path.join(out, fn))
                man.add(dst, "frame", animation=st, routes=("klein",), canvas=list(im.size), anchor="feet_bottom_center")
                files.append(fn)
            anims[st] = (files, fps, kind == "glow")
        tres = godot.sprite_frames(os.path.join(out, f"{name}_frames.tres"), f"{res}/{name}", anims)
        man.add(tres, "sprite_frames", animations=list(anims), node="AnimatedSprite2D")
        scn = _scene(os.path.join(out, f"{name}.tscn"), f"{res}/{name}/{name}_frames.tres", default,
                     name.title().replace("_", ""), solid, size_wh, bb)
        man.add(scn, "scene", node="StaticBody2D + AnimatedSprite2D" if solid else "Node2D + AnimatedSprite2D",
                animations=list(anims), autoplay=default, origin="feet")
        core.log(f"animprops {name}: {kind}, states {list(anims)}")
