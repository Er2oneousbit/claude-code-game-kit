# ---------------------------------------------------------------------------
# coyote_timer.gd
# Purpose : Example of ENGINE-FREE logic that is unit testable. Grants a short
#           grace window to still jump after leaving a ledge ("coyote time").
# Usage   : var t := CoyoteTimer.new(0.1)
#           each physics tick: t.update(delta, is_on_floor())
#           on jump pressed:   if t.can_jump(): ... ; t.consume()
# Notes   : No Node, no scene tree, so GUT tests run it instantly (see tests/).
#           A window of 0 means "no coyote time", not "no jumping": grounded
#           jumps always work. This file is a TEMPLATE example. Delete it if
#           the game has no jump.
#
# Pseudocode:
#   on floor      -> grounded, time_left = window; a landing re-arms a consumed jump
#   off floor     -> not grounded, time_left = max(0, time_left - delta)
#   can_jump()    -> not consumed and (grounded or time_left > 0)
#   consume()     -> consumed until the next landing (no double jump on the
#                    ground tick or inside the grace window)
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# Updated : 2026-10-20 with Claude (Opus 5.5, claude-opus-5-5): zero window no longer blocks
#           grounded jumps; consume() holds until the next landing
# ---------------------------------------------------------------------------
class_name CoyoteTimer
extends RefCounted

var window: float # seconds of grace after leaving the ground
var time_left: float = 0.0
var _grounded: bool = false
var _consumed: bool = false


func _init(window_seconds: float = 0.1) -> void:
	# Guard against negative windows from bad tuning data.
	window = maxf(window_seconds, 0.0)


func update(delta: float, on_floor: bool) -> void:
	if on_floor:
		if not _grounded:
			_consumed = false # landed: the next jump is available again
		_grounded = true
		time_left = window
	else:
		_grounded = false
		time_left = maxf(time_left - delta, 0.0)


func can_jump() -> bool:
	return not _consumed and (_grounded or time_left > 0.0)


func consume() -> void:
	_consumed = true
	time_left = 0.0
