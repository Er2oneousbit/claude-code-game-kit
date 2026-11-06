#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# image_diff.py
# Purpose : Visual regression: compare a new screenshot with a baseline and fail when they differ beyond a tolerance,
#           so a change that moves a menu, breaks a font or drops a sprite is caught by `dev.py smoke --compare`.
# Usage   : python tools/image_diff.py new.png baseline.png                   # exact (any changed pixel fails)
#           python tools/image_diff.py new.png baseline.png --tolerance 8 --max-pixels 20 --diff diff.png
#           python tools/image_diff.py new.png baseline.png --ignore 0,0,200,24  # skip a region (a clock, an FPS line)
# Exit    : 0 same within the tolerance, 1 different (or a different size), 2 usage problem or unreadable file
# Notes   : A pixel differs when any channel (R, G, B, A) differs by more than --tolerance (0-255). The run fails when
#           more than --max-pixels pixels differ. --diff writes a picture: differing pixels red over a dimmed copy of
#           the baseline. Reads non-interlaced PNGs (8 and 16 bit, gray, RGB, palette, with or without alpha), which
#           covers what Godot, LÖVE, Chromium, Unity and Unreal save. Standard library only, Python 3.8+.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   read both PNGs -> RGBA rows (unfilter scanlines, expand palette / gray, 16 bit -> high byte)
#   sizes differ -> FAIL
#   per pixel outside --ignore boxes: max channel delta > tolerance -> count it, grow the bounding box
#   count > max_pixels -> FAIL with count and box (and --diff picture) ; else OK
import argparse
import struct
import sys
import traceback
import zlib
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

PNG_SIG = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}       # PNG colour type -> samples per pixel


class ImageError(Exception):
    pass


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read_png(path):
    """(width, height, rows): rows is a list of bytearrays, 4 bytes (RGBA) per pixel."""
    data = Path(path).read_bytes()
    if not data.startswith(PNG_SIG):
        raise ImageError(f"{path}: not a PNG")
    pos, idat, palette, trns = 8, [], None, None
    width = height = depth = ctype = None
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if interlace:
                raise ImageError(f"{path}: interlaced PNGs are not supported (save without interlacing)")
            if ctype not in CHANNELS or depth not in (8, 16) and not (ctype == 3 and depth in (1, 2, 4, 8)):
                raise ImageError(f"{path}: unsupported PNG (colour type {ctype}, {depth} bit)")
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if width is None or not idat:
        raise ImageError(f"{path}: no image data")
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as exc:
        raise ImageError(f"{path}: damaged image data ({exc})")
    n = CHANNELS[ctype]
    bits = n * depth
    stride = (width * bits + 7) // 8
    bpp = max(1, bits // 8)
    rows, prev, p = [], bytearray(stride), 0
    for _ in range(height):
        if p + 1 + stride > len(raw):
            raise ImageError(f"{path}: image data ends early")
        f = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif f == 4:
                line[i] = (line[i] + _paeth(a, b, c)) & 255
            elif f != 0:
                raise ImageError(f"{path}: bad filter type {f}")
        rows.append(_to_rgba(line, width, ctype, depth, palette, trns))
        prev = line
    return width, height, rows


def _to_rgba(line, width, ctype, depth, palette, trns):
    out = bytearray(width * 4)
    if ctype == 3:
        per = 8 // depth
        for x in range(width):
            byte = line[x // per]
            idx = (byte >> (8 - depth * (x % per + 1))) & ((1 << depth) - 1)
            r, g, b = palette[idx * 3:idx * 3 + 3] if palette and idx * 3 + 3 <= len(palette) else (0, 0, 0)
            a = trns[idx] if trns and idx < len(trns) else 255
            out[x * 4:x * 4 + 4] = bytes((r, g, b, a))
        return out
    step = depth // 8                                   # 16 bit: keep the high byte
    n = CHANNELS[ctype]
    for x in range(width):
        s = [line[(x * n + k) * step] for k in range(n)]
        if ctype == 0:
            px = (s[0], s[0], s[0], 255)
        elif ctype == 4:
            px = (s[0], s[0], s[0], s[1])
        elif ctype == 2:
            px = (s[0], s[1], s[2], 255)
        else:
            px = tuple(s)
        out[x * 4:x * 4 + 4] = bytes(px)
    return out


def write_png(path, width, height, rows):
    """RGBA rows -> PNG (filter 0); used for --diff and by the exam. Makes the folder (#247)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    Path(path).write_bytes(PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def parse_box(text):
    try:
        x, y, w, h = (int(v) for v in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("a box is x,y,w,h")
    return x, y, w, h


def compare(a, b, tolerance=0, ignore=()):
    """(count, bbox or None, mask rows) for two images of the same size."""
    (w, h, ra), (_, _, rb) = a, b
    count, box, mask = 0, None, []
    for y in range(h):
        m = bytearray(w)
        la, lb = ra[y], rb[y]
        for x in range(w):
            if any(bx <= x < bx + bw and by <= y < by + bh for bx, by, bw, bh in ignore):
                continue
            i = x * 4
            if max(abs(la[i + k] - lb[i + k]) for k in range(4)) > tolerance:
                m[x] = 1
                count += 1
                box = (x, y, x, y) if box is None else (min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y))
        mask.append(m)
    return count, box, mask


def diff_picture(base, mask):
    w, h, rows = base
    out = []
    for y in range(h):
        r = bytearray(w * 4)
        for x in range(w):
            i = x * 4
            if mask[y][x]:
                r[i:i + 4] = b"\xff\x00\x00\xff"
            else:
                g = (rows[y][i] + rows[y][i + 1] + rows[y][i + 2]) // 6
                r[i:i + 4] = bytes((g, g, g, 255))
        out.append(r)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compare a screenshot with a baseline (visual regression).")
    ap.add_argument("new", help="the new screenshot (PNG)")
    ap.add_argument("baseline", help="the baseline it must match (PNG)")
    ap.add_argument("--tolerance", type=int, default=0, help="per-channel difference allowed, 0-255 (default 0)")
    ap.add_argument("--max-pixels", type=int, default=0, help="differing pixels allowed (default 0)")
    ap.add_argument("--ignore", type=parse_box, action="append", default=[], metavar="X,Y,W,H",
                    help="a region to skip (repeatable)")
    ap.add_argument("--diff", help="write a picture of the differences here")
    ap.add_argument("--debug", action="store_true", help="tracebacks on errors")
    args = ap.parse_args(argv)
    if not 0 <= args.tolerance <= 255 or args.max_pixels < 0:
        print("[error] --tolerance is 0-255 and --max-pixels 0 or more")
        return 2
    try:
        a, b = read_png(args.new), read_png(args.baseline)
    except (OSError, ImageError, struct.error, ValueError) as exc:   # a cut PNG raised struct.error (#247)
        print(f"[error] {exc}")
        if args.debug:
            traceback.print_exc()
        return 2
    if (a[0], a[1]) != (b[0], b[1]):
        print(f"[FAIL] size differs: {args.new} is {a[0]}x{a[1]}, {args.baseline} is {b[0]}x{b[1]}")
        return 1
    count, box, mask = compare(a, b, args.tolerance, args.ignore)
    if args.diff and count:
        write_png(args.diff, a[0], a[1], diff_picture(b, mask))
    if count > args.max_pixels:
        x0, y0, x1, y1 = box
        print(f"[FAIL] {count} pixels differ (more than {args.max_pixels}) in the box x={x0} y={y0} "
              f"w={x1 - x0 + 1} h={y1 - y0 + 1}" + (f"; picture: {args.diff}" if args.diff else ""))
        return 1
    print(f"[ OK ] {args.new} matches {args.baseline} ({count} pixels over tolerance {args.tolerance}, "
          f"{args.max_pixels} allowed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
