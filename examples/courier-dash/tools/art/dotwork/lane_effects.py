#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_effects.py
# Purpose : effects and spells for additive blending: a klein first frame on black, motion by Wan 2.2 with an
#           effect-only prompt, trim, dithered fade and round vignette for one-shots, ping-pong for loops.
# Usage   : pack spec "effects": [{"name": "fire", "subject": "a burst of flames", "motion": "the flames burst up
#           and die down", "keep": 6, "size": 48}]
# Notes   : Wan sometimes turns particles into a face or a figure: review every effect; a new seed or wording fixes it.
#           Outputs: <assets>/art/fx/<name>/ frames, SpriteFrames, an AnimatedSprite2D scene, the shared additive material.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import json
import os
import shutil

import numpy as np
from PIL import Image

import fcore as core
import godot
import spritekiln

import engine as lib  # noqa: E402

VFX_TPL = ("pixel art sprite, pixel art game visual effect: {s}, bright glowing energy, crisp pixel clusters, "
           "{style} style, centered")
NEG = "face, eyes, mouth, smile, character, creature, person, cartoon mascot, text, letters, blurry, watermark"
BAYER = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) / 16


def fx_positive(motion):
    return ("2D pixel art visual effect animation of abstract glowing energy: %s. Static locked camera, no zoom, "
            "no panning, the plain solid black background stays unchanged, crisp pixel art, abstract particles and "
            "light only, no faces, no eyes, no characters, no creatures." % motion)


def _bayer(h, w):
    return np.tile(BAYER, (h // 4 + 1, w // 4 + 1))[:h, :w]


def dissolve(f, k, n):
    a = np.array(f).astype(np.float32)
    keep = _bayer(*a.shape[:2]) >= (k / n)
    a[..., :3] *= 1 - 0.5 * k / n
    a[..., 3] = np.where(keep, a[..., 3], 0)
    return Image.fromarray(a.astype(np.uint8))


def vignette(f, inner=0.55):
    a = np.array(f).astype(np.float32)
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2))
    a[..., 3] = np.where(_bayer(h, w) < np.clip((1 - r) / (1 - inner), 0, 1), a[..., 3], 0)
    return Image.fromarray(a.astype(np.uint8))


def make(e, work, conf):
    name = core.snake(e["name"])
    # cache key = name + seed: packs that share an effect name but want a different take must not reuse a clip
    d = os.path.join(work, f"{name}_s{int(e.get('seed', 777))}" + (f"_{e['size']}" if e.get("size") else "")
                     + "_" + core.key(core.prompt(VFX_TPL, s=e.get("subject")), e.get("motion")))
    os.makedirs(d, exist_ok=True)
    first = os.path.join(d, "first.png")
    size = int(e.get("size", conf["design"]["effect"]["size"]))  # per effect: big summon blasts, small sparks
    if not os.path.exists(first):
        core.ensure_comfy()
        o = lib.sprite(core.prompt(VFX_TPL, s=e["subject"]), int(e.get("seed", 777)), f"dotwork/fx/{name}", fig=size - 4,
                       canvas=size, baseline=size - 2, fit="longest", bg="black", palette=None, colors=16,
                       outline="", max_colors=0)
        shutil.copyfile(o["path"], first)
        core.log(f"fx {name}: first frame {o['seconds']}s")
    clip = os.path.join(d, "clip")
    if not glob.glob(os.path.join(clip, "f_*.png")):
        core.ensure_comfy()
        core.require_ram()
        fn = f"dotwork_fx_{name}.png"
        fn = lib.put(Image.open(first), fn)
        g = spritekiln.load("10_animate_sprite")
        for n in g.values():
            if n["class_type"] == "SK_SavePixelArt":
                n["inputs"].update(filename_prefix=f"dotwork_work/fx/{name}_s{int(e.get('seed', 777))}/f", upscale=1,
                                   as_animation=False)
            if n["class_type"] == "SaveAnimatedWEBP":
                n["inputs"]["filename_prefix"] = f"dotwork_work/fx/{name}_s{int(e.get('seed', 777))}/raw"
            if n["class_type"] == "KSamplerAdvanced":
                n["inputs"]["noise_seed"] = int(e.get("seed", 777))
        g["2"]["inputs"]["image"] = fn
        g["4"]["inputs"]["background"] = "black"
        g["5"]["inputs"].update(subject="the pixel art visual effect", action="custom", view="keep facing direction",
                                custom_motion=e["motion"], background="black")
        g["17"]["inputs"]["text"] = fx_positive(e["motion"])
        g["18"]["inputs"]["text"] = NEG
        r = lib.run_job(g, timeout=3600)
        os.makedirs(clip, exist_ok=True)
        for f in lib.job_files(r, "f_*.png"):   # this job's frames only, never an earlier motion's
            shutil.copyfile(f, os.path.join(clip, os.path.basename(f)))
        core.free_models()
        core.log(f"fx {name}: clip {r['seconds']:.0f}s")
    fr = [Image.open(p).convert("RGBA") for p in sorted(glob.glob(os.path.join(clip, "f_*.png")))]
    if e.get("loop", False) and e.get("keep"):
        # loops can drift too (a fireball turned into a smeared fire cloud after frame 4): keep the good frames and
        # ping-pong them (0 1 2 3 2 1) so the loop stays seamless
        good = fr[:int(e["keep"])]
        fr = good + good[-2:0:-1]
    if not e.get("loop", False):
        good = fr[:int(e.get("keep", 5))]
        fr = [vignette(f) for f in good + [dissolve(good[-1], k, 5) for k in range(1, 5)]]
    return name, fr


def run(entries, pack, man, conf):
    art = core.art(conf, "fx")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/fx'
    work = os.path.join(core.WORK, "fx")
    mat = godot.additive_material(os.path.join(art, "mat_additive.tres"))
    man.add(mat, "material", blend_mode="add")
    fps = conf["design"]["effect"]["fps"]
    for e in entries:
        name, fr = make(e, work, conf)
        W = max(f.width for f in fr)
        H = max(f.height for f in fr)
        out = os.path.join(art, name)
        man.drop_dir(out)  # clean re-export
        files = []
        for i, f in enumerate(fr):
            can = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            can.alpha_composite(f, ((W - f.width) // 2, (H - f.height) // 2))
            fn = f"spr_fx_{name}_{i:02d}.png"
            core.save_clean(can, os.path.join(out, fn))
            man.add(os.path.join(out, fn), "fx_frame", prompt=e["subject"], seed=e.get("seed", 777),
                    workflow="Dotwork effect lane (klein first frame + Wan 2.2, effect-only prompt)",
                    routes=("klein", "wan"), canvas=[W, H], anchor="center", blend="add")
            files.append(fn)
        loop = bool(e.get("loop", False))
        anim = "loop" if loop else "play"
        tres = godot.sprite_frames(os.path.join(out, f"fx_{name}_frames.tres"), f"{res}/{name}",
                                   {anim: (files, fps, loop)})
        man.add(tres, "sprite_frames", animations=[anim], canvas=[W, H], anchor="center", blend="add")
        scn = godot.effect_scene(os.path.join(out, f"fx_{name}.tscn"), f"{res}/{name}/fx_{name}_frames.tres",
                                 f"{res}/mat_additive.tres", anim, node_name=f"Fx{name.title().replace('_', '')}")
        man.add(scn, "scene", node="AnimatedSprite2D", material="mat_additive.tres", autoplay=anim)
        core.log(f"fx {name}: exported {len(files)} frames ({'loop' if loop else 'one-shot'})")
