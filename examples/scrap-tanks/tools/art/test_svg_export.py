#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_svg_export.py
# Purpose : Exam for svg_export.py against a real Inkscape: page export at exact
#           widths, object export by id and wildcard, scale factors, --list-ids,
#           a missing id, overwrite protection and usage errors.
# Usage   : python tools/art/test_svg_export.py [--keep]
# Exit    : 0 all cases pass, 1 a case failed, 2 Inkscape not installed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import argparse
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE / "svg_export.py"
SVG = """<svg xmlns="http://www.w3.org/2000/svg" id="doc" width="100" height="50" viewBox="0 0 100 50">
  <rect id="icon_a" x="0" y="0" width="20" height="20" fill="#e04040"/>
  <rect id="icon_b" x="40" y="10" width="40" height="10" fill="#4040e0"/>
  <circle id="dot" cx="90" cy="40" r="5" fill="#40c040"/>
</svg>
"""


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    return struct.unpack(">II", head[16:24])


def run_tool(*args):
    p = subprocess.run([sys.executable, str(TOOL), *[str(a) for a in args]], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, p.stdout + p.stderr


def main():
    ap = argparse.ArgumentParser(description="Exam for svg_export.py (needs Inkscape).")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    sys.path.insert(0, str(HERE))
    import svg_export  # noqa: E402
    if not svg_export.find_inkscape():
        print("[ENV ] Inkscape not installed: exam skipped", file=sys.stderr)
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="svg_exam_"))
    svg = tmp / "art.svg"
    svg.write_text(SVG, encoding="utf-8")
    out = tmp / "out"
    results = []

    def case(name, ok, detail=""):
        results.append(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else '  ' + str(detail)}")

    rc, o = run_tool(svg, "--list-ids")
    case("--list-ids shows every object id", rc == 0 and all(i in o for i in ("icon_a", "icon_b", "dot")), o[-300:])

    rc, o = run_tool(svg, "--out", out, "--size", 200)
    case("page export at an exact width (exit 0)", rc == 0, o[-300:])
    if rc == 0:
        case("page PNG is 200x100 (aspect kept)", png_size(out / "art.png") == (200, 100), png_size(out / "art.png"))

    rc, o = run_tool(svg, "--out", tmp / "scaled", "--scale", 2)
    case("page at scale 2 uses the PAGE size (200x100), not the drawing's bounds",
         rc == 0 and png_size(tmp / "scaled" / "art.png") == (200, 100), o[-300:])
    mm = tmp / "mm.svg"
    mm.write_text(SVG.replace('width="100" height="50"', 'width="26.458333mm" height="13.229167mm"'), encoding="utf-8")
    rc, o = run_tool(mm, "--out", tmp / "mm", "--scale", 1)
    case("units in the file are converted (26.46 mm = 100 px)", rc == 0 and png_size(tmp / "mm" / "mm.png")[0] == 100, o[-300:])

    rc, o = run_tool(svg, "--out", out, "--id", "icon_*", "--size", 32, "--size", 64)
    case("wildcard ids at two sizes (exit 0)", rc == 0, o[-300:])
    if rc == 0:
        sizes = {p.name: png_size(p) for p in out.glob("art_icon_*.png")}
        case("four files with the right sizes",
             sizes == {"art_icon_a_32px.png": (32, 32), "art_icon_a_64px.png": (64, 64),
                       "art_icon_b_32px.png": (32, 8), "art_icon_b_64px.png": (64, 16)}, sizes)

    rc, o = run_tool(svg, "--out", out, "--id", "dot", "--scale", 2)
    case("object at scale 2 is 20 px wide", rc == 0 and png_size(out / "art_dot.png")[0] == 20, o[-300:])

    rc, o = run_tool(svg, "--out", out, "--id", "nope")
    case("an unknown id fails (exit 1) with a hint", rc == 1 and "--list-ids" in o, o[-300:])
    rc, o = run_tool(svg, "--out", out, "--size", 200)
    case("existing output is not overwritten (exit 2)", rc == 2, o[-300:])
    rc, o = run_tool(tmp / "missing.svg", "--out", out)
    case("missing SVG exits 2", rc == 2, o[-300:])
    rc, o = run_tool(svg)
    case("no --out exits 2", rc == 2, o[-300:])

    passed = sum(results)
    print(f"{passed}/{len(results)} cases passed")
    if args.keep:
        print(f"files kept in {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
