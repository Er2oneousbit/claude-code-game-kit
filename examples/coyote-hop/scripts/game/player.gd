# ---------------------------------------------------------------------------
# player.gd
# Purpose : The hopper (the Sunny Land fox, A-0006). Runs, jumps with coyote time, a jump
#           buffer and a variable jump height (release early for a short hop).
# Usage   : var p := Player.new(); add_child(p); p.respawn(spawn)
#           Reads input actions move_left, move_right, jump (set up by main.gd).
#           Signals: jumped, landed (main.gd plays the sounds).
#           controls_enabled = false ignores move and jump input (main.gd sets it at the flag).
# Notes   : Builds its own collision shape and sprite so the scene file stays
#           trivial. All numbers come from Tuning.
#
# Pseudocode (each physics tick):
#   horizontal: move velocity.x toward input * RUN_SPEED (ground or air accel)
#   vertical:   apply gravity, clamp fall speed
#   jump press -> buffer; if buffer pending and coyote allows -> jump, consume both
#   jump not held while rising -> cut upward speed once per jump (short hop); a buffered
#     tap that was released before touch-down is cut on the take-off tick
#   move_and_slide, feed is_on_floor() to the coyote timer, emit landed on touch-down
#   sprite: face the move direction, walk frames only while running on the ground
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): buffered taps and repeated
#           releases cut the jump once; controls_enabled; respawn snaps the camera and faces right
# ---------------------------------------------------------------------------
class_name Player
extends CharacterBody2D

signal jumped
signal landed

const SPRITE_DIR: String = "res://assets/art/sunny_land_fox/"   # the fox (A-0006), faces right
const SPRITE_ANIMS: Dictionary = {"idle": [4, 8.0], "run": [6, 12.0], "jump": [2, 0.0]}   # frames, fps
const SPRITE_FRAME_H: float = 32.0         # every fox frame is 33x32 with the feet on the bottom row

var coyote: CoyoteTimer = CoyoteTimer.new(Tuning.COYOTE_TIME)
var buffer: JumpBuffer = JumpBuffer.new(Tuning.JUMP_BUFFER_TIME)
var sprite: AnimatedSprite2D
var controls_enabled: bool = true
var _was_on_floor: bool = true
var _cut_available: bool = false   # true from take-off until the one jump cut is spent


func _ready() -> void:
	var shape := CollisionShape2D.new()
	var rect := RectangleShape2D.new()
	rect.size = Tuning.PLAYER_SIZE
	shape.shape = rect
	add_child(shape)
	sprite = AnimatedSprite2D.new()
	sprite.sprite_frames = Sprites.animations(SPRITE_DIR, SPRITE_ANIMS)
	# feet on the bottom edge of the collision box
	sprite.offset = Vector2(0, Tuning.PLAYER_SIZE.y / 2.0 - SPRITE_FRAME_H / 2.0)
	sprite.play("idle")
	add_child(sprite)


func _physics_process(delta: float) -> void:
	var input_x: float = Input.get_axis("move_left", "move_right") if controls_enabled else 0.0
	var jump_held: bool = controls_enabled and Input.is_action_pressed("jump")
	var accel: float = Tuning.ACCEL if is_on_floor() else Tuning.AIR_ACCEL
	velocity.x = move_toward(velocity.x, input_x * Tuning.RUN_SPEED, accel * delta)
	velocity.y = minf(velocity.y + Tuning.GRAVITY * delta, Tuning.MAX_FALL_SPEED)

	buffer.update(delta)
	if controls_enabled and Input.is_action_just_pressed("jump"):
		buffer.press()
	if buffer.is_pending() and coyote.can_jump():
		velocity.y = -Tuning.JUMP_VELOCITY
		coyote.consume()
		buffer.clear()
		_cut_available = true
		jumped.emit()
	# "Not held" instead of "just released": a buffered tap was released before touch-down, so
	# no release event comes after take-off. One cut per jump, so mashing cannot shrink a hop.
	if _cut_available and velocity.y < 0.0 and not jump_held:
		velocity.y *= Tuning.JUMP_CUT
		_cut_available = false

	move_and_slide()
	var on_floor: bool = is_on_floor()
	coyote.update(delta, on_floor)
	if on_floor and not _was_on_floor:
		landed.emit()
	_was_on_floor = on_floor
	_animate(input_x, on_floor)


func _animate(input_x: float, on_floor: bool) -> void:
	if input_x != 0.0:
		sprite.flip_h = input_x < 0.0   # the fox faces right
	if not on_floor:
		sprite.animation = "jump"       # frame 0 rising, 1 falling
		sprite.stop()
		sprite.frame = 0 if velocity.y < 0.0 else 1
	elif absf(velocity.x) > 5.0:
		sprite.play("run")
	else:
		sprite.play("idle")


func respawn(at: Vector2) -> void:
	global_position = at
	velocity = Vector2.ZERO
	buffer.clear()
	_cut_available = false
	_was_on_floor = true
	if sprite:
		sprite.flip_h = false   # the spawn faces right, into the level
	# A smoothed camera would otherwise pan all the way back from where the player was.
	for child: Node in get_children():
		if child is Camera2D:
			(child as Camera2D).reset_smoothing()
