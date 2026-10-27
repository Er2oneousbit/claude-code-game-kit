# ---------------------------------------------------------------------------
# jump_buffer.gd
# Purpose : Remembers a jump press for a short time, so pressing jump just
#           before landing still jumps. Engine-free, unit tested.
# Usage   : var b := JumpBuffer.new(0.12)
#           on jump pressed: b.press()
#           each physics tick: b.update(delta); if b.is_pending() and can_jump: jump; b.clear()
# Notes   : Pairs with CoyoteTimer (late jumps); this one forgives early jumps.
#
# Pseudocode:
#   press()      -> time_left = window
#   update(dt)   -> time_left = max(0, time_left - dt)
#   is_pending() -> time_left > 0
#   clear()      -> time_left = 0 (the press was used)
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name JumpBuffer
extends RefCounted

var window: float
var time_left: float = 0.0


func _init(window_seconds: float = 0.12) -> void:
	window = maxf(window_seconds, 0.0)


func press() -> void:
	time_left = window


func update(delta: float) -> void:
	time_left = maxf(time_left - delta, 0.0)


func is_pending() -> bool:
	return time_left > 0.0


func clear() -> void:
	time_left = 0.0
