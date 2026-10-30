#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_weather.py
# Purpose : weather overlays drawn in code: seamless pixel-art tiles (rain streaks, snowflakes, fog, ash, embers,
#           leaves, blowing sand) in near and far layers, scrolled across the screen by one shader that keeps them on
#           the art-pixel grid. Colours snap to the environment palette.
# Usage   : pack spec "weather": [{"name": "storm", "kind": "rain", "intensity": 0.8}, {"name": "snow", "kind": "snow"}]
#           keys: kind (rain / snow / fog / ash / embers / leaves / sand), intensity (0.2 .. 1.0, default 0.6: how many
#           drops, flakes or how thick the fog), tile (px, default 128; fog and sand 256), speed (multiplier, default 1.0),
#           pixel_scale (screen pixels per art pixel, default 1; 2 on a game that renders at 2x), seed.
# Notes   : Godot: weather_<name>.tscn is a CanvasLayer with one full-screen ColorRect per layer; add it to a map scene
#           (hide it or free it to stop the weather). Other engines: scroll each tile PNG at the velocity in the manifest
#           (px / s), rounding the offset to whole pixels.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import numpy as np
from PIL import Image

import fcore as core
import godot
from engine import load_hex, oklab

SHADER = """shader_type canvas_item;
// Dotwork weather layer: scrolls a seamless pixel tile across the screen, snapped to whole art pixels.
uniform sampler2D tile : filter_nearest, repeat_enable;
uniform vec2 velocity = vec2(0.0, 120.0);   // art pixels per second
uniform float wobble = 0.0;                 // sideways sway in art pixels (snow, leaves)
uniform float wobble_speed = 1.5;
uniform float pixel_scale = 1.0;            // screen pixels per art pixel
uniform vec4 tint : source_color = vec4(1.0, 1.0, 1.0, 1.0);

void fragment() {
	vec2 px = SCREEN_UV / SCREEN_PIXEL_SIZE / pixel_scale;
	vec2 off = velocity * TIME;
	off.x += sin(TIME * wobble_speed + floor(px.y / 16.0)) * wobble;
	vec2 p = floor(px - off);
	COLOR = texture(tile, (p + 0.5) / vec2(textureSize(tile, 0))) * tint;
}
"""
KINDS = ("rain", "snow", "fog", "ash", "embers", "leaves", "sand")


class Painter:
    """A seamless RGBA tile: every dot wraps around the edges."""

    def __init__(self, n, pal):
        self.n, self.pal = n, pal
        self.a = np.zeros((n, n, 4), np.uint8)

    def colour(self, hexrgb):
        """The environment palette colour nearest to a hex hint."""
        c = np.array([[int(hexrgb[i:i + 2], 16) for i in (0, 2, 4)]], np.uint8)
        return self.pal[np.argmin(((oklab(self.pal) - oklab(c)) ** 2).sum(-1))]

    def dot(self, x, y, rgb, alpha=255):
        x, y = int(round(x)) % self.n, int(round(y)) % self.n
        self.a[y, x, :3] = rgb
        self.a[y, x, 3] = max(int(self.a[y, x, 3]), int(alpha))


def streaks(p, rng, count, length, slant, rgb, alpha, head=None):
    """Rain: straight 1 px streaks along (slant, 1), a brighter head pixel at the bottom."""
    for _ in range(count):
        x, y = rng.uniform(0, p.n), rng.uniform(0, p.n)
        for k in range(length):
            p.dot(x + slant * k, y + k, rgb, alpha)
        if head is not None:
            p.dot(x + slant * length, y + length, head, 255)


def flakes(p, rng, count, rgbs, big=False):
    """Snow, ash, embers, leaves: single pixels, or small plus shapes / two-pixel leaves when big."""
    for _ in range(count):
        x, y = rng.uniform(0, p.n), rng.uniform(0, p.n)
        i = int(rng.integers(len(rgbs)))
        p.dot(x, y, rgbs[i])
        if big == "plus":
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                p.dot(x + dx, y + dy, rgbs[i], 170)
        elif big == "leaf":   # two pixels and a darker tip that leans either way
            p.dot(x + 1, y, rgbs[i])
            p.dot(x + rng.choice([-1, 2]), y + 1, rgbs[(i + 1) % len(rgbs)])


def value_noise(n, cells, rng):
    """Tileable smooth noise: a periodic lattice of random values, cosine-interpolated."""
    g = rng.random((cells, cells))
    t = np.arange(n) / n * cells
    i0 = np.floor(t).astype(int)
    f = (1 - np.cos((t - i0) * np.pi)) / 2
    i1 = (i0 + 1) % cells
    a = g[np.ix_(i0, i0)] * (1 - f)[None, :] + g[np.ix_(i0, i1)] * f[None, :]
    b = g[np.ix_(i1, i0)] * (1 - f)[None, :] + g[np.ix_(i1, i1)] * f[None, :]
    return a * (1 - f)[:, None] + b * f[:, None]


def haze(p, rng, rgb, thickness, cells=4):
    """Fog / dust: three octaves of tileable noise cut to 3 levels (a light veil, its checker-dithered edge, nothing),
    so it reads as drifting banks rather than blobs. thickness 0.2 .. 1.0 widens the banks."""
    v = (value_noise(p.n, cells, rng) * 0.55 + value_noise(p.n, cells * 2, rng) * 0.3
         + value_noise(p.n, cells * 4, rng) * 0.15)
    yy, xx = np.mgrid[0:p.n, 0:p.n]
    checker = (xx + yy) % 2 == 0
    lo = 0.62 - 0.3 * thickness
    hi = lo + 0.14
    alpha = np.where(v > hi, 84, np.where((v > lo) & checker, 84, 0))
    p.a[..., :3] = rgb
    p.a[..., 3] = alpha.astype(np.uint8)


def layers(kind, n, pal, intensity, seed):
    """[(layer name, tile RGBA, velocity (x, y) px/s, wobble px)] far layer first."""
    rng = np.random.default_rng(seed)
    k = max(0.2, min(1.0, float(intensity)))
    out = []

    def new():
        return Painter(n, pal)
    if kind == "rain":
        for lname, cnt, ln, al, vel in (("far", 70, 4, 120, (-45, 300)), ("near", 34, 8, 190, (-70, 460))):
            p = new()
            streaks(p, rng, int(cnt * k * n * n / 16384), ln, vel[0] / vel[1], p.colour("a8c4dc"), al,
                    head=p.colour("e8f2fa") if lname == "near" else None)
            out.append((lname, p.a, vel, 0))
    elif kind == "snow":
        for lname, cnt, big, vel, wob in (("far", 60, False, (4, 22), 2), ("near", 22, "plus", (8, 40), 5)):
            p = new()
            flakes(p, rng, int(cnt * k * n * n / 16384), [p.colour("f4f8fc"), p.colour("d8e4f0")], big)
            out.append((lname, p.a, vel, wob))
    elif kind == "fog":
        for lname, cells, vel in (("far", 4, (6, 1)), ("near", 6, (12, 2))):
            p = new()
            haze(p, rng, p.colour("c8ccd4"), k * (0.7 if lname == "far" else 1.0), cells)
            out.append((lname, p.a, vel, 0))
    elif kind == "ash":
        for lname, cnt, vel, wob in (("far", 50, (3, 14), 2), ("near", 20, (6, 26), 4)):
            p = new()
            flakes(p, rng, int(cnt * k * n * n / 16384), [p.colour("8a8a90"), p.colour("5a5a62"), p.colour("b0b0b4")],
                   "plus" if lname == "near" else False)
            out.append((lname, p.a, vel, wob))
    elif kind == "embers":
        for lname, cnt, vel, wob in (("far", 26, (2, -18), 3), ("near", 12, (4, -34), 6)):
            p = new()
            flakes(p, rng, int(cnt * k * n * n / 16384), [p.colour("ffd060"), p.colour("f08a30"), p.colour("e04a20")])
            out.append((lname, p.a, vel, wob))
    elif kind == "leaves":
        for lname, cnt, vel, wob in (("far", 14, (14, 20), 4), ("near", 7, (26, 34), 8)):
            p = new()
            flakes(p, rng, int(cnt * k * n * n / 16384), [p.colour("6aa040"), p.colour("c8a030"), p.colour("c86a30")],
                   "leaf")
            out.append((lname, p.a, vel, wob))
    elif kind == "sand":
        p = new()
        haze(p, rng, p.colour("c8a878"), k * 0.8, 4)
        out.append(("haze", p.a, (70, 6), 0))
        p = new()
        streaks(p, rng, int(40 * k * n * n / 16384), 6, 0, p.colour("e0c898"), 170)
        p.a = np.ascontiguousarray(np.rot90(p.a, -1))   # streaks run sideways with the wind
        out.append(("near", p.a, (260, 18), 0))
    else:
        raise core.ToolError(f"weather kind {kind!r}: one of {', '.join(KINDS)}")
    return out


def scene(path, node, shader_res, rows, pixel_scale):
    """CanvasLayer (layer 50) with one full-screen ColorRect per weather layer."""
    ext = [f'[ext_resource type="Shader" path="{shader_res}" id="1_sh"]']
    subs, nodes = [], []
    for i, (lname, tex_res, vel, wob) in enumerate(rows, 2):
        ext.append(f'[ext_resource type="Texture2D" path="{tex_res}" id="{i}_{lname}"]')
        subs += [f'[sub_resource type="ShaderMaterial" id="ShaderMaterial_{lname}"]', 'shader = ExtResource("1_sh")',
                 f'shader_parameter/tile = ExtResource("{i}_{lname}")',
                 f"shader_parameter/velocity = Vector2({vel[0]}, {vel[1]})", f"shader_parameter/wobble = {float(wob)}",
                 "shader_parameter/wobble_speed = 1.5", f"shader_parameter/pixel_scale = {float(pixel_scale)}",
                 "shader_parameter/tint = Color(1, 1, 1, 1)", ""]
        nodes += [f'[node name="{lname.title()}" type="ColorRect" parent="."]',
                  f'material = SubResource("ShaderMaterial_{lname}")', "anchors_preset = 15", "anchor_right = 1.0",
                  "anchor_bottom = 1.0", "grow_horizontal = 2", "grow_vertical = 2", "mouse_filter = 2", ""]
    text = "\n".join([f'[gd_scene load_steps={len(ext) + len(rows) + 1} format=3]', "", *ext, "", *subs,
                      f'[node name="{node}" type="CanvasLayer"]', "layer = 50", "", *nodes])
    return godot._write(path, text)


def preview(tiles, out, w=320, h=180, t=0.4):
    """One still of the layers over a plain field, as the shader places them at time t (wobble left out)."""
    yy, xx = np.mgrid[0:h, 0:w]
    img = Image.fromarray(np.dstack([np.where(((yy // 32) + (xx // 32)) % 2 == 0, 96, 84)] * 3
                                    + [np.full((h, w), 255)]).astype(np.uint8))
    for a, vel in tiles:
        n = a.shape[0]
        ox, oy = int(np.floor(vel[0] * t)), int(np.floor(vel[1] * t))
        lay = a[(yy - oy) % n, (xx - ox) % n]
        img.alpha_composite(Image.fromarray(lay.astype(np.uint8)))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out)
    return out


def run(entries, pack, man, conf):
    art = core.art(conf, "fx", "weather")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/fx/weather'
    pal = load_hex(conf["fixed"]["env_palette"])
    shots = []
    for e in entries:
        name, kind = core.snake(e["name"]), e.get("kind", "rain")
        if kind not in KINDS:
            raise core.ToolError(f"weather {name}: kind {kind!r} is not one of {', '.join(KINDS)}")
        n = int(e.get("tile", 256 if kind in ("fog", "sand") else 128))   # banks of haze need room not to repeat
        if not 32 <= n <= 512:
            raise core.ToolError(f"weather {name}: tile {n} px is outside 32 .. 512")
        speed = float(e.get("speed", 1.0))
        rows, tiles = [], []
        for lname, a, vel, wob in layers(kind, n, pal, e.get("intensity", 0.6), core.seed_of(e, 9800)):
            vel = (round(vel[0] * speed, 1), round(vel[1] * speed, 1))
            fn = f"weather_{name}_{lname}.png"
            dst = core.save_clean(Image.fromarray(a), os.path.join(art, fn))
            man.add(dst, "weather_tile", weather=kind, layer=lname, tile=n, velocity_px_s=list(vel), wobble_px=wob,
                    workflow="Dotwork weather (drawn in code)", usage="scroll seamlessly at velocity, whole pixels")
            rows.append((lname, f"{res}/{fn}", vel, wob))
            tiles.append((a, vel))
        sp = godot._write(os.path.join(art, "weather.gdshader"), SHADER)
        man.add(sp, "shader", uniforms=["tile", "velocity", "wobble", "wobble_speed", "pixel_scale", "tint"],
                workflow="Dotwork weather (written in code)")
        scn = scene(os.path.join(art, f"weather_{name}.tscn"), "Weather" + name.title().replace("_", ""),
                    f"{res}/weather.gdshader", rows, e.get("pixel_scale", 1))
        man.add(scn, "scene", node="CanvasLayer > ColorRect per layer", layers=[r[0] for r in rows])
        shots.append(preview(tiles, os.path.join(core.WORK, "weather", f"{name}_preview.png")))
        core.log(f"weather {name}: {kind}, {len(rows)} layers, tile {n}")
    if shots:
        ims = [Image.open(p) for p in shots]
        cols = 2
        W, H = ims[0].width, ims[0].height
        sheet = Image.new("RGB", (cols * (W + 4), ((len(ims) + cols - 1) // cols) * (H + 4)), (58, 58, 68))
        for i, im in enumerate(ims):
            sheet.paste(im.convert("RGB"), ((i % cols) * (W + 4), (i // cols) * (H + 4)))
        out = core.src(conf, "art", "fx", "weather_review.png")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST).save(out)
