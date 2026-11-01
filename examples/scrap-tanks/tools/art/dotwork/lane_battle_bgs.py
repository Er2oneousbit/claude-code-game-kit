#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_battle_bgs.py
# Purpose : battle backgrounds: klein 2560x1024 on the 8 px grid = 320x128 real pixels, shown at an exact 2x;
#           Sprite2D scene; the raw render is cached so palette changes are free. Optional drifting clouds: two
#           layers drawn in code in the background's own light colours (far: small and slow, near: bigger and
#           faster) scroll across the sky band over the painted picture, which stays whole.
# Usage   : pack spec "battle_bgs": [{"name": "mine", "prompt": "an underground mine with lanterns", "max_colors":
#           64}, {"name": "plains", "prompt": "grassy plains under a big cloudy sky", "scroll": -4}]
#           scroll: the near clouds' drift in pixels per second at 1x (negative = to the left; the far layer moves at
#           half that); horizon: how far down the clouds may reach, as a share of the height (default 0.33, the
#           template's "horizon in the upper third"); clouds: near-layer cloud count (default 3; far gets one more)
# Notes   : Cutting the painted sky off and scrolling it was tried first: any straight cut ran through a mountain
#           peak, whose tip then drifted away from its base (2026-10-31, the grassland sample). Clouds drawn on top
#           need no cut, and passing in front of distant mountains is what nearer clouds do. Leave scroll off for
#           caves and interiors. Godot: bg_<name>.tscn gets CloudsFar and CloudsNear children with a scroll shader
#           (TIME-driven, no script); other engines: the two cloud PNGs (they tile sideways) and their speeds in the
#           manifest.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import numpy as np
from PIL import Image

import fcore as core
import godot

import engine as lib  # noqa: E402

TPL = ("pixel art, {style} {genre} battle background, wide side view landscape of {s}, horizon in the "
       "upper third, open flat ground across the lower half for the battle, no characters, no monsters, no text, "
       "no border, rich detailed pixel art, limited palette")
W, H, GRID = 2560, 1024, 8
SCROLL_SHADER = """shader_type canvas_item;
// Dotwork battle clouds: the texture drifts sideways and wraps. speed is in texture widths per second (the lane sets
// it from the spec's scroll); nearest filtering keeps every frame on whole pixels.
uniform float speed = 0.0;

void fragment() {
	COLOR = texture(TEXTURE, vec2(fract(UV.x + TIME * speed), UV.y));
}
"""


def render_raw(name, prompt, seed, work, tpl=TPL, w=W, h=H, lora=0.7):
    """Cached raw grid sample (name + seed + a key of the full prompt, size and LoRA strength): palette / color-count
    changes need no re-render. Shared with lane_scenes (title / cutscene backdrops at 2560x1440)."""
    tag = core.key(core.prompt(tpl, s=prompt), w, h, lora)
    cp = os.path.join(work, f"{name}_s{seed}_{tag}_raw.png")
    if not os.path.exists(cp):
        core.ensure_comfy()
        out, sec = lib.run(lib.klein(core.prompt(tpl, s=prompt), seed, w, h, f"dotwork_work/{os.path.basename(work)}/{name}",
                                     lora=lora))
        rgb = np.array(Image.open(out).convert("RGB"))
        t = lib.sample(rgb, np.ones(rgb.shape[:2], bool), GRID, 0, GRID, 0, 0.5)[:h // GRID, :w // GRID, :3]
        Image.fromarray(t).save(cp)
        core.log(f"{os.path.basename(work)} {name}: {sec:.0f}s")
    return np.array(Image.open(cp).convert("RGB"))


def cloud_colours(rgb, rows):
    """Light, shade and rim for the clouds: the three lightest colours of the sky band that cover at least 0.3 % of
    it, so drifting clouds use the picture's own palette (a night sky gets dim clouds, not white ones)."""
    band = rgb[:rows].reshape(-1, 3)
    cols, counts = np.unique(band, axis=0, return_counts=True)
    keep = cols[counts >= max(1, band.shape[0] * 0.003)]
    lum = keep.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    pick = keep[np.argsort(-lum)][:3]
    while len(pick) < 3:
        pick = np.vstack([pick, pick[-1:]])
    return pick


def cloud_layer(w, rows, colours, seed, count, scale):
    """RGBA rows x w of pixel clouds that tile sideways (distances wrap at the edges): each cloud is three to five
    puffs on a flat base, lit colour on top, shade along the bottom, a checker-dithered rim."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:rows, 0:w].astype(np.float32)
    level = np.zeros((rows, w), np.int8)      # 0 clear, 1 rim, 2 shade, 3 light
    for _ in range(count):
        cw = scale * rng.uniform(22, 42)
        cx, base = rng.uniform(0, w), rng.uniform(0.35, 0.85) * rows
        dx = (xx - cx + w / 2) % w - w / 2    # wrapped: a cloud over the edge shows on both sides
        inside = np.zeros((rows, w), bool)
        rim = np.zeros((rows, w), bool)
        for k in range(int(rng.integers(3, 6))):
            px = (k / 4 - 0.5) * cw * 0.8 + rng.uniform(-2, 2)
            r = cw * rng.uniform(0.16, 0.26) * (1.25 if 1 <= k <= 3 else 0.9)
            d = np.hypot((dx - px) / r, (yy - (base - r * 0.35)) / (r * 0.8))
            inside |= d < 0.88
            rim |= d < 1.0
        inside &= yy <= base
        rim &= yy <= base
        shade = inside & (yy > base - max(1.5, scale * 2.5))
        level = np.maximum(level, np.where(rim & ~inside, 1, 0).astype(np.int8))
        level = np.maximum(level, np.where(inside, np.where(shade, 2, 3), 0).astype(np.int8))
    checker = (np.mgrid[0:rows, 0:w].sum(0) % 2) == 0
    out = np.zeros((rows, w, 4), np.uint8)
    for lv, c in ((3, colours[0]), (2, colours[1]), (1, colours[2])):
        m = (level == lv) & (checker if lv == 1 else True)
        out[m, :3], out[m, 3] = c, 255
    return out


def run(entries, pack, man, conf):
    art = core.art(conf, "battle", "bg")
    src = core.src(conf, "art", "battle", "bg")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/battle/bg'
    work = os.path.join(core.WORK, "battle_bg")
    os.makedirs(work, exist_ok=True)
    man.drop_owned(art, ("spr_bg_", "bg_"))   # a shared folder: this pack's files only
    pal = conf["fixed"]["env_palette"]
    for e in entries:   # bad options stop the run before anything renders
        if e.get("scroll") is not None and not isinstance(e["scroll"], (int, float)):
            raise core.ToolError(f"battle_bgs {e['name']}: scroll is pixels per second, a number")
        if not 0.1 <= float(e.get("horizon", 0.33)) <= 0.7:
            raise core.ToolError(f"battle_bgs {e['name']}: horizon is a share of the height, 0.1 .. 0.7")
        if not 1 <= int(e.get("clouds", 3)) <= 12:
            raise core.ToolError(f"battle_bgs {e['name']}: clouds is the near layer's count, 1 .. 12")
    for k, e in enumerate(entries):
        name = core.snake(e["name"])
        seed = core.seed_of(e, 8100)
        raw = render_raw(name, e["prompt"], seed, work, lora=float(e.get("lora", 0.7)))
        t = lib.finish(np.dstack([raw, np.full(raw.shape[:2], 255, np.uint8)]), palette=pal, outline="",
                       max_colors=int(e.get("max_colors", 64)))[..., :3]
        im = Image.fromarray(t)
        dst = core.save_clean(im, os.path.join(art, f"spr_bg_{name}.png"))
        core.save_clean(im.resize((im.width * 2, im.height * 2), Image.NEAREST), os.path.join(src, f"{name}_2x.png"))
        man.add(dst, "battle_bg", prompt=e["prompt"], seed=seed, routes=("klein",), size=[im.width, im.height],
                display_scale=2, workflow="Dotwork battle bg (klein 2560x1024, 8 px grid sample, env palette)")
        node = f"Bg{name.title().replace('_', '')}"
        scn_path = os.path.join(art, f"bg_{name}.tscn")
        if not e.get("scroll"):
            scn = godot.sprite_scene(scn_path, f"{res}/spr_bg_{name}.png", node_name=node, scale=2)
            man.add(scn, "scene", node="Sprite2D", scale=2, anchor="top_left", texture_filter="nearest")
            continue
        # drifting clouds: two layers drawn over the painted sky band, the far one smaller and at half the speed
        rows = int(round(t.shape[0] * float(e.get("horizon", 0.33))))
        cols = cloud_colours(t, rows)
        n = int(e.get("clouds", 3))
        layers = []
        for tag, count, scale, frac in (("far", n + 1, 0.6, 0.5), ("near", n, 1.0, 1.0)):
            layer = Image.fromarray(cloud_layer(im.width, rows, cols, seed + (1 if tag == "far" else 2), count, scale))
            lp = core.save_clean(layer, os.path.join(art, f"spr_bg_{name}_clouds_{tag}.png"))
            px = float(e["scroll"]) * frac
            man.add(lp, "battle_bg_layer", rows=rows, scroll_px_per_s=px, seamless="horizontal", routes=(),
                    workflow="Dotwork battle bg clouds (drawn in code)")
            layers.append((tag, -px / im.width))
        sh = os.path.join(art, "shaders", "bg_scroll.gdshader")
        if godot.ENABLED:
            os.makedirs(os.path.dirname(sh), exist_ok=True)
            core.write_text(sh, SCROLL_SHADER)
            man.add(sh, "shader", uniforms=["speed"], workflow="Dotwork battle bg (written in code)")
        lines = ['[gd_scene load_steps=7 format=3]', "",
                 f'[ext_resource type="Texture2D" path="{res}/spr_bg_{name}.png" id="1_tex"]',
                 f'[ext_resource type="Texture2D" path="{res}/spr_bg_{name}_clouds_far.png" id="2_far"]',
                 f'[ext_resource type="Texture2D" path="{res}/spr_bg_{name}_clouds_near.png" id="3_near"]',
                 f'[ext_resource type="Shader" path="{res}/shaders/bg_scroll.gdshader" id="4_sh"]', ""]
        for tag, speed in layers:
            lines += [f'[sub_resource type="ShaderMaterial" id="ShaderMaterial_{tag}"]', 'shader = ExtResource("4_sh")',
                      f"shader_parameter/speed = {speed:.6f}", ""]
        lines += [f'[node name="{node}" type="Sprite2D"]', "texture_filter = 1", 'texture = ExtResource("1_tex")',
                  "centered = false", "scale = Vector2(2, 2)", ""]
        for tag, tex in (("far", "2_far"), ("near", "3_near")):
            lines += [f'[node name="Clouds{tag.title()}" type="Sprite2D" parent="."]', "texture_filter = 1",
                      f'material = SubResource("ShaderMaterial_{tag}")', f'texture = ExtResource("{tex}")',
                      "centered = false", ""]
        scn = godot._write(scn_path, "\n".join(lines))
        man.add(scn, "scene", node="Sprite2D > CloudsFar, CloudsNear (scroll shader)", scale=2, anchor="top_left",
                texture_filter="nearest")
        core.log(f"battle_bgs {name}: drifting clouds in the top {rows} rows, {e['scroll']} px/s (far at half)")
