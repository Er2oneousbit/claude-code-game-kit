# ---------------------------------------------------------------------------
# test_dotwork_golden.py
# Purpose : Automation test: imports the Dotwork golden pack (data/golden/dotwork/) into the transient package with
#           the Paper2D importer, reads the assets back and compares them with expected.json (to 1e-6): frame rects,
#           seconds per frame, pivots, collision boxes, tile collision, the three maps (every terrain cell's key and
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
        if blocks and blocks["offset"] != [0, 0]:
            diffs.append(f"{ISO_MAP}: the blocks tile set got Drawing Offset {blocks['offset']}, expected [0, 0] "
                         "(a 16x12 block with origin [8, 8] is where Paper2D's bottom alignment puts it)")
    return diffs
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


main()
