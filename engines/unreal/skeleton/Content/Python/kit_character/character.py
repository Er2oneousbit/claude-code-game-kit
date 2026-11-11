# ---------------------------------------------------------------------------
# character.py
# Purpose : Imports a rigged glTF character with its clips through Unreal's own glTF importer (Interchange) and
#           hands back the SkeletalMesh, the Skeleton and one AnimSequence per glTF clip, set up to play in place:
#           root motion off, the asset's Loop flag on. The kit's one primitive for 3D characters in Unreal (#290).
# Usage   : in an editor script run with `python tools/dev.py exec <script.py>`:
#             from kit_character import import_character
#             ch = import_character("SourceArt/Models/hero.glb", "/Game/Characters/Hero")
#             ch.mesh, ch.skeleton, ch.sequences["walk"], ch.bone("mixamorig:Hips")  # -> "mixamorig_Hips"
# Notes   : Measured on UE 5.8.4 with data/golden/character (2026-11-11): glTF metres arrive as centimetres (a 1.80 m
#           character is 180 cm tall, so import_offset_uniform_scale stays 1.0), +Y up becomes +Z up, the glTF front
#           (+Z) becomes +Y (the way the UE Mannequin's mesh faces: a Character turns its mesh -90 yaw), left stays
#           +X; the root bone is the first joint (mixamorig_Hips), the armature node is not a bone; ':' in bone names
#           becomes '_'; a clip `walk` becomes the AnimSequence `<stem>walk`. glTF has no frame rate: Interchange
#           samples clips at 30 fps unless sample_rate is given. Root motion is off and Force Root Lock is left off on
#           purpose: with Hips as the root bone, the lock would pin the hips to the rest pose and kill their bob.
#           A fresh Interchange generic pipeline is used (the project's import settings do not apply), plus the
#           engine's glTF material pipeline, so the result does not depend on editor preferences.
#           Run it again after the .glb changes: Interchange then reimports only the SkeletalMesh, so the clips
#           already in dest are reimported one by one (InterchangeManager.reimport_asset); their Loop flag survives.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os
from pathlib import Path

import unreal

from kit_character import character_spec as spec

GLTF_MATERIAL_PIPELINE = "/Interchange/Pipelines/DefaultGLTFPipeline"   # glTF materials as instances of its masters
DEFAULT_DEST = "/Game/Characters"           # dest when none is given: /Game/Characters/<file stem>
TEMP_ROOT = "/Temp/"                        # a destination here is never saved (tests import here)


class Character:
    """What import_character made: the mesh, its Skeleton, physics asset and materials, the clips by glTF name
    (filled by import_character) and the Skeleton's bone names (bones[0] is the root)."""

    def __init__(self, glb, dest, made):
        meshes = [a for a in made if isinstance(a, unreal.SkeletalMesh)]
        if len(meshes) != 1:
            names = ", ".join(a.get_path_name() for a in made)
            raise RuntimeError(f"{glb}: expected one SkeletalMesh, the import made {len(meshes)} ({names})")
        self.glb = glb
        self.dest = dest
        self.mesh = meshes[0]
        self.skeleton = self.mesh.skeleton
        self.physics_asset = self.mesh.physics_asset
        self.materials = [m.material_interface for m in self.mesh.materials if m.material_interface]
        self.sequences = {}                  # glTF clip name -> AnimSequence
        ref = unreal.AnimPoseExtensions.get_reference_pose(self.skeleton)
        self.bones = [str(n) for n in unreal.AnimPoseExtensions.get_bone_names(ref)]

    @property
    def assets(self):
        """Every asset of the character (what save_loaded_assets gets)."""
        return [a for a in [self.mesh, self.skeleton, self.physics_asset, *self.materials,
                            *self.sequences.values()] if a]

    def bone(self, gltf_name):
        """The Skeleton's name for a glTF joint (mixamorig:Hips -> mixamorig_Hips). KeyError when it has none."""
        for name in (gltf_name, spec.ue_bone_name(gltf_name)):
            if name in self.bones:
                return name
        raise KeyError(f"no bone for {gltf_name!r} in {self.skeleton.get_path_name()} (bones: {', '.join(self.bones)})")


def project_path(path):
    """A path relative to the project folder (data/golden/..., SourceArt/...) made absolute."""
    if os.path.isabs(path):
        return os.path.normpath(path)
    root = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
    return os.path.normpath(os.path.join(root, path))


def make_pipeline(sample_rate=None):
    """A fresh Interchange generic pipeline: skeletal mesh, skeleton and animations, default scale."""
    pipe = unreal.InterchangeGenericAssetsPipeline()
    if sample_rate:
        anim = pipe.get_editor_property("animation_pipeline")
        anim.set_editor_property("use30_hz_to_bake_bone_animation", False)
        anim.set_editor_property("custom_bone_animation_sample_rate", int(sample_rate))
    return pipe


def import_params(sample_rate, materials):
    """(pipeline, ImportAssetParameters) for one import: automated (no dialogs), replacing what is there. The
    pipeline is returned too so it stays alive while the import runs."""
    pipe = make_pipeline(sample_rate)
    params = unreal.ImportAssetParameters()
    params.is_automated = True
    params.replace_existing = True
    # override_pipelines takes paths; a transient pipeline's path works (UE 5.8), the object itself does not
    params.override_pipelines.append(unreal.SoftObjectPath(pipe.get_path_name()))
    if materials and unreal.load_asset(GLTF_MATERIAL_PIPELINE):
        params.override_pipelines.append(unreal.SoftObjectPath(GLTF_MATERIAL_PIPELINE))
    return pipe, params


def assets_in(folder):
    """Every asset already in a content folder (none when it does not exist)."""
    if not unreal.EditorAssetLibrary.does_directory_exist(folder):
        return []
    paths = unreal.EditorAssetLibrary.list_assets(folder, recursive=True, include_folder=False)
    return [a for a in (unreal.load_asset(p) for p in paths) if a]


def asset_path(entry):
    """An import result entry ("/Script/Engine.SkeletalMesh'/Game/X/hero.hero'" or a bare path) -> the path."""
    text = str(entry)
    return text.split("'")[1] if text.count("'") >= 2 else text


def set_play_in_place(seq, loop):
    """Root motion off, Force Root Lock off (Hips is the root: see the header), the asset's Loop flag."""
    seq.set_editor_property("enable_root_motion", False)
    seq.set_editor_property("force_root_lock", False)
    seq.set_editor_property("loop", bool(loop))


def import_character(glb, dest=None, sample_rate=None, loop=True, save=None, materials=True):
    """Import a rigged .glb (or .gltf) into dest and return a Character.

    glb          the file, absolute or relative to the project folder; keep it outside Content/
    dest         the content folder (default /Game/Characters/<stem>); assets there are replaced in place
    sample_rate  frames per second to sample the clips at (glTF stores none; Interchange uses 30 without it)
    loop         the Loop flag on every clip's AnimSequence
    save         save the assets (default: yes, unless dest is under /Temp/)
    materials    add the engine's glTF material pipeline (material instances of the glTF masters)"""
    glb = project_path(glb)
    if not os.path.isfile(glb):
        raise FileNotFoundError(f"no glTF file at {glb}")
    stem = Path(glb).stem
    dest = (dest or f"{DEFAULT_DEST}/{spec.ue_object_name(stem)}").rstrip("/")
    clips = spec.clip_names(spec.read_gltf_json(glb))

    mgr = unreal.InterchangeManager.get_interchange_manager_scripted()
    pipe, params = import_params(sample_rate, materials)
    result = mgr.import_asset(dest, unreal.InterchangeManager.create_source_data(glb), params)
    made = [a for a in (unreal.load_asset(asset_path(e)) for e in (result or [])) if a]
    if not made:
        raise RuntimeError(f"importing {glb} into {dest} made no assets: see the Interchange lines in the log")
    # A second import into the same folder only reimports the SkeletalMesh (UE 5.8): the Skeleton, materials and
    # clips already there are kept, so take them from the folder and reimport each clip from the file
    ch = Character(glb, dest, made)
    seqs = {a.get_name(): a for a in made + [a for a in assets_in(dest) if a not in made]
            if isinstance(a, unreal.AnimSequence) and a.get_skeleton() == ch.skeleton}
    for seq in seqs.values():
        if seq not in made:
            keep, again = import_params(sample_rate, materials=False)
            if not mgr.reimport_asset(seq, again):
                raise RuntimeError(f"reimporting {seq.get_path_name()} from {glb} failed: see the Interchange lines in the log")
    found = spec.match_clips(seqs, clips, stem)
    missing = [c for c in clips if c not in found]
    if missing:
        raise RuntimeError(f"{glb}: no AnimSequence for clip(s) {', '.join(missing)} (in {dest}: "
                           f"{', '.join(seqs) or 'none'}). A second import into the same folder reimports the clips "
                           "already there; a clip new to the file may not be added (verify): import into a new folder")
    for clip in clips:
        seq = seqs[found[clip]]
        set_play_in_place(seq, loop)
        ch.sequences[clip] = seq

    if save if save is not None else not (dest + "/").startswith(TEMP_ROOT):
        unreal.EditorAssetLibrary.save_loaded_assets(ch.assets, only_if_is_dirty=False)
    unreal.log(f"CHARACTER_IMPORTED {glb} -> {dest}: {ch.mesh.get_name()}, {len(ch.bones)} bones, "
               f"clips {', '.join(f'{c}={s.get_name()}' for c, s in ch.sequences.items())}")
    return ch
