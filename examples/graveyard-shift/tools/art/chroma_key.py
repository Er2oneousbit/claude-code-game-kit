#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# chroma_key.py
# Purpose : Turn a flat key-color background (default magenta FF00FF) into real
#           transparency for AI-generated sprites. Magenta is the classic key
#           color because it almost never appears in game palettes.
# Usage   : python tools/art/chroma_key.py <file-or-folder> [--out DIR] [--key FF00FF]
#                [--tolerance 40] [--despill] [--report] [--debug]
#           Examples:
#             python tools/art/chroma_key.py assets/raw/hero_walk.png --out assets/art
#             python tools/art/chroma_key.py assets/raw --out assets/art --tolerance 60 --despill
# Needs   : Python 3.8+, Pillow (pip install pillow)
# Exit    : 0 ok, 1 some files failed, 2 usage/environment problem
# Notes   : Never overwrites the source image. Output keeps the file name, saved as PNG.
#           --tolerance is the max per-channel distance from the key color that counts as background.
#           Raise it for blurry or JPEG-like edges, lower it if the sprite itself has pink/purple in it.
#           --despill pulls leftover key-color fringe (pink for magenta, green for green) off the
#           semi-transparent edge pixels. Refuses (exit 2, nothing written) when an output would replace a
#           source image, two inputs share a name, or an output exists without --overwrite.
#           Anti-aliased pixel art edges are the hard case: check results at 400 percent zoom.
#           Tested on synthetic images only (see tools/art/test_chroma_key.py). Real AI output varies.
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# ---------------------------------------------------------------------------
import argparse
import sys
from pathlib import Path

DEBUG = False


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


def parse_hex(s):
    """'FF00FF' or '#ff00ff' -> (255, 0, 255). Raises ValueError on bad input."""
    s = s.lstrip("#")
    if len(s) != 6:
        raise ValueError(f"key color must be 6 hex digits, got '{s}'")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def despill_pixel(rgb, key):
    """Standard spill suppression: remove the amount by which the key channels exceed the others.

    Key channels are the ones above 128 in the key color (magenta: R and B; green: G). spill =
    min(key channels) - max(other channels); when positive it is subtracted from every key channel,
    so a pink fringe on a red sprite loses its pink cast but keeps its red.
    """
    k = [i for i in range(3) if key[i] > 128]
    n = [i for i in range(3) if i not in k]
    if not k or not n:
        return rgb                         # white or black key: no channel to compare against
    c = list(rgb)
    spill = min(c[i] for i in k) - max(c[i] for i in n)
    if spill > 0:
        for i in k:
            c[i] -= spill
    return tuple(c)


def key_image(img, key, tol, despill):
    """Return (new RGBA image, number of pixels made transparent).

    Pixel is background if every channel is within `tol` of the key. Pixels just outside that
    band (up to 2*tol) get partial alpha so edges are not harsh. Simple and predictable on purpose.
    """
    rgba = img.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    cleared = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            d = max(abs(r - key[0]), abs(g - key[1]), abs(b - key[2]))
            if d <= tol:
                px[x, y] = (r, g, b, 0)
                cleared += 1
            elif tol > 0 and d <= 2 * tol:
                # soft edge: alpha ramps from 0 (at tol) to full (at 2*tol)
                alpha = int(255 * (d - tol) / tol)
                if despill:
                    r, g, b = despill_pixel((r, g, b), key)
                px[x, y] = (r, g, b, min(a, alpha))
    return rgba, cleared


def collect(path):
    p = Path(path)
    if p.is_dir():
        return sorted(f for f in p.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp"))
    return [p]


def main(argv=None):
    global DEBUG
    ap = argparse.ArgumentParser(
        description="Replace a flat key-color background (default magenta) with transparency.",
        epilog="Example: python tools/art/chroma_key.py assets/raw --out assets/art --tolerance 50 --despill")
    ap.add_argument("input", help="image file or folder of images")
    ap.add_argument("--out", default="keyed", help="output folder (default ./keyed). Source files are never overwritten.")
    ap.add_argument("--key", default="FF00FF", help="background color as hex (default FF00FF magenta)")
    ap.add_argument("--tolerance", type=int, default=40, help="0-255 per-channel distance counted as background (default 40)")
    ap.add_argument("--despill", action="store_true", help="reduce key-color fringe on soft edges")
    ap.add_argument("--overwrite", action="store_true", help="replace outputs that already exist in --out")
    ap.add_argument("--report", action="store_true", help="print how much of each image was cleared")
    ap.add_argument("--debug", action="store_true", help="verbose output")
    args = ap.parse_args(argv)
    DEBUG = args.debug
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # Windows pipes default to cp1252
        except (AttributeError, ValueError):
            pass

    try:
        from PIL import Image
    except ImportError:
        print("[error] Pillow is required: pip install pillow", file=sys.stderr)
        return 2
    try:
        key = parse_hex(args.key)
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    if not 0 <= args.tolerance <= 255:
        print("[error] --tolerance must be 0 to 255", file=sys.stderr)
        return 2
    src = Path(args.input)
    if not src.exists():
        print(f"[error] input not found: {src}", file=sys.stderr)
        return 2
    files = collect(src)
    if not files:
        print(f"[error] no images found in {src}", file=sys.stderr)
        return 2

    out = Path(args.out)
    # Plan every destination first, so nothing is written when any of them is unsafe
    plan = [(f, out / (f.stem + ".png")) for f in files]
    sources = {f.resolve() for f in files}
    seen = {}
    for f, dest in plan:
        if dest.resolve() in sources:
            print(f"[error] {f.name} -> {dest} would overwrite a source image; choose a different --out", file=sys.stderr)
            return 2
        if dest.resolve() in seen:
            print(f"[error] {seen[dest.resolve()].name} and {f.name} would both be saved as {dest}; rename one", file=sys.stderr)
            return 2
        seen[dest.resolve()] = f
        if dest.exists() and not args.overwrite:
            print(f"[error] {dest} already exists; pass --overwrite to replace it", file=sys.stderr)
            return 2
    out.mkdir(parents=True, exist_ok=True)
    failures = 0
    for f, dest in plan:
        try:
            with Image.open(f) as im:
                result, cleared = key_image(im, key, args.tolerance, args.despill)
            result.save(dest)
            total = result.size[0] * result.size[1]
            msg = f"[ OK ] {f.name} -> {dest}"
            if args.report:
                msg += f"  ({cleared}/{total} px cleared, {100 * cleared / total:.1f}%)"
            print(msg)
            if cleared == 0:
                print(f"[warn] {f.name}: nothing matched the key color. Wrong --key or --tolerance?")
        except Exception as exc:
            failures += 1
            print(f"[FAIL] {f.name}: {exc}", file=sys.stderr)
            dbg(repr(exc))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
