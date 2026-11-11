# ---------------------------------------------------------------------------
# test_kit_character.gd
# Purpose : KitCharacter against the golden rigged character (data/golden/character/character.glb: Mixamo bone
#           names, looping idle and walk clips, #290): the imported scene and a run-time glTF load both find the
#           clips at their lengths, play walk on a loop, and turn the moving bone as far as the clip swings it.
#           Also pins what Godot does to the names (':' -> '_').
# Usage   : python tools/dev.py test --filter test_kit_character.gd
# Notes   : Numbers come from data/golden/character/expected.json (written by tools/blender/golden_character.py),
#           never from this file. AnimationPlayer.advance() applies the tracks at once, so no frames need to pass.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

const DIR := "res://data/golden/character/"
const STEPS := 30            # frames of walk to play
const STEP_S := 1.0 / 30.0
const MIN_SHARE := 0.8       # the bone must turn at least this share of the clip's swing (frames sample it)

var expected: Dictionary


func before_all() -> void:
	expected = JSON.parse_string(FileAccess.get_file_as_string(DIR + "expected.json"))


func _loaded(runtime: bool) -> Node3D:
	var path := DIR + str(expected.file)
	var c := KitCharacter.load_gltf(ProjectSettings.globalize_path(path)) if runtime else KitCharacter.load_scene(path)
	assert_not_null(c, "the character loads (%s)" % ("run time" if runtime else "imported"))
	if c != null:
		add_child_autofree(c)
	return c


## The largest angle (degrees) between two poses of the moving bone while walk plays STEPS frames (the clip's
## swing, as expected.json measures it: forward to back).
func _walk_swing(c: Node3D) -> float:
	var ap := KitCharacter.play(c, "walk", true, 0.0)
	assert_not_null(ap, "walk plays")
	if ap == null:
		return 0.0
	var skel := KitCharacter.skeleton(c)
	var bone := skel.find_bone(KitCharacter.bone_name(str(expected.moving_bone)))
	assert_gt(bone, -1, "the moving bone is in the skeleton")
	ap.advance(0.0)
	var poses: Array[Quaternion] = [skel.get_bone_pose_rotation(bone)]
	for i in STEPS:
		ap.advance(STEP_S)
		poses.append(skel.get_bone_pose_rotation(bone))
	var most := 0.0
	for a in poses:
		for b in poses:
			most = maxf(most, rad_to_deg(a.angle_to(b)))
	return most


func _check(c: Node3D) -> void:
	if c == null:
		return
	var clips := KitCharacter.clips(c)
	var ap := KitCharacter.player(c)
	for clip: String in expected.clips:
		assert_true(clip in clips, "clip %s is there (the file has %s)" % [clip, clips])
		if ap != null and ap.has_animation(clip):
			assert_almost_eq(ap.get_animation(clip).length, float(expected.clips[clip].seconds), 0.01, clip + " length")
	var swing := _walk_swing(c)
	assert_gt(swing, MIN_SHARE * float(expected.moving_bone_swing_deg),
		"walk turns %s by %.1f degrees" % [expected.moving_bone, swing])
	assert_eq(ap.get_animation("walk").loop_mode, Animation.LOOP_LINEAR, "play() loops by default")
	ap.advance(float(expected.clips.walk.seconds) * 1.5)
	assert_true(ap.is_playing(), "a looping clip is still playing after its length")


func test_imported_scene_plays_walk() -> void:
	_check(_loaded(false))


func test_runtime_gltf_plays_walk() -> void:
	_check(_loaded(true))


func test_bone_names_lose_the_colon() -> void:
	var c := _loaded(false)
	if c == null:
		return
	var skel := KitCharacter.skeleton(c)
	assert_eq(skel.get_bone_count(), (expected.bones as Array).size(), "every joint is a bone")
	assert_gt(skel.find_bone("mixamorig_Hips"), -1, "Godot stores mixamorig:Hips as mixamorig_Hips")
	assert_eq(skel.find_bone("mixamorig:Hips"), -1, "no bone keeps the colon")


func test_play_refuses_an_unknown_clip() -> void:
	var c := _loaded(false)
	if c == null:
		return
	assert_null(KitCharacter.play(c, "no_such_clip"))
	assert_push_error("no clip")

# {{FOOTER}}
