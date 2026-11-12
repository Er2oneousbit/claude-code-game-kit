# ---------------------------------------------------------------------------
# import_dotwork.py
# Purpose : Imports every Dotwork pack of the game (assets/dotwork/<pack>.assets.json) as Paper2D assets under
#           /Game/Dotwork/<pack>/ and saves them, then builds the demo level /Game/Dotwork/L_DotworkDemo: the tile
#           map, its props where the map places them, one character walking and a label in the pack's font.
# Usage   : python tools/dev.py exec Content/Python/kit_dotwork/import_dotwork.py
#           DOTWORK_MANIFESTS=<file>[;<file>...]  only these manifests (; on Windows, : elsewhere: os.pathsep)
#           DOTWORK_DEMO=0                         skip the demo level
# Notes   : Run it again after every `dotwork.py pack`: assets are updated in place, so levels and Blueprints that
#           use them keep their references. Assets a pack no longer has are left in place (delete them by hand).
#           Prints DOTWORK_IMPORTED <pack> <assets> per pack and DOTWORK_DEMO <level> (dev.py echoes LogPython lines).
#           Pseudocode
#             manifests = DOTWORK_MANIFESTS or every *.assets.json in assets/dotwork/
#             per manifest: Importer(path).run() then save(); one failing pack fails the run after the others
#             demo: a new level with a PaperTileMapActor (first map), PaperSpriteActors at the map's objects
#             (dotwork_paper.map_to_local: Paper2D is X right, Z up, and centres cell (0, 0) on the actor), a
#             PaperFlipbookActor playing the first walk clip, a TextRenderActor in the first font, an orthographic
#             camera looking along +Y, saved as L_DotworkDemo
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): the demo places objects through map_to_local
#           (cell (0, 0)'s centre is the tile map's origin, not its top-left; isometric maps too), #285
# ---------------------------------------------------------------------------
import os

import unreal

from kit_dotwork import dotwork_paper as paper
from kit_dotwork import dotwork_spec as spec

# ---- Tunables ------------------------------------------------------------------
DEMO_LEVEL = f"{paper.DEST_ROOT}/L_DotworkDemo"
DEMO_TEXT = "Dotwork"
DEMO_CAMERA_WIDTH = 480.0                    # orthographic width in Unreal units (= art pixels at 1 px per unit)
DEMO_SCALE = 1.0                             # draw scale of every demo actor
DEMO_LABEL_LINES = 3                         # the label's height in font lines (TextRender draws offline fonts small)
WALK_CLIPS = ("walk_s", "walk_e", "walk_w", "walk_n")   # the character clip the demo plays, first found


def manifests(root):
    listed = os.environ.get("DOTWORK_MANIFESTS", "").strip()
    if listed:
        return [p if os.path.isabs(p) else os.path.join(root, p) for p in listed.split(os.pathsep) if p.strip()]
    return spec.find_manifests(root)


def main():
    root = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
    found = manifests(root)
    if not found:
        unreal.log(f"DOTWORK_NONE no {spec.MANIFEST_SUFFIX} files in {', '.join(spec.MANIFEST_DIRS)} "
                   "(run Dotwork's pack with --engine none first)")
        return
    done, failed = [], []
    for path in found:
        try:
            imp = paper.Importer(path).run()
            imp.save()
            done.append(imp)
            unreal.log(f"DOTWORK_IMPORTED {imp.pack} {len(imp.records)}")
        except (spec.ManifestError, paper.ImportFailed, RuntimeError) as exc:
            failed.append(f"{os.path.basename(path)}: {exc}")
    if done and os.environ.get("DOTWORK_DEMO", "1") != "0":
        build_demo(done)
    if failed:
        raise RuntimeError("Dotwork import failed for " + "; ".join(failed))


def first(done, kind, pick=None):
    """The first record of a kind across the imported packs (pick filters)."""
    for imp in done:
        for key, rec in imp.records.items():
            if rec["kind"] == kind and (pick is None or pick(rec)):
                return rec
    return None


def spawn(cls, x, z, y=0.0, yaw=0.0):
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = actors.spawn_actor_from_class(cls, unreal.Vector(x, y, z), unreal.Rotator(0.0, 0.0, yaw))
    actor.set_actor_scale3d(unreal.Vector(DEMO_SCALE, DEMO_SCALE, DEMO_SCALE))
    return actor


def build_demo(done):
    """The demo level: what the packs hold, placed in Paper2D's plane (X right, Z up), seen as Paper2D's own
    2D template sees it: from +Y looking along -Y (tile layer 0 and smaller Y are nearer the camera)."""
    unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    tile_size, box = [0, 0], (0.0, 0.0, 0.0, 0.0)   # the map's box in map pixels: left, top, right, bottom
    tm = first(done, "map")
    if tm:
        # Components of editor-placed actors are static: set the asset properties (SetSprite and friends refuse)
        actor = spawn(unreal.PaperTileMapActor, 0.0, 0.0)
        actor.get_editor_property("render_component").set_editor_property("tile_map", tm["map"])
        tile_size = tm["tile_size"]
        (mw, mh), (w, h) = tm["doc"]["size"], tile_size
        if tm["shape"] == "isometric":                # the diamonds spread left of cell (0, 0) as y grows
            box = (-mh * w / 2, 0.0, (mw + 1) * w / 2, (mw + mh) * h / 2)
        else:
            box = (0.0, 0.0, mw * w, mh * h)
        sprites = {key.split("/", 1)[1]: rec["sprite"] for imp in done
                   for key, rec in imp.records.items() if rec["kind"] == "sprite"}
        for obj in tm["doc"].get("objects") or []:
            sp = sprites.get(obj["asset"])
            if sp:
                # The map's cell (0, 0) is centred on its actor (map_to_local). Objects are a little nearer the
                # camera (+Y) so they draw over the tiles.
                x, z = paper.map_to_local(obj["x"], obj["y"], tile_size)
                spawn(unreal.PaperSpriteActor, x, z, y=10.0).get_editor_property(
                    "render_component").set_editor_property("source_sprite", sp)
    # the middle of the map in the plane, where the walker and the camera go
    mid_x, mid_z = paper.map_to_local((box[0] + box[2]) / 2, (box[1] + box[3]) / 2, tile_size)
    walker = first(done, "animated_sprite", lambda r: any(c in r["clips"] for c in WALK_CLIPS))
    if walker:
        clip = next(c for c in WALK_CLIPS if c in walker["clips"])
        actor = spawn(unreal.PaperFlipbookActor, mid_x, mid_z, y=20.0)
        actor.get_editor_property("render_component").set_editor_property(
            "source_flipbook", walker["clips"][clip]["flipbook"])
    font = first(done, "font")
    if font:
        codes = set(font["codes"])
        label_text = DEMO_TEXT if all(ord(ch) in codes for ch in DEMO_TEXT) else \
            "".join(chr(c) for c in font["codes"] if 32 < c < 0x10000)[:16]   # a font without those letters
        size = DEMO_LABEL_LINES * font["font"].get_editor_property("legacy_font_size")
        label = spawn(unreal.TextRenderActor, 0.0, 4.0 + size,
                      y=10.0, yaw=90.0)          # TextRender faces +X: turned to face the camera at +Y
        text = label.get_editor_property("text_render")
        text.set_editor_property("font", font["font"])
        text.set_editor_property("text", label_text)
        text.set_editor_property("world_size", size)
        spawn(unreal.DirectionalLight, 0.0, 0.0, y=1000.0, yaw=-90.0)   # TextRender's material is lit; sprites are not
    camera = spawn(unreal.CameraActor, mid_x, mid_z, y=1000.0, yaw=-90.0)
    cam = camera.get_editor_property("camera_component")
    cam.set_editor_property("projection_mode", unreal.CameraProjectionMode.ORTHOGRAPHIC)
    cam.set_editor_property("ortho_width", DEMO_CAMERA_WIDTH)
    camera.set_editor_property("auto_activate_for_player", unreal.AutoReceiveInput.PLAYER0)
    if not unreal.EditorLoadingAndSavingUtils.save_map(unreal.get_editor_subsystem(
            unreal.UnrealEditorSubsystem).get_editor_world(), DEMO_LEVEL):
        raise RuntimeError(f"could not save {DEMO_LEVEL}")
    unreal.log(f"DOTWORK_DEMO {DEMO_LEVEL}")


main()
