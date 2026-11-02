# ---------------------------------------------------------------------------
# test_eval_guard.gd
# Purpose : GUT tests for the live eval's scoring (tools/eval_guard.gd): only a label from the model counts as a
#           hit, so a run on the keyword fallback scores zero instead of passing.
# Usage   : python tools/dev.py test      (needs the GUT addon in addons/gut/)
# Notes   : The eval itself needs the plugin and model; only its pure scoring is tested here.
# Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
# ---------------------------------------------------------------------------
extends GutTest

const Eval := preload("res://tools/eval_guard.gd")


func test_only_labels_from_the_model_count_as_hits() -> void:
	var t: Dictionary = Eval.tally([
		{"want": "greeting", "intent": "greeting", "source": "model"},
		{"want": "bribe", "intent": "other", "source": "model"},
		{"want": "threat", "intent": "threat", "source": "fallback"},   # right, but the keywords said so
	])
	assert_eq(t, {"hits": 1, "misses": 1, "fallbacks": 1})


func test_a_run_on_the_scripted_guard_scores_zero() -> void:
	var rows: Array = []
	for c: Array in Eval.CASES:
		rows.append({"want": c[1], "intent": c[1], "source": "fallback"})
	var t: Dictionary = Eval.tally(rows)
	assert_eq(t.hits, 0, "every label right, none from the model: the eval cannot pass on the fallback")
	assert_eq(t.fallbacks, Eval.CASES.size())


func test_marks() -> void:
	assert_eq(Eval.mark("greeting", "greeting", "model"), "PASS")
	assert_eq(Eval.mark("greeting", "other", "model"), "MISS")
	assert_eq(Eval.mark("greeting", "greeting", "fallback"), "FALL")
