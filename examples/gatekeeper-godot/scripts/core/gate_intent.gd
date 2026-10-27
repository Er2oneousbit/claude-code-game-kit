# ---------------------------------------------------------------------------
# gate_intent.gd
# Purpose : What the player meant, as one value from a fixed list. The model's only
#           power over the game is choosing one of these (SOP-15: the game decides,
#           the model only words it). Also the strict parser for model output and the
#           keyword classifier used when there is no model.
# Usage   : GateIntent.parse_label(raw) -> intent or "" ; GateIntent.parse_line(raw) -> line or ""
#           GateIntent.keyword_intent(player_text) -> String
# Notes   : Engine-free and unit tested against recorded model outputs (tests/fixtures/recorded.json),
#           the same fixtures as the web version of this example.
#
# Pseudocode (parse_line):
#   first line only -> drop a "Bram:" prefix and copied [...] notes -> collapse spaces -> cut to MAX_LINE
#   reject: empty, braces or brackets (leaked JSON or markup), breaking character ("as an AI ...")
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name GateIntent
extends RefCounted

const INTENTS: Array[String] = ["greeting", "flattery", "bribe", "threat", "mentions_captain", "question", "other"]
const MAX_LINE: int = 220   # characters shown from the model; longer replies are cut, not trusted
const MAX_INPUT: int = 200  # characters the player may type per message

# Checked in priority order: threats win over anything else in the same sentence
const KEYWORDS: Array = [
	["threat", "(?i)\\b(kill|hurt|attack|stab|burn|or else|break (the|your)|smash|threat)\\b"],
	["mentions_captain", "(?i)\\b(captain|wren)\\b"],
	["bribe", "(?i)\\b(gold|coins?|pay|money|bribe|silver|reward)\\b"],
	["flattery", "(?i)\\b(strong|brave|handsome|impressive|great|fine|nice|best|honou?rable|wise|sharp|tough|admire|well[- ]kept|looks? (good|great|sharp))\\b"],
	["greeting", "(?i)^\\s*(hi|hello|hey|greetings|good (morning|day|evening)|well met)\\b"],
	["question", "(?i)\\?\\s*$|^\\s*(who|what|why|where|when|how|can|could|is|are)\\b"],
]


static func clean_line(text: String) -> String:
	var ws := RegEx.create_from_string("\\s+")
	var flat := ws.sub(text, " ", true).strip_edges().trim_prefix("\"").trim_suffix("\"")
	if flat.length() > MAX_LINE:
		flat = flat.substr(0, MAX_LINE - 3).strip_edges() + "..."
	return flat


## The classifier's output: exactly one label (case and surrounding space forgiven), else "".
static func parse_label(raw: String) -> String:
	var label := raw.strip_edges().to_lower()
	return label if INTENTS.has(label) else ""


## The speaker's output: one clean in-character line, else "" (the caller uses the scripted line).
## First line only, no "Bram:" prefix, copied "[...]" notes cut out; rejects braces, brackets,
## angle brackets (leaked JSON or markup) and lines that break character ("as an AI ...").
static func parse_line(raw: String) -> String:
	var first := raw.strip_edges().split("\n")[0]
	var prefix := RegEx.create_from_string("(?i)^\\s*bram\\s*:\\s*")
	var notes := RegEx.create_from_string("\\s*\\[[^\\]]*\\]\\s*")   # small models copy "[intent: ...]" notes
	var line := clean_line(notes.sub(prefix.sub(first, ""), " ", true))
	if line.is_empty() or RegEx.create_from_string("[{}\\[\\]<>]").search(line) != null:
		return ""
	if RegEx.create_from_string("(?i)\\b(as an ai|language model|i am an ai|i'm an ai|assistant)\\b").search(line) != null:
		return ""
	return line


## Fallback classifier: first matching rule wins.
static func keyword_intent(text: String) -> String:
	for rule: Array in KEYWORDS:
		var re := RegEx.create_from_string(rule[1])
		if re.search(text) != null:
			return rule[0]
	return "other"
