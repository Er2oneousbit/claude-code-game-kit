#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# make_sprites.py
# Purpose : Render every game sprite from the Kenney 3D sources in assets_src/ with the kit's
#           tools/blender/render_sprites.py, from one table (JOBS), so the art can be rebuilt
#           the same way after any change.
# Usage   : python tools/make_sprites.py                 # all jobs
#           python tools/make_sprites.py hull_player     # only the named jobs
#           python tools/make_sprites.py --list
#           python tools/make_sprites.py --debug crate   # print the command and all of Blender's output
#           BPY_PYTHON=<python with bpy> python tools/make_sprites.py   (default: uv run --python 3.13 --with bpy python)
# Notes   : Every sprite uses --pivot origin, so the model's origin (the bottom center for these
#           Kenney models) is the cell center, and a fixed --world-size per job, so scale is known
#           (render_sprites writes pixels_per_meter into each JSON). Hulls set the game's scale; turrets
#           and cover are rendered larger on purpose (toy proportions): see SCALE NOTES below.
#           Camera: ELEVATION degrees above the ground, the same for every job so all sprites match.
#           Before the first job it checks the launcher (uv, or BPY_PYTHON) and the kit tool exist. A failed
#           render that printed no [..] line (bpy not importing, uv offline) shows its last output lines.
# Exit    : 0 all rendered, 1 a render failed, 2 setup problem
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): [error] and exit 2 for a missing launcher or
#           kit tool instead of a traceback, the cause of a silent child failure, --debug (#154)
# ---------------------------------------------------------------------------
import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "blender" / "render_sprites.py"
OUT = ROOT / "assets" / "sprites"
ELEVATION = 55       # degrees; the game's ground depth scale is sin(ELEVATION)
SIZE = 112           # px per cell
DIRECTIONS = 32      # rotations for anything that turns
SAMPLES = 24         # Cycles samples per cell
TAIL_LINES = 6       # output lines shown from a render that failed without a [..] line
DEFAULT_BPY = ["uv", "run", "--python", "3.13", "--with", "bpy", "python"]

# name: (source, world size in meters per cell, directions)
# SCALE NOTES: hulls 3.6 m per cell set the game's scale (112 px / 3.6 m = 31.1 px per meter). Everything else is
# drawn at toy proportions and its cell size is solved from: drawn meters = model meters * 3.6 / world size.
#   turrets 0.6 m model -> 2.0 m cell (1.8x)      crates 0.715 m -> 1.4 (1.84 m; 1.29 would clip, kCrateR 1.0 = 2 m)
#   rocks 0.89 m -> 1.07 (3.0 m, kRocksR 1.5)     trees 0.5 m -> 1.64 (1.1 m, kTreeR 0.55)
#   scrap plate 0.9 m -> 2.7 (1.2 m)              tire 0.6 m -> 2.2 (1.0 m)      shell 0.28 m -> 2.5 (0.4 m)
JOBS = {
    "hull_player": ("assets_src/car-kit/tractor.glb", 3.6, DIRECTIONS),
    "hull_enemy": ("assets_src/car-kit/tractor-police.glb", 3.6, DIRECTIONS),
    "hull_heavy": ("assets_src/car-kit/tractor-shovel.glb", 3.6, DIRECTIONS),
    "turret_player": ("assets_src/tower-defense-kit/weapon-cannon.glb", 2.0, DIRECTIONS),
    "turret_enemy": ("assets_src/tower-defense-kit/weapon-turret.glb", 2.0, DIRECTIONS),
    "crate": ("assets_src/car-kit/box.glb", 1.4, 1),
    "rocks": ("assets_src/tower-defense-kit/detail-rocks-large.glb", 1.07, 1),
    "tree": ("assets_src/tower-defense-kit/detail-tree-large.glb", 1.64, 1),
    "scrap_plate": ("assets_src/car-kit/debris-plate-a.glb", 2.7, 1),
    "scrap_tire": ("assets_src/car-kit/debris-tire.glb", 2.2, 1),
    "shell": ("assets_src/tower-defense-kit/weapon-ammo-cannonball.glb", 2.5, 1),
}
# The ground tile is seen from straight above and drawn squashed by the game.
GROUND = ("ground", "assets_src/tower-defense-kit/tile.glb", 1.0, 64)


class SetupError(Exception):
    """The renderer cannot start at all (exit 2), as opposed to one render failing (exit 1)."""


def bpy_python():
    custom = os.environ.get("BPY_PYTHON")
    if not custom:
        return list(DEFAULT_BPY)
    # Windows paths keep their backslashes (POSIX splitting would eat them); quotes around a part are dropped
    parts = shlex.split(custom, posix=os.name != "nt")
    return [p[1:-1] if len(p) > 1 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]


def check_setup(launcher):
    """Raise SetupError when the bpy launcher or the kit's render tool is missing."""
    if not launcher or shutil.which(launcher[0]) is None:
        name = launcher[0] if launcher else ""
        if os.environ.get("BPY_PYTHON"):
            raise SetupError(f"cannot find '{name}' (from BPY_PYTHON): point it at a Python that has the bpy module")
        raise SetupError(f"cannot find '{name}' on PATH: install uv (https://docs.astral.sh/uv/) or set BPY_PYTHON "
                         "to a Python that has the bpy module")
    if not TOOL.is_file():
        raise SetupError(f"the kit's render tool is missing: {TOOL.relative_to(ROOT).as_posix()}")


def render(name, src, world, directions, elevation=ELEVATION, size=SIZE, debug=False):
    cmd = bpy_python() + ["-B", str(TOOL), str(ROOT / src), "--out", str(OUT / f"{name}.png"),
                          "--directions", str(directions), "--size", str(size), "--world-size", str(world),
                          "--pivot", "origin", "--elevation", str(elevation), "--samples", str(SAMPLES), "--overwrite"]
    if debug:
        print(f"  {name}: [debug] {subprocess.list2cmdline(cmd)}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        raise SetupError(f"cannot start '{cmd[0]}': {e}") from e
    output = (proc.stdout + proc.stderr).splitlines()
    lines = output if debug else [l for l in output if l.startswith("[")]
    if proc.returncode != 0 and not lines:
        # It failed before render_sprites.py said anything: show why
        lines = [f"[error] exit {proc.returncode}, last output:"] + output[-TAIL_LINES:]
    for l in lines:
        print(f"  {name}: {l}")
    return proc.returncode


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Render all game sprites from assets_src/ with render_sprites.py.")
    ap.add_argument("only", nargs="*", help="job names to render (default: all, plus the ground)")
    ap.add_argument("--list", action="store_true", help="print the jobs and exit")
    ap.add_argument("--debug", action="store_true", help="print each render command and all of its output")
    args = ap.parse_args()
    if args.list:
        for name, (src, world, dirs) in JOBS.items():
            print(f"{name:14s} {src}  {world} m per cell, {dirs} direction(s)")
        print(f"{GROUND[0]:14s} {GROUND[1]}  top-down")
        return 0
    unknown = [n for n in args.only if n not in JOBS and n != GROUND[0]]
    if unknown:
        print(f"[error] unknown job(s): {', '.join(unknown)} (see --list)", file=sys.stderr)
        return 2
    failed = 0
    try:
        check_setup(bpy_python())
        OUT.mkdir(parents=True, exist_ok=True)
        for name, (src, world, dirs) in JOBS.items():
            if not args.only or name in args.only:
                failed += render(name, src, world, dirs, debug=args.debug) != 0
        if not args.only or GROUND[0] in args.only:
            failed += render(GROUND[0], GROUND[1], GROUND[2], 1, elevation=90, size=GROUND[3], debug=args.debug) != 0
    except SetupError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2
    if failed:
        print(f"[error] {failed} render(s) failed", file=sys.stderr)
        return 1
    print(f"[ OK ] sprites in {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
