#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_gimp_batch.py
# Purpose : Exam for gimp_batch.py against a real GIMP 3: layered .xcf merge with
#           transparency, aspect-kept resize, crisp pixel-art resize, palette
#           conversion, folder input, a corrupt file failing alone, usage errors.
# Usage   : python tools/art/test_gimp_batch.py [--keep]
# Exit    : 0 all cases pass, 1 a case failed, 2 GIMP 3 not installed
# Notes   : Fixtures are written with the standard library (and one .xcf made by GIMP itself).
#           Color checks use Pillow when it is installed and are skipped otherwise.
#           The first GIMP run on a machine can take minutes.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import argparse
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE / "gimp_batch.py"

# GIMP-side helper: a 64x48 image with two layers (red left half, blue right half on top), saved as .xcf
MAKE_XCF = r'''
import os
img = Gimp.Image.new(64, 48, Gimp.ImageBaseType.RGB)
for name, x, rgb in (("left", 0, (1, 0, 0)), ("right", 32, (0, 0, 1))):
    layer = Gimp.Layer.new(img, name, 32, 48, Gimp.ImageType.RGBA_IMAGE, 100, Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, 0)
    layer.set_offsets(x, 0)
    color = Gegl.Color.new("black")
    color.set_rgba(rgb[0], rgb[1], rgb[2], 1.0)
    Gimp.context_set_foreground(color)
    layer.fill(Gimp.FillType.FOREGROUND)
Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img, Gio.File.new_for_path(os.environ["GB_OUT"]), None)
img.delete()
'''


def write_png(path, w, h, pixel):
    """Minimal RGBA PNG writer (stdlib only). pixel(x, y) -> (r, g, b, a)."""
    raw = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(w)) for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def png_info(path):
    """(width, height, color type) from the PNG header. Color type 3 = palette (indexed)."""
    head = Path(path).read_bytes()[:26]
    w, h = struct.unpack(">II", head[16:24])
    return w, h, head[25]


def colors(path):
    try:
        from PIL import Image
    except ImportError:
        return None
    im = Image.open(path).convert("RGBA")
    return {c for _, c in (im.getcolors(1 << 16) or [])}


def run_tool(*args):
    p = subprocess.run([sys.executable, str(TOOL), *[str(a) for a in args]], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, p.stdout + p.stderr


def main():
    ap = argparse.ArgumentParser(description="Exam for gimp_batch.py (needs GIMP 3).")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    sys.path.insert(0, str(HERE))
    import gimp_batch  # noqa: E402
    gimp = gimp_batch.find_gimp()
    if not gimp:
        print("[ENV ] GIMP 3 not installed: exam skipped", file=sys.stderr)
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="gimp_exam_"))
    src = tmp / "src"
    src.mkdir()
    write_png(src / "checker.png", 64, 48, lambda x, y: (255, 255, 255, 255) if (x // 8 + y // 8) % 2 else (0, 0, 0, 255))
    write_png(src / "glow.png", 40, 40, lambda x, y: (min(255, x * 6), min(255, y * 6), 128, 255))
    (src / "broken.png").write_bytes(b"\x89PNG\r\n\x1a\nthis is not a real png")
    rc, out = gimp_batch.run_gimp(gimp, MAKE_XCF, {"GB_OUT": str(tmp / "layers.xcf")})
    results = []

    def case(name, ok, detail=""):
        results.append(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else '  ' + str(detail)}")

    case("fixture: GIMP wrote a two-layer .xcf", rc == 0 and (tmp / "layers.xcf").is_file(), out[-300:])

    rc, o = run_tool(tmp / "layers.xcf", "--out", tmp / "o1")
    case("layered .xcf exports to PNG (exit 0)", rc == 0, o[-400:])
    if rc == 0:
        case("PNG keeps the canvas size", png_info(tmp / "o1" / "layers.png")[:2] == (64, 48))
        c = colors(tmp / "o1" / "layers.png")
        if c is not None:
            case("both layers survive the merge (red and blue present)",
                 (255, 0, 0, 255) in c and (0, 0, 255, 255) in c, sorted(c)[:6])

    rc, o = run_tool(src / "checker.png", "--out", tmp / "o2", "--width", 32, "--interpolation", "none")
    case("resize with --width keeps the aspect ratio (64x48 -> 32x24)",
         rc == 0 and png_info(tmp / "o2" / "checker.png")[:2] == (32, 24), o[-300:])
    c = colors(tmp / "o2" / "checker.png") if rc == 0 else None
    if c is not None:
        case("--interpolation none stays crisp (only black and white)", c <= {(0, 0, 0, 255), (255, 255, 255, 255)}, sorted(c)[:6])

    rc, o = run_tool(src / "glow.png", "--out", tmp / "o3", "--indexed", 4)
    case("--indexed writes a palette PNG", rc == 0 and png_info(tmp / "o3" / "glow.png")[2] == 3, o[-300:])
    c = colors(tmp / "o3" / "glow.png") if rc == 0 else None
    if c is not None:
        case("--indexed 4 leaves at most 4 colors", len(c) <= 4, len(c))

    rc, o = run_tool(src, "--out", tmp / "o4", "--scale", 50)
    case("a corrupt file fails alone (exit 1)", rc == 1 and "broken.png" in o, o[-400:])
    case("the good files in that batch are still written",
         png_info(tmp / "o4" / "checker.png")[:2] == (32, 24) and png_info(tmp / "o4" / "glow.png")[:2] == (20, 20))

    rc, o = run_tool(src / "checker.png", "--out", tmp / "o2", "--width", 32)
    case("existing output is not overwritten (exit 2)", rc == 2, o[-200:])
    rc, o = run_tool(src / "checker.png", "--out", tmp / "o5", "--width", 32, "--scale", 50)
    case("--scale with --width exits 2", rc == 2, o[-200:])
    rc, o = run_tool(tmp / "missing.png", "--out", tmp / "o6")
    case("missing input exits 2", rc == 2, o[-200:])

    passed = sum(results)
    print(f"{passed}/{len(results)} cases passed")
    if args.keep:
        print(f"files kept in {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
