# ---------------------------------------------------------------------------
# test_player_jump.gd
# Purpose : GUT scene tests for the variable jump height in player.gd: a buffered tap is a
#           short hop like a tap on the ground, and extra releases in the air cut a hop once only.
# Usage   : python tools/dev.py test      (needs the GUT addon in addons/gut/)
# Notes   : Boots the real main scene and drives the input actions one physics tick at a time.
#           `await get_tree().physics_frame` resumes at the start of a tick, before any node's
#           _physics_process. Measured on Godot 4.7.2: an Input.action_press() made there reads as
#           pressed at once but as just pressed only in the next tick, while a release is seen at
#           once. So a press-then-release-next-tick tap takes off with the key already up, like a
#           real tap shorter than one tick. Heights are px above the resting position, with the
#           shipped tuning (full jump about 67 px).
#           Regression tests for the 2026-10-26 review: a buffered tap jumped 67 px instead of
#           about 19, and a second tap in the air shrank a 18.9 px hop to 13.8 px.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

const Main := preload("res://scripts/game/main.gd")
const MAIN_SCENE: PackedScene = preload("res://scenes/main.tscn")
const SETTLE_TICKS: int = 5           # the spawn has the feet on the floor; a few ticks make is_on_floor() true
const MAX_AIR_TICKS: int = 180        # 3 s: far longer than any jump in this game
const BUFFER_PRESS_ABOVE_FLOOR: float = 18.0   # press the buffered tap within one tile of touch-down

var main: Main
var player: Player
var rest_y: float
var _jumps: int = 0
var _held_at_take_off: Array[bool] = []


func before_each() -> void:
	main = MAIN_SCENE.instantiate()
	add_child_autofree(main)
	player = main.player
	_jumps = 0
	_held_at_take_off.clear()
	player.jumped.connect(_on_jumped)
	await _ticks(SETTLE_TICKS)
	rest_y = player.global_position.y


func after_each() -> void:
	for action: String in ["move_left", "move_right", "jump", "restart"]:
		Input.action_release(action)


func _on_jumped() -> void:
	_jumps += 1
	_held_at_take_off.append(Input.is_action_pressed("jump"))


func _ticks(n: int) -> void:
	for i in range(n):
		await get_tree().physics_frame


# Ticks until the player is back on the floor after leaving it; returns the highest rise above rest_y.
func _rise_until_landed() -> float:
	var top: float = player.global_position.y
	var airborne: bool = not player.is_on_floor()
	for i in range(MAX_AIR_TICKS):
		await _ticks(1)
		top = minf(top, player.global_position.y)
		if not player.is_on_floor():
			airborne = true
		elif airborne:
			break
	return rest_y - top


# Press for exactly one tick on the floor: the shortest hop there is.
func _ground_tap() -> float:
	await _ticks(1)
	Input.action_press("jump")
	await _ticks(1)
	Input.action_release("jump")
	var rise: float = await _rise_until_landed()
	await _ticks(SETTLE_TICKS)
	return rise


func test_ground_tap_is_a_short_hop() -> void:
	var rise: float = await _ground_tap()
	assert_eq(_jumps, 1, "the tap jumped")
	assert_between(rise, 10.0, 25.0, "a one-tick tap gives a short hop (about 19 px), got %.2f" % rise)


func test_buffered_tap_released_before_landing_is_a_short_hop() -> void:
	var ground: float = await _ground_tap()
	# A full jump, released at the apex (no cut while falling)
	await _ticks(1)
	Input.action_press("jump")
	var phase: int = 0
	for i in range(MAX_AIR_TICKS):
		await _ticks(1)
		if phase == 0 and not player.is_on_floor() and player.velocity.y > 0.0:
			Input.action_release("jump")
			phase = 1
		elif phase == 1 and player.velocity.y > 0.0 and player.global_position.y > rest_y - BUFFER_PRESS_ABOVE_FLOOR:
			Input.action_press("jump")   # the tap starts a few ticks before touch-down ...
			phase = 2
		elif phase == 2:
			assert_false(player.is_on_floor(), "the tap must end before touch-down for this test to mean anything")
			Input.action_release("jump") # ... and ends one tick later, still in the air
			phase = 3
		elif phase == 3 and _jumps >= 3:
			break
	assert_eq(_jumps, 3, "ground tap, full jump, buffered jump")
	assert_false(_held_at_take_off[2], "the buffered jump took off with the key already up")
	var buffered: float = await _rise_until_landed()
	assert_lt(buffered, ground + 1.0, "buffered tap %.2f px, ground tap %.2f px" % [buffered, ground])
	assert_lt(buffered, 25.0, "a buffered tap must not be a full-height jump (was 67 px)")


func test_extra_taps_in_the_air_cut_the_hop_only_once() -> void:
	var single: float = await _ground_tap()
	# The same tap, then press and release again on the way up (no second jump is possible)
	await _ticks(1)
	Input.action_press("jump")
	await _ticks(1)
	Input.action_release("jump")
	await _ticks(2)
	assert_lt(player.velocity.y, 0.0, "still rising when the second tap comes")
	Input.action_press("jump")
	await _ticks(1)
	Input.action_release("jump")
	var double: float = await _rise_until_landed()
	assert_eq(_jumps, 2, "one jump per tap sequence, no air jump")
	assert_almost_eq(double, single, 0.01, "mashing must not shorten the hop (was 13.8 vs 18.9 px)")


func test_full_jump_held_reaches_the_jump_math_apex() -> void:
	await _ticks(1)
	Input.action_press("jump")
	var rise: float = await _rise_until_landed()
	var apex: float = JumpMath.apex_height(Tuning.JUMP_VELOCITY, Tuning.GRAVITY, 1.0 / Engine.physics_ticks_per_second)
	assert_almost_eq(rise, apex, 0.2, "held jump %.2f px vs JumpMath %.2f px" % [rise, apex])
