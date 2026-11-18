# ---------------------------------------------------------------------------
# test_dotwork_golden.py
# Purpose : Automation test: imports the Dotwork golden pack (data/golden/dotwork/) into the transient package with
#           the Paper2D importer, reads the assets back and compares them with expected.json (to 1e-6): frame rects,
#           seconds per frame, pivots, collision boxes, tile collision, the maps (every terrain cell's key and
#           picked variant, every drawn tile's image corner, every cell's centre from Paper2D's own
#           GetTileCenterPosition: the isometric map proves Paper2D's diamond grid is the spec's), font metrics,
#           9-slice margins. Every imported texture must be nearest-filtered without mips, the particles asset must
#           expose its texture and emitter, and the stamps layer its expanded tiles.
#           Then the same for the sheet render_sprites.py --manifest rendered from the golden rigged character
#           (data/golden/character/sprites/, #290), so a 3D character's sheets reach Paper2D through the same importer.
# Usage   : python tools/dev.py test   (runs as Editor.Python.<Game>.kit_dotwork.test_dotwork_golden; needs the
#           PythonScriptPlugin and PythonAutomationTest plugins enabled in the .uproject: docs/ENGINE.md "Dotwork art")
#           python tools/dev.py exec Content/Python/kit_dotwork/test_dotwork_golden.py   (the same check, no plugin)
# Notes   : Kinds the importer skips on purpose (dotwork_paper.SKIPPED_KINDS, none at spec 1.1.0) are named, not
#           failed. Nothing is saved.
#           dev.py test runs this file twice when the PythonAutomationTest plugin is on: as an automation test in the
#           editor (where a font's page count is skipped, see dotwork_paper._font) and through the pythonscript
#           commandlet (everything compared); without the plugin, only the commandlet run.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): placed cells and centres,
#           the stamps layer, particles loaded, the isometric map's centres straight from Paper2D;
#           the rendered character sheet imports to its expected.json (0.15.0 review, #290)
# Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): #286: the additive effect's flipbooks and frames draw
#           with an additive material, the water tiles carry their animation in Paper2D's tile user data, the
#           two-page font's glyph lands at its xoffset with its xadvance, and a re-import removes what the pack
#           dropped (and nothing of yours)
# ---------------------------------------------------------------------------
import json
import os

import unreal

from kit_dotwork import dotwork_paper as paper
from kit_dotwork import dotwork_spec as spec

GOLDEN = "data/golden/dotwork"
ISO_MAP = "map/isle"                        # the golden isometric map (16x8 diamonds, 4x3 cells)
STAMPS_LAYER = ("map/yard", "Fixtures")     # the golden stamps layer: one 1x2 door at (7, 0)
PARTICLES = "particles/vfx_embers_particles"
ADDITIVE = "animated_sprite/fx_spark"        # the golden pack's blend "add" effect
WATER = ("tileset/ground_yard", 2)          # the golden animated terrain: atlas 2, 2 frames at 4 fps
OFFSET_FONT = ("font/duo", 65)              # glyph 65 of duo: page 1, xoffset 1, xadvance 5
PRUNE_DEST = "/Game/DotworkPruneTest"       # the re-import check saves here, then deletes the folder


def extra_checks(imp, actual, expected):
    """What expected.json cannot say about Unreal: the lines that would make the golden pass for the wrong reason."""
    diffs = []
    rec = imp.records.get(PARTICLES)
    if not rec or not isinstance(rec.get("texture"), unreal.Texture2D) or not rec.get("emitter", {}).get("amount"):
        diffs.append(f"{PARTICLES}: not loaded as a texture with its emitter JSON")
    key, layer = STAMPS_LAYER
    door = actual.get(key, {}).get("placed", {}).get(layer, [])
    if len(door) != 2 or [c[:2] for c in door] != [[7, 0], [7, 1]]:
        diffs.append(f"{key}.{layer}: the stamps layer did not expand to the door's two tiles: {door}")
    isle = imp.records.get(ISO_MAP)
    if not isle:
        diffs.append(f"{ISO_MAP}: not built")
    else:
        mode = isle["map"].get_editor_property("projection_mode")
        if mode != unreal.TileMapProjectionMode.ISOMETRIC_DIAMOND:
            diffs.append(f"{ISO_MAP}: projection {mode}, not ISOMETRIC_DIAMOND")
        # the spec's spot numbers, straight from Paper2D's GetTileCenterPosition through map_to_local's inverse
        comp = unreal.new_object(unreal.PaperTileMapComponent)
        comp.set_tile_map(isle["map"])
        for (x, y), want in {(0, 0): [8, 4], (1, 0): [16, 8], (0, 1): [0, 8], (3, 2): [16, 24]}.items():
            got = paper.local_to_map(comp.get_tile_center_position(x, y, 0, False), isle["tile_size"])
            if spec.compare(want, got):
                diffs.append(f"{ISO_MAP}: Paper2D centres cell {(x, y)} at {got}, the spec at {want}")
        blocks = next((info for aid, info in isle["tileset"]["atlases"].items() if aid == 1), None)
        if blocks is None:
            diffs.append(f"{ISO_MAP}: no blocks atlas")
        if blocks and blocks["offset"] != [0, 0]:
            diffs.append(f"{ISO_MAP}: the blocks tile set got Drawing Offset {blocks['offset']}, expected [0, 0] "
                         "(a 16x12 block with origin [8, 8] is where Paper2D's bottom alignment puts it)")
    diffs += checks_286(imp)
    return diffs


def checks_286(imp):
    """#286, read from the engine objects: additive blend, tile animation data, a glyph's offset and advance."""
    diffs = []
    rec = imp.records.get(ADDITIVE)
    for name, c in (rec or {}).get("clips", {}).items():
        fb = c["flipbook"]
        mats = [fb.get_editor_property("default_material")] + [
            k.get_editor_property("sprite").get_editor_property("default_material")
            for k in fb.get_editor_property("key_frames")]
        modes = {m.get_blend_mode() if m else None for m in mats}
        if modes != {unreal.BlendMode.BLEND_ADDITIVE}:
            diffs.append(f"{ADDITIVE}/{name}: the flipbook and its frames draw with {modes}, not additively")
    if not rec:
        diffs.append(f"{ADDITIVE}: not built")
    key, atlas = WATER
    ts = imp.records.get(key, {}).get("atlases", {}).get(atlas, {}).get("tileset")
    anims = [spec.parse_tile_user_data(md.get_editor_property("user_data_name"))
             for md in (ts.get_editor_property("per_tile_data") if ts else [])]
    if sum(1 for _, frames, fps in anims if frames == 2 and fps == 4) != 47:
        diffs.append(f"{key} atlas {atlas}: the 47 water tiles do not all say anim=2@4 in their user data")
    key, code = OFFSET_FONT
    f = imp.records.get(key)
    sample = paper._font_back(f)["sample"] if f else None
    if not sample or sample[5] != 1 or sample[7] != 5 or sample[8] != 1:
        diffs.append(f"{key}: glyph {code} should land 1 px right of the pen and advance 5 on page 1, got {sample}")
    return diffs


def check_prune(root):
    """A re-import deletes what the pack no longer has (tagged by an earlier run) and keeps an untagged asset."""
    src = os.path.join(root, GOLDEN, "assets", "dotwork", "golden.assets.json")
    with open(src, encoding="utf-8") as f:
        doc = json.load(f)
    tmp = os.path.join(os.path.dirname(src), "prune_test.assets.json")
    keep = [a for a in doc["assets"] if (a["kind"], a["name"]) in (("sprite", "crate"), ("image", "logo_golden"))]
    lib = unreal.EditorAssetLibrary
    try:
        # the second run drops the crate: its sprite and the texture it uses go, users first
        for assets in (keep, [a for a in keep if a["kind"] == "image"]):
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(dict(doc, assets=assets), f)
            if not lib.does_asset_exist(f"{PRUNE_DEST}/Mine/MI_Mine"):
                unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                    "MI_Mine", f"{PRUNE_DEST}/Mine", unreal.MaterialInstanceConstant,
                    unreal.MaterialInstanceConstantFactoryNew())
            imp = paper.Importer(tmp, dest=PRUNE_DEST).run()
            imp.save()
        problems = []
        for gone in (f"{PRUNE_DEST}/Sprites/S_crate", f"{PRUNE_DEST}/Textures/art/props/T_spr_crate"):
            if gone not in imp.pruned or lib.does_asset_exist(gone):
                problems.append(f"{gone}, which the pack dropped, is still there (pruned: {imp.pruned})")
        if not lib.does_asset_exist(f"{PRUNE_DEST}/Textures/art/brand/golden/T_logo_golden"):
            problems.append("the logo the pack still has was deleted")
        if not lib.does_asset_exist(f"{PRUNE_DEST}/Mine/MI_Mine"):
            problems.append("an asset the importer did not make was deleted")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
        # users before what they use (a sprite before its texture): deleting a whole folder at once trips an
        # ensure ("failed to unload all packages") while the sprite still holds its texture
        paths = [str(p).split(".")[0] for p in lib.list_assets(PRUNE_DEST, recursive=True, include_folder=False)]
        for path in sorted(paths, key=lambda p: "/Textures/" in p):
            lib.delete_asset(path)
            unreal.SystemLibrary.collect_garbage()
        lib.delete_directory(PRUNE_DEST)
    for line in problems:
        unreal.log_error(f"DOTWORK_DIFF prune: {line}")
    if problems:
        raise AssertionError("re-import pruning: see DOTWORK_DIFF")
    unreal.log(f"DOTWORK_PRUNE_OK a re-import removed {len(imp.pruned)} dropped asset(s) and kept the rest")


RENDERED = "data/golden/character/sprites"   # a sheet render_sprites.py --manifest made from the golden rigged character


def check_rendered_character(root):
    """The rendered character's manifest (#290: rows are directions, columns frames, one animated_sprite with a clip
    per action and direction) imports to its own expected.json like any Dotwork pack."""
    folder = os.path.join(root, RENDERED)
    imp = paper.Importer(os.path.join(folder, "dotwork", "character.assets.json"), transient=True).run()
    with open(os.path.join(folder, "expected.json"), encoding="utf-8") as f:
        expected = json.load(f)["assets"]
    actual = paper.loaded(imp)
    diffs = []
    for key, want in expected.items():
        if key in actual:
            spec.compare(want, actual[key], key, out=diffs)
        else:
            diffs.append(f"{key}: not loaded")
    diffs += [f"{key}: loaded but not in expected.json" for key in actual if key not in expected]
    diffs += paper.texture_settings_problems(imp)
    if not expected:
        diffs.append(f"{RENDERED}/expected.json names no asset")
    for line in diffs:
        unreal.log_error(f"DOTWORK_DIFF rendered character: {line}")
    if diffs:
        raise AssertionError(f"the rendered character differs from its expected.json in {len(diffs)} place(s): see DOTWORK_DIFF")
    unreal.log(f"DOTWORK_RENDERED_OK {len(actual)} asset(s) match {RENDERED}/expected.json ({len(imp.textures)} textures)")


def main():
    root = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
    gold = os.path.join(root, GOLDEN)
    imp = paper.Importer(os.path.join(gold, "assets", "dotwork", "golden.assets.json"), transient=True).run()
    with open(os.path.join(gold, "expected.json"), encoding="utf-8") as f:
        expected = json.load(f)["assets"]
    actual = paper.loaded(imp)
    if imp.font_pages_blocked:
        # A full editor session (the PythonAutomationTest run) cannot attach a font's pages; dev.py test also runs
        # this file through the commandlet, where they are attached and compared.
        for key in [k for k in expected if k.startswith("font/")]:
            expected[key].pop("pages", None)
            actual.get(key, {}).pop("pages", None)
            unreal.log(f"DOTWORK_SKIPPED {key}.pages (the editor blocks `set`; checked by the commandlet run)")
    diffs = []
    for key, want in expected.items():
        if key in actual:
            spec.compare(want, actual[key], key, out=diffs)
        elif key.split("/")[0] in paper.SKIPPED_KINDS:
            unreal.log(f"DOTWORK_SKIPPED {key} (not built in Unreal yet)")
        else:
            diffs.append(f"{key}: not loaded")
    diffs += [f"{key}: loaded but not in expected.json" for key in actual if key not in expected]
    diffs += paper.texture_settings_problems(imp)
    diffs += extra_checks(imp, actual, expected)
    for line in diffs:
        unreal.log_error(f"DOTWORK_DIFF {line}")
    if diffs:
        raise AssertionError(f"the golden pack differs from expected.json in {len(diffs)} place(s): see DOTWORK_DIFF")
    maps = [k for k in actual if k.startswith("map/")]
    cells = sum(len(v) for k in maps for v in actual[k]["placed"].values())
    unreal.log(f"DOTWORK_GOLDEN_OK {len(actual)} asset(s) match expected.json ({len(imp.textures)} textures, "
               f"{len(maps)} maps, {cells} placed cells, {len(imp.warnings)} warning(s))")
    check_rendered_character(root)
    check_prune(root)


main()
