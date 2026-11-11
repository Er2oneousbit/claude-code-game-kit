# ---------------------------------------------------------------------------
# frame_times.gd
# Purpose : Frame-time sampling for `dev.py smoke` (#90): the time between frames while a smoke run plays, printed as
#           one line when the run ends, which dev.py reports and checks against --frame-budget:
#             FRAME_TIMES frames=N mean=MS p95=MS p99=MS worst=MS mode=logic|render
# Usage   : the Shell adds one in a smoke run (add_child(SmokeFrameTimes.new())); nothing to call.
#           SmokeFrameTimes.summary(times) and .line(times, mode) are plain functions (tests/test_frame_times.gd).
# Notes   : Wall-clock time between _process calls, so it holds everything a frame costs. dev.py's smoke runs
#           Godot --headless, which draws nothing: the mode is "logic" there (a logic budget, not a render budget),
#           "render" in a windowed run. Percentiles are nearest-rank, the same rule as every engine's FRAME_TIMES line.
#           The line is printed when the node leaves the tree, which --quit-after does at the end of the run.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name SmokeFrameTimes
extends Node

var _last_us: int = 0
var _times: PackedFloat64Array = []


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS # a paused game still has frames to time


func _process(_delta: float) -> void:
	var now: int = Time.get_ticks_usec()
	if _last_us != 0:
		_times.append((now - _last_us) / 1000.0)
	_last_us = now


func _exit_tree() -> void:
	var text: String = line(_times, "logic" if DisplayServer.get_name() == "headless" else "render")
	if text != "":
		print(text)


## {frames, mean, p95, p99, worst} in ms for these frame times (frames 0 and the rest 0.0 when there are none).
static func summary(times: PackedFloat64Array) -> Dictionary:
	var out: Dictionary = {"frames": times.size(), "mean": 0.0, "p95": 0.0, "p99": 0.0, "worst": 0.0}
	if times.is_empty():
		return out
	var sorted: PackedFloat64Array = times.duplicate()
	sorted.sort()
	var total: float = 0.0
	for t: float in sorted:
		total += t
	out["mean"] = total / sorted.size()
	out["p95"] = _rank(sorted, 0.95)
	out["p99"] = _rank(sorted, 0.99)
	out["worst"] = sorted[sorted.size() - 1]
	return out


## The FRAME_TIMES line for these times ("" when there are none).
static func line(times: PackedFloat64Array, mode: String) -> String:
	if times.is_empty():
		return ""
	var s: Dictionary = summary(times)
	return "FRAME_TIMES frames=%d mean=%.2f p95=%.2f p99=%.2f worst=%.2f mode=%s" % [
			s["frames"], s["mean"], s["p95"], s["p99"], s["worst"], mode]


# Nearest rank: the smallest value with at least q of the samples at or below it.
static func _rank(sorted: PackedFloat64Array, q: float) -> float:
	var i: int = maxi(0, ceili(q * sorted.size()) - 1)
	return sorted[mini(i, sorted.size() - 1)]
