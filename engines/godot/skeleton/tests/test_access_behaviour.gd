# ---------------------------------------------------------------------------
# test_access_behaviour.gd
# Purpose : The motor and cognitive settings do what they say (#166, #167): auto_repeat repeats a held press on its
#           schedule, timing_scale lengthens the demo's input buffer and coyote time, subtitle_hold keeps a finished
#           line on screen until accept.
# Usage   : python tools/dev.py test --filter test_access_behaviour.gd
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

var _saved: Dictionary


func before_each() -> void:
	_saved = (Shell.settings["access"] as Dictionary).duplicate(true)


func after_each() -> void:
	Shell.settings["access"] = _saved


func test_a_held_press_repeats_after_the_delay_then_on_the_interval() -> void:
	var rep: AutoRepeat = AutoRepeat.new()
	var fired: Array = []
	var t: float = 0.0
	for i: int in 70: # 0.7 s held at 100 frames a second
		t += 0.01
		if rep.update(0.01, true):
			fired.append(snappedf(t, 0.01))
	assert_eq(fired.size(), 3, "0.35 s, then every 0.15 s: %s" % [fired])
	assert_almost_eq(float(fired[0]), AutoRepeat.DELAY_S, 0.011)
	assert_almost_eq(float(fired[1]) - float(fired[0]), AutoRepeat.INTERVAL_S, 0.011)
	assert_false(rep.update(0.01, false), "releasing stops it")
	assert_false(rep.update(0.2, true), "and the delay starts again")


func test_timing_scale_lengthens_the_demos_windows() -> void:
	Shell.settings["access"]["timing_scale"] = 2.5
	var demo: JuiceDemo = autofree(JuiceDemo.new()) # not in the tree: the shell registers the demo's actions
	demo._apply_timing()
	assert_almost_eq(demo.buffer.window, JuiceDemo.BUFFER_S * 2.5, 1e-6)
	assert_almost_eq(demo.coyote.window, JuiceDemo.COYOTE_S * 2.5, 1e-6)


func test_a_held_subtitle_waits_for_accept() -> void:
	var bar: SubtitleBar = SubtitleBar.new()
	add_child_autofree(bar)
	await get_tree().process_frame
	assert_true(bar.play("guide.intro"), "the sample line plays")
	Shell.settings["access"]["subtitle_hold"] = true
	bar._process(30.0) # far past the line's end
	assert_true(bar.shown()["visible"] and bar.is_playing(), "still on screen with subtitle_hold")
	assert_eq(str(bar.shown()["text"]).replace("
", " "), # the bar breaks it into two rows
			Shell.content("Hit the box. Feel the shake, the freeze and the squash."), "on its last words")
	Shell.settings["access"]["subtitle_hold"] = false
	bar._process(5.0)
	assert_false(bar.is_playing(), "gone once the setting is off")

# {{FOOTER}}
