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
#             ... -- hero_rigged.glb --out assets/art/characters/hero/hero.png --actions all --step 2 \
#                     --manifest assets/dotwork/rendered.assets.json      # every clip, 8 directions, Dotwork manifest
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
#           --actions idle,walk (or all) renders several clips in one run, one sheet each (<out stem>_<action>.png),
#           all framed alike (the framing covers every frame of every clip), so a character does not jump in
#           size between clips. --step N keeps every Nth frame of each clip. A clip whose model centre stands more
#           than CLIP_OFFSET_WARN of the height sideways from the rest pose draws a warning naming it (a root bone
#           offset in every key, as Tripo's in-place clips had, makes every sheet small; rig_finish.py fixes it).
#           --manifest <pack>.assets.json also writes a Dotwork asset manifest (tools/art/dotwork/ASSET_MANIFEST.md,
#           spec 1.x): one animated_sprite (--name, default the sheet's stem) with a clip <action>_<dir> per action
#           and direction (s, sw, w, nw, n, ne, e, se for 8 directions; s, w, n, e for 4; the action alone for 1),
#           the direction table, per-frame durations (step / the scene's fps), loop (all but --once clips), the
#           pivot (where the model's origin lands in the cell: a Bozzetto character's feet), and each frame's own
#           PNG in <out stem>_frames/. The manifest's base is the assets folder above its dotwork/ folder (or its own
#           folder); every sheet must sit under it. An existing manifest from render_sprites is merged (the asset of
#           that name replaced); one another tool wrote (Dotwork rebuilds its own) is refused. The manifest is
#           checked with assetspec.py before it is written. Every engine's Dotwork importer loads it as it is.
#           A looping clip whose last frame repeats its first pose (glTF loops do) renders that frame once.
#           Clips keyed at another frame rate than the scene's (Tripo's at 30 fps land every 0.8 frames in Blender's
#           24 fps scene) first move the scene to their rate (bpy_common.py, #292): rendered frames then sit on the
#           clip's own keys, the manifest's fps and durations are the clip's, and a loop's closing frame is found.
#           Blender 4.2's glTF importer names an action "<clip>_<object>": it takes its clip's name back, so
#           --action walk finds it and the manifest's clips are walk_s, not walk_Armature_s.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-10-24: --engine eevee also tries BLENDER_EEVEE_NEXT (Blender 4.2 to 4.5); launch lines
#           pass --python-exit-code 1 so a traceback is not exit 0 (E64, tested on Blender 5.2)
#           2026-11-11: --actions, --step, --manifest, --name, --once (#290); a skinned body beside a rig chain's
#           small strip is not called a helper (#291); a clip standing far from the rest pose warns
#           2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): Blender 4.2 clip names, clips at 30 fps, the bpy
#           module's exit crash (#292)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   parse args -> import asset into an empty scene -> remove cameras and lights -> actions take their clip's name
#   an action asked for: the scene takes the clips' frame rate (keys on whole frames)
#   clips = --actions (each with its frame range, every --step-th frame; a looping clip drops its last frame when
#           the pose there equals the first), or the one --action, or no action
#   frames = parsed range or the current frame
#   bounds = union of evaluated mesh bounds over all frames of all clips -> center, radius; a clip whose own bounds
#            centre stands far sideways from the rest pose's warns (a root offset that shrinks every sheet)
#   --pivot origin: center = (0, 0, 0), radius = farthest bounds corner from it
#   ortho width = --world-size, or 2 * radius * (1 + margin); with --world-size, project the model's
#   vertices onto every camera's screen axes and warn if any lands outside the cell
#   add ortho camera with that width and a key light parented to it
#   for each clip, for each direction: move the camera on a circle around the center (elevation fixed)
#       for each frame: set frame, render one cell to a temp PNG
#   stitch each clip's cells into one RGBA sheet (numpy, rows top to bottom), save PNG and JSON
#   --manifest: copy the cells out as frame PNGs, build the animated_sprite (pivot = the origin projected into
#   each direction's cell), merge into the manifest, validate with assetspec, write
import argparse
import fnmatch
import json
import math
import os
import re
import shutil
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
LOOP_POSE_TOLERANCE = 1e-4    # metres: a looping clip's last frame "repeats the first" when no vertex moved more
CLIP_OFFSET_WARN = 0.25       # share of the rest-pose height: a clip whose model centre stands farther off warns
# Row order -> Dotwork direction (screen directions, s faces the camera). Row 0 sees the model's front (s); each next
# row turns the camera counter-clockwise seen from above, so the model's front turns toward screen left first.
COMPASS = {1: (None,), 4: ("s", "w", "n", "e"), 8: ("s", "sw", "w", "nw", "n", "ne", "e", "se")}
MANIFEST_FORMAT, MANIFEST_VERSION, GENERATOR = "dotwork-assets", "1.0.0", "render_sprites"
MANIFEST_SUFFIX = ".assets.json"
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")   # a manifest name (ASSET_MANIFEST.md "Names")
ROLE = "characters"           # the animated_sprite's role: the art folder kind it belongs to


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


# --- the asset manifest (no Blender needed: test_render_sprites_manifest.py runs these on plain Python) ----------
def manifest_base(manifest):
    """(folder the manifest's paths are relative to, its `base` text): the assets folder above a dotwork/ folder,
    as Dotwork's own manifests have it, else the manifest's own folder."""
    folder = Path(os.path.abspath(manifest)).parent
    return (folder.parent, "..") if folder.name == "dotwork" else (folder, ".")


def rel_to(path, base_dir):
    """`path` relative to base_dir with forward slashes, or None when it is not inside it (manifest paths never
    use '..')."""
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(base_dir))
    parts = Path(rel).parts
    if not parts or parts[0] == ".." or os.path.isabs(rel):
        return None
    return Path(rel).as_posix()


def clip_name(action, direction):
    return action if direction is None else f"{action}_{direction}"


def build_asset(name, clips, cell):
    """The animated_sprite for rendered clips. clips: [{action, loop, fps, sheet, rows: [{dir, pivot, files}]}],
    sheet and files relative to the manifest's base; row r of a sheet is rows[r], column c is files[c]."""
    out, table = [], {}
    for c in clips:
        dur = 1.0 / c["fps"]
        for r, row in enumerate(c["rows"]):
            n = clip_name(c["action"], row["dir"])
            frames = [{"file": f, "rect": [i * cell, r * cell, cell, cell], "duration": dur}
                      for i, f in enumerate(row["files"])]
            out.append({"name": n, "fps": c["fps"], "loop": c["loop"], "frame_size": [cell, cell],
                        "pivot": [round(v, 2) for v in row["pivot"]], "sheet": c["sheet"], "frames": frames,
                        "length": sum(f["duration"] for f in frames)})
            if row["dir"] is not None:
                table.setdefault(c["action"], {})[row["dir"]] = n
    asset = {"kind": "animated_sprite", "name": name, "role": ROLE, "blend": "normal", "clips": out}
    if table:
        asset["directions"] = table
    return asset


def merge_manifest(existing, asset, pack, base):
    """A manifest document with `asset` added (or replacing the animated_sprite of its name). existing: the parsed
    file or None. Raises ValueError for a file this tool did not write (Dotwork rebuilds its own packs)."""
    if existing is None:
        doc = {"format": MANIFEST_FORMAT, "version": MANIFEST_VERSION, "pack": pack, "generator": GENERATOR,
               "base": base, "assets": []}
    else:
        if existing.get("format") != MANIFEST_FORMAT or existing.get("generator") != GENERATOR:
            raise ValueError(f"it was written by {existing.get('generator') or 'another tool'!r}, not {GENERATOR}: "
                             f"pick another pack name (Dotwork rebuilds its own manifests and would drop this asset)")
        if existing.get("base") != base:
            raise ValueError(f"its base is {existing.get('base')!r}, this run needs {base!r}")
        doc = dict(existing)
        doc["version"] = MANIFEST_VERSION
    kept = [a for a in doc.get("assets", []) if (a.get("kind"), a.get("name")) != ("animated_sprite", asset["name"])]
    doc["assets"] = sorted(kept + [asset], key=lambda a: (a.get("kind", ""), a.get("name", "")))
    return doc


def check_manifest(doc, base_dir):
    """assetspec.py's findings for the document (files checked under base_dir), or None when the validator is not
    beside this tool (a copy of render_sprites.py outside the kit)."""
    spec_dir = Path(__file__).resolve().parents[1] / "art" / "dotwork"
    if not (spec_dir / "assetspec.py").is_file():
        return None
    sys.path.insert(0, str(spec_dir))
    try:
        import assetspec
    finally:
        sys.path.remove(str(spec_dir))
    return assetspec.check(doc, str(base_dir))


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="render_sprites.py",
                                 description="Render a 3D model into a sprite sheet (directions x frames).")
    ap.add_argument("asset", help="model file: .glb .gltf .fbx .obj .blend")
    ap.add_argument("--out", help="sheet PNG to write (a .json with the layout goes next to it)")
    ap.add_argument("--action", help="animation to play (see --list-actions); default: whatever the file has active")
    ap.add_argument("--actions", metavar="LIST",
                    help="several animations, comma separated, or 'all': one sheet each, <out stem>_<action>.png")
    ap.add_argument("--step", type=int, default=1, help="keep every Nth frame of each action (default 1)")
    ap.add_argument("--manifest", metavar="FILE",
                    help="also write a Dotwork asset manifest (<pack>.assets.json) with one animated_sprite")
    ap.add_argument("--name", help="the animated_sprite's name in the manifest (default: the sheet's stem)")
    ap.add_argument("--once", action="append", default=[], metavar="ACTION",
                    help="an action that plays once and holds its last frame (manifest loop false; repeatable)")
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
    ap.add_argument("--overwrite", action="store_true", help="replace an existing sheet and its .json")
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
    if args.action and args.actions:
        ap.error("use --action or --actions, not both")
    if args.step < 1:
        ap.error("--step must be 1 or more")
    if args.frames and args.actions:
        ap.error("--frames picks one range; with --actions each action uses its own range (thin it with --step)")
    if args.manifest:
        if not args.manifest.endswith(MANIFEST_SUFFIX):
            ap.error(f"--manifest must end in {MANIFEST_SUFFIX} (<pack>{MANIFEST_SUFFIX})")
        if args.directions not in COMPASS:
            ap.error(f"--manifest needs --directions 1, 4 or 8 (Dotwork's direction names), not {args.directions}")
        if not (args.action or args.actions):
            ap.error("--manifest needs --action or --actions (a manifest clip is an animation)")
    if args.name is not None and not NAME_RE.match(args.name):
        ap.error("--name may use letters, digits, '_', '.' and '-' only")
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


def common(bpy):
    """bpy_common.py from this folder (clip names, clip frame rate, the exit): None when a lone copy of this script
    has no such neighbour."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import bpy_common
    except ImportError:
        return None
    return bpy_common


def import_asset(bpy, path):
    """Same import rules as validate_asset.py (shared on purpose)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from validate_asset import drop_back_to_back, import_asset as va_import  # noqa: E402
    va_import(bpy, path)
    removed = drop_back_to_back(bpy)
    if removed:
        print(f"[info] removed {removed} back-to-back duplicate faces (the file stores both sides of each face; "
              f"Cycles would render them black)")
    bc = common(bpy)
    if bc is not None:
        for old, new in bc.adopt_clip_names(bpy):   # Blender 4.2: "walk_Armature" is the clip "walk" (#292)
            dbg(f"action {old} is the clip {new}")


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
    """Warn when one mesh is much bigger than all the others together (a helper deciding the framing). A skinned
    mesh is never called a helper: it is the character."""
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
    if any(m.type == "ARMATURE" for m in scene.objects[biggest].modifiers):
        return   # a skinned body is the character, not a helper (beside a rig chain's small scarf strip, #291)
    rest = max(v for k, v in sizes.items() if k != biggest)
    if rest > 0 and sizes[biggest] > 2.5 * rest:
        print(f"[WARN] '{biggest}' ({sizes[biggest]:.2f} m) is {sizes[biggest] / rest:.1f}x bigger than any other mesh and "
              f"decides the framing. If it is a helper, add: --ignore \"{biggest}\"")


def new_bounds():
    from mathutils import Vector
    return {"lo": Vector((math.inf,) * 3), "hi": Vector((-math.inf,) * 3), "points": []}


def grow_bounds(bpy, scene, frames, box):
    """Grow box by all meshes over these frames (evaluated, so armatures and modifiers count). Called once per clip,
    with that clip's action assigned, so the framing covers every clip."""
    from mathutils import Vector
    lo, hi, points = box["lo"], box["hi"], box["points"]   # points: evaluated vertices, for the exact fit check
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
    box["lo"], box["hi"] = lo, hi


def merge_bounds(into, box):
    """Fold one clip's box into the union of every clip (the fit points stop at MAX_FIT_POINTS, as in grow_bounds)."""
    from mathutils import Vector
    into["lo"] = Vector(min(a, b) for a, b in zip(into["lo"], box["lo"]))
    into["hi"] = Vector(max(a, b) for a, b in zip(into["hi"], box["hi"]))
    if len(into["points"]) < MAX_FIT_POINTS:
        into["points"].extend(box["points"])


def rest_spot(bpy, scene):
    """(horizontal centre x, y, height) of the meshes in the rest pose (every armature at REST), or None without an
    armature: where the character stands, to compare each clip with."""
    arms = [o for o in scene.objects if o.type == "ARMATURE"]
    if not arms:
        return None
    saved = [(a, a.data.pose_position) for a in arms]
    box = new_bounds()
    try:
        for a, _ in saved:
            a.data.pose_position = "REST"
        grow_bounds(bpy, scene, [scene.frame_current], box)
    finally:
        for a, pos in saved:
            a.data.pose_position = pos
    lo, hi = box["lo"], box["hi"]
    if lo.x == math.inf or hi.z - lo.z <= 0:
        return None
    return (lo.x + hi.x) / 2, (lo.y + hi.y) / 2, hi.z - lo.z


def warn_clip_offset(action, box, rest):
    """Warn when a clip's model centre stands far sideways from the rest pose's (Tripo's in-place clips with an
    offset root did, 2026-11-11): the shared framing grows to hold it and every clip draws small."""
    lo, hi = box["lo"], box["hi"]
    if lo.x == math.inf:
        return
    x, y, height = rest
    d = math.hypot((lo.x + hi.x) / 2 - x, (lo.y + hi.y) / 2 - y)
    if d > CLIP_OFFSET_WARN * height:
        print(f"[WARN] {action}: the model's centre sits {d:.2f} m sideways from where it stands in the rest pose "
              f"({d / height:.1f}x its height), so the framing grows to hold it and every clip draws small. Its root "
              "bone likely carries a constant offset in every key: tools/bozzetto/rig_finish.py re-centres such clips "
              "(run it on the file, or rig it again), or render this clip on its own")


def scene_bounds(bpy, scene, frames):
    """Center, radius, reach and fit points of all meshes over these frames (one clip). bozzetto/turntable.py
    frames its contact sheet with it."""
    box = new_bounds()
    grow_bounds(bpy, scene, frames, box)
    return finish_bounds(box)


def finish_bounds(box):
    """Center, radius, reach (farthest corner from the origin) and fit points of the grown box."""
    from mathutils import Vector
    lo, hi, points = box["lo"], box["hi"], box["points"]
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


def same_pose(bpy, scene, f0, f1):
    """True when every evaluated mesh vertex is where it was (within LOOP_POSE_TOLERANCE) at frames f0 and f1."""
    def verts(f):
        scene.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        pts = []
        for obj in scene.objects:
            if obj.type == "MESH":
                ev = obj.evaluated_get(dg)
                pts.extend(ev.matrix_world @ v.co for v in ev.data.vertices)
        return pts
    a, b = verts(f0), verts(f1)
    return len(a) == len(b) and all((p - q).length <= LOOP_POSE_TOLERANCE for p, q in zip(a, b))


def plan_clips(bpy, scene, args):
    """[{action, frames, loop}] to render: every --actions entry, the one --action, or the file as it is."""
    if args.actions:
        if args.actions.strip() == "all":
            names = sorted(a.name for a in bpy.data.actions)
            if not names:
                raise ValueError("--actions all: the file has no animations")
        else:
            names = [n.strip() for n in args.actions.split(",") if n.strip()]
    else:
        names = [args.action]
    for once in args.once:
        if once not in names:
            print(f"[WARN] --once {once}: not one of the rendered actions ({', '.join(str(n) for n in names)})")
    clips = []
    for name in names:
        if name is None:
            clips.append({"action": None, "frames": args.frames or [scene.frame_current], "loop": True})
            continue
        start, end = assign_action(bpy, scene, name)
        loop = name not in args.once
        if args.frames:
            frames = list(args.frames)
        else:
            frames = list(range(start, end + 1, args.step))
            if loop and len(frames) > 1 and frames[-1] == end and same_pose(bpy, scene, start, end):
                frames.pop()   # a glTF loop's last key repeats its first pose: show it once per cycle
                dbg(f"{name}: frame {end} repeats frame {start}, rendered once")
            if loop and args.step > 1 and (end - start) % args.step:
                print(f"[WARN] {name}: {end - start} frames do not divide by --step {args.step}, so the frame that "
                      f"wraps the loop is held a little shorter or longer than the others")
        clips.append({"action": name, "frames": frames, "loop": loop})
    return clips


def sheet_path(out, action, several):
    return out.with_name(f"{out.stem}_{action}.png") if several else out


def pivot_in_cell(bpy, scene, cam, size):
    """Where the world origin (a Bozzetto model's feet) lands in a cell, in pixels from the top left."""
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    bpy.context.view_layer.update()
    p = world_to_camera_view(scene, cam, Vector((0.0, 0.0, 0.0)))
    return [p.x * size, (1.0 - p.y) * size]


def manifest_plan(args, out, sheets):
    """Checks before any render: (manifest path, base dir, base text, frames dir, existing doc) or an [ENV ] text."""
    manifest = Path(args.manifest)
    base_dir, base = manifest_base(manifest)
    for s in sheets:
        if rel_to(s, base_dir) is None:
            return None, (f"{s} is not inside {base_dir}, the folder {manifest.name}'s paths are relative to "
                          f"(the assets folder above its dotwork/ folder): put the sheets there")
    frames_dir = out.with_name(f"{out.stem}_frames")
    if frames_dir.exists() and any(frames_dir.iterdir()) and not args.overwrite:
        return None, f"{frames_dir} exists (use --overwrite)"
    existing = None
    if manifest.exists():
        try:
            existing = json.loads(manifest.read_text(encoding="utf-8"))
            merge_manifest(existing, {"kind": "animated_sprite", "name": "probe"}, manifest.name, base)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            return None, f"{manifest} cannot take this asset: {exc}"
    return (manifest, base_dir, base, frames_dir, existing), None


def write_layout(out, args, angles, frames, action, ortho, source):
    meta = {
        "image": out.name, "cell_width": args.size, "cell_height": args.size,
        "rows": "directions", "columns": "frames",
        "directions": [{"row": i, "angle_deg": a} for i, a in enumerate(angles)],
        "frames": frames, "action": action, "elevation_deg": args.elevation, "source": source,
        "note": "row 0 = front (camera on -Y); angles turn counter-clockwise seen from above",
        "world_size_m": round(ortho, 6), "pixels_per_meter": round(args.size / ortho, 6), "pivot": args.pivot,
        "pivot_px": [args.size / 2, args.size / 2] if args.pivot == "origin" else None,
        "ground_depth_scale": round(math.sin(math.radians(args.elevation)), 6),
        "note_scale": "a ground offset (dx, dy) in meters is (dx, dy * ground_depth_scale) * pixels_per_meter on screen",
    }
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def run(args):
    path, out = Path(args.asset), Path(args.out or "unused.png")
    if not path.exists():
        print(f"[ENV ] asset not found: {path}", file=sys.stderr)
        return 2
    if out.suffix.lower() != ".png":
        print("[ENV ] --out must end in .png", file=sys.stderr)
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
    bc = common(bpy)
    if bc is not None and (args.action or args.actions) and bpy.data.actions:
        # Tripo's 30 fps clips land every 0.8 frames in a 24 fps scene: rendering whole frames would miss the keys
        # and the manifest would hold 24 fps durations for a 30 fps clip (#292)
        bc.conform_clip_fps(bpy, scene, list(bpy.data.actions))
    try:
        clips = plan_clips(bpy, scene, args)
    except ValueError as exc:
        print(f"[ENV ] {exc}", file=sys.stderr)
        return 2
    several = bool(args.actions)
    for c in clips:
        c["sheet"] = sheet_path(out, c["action"], several)
    for c in clips:                                       # the sheets and the layout JSON beside each
        for f in (c["sheet"], c["sheet"].with_suffix(".json")):
            if f.exists() and not args.overwrite:
                print(f"[ENV ] {f} exists (use --overwrite)", file=sys.stderr)
                return 2
    mplan = None
    if args.manifest:
        mplan, why = manifest_plan(args, out, [c["sheet"] for c in clips])
        if mplan is None:
            print(f"[ENV ] {why}", file=sys.stderr)
            return 2

    box = new_bounds()
    rest = rest_spot(bpy, scene) if any(c["action"] for c in clips) else None
    for c in clips:
        if c["action"]:
            assign_action(bpy, scene, c["action"])
        own = new_bounds()
        grow_bounds(bpy, scene, c["frames"], own)
        if rest and c["action"]:
            warn_clip_offset(c["action"], own, rest)
        merge_bounds(box, own)
    center, radius, reach, corners = finish_bounds(box)
    if center is None:
        print("[FAIL] no mesh objects found in the file", file=sys.stderr)
        return 1
    dbg(f"center {tuple(round(v, 3) for v in center)} radius {radius:.3f} clips "
        f"{[(c['action'], c['frames']) for c in clips]}")
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
    pivots = []
    for angle in angles:
        place_camera(cam, center, radius, angle, args.elevation)
        pivots.append(pivot_in_cell(bpy, scene, cam, args.size))

    if mplan and mplan[3].exists() and args.overwrite:   # our own frames folder: old frames of dropped clips go
        for old in mplan[3].glob("*.png"):
            old.unlink()
    rendered = []
    for c in clips:
        if c["action"]:
            assign_action(bpy, scene, c["action"])
        cells = {}
        with tempfile.TemporaryDirectory(prefix="sprites_") as tmp:
            for row, angle in enumerate(angles):
                place_camera(cam, center, radius, angle, args.elevation)
                for col, f in enumerate(c["frames"]):
                    scene.frame_set(f)
                    cell = Path(tmp) / f"r{row:02d}_c{col:03d}.png"
                    scene.render.filepath = str(cell)
                    bpy.ops.render.render(write_still=True)
                    if not cell.exists():
                        print(f"[FAIL] render produced no image for {c['action'] or 'the model'} direction {angle:g} "
                              f"frame {f}", file=sys.stderr)
                        return 1
                    cells[(row, col)] = cell
                    dbg(f"rendered {c['action']} direction {angle:g} frame {f}")
            sheet = c["sheet"]
            sheet.parent.mkdir(parents=True, exist_ok=True)
            stitch(bpy, cells, len(angles), len(c["frames"]), args.size, sheet.resolve())
            if mplan:
                rows = []
                for row, d in enumerate(COMPASS[args.directions]):
                    files = []
                    for col in range(len(c["frames"])):
                        dst = mplan[3] / f"{clip_name(c['action'], d)}_{col:02d}.png"
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(cells[(row, col)], dst)
                        files.append(rel_to(dst, mplan[1]))
                    rows.append({"dir": d, "pivot": pivots[row], "files": files})
                fps = scene.render.fps / scene.render.fps_base / args.step
                rendered.append({"action": c["action"], "loop": c["loop"], "rows": rows,
                                 "fps": int(fps) if fps == int(fps) else round(fps, 6),
                                 "sheet": rel_to(sheet, mplan[1])})
        write_layout(sheet, args, angles, c["frames"], c["action"], ortho, path.name)
        print(f"[ OK ] {sheet}: {len(angles)} direction(s) x {len(c['frames'])} frame(s) of {args.size} px "
              f"({len(c['frames']) * args.size} x {len(angles) * args.size}), layout in {sheet.with_suffix('.json').name}")

    if mplan:
        manifest, base_dir, base, _, existing = mplan
        name = args.name or out.stem
        doc = merge_manifest(existing, build_asset(name, rendered, args.size), manifest.name[:-len(MANIFEST_SUFFIX)], base)
        errs = check_manifest(doc, base_dir)
        if errs:
            print(f"[FAIL] the manifest would not pass assetspec.py ({len(errs)} findings), not written:", file=sys.stderr)
            for e in errs[:20]:
                print(f"  {e}", file=sys.stderr)
            return 1
        if errs is None:
            print("[WARN] tools/art/dotwork/assetspec.py not found beside this tool: the manifest is not validated")
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(doc, indent=1) + "\n")
        n = sum(len(r["rows"]) for r in rendered)
        print(f"[ OK ] {manifest}: animated_sprite {name!r}, {n} clip(s) "
              f"({', '.join(clip_name(r['action'], d['dir']) for r in rendered for d in r['rows'][:1])} ...), "
              f"frames in {mplan[3].name}/")
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


def exit_with(code):
    """sys.exit, or with the bpy module on Windows the process end that does not crash after a render (#292)."""
    try:
        import bpy
    except ImportError:
        sys.exit(code)
    bc = common(bpy)
    if bc is None:
        sys.exit(code)
    bc.end_process(bpy, code)


if __name__ == "__main__":
    exit_with(main())
