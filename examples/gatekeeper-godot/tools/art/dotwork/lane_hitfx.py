#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_hitfx.py
# Purpose : hit feedback drawn in code: hit sparks and slash arcs (additive SpriteFrames + scene) and a damage-flash
#           CanvasItem shader + material.
# Usage   : pack spec "hitfx": [{"name": "spark", "kind": "spark"}, {"name": "slash", "kind": "slash"}, {"name":
#           "flash", "kind": "flash"}]
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import math
import os

import numpy as np
from PIL import Image

import fcore as core
import godot

FLASH_SHADER = """shader_type canvas_item;
// Dotwork damage flash: mix the sprite toward a flat colour while keeping its alpha. Tween "flash" 1 -> 0 on hit.
uniform float flash : hint_range(0.0, 1.0) = 0.0;
uniform vec4 flash_color : source_color = vec4(1.0, 1.0, 1.0, 1.0);

void fragment() {
	vec4 c = texture(TEXTURE, UV);
	COLOR = vec4(mix(c.rgb, flash_color.rgb, flash), c.a) * vec4(1.0, 1.0, 1.0, COLOR.a);
}
"""


def _rgb(h):
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


def _steps(x, n=4):
    """A 0..1 field cut to n flat levels, so a frame's colours form a short ramp like hand-made pixel effects instead
    of ~100 anti-aliased shades (2026-10-30 art audit: 89-101 colours in a 150 px slash)."""
    return np.round(np.clip(x, 0, 1) * (n - 1)) / (n - 1)


def _dither_alpha(a):
    """Hard 3-level alpha (0 / 50% checker / full) so additive frames stay crisp pixel art."""
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    checker = (yy + xx) % 2 == 0
    return np.where(a > 0.66, 255, np.where((a > 0.25) & checker, 255, 0)).astype(np.uint8)


def spark_frames(size, color, n=6, rays=8, seed=1):
    rng = np.random.default_rng(seed)
    c = (size - 1) / 2
    yy, xx = np.mgrid[0:size, 0:size]
    ang = np.arctan2(yy - c, xx - c)
    r = np.hypot(yy - c, xx - c)
    base = _rgb(color)
    offs = rng.uniform(0, 2 * np.pi)
    out = []
    for f in range(n):
        t = (f + 1) / n
        reach = c * (0.35 + 0.65 * t)
        width = 0.20 * (1 - t) + 0.05
        ray = np.zeros_like(r)
        for k in range(rays):
            a0 = offs + 2 * np.pi * k / rays
            d = np.abs((ang - a0 + np.pi) % (2 * np.pi) - np.pi)
            ln = reach * (1.0 if k % 2 == 0 else 0.6)
            ray = np.maximum(ray, (d < width) * (r < ln) * (r > reach * 0.25 * t))
        core_ = np.clip(1 - r / max(1, c * 0.45 * (1 - t) + 1), 0, 1)
        a = np.maximum(ray * (1 - t * 0.7), core_)
        rgb = np.clip(base * (0.6 + 0.4 * _steps(a)[..., None]) + 255 * _steps(core_)[..., None] * 0.6, 0, 255)
        out.append(np.dstack([rgb.astype(np.uint8), _dither_alpha(a)]))
    return out


def slash_frames(size, color, n=5, direction="down_left"):
    """A crescent swept along an arc: each frame shows the blade's leading edge plus a fading tail."""
    c = (size - 1) / 2
    yy, xx = np.mgrid[0:size, 0:size]
    if direction == "down_right":
        xx = size - 1 - xx
    ang = np.degrees(np.arctan2(yy - c, xx - c))  # -180..180, 0 = east
    r = np.hypot(yy - c, xx - c)
    base = _rgb(color)
    start, end = -150.0, 30.0  # sweep from upper-left round to lower-right (mirrored for down_right)
    out = []
    for f in range(n):
        head = start + (end - start) * (f + 1) / n
        tail = head - 90.0
        inside = (ang <= head) & (ang >= tail)
        prog = np.clip((ang - tail) / max(1e-6, head - tail), 0, 1)  # 1 at the head
        thick = 0.8 + 3.2 * np.sin(np.pi * prog) * (1.0 - 0.25 * (f / n))  # tapered at both ends: a blade arc
        band = np.abs(r - c * 0.78) < thick
        a = inside * band * (0.35 + 0.65 * prog) * (1.0 if f < n - 1 else 0.6)
        rgb = np.clip(base * (0.55 + 0.45 * _steps(prog)[..., None]) + 60 * _steps(prog)[..., None], 0, 255)
        out.append(np.dstack([rgb.astype(np.uint8), _dither_alpha(a)]))
    return out


def run(entries, pack, man, conf):
    art = core.art(conf, "fx")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/fx'
    mat = godot.additive_material(os.path.join(art, "mat_additive.tres"))
    man.add(mat, "material", blend_mode="add")
    for e in entries:
        name = core.snake(e["name"])
        kind = e.get("kind", "spark")
        if kind == "flash":
            if not godot.ENABLED:
                core.log(f"hitfx {name}: skipped (--engine none: the damage flash is a Godot shader)")
                continue
            sp = os.path.join(art, "shaders", "damage_flash.gdshader")
            os.makedirs(os.path.dirname(sp), exist_ok=True)
            with open(core.safe_dest(sp), "w", encoding="utf-8", newline="\n") as f:
                f.write(FLASH_SHADER)
            mp = godot._write(os.path.join(art, "shaders", "mat_damage_flash.tres"), "\n".join([
                '[gd_resource type="ShaderMaterial" load_steps=2 format=3]', "",
                f'[ext_resource type="Shader" path="{res}/shaders/damage_flash.gdshader" id="1_sh"]', "",
                "[resource]", 'shader = ExtResource("1_sh")', "shader_parameter/flash = 0.0",
                "shader_parameter/flash_color = Color(1, 1, 1, 1)", ""]))
            man.add(sp, "shader", uniforms=["flash", "flash_color"], routes=(), workflow="Dotwork hitfx (written in code)",
                    usage="set as the sprite's material; tween shader_parameter/flash 1 -> 0 over ~0.15 s on hit")
            man.add(mp, "material", shader="damage_flash.gdshader")
            core.log("hitfx flash: shader + material")
            continue
        size = int(e.get("size", 48))
        fr = (spark_frames(size, e.get("color", "fff2b8")) if kind == "spark"
              else slash_frames(size, e.get("color", "e8f4ff"), direction=e.get("dir", "down_left")))
        out = os.path.join(art, name)
        man.drop_dir(out)
        files = []
        for i, a in enumerate(fr):
            fn = f"spr_fx_{name}_{i:02d}.png"
            core.save_clean(Image.fromarray(a), os.path.join(out, fn))
            man.add(os.path.join(out, fn), "fx_frame", routes=(), workflow=f"Dotwork hitfx {kind} (drawn in code)",
                    canvas=[size, size], anchor="center", blend="add")
            files.append(fn)
        fps = int(e.get("fps", 20))
        tres = godot.sprite_frames(os.path.join(out, f"fx_{name}_frames.tres"), f"{res}/{name}",
                                   {"play": (files, fps, False)})
        man.add(tres, "sprite_frames", animations=["play"], blend="add")
        scn = godot.effect_scene(os.path.join(out, f"fx_{name}.tscn"), f"{res}/{name}/fx_{name}_frames.tres",
                                 f"{res}/mat_additive.tres", "play", node_name=f"Fx{name.title().replace('_', '')}")
        man.add(scn, "scene", node="AnimatedSprite2D", material="mat_additive.tres", autoplay="play")
        core.log(f"hitfx {name}: {len(files)} frames ({kind})")
