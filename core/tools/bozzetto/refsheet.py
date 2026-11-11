#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# refsheet.py
# Purpose : Pictures for `bozzetto.py reference`, in the standard library: read a PNG (any 8-bit colour type, not
#           interlaced), write one, lay the views side by side on a turnaround sheet, and a quick look check (is the
#           background flat and light, are the views the same height, does a figure touch the edge).
# Usage   : import refsheet
#           img = refsheet.decode(png_bytes)            # Image(w, h, rgb bytes) or None when it cannot be read
#           sheet_png = refsheet.sheet([img_front, img_left, img_back, img_right])
#           report = refsheet.look({"front": img_front, "left": img_left})   # {"warnings": [...], "views": {...}}
# Notes   : Pillow is used when it is installed (much faster on 1024 px pictures, and it reads JPEG and WebP);
#           without it PNG still works, in pure Python (a few seconds per 1024 px view). The look check is a hint for
#           the person looking at the sheet, never a gate: generators drift in ways no pixel count sees.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   decode: Pillow -> RGB bytes | PNG chunks -> inflate IDAT -> unfilter rows -> expand to RGB
#   sheet:  each view scaled (nearest) to one cell height -> pasted left to right on the light grey -> encode
#   look:   per view, a small copy -> border pixels: mean, spread -> figure box = pixels far from the border colour
#           -> warnings: busy or dark or coloured background, figure cut off, heights or feet that differ
import io
import struct
import zlib

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
BACKGROUND = (208, 208, 208)       # the sheet's grey, the same as the prompts ask for
CELL_H = 512                       # sheet cell height in pixels
GAP = 16                           # between cells and around the edge
LOOK_H = 160                       # the small copy the look check measures
BORDER = 0.03                      # share of each side counted as background
FLAT_SPREAD = 10.0                 # mean absolute deviation of border pixels above this: not a flat background
LIGHT_MIN, LIGHT_MAX = 150, 248    # mean border brightness for "light grey" (white passes, black does not)
TINT_MAX = 24                      # border colour channels further apart than this: a coloured background
FIGURE_DIFF = 36                   # a pixel this far from the border colour belongs to the figure
HEIGHT_TOL = 0.08                  # figure heights differing by more than this share: warn
FEET_TOL = 0.05                    # lowest figure rows differing by more than this share of the picture: warn


class Image:
    """Width, height and packed RGB bytes (3 per pixel, rows top to bottom)."""

    def __init__(self, w, h, rgb):
        self.w, self.h, self.rgb = w, h, rgb

    def px(self, x, y):
        i = (y * self.w + x) * 3
        return self.rgb[i], self.rgb[i + 1], self.rgb[i + 2]


# ---- reading ----------------------------------------------------------------------------------------------------
def _pillow():
    try:
        from PIL import Image as PILImage   # noqa: F401  (optional speed-up)
        return PILImage
    except ImportError:
        return None


def decode(data):
    """An Image from PNG (or, with Pillow, JPEG and WebP) bytes, or None when it cannot be read."""
    pil = _pillow()
    if pil is not None:
        try:
            im = pil.open(io.BytesIO(data))
            if im.mode in ("RGBA", "LA", "P", "PA"):   # transparent: flattened onto the sheet grey
                im = im.convert("RGBA")
                bg = pil.new("RGBA", im.size, BACKGROUND + (255,))
                bg.alpha_composite(im)
                im = bg
            im = im.convert("RGB")
            return Image(im.width, im.height, im.tobytes())
        except Exception:  # noqa: BLE001  (a broken picture is reported as unreadable, never a crash)
            return None
    if not data.startswith(PNG_MAGIC):
        return None
    try:
        return _decode_png(data)
    except (ValueError, zlib.error, struct.error, IndexError):
        return None


def to_png(data):
    """PNG bytes for a JPEG or WebP (needs Pillow), the same bytes for a PNG, or None."""
    if data.startswith(PNG_MAGIC):
        return data
    pil = _pillow()
    if pil is None:
        return None
    try:
        out = io.BytesIO()
        pil.open(io.BytesIO(data)).save(out, format="PNG")
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return None


def _decode_png(data):
    pos, ihdr, idat, plte, trns = 8, None, [], None, None
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if tag == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"PLTE":
            plte = body
        elif tag == b"tRNS":
            trns = body
        elif tag == b"IEND":
            break
    if not ihdr:
        raise ValueError("no IHDR")
    w, h, depth, ctype, _, _, interlace = ihdr
    if depth != 8 or interlace or ctype not in (0, 2, 3, 4, 6):
        raise ValueError("only 8-bit, non-interlaced PNGs are read without Pillow")
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(b"".join(idat))
    stride = w * ch
    out = bytearray(stride * h)
    prev = bytearray(stride)
    pos = 0
    for y in range(h):
        ftype = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if ftype == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ftype == 3:
            for i in range(stride):
                left = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif ftype == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        elif ftype != 0:
            raise ValueError("bad PNG filter")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return Image(w, h, bytes(_to_rgb(out, ch, ctype, plte, trns)))


def _to_rgb(px, ch, ctype, plte, trns):
    """Packed RGB; alpha is flattened onto the sheet grey."""
    if ctype == 2:
        return px
    rgb = bytearray()
    bg = BACKGROUND
    if ctype == 3:
        pal = [tuple(plte[i:i + 3]) for i in range(0, len(plte or b""), 3)]
        alpha = list(trns or b"")
        for i in px:
            r, g, b = pal[i] if i < len(pal) else (0, 0, 0)
            a = alpha[i] if i < len(alpha) else 255
            rgb += bytes(((r * a + bg[0] * (255 - a)) // 255, (g * a + bg[1] * (255 - a)) // 255,
                          (b * a + bg[2] * (255 - a)) // 255))
        return rgb
    for i in range(0, len(px), ch):
        if ctype in (0, 4):
            r = g = b = px[i]
        else:
            r, g, b = px[i], px[i + 1], px[i + 2]
        a = px[i + ch - 1] if ctype in (4, 6) else 255
        rgb += bytes(((r * a + bg[0] * (255 - a)) // 255, (g * a + bg[1] * (255 - a)) // 255,
                      (b * a + bg[2] * (255 - a)) // 255))
    return rgb


# ---- writing ----------------------------------------------------------------------------------------------------
def _chunk(tag, body):
    return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)


def encode(img):
    """PNG bytes (RGB, no metadata at all)."""
    stride = img.w * 3
    raw = b"".join(b"\x00" + img.rgb[y * stride:(y + 1) * stride] for y in range(img.h))
    return (PNG_MAGIC + _chunk(b"IHDR", struct.pack(">IIBBBBB", img.w, img.h, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw, 6)) + _chunk(b"IEND", b""))


def scaled(img, h):
    """Nearest-neighbour copy at height h, aspect kept."""
    w = max(1, round(img.w * h / img.h))
    xs = [min(img.w - 1, x * img.w // w) * 3 for x in range(w)]
    out = bytearray()
    for y in range(h):
        row = min(img.h - 1, y * img.h // h) * img.w * 3
        src = img.rgb
        for x in xs:
            i = row + x
            out += src[i:i + 3]
    return Image(w, h, bytes(out))


def sheet(images, cell_h=CELL_H):
    """The views side by side, each cell_h tall, on the light grey with a gap around each: PNG bytes."""
    cells = [scaled(im, cell_h) for im in images]
    w = GAP + sum(c.w + GAP for c in cells)
    h = cell_h + 2 * GAP
    canvas = bytearray(bytes(BACKGROUND) * (w * h))
    x0 = GAP
    for c in cells:
        for y in range(c.h):
            dst = ((y + GAP) * w + x0) * 3
            canvas[dst:dst + c.w * 3] = c.rgb[y * c.w * 3:(y + 1) * c.w * 3]
        x0 += c.w + GAP
    return encode(Image(w, h, bytes(canvas)))


# ---- look check -------------------------------------------------------------------------------------------------
def measure(img):
    """Border colour and spread, and the figure's box as shares of the picture (None when nothing stands out)."""
    small = scaled(img, LOOK_H) if img.h > LOOK_H else img
    w, h = small.w, small.h
    b = max(1, int(min(w, h) * BORDER))
    border = [small.px(x, y) for y in range(h) for x in range(w) if x < b or x >= w - b or y < b or y >= h - b]
    mean = tuple(sum(p[i] for p in border) / len(border) for i in range(3))
    spread = sum(sum(abs(p[i] - mean[i]) for i in range(3)) / 3 for p in border) / len(border)
    rows, cols = [], []
    for y in range(h):
        for x in range(w):
            p = small.px(x, y)
            if max(abs(p[i] - mean[i]) for i in range(3)) > FIGURE_DIFF:
                rows.append(y)
                cols.append(x)
    box = None
    if rows:
        box = {"top": min(rows) / h, "bottom": (max(rows) + 1) / h, "left": min(cols) / w, "right": (max(cols) + 1) / w}
    return {"size": [img.w, img.h], "background": [round(v) for v in mean], "background_spread": round(spread, 1),
            "figure": {k: round(v, 3) for k, v in box.items()} if box else None}


def look(views):
    """{"views": {name: measure}, "warnings": [...]} for a dict of name -> Image (None for an unreadable one)."""
    report, warns = {}, []
    for name, img in views.items():
        if img is None:
            warns.append(f"{name}: not readable here (install Pillow for JPEG or WebP); look at it yourself")
            continue
        m = measure(img)
        report[name] = m
        light = sum(m["background"]) / 3
        if m["background_spread"] > FLAT_SPREAD:
            warns.append(f"{name}: the background is not flat (border spread {m['background_spread']})")
        if not LIGHT_MIN <= light <= LIGHT_MAX:
            warns.append(f"{name}: the background is not light grey (mean {round(light)})")
        if max(m["background"]) - min(m["background"]) > TINT_MAX:
            warns.append(f"{name}: the background is tinted {tuple(m['background'])}")
        f = m["figure"]
        if f is None:
            warns.append(f"{name}: no figure stands out from the background")
        elif f["top"] <= 0.0 or f["left"] <= 0.0 or f["right"] >= 1.0:
            warns.append(f"{name}: the figure touches the edge of the picture (cut off?)")
        elif f["bottom"] >= 1.0:
            warns.append(f"{name}: something reaches the bottom edge: cut-off feet, or a floor shadow or gradient")
    figs = {n: m["figure"] for n, m in report.items() if m["figure"]}
    if len(figs) > 1:
        heights = {n: f["bottom"] - f["top"] for n, f in figs.items()}
        hi = max(heights.values())
        if hi and (hi - min(heights.values())) / hi > HEIGHT_TOL:
            warns.append("the views differ in figure height: " + ", ".join(f"{n} {v:.0%}" for n, v in heights.items()))
        feet = [f["bottom"] for f in figs.values()]
        if max(feet) - min(feet) > FEET_TOL:
            warns.append("the feet are not on one line across the views: " + ", ".join(
                f"{n} {f['bottom']:.0%}" for n, f in figs.items()))
    sizes = {tuple(m["size"]) for m in report.values()}
    if len(sizes) > 1:
        warns.append("the views have different picture sizes: " + ", ".join(f"{n} {m['size'][0]}x{m['size'][1]}"
                                                                          for n, m in report.items()))
    return {"views": report, "warnings": warns}
