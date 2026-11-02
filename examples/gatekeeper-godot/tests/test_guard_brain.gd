# ---------------------------------------------------------------------------
# test_guard_brain.gd
# Purpose : GUT tests for GuardBrain's error paths with a stand-in chat (no plugin, no model): a plugin error
#           is told apart from a timeout and drops the model, two timeouts in a row hand over to the scripted
#           guard, a hung history call cannot hang say() or reset(), and a restart stops the generation in flight.
# Usage   : python tools/dev.py test      (needs the GUT addon in addons/gut/)
# Notes   : The stand-in has the calls the brain makes on a NobodyWhoChat (ask().completed(), stop_generation,
#           reset_history, set_chat_history) and answers, errors or hangs as told. Timeouts are shrunk to 50 ms.
#           The load path (NobodyWhoModel.create and the warm-up) needs the real plugin: not covered here.
# Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
# ---------------------------------------------------------------------------
extends GutTest

const FAST := 0.05   # seconds: the brain's reply timeout in these tests


## What ask().completed() comes to: the text, null (the plugin's error), or never (a hung driver).
class FakeCompletion extends RefCounted:
	var chat: RefCounted

	func _init(c: RefCounted) -> void:
		chat = c

	func completed() -> Variant:
		match chat.mode:
			"error":
				return null
			"hang":
				await chat.never
				return null
		return chat.text


class FakeChat extends RefCounted:
	signal never   # emitted by nobody: a hung driver
	var mode := "text"   # text | error | hang
	var text := "greeting"
	var hang_history := false
	var asked: Array[String] = []
	var stopped := 0
	var history_calls := 0

	func ask(prompt: String) -> FakeCompletion:
		asked.append(prompt)
		return FakeCompletion.new(self)

	func stop_generation() -> void:
		stopped += 1

	func reset_history() -> void:
		history_calls += 1
		if hang_history:
			await never

	func set_chat_history(_history: Array) -> void:
		history_calls += 1
		if hang_history:
			await never


var brain: GuardBrain
var classifier: FakeChat
var speaker: FakeChat


func before_each() -> void:
	brain = GuardBrain.new(RandomNumberGenerator.new())
	brain.reply_timeout_s = FAST
	classifier = FakeChat.new()
	speaker = FakeChat.new()
	speaker.text = "Evening. What brings you here?"
	brain.classifier = classifier
	brain.speaker = speaker


func ask(text := "Good evening.") -> Dictionary:
	return await brain.reply(get_tree(), text, "wary")


func test_a_good_reply_comes_from_the_model() -> void:
	var r := await ask()
	assert_eq(r.intent, "greeting")
	assert_eq(r.line, "Evening. What brings you here?")
	assert_eq(r.source, "model")
	assert_eq(r.why, "")
	assert_eq(classifier.asked, ["Good evening."], "the classifier gets the bare line")
	assert_true(speaker.asked[0].begins_with("Good evening. [intent: greeting; Bram feels wary]"))
	assert_true(brain.has_model())


func test_a_plugin_error_is_reported_as_an_error_and_drops_the_model() -> void:
	classifier.mode = "error"
	var r := await ask()
	assert_true(r.why.begins_with("model error"), "an error, not 'model too slow': " + r.why)
	assert_eq(r.source, "fallback")
	assert_false(brain.has_model(), "the model is not asked again this session")
	assert_true(brain.lost_why.begins_with("model error"))
	var again := await ask("Nice helmet.")
	assert_eq(again.why, "", "the scripted guard answers at once, with no error and no wait")
	assert_eq(classifier.asked.size(), 1, "the model was not asked again")


func test_two_timeouts_in_a_row_hand_over_to_the_scripted_guard_but_one_does_not() -> void:
	classifier.mode = "hang"
	var first := await ask()
	assert_eq(first.why, GuardBrain.TOO_SLOW)
	assert_eq(classifier.stopped, 1, "the generation is stopped")
	assert_true(brain.has_model(), "one timeout can be a hiccup")
	var second := await ask()
	assert_eq(second.why, GuardBrain.TOO_SLOW)
	assert_false(brain.has_model(), "two in a row: stop costing a timeout per line")
	assert_true(brain.lost_why.contains("in a row"))
	var t0 := Time.get_ticks_msec()
	var third := await ask()
	assert_lt(Time.get_ticks_msec() - t0, int(FAST * 1000), "no wait at all now")
	assert_eq(third.source, "fallback")
	assert_eq(third.why, "")


func test_a_reply_in_time_resets_the_timeout_count() -> void:
	classifier.mode = "hang"
	await ask()
	classifier.mode = "text"
	var good := await ask()
	assert_eq(good.source, "model")
	assert_eq(brain.slow_in_a_row, 0)
	classifier.mode = "hang"
	await ask()
	assert_true(brain.has_model(), "slow, good, slow: still a hiccup")


func test_a_slow_line_keeps_the_models_intent_and_scripts_the_words() -> void:
	classifier.text = "flattery"
	speaker.mode = "hang"
	var r := await ask("Nice helmet.")
	assert_eq(r.intent, "flattery")
	assert_eq(r.source, "model")
	assert_has(GuardLines.LINES.flattery, r.line)
	assert_true(r.why.begins_with(GuardBrain.TOO_SLOW))
	assert_eq(brain.slow_in_a_row, 1, "a line that never comes counts like a label that never comes")


func test_a_line_error_keeps_the_intent_and_drops_the_model() -> void:
	classifier.text = "bribe"
	speaker.mode = "error"
	var r := await ask("Ten gold for you.")
	assert_eq(r.intent, "bribe")
	assert_has(GuardLines.LINES.bribe, r.line)
	assert_true(r.why.begins_with("model error"))
	assert_false(brain.has_model())


func test_a_hung_history_call_cannot_hang_say() -> void:
	classifier.hang_history = true
	var t0 := Time.get_ticks_msec()
	var r := await ask()
	assert_lt(Time.get_ticks_msec() - t0, 1000, "back within the timeout, not never")
	assert_eq(r.why, GuardBrain.TOO_SLOW)
	assert_eq(classifier.asked.size(), 0, "never asked: the history call never returned")


func test_reset_gives_up_on_a_hung_model() -> void:
	speaker.hang_history = true
	var t0 := Time.get_ticks_msec()
	await brain.reset()
	assert_lt(Time.get_ticks_msec() - t0, 1000, "back within the timeout, not never")
	assert_false(brain.has_model())
	assert_true(brain.lost_why.contains("history"))


func test_reset_stops_the_generation_in_flight_and_ends_that_reply() -> void:
	classifier.mode = "hang"
	brain.reply(get_tree(), "Captain Wren sent me.", "wary")   # the player's line is being classified
	await get_tree().process_frame
	await brain.reset()
	assert_eq(classifier.stopped, 1, "stopped at once, not after the timeout")
	await wait_seconds(FAST * 3)                               # the old reply's step runs out meanwhile
	assert_eq(speaker.asked.size(), 0, "the old reply does not go on to the speaker")
	assert_true(brain.has_model(), "a restart is not a timeout")
	assert_eq(brain.slow_in_a_row, 0)
	assert_eq(classifier.history_calls, 3, "seeded for the reply, then reset and seeded again")
