#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# pixel_sprite.py
# Purpose : Draw game characters and props as real pixel art IN CODE, so a game's very first build has figures a
#           player can read (a hero with a head, a scarf, a piston fist), never dots or plain shapes. A sprite is a
#           small Python file that paints rectangles and pixels on a 32x32 grid; this tool adds the automatic dark
#           outline and ground shadow, mirrors left-facing frames to right, packs every pose and direction into one
#           atlas PNG with a JSON layout, renders an upscaled preview, and checks the result against the kit's
#           first-art floor.
# Usage   : python tools/art/pixel_sprite.py build assets_src/sprites/hero.py --out <assets>/art/hero
#               writes hero.png (atlas), hero.json (layout) and hero_preview.png
#           python tools/art/pixel_sprite.py check <assets>/art/hero.png --cell 32
#           python tools/art/pixel_sprite.py example --out assets_src/sprites
#               copies the reference character (a steampunk piston-fist hero) to learn the technique from; a game's
#               own characters are new sprite files drawn from its GDD, and building the hero unchanged warns
#           Options: --overwrite, --preview-scale N (0 = no preview), --debug
# Exit    : 0 ok, 1 the check failed (a frame below the floor), 2 usage, missing file or a sprite file error
# Notes   : Standard library only (writes and reads PNG itself). A sprite file defines:
#             CELL (int, default 32), PALETTE ({name: (r, g, b)}), ROWS ([(pose, direction), ...] in atlas order),
#             FRAMES (frames per row, default 4), MIRROR (e.g. {"right": "left"}: right frames are mirrored left
#             frames), and draw(pose, direction, frame) returning a Sprite. Optional SHADOW = False, OUTLINE = False.
#           Sprite.rect(x0, y0, x1, y1, color) fills an inclusive rectangle and follows the body offset s.oy (for
#           idle bobbing and leaning); Sprite.dot(x, y, color) sets one pixel at an absolute position.
#           The first-art floor (check): in every frame the figure is at least FLOOR_HEIGHT of the cell tall, uses at
#           least FLOOR_COLORS distinct colors, covers at least FLOOR_FILL of the cell, and is ringed by a darker
#           outline. Dots, circles and single-color boxes fail it. Tune the numbers below if a game needs smaller
#           props, and say why in an ADR.
#           Phaser: this.load.spritesheet(key, png, {frameWidth: cell, frameHeight: cell}); a row's frames are
#           row * columns + 0..frames-1. Godot: an AtlasTexture or SpriteFrames region per cell.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5), generalizing a sprite script written with Claude
#           (Sonnet 5.5) and iterated by hand
# ---------------------------------------------------------------------------
#
# Pseudocode
#   build: import the sprite file -> for each (pose, direction) row and frame: draw() (or draw the mirrored source
#          direction and flip it) -> render (shadow, outline, pixels) -> paste into the atlas -> write PNG + JSON +
#          preview -> run the floor check on the result and print it
#   check: read the PNG -> split into cells -> per non-empty cell measure height, colors, fill, outline -> report
#   PNG I/O: write = filter 0 rows + zlib; read = unfilter all five filter types (8-bit gray/RGB/RGBA/palette)
import argparse
import importlib.util
import json
import shutil
import struct
import sys
import zlib
from pathlib import Path

DEBUG = False
DEFAULT_CELL = 32
DEFAULT_FRAMES = 4
SHADOW_ROWS = ((29, 10, 21, 70), (30, 12, 19, 70))   # (y, x0, x1, alpha) for a 32 px cell, scaled for others
OUTLINE_RGB = (27, 20, 16)
PREVIEW_BG = (24, 24, 28, 255)
PREVIEW_GAP = 2                                      # preview cells are separated by this many scaled pixels
FLOOR_HEIGHT = 0.55                                  # figure at least 55% of the cell tall
FLOOR_COLORS = 5                                     # at least 5 distinct opaque colors (outline + 2 shades + ...)
FLOOR_FILL = 0.12                                    # opaque pixels cover at least 12% of the cell
FLOOR_OUTLINE = 0.60                                 # at least 60% of the figure's edge pixels are darker outline
OUTLINE_LUM = 60                                     # an edge pixel this dark counts as outline even on a dark figure
MAX_PIXELS = 4096 * 4096                             # read_png refuses bigger images (a header can claim anything)
EXAMPLE = Path(__file__).resolve().parent / "sprites" / "example_hero.py"


class SpriteError(Exception):
    pass


# ---- the drawing surface sprite files use -------------------------------------------------------------------
class Sprite:
    """A sprite as {(x, y): (r, g, b)}. oy is a vertical body offset that rect() applies and dot() does not."""

    def __init__(self, palette, cell=DEFAULT_CELL):
        self.palette = palette
        self.cell = cell
        self.px = {}
        self.oy = 0

    def color(self, c):
        if isinstance(c, tuple):
            return c
        try:
            return tuple(self.palette[c])
        except KeyError:
            raise SpriteError(f"color {c!r} is not in PALETTE") from None

    def rect(self, x0, y0, x1, y1, c):
        """Fill an inclusive rectangle; follows the body offset."""
        rgb = self.color(c)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.px[(x, y + self.oy)] = rgb

    def dot(self, x, y, c):
        """Set one pixel at an absolute position (add s.oy yourself if it should move with the body)."""
        self.px[(x, y)] = self.color(c)


def render(sprite, outline=True, shadow=True):
    """Pixels -> RGBA grid (list of rows of 4-tuples): soft shadow, then outline, then the sprite on top."""
    n = sprite.cell
    grid = [[(0, 0, 0, 0)] * n for _ in range(n)]
    if shadow:
        k = n / DEFAULT_CELL
        for y, a, b, al in SHADOW_ROWS:
            yy = int(round(y * k))
            for x in range(int(round(a * k)), int(round(b * k)) + 1):
                if 0 <= yy < n and 0 <= x < n:
                    grid[yy][x] = (0, 0, 0, al)
    if outline:
        line = OUTLINE_RGB + (255,)
        for (x, y) in sprite.px:
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (nx, ny) not in sprite.px and 0 <= nx < n and 0 <= ny < n:
                    grid[ny][nx] = line
    for (x, y), c in sprite.px.items():
        if 0 <= x < n and 0 <= y < n:
            grid[y][x] = tuple(c) + (255,)
    return grid


def mirror(grid):
    return [list(reversed(row)) for row in grid]


# ---- PNG write and read (standard library) ---------------------------------------------------------------------
def png_bytes(grid):
    h, w = len(grid), len(grid[0])
    raw = bytearray()
    for row in grid:
        raw.append(0)
        for px in row:
            raw.extend(px)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def read_png(path):
    """8-bit, non-interlaced gray, RGB, RGBA, gray+alpha or palette PNG -> RGBA grid. A malformed or oversized
    file is a SpriteError (exit 2), never a crash or a runaway allocation."""
    try:
        return _read_png(path)
    except SpriteError:
        raise
    except (struct.error, zlib.error, IndexError, TypeError, ValueError, KeyError) as exc:
        raise SpriteError(f"{path} is not a readable PNG ({exc.__class__.__name__}: {exc})") from None


def _read_png(path):
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SpriteError(f"{path} is not a PNG")
    pos, idat, plte, trns = 8, b"", None, None
    w = h = depth = ctype = interlace = None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif tag == b"PLTE":
            plte = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif tag == b"tRNS":
            trns = body
        elif tag == b"IDAT":
            idat += body
    if depth != 8 or interlace != 0 or ctype not in (0, 2, 3, 4, 6):
        raise SpriteError(f"{path}: only 8-bit, non-interlaced PNGs are supported (depth {depth}, type {ctype})")
    if not w or not h or w * h > MAX_PIXELS:
        raise SpriteError(f"{path} is {w}x{h}: outside 1 to {MAX_PIXELS} pixels (a sprite atlas is far smaller)")
    if ctype == 3 and not plte:
        raise SpriteError(f"{path} is a palette PNG without a palette")
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    stride = w * bpp
    expected = h * (1 + stride)
    raw = zlib.decompressobj().decompress(idat, expected + 1)   # never inflate more than the header promises
    if len(raw) != expected:
        raise SpriteError(f"{path}: image data is {len(raw)} bytes, its header promises {expected}")
    rows, prev, i = [], bytearray(stride), 0
    for _ in range(h):
        ftype, line = raw[i], bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if ftype == 1:
                line[x] = (line[x] + a) & 255
            elif ftype == 2:
                line[x] = (line[x] + b) & 255
            elif ftype == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif ftype == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        prev = line
    grid = []
    for line in rows:
        out = []
        for x in range(w):
            p = line[x * bpp:(x + 1) * bpp]
            if ctype == 6:
                out.append(tuple(p))
            elif ctype == 2:
                out.append(tuple(p) + (255,))
            elif ctype == 0:
                out.append((p[0], p[0], p[0], 255))
            elif ctype == 4:
                out.append((p[0], p[0], p[0], p[1]))
            else:
                idx = p[0]
                alpha = trns[idx] if trns is not None and idx < len(trns) else 255
                out.append(plte[idx] + (alpha,))
        grid.append(out)
    return grid


def write_png(path, grid, overwrite):
    path = Path(path)
    if path.exists() and not overwrite:
        raise SpriteError(f"{path} exists (use --overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes(grid))


# ---- build --------------------------------------------------------------------------------------------------------
def load_sprite_file(path):
    path = Path(path)
    if not path.is_file():
        raise SpriteError(f"sprite file not found: {path}")
    sys.path.insert(0, str(Path(__file__).resolve().parent))   # so sprite files can `from pixel_sprite import Sprite`
    sys.modules.setdefault("pixel_sprite", sys.modules[__name__])  # run as a script, this module is __main__: one Sprite class
    spec = importlib.util.spec_from_file_location(f"sprite_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        raise SpriteError(f"{path}: {exc!r}") from exc
    for name in ("PALETTE", "ROWS", "draw"):
        if not hasattr(mod, name):
            raise SpriteError(f"{path} must define {name} (see this tool's header)")
    return mod


def draw_frame(mod, pose, direction, frame):
    src = getattr(mod, "MIRROR", {}).get(direction)
    try:
        sprite = mod.draw(pose, src or direction, frame)
    except SpriteError:
        raise
    except Exception as exc:
        raise SpriteError(f"draw({pose!r}, {src or direction!r}, {frame}) failed: {exc!r}") from exc
    if not isinstance(sprite, Sprite):
        raise SpriteError(f"draw({pose!r}, {direction!r}, {frame}) must return a Sprite")
    grid = render(sprite, getattr(mod, "OUTLINE", True), getattr(mod, "SHADOW", True))
    return mirror(grid) if src else grid


def build_atlas(mod):
    cell = getattr(mod, "CELL", DEFAULT_CELL)
    frames = getattr(mod, "FRAMES", DEFAULT_FRAMES)
    rows = list(mod.ROWS)
    atlas = [[(0, 0, 0, 0)] * (cell * frames) for _ in range(cell * len(rows))]
    for r, (pose, direction) in enumerate(rows):
        for f in range(frames):
            g = draw_frame(mod, pose, direction, f)
            if len(g) != cell:
                raise SpriteError(f"draw() made a {len(g)} px frame, CELL is {cell}: create Sprite(PALETTE, CELL)")
            for y in range(cell):
                atlas[r * cell + y][f * cell:(f + 1) * cell] = g[y]
    layout = {"cell": cell, "columns": frames, "rows": [
        {"index": i, "pose": p, "direction": d, "frames": frames, "first_frame": i * frames} for i, (p, d) in enumerate(rows)]}
    return atlas, layout


def preview(atlas, cell, scale):
    rows, cols = len(atlas) // cell, len(atlas[0]) // cell
    step = cell * scale + PREVIEW_GAP * scale
    out = [[PREVIEW_BG] * (cols * step + PREVIEW_GAP * scale) for _ in range(rows * step + PREVIEW_GAP * scale)]
    for r in range(rows):
        for c in range(cols):
            for y in range(cell):
                for x in range(cell):
                    p = atlas[r * cell + y][c * cell + x]
                    if p[3] == 0:
                        continue
                    a = p[3] / 255
                    blend = tuple(int(p[i] * a + PREVIEW_BG[i] * (1 - a)) for i in range(3)) + (255,)
                    oy, ox = PREVIEW_GAP * scale + r * step + y * scale, PREVIEW_GAP * scale + c * step + x * scale
                    for yy in range(scale):
                        out[oy + yy][ox:ox + scale] = [blend] * scale
    return out


# ---- check: the first-art floor -------------------------------------------------------------------------------------
def check_frame(grid, x0, y0, cell):
    opaque, colors, ys = [], set(), []
    for y in range(cell):
        for x in range(cell):
            p = grid[y0 + y][x0 + x]
            if p[3] >= 200:
                opaque.append((x, y))
                colors.add(p[:3])
                ys.append(y)
    if not opaque:
        return None
    filled = set(opaque)
    height = (max(ys) - min(ys) + 1) / cell
    fill = len(opaque) / (cell * cell)
    edge = [(x, y) for (x, y) in opaque
            if any((nx, ny) not in filled for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))]
    lum = lambda p: 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]
    avg = sum(lum(grid[y0 + y][x0 + x]) for x, y in opaque) / len(opaque)
    dark = max(avg * 0.6, OUTLINE_LUM)                # relative for bright figures, absolute so dark ones can pass
    dark_edge = sum(1 for x, y in edge if lum(grid[y0 + y][x0 + x]) < dark) / max(len(edge), 1)
    problems = []
    if height < FLOOR_HEIGHT:
        problems.append(f"only {height:.0%} of the cell tall (floor {FLOOR_HEIGHT:.0%})")
    if len(colors) < FLOOR_COLORS:
        problems.append(f"{len(colors)} colors (floor {FLOOR_COLORS}): add shades and details")
    if fill < FLOOR_FILL:
        problems.append(f"covers {fill:.0%} of the cell (floor {FLOOR_FILL:.0%})")
    if dark_edge < FLOOR_OUTLINE:
        problems.append(f"{dark_edge:.0%} of the edge is a dark outline (floor {FLOOR_OUTLINE:.0%})")
    return {"height": height, "colors": len(colors), "fill": fill, "outline": dark_edge, "problems": problems}


def check_atlas(grid, cell):
    rows, cols = len(grid) // cell, len(grid[0]) // cell
    if rows == 0 or cols == 0 or len(grid) % cell or len(grid[0]) % cell:
        raise SpriteError(f"image is {len(grid[0])}x{len(grid)}, not a whole number of {cell} px cells (use --cell)")
    results = []
    for r in range(rows):
        for c in range(cols):
            res = check_frame(grid, c * cell, r * cell, cell)
            if res is not None:
                results.append(((r, c), res))
    return results


def print_check(results, name):
    if not results:
        print(f"[FAIL] {name}: every cell is empty")
        return 1
    bad = [(rc, res) for rc, res in results if res["problems"]]
    for (r, c), res in bad[:12]:
        print(f"[FAIL] {name} row {r} frame {c}: " + "; ".join(res["problems"]))
    if len(bad) > 12:
        print(f"[FAIL] ... and {len(bad) - 12} more frame(s)")
    if bad:
        print(f"[FAIL] {len(bad)} of {len(results)} frame(s) below the first-art floor: draw a real figure "
              f"(head, body, limbs, 2 or 3 shades per material, outline), not a dot or a shape")
        return 1
    worst = min(results, key=lambda t: t[1]["colors"])[1]
    print(f"[ OK ] {name}: {len(results)} frame(s) meet the first-art floor "
          f"(fewest colors {worst['colors']}, figure height {min(r[1]['height'] for r in results):.0%} of the cell)")
    return 0


# ---- commands -----------------------------------------------------------------------------------------------------
def is_unchanged_example(path):
    try:
        return Path(path).read_bytes() == EXAMPLE.read_bytes()
    except OSError:
        return False


def cmd_build(args):
    if is_unchanged_example(args.sprite):
        print("[WARN] this is the kit's reference hero, unchanged: fine for learning the technique, never as this game's "
              "character. Draw the game's own characters from docs/GDD.md (CLAUDE.md, \"The first-art floor\").")
    mod = load_sprite_file(args.sprite)
    atlas, layout = build_atlas(mod)
    out = Path(args.out)
    png, js = out.with_suffix(".png"), out.with_suffix(".json")
    prev = out.parent / f"{out.name}_preview.png"
    for p in [png, js] + ([prev] if args.preview_scale > 0 else []):   # all or nothing: no half-written outputs
        if p.exists() and not args.overwrite:
            raise SpriteError(f"{p} exists (use --overwrite)")
    write_png(png, atlas, args.overwrite)
    layout["image"] = png.name
    js.write_text(json.dumps(layout, indent=2) + "\n", encoding="utf-8")
    print(f"[ OK ] {png} ({len(atlas[0])}x{len(atlas)}, {len(layout['rows'])} rows of {layout['columns']} frames) and {js.name}")
    if args.preview_scale > 0:
        write_png(prev, preview(atlas, layout["cell"], args.preview_scale), args.overwrite)
        print(f"[ OK ] {prev} (preview, {args.preview_scale}x)")
    return print_check(check_atlas(atlas, layout["cell"]), png.name)


def cmd_check(args):
    path = Path(args.png)
    if not path.is_file():
        raise SpriteError(f"not found: {path}")
    cell = args.cell
    js = path.with_suffix(".json")
    if cell is None and js.is_file():
        cell = json.loads(js.read_text(encoding="utf-8")).get("cell")
    return print_check(check_atlas(read_png(path), cell or DEFAULT_CELL), path.name)


def cmd_example(args):
    dest = Path(args.out) / EXAMPLE.name
    if dest.exists() and not args.overwrite:
        raise SpriteError(f"{dest} exists (use --overwrite)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(EXAMPLE, dest)
    print(f"[ OK ] {dest}: build it with `python tools/art/pixel_sprite.py build {dest.as_posix()} --out <assets>/art/hero`")
    return 0


def parse_args(argv):
    ap = argparse.ArgumentParser(
        description="Draw game sprites as real pixel art in code: build an atlas from a sprite file, check art "
                    "against the kit's first-art floor (no dots or plain shapes), or copy the example hero.",
        epilog="Exit 0 ok, 1 below the first-art floor, 2 usage or file error. A sprite file's format: see the "
               "header of this script or tools/art/sprites/example_hero.py.")
    ap.add_argument("--debug", action="store_true", help="print tracebacks")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="sprite file -> atlas PNG + JSON layout + preview, then the floor check")
    b.add_argument("sprite", help="the sprite file (Python), e.g. assets_src/sprites/hero.py")
    b.add_argument("--out", required=True, help="output path without extension, e.g. public/assets/art/hero")
    b.add_argument("--preview-scale", type=int, default=4, help="upscale for <out>_preview.png (0 = none, default 4)")
    b.add_argument("--overwrite", action="store_true", help="replace existing outputs")
    c = sub.add_parser("check", help="check an atlas or a single sprite PNG against the first-art floor")
    c.add_argument("png")
    c.add_argument("--cell", type=int, default=None, help="cell size in px (default: from the .json beside it, else 32)")
    e = sub.add_parser("example", help="copy the reference character (steampunk hero) to start from")
    e.add_argument("--out", default="assets_src/sprites", help="folder to copy it into (default assets_src/sprites)")
    e.add_argument("--overwrite", action="store_true")
    for p in (b, c, e):
        p.add_argument("--debug", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    return ap.parse_args(argv)


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # Windows pipes default to cp1252
        except (AttributeError, ValueError):
            pass
    args = parse_args(sys.argv[1:] if argv is None else argv)
    DEBUG = args.debug
    try:
        return {"build": cmd_build, "check": cmd_check, "example": cmd_example}[args.cmd](args)
    except SpriteError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            raise
        return 2


if __name__ == "__main__":
    sys.exit(main())
