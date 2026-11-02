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
#           brain.has_model(), brain.lost_why                   # false once the model was dropped, and why
# Notes   : The plugin is reached through ClassDB.class_call_static, never by class name, so this
#           script parses and the game runs without the plugin (scripted guard only).
#           NobodyWho v12 API (verified against its docs and source, 2026-10): NobodyWhoModel.create(path)
#           loads once and is shared by both chats; NobodyWhoChat.create(model, config) and
#           chat.ask(text).completed() are awaitable; NobodyWhoSamplerPresets.constrain_with_regex(re).
#           Every model step has a timeout and a scripted fallback (SOP-15). A plugin error (completed()
#           resolves with null) or Tuning.MAX_SLOW_REPLIES timeouts in a row drop the model for the session:
#           has_model() turns false and the scripted guard plays on at once, instead of an error or a
#           timeout on every line. Tested with a stand-in chat (tests/test_guard_brain.gd); the load path
#           (NobodyWhoModel.create, the warm-up) needs the real plugin (verify).
#
# Pseudocode (reply)
#   no model -> scripted
#   seed the classifier, ask the label, ask the line: each awaited with a frame-polled timeout (_bounded)
#   restarted meanwhile -> scripted (the game drops it) | label slow -> count, maybe drop | error -> drop
#   bad label -> scripted | line slow or rejected -> the model's intent, scripted words | line error -> drop
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-02 with Claude (Fable 5.1, claude-fable-5-1): a restart stops the generation in flight (#1);
#           errors told apart from timeouts, the model dropped after an error or MAX_SLOW_REPLIES timeouts,
#           history calls and reset() bounded (#3)
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
const NO_REPLY := "the plugin returned no reply (see the console)"   # completed() resolved with null
const TOO_SLOW := "model too slow"

var rng: RandomNumberGenerator
var classifier: Variant = null   # NobodyWhoChat
var speaker: Variant = null      # NobodyWhoChat
var reply_timeout_s: float = Tuning.REPLY_TIMEOUT_S   # instance copies of the tunables, so a test can shrink them
var load_timeout_s: float = Tuning.LOAD_TIMEOUT_S
var slow_in_a_row: int = 0       # model timeouts in a row; Tuning.MAX_SLOW_REPLIES of them drop the model
var lost_why: String = ""        # why the model was dropped this session ("" while it is still in use)
var _asking: Variant = null      # the chat generating a reply right now, so a restart can stop it
var _epoch: int = 0              # bumped by reset(): a reply started before it ends after its current step
var _tree: SceneTree = null      # the tree given to load_model() or reply(); Engine.get_main_loop() when none


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
## Gives up after load_timeout_s, so a stuck load or warm-up never leaves the start screen hanging.
func load_model(tree: SceneTree) -> String:
	var problem := model_problem()
	if problem != "":
		return problem
	_tree = tree
	var box := {"done": false, "err": "", "abandoned": false}
	_load(box)
	var t0 := Time.get_ticks_msec()
	while not box.done and (Time.get_ticks_msec() - t0) < load_timeout_s * 1000.0:
		await _loop().process_frame
	if not box.done:
		box.abandoned = true   # a late finish must not switch the guard to the model mid-game
		classifier = null
		speaker = null
		return "the model took longer than %d s to load" % int(load_timeout_s)
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
	var warm: Variant = await c.ask("Hello").completed()   # first generation warms up the GPU: now, not on turn one
	if box.abandoned:
		return
	if warm == null:   # the plugin's error: a model that cannot answer once will not answer later either
		box.err = "the warm-up reply failed (see the console)"
		box.done = true
		return
	classifier = c
	speaker = s
	await reset()
	box.done = true


## Fresh conversation: both chats start from their examples. A reply still being generated ("Start over" while
## Bram was thinking) is stopped first, and the reply() that started it ends after its current step (the game
## drops its result by its run counter). History calls that hang drop the model (verify with the real model:
## tested with a stand-in chat).
func reset() -> void:
	if not has_model():
		return
	_epoch += 1
	if _asking != null:
		_asking.stop_generation()
	var r := await _bounded(_reseed.bind(classifier, speaker), reply_timeout_s)
	if not r.done:
		_drop("the model stopped answering (a history call took longer than %d s)" % int(reply_timeout_s))


func _reseed(c: Variant, s: Variant) -> void:
	await c.reset_history()
	await c.set_chat_history(CLASSIFY_EXAMPLES)
	await s.reset_history()
	await s.set_chat_history(SPEAK_EXAMPLES)


func scripted(text: String, why: String = "") -> Dictionary:
	var intent := GateIntent.keyword_intent(text)
	return {"intent": intent, "line": GuardLines.fallback_line(intent, rng), "source": "fallback", "ms": 0, "why": why}


## One reply. Each model step has its own timeout; nothing from the model is used unchecked.
func reply(tree: SceneTree, text: String, mood: String) -> Dictionary:
	text = text.substr(0, GateIntent.MAX_INPUT)
	if not has_model():
		return scripted(text)
	_tree = tree
	var t0 := Time.get_ticks_msec()
	var epoch := _epoch
	var c: Variant = classifier
	var seeded := await _bounded(_seed.bind(c, CLASSIFY_EXAMPLES), reply_timeout_s)   # stateless classification
	if epoch != _epoch:
		return scripted(text, "restarted")
	if not seeded.done:
		return _slow(text, t0)
	var label := await _ask(c, text)
	if epoch != _epoch:
		return scripted(text, "restarted")
	if label.has("slow"):
		return _slow(text, t0)
	if label.has("error"):
		_drop("model error: " + str(label.error))
		return scripted(text, lost_why).merged({"ms": Time.get_ticks_msec() - t0}, true)
	var intent := GateIntent.parse_label(str(label.text))
	if intent == "":
		return scripted(text, "invalid label: " + str(label.text).substr(0, 40)).merged({"ms": Time.get_ticks_msec() - t0}, true)
	var spoken := await _ask(speaker, "%s [intent: %s; Bram feels %s]" % [text, intent, mood])
	if epoch != _epoch:
		return scripted(text, "restarted")
	var line := ""
	var why := ""
	if spoken.has("error"):
		_drop("model error: " + str(spoken.error))
		why = lost_why
	elif spoken.has("slow"):
		why = TOO_SLOW + " (the line), scripted instead"
		_note_slow()
	else:
		slow_in_a_row = 0   # a whole reply in time: earlier timeouts were a hiccup
		line = GateIntent.parse_line(str(spoken.text))
		if line.is_empty():
			why = "line rejected, scripted instead: " + JSON.stringify(str(spoken.text).substr(0, 80))
	if line.is_empty():
		line = GuardLines.fallback_line(intent, rng)    # keep the model's intent, script the words
	return {"intent": intent, "line": line, "source": "model", "ms": Time.get_ticks_msec() - t0, "why": why}


## A label that never came: counted; the scripted guard answers this line.
func _slow(text: String, t0: int) -> Dictionary:
	_note_slow()
	return scripted(text, TOO_SLOW).merged({"ms": Time.get_ticks_msec() - t0}, true)


func _note_slow() -> void:
	slow_in_a_row += 1
	if slow_in_a_row >= Tuning.MAX_SLOW_REPLIES:
		_drop("the model timed out %d times in a row" % slow_in_a_row)


## The model is not asked again this session: has_model() turns false and the scripted guard plays on.
func _drop(why: String) -> void:
	lost_why = why
	classifier = null
	speaker = null


func _seed(chat: Variant, history: Array) -> void:
	await chat.set_chat_history(history)


## One completion. {"text": ...}, {"slow": true} (stopped after reply_timeout_s) or {"error": ...} (the plugin
## resolved completed() with null). Only the last two are the model's fault, and only the error is final.
func _ask(chat: Variant, prompt: String) -> Dictionary:
	_asking = chat
	var r := await _bounded(_completion.bind(chat, prompt), reply_timeout_s)
	_asking = null
	if not r.done:
		chat.stop_generation()
		return {"slow": true}
	if r.value == null:
		return {"error": NO_REPLY}
	return {"text": str(r.value)}


func _completion(chat: Variant, prompt: String) -> Variant:
	return await chat.ask(prompt).completed()


## Run `work` (a coroutine Callable) and give up after `seconds` of frames. Returns {done, value}; a late
## finish still writes into a box nobody reads, which is harmless.
func _bounded(work: Callable, seconds: float) -> Dictionary:
	var box := {"done": false, "value": null}
	_run_into(box, work)
	var t0 := Time.get_ticks_msec()
	while not box.done and (Time.get_ticks_msec() - t0) < seconds * 1000.0:
		await _loop().process_frame
	return box


func _run_into(box: Dictionary, work: Callable) -> void:
	box.value = await work.call()
	box.done = true


func _loop() -> SceneTree:
	return _tree if _tree != null else Engine.get_main_loop() as SceneTree
