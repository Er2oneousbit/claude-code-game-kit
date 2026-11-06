#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# shader_ref.py
# Purpose : The reference for the kit's shader recipes (tools/shaders/recipes.json): writes the test inputs, renders
#           each effect in plain Python into data/golden/shaders/<name>.png, and compares an engine's renders with
#           those golden images. Every engine port renders the same 64x64 check images; this is the yardstick.
# Usage   : python tools/shaders/shader_ref.py list
#           python tools/shaders/shader_ref.py golden            # are the inputs and golden images current? (exit 1 if not)
#           python tools/shaders/shader_ref.py golden --write    # rewrite them (after changing a recipe)
#           python tools/shaders/shader_ref.py render vignette --out build/v.png
#           python tools/shaders/shader_ref.py compare build/shader_check   # an engine's renders vs the golden images
# Exit    : 0 ok, 1 a render differs or a golden image is stale, 2 usage or missing files
# Notes   : Standard library only (PNG reading and writing from tools/image_diff.py). Image space: origin top-left,
#           x right, y down, pixel centres at +0.5; inputs sampled nearest-neighbour, clamped unless a recipe wraps.
#           Colours are 8-bit inputs read as byte / 255 (what a GPU's unorm texture gives) and written back rounded.
#           A pixel whose sprite texel is clear is written (0, 0, 0, 0) by every sprite effect, so engines that store
#           colour under zero alpha still match. Tolerances are per recipe: GPUs round sin, pow and normalize
#           differently, so the surface and lighting recipes allow a small share of pixels past the tolerance.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   inputs  : deterministic little images (a sprite, its index and normal maps, a palette, noise, a scene, a sphere's
#             normal map, a tile) built from integer arithmetic only
#   render  : for each pixel of the 64x64 canvas, uv = (x + 0.5, y + 0.5) / 64 -> the recipe's function -> RGBA
#   golden  : render every recipe; --write saves them, otherwise compare with the files on disk (stale = exit 1)
#   compare : <dir>/<name>.png against data/golden/shaders/<name>.png: channels further apart than the recipe's
#             tolerance, as a share of the pixels, must not exceed max_share
import argparse
import json
import math
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                                  # the project root (tools/shaders/ -> ..)
sys.path.insert(0, str(HERE.parent))
import image_diff  # noqa: E402  (stdlib PNG reader and writer)

RECIPES = HERE / "recipes.json"
GOLDEN_DIR = ROOT / "data" / "golden" / "shaders"
SPRITE = 32                                             # sprite-size inputs (sprite, indexed, noise, normals, tile)
DEBUG = False


class ToolError(Exception):
    """Exit 2: usage or missing files."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}")


# ---- inputs: built from integer arithmetic only, so they are the same bytes everywhere ----------------------------
def _clamp_byte(v):
    return max(0, min(255, int(v)))


def _in_body(x, y):
    """The test sprite's shape: a round body (centre 16, 17, radius 11) and two ears."""
    dx, dy = 2 * x + 1 - 32, 2 * y + 1 - 34            # doubled pixel-centre offsets: integer maths
    if dx * dx + dy * dy <= 22 * 22:
        return True
    return (6 <= x <= 9 and 3 <= y <= 8) or (22 <= x <= 25 and 3 <= y <= 8)


def _sprite_index(x, y):
    """0 clear, 1 body, 2 belly, 3 eyes, 4 belt."""
    if not _in_body(x, y):
        return 0
    if y in (11, 12) and x in (12, 13, 19, 20):
        return 3
    if y == 20:
        return 4
    dx, dy = 2 * x + 1 - 32, 2 * y + 1 - 40
    if dx * dx + dy * dy <= 12 * 12:
        return 2
    return 1


PALETTE_SRC = [(0, 0, 0), (214, 140, 64), (240, 214, 170), (24, 20, 36), (120, 60, 160)]   # what sprite.png shows
PALETTE_SWAP = [(0, 0, 0), (70, 130, 210), (200, 225, 245), (24, 20, 36), (230, 70, 60), (0, 200, 120),
                (255, 255, 0), (255, 0, 255), (90, 90, 90), (10, 120, 10), (120, 10, 10), (10, 10, 120),
                (200, 200, 200), (60, 30, 0), (0, 60, 60), (255, 128, 0)]


def _hash(x, y):
    """A small integer hash (no floating point): the noise texture's order."""
    h = (x * 374761393 + y * 668265263) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return h ^ (h >> 16)


def build_inputs():
    """{name: (width, height, rows)} of every input image (rows of RGBA bytes)."""
    def img(w, h, fn):
        return w, h, [bytearray(b for x in range(w) for b in fn(x, y)) for y in range(h)]

    def sprite(x, y):
        i = _sprite_index(x, y)
        return (0, 0, 0, 0) if i == 0 else PALETTE_SRC[i] + (255,)

    def indexed(x, y):
        i = _sprite_index(x, y)
        return (0, 0, 0, 0) if i == 0 else (i * 16, 0, 0, 255)

    def noise(x, y):
        k = _hash(x, y) % 16                            # (k + 0.5) / 16: never on a threshold of 1/16 steps
        v = _clamp_byte(round((k + 0.5) / 16 * 255))
        return (v, v, v, 255)

    def scene(x, y):
        r, g, b = x * 4, y * 4, 128 + ((x + y) % 32) * 4
        if 8 <= x < 24 and 8 <= y < 24:
            r, g, b = 220, 40, 40                       # a red block and a green one: what colour-blind modes shift
        elif 40 <= x < 56 and 8 <= y < 24:
            r, g, b = 40, 200, 60
        elif 24 <= x < 40 and 40 <= y < 56:
            r, g, b = 40, 80, 220
        return (_clamp_byte(r), _clamp_byte(g), _clamp_byte(b), 255)

    def sphere(x, y):
        sx, sy = (2 * x + 1) / 64 - 1, (2 * y + 1) / 64 - 1
        d2 = sx * sx + sy * sy
        if d2 >= 0.9025:                                # radius 0.95
            return (128, 128, 255, 0)
        nx, ny = sx / 0.95, sy / 0.95
        nz = math.sqrt(max(0.0, 1 - nx * nx - ny * ny))
        return tuple(_clamp_byte(round((c * 0.5 + 0.5) * 255)) for c in (nx, ny, nz)) + (255,)

    def tile(x, y):
        if (x // 4 + y // 4) % 2 == 0:
            base = (60, 120, 200)
        else:
            base = (230, 230, 210)
        if (x + y) % 8 == 0:
            base = (20, 40, 90)                         # a diagonal stripe: shows direction and wrapping
        return base + (255,)

    def sprite_normal(x, y):
        if not _in_body(x, y):
            return (128, 128, 255, 0)
        nx, ny = (x + 0.5 - 16) / 13, (y + 0.5 - 17) / 13
        d2 = min(nx * nx + ny * ny, 0.98)
        nz = math.sqrt(1 - d2)
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        return tuple(_clamp_byte(round((c / length * 0.5 + 0.5) * 255)) for c in (nx, ny, nz)) + (255,)

    return {
        "sprite": img(SPRITE, SPRITE, sprite), "indexed": img(SPRITE, SPRITE, indexed),
        "palette": img(16, 1, lambda x, y: PALETTE_SWAP[x] + (255,)), "noise": img(SPRITE, SPRITE, noise),
        "scene": img(64, 64, scene), "sphere": img(64, 64, sphere), "tile": img(SPRITE, SPRITE, tile),
        "sprite_normal": img(SPRITE, SPRITE, sprite_normal),
    }


# ---- sampling and maths as GLSL has them ----------------------------------------------------------------------------
def texel(image, u, v, wrap=False):
    """RGBA floats (byte / 255) of the texel at uv, nearest-neighbour; clamped to the edge, or wrapped."""
    w, h, rows = image
    if wrap:
        u, v = u - math.floor(u), v - math.floor(v)
    x = min(w - 1, max(0, int(math.floor(u * w))))
    y = min(h - 1, max(0, int(math.floor(v * h))))
    p = rows[y][x * 4:x * 4 + 4]
    return [c / 255 for c in p]


def smoothstep(e0, e1, x):
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def normalize(v):
    length = math.sqrt(sum(c * c for c in v)) or 1.0
    return [c / length for c in v]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def clamp01(v):
    return min(1.0, max(0.0, v))


CLEAR = [0.0, 0.0, 0.0, 0.0]


# ---- the recipes (one function each: uv -> RGBA) ---------------------------------------------------------------------
def fx_flash(uv, p, inp):
    c = texel(inp["sprite"], *uv)
    if c[3] < 0.5:
        return CLEAR
    a = p["amount"]
    return [c[i] * (1 - a) + p["flash_color"][i] * a for i in range(3)] + [c[3]]


def fx_dissolve(uv, p, inp):
    c = texel(inp["sprite"], *uv)
    if c[3] < 0.5:
        return CLEAR
    n = texel(inp["noise"], *uv)[0]
    if n < p["progress"]:
        return CLEAR
    if n < p["progress"] + p["edge_width"]:
        return list(p["edge_color"]) + [c[3]]
    return c


def fx_outline(uv, p, inp):
    c = texel(inp["sprite"], *uv)
    if c[3] >= 0.5:
        return c
    step = 1 / SPRITE
    for du, dv in ((step, 0), (-step, 0), (0, step), (0, -step)):
        u, v = uv[0] + du, uv[1] + dv
        if 0 <= u <= 1 and 0 <= v <= 1 and texel(inp["sprite"], u, v)[3] >= 0.5:
            return list(p["outline_color"]) + [1.0]
    return CLEAR


def fx_palette_swap(uv, p, inp):
    c = texel(inp["indexed"], *uv)
    if c[3] < 0.5:
        return CLEAR
    index = math.floor(c[0] * 255 / 16 + 0.5)
    return texel(inp["palette"], (index + 0.5) / 16, 0.5)[:3] + [1.0]


RGB_TO_LMS = [[17.8824, 43.5161, 4.11935], [3.45565, 27.1554, 3.86714], [0.0299566, 0.184309, 1.46709]]
LMS_TO_RGB = [[0.0809444479, -0.130504409, 0.116721066], [-0.0102485335, 0.0540193266, -0.113614708],
              [-0.000365296938, -0.00412161469, 0.693511405]]


def fx_colorblind(uv, p, inp):
    c = texel(inp["scene"], *uv)[:3]
    lms = [dot(row, c) for row in RGB_TO_LMS]
    sim = list(lms)
    mode = p["mode"]
    if mode == 1:
        sim[0] = 2.02344 * lms[1] - 2.52581 * lms[2]
    elif mode == 2:
        sim[1] = 0.494207 * lms[0] + 1.24827 * lms[2]
    elif mode == 3:
        sim[2] = -0.395913 * lms[0] + 0.801109 * lms[1]
    back = [dot(row, sim) for row in LMS_TO_RGB]
    err = [c[i] - back[i] for i in range(3)]
    shift = [0.0, 0.7 * err[0] + err[1], 0.7 * err[0] + err[2]]
    return [clamp01(c[i] + shift[i]) for i in range(3)] + [1.0]


def fx_crt(uv, p, inp):
    c = texel(inp["scene"], *uv)
    row = int(math.floor(uv[1] * 64))
    k = 1 - p["scanline"] if row % 2 == 1 else 1.0
    return [c[i] * k for i in range(3)] + [1.0]


def fx_vignette(uv, p, inp):
    c = texel(inp["scene"], *uv)
    d = math.sqrt((uv[0] - 0.5) ** 2 + (uv[1] - 0.5) ** 2) / 0.70710678
    f = 1 - p["strength"] * smoothstep(p["radius"], 1.0, d)
    return [c[i] * f for i in range(3)] + [1.0]


def fx_toon_rim(uv, p, inp):
    s = texel(inp["sphere"], *uv)
    if s[3] < 0.5:
        return CLEAR
    n = normalize([c * 2 - 1 for c in s[:3]])
    ndl = dot(n, normalize(p["light_dir"]))
    band = 1.0 if ndl > 0.5 else 0.6 if ndl > 0.0 else 0.3
    rim = smoothstep(0.55, 0.75, 1 - n[2]) * p["rim_strength"]
    return [clamp01(p["albedo"][i] * band + rim) for i in range(3)] + [1.0]


def fx_scroll_water(uv, p, inp):
    t, (sx, sy), amp, freq = p["time"], p["speed"], p["amplitude"], p["frequency"]
    u = uv[0] * 2 + t * sx
    v = uv[1] * 2 + t * sy + amp * math.sin(6.2831853 * (uv[0] * freq + t))
    return texel(inp["tile"], u, v, wrap=True)[:3] + [1.0]


def fx_triplanar(uv, p, inp):
    s = texel(inp["sphere"], *uv)
    if s[3] < 0.5:
        return CLEAR
    n = normalize([c * 2 - 1 for c in s[:3]])
    px, py = uv[0] * 2 - 1, uv[1] * 2 - 1
    pz = math.sqrt(max(0.0, 1 - px * px - py * py))
    w = [abs(c) ** p["sharpness"] for c in n]
    total = sum(w) or 1.0
    w = [c / total for c in w]
    k = p["scale"]
    tx = texel(inp["tile"], py * k, pz * k, wrap=True)
    ty = texel(inp["tile"], px * k, pz * k, wrap=True)
    tz = texel(inp["tile"], px * k, py * k, wrap=True)
    return [clamp01(w[0] * tx[i] + w[1] * ty[i] + w[2] * tz[i]) for i in range(3)] + [1.0]


def fx_sprite_light(uv, p, inp):
    albedo = texel(inp["sprite"], *uv)
    if albedo[3] < 0.5:
        return CLEAR
    n = normalize([c * 2 - 1 for c in texel(inp["sprite_normal"], *uv)[:3]])
    fx, fy = uv[0] * 64, uv[1] * 64
    lx, ly = p["light_pos"]
    light = normalize([lx - fx, ly - fy, p["light_height"]])
    diff = max(dot(n, light), 0.0)
    return [clamp01(albedo[i] * (p["ambient"] + diff * p["light_color"][i])) for i in range(3)] + [1.0]


EFFECTS = {"flash": fx_flash, "dissolve": fx_dissolve, "outline": fx_outline, "palette_swap": fx_palette_swap,
           "colorblind": fx_colorblind, "crt": fx_crt, "vignette": fx_vignette, "toon_rim": fx_toon_rim,
           "scroll_water": fx_scroll_water, "triplanar": fx_triplanar, "sprite_light": fx_sprite_light}


# ---- rendering and comparing ------------------------------------------------------------------------------------------
def load_recipes():
    try:
        data = json.loads(RECIPES.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolError(f"cannot read {RECIPES}: {exc}")
    missing = sorted(set(data["recipes"]) - set(EFFECTS))
    if missing:
        raise ToolError(f"recipes without a reference function: {', '.join(missing)}")
    return data


def render(name, data=None, inputs=None):
    """(width, height, rows) of one recipe's check image."""
    data = data or load_recipes()
    inputs = inputs or build_inputs()
    recipe = data["recipes"][name]
    w, h = data["canvas"]
    fn = EFFECTS[name]
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            rgba = fn(((x + 0.5) / w, (y + 0.5) / h), recipe["params"], inputs)
            row += bytes(_clamp_byte(round(clamp01(c) * 255)) for c in rgba)
        rows.append(row)
    return w, h, rows


def differences(got, want, tolerance):
    """How many pixels have a channel further than tolerance from the other image, and the largest difference."""
    (gw, gh, grows), (ww, wh, wrows) = got, want
    if (gw, gh) != (ww, wh):
        raise ToolError(f"size {gw}x{gh}, expected {ww}x{wh}")
    bad, worst = 0, 0
    for a, b in zip(grows, wrows):
        for x in range(0, len(a), 4):
            d = max(abs(a[x + i] - b[x + i]) for i in range(4))
            worst = max(worst, d)
            bad += d > tolerance
    return bad, worst


def input_files(data):
    return {name: ROOT / rel for name, rel in data["inputs"].items()}


def cmd_list(args):
    data = load_recipes()
    for name, r in data["recipes"].items():
        print(f"{name:13s} {r['group']:9s} {r['summary']}")
    return 0


def cmd_golden(args):
    """Check (or with --write, rewrite) the input images and the golden renders."""
    data = load_recipes()
    inputs = build_inputs()
    stale = []
    targets = [(path, inputs[name]) for name, path in input_files(data).items()]
    targets += [(GOLDEN_DIR / f"{name}.png", render(name, data, inputs)) for name in data["recipes"]]
    for path, (w, h, rows) in targets:
        if args.write:
            image_diff.write_png(path, w, h, rows)
            continue
        try:
            have = image_diff.read_png(path)
        except (OSError, image_diff.ImageError) as exc:
            stale.append(f"{path.relative_to(ROOT).as_posix()}: {exc}")
            continue
        if have[0] != w or have[1] != h or any(bytes(a) != bytes(b) for a, b in zip(have[2], rows)):
            stale.append(path.relative_to(ROOT).as_posix())
    if args.write:
        print(f"[ OK ] wrote {len(targets)} images (inputs and golden renders)")
        return 0
    for s in stale:
        print(f"[FAIL] stale: {s} (run with --write after changing a recipe)")
    if not stale:
        print(f"[ OK ] {len(targets)} input and golden images are current")
    return 1 if stale else 0


def cmd_render(args):
    data = load_recipes()
    if args.name not in data["recipes"]:
        raise ToolError(f"no recipe {args.name!r} (list shows them)")
    w, h, rows = render(args.name, data)
    image_diff.write_png(Path(args.out), w, h, rows)
    print(f"[ OK ] {args.out}")
    return 0


def cmd_compare(args):
    """Each <dir>/<name>.png against its golden image, within the recipe's tolerance."""
    data = load_recipes()
    folder = Path(args.dir)
    names = args.only or list(data["recipes"])
    failed, missing = [], []
    for name in names:
        if name not in data["recipes"]:
            raise ToolError(f"no recipe {name!r}")
        recipe = data["recipes"][name]
        got_path = folder / f"{name}.png"
        if not got_path.is_file():
            missing.append(name)
            print(f"[FAIL] {name}: no render at {got_path.as_posix()}")
            continue
        try:
            got = image_diff.read_png(got_path)
            want = image_diff.read_png(GOLDEN_DIR / f"{name}.png")
            bad, worst = differences(got, want, recipe["tolerance"])
        except (OSError, image_diff.ImageError, ToolError) as exc:
            failed.append(name)
            print(f"[FAIL] {name}: {exc}")
            continue
        share = bad / (got[0] * got[1])
        ok = share <= recipe["max_share"]
        print(f"[{' OK ' if ok else 'FAIL'}] {name}: {bad} pixel(s) past {recipe['tolerance']} "
              f"({share:.1%}, allowed {recipe['max_share']:.0%}), largest difference {worst}")
        if not ok:
            failed.append(name)
    if failed or missing:
        print(f"[FAIL] {len(failed) + len(missing)} of {len(names)} effect(s) differ from the reference")
        return 1
    print(f"[ OK ] all {len(names)} effect(s) match the reference")
    return 0


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="The reference renderer and golden images of the kit's shader recipes.",
                                 epilog="Exit codes: 0 ok, 1 a render differs or a golden image is stale, 2 usage.")
    ap.add_argument("--debug", action="store_true", help="tracebacks on errors")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="the recipes").set_defaults(fn=cmd_list)
    p = sub.add_parser("golden", help="check the inputs and golden images are current (--write rewrites them)")
    p.add_argument("--write", action="store_true")
    p.set_defaults(fn=cmd_golden)
    p = sub.add_parser("render", help="render one recipe's check image")
    p.add_argument("name")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_render)
    p = sub.add_parser("compare", help="an engine's renders (<dir>/<name>.png) against the golden images")
    p.add_argument("dir")
    p.add_argument("--only", nargs="*", help="these recipes only")
    p.set_defaults(fn=cmd_compare)
    args = ap.parse_args(argv)
    DEBUG = args.debug
    try:
        return args.fn(args)
    except ToolError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:   # noqa: BLE001 - last resort, traceback with --debug
        print(f"[error] unexpected failure: {exc!r}. Re-run with --debug.", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
