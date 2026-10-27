# ---------------------------------------------------------------------------
# test_gate_rules.gd
# Purpose : The rules no model can change (same cases as the web version).
# Usage   : python tools/dev.py test   (GUT)
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

var R: Dictionary = Tuning.RULES


func play(intents: Array) -> Dictionary:
	var s := GateRules.new_state(R)
	for i in intents:
		s = GateRules.apply_intent(s, i, R).state
	return s


func test_opens_for_greeting_plus_captain() -> void:
	assert_eq(play(["greeting", "mentions_captain"]).outcome, "open")


func test_never_opens_without_the_captain() -> void:
	var s := play(["greeting", "flattery", "flattery", "flattery", "question", "question", "flattery", "greeting"])
	assert_eq(s.outcome, "turned_away")
	assert_lt(s.trust, R.open_at)


func test_flattery_counts_twice() -> void:
	assert_eq(play(["flattery", "flattery", "flattery"]).trust, play(["flattery", "flattery"]).trust)


func test_two_threats_end_it() -> void:
	assert_eq(play(["threat", "threat"]).outcome, "turned_away")


func test_bribe_makes_captain_alone_not_enough() -> void:
	assert_eq(play(["bribe", "mentions_captain"]).outcome, "talking")


func test_turns_run_out() -> void:
	var many: Array = []
	for i in R.turns:
		many.append("question")
	assert_eq(play(many).outcome, "turned_away")


func test_misunderstood_line_costs_nothing() -> void:
	assert_eq(play(["other"]).trust, R.start_trust)


func test_nothing_changes_after_the_end() -> void:
	var done := play(["greeting", "mentions_captain"])
	assert_eq(GateRules.apply_intent(done, "threat", R).state, done)
