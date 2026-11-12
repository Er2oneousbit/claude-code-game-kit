# ---------------------------------------------------------------------------
# test_dotwork_golden.py
# Purpose : Automation test: imports the Dotwork golden pack (data/golden/dotwork/) into the transient package with
#           the Paper2D importer, reads the assets back and compares them with expected.json (to 1e-6): frame rects,
#           seconds per frame, pivots, collision boxes, tile collision, the terrain map cell by cell, font metrics,
#           9-slice margins. Every imported texture must be nearest-filtered without mips. Then the same for the
#           sheet render_sprites.py --manifest rendered from the golden rigged character (data/golden/character/
#           sprites/, #290), so a 3D character's sheets reach Paper2D through the same importer.
# Usage   : python tools/dev.py test   (runs as Editor.Python.<Game>.kit_dotwork.test_dotwork_golden; needs the
#           PythonScriptPlugin and PythonAutomationTest plugins enabled in the .uproject: docs/ENGINE.md "Dotwork art")
#           python tools/dev.py exec Content/Python/kit_dotwork/test_dotwork_golden.py   (the same check, no plugin)
# Notes   : Kinds the importer skips on purpose (dotwork_paper.SKIPPED_KINDS) are named, not failed. Nothing is saved.
#           dev.py test runs this file twice when the PythonAutomationTest plugin is on: as an automation test in the
#           editor (where a font's page count is skipped, see dotwork_paper._font) and through the pythonscript
#           commandlet (everything compared); without the plugin, only the commandlet run.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): the rendered character sheet imports to its
#           expected.json (0.15.0 review, #290)
# ---------------------------------------------------------------------------
import json
import os

import unreal

from kit_dotwork import dotwork_paper as paper
from kit_dotwork import dotwork_spec as spec

GOLDEN = "data/golden/dotwork"
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
    for line in diffs:
        unreal.log_error(f"DOTWORK_DIFF {line}")
    if diffs:
        raise AssertionError(f"the golden pack differs from expected.json in {len(diffs)} place(s): see DOTWORK_DIFF")
    unreal.log(f"DOTWORK_GOLDEN_OK {len(actual)} asset(s) match expected.json ({len(imp.textures)} textures)")
    check_rendered_character(root)


main()
