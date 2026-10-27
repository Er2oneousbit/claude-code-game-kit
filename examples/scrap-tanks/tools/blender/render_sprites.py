#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# render_sprites.py
# Purpose : Render a 3D model into a 2D sprite sheet: N camera directions (rows) by
#           M animation frames (columns), transparent background, the same framing
#           and lighting in every cell. The classic "3D source, 2D game" pipeline.
# Usage   : Inside Blender (any OS):
#             blender -b --python-exit-code 1 -P tools/blender/render_sprites.py -- <asset> --out <sheet.png> [options]
#           With the bpy module (pip install bpy, needs the matching Python version):
#             python tools/blender/render_sprites.py <asset> --out <sheet.png> [options]
#           Examples:
#             ... -- assets_src/hero.glb --out assets/art/hero_sheet.png --directions 8 --size 96
#             ... -- hero.blend --out hero_walk.png --frames 1:24:3 --elevation 35
#             ... -- crate.glb --out crate.png --directions 1 --size 32 --pixel-art
#             ... -- character.glb --list-actions          # names of the animations in the file
#             ... -- character.glb --out walk.png --action walk --directions 4
#             ... -- hull.glb --out hull.png --directions 16 --world-size 3 --pivot origin   # a set that
#             ... -- turret.glb --out turret.png --directions 16 --world-size 3 --pivot origin  # stacks
# Needs   : Blender 4.2+ or the bpy module. Cycles renders on the CPU, so no GPU is required.
# Exit    : 0 sheet written, 1 render failed, 2 usage/environment problem
# Notes   : Inputs: .glb .gltf .fbx .obj .blend (imported into an empty scene, never saved back).
#           Cameras and lights in the file are removed; this script adds its own orthographic
#           camera, a key light and soft ambient, all fixed relative to the camera.
#           Row 0 is the model's front (camera on -Y looking toward +Y, Blender's front view);
#           each next row turns the camera counter-clockwise seen from above by 360/N degrees.
#           Framing is computed over every requested frame, so animation never leaves the cell.
#           By default each model fills its own cell (scale and center differ per model). For a SET of
#           sprites that must match (a hull and its turret, units on one map), pass the same
#           --world-size (meters across a cell) and --pivot origin (the model's origin lands on the cell
#           center) to every render; the JSON then records pixels_per_meter and the pivot pixel.
#           The glTF import removes the 'Icosphere' Blender adds as a rigged model's bone display shape (shared
#           import in validate_asset.py). Other helper meshes in a file (a ground plane, a proxy) still spoil
#           the framing: the script warns when one object dwarfs the rest; drop it with --ignore NAME.
#           Faces stored twice back to back (some packs bake double-sided geometry into the mesh) render
#           black in Cycles, so the inner twin of each pair is removed after import.
#           --action NAME plays that animation on every armature (and animated object) in the file;
#           without --frames it renders the action's whole frame range.
#           --pixel-art turns the pixel filter down for hard edges (render at your target size).
#           Writes <sheet>.json next to the PNG: cell size, rows (directions with angles) and
#           columns (frames), for Phaser's spritesheet or Godot's AtlasTexture.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-10-24: --engine eevee also tries BLENDER_EEVEE_NEXT (Blender 4.2 to 4.5); launch lines
#           pass --python-exit-code 1 so a traceback is not exit 0 (E64, tested on Blender 5.2)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   parse args -> import asset into an empty scene -> remove cameras and lights
#   frames = parsed range or the current frame
#   bounds = union of evaluated mesh bounds over all frames -> center, radius
#   --pivot origin: center = (0, 0, 0), radius = farthest bounds corner from it
#   ortho width = --world-size, or 2 * radius * (1 + margin); with --world-size, project the model's
#   vertices onto every camera's screen axes and warn if any lands outside the cell
#   add ortho camera with that width and a key light parented to it
#   for each direction: move the camera on a circle around the center (elevation fixed)
#       for each frame: set frame, render one cell to a temp PNG
#   stitch the cells into one RGBA sheet (numpy, rows top to bottom), save PNG and JSON
import argparse
import fnmatch
import json
import math
import sys
import tempfile
from pathlib import Path

DEBUG = False
# Engine ids to try in order: EEVEE was BLENDER_EEVEE_NEXT in Blender 4.2 to 4.5, BLENDER_EEVEE before and from 5.0
ENGINES = {"cycles": ("CYCLES",), "eevee": ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"), "workbench": ("BLENDER_WORKBENCH",)}
KEY_LIGHT_ENERGY = 3.0        # sun strength
AMBIENT_STRENGTH = 0.6        # world light, so shadow sides are not black
CAMERA_DISTANCE_FACTOR = 4.0  # camera distance = radius * this (ortho: only clipping depends on it)
MAX_FIT_POINTS = 300_000      # vertices kept for the --world-size fit check (more: use the bounds corners)


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}")


def script_argv():
    """Blender passes its own args first; ours come after a lone '--'."""
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else argv[1:]


def frame_list(text):
    """'5' -> [5]; '1:24' -> 1..24; '1:24:3' -> 1, 4, ..., 22."""
    try:
        parts = [int(p) for p in text.split(":")]
    except ValueError:
        raise argparse.ArgumentTypeError(f"frames must look like 5, 1:24 or 1:24:3, got {text!r}")
    if len(parts) == 1:
        return parts
    start, end = parts[0], parts[1]
    step = parts[2] if len(parts) == 3 else 1
    if len(parts) > 3 or step < 1 or end < start:
        raise argparse.ArgumentTypeError(f"bad frame range {text!r} (start:end[:step], end >= start, step >= 1)")
    return list(range(start, end + 1, step))


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="render_sprites.py",
                                 description="Render a 3D model into a sprite sheet (directions x frames).")
    ap.add_argument("asset", help="model file: .glb .gltf .fbx .obj .blend")
    ap.add_argument("--out", help="sheet PNG to write (a .json with the layout goes next to it)")
    ap.add_argument("--action", help="animation to play (see --list-actions); default: whatever the file has active")
    ap.add_argument("--list-actions", action="store_true", help="print the animations in the file and exit")
    ap.add_argument("--ignore", action="append", default=[], metavar="NAME",
                    help="drop objects whose name matches (wildcards ok, repeatable): stray helpers that spoil the framing")
    ap.add_argument("--directions", type=int, default=8, help="camera directions around the model, rows (default 8)")
    ap.add_argument("--frames", type=frame_list, default=None, help="frame or range start:end[:step] (default: current frame)")
    ap.add_argument("--size", type=int, default=128, help="cell size in pixels, square (default 128)")
    ap.add_argument("--elevation", type=float, default=30.0, help="camera pitch in degrees: 0 side view, 90 top-down (default 30)")
    ap.add_argument("--margin", type=float, default=0.08, help="empty border around the model, fraction (default 0.08)")
    ap.add_argument("--world-size", type=float, default=None, metavar="METERS",
                    help="fixed width of a cell in meters, so several sheets share one scale (default: fit each model)")
    ap.add_argument("--pivot", choices=("bounds", "origin"), default="bounds",
                    help="cell center = the model's bounds center (default) or its origin (for sets that stack)")
    ap.add_argument("--engine", choices=sorted(ENGINES), default="cycles", help="render engine (default cycles: CPU, works headless)")
    ap.add_argument("--samples", type=int, default=32, help="Cycles samples (default 32)")
    ap.add_argument("--pixel-art", action="store_true", help="hard pixel edges (tiny pixel filter); render at your target size")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing sheet")
    ap.add_argument("--debug", action="store_true", help="verbose output")
    args = ap.parse_args(argv)
    if not args.out and not args.list_actions:
        ap.error("--out is required (or use --list-actions)")
    if not 1 <= args.directions <= 64 or not 8 <= args.size <= 4096 or not -90 <= args.elevation <= 90:
        ap.error("need 1 <= --directions <= 64, 8 <= --size <= 4096, -90 <= --elevation <= 90")
    if args.samples < 1 or not 0 <= args.margin < 1:
        ap.error("need --samples >= 1 and 0 <= --margin < 1")
    if args.world_size is not None and args.world_size <= 0:
        ap.error("--world-size must be a positive number of meters")
    return args


def load_bpy():
    try:
        import bpy  # noqa: F401
        return bpy
    except ImportError:
        print("[ENV ] bpy not available. Run inside Blender:\n"
              "         blender -b --python-exit-code 1 -P tools/blender/render_sprites.py -- <asset> --out <sheet.png>\n"
              "       or with the bpy module for your Python version (pip install bpy)", file=sys.stderr)
        return None


def import_asset(bpy, path):
    """Same import rules as validate_asset.py (shared on purpose)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from validate_asset import drop_back_to_back, import_asset as va_import  # noqa: E402
    va_import(bpy, path)
    removed = drop_back_to_back(bpy)
    if removed:
        print(f"[info] removed {removed} back-to-back duplicate faces (the file stores both sides of each face; "
              f"Cycles would render them black)")


def assign_action(bpy, scene, name):
    """Play action `name` on every armature (or animated object). Returns the action's (start, end) frames.
    Blender 4.4+ actions have slots: pick a slot that fits the object, or the assignment does nothing."""
    action = bpy.data.actions.get(name)
    if action is None:
        raise ValueError(f"no action named {name!r}; the file has: {', '.join(sorted(a.name for a in bpy.data.actions)) or 'none'}")
    targets = [o for o in scene.objects if o.type == "ARMATURE"] or [o for o in scene.objects if o.animation_data]
    if not targets:
        raise ValueError("the file has no armature or animated object to play the action on")
    for obj in targets:
        ad = obj.animation_data or obj.animation_data_create()
        for track in ad.nla_tracks:                       # imported NLA strips would override the action
            track.mute = True
        ad.action = action
        if hasattr(ad, "action_slot") and ad.action_slot is None:
            slots = list(getattr(ad, "action_suitable_slots", [])) or list(getattr(action, "slots", []))
            if slots:
                ad.action_slot = slots[0]
    start, end = action.frame_range
    return int(round(start)), int(round(end))


def drop_ignored(bpy, scene, patterns):
    """Remove objects matching any pattern. Returns the removed names."""
    gone = [o for o in scene.objects if any(fnmatch.fnmatch(o.name, p) for p in patterns)]
    names = [o.name for o in gone]
    for o in gone:
        bpy.data.objects.remove(o, do_unlink=True)
    return names


def warn_outliers(bpy, scene):
    """Warn when one mesh is much bigger than all the others together (a helper deciding the framing)."""
    from mathutils import Vector
    depsgraph = bpy.context.evaluated_depsgraph_get()
    sizes = {}
    for obj in scene.objects:
        if obj.type == "MESH":
            ev = obj.evaluated_get(depsgraph)
            pts = [ev.matrix_world @ Vector(c) for c in ev.bound_box]
            sizes[obj.name] = max(max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3))
    if len(sizes) < 2:
        return
    biggest = max(sizes, key=sizes.get)
    rest = max(v for k, v in sizes.items() if k != biggest)
    if rest > 0 and sizes[biggest] > 2.5 * rest:
        print(f"[WARN] '{biggest}' ({sizes[biggest]:.2f} m) is {sizes[biggest] / rest:.1f}x bigger than any other mesh and "
              f"decides the framing. If it is a helper, add: --ignore \"{biggest}\"")


def scene_bounds(bpy, scene, frames):
    """Center and radius of all meshes over all frames (evaluated, so armatures and modifiers count)."""
    from mathutils import Vector
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    points = []  # evaluated vertices, for the exact on-screen fit check
    for f in frames:
        scene.frame_set(f)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        for obj in scene.objects:
            if obj.type != "MESH":
                continue
            ev = obj.evaluated_get(depsgraph)
            for corner in ev.bound_box:
                p = ev.matrix_world @ Vector(corner)
                lo = Vector(min(a, b) for a, b in zip(lo, p))
                hi = Vector(max(a, b) for a, b in zip(hi, p))
            if len(points) < MAX_FIT_POINTS:
                mw = ev.matrix_world
                points.extend(mw @ v.co for v in ev.data.vertices)
    if lo.x == math.inf:
        return None, None, None, None
    center = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 1e-4)
    # farthest bounds corner from the origin, for --pivot origin
    reach = max(Vector((x, y, z)).length for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z))
    if not points or len(points) >= MAX_FIT_POINTS:  # huge animated sets: the bounds corners (conservative)
        points = [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    return center, radius, max(reach, 1e-4), points


def view_extent(corners, center, angles, elevation_deg):
    """Largest distance of a model point from the cell center on screen, over every camera direction (meters).
    The orthographic cell must be at least twice this wide, or the model is cut off."""
    from mathutils import Vector
    worst = 0.0
    e = math.radians(elevation_deg)
    for angle in angles:
        a = math.radians(angle)
        forward = -Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
        hint = Vector((0, 0, 1)) if abs(forward.z) < 0.999 else Vector((math.sin(a), -math.cos(a), 0)) * -1
        right = forward.cross(hint).normalized()
        up = right.cross(forward).normalized()
        for c in corners:
            d = c - center
            worst = max(worst, abs(d.dot(right)), abs(d.dot(up)))
    return worst


def setup_scene(bpy, scene, args, radius, ortho_scale):
    """Camera with a key light parented to it, ambient world, render settings."""
    for obj in [o for o in scene.objects if o.type in ("CAMERA", "LIGHT")]:
        bpy.data.objects.remove(obj, do_unlink=True)
    cam_data = bpy.data.cameras.new("SpriteCam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ortho_scale
    cam_data.clip_start = 0.001
    cam_data.clip_end = radius * CAMERA_DISTANCE_FACTOR * 3
    cam = bpy.data.objects.new("SpriteCam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    sun_data = bpy.data.lights.new("SpriteKey", type="SUN")
    sun_data.energy = KEY_LIGHT_ENERGY
    sun = bpy.data.objects.new("SpriteKey", sun_data)
    scene.collection.objects.link(sun)
    sun.parent = cam                                  # light turns with the camera: same lighting per direction
    sun.rotation_euler = (math.radians(-35), math.radians(30), 0)   # from the upper left of the view
    world = scene.world or bpy.data.worlds.new("SpriteWorld")
    scene.world = world
    if bpy.app.version < (5, 0, 0):   # 5.x always uses nodes; use_nodes goes away in 6.0
        world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (1, 1, 1, 1)
        bg.inputs["Strength"].default_value = AMBIENT_STRENGTH

    r = scene.render
    for engine_id in ENGINES[args.engine]:
        try:
            r.engine = engine_id
            break
        except TypeError:  # unknown enum value in this Blender version
            continue
    else:
        raise RuntimeError(f"render engine {args.engine} ({' or '.join(ENGINES[args.engine])}) not available "
                           f"in this Blender (try --engine cycles)")
    if args.engine == "cycles":
        scene.cycles.device = "CPU"
        scene.cycles.samples = args.samples
        scene.cycles.use_denoising = not args.pixel_art
        if args.pixel_art:
            scene.cycles.filter_width = 0.01
    r.resolution_x = r.resolution_y = args.size
    r.resolution_percentage = 100
    r.film_transparent = True
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"   # AgX/Filmic would wash out game colors
    return cam


def place_camera(cam, center, radius, angle_deg, elevation_deg):
    """Camera on a circle around center: angle 0 = front (on -Y), counter-clockwise seen from above."""
    from mathutils import Vector
    a, e = math.radians(angle_deg), math.radians(elevation_deg)
    direction = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
    cam.location = center + direction * radius * CAMERA_DISTANCE_FACTOR
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()


def stitch(bpy, cells, rows, cols, size, out):
    """cells[(row, col)] = png path. Row 0 is the top of the sheet. Saves an RGBA PNG."""
    import numpy as np
    sheet = np.zeros((rows * size, cols * size, 4), dtype=np.float32)
    for (row, col), path in cells.items():
        img = bpy.data.images.load(str(path))
        px = np.empty(size * size * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
        y0 = (rows - 1 - row) * size                  # Blender image rows start at the bottom
        sheet[y0:y0 + size, col * size:(col + 1) * size] = px.reshape(size, size, 4)
        bpy.data.images.remove(img)
    out_img = bpy.data.images.new("sprite_sheet", cols * size, rows * size, alpha=True)
    out_img.pixels.foreach_set(sheet.ravel())
    out_img.filepath_raw = str(out)
    out_img.file_format = "PNG"
    out_img.save()


def run(args):
    path, out = Path(args.asset), Path(args.out or "unused.png")
    if not path.exists():
        print(f"[ENV ] asset not found: {path}", file=sys.stderr)
        return 2
    if out.suffix.lower() != ".png":
        print("[ENV ] --out must end in .png", file=sys.stderr)
        return 2
    if args.out and out.exists() and not args.overwrite:
        print(f"[ENV ] {out} exists (use --overwrite)", file=sys.stderr)
        return 2
    bpy = load_bpy()
    if bpy is None:
        return 2
    try:
        import_asset(bpy, path.resolve())
    except ValueError as exc:
        print(f"[ENV ] {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"[FAIL] import failed: {exc}", file=sys.stderr)
        return 1

    scene = bpy.context.scene
    if args.list_actions:
        for a in sorted(bpy.data.actions, key=lambda a: a.name):
            print(f"{a.name:32s} frames {int(round(a.frame_range[0]))}..{int(round(a.frame_range[1]))}")
        if not bpy.data.actions:
            print("(no animations in this file)")
        return 0
    for name in drop_ignored(bpy, scene, args.ignore):
        print(f"[info] ignored {name}")
    warn_outliers(bpy, scene)
    action_range = None
    if args.action:
        try:
            action_range = assign_action(bpy, scene, args.action)
        except ValueError as exc:
            print(f"[ENV ] {exc}", file=sys.stderr)
            return 2
    frames = args.frames or (list(range(action_range[0], action_range[1] + 1)) if action_range else [scene.frame_current])
    center, radius, reach, corners = scene_bounds(bpy, scene, frames)
    if center is None:
        print("[FAIL] no mesh objects found in the file", file=sys.stderr)
        return 1
    dbg(f"center {tuple(round(c, 3) for c in center)} radius {radius:.3f} frames {frames}")
    if args.pivot == "origin":
        from mathutils import Vector
        center, radius = Vector((0.0, 0.0, 0.0)), reach
    angles = [i * 360.0 / args.directions for i in range(args.directions)]
    ortho = args.world_size or 2 * radius * (1 + args.margin)
    if args.world_size:
        extent = view_extent(corners, center, angles, args.elevation)
        if extent > args.world_size / 2:
            print(f"[WARN] seen from some directions the model reaches {extent:.2f} m from the {args.pivot} pivot and a "
                  f"cell is {args.world_size:g} m wide: parts are cut off (raise --world-size to {2 * extent:.2f} or more)")
    cam = setup_scene(bpy, scene, args, radius, ortho)

    cells = {}
    with tempfile.TemporaryDirectory(prefix="sprites_") as tmp:
        for row, angle in enumerate(angles):
            place_camera(cam, center, radius, angle, args.elevation)
            for col, f in enumerate(frames):
                scene.frame_set(f)
                cell = Path(tmp) / f"r{row:02d}_c{col:03d}.png"
                scene.render.filepath = str(cell)
                bpy.ops.render.render(write_still=True)
                if not cell.exists():
                    print(f"[FAIL] render produced no image for direction {angle:g} frame {f}", file=sys.stderr)
                    return 1
                cells[(row, col)] = cell
                dbg(f"rendered direction {angle:g} frame {f}")
        out.parent.mkdir(parents=True, exist_ok=True)
        stitch(bpy, cells, len(angles), len(frames), args.size, out.resolve())

    meta = {
        "image": out.name, "cell_width": args.size, "cell_height": args.size,
        "rows": "directions", "columns": "frames",
        "directions": [{"row": i, "angle_deg": a} for i, a in enumerate(angles)],
        "frames": frames, "action": args.action, "elevation_deg": args.elevation, "source": path.name,
        "note": "row 0 = front (camera on -Y); angles turn counter-clockwise seen from above",
        "world_size_m": round(ortho, 6), "pixels_per_meter": round(args.size / ortho, 6), "pivot": args.pivot,
        "pivot_px": [args.size / 2, args.size / 2] if args.pivot == "origin" else None,
        "ground_depth_scale": round(math.sin(math.radians(args.elevation)), 6),
        "note_scale": "a ground offset (dx, dy) in meters is (dx, dy * ground_depth_scale) * pixels_per_meter on screen",
    }
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[ OK ] {out}: {len(angles)} direction(s) x {len(frames)} frame(s) of {args.size} px "
          f"({len(frames) * args.size} x {len(angles) * args.size}), layout in {out.with_suffix('.json').name}")
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
        print(f"[ENV ] render_sprites crashed: {exc!r}. Re-run with --debug and paste the output.", file=sys.stderr)
        if DEBUG:
            raise
        return 2


if __name__ == "__main__":
    sys.exit(main())
