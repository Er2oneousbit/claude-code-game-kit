#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# colour_check.py
# Purpose : Can a colour-blind player tell the game's important colours apart? Checks the pairs a game declares in
#           data/access/colours.json (player vs enemy, hazard vs floor) under protanopia, deuteranopia and tritanopia,
#           each in the palette the game's colour-blind setting switches to (or the normal palette through the kit's
#           colour-blind filter, when the game uses it), and shows a screenshot as each player sees it.
# Usage   : python tools/access/colour_check.py pairs                     # the game's declared pairs (exit 1 if one fails)
#           python tools/access/colour_check.py pairs --data other.json
#           python tools/access/colour_check.py image shot.png --out sim/  # shot_protanopia.png ... for a look
#           python tools/access/colour_check.py -h
# Notes   : Standard library only (colour.py next to it holds the maths and its sources). A pair passes when its
#           CIEDE2000 difference, as that player sees it, is at least the file's min_delta_e. No published rule sets
#           that number for game art: the kit starts at 20 (about twice the "visible at a glance" end of the usual
#           CIEDE2000 scale, because game marks are small and move), a tip to raise if playtesters mix the pairs up.
#           Achromatopsia (no colour at all) has no setting in the shell: its pairs are reported, never failed, as a
#           reminder that a shape or label is the fix that works for everyone (SOP-20).
#           Exit codes: 0 every pair passes (or none declared), 1 a pair fails, 2 a usage or file problem.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import colour  # noqa: E402

DEFAULT_DATA = "data/access/colours.json"
MODES = ("none", "protanopia", "deuteranopia", "tritanopia")   # the shell's colorblind setting (normal vision first)
REPORT_ONLY = ("achromatopsia",)
DEFAULT_MIN = 20.0


class UsageError(Exception):
    pass


def dbg(args, msg):
    if args.debug:
        print(f"[debug] {msg}", file=sys.stderr)


def load(path):
    """The game's colour data, checked: {"min_delta_e", "filter", "pairs": [(a, b)], "palettes": {mode: {name: rgb}}}."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise UsageError(f"{path} not found: copy the kit's data/access/colours.json and declare your pairs")
    except (OSError, ValueError) as e:
        raise UsageError(f"{path}: {e}")
    if not isinstance(d, dict):
        raise UsageError(f"{path}: not a JSON object")
    pal = d.get("palettes")
    if not isinstance(pal, dict) or not isinstance(pal.get("none"), dict):
        raise UsageError(f"{path}: needs palettes.none (the colours with the colour-blind setting off)")
    out = {"min_delta_e": float(d.get("min_delta_e", DEFAULT_MIN)), "filter": bool(d.get("filter", False)),
           "pairs": [], "palettes": {}}
    for mode, colours in pal.items():
        if mode not in MODES:
            raise UsageError(f"{path}: palettes.{mode}: the setting has no such mode ({', '.join(MODES)})")
        if not isinstance(colours, dict):
            raise UsageError(f"{path}: palettes.{mode} is not an object")
        try:
            out["palettes"][mode] = {k: colour.parse(v) for k, v in colours.items()}
        except ValueError as e:
            raise UsageError(f"{path}: palettes.{mode}: {e}")
    for i, p in enumerate(d.get("pairs") or []):
        if not (isinstance(p, list) and len(p) == 2 and all(isinstance(x, str) for x in p)):
            raise UsageError(f"{path}: pairs[{i}] is not two colour names")
        for mode, colours in out["palettes"].items():
            for name in p:
                if name not in colours:
                    raise UsageError(f"{path}: pairs[{i}] names {name!r}, which palettes.{mode} lacks")
        out["pairs"].append(tuple(p))
    return out


def seen(data, mode, name):
    """The colour `name` as a player with `mode` sees it with the setting on that mode."""
    pal = data["palettes"].get(mode)
    c = (pal or data["palettes"]["none"])[name]
    if pal is None and data["filter"] and mode in colour.MACHADO:
        c = colour.daltonize(c, mode)
    return colour.simulate(c, mode)


def check_pairs(data):
    """[(mode, a, b, difference, ok)] for every declared pair; achromatopsia rows have ok None (reported only)."""
    rows = []
    for mode in MODES + REPORT_ONLY:
        for a, b in data["pairs"]:
            if mode in REPORT_ONLY:
                d = colour.difference(colour.simulate(data["palettes"]["none"][a], mode),
                                      colour.simulate(data["palettes"]["none"][b], mode))
                rows.append((mode, a, b, d, None))
            else:
                d = colour.difference(seen(data, mode, a), seen(data, mode, b))
                rows.append((mode, a, b, d, d >= data["min_delta_e"]))
    return rows


def cmd_pairs(args):
    data = load(args.data)
    if not data["pairs"]:
        print(f"[warn] {args.data} declares no important colour pairs: add the ones your game tells apart by colour "
              "(player vs enemy, hazard vs floor)")
        return 0
    how = "the filter" if data["filter"] else "each mode's palette"
    print(f"[info] {len(data['pairs'])} pairs, {how}, pass at CIEDE2000 >= {data['min_delta_e']:g}")
    failed = 0
    for mode, a, b, d, ok in check_pairs(data):
        mark = "[info]" if ok is None else "[ OK ]" if ok else "[FAIL]"
        failed += ok is False
        print(f"{mark} {mode:<13} {a} vs {b}: {d:.1f}")
    if failed:
        print(f"[FAIL] {failed} pair(s) too close: change a colour in that mode's palette, or add a shape, icon or "
              "label that tells them apart (SOP-20)")
        return 1
    print("[ OK ] every pair stays apart in every colour-blind mode")
    return 0


def cmd_image(args):
    sys.path.insert(0, str(HERE.parent))
    import image_diff
    src = Path(args.png)
    try:
        w, h, rows = image_diff.read_png(src)
    except (OSError, image_diff.ImageError) as e:
        raise UsageError(f"{src}: {e}")
    out = Path(args.out) if args.out else src.parent
    cache = {}
    for kind in colour.KINDS:
        sim = []
        for row in rows:
            line = bytearray(row)
            for x in range(w):
                px = tuple(row[4 * x:4 * x + 3])
                if px not in cache:
                    cache[px] = {k: colour.simulate(px, k) for k in colour.KINDS}
                line[4 * x:4 * x + 3] = bytes(cache[px][kind])
            sim.append(line)
        dest = out / f"{src.stem}_{kind}{src.suffix}"
        image_diff.write_png(dest, w, h, sim)
        print(f"[ OK ] {dest}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Check that the game's important colour pairs stay apart for colour-blind players, or show a "
                    "screenshot as they see it.",
        epilog="Exit codes: 0 ok, 1 a pair is too close, 2 usage or file problem. The maths and its sources: "
               "tools/access/colour.py. SOP-20 says what the colour rule is.")
    p.add_argument("--debug", action="store_true", help="print tracebacks and extra detail")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("pairs", help="check the pairs in data/access/colours.json")
    s.add_argument("--data", default=DEFAULT_DATA, help=f"the colour data file (default {DEFAULT_DATA})")
    s.add_argument("--debug", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    s = sub.add_parser("image", help="write a PNG as each colour-blind player sees it")
    s.add_argument("png", help="a screenshot (smoke --screenshot writes them)")
    s.add_argument("--out", help="folder for the simulated pictures (default: next to the screenshot)")
    s.add_argument("--debug", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return {"pairs": cmd_pairs, "image": cmd_image}[args.cmd](args)
    except UsageError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 - one line for the user, the traceback with --debug
        if args.debug:
            raise
        print(f"[error] unexpected failure: {type(e).__name__}: {e} (run with --debug for the traceback)",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
