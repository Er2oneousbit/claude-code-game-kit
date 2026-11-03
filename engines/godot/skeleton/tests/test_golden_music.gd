# ---------------------------------------------------------------------------
# test_golden_music.gd
# Purpose : Checks the GDScript MusicDirector (beat grid, loop wrap, next beat / bar / phrase / loop end, rule
#           lookup, fades, stingers, sync entry) against every case in data/golden/music.json, the kit's golden vectors.
# Usage   : python tools/dev.py test      (or --filter test_golden_music.gd)
# Notes   : One test per case type; each prints how many cases and values it checked. A case type this file does
#           not know fails test_every_case_type_is_known, so a new vector type cannot be skipped silently.
#           Expected values are only ever read from the JSON (tools/audio/wavesmith/music.py vectors --write writes
#           it). The tolerance is 0: every value is a whole number of samples, and the director must return ints
#           (a float that happens to compare equal would hide a missing floor). stinger and stinger_at may be null.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

const Golden = preload("res://tests/golden_util.gd")
const FILE: String = "music.json"
const KNOWN_TYPES: PackedStringArray = ["music_grid", "music_plan"]

var _file: Dictionary = {}
var _tol: float = 0.0
var _checked: int = 0 # values compared in the current test


func before_all() -> void:
	_file = Golden.load_file(FILE)
	_tol = float(_file.get("tolerance", -1.0))


func _cases(kind: String) -> Array:
	var out: Array = []
	for c: Dictionary in _file.get("cases", []):
		if c["type"] == kind:
			out.append(c)
	return out


func _check(actual: Variant, expected: Variant, where: String) -> void:
	_checked += 1
	var d: String = Golden.diff(actual, expected, _tol)
	assert_eq(d, "", "%s: %s" % [where, d])


func _check_ints(plan: Dictionary, where: String) -> void:
	# Samples are ints, never floats that merely look whole
	for key: String in plan:
		if Golden.is_num(plan[key]):
			assert_eq(typeof(plan[key]), TYPE_INT, "%s: %s is a %s, not an int" % [where, key,
					type_string(typeof(plan[key]))])


func _report(kind: String, cases: int) -> void:
	assert_gt(cases, 0, "%s has no '%s' cases" % [FILE, kind])
	gut.p("[golden] %s %s: %d case(s), %d value(s) checked" % [FILE, kind, cases, _checked])
	_checked = 0


func test_file_loaded() -> void:
	assert_false(_file.is_empty(), "res://data/golden/%s is missing or not JSON (it ships from the kit)" % FILE)
	assert_eq(_tol, 0.0, "tolerance must be 0 (whole samples)")


func test_every_case_type_is_known() -> void:
	var seen: Dictionary = {}
	for c: Dictionary in _file.get("cases", []):
		seen[c["type"]] = true
		assert_true(KNOWN_TYPES.has(c["type"]), "unknown case type '%s' (%s): port it, then add it here" % [c["type"], c["name"]])
	for kind: String in KNOWN_TYPES:
		assert_true(seen.has(kind), "no '%s' cases in %s" % [kind, FILE])


func test_music_grid() -> void:
	var cases: Array = _cases("music_grid")
	for c: Dictionary in cases:
		for i: int in c["steps"].size():
			var step: Dictionary = c["steps"][i]
			var got: int = MusicDirector.beat_sample(float(step["k"]), float(step["bpm"]), int(step["rate"]))
			_check(got, step["sample"], "%s step %d (beat %s at %s BPM, %s Hz)" % [c["name"], i, step["k"],
					step["bpm"], step["rate"]])
	_report("music_grid", cases.size())


func test_music_plan() -> void:
	var cases: Array = _cases("music_plan")
	for c: Dictionary in cases:
		for i: int in c["steps"].size():
			var step: Dictionary = c["steps"][i]
			var where: String = "%s step %d (%s -> %s at %s)" % [c["name"], i, step["from"], step["to"], step["now"]]
			var got: Dictionary = MusicDirector.plan(c["params"], step["from"], int(step["since"]), int(step["entry"]),
					step["to"], int(step["now"]))
			_check(got, step["expect"], where)
			_check_ints(got, where)
	_report("music_plan", cases.size())


func _params_with_rule(from: String, to: String, key: String, value: Variant) -> Dictionary:
	# The golden music_plan params with one field of the first from -> to rule changed (a deep copy)
	var params: Dictionary = _cases("music_plan")[0]["params"].duplicate(true)
	for r: Dictionary in params["transitions"]:
		if r["from"] == from and r["to"] == to:
			r[key] = value
			break
	return params


func test_unknown_quantize_is_an_error_and_an_empty_stinger_is_none() -> void:
	# music.py raises on a quantize it does not know (a typo must not mean "phrase") and plans "stinger": "" as
	# no stinger; the golden plans never reach either
	var typo: Dictionary = MusicDirector.plan(_params_with_rule("combat", "explore", "quantize", "bars"), "combat",
			5000, 0, "explore", 50000)
	assert_push_error("unknown quantize 'bars'")
	assert_eq(typo, {}, "quantize \"bars\" plans nothing")
	var empty: Dictionary = MusicDirector.plan(_params_with_rule("*", "waltz", "stinger", ""), "explore", 0, 0,
			"waltz", 70000)
	assert_eq(empty.get("stinger_at", "missing"), null, "\"stinger\": \"\" plays no stinger")
	assert_eq(empty.get("to_start_at"), empty.get("switch_at"), "the next track enters at the switch")

# {{FOOTER}}
