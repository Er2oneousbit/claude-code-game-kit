# ---------------------------------------------------------------------------
# auto_repeat.gd
# Purpose : "Hold to mash" (access.auto_repeat, #166): a held button repeats its press, so a player who cannot tap
#           fast (one hand, a switch, tremor) can still mash.
# Usage   : var rep := AutoRepeat.new()
#           if Input.is_action_just_pressed("attack") or (Shell.access("auto_repeat")
#                   and rep.update(dt, Input.is_action_pressed("attack"))): attack()
# Notes   : The first repeat comes after DELAY_S, then one every INTERVAL_S while held; releasing resets it. The
#           times are the kit's starting point (a tip: tune them per game), not from a source.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name AutoRepeat
extends RefCounted

const DELAY_S: float = 0.35 # held this long before the first repeat
const INTERVAL_S: float = 0.15 # then one repeat this often

var _held: float = 0.0
var _next: float = DELAY_S


## Call every frame with whether the button is held; true on a frame that repeats the press.
func update(dt: float, held: bool) -> bool:
	if not held:
		_held = 0.0
		_next = DELAY_S
		return false
	_held += dt
	if _held >= _next:
		_next += INTERVAL_S
		return true
	return false

# {{FOOTER}}
