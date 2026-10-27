#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# frames_to_gif.py
# Purpose : Turn a folder of numbered PNG frames into a small looping GIF for a
#           README, a store page draft, or a bug report.
# Usage   : python tools/art/frames_to_gif.py <frames-dir> <out.gif> [--fps 15] [--every 1]
#                [--width 480] [--colors 64] [--overwrite] [--debug]
#           Where frames come from:
#             web:   python tools/dev.py smoke --query autoplay --until ESCAPED --record build/frames
#             Godot: godot --path . --write-movie build/frames/f.png --fixed-fps 30 -- --autoplay
# Needs   : Python 3.8+, Pillow (pip install pillow)
# Exit    : 0 ok, 1 no frames or a frame could not be read, 2 usage/environment problem
# Notes   : Frames are taken in file-name order (zero-padded names sort correctly).
#           --every 2 keeps every second frame (halves the size of a 30 fps recording).
#           --width scales down with nearest-neighbor, so pixel art stays crisp.
#           GIFs get big fast: keep clips under about 10 s, 480 px wide, 64 colors.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   list *.png and *.bmp in frames-dir (BMP: the C++ overlay's smoke --record), sorted; keep every Nth
#   for each: open, convert to RGB, scale to --width (nearest), quantize to --colors
#   save as an animated GIF, duration 1000/fps ms per frame, loop forever
import argparse
import sys
from pathlib import Path

DEBUG = False


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


def build_gif(frames, out, fps, width, colors, Image):
    """Write the GIF. Returns the number of frames written."""
    images = []
    for f in frames:
        im = Image.open(f).convert("RGB")
        if width and im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.NEAREST)
        images.append(im.quantize(colors=colors, method=getattr(Image, "Quantize", Image).MEDIANCUT))  # Pillow 9.1+ and older
        dbg(f"frame {f.name} {im.size}")
    images[0].save(out, save_all=True, append_images=images[1:], duration=round(1000 / fps), loop=0, optimize=True)
    return len(images)


def main(argv=None):
    global DEBUG
    ap = argparse.ArgumentParser(description="Make a looping GIF from a folder of PNG frames.")
    ap.add_argument("frames", help="folder with the PNG frames")
    ap.add_argument("out", help="output .gif path")
    ap.add_argument("--fps", type=float, default=15.0, help="playback frames per second (default 15)")
    ap.add_argument("--every", type=int, default=1, help="keep every Nth frame (default 1 = all)")
    ap.add_argument("--width", type=int, default=480, help="scale down to this width, 0 = keep (default 480)")
    ap.add_argument("--colors", type=int, default=64, help="palette size 2..256 (default 64)")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing output file")
    ap.add_argument("--debug", action="store_true", help="print each frame as it is processed")
    args = ap.parse_args(argv)
    DEBUG = args.debug
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        from PIL import Image
    except ImportError:
        print("[error] Pillow is required: pip install pillow", file=sys.stderr)
        return 2
    src, out = Path(args.frames), Path(args.out)
    if not src.is_dir():
        print(f"[error] not a folder: {src}", file=sys.stderr)
        return 2
    if out.suffix.lower() != ".gif":
        print("[error] output must end in .gif", file=sys.stderr)
        return 2
    if out.exists() and not args.overwrite:
        print(f"[error] {out} exists (use --overwrite)", file=sys.stderr)
        return 2
    if args.fps <= 0 or args.every < 1 or not 2 <= args.colors <= 256 or args.width < 0:
        print("[error] need --fps > 0, --every >= 1, --colors 2..256, --width >= 0", file=sys.stderr)
        return 2
    frames = sorted([*src.glob("*.png"), *src.glob("*.bmp")])[:: args.every]
    if not frames:
        print(f"[error] no .png or .bmp frames in {src}", file=sys.stderr)
        return 1
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        n = build_gif(frames, out, args.fps, args.width, args.colors, Image)
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    print(f"[ OK ] {out}: {n} frames, {out.stat().st_size // 1024} KB, {n / args.fps:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
