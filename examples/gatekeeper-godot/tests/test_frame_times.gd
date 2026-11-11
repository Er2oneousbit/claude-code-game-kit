# ---------------------------------------------------------------------------
# test_frame_times.gd
# Purpose : GUT unit tests for SmokeFrameTimes, the FRAME_TIMES line `dev.py smoke` reads (#90).
# Usage   : python tools/dev.py test      (needs the GUT addon in addons/gut/)
# Notes   : Nearest-rank percentiles, the same rule as every engine's FRAME_TIMES line.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest


func test_summary_of_a_known_set() -> void:
	var times := PackedFloat64Array()
	for i: int in range(1, 101):
		times.append(float(i)) # 1 .. 100 ms, shuffled order must not matter
	times.reverse()
	var s: Dictionary = SmokeFrameTimes.summary(times)
	assert_eq(s["frames"], 100)
	assert_almost_eq(s["mean"], 50.5, 0.0001)
	assert_eq(s["p95"], 95.0)
	assert_eq(s["p99"], 99.0)
	assert_eq(s["worst"], 100.0)


func test_one_frame_is_every_percentile() -> void:
	var s: Dictionary = SmokeFrameTimes.summary(PackedFloat64Array([7.5]))
	assert_eq([s["p95"], s["p99"], s["worst"]], [7.5, 7.5, 7.5])


func test_the_line_dev_py_reads() -> void:
	var text: String = SmokeFrameTimes.line(PackedFloat64Array([16.0, 17.0, 40.0]), "logic")
	assert_eq(text, "FRAME_TIMES frames=3 mean=24.33 p95=40.00 p99=40.00 worst=40.00 mode=logic")


func test_no_frames_no_line() -> void:
	assert_eq(SmokeFrameTimes.line(PackedFloat64Array(), "logic"), "")
	assert_eq(SmokeFrameTimes.summary(PackedFloat64Array())["frames"], 0)
