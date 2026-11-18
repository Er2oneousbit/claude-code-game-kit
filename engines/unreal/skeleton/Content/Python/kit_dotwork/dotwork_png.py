# ---------------------------------------------------------------------------
# dotwork_png.py
# Purpose : A small PNG reader and writer in plain Python (zlib only) for the Unreal Dotwork importer: Unreal's
#           Python has no Pillow, and a font's pages are re-laid out before Unreal imports them (#286: an offline
#           Font keeps no per-glyph x offset, so each glyph gets a cell of its own with the offset drawn in).
# Usage   : img = dotwork_png.read(path)          # Image(width, height, rgba bytearray, 4 bytes per pixel)
#           dotwork_png.write(path, img)
#           img.crop(x, y, w, h); img.paste(other, x, y); img.pixel(x, y)
# Notes   : Reads 8-bit greyscale, RGB, palette (with tRNS), grey + alpha and RGBA, all five filter types, not
#           interlaced (Dotwork, Pillow and Aseprite write these); writes 8-bit RGBA with filter 0. Anything else
#           raises PngError with the reason.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}   # colour type -> samples per pixel


class PngError(Exception):
    """A PNG this reader does not handle (or not a PNG)."""


class Image:
    """RGBA pixels, row by row, top row first."""

    def __init__(self, width, height, data=None):
        self.width, self.height = width, height
        self.data = bytearray(data) if data is not None else bytearray(width * height * 4)

    def pixel(self, x, y):
        i = (y * self.width + x) * 4
        return tuple(self.data[i:i + 4])

    def crop(self, x, y, w, h):
        out = Image(w, h)
        for row in range(h):
            sy = y + row
            if not 0 <= sy < self.height:
                continue
            for col in range(w):
                sx = x + col
                if 0 <= sx < self.width:
                    s, d = (sy * self.width + sx) * 4, (row * w + col) * 4
                    out.data[d:d + 4] = self.data[s:s + 4]
        return out

    def paste(self, src, x, y):
        """Copies src's pixels (alpha included, no blending) with its top-left at (x, y)."""
        for row in range(src.height):
            dy = y + row
            if not 0 <= dy < self.height:
                continue
            for col in range(src.width):
                dx = x + col
                if 0 <= dx < self.width:
                    s, d = (row * src.width + col) * 4, (dy * self.width + dx) * 4
                    self.data[d:d + 4] = src.data[s:s + 4]
        return self


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def read_bytes(raw, where="PNG"):
    if raw[:8] != SIGNATURE:
        raise PngError(f"{where}: not a PNG")
    pos, idat, palette, trns, head = 8, bytearray(), None, None, None
    while pos + 8 <= len(raw):
        n, tag = struct.unpack(">I4s", raw[pos:pos + 8])
        body = raw[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            head = struct.unpack(">IIBBBBB", body)
        elif tag == b"PLTE":
            palette = body
        elif tag == b"tRNS":
            trns = body
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
        pos += 12 + n
    if head is None:
        raise PngError(f"{where}: no IHDR")
    w, h, depth, ctype, _, _, interlace = head
    if depth != 8 or ctype not in CHANNELS or interlace:
        raise PngError(f"{where}: {depth}-bit colour type {ctype}{' interlaced' if interlace else ''} is not read here")
    bpp = CHANNELS[ctype]
    stride = w * bpp
    try:
        src = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise PngError(f"{where}: image data does not inflate ({exc})")
    if len(src) < h * (stride + 1):
        raise PngError(f"{where}: image data is shorter than {w}x{h}")
    rows, prev = [], bytearray(stride)
    for y in range(h):
        f = src[y * (stride + 1)]
        line = bytearray(src[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], (prev[i - bpp] if i >= bpp else 0)
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                line[i] = (line[i] + _paeth(a, b, c)) & 255
            elif f != 0:
                raise PngError(f"{where}: unknown filter {f}")
        rows.append(line)
        prev = line
    img = Image(w, h)
    d = img.data
    for y, line in enumerate(rows):
        for x in range(w):
            o = (y * w + x) * 4
            s = x * bpp
            if ctype == 6:
                d[o:o + 4] = line[s:s + 4]
            elif ctype == 2:
                d[o:o + 4] = bytes(line[s:s + 3]) + b"\xff"
            elif ctype == 0:
                d[o:o + 4] = bytes((line[s],) * 3) + b"\xff"
            elif ctype == 4:
                d[o:o + 4] = bytes((line[s],) * 3) + bytes((line[s + 1],))
            else:
                k = line[s]
                if palette is None or 3 * k + 3 > len(palette):
                    raise PngError(f"{where}: palette index {k} out of range")
                alpha = trns[k] if trns is not None and k < len(trns) else 255
                d[o:o + 4] = bytes(palette[3 * k:3 * k + 3]) + bytes((alpha,))
    return img


def read(path):
    with open(path, "rb") as f:
        return read_bytes(f.read(), path)


def to_bytes(img):
    raw = b"".join(b"\x00" + bytes(img.data[y * img.width * 4:(y + 1) * img.width * 4]) for y in range(img.height))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", img.width, img.height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def write(path, img):
    with open(path, "wb") as f:
        f.write(to_bytes(img))
