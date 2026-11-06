#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_image_diff.py
# Purpose : Exam for tools/image_diff.py (visual regression): identical images pass, a planted small change fails
#           with its box, tolerance and --ignore work, every PNG colour type and filter decodes the same pixels.
# Usage   : python tools/test_image_diff.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import io
import struct
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import image_diff as idf  # noqa: E402


def picture(w=40, h=30):
    return [bytearray(b"".join(bytes(((x * 7) % 256, (y * 9) % 256, (x * y) % 256, 255)) for x in range(w)))
            for y in range(h)]


def png_bytes(w, h, ctype, depth, rows_samples, filt=0, palette=None, trns=None):
    """A PNG from raw per-row sample bytes with one filter type for every row (the encoder is the test's own)."""
    n = idf.CHANNELS[ctype]
    bpp = max(1, n * depth // 8)
    raw, prev = b"", bytes(len(rows_samples[0]))
    for line in rows_samples:
        out = bytearray()
        for i, v in enumerate(line):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            pred = {0: 0, 1: a, 2: b, 3: (a + b) >> 1, 4: idf._paeth(a, b, c)}[filt]
            out.append((v - pred) & 255)
        raw += bytes([filt]) + bytes(out)
        prev = line

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    body = chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, ctype, 0, 0, 0))
    if palette:
        body += chunk(b"PLTE", palette)
    if trns:
        body += chunk(b"tRNS", trns)
    return idf.PNG_SIG + body + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class ImageDiff(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rows = picture()
        self.base = self.tmp / "base.png"
        idf.write_png(self.base, 40, 30, self.rows)

    def run_cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = idf.main([str(a) for a in args])
        return code, buf.getvalue()

    def planted(self, name="new.png", box=(10, 12, 3, 2), color=b"\x00\xff\x00\xff"):
        rows = [bytearray(r) for r in self.rows]
        x0, y0, w, h = box
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                rows[y][x * 4:x * 4 + 4] = color
        path = self.tmp / name
        idf.write_png(path, 40, 30, rows)
        return path

    def test_identical_passes(self):
        copy = self.tmp / "copy.png"
        idf.write_png(copy, 40, 30, self.rows)
        self.assertEqual(self.run_cli(copy, self.base)[0], 0)

    def test_planted_region_fails_with_its_box(self):
        code, out = self.run_cli(self.planted(), self.base, "--diff", self.tmp / "d.png")
        self.assertEqual(code, 1, out)
        self.assertIn("6 pixels differ", out)
        self.assertIn("x=10 y=12 w=3 h=2", out)
        w, h, rows = idf.read_png(self.tmp / "d.png")
        self.assertEqual(bytes(rows[12][40:44]), b"\xff\x00\x00\xff")

    def test_one_pixel_fails_by_default(self):
        self.assertEqual(self.run_cli(self.planted(box=(0, 0, 1, 1)), self.base)[0], 1)

    def test_tolerance_and_max_pixels(self):
        rows = [bytearray(r) for r in self.rows]
        rows[3][0] = (rows[3][0] + 5) % 256
        near = self.tmp / "near.png"
        idf.write_png(near, 40, 30, rows)
        self.assertEqual(self.run_cli(near, self.base)[0], 1)
        self.assertEqual(self.run_cli(near, self.base, "--tolerance", 5)[0], 0)
        self.assertEqual(self.run_cli(self.planted(), self.base, "--max-pixels", 6)[0], 0)

    def test_ignore_region(self):
        self.assertEqual(self.run_cli(self.planted(), self.base, "--ignore", "9,11,5,4")[0], 0)

    def test_size_and_unreadable(self):
        small = self.tmp / "small.png"
        idf.write_png(small, 2, 2, [bytearray(8), bytearray(8)])
        self.assertEqual(self.run_cli(small, self.base)[0], 1)
        bad = self.tmp / "bad.png"
        bad.write_bytes(b"not a png")
        self.assertEqual(self.run_cli(bad, self.base)[0], 2)
        self.assertEqual(self.run_cli(self.tmp / "missing.png", self.base)[0], 2)

    def test_every_filter_and_colour_type_decodes(self):
        w, h = 5, 4
        rgb = [bytes((x * 40 + y, 200 - x * 10, y * 50)[k] for x in range(w) for k in range(3)) for y in range(h)]
        expect = [[(x * 40 + y, 200 - x * 10, y * 50, 255) for x in range(w)] for y in range(h)]
        for filt in range(5):
            p = self.tmp / f"rgb{filt}.png"
            p.write_bytes(png_bytes(w, h, 2, 8, rgb, filt))
            _, _, rows = idf.read_png(p)
            self.assertEqual([[tuple(r[x * 4:x * 4 + 4]) for x in range(w)] for r in rows], expect, filt)
        gray16 = [b"".join(struct.pack(">H", (x * 60 + y) * 256 + 7) for x in range(w)) for y in range(h)]
        p = self.tmp / "g16.png"
        p.write_bytes(png_bytes(w, h, 0, 16, gray16, 4))
        _, _, rows = idf.read_png(p)
        self.assertEqual(tuple(rows[1][8:12]), (121, 121, 121, 255))
        pal = bytes((10, 20, 30, 200, 100, 50))
        idx = [bytes((0b01000000,)) for _ in range(h)]                    # 2-bit indices: 1, 0, 0, 0
        p = self.tmp / "p2.png"
        p.write_bytes(png_bytes(4, h, 3, 2, idx, 0, palette=pal, trns=bytes((255, 128))))
        _, _, rows = idf.read_png(p)
        self.assertEqual((tuple(rows[0][0:4]), tuple(rows[0][4:8])), ((200, 100, 50, 128), (10, 20, 30, 255)))

    def test_interlaced_is_refused(self):
        p = self.tmp / "il.png"
        data = bytearray(png_bytes(2, 2, 2, 8, [bytes(6), bytes(6)]))
        data[28] = 1                                                     # IHDR interlace byte
        p.write_bytes(bytes(data))
        self.assertEqual(self.run_cli(p, self.base)[0], 2)


class ImageDiffReviewFixes(ImageDiff):
    """#247: a cut PNG raised struct.error (a traceback, exit 1); --diff into a missing folder too."""

    def test_a_cut_png_is_exit_2(self):
        cut = self.tmp / "cut.png"
        cut.write_bytes(self.base.read_bytes()[:20])
        code, out = self.run_cli(cut, self.base)
        self.assertEqual(code, 2, out)

    def test_diff_into_a_new_folder(self):
        new = self.planted()
        code, out = self.run_cli(new, self.base, "--diff", self.tmp / "out" / "deep" / "d.png")
        self.assertEqual(code, 1, out)
        self.assertTrue((self.tmp / "out" / "deep" / "d.png").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=1)
