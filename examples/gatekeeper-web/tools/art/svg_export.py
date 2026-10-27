#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# svg_export.py
# Purpose : Export SVG art to PNG with Inkscape, headless: whole pages or single objects
#           (by id), at exact pixel sizes or scale factors, many in one Inkscape run.
#           UI, icons, vector characters: draw once, export 1x/2x/4x.
# Usage   : python tools/art/svg_export.py <file.svg> [...] --out DIR [options]
#           Examples:
#             python tools/art/svg_export.py ui/icons.svg --list-ids
#             python tools/art/svg_export.py ui/icons.svg --out assets/ui --id "icon_*" --size 32 --size 64
#             python tools/art/svg_export.py hero.svg --out assets/art --scale 1 --scale 2 --scale 4
# Needs   : Inkscape 1.x. Python 3.8+, stdlib only. Inkscape is found via INKSCAPE, PATH, or the default
#           Windows folders (%ProgramFiles%\Inkscape\bin; inkscape.com is used there so output is captured).
# Exit    : 0 every export written, 1 some export missing or an id not found, 2 usage/environment problem
# Notes   : Output names: <svg-stem>.png for the page, <svg-stem>_<id>.png for objects, with _<size>px
#           or _<scale>x added when you ask for more than one size or scale.
#           --size sets the WIDTH in px (height follows the aspect ratio); --scale multiplies the
#           page or object size at 96 dpi. --id accepts wildcards, matched against --list-ids.
#           Inkscape exits 0 even when an export is skipped, so this script checks that every expected
#           file was written (fresh and not empty) and reports Inkscape's "Skipping" lines.
#           Text uses the fonts installed on THIS machine: convert text to paths in the SVG for art that
#           must look the same everywhere. Tested with Inkscape 1.4 on Windows (tools/art/test_svg_export.py).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   find inkscape; for each svg: (ids wanted?) query ids, expand wildcards
#   plan outputs (target, width) per page or id and per size/scale; refuse overwrites
#   write an actions file: export-id / export-id-only / export-width / export-filename / export-do per output
#   run inkscape once per svg with --actions-file, cwd = output folder (plain file names in actions)
#   verify each output exists, is newer than the run and not empty; report missing ones
import argparse
import fnmatch
import os
import re
import xml.etree.ElementTree as ET
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEBUG = False
TIMEOUT_S = 600
DPI = 96
UNIT_PX = {"": 1.0, "px": 1.0, "pt": DPI / 72, "pc": DPI / 6, "mm": DPI / 25.4, "cm": DPI / 2.54, "in": DPI}


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


def find_inkscape():
    env = os.environ.get("INKSCAPE")
    if env and Path(env).is_file():
        return env
    if os.name == "nt":
        for root in (os.environ.get("ProgramFiles", "") + r"\Inkscape\bin",
                     os.environ.get("LOCALAPPDATA", "") + r"\Programs\Inkscape\bin"):
            com = Path(root) / "inkscape.com"          # console wrapper: stdout and stderr reach us
            if com.is_file():
                return str(com)
    for name in ("inkscape.com", "inkscape"):
        found = shutil.which(name)
        if found:
            return found
    return None


def run(cmd, cwd=None, timeout=TIMEOUT_S):
    dbg("run: " + " ".join(str(c) for c in cmd))
    try:
        p = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"Inkscape did not finish within {timeout} s"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def query_ids(inkscape, svg):
    """[(id, width_px, height_px)] for every object with an id (Inkscape --query-all)."""
    rc, out = run([inkscape, "--query-all", svg])
    if rc != 0:
        raise RuntimeError(f"--query-all failed: {out.strip()[:300]}")
    items = []
    for line in out.splitlines():
        parts = line.strip().split(",")
        if len(parts) == 5:
            try:
                items.append((parts[0], float(parts[3]), float(parts[4])))
            except ValueError:
                continue
    return items


def page_width_px(svg):
    """Page width in px from the root width (with units) or the viewBox; None if neither is usable."""
    try:
        root = ET.parse(svg).getroot()
    except (ET.ParseError, OSError):
        return None
    m = re.fullmatch(r"\s*([0-9.]+)\s*([a-z]*)\s*", root.get("width", ""))
    if m and m.group(2) in UNIT_PX:
        return float(m.group(1)) * UNIT_PX[m.group(2)]
    vb = (root.get("viewBox") or "").replace(",", " ").split()
    if len(vb) == 4:
        try:
            return float(vb[2])
        except ValueError:
            return None
    return None


def plan_svg(svg, items, args, out_dir):
    """[(output Path, export-id or None, width px)] for one SVG."""
    sizes = [("_" + f"{s}px", s, None) for s in args.size] + [("_" + f"{k:g}x", None, k) for k in args.scale]
    if not sizes:
        sizes = [("", None, 1.0)]
    multi = len(sizes) > 1
    targets = []
    if args.id:
        by_id = {i: (w, h) for i, w, h in items}
        for pattern in args.id:
            hits = [i for i in by_id if fnmatch.fnmatch(i, pattern)]
            if not hits:
                raise LookupError(f"{svg.name}: no object id matches {pattern!r} (see --list-ids)")
            targets += [(i, by_id[i][0]) for i in hits if (i, by_id[i][0]) not in targets]
    else:
        # Page exports scale the PAGE size (from the file). For --area drawing, --query-all lists the root <svg>
        # first, and its box is the drawing's bounds (checked against Inkscape 1.4: 340 px for a 340 px drawing)
        page_w = page_width_px(svg) if args.area == "page" else (items[0][1] if items else None)
        targets = [(None, page_w)]
    plan = []
    for target_id, base_w in targets:
        for suffix, width, factor in sizes:
            if width is None:
                if not base_w:
                    raise LookupError(f"{svg.name}: cannot read the size of {target_id or 'the page'}")
                width = max(1, round(base_w * factor))
            name = f"{svg.stem}{'_' + target_id if target_id else ''}{suffix if multi else ''}.png"
            plan.append((out_dir / name, target_id, int(width)))
    return plan


def actions_for(plan, args):
    lines = []
    for out, target_id, width in plan:
        if target_id:
            lines += [f"export-id:{target_id}", "export-id-only"]
        else:
            lines.append(f"export-area-{'drawing' if args.area == 'drawing' else 'page'}")
        if args.background:
            lines += [f"export-background:{args.background}", f"export-background-opacity:{args.opacity}"]
        lines += [f"export-width:{width}", f"export-filename:{out.name}", "export-do"]
    return ";\n".join(lines) + ";\n"


def build_parser():
    ap = argparse.ArgumentParser(description="Export SVG pages or objects to PNG with Inkscape (sizes, scales, ids).")
    ap.add_argument("svgs", nargs="+", help="SVG files")
    ap.add_argument("--out", help="output folder (required unless --list-ids)")
    ap.add_argument("--id", action="append", default=[], help="object id or wildcard to export alone (repeatable)")
    ap.add_argument("--size", type=int, action="append", default=[], help="output width in px (repeatable)")
    ap.add_argument("--scale", type=float, action="append", default=[], help="scale factor of the 96-dpi size (repeatable)")
    ap.add_argument("--area", choices=["page", "drawing"], default="page", help="page bounds or drawn content (default page)")
    ap.add_argument("--background", help="background color, e.g. #ffffff (default transparent)")
    ap.add_argument("--opacity", type=float, default=1.0, help="background opacity 0..1 with --background")
    ap.add_argument("--list-ids", action="store_true", help="print object ids and sizes, export nothing")
    ap.add_argument("--overwrite", action="store_true", help="replace existing PNGs")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, export nothing")
    ap.add_argument("--debug", action="store_true", help="print Inkscape's output and the actions")
    return ap


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    DEBUG = args.debug
    svgs = [Path(s) for s in args.svgs]
    missing = [s for s in svgs if not s.is_file()]
    if missing:
        print(f"[error] not found: {missing[0]}", file=sys.stderr)
        return 2
    if not args.list_ids and not args.out:
        print("[error] --out is required (or use --list-ids)", file=sys.stderr)
        return 2
    if any(s < 1 for s in args.size) or any(k <= 0 for k in args.scale):
        print("[error] --size and --scale must be positive", file=sys.stderr)
        return 2
    inkscape = find_inkscape()
    if not inkscape:
        print("[error] Inkscape not found. Install Inkscape 1.x (inkscape.org; on Windows: winget install Inkscape.Inkscape) "
              "or set INKSCAPE to inkscape.com", file=sys.stderr)
        return 2
    failed = 0
    for svg in svgs:
        try:
            items = query_ids(inkscape, svg.resolve())
        except RuntimeError as exc:
            print(f"[FAIL] {svg.name}: {exc}")
            failed += 1
            continue
        if args.list_ids:
            print(f"{svg.name}: {len(items)} object(s) with ids")
            for i, w, h in items:
                print(f"  {i:32s} {w:9.1f} x {h:.1f} px")
            continue
        out_dir = Path(args.out).resolve()
        try:
            plan = plan_svg(svg, items, args, out_dir)
        except LookupError as exc:
            print(f"[FAIL] {exc}")
            failed += 1
            continue
        clash = [o for o, _, _ in plan if o.exists() and not args.overwrite]
        if clash:
            print(f"[error] {clash[0]} exists (use --overwrite)", file=sys.stderr)
            return 2
        if args.dry_run:
            for o, t, w in plan:
                print(f"[dry-run] {svg.name}{' #' + t if t else ''} -> {o.name} ({w} px wide)")
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        start = time.time() - 1
        with tempfile.TemporaryDirectory(prefix="svg_export_") as tmp:
            actions = Path(tmp) / "actions.txt"
            actions.write_text(actions_for(plan, args), encoding="utf-8")
            dbg(actions.read_text(encoding="utf-8"))
            rc, out = run([inkscape, f"--actions-file={actions}", svg.resolve()], cwd=out_dir)
        skipped = [l.strip() for l in out.splitlines() if "Skipping" in l or "not found" in l]
        if DEBUG or rc != 0:
            print(out.rstrip())
        for o, t, w in plan:
            fresh = o.is_file() and o.stat().st_size > 0 and o.stat().st_mtime >= start
            print(f"[{' OK ' if fresh else 'FAIL'}] {o.name} ({w} px wide){'' if fresh else ' not written'}")
            failed += 0 if fresh else 1
        for line in skipped:
            print(f"[WARN] inkscape: {line}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
