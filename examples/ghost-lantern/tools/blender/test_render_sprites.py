#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_render_sprites.py
# Purpose : The exam for render_sprites.py: builds small known models with bpy,
#           renders them, and checks the sheet's size, transparency, that every
#           cell has the model in it, that directions and frames really differ,
#           and the usage errors.
# Usage   : With the bpy module:  python tools/blender/test_render_sprites.py [--keep] [--debug]
#           Inside Blender:       blender -b --python-exit-code 1 -P tools/blender/test_render_sprites.py -- [--keep] [--debug]
# Exit    : 0 all cases pass, 1 some case failed, 2 bpy not available
# Notes   : Renders tiny cells (32 px, 4 Cycles samples) so the whole exam takes about a minute on a CPU.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   build fixtures (a body with a nose on its front; the same with a moving location key)
#   run render_sprites as a separate process for each case, then read the sheet with bpy
#   check: dimensions, transparent corners, alpha in every cell, front vs side silhouettes
#          differ, animated frames differ, JSON layout, bad input exits 2
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE / "render_sprites.py"
CELL = 32


def script_argv():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else argv[1:]


def tool_cmd():
    """Launch through Blender when running inside it (its python cannot import bpy), else this Python."""
    try:
        import bpy
        binary = getattr(bpy.app, "binary_path", "") or ""
    except ImportError:
        binary = ""
    if binary and Path(binary).stem.lower().startswith("blender"):
        return [binary, "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(TOOL), "--"]
    return [sys.executable, str(TOOL)]


def run_tool(*args):
    proc = subprocess.run(tool_cmd() + [str(a) for a in args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout + proc.stderr


def build_with_helper(bpy, path):
    """The body plus a big stray 'Helper' plane: the kind of leftover downloaded models carry."""
    build_fixture(bpy, path, export=False)
    bpy.ops.mesh.primitive_plane_add(size=6, location=(0, 0, 0))
    bpy.context.active_object.name = "Helper"
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB")


def build_fixture(bpy, path, animate=False, export=True):
    """A tall body with a nose sticking out of its front (-Y), exported as .glb."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.75))
    body = bpy.context.active_object
    body.scale = (0.5, 0.5, 1.5)
    bpy.ops.object.transform_apply(scale=True)
    bpy.ops.mesh.primitive_cube_add(size=0.4, location=(0, -0.6, 1.0))
    nose = bpy.context.active_object
    for o in (body, nose):
        o.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    if animate:
        body.location = (-0.8, 0, 0)
        body.keyframe_insert("location", frame=1)
        body.location = (0.8, 0, 0)
        body.keyframe_insert("location", frame=3)
    if export:
        bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", export_animations=animate)


def build_double_sided(bpy, path):
    """The fixture with every face stored twice, back to back (how some packs ship double-sided meshes)."""
    import bmesh
    build_fixture(bpy, path, export=False)
    obj = bpy.context.active_object
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    dup = bmesh.ops.duplicate(bm, geom=list(bm.faces))
    bmesh.ops.reverse_faces(bm, faces=[g for g in dup["geom"] if isinstance(g, bmesh.types.BMFace)])
    bm.to_mesh(obj.data)
    bm.free()
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB")


def read_rgba(bpy, path):
    """Mean color of the opaque pixels (0..1)."""
    import numpy as np
    img = bpy.data.images.load(str(path))
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    px = px.reshape(-1, 4)
    solid = px[px[:, 3] > 0.5]
    return float(solid[:, :3].mean()) if len(solid) else 0.0


def build_variant(bpy, path, scale=1.0, offset=(0.0, 0.0, 0.0)):
    """The fixture scaled and moved away from the origin (applied, so the origin stays at 0,0,0)."""
    build_fixture(bpy, path, export=False)
    obj = bpy.context.active_object
    obj.scale = (scale, scale, scale)
    obj.location = offset
    bpy.ops.object.transform_apply(location=True, scale=True)
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB")


def read_sheet(bpy, path):
    """Returns (width, height, alpha rows top-to-bottom as a numpy array)."""
    import numpy as np
    img = bpy.data.images.load(str(path))
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return w, h, px.reshape(h, w, 4)[::-1, :, 3]


def opaque_width(alpha):
    cols = (alpha > 0.5).any(axis=0).nonzero()[0]
    return 0 if len(cols) == 0 else int(cols[-1] - cols[0] + 1)


def opaque_center_x(alpha):
    cols = (alpha > 0.5).any(axis=0).nonzero()[0]
    return None if len(cols) == 0 else float(cols.mean())


def main():
    ap = argparse.ArgumentParser(description="Exam for render_sprites.py (builds fixtures with bpy).")
    ap.add_argument("--keep", action="store_true", help="keep the generated files")
    ap.add_argument("--debug", action="store_true", help="print tool output for every case")
    args = ap.parse_args(script_argv())
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        import bpy
    except ImportError:
        print("[ENV ] bpy not available (run inside Blender or install the bpy module)", file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="sprites_exam_"))
    still, moving = tmp / "body.glb", tmp / "moving.glb"
    build_fixture(bpy, still)
    build_fixture(bpy, moving, animate=True)
    helper = tmp / "helper.glb"
    build_with_helper(bpy, helper)
    results = []

    def case(name, ok, detail=""):
        results.append(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else '  ' + detail}")

    common = ["--size", CELL, "--samples", 4]
    plain_front = None

    # --world-size and --pivot origin: sets of sprites that share a scale and a pivot
    big, shifted = tmp / "big.glb", tmp / "shifted.glb"
    build_variant(bpy, big, scale=2.0)
    build_variant(bpy, shifted, offset=(1.0, 0.0, 0.0))
    top = ["--directions", 1, "--elevation", 90, "--world-size", 4, "--pivot", "origin", *common]
    rc1, out1 = run_tool(still, "--out", tmp / "set_small.png", *top)
    rc2, out2 = run_tool(big, "--out", tmp / "set_big.png", *top)
    rc3, out3 = run_tool(shifted, "--out", tmp / "set_shifted.png", *top)
    case("fixed --world-size renders (exit 0)", rc1 == rc2 == rc3 == 0, (out1 + out2 + out3)[-400:])
    case("a model that fits its fixed cell does not warn", rc1 == 0 and "raise --world-size" not in out1, out1[-300:])
    if rc1 == rc2 == rc3 == 0:
        ws = opaque_width(read_sheet(bpy, tmp / "set_small.png")[2])
        wb = opaque_width(read_sheet(bpy, tmp / "set_big.png")[2])
        case("same --world-size keeps the size ratio (2x model, 2x pixels)", ws > 0 and abs(wb / ws - 2) < 0.25,
             f"{ws} vs {wb} px")
        cx = opaque_center_x(read_sheet(bpy, tmp / "set_shifted.png")[2])
        want = CELL / 2 + 1.0 * CELL / 4  # 1 m off the origin at CELL px per 4 m
        case("--pivot origin draws a model 1 m off its origin 1 m off center",
             cx is not None and abs(cx + 0.5 - want) < 2, f"center {cx}, wanted about {want}")
        meta = json.loads((tmp / "set_small.json").read_text(encoding="utf-8"))
        case("JSON records pixels_per_meter and the pivot pixel",
             meta.get("pixels_per_meter") == CELL / 4 and meta.get("pivot_px") == [CELL / 2, CELL / 2], str(meta)[:200])
    twin = tmp / "double_sided.glb"
    build_double_sided(bpy, twin)
    rc, out = run_tool(twin, "--out", tmp / "double_sided.png", "--directions", 1, *common)
    shade = read_rgba(bpy, tmp / "double_sided.png") if rc == 0 else 0.0
    case("faces stored twice back to back are removed and render lit, not black",
         rc == 0 and "back-to-back" in out and shade > 0.15, f"mean {shade:.2f}; " + out[-300:])
    rc, out = run_tool(big, "--out", tmp / "too_big.png", "--directions", 1, "--world-size", 1, *common)
    case("a model bigger than --world-size warns", rc == 0 and "raise --world-size" in out, out[-300:])

    rc, out = run_tool(still, "--out", tmp / "four.png", "--directions", 4, *common)
    if args.debug:
        print(out)
    case("4 directions render (exit 0)", rc == 0, out[-400:])
    if rc == 0:
        w, h, a = read_sheet(bpy, tmp / "four.png")
        case("sheet is 1 column x 4 rows of 32 px", (w, h) == (CELL, 4 * CELL), f"got {w}x{h}")
        case("corners are transparent", max(a[0, 0], a[0, -1], a[-1, 0], a[-1, -1]) < 0.05)
        cells = [a[r * CELL:(r + 1) * CELL] for r in range(4)]
        case("every cell contains the model", all((c > 0.5).sum() > 20 for c in cells),
             str([int((c > 0.5).sum()) for c in cells]))
        front, side = opaque_width(cells[0]), opaque_width(cells[1])
        plain_front = front
        case("front and side silhouettes differ (the nose shows from the side)", side > front, f"front {front}, side {side}")
        meta = json.loads((tmp / "four.json").read_text(encoding="utf-8"))
        case("JSON lists 4 directions and the cell size",
             len(meta["directions"]) == 4 and meta["cell_width"] == CELL and meta["directions"][1]["angle_deg"] == 90)

    rc, out = run_tool(moving, "--out", tmp / "anim.png", "--directions", 1, "--frames", "1:3", *common)
    if args.debug:
        print(out)
    case("animated range renders (exit 0)", rc == 0, out[-400:])
    if rc == 0:
        w, h, a = read_sheet(bpy, tmp / "anim.png")
        case("sheet is 3 columns x 1 row", (w, h) == (3 * CELL, CELL), f"got {w}x{h}")
        x1 = opaque_center_x(a[:, :CELL])
        x3 = opaque_center_x(a[:, 2 * CELL:])
        case("the model moves between frames and stays in the cell",
             x1 is not None and x3 is not None and x3 > x1 + 3, f"center x {x1} -> {x3}")

    rc, out = run_tool(helper, "--out", tmp / "helper_raw.png", "--directions", 1, *common)
    case("a giant helper mesh triggers the framing warning", rc == 0 and "--ignore" in out and "Helper" in out, out[-300:])
    rc2, out2 = run_tool(helper, "--out", tmp / "helper_ign.png", "--directions", 1, "--ignore", "Help*", *common)
    case("--ignore drops it (wildcards work)", rc2 == 0 and "ignored Helper" in out2, out2[-300:])
    if rc == 0 and rc2 == 0:
        _, _, raw = read_sheet(bpy, tmp / "helper_raw.png")
        _, _, ign = read_sheet(bpy, tmp / "helper_ign.png")
        case("ignoring the helper frames the model exactly like the plain model (within 2 px)",
             plain_front is not None and abs(opaque_width(ign) - plain_front) <= 2,
             f"plain {plain_front}, ignored {opaque_width(ign)}, raw {opaque_width(raw)}")
    rc, out = run_tool(moving, "--list-actions")
    case("--list-actions names the animation", rc == 0 and "frames" in out, out[-300:])
    rc, out = run_tool(moving, "--out", tmp / "x.png", "--action", "no-such-action")
    case("unknown --action exits 2 and lists what exists", rc == 2 and "the file has" in out, out[-300:])

    rc, out = run_tool(still, "--out", tmp / "four.png", "--directions", 4, *common)
    case("existing sheet is not overwritten without --overwrite (exit 2)", rc == 2, out[-200:])
    rc, out = run_tool(tmp / "missing.glb", "--out", tmp / "x.png")
    case("missing asset exits 2", rc == 2, out[-200:])
    rc, out = run_tool(still, "--out", tmp / "x.png", "--frames", "5:1")
    case("bad frame range exits 2", rc == 2, out[-200:])

    passed = sum(results)
    print(f"{passed}/{len(results)} cases passed")
    if args.keep:
        print(f"files kept in {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
