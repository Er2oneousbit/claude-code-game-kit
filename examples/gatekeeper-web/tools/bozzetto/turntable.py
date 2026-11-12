#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# turntable.py
# Purpose : A quick look at a 3D model from every side: one contact sheet PNG of N views around it (default 8, in
#           2 rows of 4), and optionally a folder of frames for a turntable GIF or video.
# Usage   : Inside Blender (any OS):
#             blender -b --python-exit-code 1 -P tools/bozzetto/turntable.py -- <model.glb> --out <sheet.png> [options]
#           With the bpy module:
#             python tools/bozzetto/turntable.py <model.glb> --out <sheet.png> [options]
#           Examples:
#             ... -- assets/models/prop_chest.glb --out assets_src/bozzetto/prop_chest/turntable.png
#             ... -- chest.glb --out chest.png --frames-dir build/chest_frames --frames 36 --background "#d8d8d8"
#             then: python tools/art/frames_to_gif.py build/chest_frames chest.gif --fps 12 --width 240
# Needs   : Blender 4.2+ or the bpy module. Cycles renders on the CPU, so no GPU is needed.
# Exit    : 0 written, 1 render failed, 2 usage or environment
# Notes   : Camera, light and framing are tools/blender/render_sprites.py's (imported, not copied): orthographic,
#           a key light that turns with the camera, the same framing in every view. View 0 is the front (camera on
#           -Y, glTF's +Z front); the next views turn counter-clockwise seen from above.
#           Transparent background unless --background (a GIF has no partial transparency).
#           With the bpy module on Windows the process is ended through render_sprites.exit_with (#292): a plain exit
#           after a render crashed and hid the exit code.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): the bpy module's exit crash (#292)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   import the model (render_sprites' importer: drops bone shapes and back-to-back twin faces)
#   bounds -> ortho width -> render_sprites.setup_scene (camera + key light + ambient)
#   for each of --views angles: place the camera, render a cell -> stitch into rows x --cols
#   --frames-dir: --frames more angles, each saved as f_000.png ...
#   --background: composite every image over that colour
import argparse
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "blender"))

DEBUG = False
MARGIN = 0.08


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}")


def script_argv():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else argv[1:]


def hex_color(text):
    t = text.lstrip("#")
    if len(t) != 6:
        raise argparse.ArgumentTypeError(f"colour must look like #d8d8d8, got {text!r}")
    try:
        return tuple(int(t[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        raise argparse.ArgumentTypeError(f"colour must look like #d8d8d8, got {text!r}")


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="turntable.py", description="Render a model from every side: a contact sheet, "
                                                                  "and optionally turntable frames.")
    ap.add_argument("asset", help="model: .glb .gltf .fbx .obj .blend")
    ap.add_argument("--out", required=True, help="contact sheet PNG")
    ap.add_argument("--views", type=int, default=8, help="views on the sheet (default 8)")
    ap.add_argument("--cols", type=int, default=4, help="views per row (default 4)")
    ap.add_argument("--size", type=int, default=256, help="pixels per view, square (default 256)")
    ap.add_argument("--elevation", type=float, default=20.0, help="camera pitch in degrees (default 20)")
    ap.add_argument("--frames-dir", help="also render turntable frames into this folder (f_000.png, ...)")
    ap.add_argument("--frames", type=int, default=36, help="frames for --frames-dir (default 36, 10 degrees each)")
    ap.add_argument("--background", type=hex_color, help="flatten onto this colour, e.g. #d8d8d8 (default transparent)")
    ap.add_argument("--engine", choices=("cycles", "eevee", "workbench"), default="cycles",
                    help="render engine (default cycles on the CPU)")
    ap.add_argument("--samples", type=int, default=16, help="Cycles samples (default 16)")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing sheet")
    ap.add_argument("--debug", action="store_true", help="verbose output")
    args = ap.parse_args(argv)
    if not 1 <= args.views <= 64 or not 1 <= args.cols <= 64 or not 16 <= args.size <= 2048 or not 1 <= args.frames <= 720:
        ap.error("need 1 <= --views <= 64, 1 <= --cols <= 64, 16 <= --size <= 2048, 1 <= --frames <= 720")
    return args


def flatten(bpy, path, rgb):
    """Composite an RGBA PNG over a solid colour, in place."""
    import numpy as np
    img = bpy.data.images.load(str(path))
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(-1, 4)
    a = px[:, 3:4]
    px[:, :3] = px[:, :3] * a + np.array(rgb, dtype=np.float32) * (1 - a)
    px[:, 3] = 1.0
    img.pixels.foreach_set(px.ravel())
    img.filepath_raw = str(path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def render_to(bpy, scene, path):
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    if not Path(path).exists():
        raise RuntimeError(f"render produced no image ({path})")


def run(args):
    src, out = Path(args.asset), Path(args.out)
    if not src.is_file():
        print(f"[ENV ] model not found: {src}", file=sys.stderr)
        return 2
    if out.suffix.lower() != ".png":
        print("[ENV ] --out must end in .png", file=sys.stderr)
        return 2
    if out.exists() and not args.overwrite:
        print(f"[ENV ] {out} exists (use --overwrite)", file=sys.stderr)
        return 2
    try:
        import bpy
    except ImportError:
        print("[ENV ] bpy not available: run inside Blender (blender -b --python-exit-code 1 -P ...) or with the bpy "
              "module", file=sys.stderr)
        return 2
    import render_sprites as rs
    try:
        rs.import_asset(bpy, src.resolve())
    except ValueError as exc:
        print(f"[ENV ] {exc}", file=sys.stderr)
        return 2
    scene = bpy.context.scene
    center, radius, _, _ = rs.scene_bounds(bpy, scene, [scene.frame_current])
    if center is None:
        print("[FAIL] no mesh in the file", file=sys.stderr)
        return 1
    opts = SimpleNamespace(engine=args.engine, samples=args.samples, pixel_art=False, size=args.size)
    cam = rs.setup_scene(bpy, scene, opts, radius, 2 * radius * (1 + MARGIN))
    rows = (args.views + args.cols - 1) // args.cols
    cols = min(args.cols, args.views)
    cells = {}
    with tempfile.TemporaryDirectory(prefix="turntable_") as tmp:
        for i in range(args.views):
            rs.place_camera(cam, center, radius, i * 360.0 / args.views, args.elevation)
            cell = Path(tmp) / f"v{i:02d}.png"
            render_to(bpy, scene, cell)
            cells[(i // cols, i % cols)] = cell
            dbg(f"view {i} rendered")
        out.parent.mkdir(parents=True, exist_ok=True)
        rs.stitch(bpy, cells, rows, cols, args.size, out.resolve())
    if args.background:
        flatten(bpy, out.resolve(), args.background)
    print(f"[ OK ] {out}: {args.views} views in {rows} x {cols}, {args.size} px each")
    if args.frames_dir:
        fdir = Path(args.frames_dir)
        fdir.mkdir(parents=True, exist_ok=True)
        for i in range(args.frames):
            rs.place_camera(cam, center, radius, i * 360.0 / args.frames, args.elevation)
            f = (fdir / f"f_{i:03d}.png").resolve()
            render_to(bpy, scene, f)
            if args.background:
                flatten(bpy, f, args.background)
        print(f"[ OK ] {args.frames} turntable frames in {fdir}")
    return 0


def main():
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        args = parse_args(script_argv())
    except SystemExit as exc:
        return int(exc.code or 0)
    DEBUG = args.debug
    try:
        return run(args)
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # keep the exit-code contract even on surprises
        print(f"[ENV ] turntable crashed: {exc!r}. Re-run with --debug and paste the output.", file=sys.stderr)
        if DEBUG:
            raise
        return 2


if __name__ == "__main__":
    _code = main()
    try:
        import render_sprites as _rs   # its exit_with: the bpy module crashes on a plain exit after a render (#292)
        _rs.exit_with(_code)
    except ImportError:
        sys.exit(_code)
