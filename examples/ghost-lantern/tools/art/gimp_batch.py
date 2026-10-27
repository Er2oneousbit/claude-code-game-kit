#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# gimp_batch.py
# Purpose : Batch-process art with GIMP 3, headless: flatten layered .xcf/.psd files,
#           resize (crisp for pixel art), reduce to an indexed palette, and export
#           PNG/JPG/WebP. One GIMP process handles the whole batch.
# Usage   : python tools/art/gimp_batch.py <file-or-folder> [...] --out DIR [options]
#           Examples:
#             python tools/art/gimp_batch.py assets_src/sprites --out assets/art --format png
#             python tools/art/gimp_batch.py hero.xcf --out assets/art --width 64 --interpolation none
#             python tools/art/gimp_batch.py tiles/ --out assets/art --scale 50 --indexed 16
# Needs   : GIMP 3.x with its Python support (an install option on Windows). Python 3.8+, stdlib only.
#           GIMP is found via GIMP_CONSOLE, PATH, or the default Windows install folders
#           (%LOCALAPPDATA%\Programs\GIMP 3\bin for a per-user install, %ProgramFiles%\GIMP 3\bin).
# Exit    : 0 every file done, 1 some file failed, 2 usage/environment problem (GIMP missing, Python missing)
# Notes   : Layers are merged with transparency kept (--no-alpha flattens onto the background).
#           --width or --height alone keeps the aspect ratio; --scale is a percentage.
#           --interpolation none keeps pixel art hard-edged; cubic (default) suits painted art.
#           --indexed N converts to an N-color palette without dithering (add --dither for Floyd-Steinberg).
#           The FIRST GIMP run on a machine can take minutes (it builds caches); later runs take seconds.
#           Paths reach GIMP through environment variables and a job file, never through its command
#           line, so spaces and backslashes are safe. Never overwrites without --overwrite.
#           Tested with GIMP 3.2.6 on Windows (tools/art/test_gimp_batch.py).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   collect input files; plan outputs (refuse clashes and overwrites)
#   write jobs.json + the GIMP-side script to a temp folder
#   gimp-console -i -d -f --batch-interpreter=python-fu-eval -b "exec(script)" --quit
#     GIMP side, per job: load -> merge visible (or flatten) -> scale -> indexed -> export -> delete
#     record ok/error per job into results.json (one bad file never stops the batch)
#   read results.json, print per-file lines, map GIMP's exit codes (64 script error, 69 no Python)
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEBUG = False
INPUT_EXT = {".xcf", ".png", ".jpg", ".jpeg", ".psd", ".webp", ".tif", ".tiff", ".bmp", ".tga", ".gif"}
FORMATS = ("png", "jpg", "webp")
INTERPOLATION = ("none", "linear", "cubic", "nohalo", "lohalo")
CONSOLE_NAMES = ("gimp-console-3", "gimp-console-3.2", "gimp-console-3.0", "gimp-console")
TIMEOUT_S = 900          # the first run on a machine builds caches for minutes
EXIT_MEANING = {64: "the GIMP-side script raised an error", 69: "GIMP has no Python support (reinstall with the Python component)",
                70: "GIMP reported an execution error", 130: "cancelled"}

# Runs INSIDE GIMP (python-fu-eval provides Gimp, Gio). Reads the job file, writes the result file.
GIMP_SIDE = r'''
import json, os, traceback
jobs = json.load(open(os.environ["GB_JOBS"], encoding="utf-8"))
results = []
INTERP = {"none": Gimp.InterpolationType.NONE, "linear": Gimp.InterpolationType.LINEAR,
          "cubic": Gimp.InterpolationType.CUBIC, "nohalo": Gimp.InterpolationType.NOHALO,
          "lohalo": Gimp.InterpolationType.LOHALO}
opt = jobs["options"]
Gimp.context_set_interpolation(INTERP[opt["interpolation"]])
for job in jobs["files"]:
    img = None
    try:
        img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(job["src"]))
        if img is None:
            raise RuntimeError("GIMP could not open the file")
        if opt["no_alpha"]:
            img.flatten()
        else:
            img.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
        w0, h0 = img.get_width(), img.get_height()
        w, h = w0, h0
        if opt["scale"]:
            w, h = max(1, round(w0 * opt["scale"] / 100)), max(1, round(h0 * opt["scale"] / 100))
        elif opt["width"] and opt["height"]:
            w, h = opt["width"], opt["height"]
        elif opt["width"]:
            w, h = opt["width"], max(1, round(h0 * opt["width"] / w0))
        elif opt["height"]:
            w, h = max(1, round(w0 * opt["height"] / h0)), opt["height"]
        if (w, h) != (w0, h0):
            img.scale(w, h)
        if opt["indexed"]:
            dither = Gimp.ConvertDitherType.FS if opt["dither"] else Gimp.ConvertDitherType.NONE
            if not img.convert_indexed(dither, Gimp.ConvertPaletteType.GENERATE, opt["indexed"], False, True, ""):
                raise RuntimeError("palette conversion failed")
        if not Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img, Gio.File.new_for_path(job["dst"]), None):
            raise RuntimeError("export failed")
        results.append({"src": job["src"], "ok": True, "size": [w, h]})
    except Exception as exc:
        results.append({"src": job["src"], "ok": False, "error": f"{exc}"})
    finally:
        if img is not None:
            img.delete()
json.dump(results, open(os.environ["GB_RESULT"], "w", encoding="utf-8"))
'''


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


def find_gimp():
    """Path to gimp-console, or None."""
    env = os.environ.get("GIMP_CONSOLE")
    if env and Path(env).is_file():
        return env
    for name in CONSOLE_NAMES:
        found = shutil.which(name)
        if found:
            return found
    if os.name == "nt":
        roots = [os.environ.get("LOCALAPPDATA", "") + r"\Programs\GIMP 3\bin", os.environ.get("ProgramFiles", "") + r"\GIMP 3\bin"]
        for root in roots:
            for name in CONSOLE_NAMES:
                p = Path(root) / f"{name}.exe"
                if p.is_file():
                    return str(p)
    return None


def run_gimp(gimp, script_text, env_extra, timeout=TIMEOUT_S):
    """Run GIMP-side Python in batch mode. Returns (exit code, combined output)."""
    with tempfile.TemporaryDirectory(prefix="gimp_batch_") as tmp:
        script = Path(tmp) / "gimp_side.py"
        script.write_text(script_text, encoding="utf-8")
        env = dict(os.environ, GB_SCRIPT=str(script), **env_extra)
        cmd = [gimp, "-i", "-d", "-f", "--batch-interpreter=python-fu-eval",
               "-b", "import os;exec(open(os.environ['GB_SCRIPT'],encoding='utf-8').read())", "--quit"]
        dbg("run: " + " ".join(cmd))
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", stdin=subprocess.DEVNULL, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, f"GIMP did not finish within {timeout} s"
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def collect(inputs, recursive):
    files = []
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            it = p.rglob("*") if recursive else p.iterdir()
            files += sorted(f for f in it if f.is_file() and f.suffix.lower() in INPUT_EXT)
        elif p.is_file():
            files.append(p)
        else:
            raise FileNotFoundError(raw)
    return files


def build_parser():
    ap = argparse.ArgumentParser(description="Batch-process art with GIMP 3 (flatten, resize, palette, export).")
    ap.add_argument("inputs", nargs="+", help="files or folders (.xcf .psd .png .jpg .webp .tif .bmp .tga .gif)")
    ap.add_argument("--out", required=True, help="output folder")
    ap.add_argument("--format", choices=FORMATS, default="png", help="output format (default png)")
    ap.add_argument("--width", type=int, help="target width in px (alone: keep aspect ratio)")
    ap.add_argument("--height", type=int, help="target height in px (alone: keep aspect ratio)")
    ap.add_argument("--scale", type=float, help="scale percent, e.g. 50 or 200 (instead of width/height)")
    ap.add_argument("--interpolation", choices=INTERPOLATION, default="cubic", help="resize filter; none for pixel art (default cubic)")
    ap.add_argument("--indexed", type=int, metavar="N", help="convert to an N-color palette (2..256)")
    ap.add_argument("--dither", action="store_true", help="Floyd-Steinberg dithering with --indexed")
    ap.add_argument("--no-alpha", action="store_true", help="flatten onto the background (drops transparency)")
    ap.add_argument("--recursive", action="store_true", help="include subfolders of input folders")
    ap.add_argument("--overwrite", action="store_true", help="replace existing outputs")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, run nothing")
    ap.add_argument("--timeout", type=int, default=TIMEOUT_S, help=f"seconds before giving up on GIMP (default {TIMEOUT_S})")
    ap.add_argument("--debug", action="store_true", help="print GIMP's full output")
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
    if args.scale is not None and (args.width or args.height):
        print("[error] use --scale or --width/--height, not both", file=sys.stderr)
        return 2
    if (args.scale is not None and args.scale <= 0) or (args.width or 1) < 1 or (args.height or 1) < 1:
        print("[error] sizes must be positive", file=sys.stderr)
        return 2
    if args.indexed is not None and not 2 <= args.indexed <= 256:
        print("[error] --indexed must be 2..256", file=sys.stderr)
        return 2
    try:
        files = collect(args.inputs, args.recursive)
    except FileNotFoundError as exc:
        print(f"[error] not found: {exc}", file=sys.stderr)
        return 2
    if not files:
        print("[error] no supported image files in the inputs", file=sys.stderr)
        return 2
    out_dir = Path(args.out)
    plan = [(f.resolve(), (out_dir / f"{f.stem}.{args.format}").resolve()) for f in files]
    names = [d for _, d in plan]
    if len(set(names)) != len(names):
        print("[error] two inputs would produce the same output name (same stem); split the batch", file=sys.stderr)
        return 2
    clashes = [d for s, d in plan if d.exists() and not args.overwrite or d == s]
    if clashes:
        print(f"[error] would overwrite {clashes[0]} (use --overwrite; never the source itself)", file=sys.stderr)
        return 2
    if args.dry_run:
        for s, d in plan:
            print(f"[dry-run] {s} -> {d}")
        return 0
    gimp = find_gimp()
    if not gimp:
        print("[error] GIMP 3 console not found. Install GIMP 3 (gimp.org; on Windows: winget install GIMP.GIMP.3) "
              "or set GIMP_CONSOLE to gimp-console-3.exe", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    options = {"width": args.width, "height": args.height, "scale": args.scale, "interpolation": args.interpolation,
               "indexed": args.indexed, "dither": args.dither, "no_alpha": args.no_alpha}
    with tempfile.TemporaryDirectory(prefix="gimp_jobs_") as tmp:
        jobs, result = Path(tmp) / "jobs.json", Path(tmp) / "results.json"
        jobs.write_text(json.dumps({"options": options, "files": [{"src": str(s), "dst": str(d)} for s, d in plan]}), encoding="utf-8")
        print(f"[info] GIMP: {gimp} ({len(plan)} file(s); the first GIMP run on a machine can take minutes)")
        rc, out = run_gimp(gimp, GIMP_SIDE, {"GB_JOBS": str(jobs), "GB_RESULT": str(result)}, args.timeout)
        if DEBUG or rc != 0:
            print(out.rstrip())
        if rc != 0:
            print(f"[FAIL] GIMP exited {rc}: {EXIT_MEANING.get(rc, 'see the output above')}", file=sys.stderr)
            return 2 if rc in (69, 124) else 1
        try:
            results = json.loads(result.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print("[FAIL] GIMP finished but wrote no results (run with --debug)", file=sys.stderr)
            return 1
    failed = 0
    for r in results:
        if r["ok"]:
            print(f"[ OK ] {Path(r['src']).name} -> {r['size'][0]}x{r['size'][1]}")
        else:
            failed += 1
            print(f"[FAIL] {Path(r['src']).name}: {r['error']}")
    print(f"{len(results) - failed}/{len(results)} file(s) done, output in {out_dir}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
