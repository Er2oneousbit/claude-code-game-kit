# ---------------------------------------------------------------------------
# eval_guard.gd
# Purpose : Golden-case eval for the AI guard (SOP-15 step 6): runs labelled player lines
#           through the real local model and reports intent accuracy and sample replies.
#           Use it before and after any prompt, model or sampler change.
# Usage   : godot --headless --path . --script res://tools/eval_guard.gd
# Exit    : 0 accuracy >= MIN_ACCURACY, 1 below it, 2 model or plugin missing
# Notes   : Needs the plugin and model (python tools/setup_ai.py). Not part of dev.py test:
#           a live model is slow, needs a GPU for speed, and is not deterministic.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
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


func _init() -> void:
	var rng := RandomNumberGenerator.new()
	var brain := GuardBrain.new(rng)
	var err: String = await brain.load_model(self)
	if err != "":
		print("[ENV ] ", err)
		quit(2)
		return
	var hits := 0
	var total_ms := 0
	for c: Array in CASES:
		await brain.reset()
		var r: Dictionary = await brain.reply(self, c[0], "wary")
		var ok: bool = r.intent == c[1]
		hits += 1 if ok else 0
		total_ms += r.ms
		print("[%s] %-42s -> %-17s (want %-16s) %4d ms  %s%s" % ["PASS" if ok else "MISS", c[0], r.intent, c[1], r.ms, r.line,
			("  [" + r.why + "]") if r.why != "" else ""])
	var acc := float(hits) / CASES.size()
	print("accuracy %d/%d = %.0f%%, mean %d ms" % [hits, CASES.size(), acc * 100, total_ms / CASES.size()])
	quit(0 if acc >= MIN_ACCURACY else 1)
