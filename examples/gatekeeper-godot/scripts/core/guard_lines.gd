# ---------------------------------------------------------------------------
# guard_lines.gd
# Purpose : The guard's scripted voice: every reply when no model is loaded, any reply the
#           model gets wrong or too late, and always the final lines (gate opens, turned
#           away), so endings stay consistent and fair. Same lines as the web version.
# Usage   : GuardLines.fallback_line("greeting", rng) ; GuardLines.outcome_line("open", rng)
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name GuardLines
extends RefCounted

const LINES: Dictionary = {
	"greeting": ["Evening. State your business.", "Aye, hello. The gate's shut, though.", "Hm. Traveler. What do you want?"],
	"flattery": ["Kind words won't open a gate. Still, kind words.", "Strong, am I? My mother says the same.", "Flattery. Noted. Not convinced."],
	"bribe": ["Put that away before someone sees it.", "I'm a guard, not a toll booth.", "Coin? Insulting. Go on, put it back."],
	"threat": ["Try it. See how that goes.", "That's a fine way to end up in a cell.", "Say that again and you'll be walking home."],
	"mentions_captain": ["Captain Wren? Why didn't you say so.", "You know the captain? That changes things.", "Wren's orders, eh. Let's see."],
	"question": ["The gate's closed by order of the captain. That's all I know.", "Questions, questions. The notice says it all.", "Read the notice. It's right there."],
	"other": ["What? Speak plainly.", "I don't follow you, traveler.", "Hm. Is that supposed to mean something?"],
}
const ENDINGS: Dictionary = {
	"open": ["Alright. On you go, and tell the captain I was polite.", "Fine. The gate's open. Don't make me regret it."],
	"turned_away": ["That's enough. Off with you.", "We're done here. Come back with better manners."],
}


static func fallback_line(intent: String, rng: RandomNumberGenerator) -> String:
	var options: Array = LINES[intent]
	return options[rng.randi_range(0, options.size() - 1)]


static func outcome_line(outcome: String, rng: RandomNumberGenerator) -> String:
	var options: Array = ENDINGS[outcome]
	return options[rng.randi_range(0, options.size() - 1)]
