# ---------------------------------------------------------------------------
# test_main_flow.gd
# Purpose : GUT tests for the game flow in scripts/game/main.gd with a stand-in brain (no plugin, no model):
#           one intro when the scripted guard is picked during a model load, "Start over" keeps the brain and
#           drops a reply still on its way, the new game takes a line at once, and a line typed while the guard
#           is thinking stays in the box.
# Usage   : python tools/dev.py test      (needs the GUT addon in addons/gut/)
# Notes   : The main scene is built headless (its sounds play into no device). The stand-in extends GuardBrain
#           and finishes loading or answering only when the test says so, like the web twin's fake brains.
#           Buttons are found by their text, as a player would.
# Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
# ---------------------------------------------------------------------------
extends GutTest

const MainScript := preload("res://scripts/game/main.gd")
const MAIN_SCENE := preload("res://scenes/main.tscn")
const HALT := "Halt. The gate is closed."
const SCRIPTED_BUTTON := "Play with the scripted guard"
const AGAIN_BUTTON := "Start over"


## A model brain under the test's control: load_model() and reply() finish when the test fires their signal.
class FakeBrain extends GuardBrain:
	signal loaded
	signal answered
	signal reset_done
	var next_reply := {"intent": "greeting", "line": "Evening.", "source": "model", "ms": 1, "why": ""}
	var resets := 0
	var slow_reset := false   # true: reset() waits for reset_done, like history calls on the real model
	var alive := true         # false once the brain dropped the model (an error, timeouts in a row)
	var die_on_reply := false
	var asked: Array[String] = []

	func _init() -> void:
		super(RandomNumberGenerator.new())

	func has_model() -> bool:
		return alive

	func load_model(_tree: SceneTree) -> String:
		await loaded
		return ""

	func reset() -> void:
		resets += 1
		if slow_reset:
			await reset_done

	func reply(_tree: SceneTree, text: String, _mood: String) -> Dictionary:
		asked.append(text)
		await answered
		if die_on_reply:
			alive = false
			lost_why = "model error: a stand-in failure"
			return scripted(text, lost_why)
		return next_reply.duplicate()


var main: MainScript
var brain: FakeBrain


func before_each() -> void:
	main = MAIN_SCENE.instantiate()
	add_child_autofree(main)
	brain = FakeBrain.new()
	main.brain = brain


func button(text: String) -> Button:
	for b: Button in main.find_children("*", "Button", true, false):
		if b.text == text:
			return b
	fail_test("no button named %s" % text)
	return null


func intros() -> int:
	return main.log_box.get_parsed_text().count(HALT)


func test_scripted_guard_picked_during_a_model_load_gives_one_intro() -> void:
	main._use_model()                                # "Talk to the AI guard": the load is under way
	assert_true(button(SCRIPTED_BUTTON).disabled, "the scripted button waits for the load")
	button(SCRIPTED_BUTTON).pressed.emit()           # the click anyway (a key, a race): must not begin
	assert_eq(intros(), 0, "no intro before the load ends")
	brain.loaded.emit()                              # the model is ready
	assert_eq(intros(), 1, "one intro, with the model (was two: scripted at once, then the model mid-game)")
	assert_true(main.begun)
	assert_false(main.loading)


func test_start_over_keeps_the_brain_and_drops_the_reply_in_flight() -> void:
	button(SCRIPTED_BUTTON).pressed.emit()
	main.say("Captain Wren sent me.")                # the model is thinking
	assert_true(main.busy)
	button(AGAIN_BUTTON).pressed.emit()              # "Start over" while waiting
	assert_same(main.brain, brain, "the same brain: the model is not loaded again")
	assert_eq(brain.resets, 1, "a fresh conversation on the loaded model")
	assert_eq(main.state, GateRules.new_state(Tuning.RULES), "a fresh game")
	assert_false(main.busy, "the new game takes a line at once")
	assert_eq(intros(), 1, "the log starts over with one intro")

	brain.next_reply = {"intent": "mentions_captain", "line": "Wren? Hm.", "source": "model", "ms": 5, "why": ""}
	brain.answered.emit()                            # the old reply lands now
	assert_eq(main.state.trust, Tuning.RULES.start_trust, "the old reply does not touch the new game")
	assert_false(main.log_box.get_parsed_text().contains("Wren? Hm."), "nor its line")

	brain.next_reply = {"intent": "greeting", "line": "Evening.", "source": "model", "ms": 1, "why": ""}
	main.say("Good evening.")
	brain.answered.emit()
	assert_eq(main.state.trust, Tuning.RULES.start_trust + Tuning.RULES.delta.greeting, "one greeting counts once")
	assert_eq(main.state.outcome, "talking", "and does not open the gate (it did when the old 65 trust survived)")


func test_a_double_click_on_start_over_restarts_once() -> void:
	button(SCRIPTED_BUTTON).pressed.emit()
	brain.slow_reset = true
	button(AGAIN_BUTTON).pressed.emit()              # the reset is under way on the model
	button(AGAIN_BUTTON).pressed.emit()              # second click before it finished
	assert_eq(main.run, 1, "the second click does nothing")
	assert_eq(brain.resets, 1)
	brain.reset_done.emit()
	assert_eq(intros(), 1, "one intro, not two")
	assert_false(main.restarting)
	button(AGAIN_BUTTON).pressed.emit()              # a later click works again
	assert_eq(main.run, 2)


func test_a_line_typed_while_the_guard_is_thinking_is_kept() -> void:
	button(SCRIPTED_BUTTON).pressed.emit()
	main.say("Good evening.")                        # the model is thinking
	main.input.text = "Captain Wren sent me."
	main.input.text_submitted.emit(main.input.text)  # Enter while Bram thinks
	assert_eq(main.input.text, "Captain Wren sent me.", "the line stays in the box (it was cleared and lost)")
	assert_false(main.log_box.get_parsed_text().contains("You: Captain Wren sent me."), "and is not sent yet")
	assert_eq(brain.asked.size(), 1, "the model got the first line only")
	brain.answered.emit()                            # Bram answers the first line
	main.input.text_submitted.emit(main.input.text)  # Enter again
	assert_eq(main.input.text, "", "taken now")
	assert_true(main.log_box.get_parsed_text().contains("You: Captain Wren sent me."))
	assert_eq(brain.asked.back(), "Captain Wren sent me.")


func test_a_lost_model_is_announced_once_and_the_game_goes_on() -> void:
	button(SCRIPTED_BUTTON).pressed.emit()
	brain.die_on_reply = true
	main.say("Good evening.")
	brain.answered.emit()
	var text := main.log_box.get_parsed_text()
	assert_true(text.contains("The AI guard stopped working; the scripted guard takes over."), "announced")
	assert_eq(main.state.turns_left, Tuning.RULES.turns - 1, "the line still counted (it has a scripted reply)")
	main.say("Nice helmet.")
	brain.answered.emit()
	assert_eq(main.log_box.get_parsed_text().count("stopped working"), 1, "announced once, not per line")
	assert_eq(main.state.turns_left, Tuning.RULES.turns - 2, "the game goes on with the scripted guard")


func test_enter_on_an_empty_box_does_nothing() -> void:
	button(SCRIPTED_BUTTON).pressed.emit()
	main.input.text = "   "
	main.input.text_submitted.emit(main.input.text)
	assert_eq(brain.asked.size(), 0)
	assert_false(main.busy)


func test_start_over_puts_the_gate_and_the_guard_back() -> void:
	button(SCRIPTED_BUTTON).pressed.emit()
	brain.next_reply = {"intent": "mentions_captain", "line": "Wren!", "source": "model", "ms": 1, "why": ""}
	main.state.trust = Tuning.RULES.open_at - Tuning.RULES.delta.mentions_captain
	main.say("Captain Wren sent me.")
	brain.answered.emit()
	assert_eq(main.state.outcome, "open")
	assert_true(main.end_tween != null and main.end_tween.is_valid(), "the gate is opening")
	button(AGAIN_BUTTON).pressed.emit()
	assert_eq(main.door.modulate.a, 1.0, "the door is shut again")
	assert_eq(main.guard.position, main.guard_home, "the guard is back in the way")
	assert_eq(main.state.outcome, "talking")
