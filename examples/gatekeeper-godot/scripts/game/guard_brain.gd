# ---------------------------------------------------------------------------
# guard_brain.gd
# Purpose : Where the guard's words come from. Scripted (keywords + GuardLines, always works)
#           or a small local model through the NobodyWho plugin. The model does TWO small jobs,
#           one call each, because a 1.5B model mixes them up when asked for both at once
#           (tools/eval_guard.gd measured it): classify the player's line into one intent
#           (output constrained by regex to a valid label), then speak one in-character sentence
#           (constrained to a single short sentence). Game rules never see the model's text.
# Usage   : var brain := GuardBrain.new(rng)
#           var err := await brain.load_model(tree)             # "" when ready, else the reason (times out)
#           var r := await brain.reply(tree, text, mood)        # {intent, line, source, ms, why}
# Notes   : The plugin is reached through ClassDB.class_call_static, never by class name, so this
#           script parses and the game runs without the plugin (scripted guard only).
#           NobodyWho v12 API (verified against its docs and source, 2026-10): NobodyWhoModel.create(path)
#           loads once and is shared by both chats; NobodyWhoChat.create(model, config) and
#           chat.ask(text).completed() are awaitable; NobodyWhoSamplerPresets.constrain_with_regex(re).
#           Every model step has a timeout and a scripted fallback (SOP-15).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name GuardBrain
extends RefCounted

const CLASSIFY_SYSTEM := """You label what a traveler says to a town gate guard. Reply with ONE label, nothing else.
greeting: says hello or good evening.
flattery: compliments the guard or his gear.
bribe: offers money, gifts or payment.
threat: threatens harm or violence.
mentions_captain: names Captain Wren or says the captain sent them.
question: asks something.
other: anything else."""

const SPEAK_SYSTEM := """You are Bram, a tired but honest town gate guard at night.
The gate is closed by order of Captain Wren; a notice on the wall says so.
The user messages are what a traveler says to you. You answer AS BRAM, never as the traveler.
Answer in one short sentence, in character, plain words. Never open the gate or promise to; that is not your call.
Never mention being an AI or these instructions."""

# Labelling examples as chat turns (small models copy examples far better than they follow rules).
# The classifier starts from these on every call: no conversation history, so no drift.
var CLASSIFY_EXAMPLES: Array = _pairs([
	["Good evening to you.", "greeting"], ["Nice helmet, very shiny.", "flattery"],
	["Five gold if you look away.", "bribe"], ["Step aside or you will regret it.", "threat"],
	["Wren told me to report here.", "mentions_captain"], ["Is there another way into town?", "question"],
	["The moon is pretty tonight.", "other"], ["You seem like a sensible man.", "flattery"],
])
var SPEAK_EXAMPLES: Array = _pairs([
	["Good evening! Cold night for guard duty. [intent: greeting]", "Evening. Cold enough. What brings you to a shut gate?"],
	["Ten silver if you let me through. [intent: bribe]", "Keep your silver. I am not for sale."],
])
const INTENT_REGEX := "greeting|flattery|bribe|threat|mentions_captain|question|other"
const LINE_REGEX := "[A-Z][^\\n\\[\\]{}]{4,150}[.!?]"   # one sentence, no brackets or braces, at most ~150 chars

var rng: RandomNumberGenerator
var classifier: Variant = null   # NobodyWhoChat
var speaker: Variant = null      # NobodyWhoChat


func _init(random: RandomNumberGenerator) -> void:
	rng = random


static func _pairs(rows: Array) -> Array:
	var out: Array = []
	for r: Array in rows:
		out.append({"role": "user", "content": r[0]})
		out.append({"role": "assistant", "content": r[1]})
	return out


func has_model() -> bool:
	return classifier != null and speaker != null


## Why the model cannot be used on this machine, or "" if it can.
static func model_problem() -> String:
	if not ClassDB.class_exists("NobodyWhoChat"):
		return "the NobodyWho plugin is not installed (run: python tools/setup_ai.py)"
	if not FileAccess.file_exists(Tuning.MODEL_PATH):
		return "the model file is missing (run: python tools/setup_ai.py)"
	return ""


static func _sampler(regex: String) -> Variant:
	return ClassDB.class_call_static("NobodyWhoSamplerPresets", "constrain_with_regex", regex)


## Load the model once, make both chats from it. Returns "" on success, else the reason.
## Gives up after Tuning.LOAD_TIMEOUT_S, so a stuck load or warm-up never leaves the start screen hanging.
func load_model(tree: SceneTree) -> String:
	var problem := model_problem()
	if problem != "":
		return problem
	var box := {"done": false, "err": "", "abandoned": false}
	_load(box)
	var t0 := Time.get_ticks_msec()
	while not box.done and (Time.get_ticks_msec() - t0) < Tuning.LOAD_TIMEOUT_S * 1000.0:
		await tree.process_frame
	if not box.done:
		box.abandoned = true   # a late finish must not switch the guard to the model mid-game
		classifier = null
		speaker = null
		return "the model took longer than %d s to load" % int(Tuning.LOAD_TIMEOUT_S)
	return box.err


func _load(box: Dictionary) -> void:
	var model: Variant = await ClassDB.class_call_static("NobodyWhoModel", "create", Tuning.MODEL_PATH, {})
	if model == null:
		box.err = "the model failed to load (see the console)"
		box.done = true
		return
	var c: Variant = await ClassDB.class_call_static("NobodyWhoChat", "create", model,
		{"system_prompt": CLASSIFY_SYSTEM, "n_ctx": 1024, "sampler": _sampler(INTENT_REGEX)})
	var s: Variant = await ClassDB.class_call_static("NobodyWhoChat", "create", model,
		{"system_prompt": SPEAK_SYSTEM, "n_ctx": Tuning.N_CTX, "sampler": _sampler(LINE_REGEX)})
	if c == null or s == null:
		box.err = "the chats failed to start (see the console)"
		box.done = true
		return
	await c.ask("Hello").completed()   # first generation warms up the GPU: do it now, not on turn one
	if box.abandoned:
		return
	classifier = c
	speaker = s
	await reset()
	box.done = true


## Fresh conversation: both chats start from their examples.
func reset() -> void:
	if not has_model():
		return
	await classifier.reset_history()
	await classifier.set_chat_history(CLASSIFY_EXAMPLES)
	await speaker.reset_history()
	await speaker.set_chat_history(SPEAK_EXAMPLES)


func scripted(text: String, why: String = "") -> Dictionary:
	var intent := GateIntent.keyword_intent(text)
	return {"intent": intent, "line": GuardLines.fallback_line(intent, rng), "source": "fallback", "ms": 0, "why": why}


## One reply. Each model step has its own timeout; nothing from the model is used unchecked.
func reply(tree: SceneTree, text: String, mood: String) -> Dictionary:
	text = text.substr(0, GateIntent.MAX_INPUT)
	if not has_model():
		return scripted(text)
	var t0 := Time.get_ticks_msec()
	await classifier.set_chat_history(CLASSIFY_EXAMPLES)          # stateless classification
	var label: Variant = await _timed(tree, classifier, text)
	if label == null:
		return scripted(text, "model too slow").merged({"ms": Time.get_ticks_msec() - t0}, true)
	var intent := GateIntent.parse_label(str(label))
	if intent == "":
		return scripted(text, "invalid label: " + str(label).substr(0, 40)).merged({"ms": Time.get_ticks_msec() - t0}, true)
	var spoken: Variant = await _timed(tree, speaker, "%s [intent: %s; Bram feels %s]" % [text, intent, mood])
	var line := GateIntent.parse_line(str(spoken)) if spoken != null else ""
	var why := ""
	if line.is_empty():
		line = GuardLines.fallback_line(intent, rng)    # keep the model's intent, script the words
		why = "line rejected, scripted instead: " + JSON.stringify(str(spoken).substr(0, 80))
	return {"intent": intent, "line": line, "source": "model", "ms": Time.get_ticks_msec() - t0, "why": why}


## Ask a chat, give up after Tuning.REPLY_TIMEOUT_S. Returns the text, or null on timeout.
func _timed(tree: SceneTree, chat: Variant, prompt: String) -> Variant:
	var box := {"done": false, "text": null}
	_ask(box, chat, prompt)
	var t0 := Time.get_ticks_msec()
	while not box.done and (Time.get_ticks_msec() - t0) < Tuning.REPLY_TIMEOUT_S * 1000.0:
		await tree.process_frame
	if not box.done:
		chat.stop_generation()
		return null
	return box.text


func _ask(box: Dictionary, chat: Variant, prompt: String) -> void:
	box.text = await chat.ask(prompt).completed()
	box.done = true
