#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_bozzetto_live.py
# Purpose : The live exam for bozzetto.py: one real run on this machine's GPU. A crate drawn in code (three
#           shaded faces of a box on white, standard library only) goes through the whole lane: TRELLIS.2 in the
#           local ComfyUI, cleanup, export, the budget check, the asset log, the turntable. Checks the result is a
#           prop under budget, 1 m tall, pivot at the bottom, with no ComfyUI prompt left in the file.
# Usage   : python tools/bozzetto/test_bozzetto_live.py [--keep] [--quality high]
#           python tools/bozzetto/bozzetto.py test --live      # the offline exam, then this one
# Exit    : 0 passed, or skipped because ComfyUI, the model files or Blender are not here (it says which);
#           1 the run or a check failed
# Notes   : About 5 minutes at normal quality once ComfyUI has the model loaded (8 to 9 cold, K01), 15 GB of VRAM.
#           Works in a temporary game folder (--keep leaves it and prints where).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   ComfyUI up? models present? Blender found? -> any no: print SKIP with the reason, exit 0
#   temp game: docs/ASSET_LOG.md + art_src/crate.png (drawn here)
#   bozzetto make prop_live_crate --image art_src/crate.png --seed 7 --no-preview off
#   read the .glb: triangles <= budget, height ~1.0 m (glTF Y), bottom at 0, no "extras"; log row; record
import argparse
import json
import shutil
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bozzetto as bz  # noqa: E402

SIZE = 512
LOG = """# Asset Log

| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) | AI-assisted? | Modified? | Date added | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | | | | | | | no | no | 2026-01-01 | |
"""


def inside(px, py, poly):
    """Point in polygon (even-odd)."""
    hit, j = False, len(poly) - 1
    for i, (xi, yi) in enumerate(poly):
        xj, yj = poly[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def crate_png():
    """A box seen from above at three quarters: a light top, a mid left side, a dark right side, plank lines."""
    c, s, h = SIZE / 2, SIZE * 0.3, SIZE * 0.32
    top = [(c, c - s * 0.9), (c + s, c - s * 0.4), (c, c + s * 0.1), (c - s, c - s * 0.4)]
    left = [(c - s, c - s * 0.4), (c, c + s * 0.1), (c, c + s * 0.1 + h), (c - s, c - s * 0.4 + h)]
    right = [(c, c + s * 0.1), (c + s, c - s * 0.4), (c + s, c - s * 0.4 + h), (c, c + s * 0.1 + h)]
    faces = [(top, (196, 150, 96)), (left, (150, 104, 60)), (right, (110, 74, 42))]
    rows = []
    for y in range(SIZE):
        row = bytearray(b"\x00")
        for x in range(SIZE):
            rgb = (255, 255, 255)
            for poly, col in faces:
                if inside(x + 0.5, y + 0.5, poly):
                    plank = int((y - c) / 18) % 2 == 0
                    rgb = tuple(max(0, v - 18) if plank else v for v in col)
                    break
            row += bytes(rgb)
        rows.append(bytes(row))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def ready():
    """None when everything is here, else why the exam skips."""
    class A:
        url, allow_remote = None, False
    try:
        base = bz.comfy_base(A)
        info = bz.comfy(bz.cl.get_json, base, "/object_info")
    except bz.ToolError as exc:
        return f"no ComfyUI ({str(exc).split('(')[0].strip()})"
    gone = bz.missing_models(info, bz.load_lock()["models"])
    if gone:
        return f"model files missing in ComfyUI: {', '.join(m['file'] for m in gone)}"
    if bz.cl.missing_nodes(json.loads(bz.WORKFLOW_3D.read_text(encoding="utf-8")), info):
        return "ComfyUI lacks the TRELLIS.2 nodes (0.43.0+ has them)"
    if bz.find_blender() is None:
        return "no Blender or bpy module"
    return None


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Live Bozzetto exam: one real GPU run (skips when it cannot run).")
    ap.add_argument("--keep", action="store_true", help="keep the temporary game folder")
    ap.add_argument("--quality", choices=sorted(bz.QUALITY), default="normal")
    a = ap.parse_args()
    why = ready()
    if why:
        print(f"[SKIP] live exam not run: {why}")
        return 0
    root = Path(tempfile.mkdtemp(prefix="bz_live_"))
    failures = []

    def check(ok, what):
        print(f"[{' OK ' if ok else 'FAIL'}] {what}")
        if not ok:
            failures.append(what)

    try:
        (root / "docs").mkdir()
        (root / "docs" / "ASSET_LOG.md").write_text(LOG, encoding="utf-8")
        (root / "art_src").mkdir()
        (root / "art_src" / "crate.png").write_bytes(crate_png())
        t0 = time.monotonic()
        rc = bz.main(["make", "prop_live_crate", "--image", str(root / "art_src" / "crate.png"), "--seed", "7",
                      "--project", str(root), "--quality", a.quality])
        took = time.monotonic() - t0
        check(rc == 0, f"make exits 0 (it took {took:.0f} s)")
        glb = root / "assets" / "models" / "prop_live_crate.glb"
        check(glb.is_file(), "the .glb is in assets/models")
        if glb.is_file():
            data = glb.read_bytes()
            doc = bz.cl.read_glb(data)[0]
            tris = bz.glb_triangles(doc)
            acc = [doc["accessors"][p["attributes"]["POSITION"]] for m in doc["meshes"] for p in m["primitives"]]
            lo = [min(x["min"][i] for x in acc) for i in range(3)]
            hi = [max(x["max"][i] for x in acc) for i in range(3)]
            check(0 < tris <= 3000, f"{tris} triangles, prop budget 3000")
            check(abs(hi[1] - lo[1] - 1.0) < 0.01, f"height {hi[1] - lo[1]:.3f} m (1.0 asked)")
            check(abs(lo[1]) < 1e-3, f"bottom at {lo[1]:.4f} (pivot at the base)")
            check(b"extras" not in data and b"ComfyUI" not in data, "no ComfyUI prompt or name in the file")
            check(bool(doc.get("images")), f"{len(doc.get('images', []))} texture image(s)")
        rec_path = root / "assets_src" / "bozzetto" / "prop_live_crate" / "bozzetto.json"
        if rec_path.is_file():
            rec = json.loads(rec_path.read_text(encoding="utf-8"))
            job = rec["job"]
            print(f"[info] GPU {job['gpu_seconds']} s, VRAM peak {job.get('vram_peak_mib')} MiB, raw "
                  f"{job['tris_raw']} triangles, cleanup {rec['cleanup'].get('tris_in')} -> {rec['cleanup'].get('tris_out')}"
                  f", validator warnings {len(rec['validation'].get('warnings') or [])}")
            check(not rec["validation"].get("failures"), "validator: no failures")
        check("| model |" in (root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8"), "asset log row written")
        check((root / "assets_src" / "bozzetto" / "prop_live_crate" / "turntable.png").is_file(), "turntable sheet")
    finally:
        if a.keep:
            print(f"[info] kept {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    print(f"\n{'[FAIL] ' + str(len(failures)) + ' check(s) failed' if failures else '[ OK ] live exam passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
