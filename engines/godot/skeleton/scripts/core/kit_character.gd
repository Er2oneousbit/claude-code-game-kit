# ---------------------------------------------------------------------------
# kit_character.gd
# Purpose : Load a rigged glTF character (a Bozzetto `rig make` result, or any .glb with a skin and clips) and play a
#           named clip on a loop. The one thing every 3D game does with such a file, in a few static calls.
# Usage   : var hero := KitCharacter.load_scene("res://assets/models/hero_rigged.glb")
#           add_child(hero)
#           KitCharacter.play(hero, "walk")                 # loops; play(hero, "wave", false) plays once
#           KitCharacter.clips(hero)                        # ["idle", "walk", ...]
#           var skel := KitCharacter.skeleton(hero)
#           skel.find_bone(KitCharacter.bone_name("mixamorig:LeftUpLeg"))   # Godot's name: mixamorig_LeftUpLeg
#           KitCharacter.use_vertex_colours(hero)           # a `--material vertex` model renders white without it
# Notes   : load_scene() takes the imported scene (a .glb under res:// the editor or `dev.py import` imported) and
#           falls back to loading the file at run time with GLTFDocument (user:// or any path on disk; a runtime
#           load has no import settings). glTF clips import without looping: play() sets the clip's loop_mode, on
#           the player's own copies of the Animations (own_animations(); instances of one imported scene share the
#           originals, so one instance's loop flag must not reach another). play() of the clip that is already
#           playing keeps it going from where it is (AnimationPlayer.play), so calling it every frame is fine;
#           player(hero).seek(0.0, true) restarts it. Root motion: none is applied
#           (AnimationPlayer has no root motion; Bozzetto's clips walk in place, the game moves the node).
#           Godot replaces ':' in bone and node names with '_' on import (mixamorig:Hips -> mixamorig_Hips).
#           Facing: glTF's front is +Z; Godot's forward is -Z, so a character faces the default camera; to walk
#           toward a point use look_at(target, Vector3.UP, true) (use_model_front: +Z is the front).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): own_animations(), so one instance's loop flag
#           never reaches another instance of the same imported scene (0.15.0 review)
# ---------------------------------------------------------------------------
class_name KitCharacter
extends RefCounted

const BLEND_S := 0.2   # seconds of crossfade when play() switches clips
const OWNED_META := "kit_character_owned_animations"   # set on a player once its animations are its own copies


## The character's scene: the imported one when Godot imported the file, else loaded at run time. null on failure.
static func load_scene(path: String) -> Node3D:
	if ResourceLoader.exists(path):
		var packed := load(path) as PackedScene
		if packed != null:
			var scene := packed.instantiate() as Node3D
			var ap := player(scene)
			if ap != null:
				own_animations(ap)   # before anything plays: the instances share the imported Animations
			return scene
	return load_gltf(path)


## Load a .glb or .gltf at run time (no import step, no import settings). null (and an error) on failure.
static func load_gltf(path: String) -> Node3D:
	var doc := GLTFDocument.new()
	var state := GLTFState.new()
	var err := doc.append_from_file(path, state)
	if err != OK:
		push_error("KitCharacter: cannot load %s (error %d)" % [path, err])
		return null
	return doc.generate_scene(state) as Node3D


## The character's AnimationPlayer (the glTF importer makes one), or null.
static func player(character: Node) -> AnimationPlayer:
	var found := character.find_children("*", "AnimationPlayer", true, false)
	return found[0] as AnimationPlayer if not found.is_empty() else null


## The character's Skeleton3D, or null.
static func skeleton(character: Node) -> Skeleton3D:
	var found := character.find_children("*", "Skeleton3D", true, false)
	return found[0] as Skeleton3D if not found.is_empty() else null


## The clip names, as the glTF file names its animations.
static func clips(character: Node) -> PackedStringArray:
	var ap := player(character)
	return ap.get_animation_list() if ap != null else PackedStringArray()


## Play `clip`, looping unless loop is false; crossfade from the current clip over blend seconds. Returns the player
## (null, with an error, when the character has no such clip).
static func play(character: Node, clip: String, loop: bool = true, blend: float = BLEND_S) -> AnimationPlayer:
	var ap := player(character)
	if ap == null or not ap.has_animation(clip):
		push_error("KitCharacter: no clip '%s' (the file has %s)" % [clip, clips(character)])
		return null
	own_animations(ap)
	ap.get_animation(clip).loop_mode = Animation.LOOP_LINEAR if loop else Animation.LOOP_NONE
	ap.play(clip, blend)
	return ap


## Give the player its own copy of every animation, once. Instances of one imported scene share their Animation
## resources, so without this play(hero_a, "wave", false) would stop hero_b's looping wave as well.
static func own_animations(ap: AnimationPlayer) -> void:
	if ap.has_meta(OWNED_META):
		return
	for lib_name in ap.get_animation_library_list():
		var lib := ap.get_animation_library(lib_name)
		var copy := AnimationLibrary.new()
		for anim_name in lib.get_animation_list():
			copy.add_animation(anim_name, lib.get_animation(anim_name).duplicate())
		ap.remove_animation_library(lib_name)
		ap.add_animation_library(lib_name, copy)
	ap.set_meta(OWNED_META, true)


## A glTF bone or node name as Godot stores it (':' and '/' become '_').
static func bone_name(gltf_name: String) -> String:
	return gltf_name.replace(":", "_").replace("/", "_")


## Turn vertex colours on (Godot 4.7 imports COLOR_0 but leaves vertex_color_use_as_albedo off: #202).
static func use_vertex_colours(root: Node) -> void:
	for mi: MeshInstance3D in root.find_children("*", "MeshInstance3D", true, false):
		for s in mi.mesh.get_surface_count():
			var mat: Material = mi.get_active_material(s)
			if mat is StandardMaterial3D:
				mat = mat.duplicate()
				mat.vertex_color_use_as_albedo = true
				mi.set_surface_override_material(s, mat)

# {{FOOTER}}
