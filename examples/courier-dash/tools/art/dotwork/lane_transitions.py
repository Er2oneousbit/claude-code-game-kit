#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_transitions.py
# Purpose : screen transitions drawn in code, the rule-image way 16-bit era games and visual novels do them: a greyscale
#           image says when each pixel switches (black first, white last), and one threshold shader plays any of them
#           by tweening "progress" 0 -> 1. Kinds: fade, iris, diamond, wipe_left / right / up / down, blinds, spiral (the
#           battle swirl), dither, clock, blocks. Plus a screen mosaic shader (the classic pixelate-out).
# Usage   : pack spec "transitions": [{"name": "battle_swirl", "kind": "spiral"}, {"name": "door", "kind": "iris"},
#           {"name": "mosaic", "kind": "mosaic"}]   keys: size [w, h] (default 320 x 180: the game's screen),
#           cell (block size of blinds / blocks / dither, default 8; diamond 16), steps (grey levels, default 32),
#           arms / turns (spiral: arm count, default 3, and winding, default 1.5), invert (play the other way round),
#           seed (blocks).
# Notes   : Godot: transition_<name>.tscn is a CanvasLayer with a full-screen ColorRect; tween
#           $Cover.material.set_shader_parameter("progress", 1.0) in, back to 0.0 out (color and smoothness are
#           uniforms too). The rule PNG works in any engine: cover a pixel when progress > its grey value / 255.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import numpy as np
from PIL import Image

import fcore as core
import godot

KINDS = ("fade", "iris", "diamond", "wipe_left", "wipe_right", "wipe_up", "wipe_down", "blinds", "spiral", "dither",
         "clock", "blocks", "mosaic")

RULE_SHADER = """shader_type canvas_item;
// Dotwork transition: a rule image says when each pixel is covered (black first, white last). Tween progress 0 -> 1.
uniform sampler2D rule : filter_nearest;
uniform float progress : hint_range(0.0, 1.0) = 0.0;
uniform float smoothness : hint_range(0.0, 0.5) = 0.0;
uniform vec4 color : source_color = vec4(0.0, 0.0, 0.0, 1.0);
uniform bool invert = false;

void fragment() {
	float r = texture(rule, UV).r;
	if (invert) {
		r = 1.0 - r;
	}
	// progress 0.0 covers nothing and 1.0 everything, with or without a soft edge; an all-black rule with
	// smoothness 1.0 is a plain linear fade
	float a = smoothness > 0.0 ? clamp((progress - r * (1.0 - smoothness)) / smoothness, 0.0, 1.0)
			: (progress >= 1.0 ? 1.0 : step(0.0001, progress) * step(r, progress));
	COLOR = vec4(color.rgb, color.a * a);
}
"""

MOSAIC_SHADER = """shader_type canvas_item;
// Dotwork mosaic: pixelates whatever is drawn below this rect. Tween cell 1 -> 32 out, 32 -> 1 in.
uniform sampler2D screen : hint_screen_texture, filter_nearest;
uniform float cell : hint_range(1.0, 64.0) = 1.0;

void fragment() {
	vec2 size = SCREEN_PIXEL_SIZE * floor(cell);
	COLOR = texture(screen, (floor(SCREEN_UV / size) + 0.5) * size);
}
"""


def bayer(n):
    """n x n ordered-dither matrix (n a power of two), values 0..1."""
    m = np.array([[0]])
    while m.shape[0] < n:
        m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
    return (m + 0.5) / m.size


def rule(kind, w, h, cell=8, turns=1.5, seed=1, arms=3):
    """A 0..1 float field: the progress at which each screen pixel is covered."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    cx, cy = (w - 1) / 2, (h - 1) / 2
    r = np.hypot(xx - cx, yy - cy) / np.hypot(cx, cy)
    if kind == "fade":   # all black: with smoothness 1.0 the shader's cover is simply progress
        return np.zeros((h, w))
    if kind == "iris":   # closes in from the edges onto the centre
        return 1 - r
    if kind == "wipe_left":   # the cover enters from the right edge and moves left
        return 1 - xx / (w - 1)
    if kind == "wipe_right":
        return xx / (w - 1)
    if kind == "wipe_up":
        return 1 - yy / (h - 1)
    if kind == "wipe_down":
        return yy / (h - 1)
    if kind == "blinds":   # every band of `cell` rows closes top to bottom, bands a little staggered down the screen
        return ((yy % cell) / cell) * 0.8 + (yy / (h - 1)) * 0.2
    if kind == "diamond":   # diamonds grow in every cell, sweeping left to right
        lx, ly = (xx % cell) - (cell - 1) / 2, (yy % cell) - (cell - 1) / 2
        local = (np.abs(lx) + np.abs(ly)) / (cell - 1)
        return local * 0.5 + (xx // cell * cell) / (w - 1) * 0.5
    if kind == "spiral":   # curved arms wind out from the centre and thicken until they meet: the battle swirl
        ang = (np.arctan2(yy - cy, xx - cx) / (2 * np.pi)) % 1.0
        return 0.45 * r + 0.55 * ((arms * ang + turns * r) % 1.0)
    if kind == "clock":   # a hand sweeps clockwise from twelve o'clock
        return (np.arctan2(xx - cx, -(yy - cy)) / (2 * np.pi)) % 1.0
    if kind == "dither":   # an ordered dissolve in chunky blocks
        b = bayer(4)
        size = max(1, cell // 4)
        return b[(yy // size).astype(int) % 4, (xx // size).astype(int) % 4]
    if kind == "blocks":   # cells switch in a fixed random order
        gw, gh = -(-w // cell), -(-h // cell)
        order = np.random.default_rng(seed).permutation(gw * gh).reshape(gh, gw) / max(1, gw * gh - 1)
        return order[(yy // cell).astype(int), (xx // cell).astype(int)]
    raise core.ToolError(f"transition kind {kind!r}: one of {', '.join(KINDS)}")


def to_png(field, steps=32):
    """Grey levels cut to `steps` flat bands (a pixel-art wipe moves in visible steps, not a smooth gradient)."""
    f = np.clip(field, 0, 1)
    if steps:
        f = np.floor(f * steps).clip(0, steps - 1) / max(1, steps - 1)
    return Image.fromarray(np.round(f * 255).astype(np.uint8), "L")


def scene(path, node, shader_res, params, rule_res=None):
    """CanvasLayer (layer 100) > ColorRect "Cover", full screen, mouse ignored, with the shader material."""
    ext = [f'[ext_resource type="Shader" path="{shader_res}" id="1_sh"]']
    if rule_res:
        ext.append(f'[ext_resource type="Texture2D" path="{rule_res}" id="2_rule"]')
    mat = ['[sub_resource type="ShaderMaterial" id="ShaderMaterial_1"]', 'shader = ExtResource("1_sh")']
    if rule_res:
        mat.append('shader_parameter/rule = ExtResource("2_rule")')
    mat += [f"shader_parameter/{k} = {v}" for k, v in params.items()]
    text = "\n".join([f'[gd_scene load_steps={len(ext) + 2} format=3]', "", *ext, "", *mat, "",
                      f'[node name="{node}" type="CanvasLayer"]', "layer = 100", "",
                      '[node name="Cover" type="ColorRect" parent="."]', 'material = SubResource("ShaderMaterial_1")',
                      "anchors_preset = 15", "anchor_right = 1.0", "anchor_bottom = 1.0", "grow_horizontal = 2",
                      "grow_vertical = 2", "mouse_filter = 2", ""])
    return godot._write(path, text)


def preview(png, kind, out, steps=(0.2, 0.45, 0.7, 0.95)):
    """Review strip: the transition at a few progress values over a checker 'screen' (cover drawn dark)."""
    f = np.asarray(png, np.float64) / 255
    h, w = f.shape
    yy, xx = np.mgrid[0:h, 0:w]
    screen = np.where(((yy // 16) + (xx // 16)) % 2 == 0, 150, 110).astype(np.uint8)
    tiles = []
    for p in steps:
        cover = (f < p) if kind != "fade" else np.full(f.shape, False)
        img = np.dstack([screen] * 3).copy()
        if kind == "fade":
            img = (img * (1 - p)).astype(np.uint8)
        img[cover] = (14, 12, 20)
        tiles.append(img)
    pad = np.full((h, 4, 3), 58, np.uint8)
    strip = np.concatenate(sum([[t, pad] for t in tiles], [])[:-1], axis=1)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    Image.fromarray(strip).save(out)
    return out


def run(entries, pack, man, conf):
    art = core.art(conf, "ui", "transitions")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/ui/transitions'
    rows = []
    for e in entries:
        name, kind = core.snake(e["name"]), e.get("kind", "fade")
        if kind not in KINDS:
            raise core.ToolError(f"transition {name}: kind {kind!r} is not one of {', '.join(KINDS)}")
        node = "Transition" + name.title().replace("_", "")
        if kind == "mosaic":
            sp = godot._write(os.path.join(art, "shaders", "mosaic.gdshader"), MOSAIC_SHADER)
            man.add(sp, "shader", uniforms=["cell"], workflow="Dotwork transitions (written in code)",
                    usage="tween shader_parameter/cell 1 -> 32 (out) / 32 -> 1 (in)")
            scn = scene(os.path.join(art, f"transition_{name}.tscn"), node, f"{res}/shaders/mosaic.gdshader",
                        {"cell": "1.0"})
            man.add(scn, "scene", node="CanvasLayer > ColorRect (screen mosaic)")
            if not godot.ENABLED:
                core.log(f"transition {name}: skipped the scene (--engine none: mosaic is a screen shader)")
            continue
        size = e.get("size", [320, 180])
        w, h = int(size[0]), int(size[1])
        cell = int(e.get("cell", 16 if kind == "diamond" else 8))   # 16 px diamonds read as diamonds at 1x
        if not (8 <= w <= 4096 and 8 <= h <= 4096) or not 2 <= cell <= min(w, h):   # a 1 px side made NaN rules
            raise core.ToolError(f"transition {name}: size {w}x{h} needs both sides 8 .. 4096 px and cell 2 .. "
                                 f"{min(w, h)}, not {cell}")
        field = rule(kind, w, h, cell, float(e.get("turns", 1.5)), core.seed_of(e, 9700), int(e.get("arms", 3)))
        if e.get("invert"):
            field = 1 - field
        png = to_png(field, int(e.get("steps", 32)) if kind not in ("fade", "dither", "blocks") else 0)
        dst = core.save_clean(png, os.path.join(art, f"rule_{name}.png"))
        man.add(dst, "transition_rule", transition=kind, size=[w, h], workflow="Dotwork transitions (drawn in code)",
                usage="cover a pixel once progress > grey / 255 (black first, white last)")
        sp = godot._write(os.path.join(art, "shaders", "transition_rule.gdshader"), RULE_SHADER)
        man.add(sp, "shader", uniforms=["rule", "progress", "smoothness", "color", "invert"],
                workflow="Dotwork transitions (written in code)")
        params = {"progress": "0.0", "smoothness": "1.0" if kind == "fade" else "0.0", "color": "Color(0, 0, 0, 1)",
                  "invert": "false"}
        scn = scene(os.path.join(art, f"transition_{name}.tscn"), node, f"{res}/shaders/transition_rule.gdshader",
                    params, f"{res}/rule_{name}.png")
        man.add(scn, "scene", node="CanvasLayer > ColorRect (rule transition)",
                usage='tween $Cover.material.set_shader_parameter("progress", 1.0)')
        rows.append((name, preview(png, kind, os.path.join(core.WORK, "transitions", f"{name}_preview.png"))))
        core.log(f"transition {name}: {kind} {w}x{h}")
    if rows:
        _sheet(rows, core.src(conf, "art", "ui", "transitions_review.png"))


def _sheet(rows, out):
    ims = [Image.open(p) for _, p in rows]
    W, H = max(i.width for i in ims), sum(i.height + 4 for i in ims)
    s = Image.new("RGB", (W, H), (58, 58, 68))
    y = 0
    for im in ims:
        s.paste(im, (0, y))
        y += im.height + 4
    os.makedirs(os.path.dirname(out), exist_ok=True)
    s.save(out)
    return out
