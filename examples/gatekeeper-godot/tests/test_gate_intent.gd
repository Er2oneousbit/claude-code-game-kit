# ---------------------------------------------------------------------------
# test_gate_intent.gd
# Purpose : The model-output gate (SOP-15 step 6): the recorded labels and lines in
#           tests/fixtures/recorded.json (shared with the web version) are accepted or
#           rejected exactly as expected; the keyword fallback handles the obvious cases.
# Usage   : python tools/dev.py test   (GUT)
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

var data: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://tests/fixtures/recorded.json"))


func test_recorded_labels() -> void:
	assert_gt(data.labels.size(), 3, "fixtures loaded")
	for c: Dictionary in data.labels:
		assert_eq(GateIntent.parse_label(c.raw), "" if c.expect == null else c.expect, c.name)


func test_recorded_lines() -> void:
	assert_gt(data.lines.size(), 3, "fixtures loaded")
	for c: Dictionary in data.lines:
		assert_eq(GateIntent.parse_line(c.raw), "" if c.expect == null else c.expect, c.name)


func test_long_lines_are_cut() -> void:
	assert_lte(GateIntent.parse_line("A".repeat(1000)).length(), GateIntent.MAX_LINE)


func test_keyword_fallback() -> void:
	var cases := {
		"Hello there!": "greeting", "Captain Wren sent me.": "mentions_captain", "Here, take some gold.": "bribe",
		"Open it or I'll break your nose.": "threat", "That armor looks well kept.": "flattery",
		"Why is the gate closed?": "question", "Banana.": "other",
		"Hello captain, open up or I will hurt you": "threat",
	}
	for text: String in cases:
		assert_eq(GateIntent.keyword_intent(text), cases[text], text)
