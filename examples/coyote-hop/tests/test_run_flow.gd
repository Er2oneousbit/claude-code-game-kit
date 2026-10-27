# ---------------------------------------------------------------------------
# test_run_flow.gd
# Purpose : GUT scene tests for the run around the player in main.gd: the flag ends the run for
#           good, the clock starts on the first input, a respawn or R does not pan the camera,
#           and R resets the jingle and the fox's facing.
# Usage   : python tools/dev.py test      (needs the GUT addon in addons/gut/)
# Notes   : Boots the real main scene and drives the input actions one physics tick at a time
#           (see test_player_jump.gd for why `await get_tree().physics_frame`).
#           Regression tests for the 2026-10-26 review: after the flag the fox ran off the level
#           and fell forever, coins still counted, the clock ran from boot, the camera panned
#           back from the death point, and R left the jingle playing and the fox facing left.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

const Main := preload("res://scripts/game/main.gd")
const MAIN_SCENE: PackedScene = preload("res://scenes/main.tscn")
const SETTLE_TICKS: int = 5
const NEAR_FLAG_X: float = 1020.0    # a few px left of the flag (tile 58), on the finish platform
const FAR_X: float = 900.0           # far enough right that the camera is well away from the spawn view
const CAMERA_SNAP_PX: float = 1.0

var main: Main
var player: Player
var rest_y: float
var _jumps_after_flag: int = 0


func before_each() -> void:
	main = MAIN_SCENE.instantiate()
	add_child_autofree(main)
	player = main.player
	_jumps_after_flag = 0
	await _ticks(SETTLE_TICKS)
	rest_y = player.global_position.y


func after_each() -> void:
	for action: String in ["move_left", "move_right", "jump", "restart"]:
		Input.action_release(action)


func _on_jumped() -> void:
	_jumps_after_flag += 1


func _ticks(n: int) -> void:
	for i in range(n):
		await get_tree().physics_frame


func _camera() -> Camera2D:
	for child: Node in player.get_children():
		if child is Camera2D:
			return child
	return null


# Taps R and returns once main.gd has handled it: the press reads as just pressed one tick
# after it is made, so wait for the end of that tick.
func _press_restart() -> void:
	await _ticks(1)
	Input.action_press("restart")
	await _ticks(1)
	Input.action_release("restart")
	await _ticks(1)


func test_player_stops_at_the_flag_and_cannot_run_off() -> void:
	player.respawn(Vector2(NEAR_FLAG_X, rest_y))
	await _ticks(1)
	Input.action_press("move_right")
	for i in range(120):
		await _ticks(1)
		if main.finished:
			break
	assert_true(main.finished, "the flag was reached")
	var x_at_flag: float = player.global_position.x
	player.jumped.connect(_on_jumped)
	Input.action_press("jump")   # keep holding right and jump: the controls are locked now
	await _ticks(240)
	assert_lt(player.global_position.y, Tuning.FALL_LIMIT_Y, "the fox stays on the finish platform")
	assert_lt(player.global_position.x, x_at_flag + Tuning.TILE, "it stops near the flag, got x %.1f" % player.global_position.x)
	assert_almost_eq(player.velocity.x, 0.0, 0.01, "no movement after the flag")
	assert_eq(_jumps_after_flag, 0, "no jump after the flag")
	assert_eq(main.falls, 0, "no falls after the flag")


func test_fall_check_still_runs_after_the_flag() -> void:
	main._on_goal_body_entered(player)
	player.global_position = Vector2(NEAR_FLAG_X, Tuning.FALL_LIMIT_Y + 40.0)
	await _ticks(2)
	assert_lt(player.global_position.y, Tuning.FALL_LIMIT_Y, "a fall after the flag still respawns")


func test_coins_do_not_count_after_the_flag() -> void:
	main._on_goal_body_entered(player)
	var coin: Area2D = main.coins[0]
	main._on_coin_body_entered(player, coin)
	assert_eq(main.coins_taken, 0, "the result is final once the flag is touched")
	assert_true(coin.visible, "the coin stays")


func test_clock_waits_for_the_first_move() -> void:
	await _ticks(30)
	assert_eq(main.elapsed, 0.0, "no input yet, no time")
	Input.action_press("move_right")
	await _ticks(30)
	assert_almost_eq(main.elapsed, 30.0 / Engine.physics_ticks_per_second, 2.0 / Engine.physics_ticks_per_second,
			"the clock runs from the first move")


func test_clock_starts_on_a_jump_and_waits_again_after_restart() -> void:
	Input.action_press("move_right")
	await _ticks(10)
	Input.action_release("move_right")
	await _press_restart()
	await _ticks(20)
	assert_eq(main.elapsed, 0.0, "after R the clock waits for input again")
	Input.action_press("jump")
	await _ticks(10)
	assert_gt(main.elapsed, 0.0, "a jump starts the clock")


func test_restart_does_not_pan_the_camera() -> void:
	var cam: Camera2D = _camera()
	var home: Vector2 = cam.get_screen_center_position()
	player.respawn(Vector2(FAR_X, rest_y))
	await _ticks(SETTLE_TICKS)
	assert_gt(cam.get_screen_center_position().x, home.x + 500.0, "the camera followed the player away")
	await _press_restart()
	assert_almost_eq(cam.get_screen_center_position().x, home.x, CAMERA_SNAP_PX, "the camera is home as soon as R is handled")


func test_fall_respawn_does_not_pan_the_camera() -> void:
	var cam: Camera2D = _camera()
	var home: Vector2 = cam.get_screen_center_position()
	player.respawn(Vector2(FAR_X, rest_y))
	await _ticks(SETTLE_TICKS)
	player.global_position = Vector2(FAR_X, Tuning.FALL_LIMIT_Y + 1.0)
	await _ticks(2)
	assert_eq(main.falls, 1, "the fall was counted")
	assert_almost_eq(cam.get_screen_center_position().x, home.x, CAMERA_SNAP_PX, "the camera is home right after the respawn")


func test_restart_stops_the_jingle_and_faces_right() -> void:
	Input.action_press("move_left")
	await _ticks(5)
	Input.action_release("move_left")
	assert_true(player.sprite.flip_h, "precondition: the fox faces left")
	main._on_goal_body_entered(player)
	var jingle: AudioStreamPlayer = main.sfx_players["goal"]
	assert_true(jingle.playing, "precondition: the jingle plays")
	await _press_restart()
	assert_false(jingle.playing, "R stops the jingle")
	assert_false(player.sprite.flip_h, "R faces the fox right again")
	assert_true(player.controls_enabled, "R gives the controls back")
	assert_false(main.finished, "the run is on again")
