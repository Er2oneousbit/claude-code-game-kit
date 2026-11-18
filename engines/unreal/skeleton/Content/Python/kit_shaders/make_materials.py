# ---------------------------------------------------------------------------
# make_materials.py
# Purpose : Builds every kit shader recipe as a material asset in /Game/KitShaders (M_Kit_<name>) and saves them,
#           for the game to use: a material instance per sprite or surface sets MainTex (and AuxTex) and the
#           u_<name> parameters.
# Usage   : python tools/dev.py exec Content/Python/kit_shaders/make_materials.py
# Notes   : Run it again after `python tools/shaders/shader_gen.py` changed a recipe: it rebuilds the assets.
#           The pythonscript commandlet is enough here (building and saving needs no renderer); the GPU check is
#           `python tools/dev.py smoke --shaders`.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-17 with Claude (Sonnet 5.5, claude-sonnet-5-5): the post recipes also as Post Process materials
#           (M_KitPost_<name>, scene colour in place of MainTex, #260)
# ---------------------------------------------------------------------------
import unreal

from kit_shaders import kit_materials
from kit_shaders.kit_recipes import RECIPES

DEST = "/Game/KitShaders"

for name in RECIPES:
    material = kit_materials.build(name, DEST)
    if not unreal.EditorAssetLibrary.save_loaded_asset(material, False):
        raise RuntimeError(f"could not save {DEST}/M_Kit_{name}")
    unreal.log(f"made {DEST}/M_Kit_{name}")
    if RECIPES[name]["group"] == "post":        # the same effect as a Post Process material (a volume's blendable)
        material = kit_materials.build_post(name, DEST)
        if not unreal.EditorAssetLibrary.save_loaded_asset(material, False):
            raise RuntimeError(f"could not save {DEST}/M_KitPost_{name}")
        unreal.log(f"made {DEST}/M_KitPost_{name}")
