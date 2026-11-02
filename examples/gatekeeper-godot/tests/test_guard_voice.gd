# ---------------------------------------------------------------------------
# test_guard_voice.gd
# Purpose : GUT tests for the optional live voice: when it turns on, the cache key, the request body, that
#           without a key it stays off and speak() does nothing (no network in tests), and that a reply is
#           cached only when it plays (a 200 that is not audio leaves no file behind).
# Usage   : python tools/dev.py test      (needs the GUT addon in addons/gut/)
# Notes   : The cache tests call _on_done() as HTTPRequest would, with a stand-in reply: no key, no network.
#           They use the project's own guard-talk.mp3 as the good reply and remove what they cache.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-02 with Claude (Fable 5.1, claude-fable-5-1): the cache-after-check tests (#4)
# ---------------------------------------------------------------------------
extends GutTest

const REAL_MP3 := "res://assets/audio/guard-talk.mp3"
const TEST_VOICE := "test-voice"
const LINE := "Halt, this is a cache test."


## A voice node ready to take a reply for LINE, as _next() leaves it before the request returns.
func voice_awaiting_reply() -> GuardVoice:
	var v := GuardVoice.new()
	add_child_autofree(v)
	v._voice = TEST_VOICE
	v._current = LINE
	v._busy = true
	var path := GuardVoice.cache_path(Tuning.VOICE_MODEL, TEST_VOICE, LINE)
	if FileAccess.file_exists(path):
		DirAccess.remove_absolute(path)   # a leftover from an earlier run must not fake a result
	return v


func cache_file() -> String:
	return GuardVoice.cache_path(Tuning.VOICE_MODEL, TEST_VOICE, LINE)


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


func test_a_200_that_is_not_audio_is_skipped_and_never_cached() -> void:
	var v := voice_awaiting_reply()
	v._on_done(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), "<html>not audio</html>".to_utf8_buffer())
	assert_false(FileAccess.file_exists(cache_file()), "no cache file (it used to be written before the check)")
	assert_false(v._busy, "the line is skipped, the voice goes on")
	assert_true(v._player.stream == null, "nothing played")


func test_a_reply_that_plays_is_cached() -> void:
	var v := voice_awaiting_reply()
	var mp3 := FileAccess.get_file_as_bytes(REAL_MP3)
	assert_gt(mp3.size(), 0, "fixture loaded")
	v._on_done(HTTPRequest.RESULT_SUCCESS, 200, PackedStringArray(), mp3)
	assert_true(FileAccess.file_exists(cache_file()), "cached for next time")
	assert_eq(FileAccess.get_file_as_bytes(cache_file()), mp3, "as received")
	assert_true(v._player.playing, "and played")
	DirAccess.remove_absolute(cache_file())
	await wait_seconds(v._player.stream.get_length() + 0.3)   # _play() ends on this node before it is freed


func test_a_broken_cached_file_is_dropped_so_the_line_is_fetched_again() -> void:
	var path := cache_file()
	if FileAccess.file_exists(path):
		DirAccess.remove_absolute(path)
	DirAccess.make_dir_recursive_absolute(GuardVoice.CACHE_DIR)
	var f := FileAccess.open(path, FileAccess.WRITE)
	f.store_buffer("<html>cached by an older build</html>".to_utf8_buffer())
	f.close()
	assert_null(GuardVoice.cached_stream(path), "not played")
	assert_false(FileAccess.file_exists(path), "the broken file is gone, so the next speak() fetches the line")
	assert_null(GuardVoice.cached_stream(path), "no file: a miss, no error")


func test_playable_tells_audio_from_anything_else() -> void:
	assert_null(GuardVoice.playable(PackedByteArray()), "empty")
	assert_null(GuardVoice.playable("<html>not audio</html>".to_utf8_buffer()), "text")
	assert_null(GuardVoice.playable("{\"error\": \"quota\"}".to_utf8_buffer()), "JSON")
	assert_not_null(GuardVoice.playable(FileAccess.get_file_as_bytes(REAL_MP3)), "a real file")
	assert_true(GuardVoice.looks_like_mp3(PackedByteArray([0x49, 0x44, 0x33, 0x04])), "an ID3 tag")
	assert_true(GuardVoice.looks_like_mp3(PackedByteArray([0xFF, 0xFB, 0x90, 0x00])), "a frame sync")
	assert_false(GuardVoice.looks_like_mp3(PackedByteArray([0xFF, 0x1B, 0x90, 0x00])), "not a frame sync")
