# ---------------------------------------------------------------------------
# test_guard_voice.gd
# Purpose : GUT tests for the optional live voice: when it turns on, the cache key, the request body, and
#           that without a key it stays off and speak() does nothing (no network in tests).
# Usage   : python tools/dev.py test      (needs the GUT addon in addons/gut/)
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest


func test_needs_a_key_and_a_window_unless_forced() -> void:
	assert_false(GuardVoice.should_enable("", false, false, false), "no key: off")
	assert_true(GuardVoice.should_enable("k", false, false, false), "key and a window: on")
	assert_false(GuardVoice.should_enable("k", true, false, false), "headless smoke runs spend nothing")
	assert_true(GuardVoice.should_enable("k", true, true, false), "--voice forces it in headless runs")
	assert_false(GuardVoice.should_enable("k", false, true, true), "--no-voice wins")


func test_cache_path_depends_on_model_voice_and_text() -> void:
	var a := GuardVoice.cache_path("m", "v", "Halt.")
	assert_eq(a, GuardVoice.cache_path("m", "v", "Halt."), "same line, same file: repeats cost nothing")
	assert_ne(a, GuardVoice.cache_path("m", "v", "Halt!"))
	assert_ne(a, GuardVoice.cache_path("m", "other", "Halt."))
	assert_ne(a, GuardVoice.cache_path("m2", "v", "Halt."))
	assert_true(a.begins_with(GuardVoice.CACHE_DIR) and a.ends_with(".mp3"))


func test_request_body_has_text_and_voice_only() -> void:
	var body: Dictionary = JSON.parse_string(GuardVoice.request_body("Halt, \"traveler\".", "voice123"))
	assert_eq(body.text, "Halt, \"traveler\".", "quotes survive the JSON")
	assert_eq(body.reference_id, "voice123")
	assert_eq(body.format, "mp3")
	assert_false(body.has("key") or body.has("Authorization"), "the key goes in a header, never the body")


func test_without_a_key_speak_does_nothing() -> void:
	if OS.get_environment(GuardVoice.KEY_ENV) != "":
		pass_test("a key is set on this machine; the off path is covered by should_enable")
		return
	var v := GuardVoice.new()
	add_child_autofree(v)
	assert_false(v.enabled)
	v.speak("Halt.")
	assert_false(v._busy, "nothing queued, nothing sent")
