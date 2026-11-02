# ---------------------------------------------------------------------------
# eval_guard.gd
# Purpose : Golden-case eval for the AI guard (SOP-15 step 6): runs labelled player lines
#           through the real local model and reports intent accuracy and sample replies.
#           Use it before and after any prompt, model or sampler change.
# Usage   : godot --headless --path . --script res://tools/eval_guard.gd
# Exit    : 0 accuracy >= MIN_ACCURACY, 1 below it, 2 model or plugin missing
# Notes   : Needs the plugin and model (python tools/setup_ai.py). Not part of dev.py test:
#           a live model is slow, needs a GPU for speed, and is not deterministic.
#           Only a label FROM THE MODEL counts as a hit (tally): a keyword-fallback answer (the model too
#           slow, its label rejected, or the model dropped) is reported apart as FALL and never counts, so
#           the eval cannot pass on the scripted guard. tally() is unit tested (tests/test_eval_guard.gd).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-02 with Claude (Fable 5.1, claude-fable-5-1): fallbacks counted apart, never as hits (#5)
# ---------------------------------------------------------------------------
extends SceneTree

const MIN_ACCURACY: float = 0.75
const CASES: Array = [
	["Good evening, guard.", "greeting"], ["Hello there, friend.", "greeting"],
	["That armor looks well kept.", "flattery"], ["You must be the bravest guard in town.", "flattery"],
	["Here, take ten gold coins and let me in.", "bribe"], ["I can pay you well for a little favor.", "bribe"],
	["Open up or I'll break your nose.", "threat"], ["Move aside before you get hurt.", "threat"],
	["Captain Wren asked me to come tonight.", "mentions_captain"], ["The captain sent me with a message.", "mentions_captain"],
	["Why is the gate closed?", "question"], ["When does the gate open again?", "question"],
	["Banana.", "other"], ["I like turtles.", "other"],
]


## PASS: the right label from the model. MISS: a wrong label from the model. FALL: the keywords answered.
static func mark(want: String, intent: String, source: String) -> String:
	if source != "model":
		return "FALL"
	return "PASS" if intent == want else "MISS"


## Score rows of {want, intent, source}: {hits, misses, fallbacks}. Fallbacks never count as hits.
static func tally(rows: Array) -> Dictionary:
	var out := {"hits": 0, "misses": 0, "fallbacks": 0}
	for r: Dictionary in rows:
		match mark(r.want, r.intent, r.source):
			"PASS":
				out.hits += 1
			"MISS":
				out.misses += 1
			_:
				out.fallbacks += 1
	return out


func _init() -> void:
	var rng := RandomNumberGenerator.new()
	var brain := GuardBrain.new(rng)
	var err: String = await brain.load_model(self)
	if err != "":
		print("[ENV ] ", err)
		quit(2)
		return
	var rows: Array = []
	var total_ms := 0
	for c: Array in CASES:
		await brain.reset()
		var r: Dictionary = await brain.reply(self, c[0], "wary")
		rows.append({"want": c[1], "intent": r.intent, "source": r.source})
		total_ms += r.ms
		print("[%s] %-42s -> %-17s (want %-16s) %4d ms  %s%s" % [mark(c[1], r.intent, r.source), c[0], r.intent, c[1],
			r.ms, r.line, ("  [" + r.why + "]") if r.why != "" else ""])
	var t := tally(rows)
	var acc := float(t.hits) / CASES.size()
	print("accuracy %d/%d = %.0f%% from the model (%d miss, %d fallback not counted), mean %d ms" % [t.hits, CASES.size(),
		acc * 100, t.misses, t.fallbacks, total_ms / CASES.size()])
	if not brain.has_model():
		print("[WARN] the model was dropped during the run: ", brain.lost_why)
	quit(0 if acc >= MIN_ACCURACY else 1)
