# ---------------------------------------------------------------------------
# test_golden_dialogue.gd
# Purpose : Checks DialogueData.revealed (the subtitle typewriter) against every case in data/golden/dialogue.json:
#           a reveal list that fits the text is followed, one that does not (shorter or longer) is ignored and the
#           line types at 30 characters a second or fast enough to finish within its duration, code points counted.
# Usage   : python tools/dev.py test      (or --filter test_golden_dialogue.gd)
# Notes   : Expected values are only ever read from the JSON (tools/audio/wavesmith/dialogue.py vectors --write
#           writes it); the tolerance is 0 (whole characters). A case type this file does not know fails.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

const Golden = preload("res://tests/golden_util.gd")
const FILE: String = "dialogue.json"
const KNOWN_TYPES: PackedStringArray = ["reveal_count"]

var _file: Dictionary = {}


func before_all() -> void:
	_file = Golden.load_file(FILE)


func test_file_loaded() -> void:
	assert_false(_file.is_empty(), "res://data/golden/%s is missing or not JSON (it ships from the kit)" % FILE)
	assert_eq(float(_file.get("tolerance", -1.0)), 0.0, "tolerance must be 0 (whole characters)")


func test_every_case_type_is_known() -> void:
	var seen: Dictionary = {}
	for c: Dictionary in _file.get("cases", []):
		seen[c["type"]] = true
		assert_true(KNOWN_TYPES.has(c["type"]), "unknown case type '%s' (%s): port it, then add it here" % [c["type"], c["name"]])
	for kind: String in KNOWN_TYPES:
		assert_true(seen.has(kind), "no '%s' cases in %s" % [kind, FILE])


func test_reveal_count() -> void:
	var checked: int = 0
	for c: Dictionary in _file.get("cases", []):
		if c["type"] != "reveal_count":
			continue
		for i: int in c["steps"].size():
			var step: Dictionary = c["steps"][i]
			var got: int = DialogueData.revealed(step["line"], float(step["t"]))
			assert_eq(got, int(step["expect"]), "%s step %d (%s, t=%s)" % [c["name"], i, step["about"], step["t"]])
			checked += 1
	assert_gt(checked, 0, "%s has no reveal_count steps" % FILE)
	gut.p("[golden] %s reveal_count: %d value(s) checked" % [FILE, checked])
