#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# make_sprites.py
# Purpose : Render every game sprite from the Kenney 3D sources in assets_src/ with the kit's
#           tools/blender/render_sprites.py, from one table (JOBS), so the art can be rebuilt
#           the same way after any change.
# Usage   : python tools/make_sprites.py                 # all jobs
#           python tools/make_sprites.py hull_player     # only the named jobs
#           python tools/make_sprites.py --list
#           BPY_PYTHON=<python with bpy> python tools/make_sprites.py   (default: uv run --python 3.13 --with bpy python)
# Notes   : Every sprite uses --pivot origin, so the model's origin (the bottom center for these
#           Kenney models) is the cell center, and a fixed --world-size per job, so scale is known
#           (render_sprites writes pixels_per_meter into each JSON). Hulls set the game's scale; turrets
#           and cover are rendered larger on purpose (toy proportions): see SCALE NOTES below.
#           Camera: ELEVATION degrees above the ground, the same for every job so all sprites match.
# Exit    : 0 all rendered, 1 a render failed, 2 setup problem
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import argparse
import os
import shlex
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


def bpy_python():
    custom = os.environ.get("BPY_PYTHON")
    return shlex.split(custom) if custom else ["uv", "run", "--python", "3.13", "--with", "bpy", "python"]


def render(name, src, world, directions, elevation=ELEVATION, size=SIZE):
    cmd = bpy_python() + ["-B", str(TOOL), str(ROOT / src), "--out", str(OUT / f"{name}.png"),
                          "--directions", str(directions), "--size", str(size), "--world-size", str(world),
                          "--pivot", "origin", "--elevation", str(elevation), "--samples", str(SAMPLES), "--overwrite"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = [l for l in (proc.stdout + proc.stderr).splitlines() if l.startswith("[")]
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
    OUT.mkdir(parents=True, exist_ok=True)
    failed = 0
    for name, (src, world, dirs) in JOBS.items():
        if not args.only or name in args.only:
            failed += render(name, src, world, dirs) != 0
    if not args.only or GROUND[0] in args.only:
        failed += render(GROUND[0], GROUND[1], GROUND[2], 1, elevation=90, size=GROUND[3]) != 0
    if failed:
        print(f"[error] {failed} render(s) failed", file=sys.stderr)
        return 1
    print(f"[ OK ] sprites in {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
