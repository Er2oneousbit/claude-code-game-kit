#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_chroma_key.py
# Purpose : Exam for chroma_key.py: synthetic sprites on a key color with known expected results.
# Usage   : python tools/art/test_chroma_key.py
# Exit    : 0 all checks pass, 1 a check failed, 2 Pillow missing
# Notes   : Needs Pillow (pip install pillow). Covers keying, soft edges, despill for magenta and green,
#           and the no-overwrite guards.
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# Updated : 2026-10-21 with Claude (Opus 5.5, claude-opus-5-5): despill and overwrite cases, header and footer
# ---------------------------------------------------------------------------
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import chroma_key as ck

try:
    from PIL import Image
except ImportError:
    print("[ENV ] Pillow is required: pip install pillow", file=sys.stderr)
    sys.exit(2)


def make(path, size=16):
    im = Image.new("RGB", (size, size), (255, 0, 255))
    for y in range(4, 12):
        for x in range(4, 12):
            im.putpixel((x, y), (200, 30, 30))          # red 8x8 square "sprite"
    im.putpixel((0, 0), (250, 10, 250))                   # near-magenta noise in background
    im.save(path)


def main():
    fails = 0
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        make(d / "s.png")
        rc = ck.main([str(d / "s.png"), "--out", str(d / "o"), "--tolerance", "40"])
        out = Image.open(d / "o" / "s.png").convert("RGBA")
        checks = [
            ("exit code 0", rc == 0),
            ("background transparent", out.getpixel((8, 1))[3] == 0),
            ("noise pixel transparent", out.getpixel((0, 0))[3] == 0),
            ("sprite opaque", out.getpixel((8, 8))[3] == 255),
            ("sprite color kept", out.getpixel((8, 8))[:3] == (200, 30, 30)),
            ("source untouched", Image.open(d / "s.png").getpixel((8, 1)) == (255, 0, 255)),
        ]
        rc_bad = ck.main([str(d / "missing.png")])
        checks.append(("missing input exits 2", rc_bad == 2))
        rc_key = ck.main([str(d / "s.png"), "--key", "XYZ"])
        checks.append(("bad key exits 2", rc_key == 2))

        # despill: a pink fringe on a red sprite loses its pink but keeps its red; green fringe likewise
        r, g, b = ck.despill_pixel((220, 40, 180), (255, 0, 255))
        checks.append(("magenta despill removes pink cast", b <= g + 0 and r > b))
        r, g, b = ck.despill_pixel((60, 200, 50), (0, 255, 0))
        checks.append(("green despill caps green", g <= max(r, b)))
        checks.append(("despill leaves clean pixels alone", ck.despill_pixel((200, 30, 30), (255, 0, 255)) == (200, 30, 30)))

        # no-overwrite guards: nothing is written when any destination is unsafe
        src = d / "src"
        src.mkdir()
        Image.new("RGB", (4, 4), (255, 0, 255)).save(src / "hero.png")
        Image.new("RGB", (4, 4), (255, 0, 255)).save(src / "hero.jpg")
        before = (src / "hero.png").read_bytes()
        rc_same = ck.main([str(src), "--out", str(src)])
        checks.append(("--out = input folder refused, source intact", rc_same == 2 and (src / "hero.png").read_bytes() == before))
        rc_clash = ck.main([str(src), "--out", str(d / "o2")])
        checks.append(("two inputs with one output name refused", rc_clash == 2 and not (d / "o2").exists()))
        (src / "hero.jpg").unlink()
        rc_first = ck.main([str(src), "--out", str(d / "o3")])
        rc_again = ck.main([str(src), "--out", str(d / "o3")])
        rc_forced = ck.main([str(src), "--out", str(d / "o3"), "--overwrite"])
        checks.append(("existing output needs --overwrite", (rc_first, rc_again, rc_forced) == (0, 2, 0)))
        for name, ok in checks:
            print(("[ OK ] " if ok else "[FAIL] ") + name)
            fails += 0 if ok else 1
    print(f"score: {len(checks) - fails}/{len(checks)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
