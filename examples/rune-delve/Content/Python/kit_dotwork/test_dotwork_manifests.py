# ---------------------------------------------------------------------------
# test_dotwork_manifests.py
# Purpose : Automation test: every Dotwork manifest of the game (assets/dotwork/*.assets.json) is valid and loads.
#           Each one is validated with tools/art/dotwork/assetspec.py (schema, files on disk, PNG sizes, frame rects,
#           map cells) and then built in the transient package by the Paper2D importer; a missing file or a broken
#           asset fails. Unreal's stand-in for Dotwork's Godot-only `verify`.
# Usage   : python tools/dev.py test   (Editor.Python.<Game>.kit_dotwork.test_dotwork_manifests)
#           python tools/dev.py exec Content/Python/kit_dotwork/test_dotwork_manifests.py
# Notes   : A game without Dotwork manifests passes with DOTWORK_NONE. Nothing is saved.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os
import sys

import unreal

from kit_dotwork import dotwork_paper as paper
from kit_dotwork import dotwork_spec as spec

ASSETSPEC_DIR = "tools/art/dotwork"         # the kit's standard-library validator (shipped with Dotwork)


def validator(root):
    """assetspec.check, or None when the game does not ship Dotwork's tools."""
    folder = os.path.join(root, ASSETSPEC_DIR)
    if not os.path.isfile(os.path.join(folder, "assetspec.py")):
        return None
    if folder not in sys.path:
        sys.path.insert(0, folder)
    import assetspec
    return assetspec


def main():
    root = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
    found = spec.find_manifests(root)
    if not found:
        unreal.log(f"DOTWORK_NONE no Dotwork manifests in {', '.join(spec.MANIFEST_DIRS)}: nothing to check")
        return
    check = validator(root)
    problems = []
    for path in found:
        name = os.path.relpath(path, root)
        try:
            doc = spec.load(path)
            if check:
                problems += [f"{name}: {e}" for e in check.check(doc, spec.base_dir(path, doc))]
            imp = paper.Importer(path, transient=True).run()
            problems += [f"{name}: {e}" for e in paper.texture_settings_problems(imp)]
            unreal.log(f"DOTWORK_LOADED {name} {len(imp.records)} asset(s)")
        except (spec.ManifestError, paper.ImportFailed, RuntimeError) as exc:
            problems.append(f"{name}: {exc}")
    for line in problems:
        unreal.log_error(f"DOTWORK_BROKEN {line}")
    if problems:
        raise AssertionError(f"{len(problems)} problem(s) in the game's Dotwork manifests (DOTWORK_BROKEN lines)")
    unreal.log(f"DOTWORK_MANIFESTS_OK {len(found)} manifest(s)" + ("" if check else " (assetspec.py not found: "
                                                                    "files checked by the import only)"))


main()
