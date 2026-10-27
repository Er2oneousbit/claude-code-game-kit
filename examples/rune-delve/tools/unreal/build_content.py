# ---------------------------------------------------------------------------
# build_content.py  (editor Python, run headless)
# Purpose : Everything in Content/ comes from this script, so nobody hand-edits binary assets:
#           imports the Kenney models and the ElevenLabs sounds from assets_src/, and makes the Delve map.
# Usage   : python tools/dev.py exec tools/unreal/build_content.py
# Notes   : Re-run after adding a model or sound (imports replace the old asset; a sound whose file is gone from
#           assets_src/audio is deleted, and *-ambience waves are set to loop). The map holds only a
#           NavMesh bounds volume and a PlayerStart: the game spawns rooms, props, lights and characters from C++ data
#           at runtime (Config/DefaultEngine.ini sets RuntimeGeneration=Dynamic, so the NavMesh follows).
#           Prints each prop's size so the C++ layout uses measured tile sizes, not guesses.
#
# Pseudocode:
#   import characters -> /Game/Art/Characters, props -> /Game/Art/Dungeon, sounds -> /Game/Audio (loops, stale)
#   -> print bounds of every static mesh -> new blank map -> NavMeshBoundsVolume + PlayerStart -> save
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import unreal

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODELS = os.path.join(ROOT, "assets_src", "mini-dungeon")
SOUNDS = os.path.join(ROOT, "assets_src", "audio")
CHARACTERS = ("character-human.fbx", "character-orc.fbx")
MAP = "/Game/Maps/Delve"
# NavMesh bounds: the same box as FRDLevel::NavBounds() (RDLevel.cpp), and the mage's start (FRDLevel::MageStart).
# Centimetres. RuneDelve.Smoke.Boot checks the NavMesh covers every room, so a drift here fails a test.
NAV_CENTER = unreal.Vector(3000.0, 0.0, 100.0)
NAV_SIZE = unreal.Vector(6400.0, 2000.0, 600.0)
PLAYER_START = unreal.Vector(400.0, 0.0, 100.0)
BRUSH_SIZE = 200.0  # a new box volume's brush is 200 cm on each side


def import_files(files, dest):
    tasks = []
    for f in files:
        t = unreal.AssetImportTask()
        t.filename = f
        t.destination_path = dest
        t.automated = True
        t.save = True
        t.replace_existing = True
        tasks.append(t)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
    for t in tasks:
        if not t.imported_object_paths:
            unreal.log_error("nothing imported from %s" % t.filename)
    return sum(len(t.imported_object_paths) for t in tasks)


def main():
    fbx = sorted(f for f in os.listdir(MODELS) if f.endswith(".fbx"))
    n = import_files([os.path.join(MODELS, f) for f in fbx if f in CHARACTERS], "/Game/Art/Characters")
    n += import_files([os.path.join(MODELS, f) for f in fbx if f not in CHARACTERS], "/Game/Art/Dungeon")
    sound_files = sorted(f for f in os.listdir(SOUNDS) if f.endswith((".ogg", ".wav")))
    n += import_files([os.path.join(SOUNDS, f) for f in sound_files], "/Game/Audio")
    keep = {os.path.splitext(f)[0] for f in sound_files}
    for path in unreal.EditorAssetLibrary.list_assets("/Game/Audio"):
        name = path.rsplit("/", 1)[-1].split(".")[0]
        if name not in keep:
            unreal.EditorAssetLibrary.delete_asset(path)
            unreal.log("deleted %s (no file in assets_src/audio)" % path)
        elif name.endswith("-ambience"):
            wave = unreal.EditorAssetLibrary.load_asset(path)
            wave.set_editor_property("looping", True)
            unreal.EditorAssetLibrary.save_asset(path)
            unreal.log("LOOP %s" % path)
    unreal.log("imported %d assets" % n)

    for path in sorted(unreal.EditorAssetLibrary.list_assets("/Game/Art/Dungeon")):
        mesh = unreal.EditorAssetLibrary.load_asset(path)
        if isinstance(mesh, unreal.StaticMesh):
            b = mesh.get_bounding_box()
            size = b.max - b.min
            unreal.log("BOUNDS %-24s size %7.1f %7.1f %7.1f  min %7.1f %7.1f %7.1f" % (
                mesh.get_name(), size.x, size.y, size.z, b.min.x, b.min.y, b.min.z))
    for path in sorted(unreal.EditorAssetLibrary.list_assets("/Game/Audio")):
        unreal.log("SOUND %s" % path)

    world = unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    vol = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.NavMeshBoundsVolume, NAV_CENTER)
    vol.set_actor_scale3d(NAV_SIZE / BRUSH_SIZE)
    unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.PlayerStart, PLAYER_START)
    unreal.log("nav bounds %s" % vol.get_actor_bounds(False)[1])
    if not unreal.EditorLoadingAndSavingUtils.save_map(world, MAP):
        unreal.log_error("could not save %s" % MAP)
    unreal.log("map saved: %s" % MAP)


main()
