#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# access.py
# Purpose : The audio accessibility rules every engine follows, as a reference with golden vectors
#           (data/golden/access.json): which settings slider turns which bus of data/audio_events.json up or down
#           (never twice down one branch), and which arrow a directional caption gets for a sound off screen.
# Usage   : python tools/audio/wavesmith/wavesmith.py access gains data/audio_events.json --sfx 0.5 --voice 0.8
#           python tools/audio/wavesmith/wavesmith.py access arrow --dx 900 --dy 120 --half-w 320 --half-h 180
#           python tools/audio/wavesmith/wavesmith.py access vectors --check       # golden file current? (exit 1)
#           python tools/audio/wavesmith/wavesmith.py access vectors --write       # after changing a rule
# Needs   : Python 3.8+ only
# Exit    : 0 ok, 1 stale vectors, 2 usage or unreadable files
# Notes   : Sliders are linear 0..1 (settings.audio: master, music, sfx, ui, voice). A bus follows the slider named
#           in SLIDER_FOR_BUS; when one of its parents already follows the same slider it gets 1 (ambience under sfx
#           is not turned down twice); buses without a slider get 1; bad values clamp to 0..1 and a missing or
#           non-numeric one counts as 1. Parents default to "master" (master has none); a cycle stops after one step
#           per bus. Arrows: screen coordinates (y grows downwards); nothing while the source is inside the view
#           (edges included); otherwise direction k = floor(atan2(dy, dx) / 45 degrees + 0.5) mod 8, clockwise from
#           the right: 0 right, 1 down-right, 2 down, 3 down-left, 4 left, 5 up-left, 6 up, 7 up-right. floor(x + 0.5)
#           is the rule in every language (Python's round() rounds halves to even; Rust's rounds them away from 0).
#           The golden points avoid the exact 22.5 degree boundaries, where atan2 libraries may differ in the last bit.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   gains: for each bus: slider = SLIDER_FOR_BUS[bus]; walk the parents; a parent with the same slider -> 1;
#          no slider -> 1; else clamp(slider value)
#   arrow: inside the half sizes -> none; else k from atan2 -> ARROWS[k]
#   vectors: scripted bus trees and points through the rules -> data/golden/access.json (--write / --check)
import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLDEN = HERE.parents[2] / "data" / "golden" / "access.json"
SLIDERS = ("master", "music", "sfx", "ui", "voice")
SLIDER_FOR_BUS = {"master": "master", "music": "music", "sfx": "sfx", "ambience": "sfx", "ui": "ui",
                  "dialogue": "voice", "voice": "voice"}
ARROWS = ("→", "↘", "↓", "↙", "←", "↖", "↑", "↗")      # k = 0..7, clockwise from the right (y down)


class ToolError(Exception):
    """Exit 2: usage or a file that cannot be read."""


def clamp01(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return 1.0
    return min(1.0, max(0.0, float(v)))


def user_bus_gains(buses, sliders, mapping=None):
    """{bus: linear gain} from the player's sliders, a slider never applied twice down one branch."""
    mapping = SLIDER_FOR_BUS if mapping is None else mapping
    if not isinstance(buses, dict):
        raise ValueError("buses must be an object of bus name -> {parent}")
    names = list(buses)

    def parent_of(b):
        entry = buses.get(b)
        p = entry.get("parent") if isinstance(entry, dict) else None   # a malformed bus counts as under master
        return p if isinstance(p, str) else (None if b == "master" else "master")
    out = {}
    for name in names:
        slider = mapping.get(name)
        inherited = False
        p, n = parent_of(name), 0
        while p is not None and n < len(names):
            if slider is not None and mapping.get(p) == slider:
                inherited = True
            p, n = parent_of(p), n + 1
        out[name] = 1.0 if slider is None or inherited else clamp01(sliders.get(slider))
    return out


def caption_direction(dx, dy, half_w, half_h):
    """-1 while the source is inside the view (edges included), else 0..7 clockwise from the right."""
    if not (math.isfinite(dx) and math.isfinite(dy)):
        return -1
    if abs(dx) <= half_w and abs(dy) <= half_h:
        return -1
    return math.floor(math.atan2(dy, dx) / (math.pi / 4) + 0.5) % 8


def caption_arrow(dx, dy, half_w, half_h):
    k = caption_direction(dx, dy, half_w, half_h)
    return "" if k < 0 else ARROWS[k]


# ---- Golden vectors ----------------------------------------------------------------------------------------------
def vector_cases():
    full = {"master": {}, "music": {"parent": "master"}, "sfx": {"parent": "master"}, "ui": {"parent": "master"},
            "dialogue": {"parent": "master"}, "ambience": {"parent": "master"}}
    nested = {"master": {}, "sfx": {"parent": "master"}, "ambience": {"parent": "sfx"}, "foley": {"parent": "sfx"},
              "stingers": {"parent": "music"}, "music": {}}
    voice_tree = {"master": {}, "voice": {}, "dialogue": {"parent": "voice"}, "barks": {"parent": "dialogue"}}
    cycle = {"a": {"parent": "b"}, "b": {"parent": "a"}}
    odd_parent = {"master": {}, "sfx": {"parent": 7}, "ui": {"parent": None}}   # not text: under master
    s1 = {"master": 0.9, "music": 0.5, "sfx": 0.25, "ui": 0.75, "voice": 0.6}
    bad = {"master": 2, "music": -1, "sfx": "loud", "ui": None, "voice": 0.5}
    gains = [{"buses": b, "sliders": s, "expect": user_bus_gains(b, s)}
             for b, s in ((full, s1), (nested, s1), (voice_tree, s1), (full, bad), (cycle, s1),
                          ({"master": {}, "music": {}}, {}), (odd_parent, s1))]
    w, h = 320, 180
    pts = [(0, 0), (320, -180), (-320, 180), (321, 0), (500, 0), (-500, 0), (0, -400), (0, 400), (500, 500),
           (-500, 500), (-500, -500), (500, -500), (900, 120), (-900, 300), (100, -181), (2000, -1999), (-3, 900),
           (640.5, -0.25)]
    arrows = [{"dx": dx, "dy": dy, "half_w": w, "half_h": h, "dir": caption_direction(dx, dy, w, h),
               "arrow": caption_arrow(dx, dy, w, h)} for dx, dy in pts]
    return [{"type": "access_gains", "name": "slider gains per bus", "steps": gains},
            {"type": "access_arrow", "name": "caption arrows", "steps": arrows}]


def render_vectors():
    return json.dumps({"version": 1, "tolerance": 1e-9, "about": "tools/audio/wavesmith/access.py vectors --write",
                       "arrows": list(ARROWS), "cases": vector_cases()}, indent=1, ensure_ascii=False) + "\n"


# ---- Commands ----------------------------------------------------------------------------------------------------
def cmd_gains(args):
    try:
        data = json.loads(Path(args.events).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolError(f"cannot read {args.events}: {exc}")
    buses = data.get("buses") if isinstance(data, dict) else None
    if not isinstance(buses, dict) or not buses:
        raise ToolError(f"{args.events} has no buses")
    bad = [name for name, b in buses.items() if not isinstance(b, dict)]
    if bad:
        raise ToolError(f"{args.events}: bus {bad[0]} must be an object, e.g. {{\"parent\": \"master\"}} "
                        f"(events validate names every problem)")
    sliders = {s: getattr(args, s) for s in SLIDERS}
    for bus, g in user_bus_gains(buses, sliders).items():
        slider = SLIDER_FOR_BUS.get(bus)
        why = "no slider" if slider is None else (f"{slider} slider" if g == clamp01(sliders[slider]) else
                                                  f"{slider} slider already on a parent bus")
        print(f"{bus:12} x {g:.3f}   ({why})")
    return 0


def cmd_arrow(args):
    k = caption_direction(args.dx, args.dy, args.half_w, args.half_h)
    print("on screen: no arrow" if k < 0 else f"{ARROWS[k]} (direction {k})")
    return 0


def cmd_vectors(args):
    text = render_vectors()
    if args.write:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_bytes(text.encode("utf-8"))
        print(f"[ OK ] wrote {GOLDEN}")
        return 0
    current = GOLDEN.read_bytes().decode("utf-8") if GOLDEN.exists() else None
    if current != text:
        print(f"[FAIL] {GOLDEN} is stale or missing: run access.py vectors --write")
        return 1
    print(f"[ OK ] {GOLDEN} is current")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description="Audio accessibility rules: slider gains per bus and caption arrows, "
                                             "with the golden vectors every engine follows.",
                                 epilog="Exit codes: 0 ok, 1 stale vectors, 2 usage or unreadable files.")
    sub = ap.add_subparsers(dest="cmd")
    g = sub.add_parser("gains", help="what each bus of an audio_events.json gets from the sliders")
    g.add_argument("events")
    for s in SLIDERS:
        g.add_argument(f"--{s}", type=float, default=1.0, help=f"the {s} slider, 0..1 (default 1)")
    a = sub.add_parser("arrow", help="the arrow for a sound at (dx, dy) from the view's centre")
    for opt in ("--dx", "--dy", "--half-w", "--half-h"):
        a.add_argument(opt, type=float, required=True)
    v = sub.add_parser("vectors", help="data/golden/access.json: --check (default) or --write")
    v.add_argument("--write", action="store_true")
    v.add_argument("--check", action="store_true")
    return ap


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2
    try:
        return {"gains": cmd_gains, "arrow": cmd_arrow, "vectors": cmd_vectors}[args.cmd](args)
    except ToolError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
