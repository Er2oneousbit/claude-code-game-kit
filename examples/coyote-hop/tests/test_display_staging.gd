# ---------------------------------------------------------------------------
# test_display_staging.gd
# Purpose : The parts of DisplayStaging the golden cases do not reach: the real-time clock the settings screen feeds
#           it (tick_real), and value equality across JSON floats and control ints.
# Usage   : python tools/dev.py test --filter test_display_staging.gd
# Notes   : The rules themselves are held by tests/test_golden_shell.gd (data/golden/shell.json, display_staging).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest


func _confirming() -> DisplayStaging:
	var st: DisplayStaging = DisplayStaging.new(GameSettings.defaults()["display"])
	st.stage("mode", "fullscreen")
	st.apply()
	return st


func test_the_countdown_runs_on_the_clock_given() -> void:
	var st: DisplayStaging = _confirming()
	assert_eq(st.tick_real(5_000_000), [], "the first tick only starts the clock")
	assert_eq(st.seconds(), 15)
	assert_eq(st.tick_real(14_000_000), [])
	assert_eq(st.seconds(), 6, "9 s of clock time went by")
	assert_eq(st.tick_real(20_000_000), [["mode", "windowed"]], "15 s after the start: reverted")
	assert_false(st.confirming())


func test_the_countdown_ignores_engine_time_scale() -> void:
	# A hitstop or a slow game speed scales delta, never the clock: the confirm still ends on time
	var scale: float = Engine.time_scale
	Engine.time_scale = 0.0
	var st: DisplayStaging = _confirming()
	st.tick_real(0)
	var calls: Array = st.tick_real(15_000_000)
	Engine.time_scale = scale
	assert_eq(calls, [["mode", "windowed"]])


func test_a_new_confirm_restarts_the_clock() -> void:
	var st: DisplayStaging = _confirming()
	st.tick_real(1_000_000)
	st.keep()
	st.stage("resolution", [1280, 720])
	st.apply()
	assert_eq(st.tick_real(100_000_000), [], "the clock of the old confirm is not reused")
	assert_eq(st.seconds(), 15)


func test_values_compare_by_value() -> void:
	assert_true(DisplayStaging.same(60, 60.0), "a control int and a JSON float")
	assert_true(DisplayStaging.same([1920, 1080], [1920.0, 1080.0]))
	assert_false(DisplayStaging.same([1920, 1080], [1280, 720]))
	assert_false(DisplayStaging.same("windowed", 0), "different kinds never match (and never raise)")
	var st: DisplayStaging = DisplayStaging.new({"mode": "windowed", "vsync": true, "frame_cap": 0.0,
			"resolution": [1920.0, 1080.0], "ui_scale": 1.0})
	st.stage("frame_cap", 0)
	st.stage("resolution", [1920, 1080])
	assert_false(st.has_pending(), "staging the applied value (as an int) drops it")
