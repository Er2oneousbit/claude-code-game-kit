# ---------------------------------------------------------------------------
# flash_limiter.gd
# Purpose : Photosensitivity guard (engine-free): at most max_flashes full-screen flashes in any window_s.
# Usage   : var limiter := FlashLimiter.new()                # 3 per second
#           if limiter.request(real_clock): flash()               # ALWAYS ask, whatever the settings say
# Notes   : The default (three per second) follows the common photosensitivity guidance for games; a refused
#           flash is simply skipped. No setting turns the limiter off: the access.flash_limit setting only tones
#           the flash down on top of it (see scripts/game/juice_demo.gd). now is REAL time in seconds (wall
#           clock, before hitstop and game speed), so slow motion cannot squeeze more flashes into a real second.
#           Tested against data/golden/juice.json.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name FlashLimiter
extends RefCounted

var max_flashes: int
var window: float
var times: Array[float] = [] # recent flash times inside the window


func _init(p_max_flashes: int = 3, window_s: float = 1.0) -> void:
	max_flashes = p_max_flashes
	window = window_s


func request(now: float) -> bool:
	var kept: Array[float] = []
	for t: float in times:
		if t > now - window:
			kept.append(t)
	times = kept
	if times.size() < max_flashes:
		times.append(now)
		return true
	return false
