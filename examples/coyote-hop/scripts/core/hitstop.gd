# ---------------------------------------------------------------------------
# hitstop.gd
# Purpose : Hitstop (engine-free): freeze game time for a moment on impact so a hit feels heavy.
# Usage   : var hitstop := Hitstop.new(0.25)                 # longest freeze allowed, seconds
#           on a hit:    hitstop.hit(0.08)
#           each tick:   var dt := hitstop.scaled_dt(delta)  # 0 while frozen; move the game with dt
# Notes   : Overlapping hits keep the longest remaining freeze, capped at max_s. Feed it REAL time (the frame
#           delta before game speed); the game time it returns, times game_speed, drives everything else (shake,
#           follow camera, springs, input buffer, coyote time). Tested against data/golden/juice.json.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name Hitstop
extends RefCounted

var max_s: float # cap for one freeze
var remaining: float = 0.0 # seconds of freeze left


func _init(p_max_s: float = 0.25) -> void:
	max_s = p_max_s


func hit(duration: float) -> void:
	remaining = minf(maxf(remaining, duration), max_s)


func scaled_dt(real_dt: float) -> float:
	# The game's delta for this frame: the frozen part of real_dt is removed
	if remaining <= 0.0:
		return real_dt
	var used: float = minf(remaining, real_dt)
	remaining -= used
	return real_dt - used
