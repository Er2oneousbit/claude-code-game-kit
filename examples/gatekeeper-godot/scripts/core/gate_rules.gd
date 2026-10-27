# ---------------------------------------------------------------------------
# gate_rules.gd
# Purpose : The rules: how much each intent moves the guard's trust, when the gate
#           opens, when the guard sends you away. Pure functions on a state Dictionary,
#           unit tested. This is the part a language model can never change (SOP-15).
# Usage   : var s := GateRules.new_state(rules); var step := GateRules.apply_intent(s, "greeting", rules)
#           s = step.state
# Notes   : Same rules as the web version (src/core/gatekeeper.ts there). The puzzle: the notice says
#           the gate is closed by order of Captain Wren; naming the captain is the big trust jump.
#
# Pseudocode:
#   delta = rules.delta[intent], with "first time only" (greeting, captain) and "max twice" (flattery)
#   trust = clamp(trust + delta, 0, 100); turns -= 1
#   trust >= open_at -> open | threats >= max_threats or turns == 0 -> turned_away | else talking
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name GateRules
extends RefCounted


static func new_state(r: Dictionary) -> Dictionary:
	return {"trust": r.start_trust, "turns_left": r.turns, "threats": 0, "flattery": 0,
		"greeted": false, "captain_mentioned": false, "outcome": "talking"}


static func apply_intent(s: Dictionary, intent: String, r: Dictionary) -> Dictionary:
	if s.outcome != "talking":
		return {"state": s, "delta": 0, "note": "the conversation is over"}
	var next := s.duplicate()
	var delta: int = r.delta[intent]
	var note := intent
	match intent:
		"greeting":
			if s.greeted:
				delta = 0
				note = "already greeted"
			next.greeted = true
		"flattery":
			if s.flattery >= r.max_flattery:
				delta = 0
				note = "flattery wore off"
			next.flattery += 1
		"mentions_captain":
			if s.captain_mentioned:
				delta = 0
				note = "captain already mentioned"
			next.captain_mentioned = true
		"threat":
			next.threats += 1
	next.trust = clampi(s.trust + delta, 0, 100)
	next.turns_left = s.turns_left - 1
	if next.trust >= r.open_at:
		next.outcome = "open"
	elif next.threats >= r.max_threats or next.turns_left <= 0:
		next.outcome = "turned_away"
	return {"state": next, "delta": next.trust - s.trust, "note": note}


## A word for the prompt, so the model's tone follows the game's state (state in, words out).
static func mood(s: Dictionary, r: Dictionary) -> String:
	if s.trust >= r.open_at * 0.6:
		return "warming up"
	return "wary" if s.trust >= r.start_trust else "suspicious"
