# ---------------------------------------------------------------------------
# test_kit_character.gd
# Purpose : KitCharacter against the golden rigged character (data/golden/character/character.glb: Mixamo bone
#           names, looping idle and walk clips, #290): the imported scene and a run-time glTF load both find the
#           clips at their lengths, play walk on a loop at 1x (the clock and the loop's period), and turn the moving
#           bone as far as the clip swings it, no more. Two instances keep their own loop flags. Also pins what
#           Godot does to the names (':' -> '_').
# Usage   : python tools/dev.py test --filter test_kit_character.gd
# Notes   : Numbers come from data/golden/character/expected.json (written by tools/blender/golden_character.py),
#           never from this file. AnimationPlayer.advance() applies the tracks at once, so no frames need to pass.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): the swing's ceiling, the loop's period and clock,
#           and two instances keeping their own loop flags (0.15.0 review)
#           2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): the same clip keeps its time, an ended one-shot
#           keeps holding, restart is explicit (#296)
#           2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): the swing is sampled over the whole walk clip, not a
#           fixed second (a longer walk was under-measured), as Bevy's test does
# ---------------------------------------------------------------------------
extends GutTest

const DIR := "res://data/golden/character/"
const STEP_S := 1.0 / 30.0   # walk plays in steps of this, over its whole length
const MIN_SHARE := 0.8       # the bone must turn at least this share of the clip's swing (frames sample it)
const MAX_SHARE := 1.1       # ... and no more: more would mean two clips applied at once, or the wrong bone
const PERIOD_TOL_DEG := 1.0  # a pose a whole clip length later is the same pose (the loop's period is the length)
const CLOCK_TOL_S := 0.002   # the player's clock advances by the time given (speed_scale 1, no custom speed)

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


## The largest angle (degrees) between two poses of the moving bone while walk plays its whole length (the clip's
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
	var steps := ceili(float(expected.clips.walk.seconds) / STEP_S) + 1
	for i in steps:
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
	assert_lt(swing, MAX_SHARE * float(expected.moving_bone_swing_deg),
		"walk turns %s by no more than the clip's swing (%.1f degrees)" % [expected.moving_bone, swing])
	assert_eq(ap.get_animation("walk").loop_mode, Animation.LOOP_LINEAR, "play() loops by default")
	ap.advance(float(expected.clips.walk.seconds) * 1.5)
	assert_true(ap.is_playing(), "a looping clip is still playing after its length")
	_check_period(c)


## The loop's period is the clip's length and the clock runs at 1x: the pose a quarter in equals the pose a quarter
## into the next loop, and advancing the player by t moves its position by t.
func _check_period(c: Node3D) -> void:
	KitCharacter.player(c).stop()   # play() of the clip already playing keeps its position (#296)
	var ap := KitCharacter.play(c, "walk", true, 0.0)
	var skel := KitCharacter.skeleton(c)
	var bone := skel.find_bone(KitCharacter.bone_name(str(expected.moving_bone)))
	var length := float(expected.clips.walk.seconds)
	ap.advance(0.0)
	ap.advance(length * 0.25)
	assert_almost_eq(ap.current_animation_position, length * 0.25, CLOCK_TOL_S, "the clock advanced a quarter clip")
	var quarter := skel.get_bone_pose_rotation(bone)
	ap.advance(length)
	assert_lt(rad_to_deg(quarter.angle_to(skel.get_bone_pose_rotation(bone))), PERIOD_TOL_DEG,
		"the pose at 1.25 lengths is the pose at 0.25 (the loop repeats every clip length)")


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


## Two instances of one imported scene share its Animation resources: one instance's loop flag must stay its own
## (0.15.0 review: play(b, "idle", false) used to stop a's looping idle as well).
func test_loop_is_per_instance() -> void:
	var a := _loaded(false)
	var b := _loaded(false)
	if a == null or b == null:
		return
	var ap_a := KitCharacter.play(a, "idle", true, 0.0)
	var ap_b := KitCharacter.play(b, "idle", false, 0.0)
	assert_eq(ap_a.get_animation("idle").loop_mode, Animation.LOOP_LINEAR, "a still loops after b played idle once")
	assert_eq(ap_b.get_animation("idle").loop_mode, Animation.LOOP_NONE, "b plays idle once")
	var length := float(expected.clips.idle.seconds)
	ap_a.advance(length * 1.5)
	ap_b.advance(length * 1.5)
	assert_true(ap_a.is_playing(), "a is still playing after its length")
	assert_false(ap_b.is_playing(), "b stopped at the end of its clip")


## #296, the kit's rule in all five engines: play() of the clip already playing changes nothing (a game may call it
## every frame), a one-shot that ended keeps holding (AnimationPlayer.play alone would start it again), and a restart
## is explicit.
func test_the_same_clip_keeps_its_time_and_restart_is_explicit() -> void:
	var c := _loaded(false)
	if c == null:
		return
	var ap := KitCharacter.play(c, "walk", true, 0.0)
	ap.advance(0.0)
	ap.advance(0.3)
	for i in 3:
		KitCharacter.play(c, "walk", true, 0.0)
	ap.advance(0.1)
	assert_almost_eq(ap.current_animation_position, 0.4, CLOCK_TOL_S, "walk kept its time when asked for again")
	KitCharacter.play(c, "walk", true, 0.0, true)
	ap.advance(0.0)
	assert_almost_eq(ap.current_animation_position, 0.0, CLOCK_TOL_S, "restart = true starts walk from 0")
	ap.advance(0.2)
	KitCharacter.play(c, "walk", false, 0.0)
	ap.advance(0.0)
	assert_almost_eq(ap.current_animation_position, 0.0, CLOCK_TOL_S, "another loop setting starts it again")
	var length := float(expected.clips.walk.seconds)
	ap.advance(length + 0.5)
	assert_false(ap.is_playing(), "the one-shot ended")
	KitCharacter.play(c, "walk", false, 0.0)
	assert_false(ap.is_playing(), "asking for the ended one-shot again keeps it holding its last frame")
	KitCharacter.play(c, "walk", false, 0.0, true)
	assert_true(ap.is_playing(), "restart = true plays the one-shot again")
