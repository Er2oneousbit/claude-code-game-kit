# ---------------------------------------------------------------------------
# input_buffer.gd
# Purpose : Input buffer (engine-free): remembers a press for a short window, so a jump pressed just before
#           landing still happens on landing.
# Usage   : var buffer := InputBuffer.new(0.12)
#           on press:   buffer.press("jump")
#           each tick:  buffer.update(dt)
#                       if coyote.can_jump() and buffer.consume("jump"): jump()
# Notes   : consume() returns true once per press, then forgets it. Check whether the action CAN happen before
#           consuming, or the press is lost. Tested against data/golden/juice.json.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name InputBuffer
extends RefCounted

const EXPIRED_EPSILON: float = 1e-12 # a press with this little time left counts as gone (float rounding)

var window: float # seconds a press is remembered
var pending: Dictionary = {} # action -> seconds left


func _init(window_s: float = 0.12) -> void:
	window = window_s


func press(action: String) -> void:
	pending[action] = window


func update(dt: float) -> void:
	var actions: Array = pending.keys()
	actions.sort() # same order as the reference, so float rounding matches
	for action: String in actions:
		pending[action] = float(pending[action]) - dt
		if float(pending[action]) <= EXPIRED_EPSILON:
			pending.erase(action)


func consume(action: String) -> bool:
	if float(pending.get(action, 0.0)) > 0.0:
		pending.erase(action)
		return true
	return false
