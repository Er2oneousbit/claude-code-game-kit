# ---------------------------------------------------------------------------
# test_golden_access.gd
# Purpose : Checks the GDScript AudioAccess (slider gains per bus, never twice down one branch, clamping, cycles;
#           caption directions and arrows) against every case in data/golden/access.json, the kit's golden vectors.
# Usage   : python tools/dev.py test      (or --filter test_golden_access.gd)
# Notes   : One test per case type; each prints how many cases and values it checked. A case type this file does
#           not know fails test_every_case_type_is_known, so a new vector type cannot be skipped silently.
#           Expected values are only ever read from the JSON (tools/audio/wavesmith/access.py vectors --write writes
#           it), including the arrow characters. Directions are ints and compared exactly; gains within the file's
#           tolerance.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

const Golden = preload("res://tests/golden_util.gd")
const FILE: String = "access.json"
const KNOWN_TYPES: PackedStringArray = ["access_gains", "access_arrow"]

var _file: Dictionary = {}
var _tol: float = 0.0
var _checked: int = 0 # values compared in the current test


func before_all() -> void:
	_file = Golden.load_file(FILE)
	_tol = float(_file.get("tolerance", 0.0))


func _cases(kind: String) -> Array:
	var out: Array = []
	for c: Dictionary in _file.get("cases", []):
		if c["type"] == kind:
			out.append(c)
	return out


func _check(actual: Variant, expected: Variant, where: String, tolerance: float = _tol) -> void:
	_checked += 1
	var d: String = Golden.diff(actual, expected, tolerance)
	assert_eq(d, "", "%s: %s" % [where, d])


func _report(kind: String, cases: int) -> void:
	assert_gt(cases, 0, "%s has no '%s' cases" % [FILE, kind])
	gut.p("[golden] %s %s: %d case(s), %d value(s) checked" % [FILE, kind, cases, _checked])
	_checked = 0


func test_file_loaded() -> void:
	assert_false(_file.is_empty(), "res://data/golden/%s is missing or not JSON (it ships from the kit)" % FILE)
	assert_gt(_tol, 0.0, "tolerance missing")


func test_every_case_type_is_known() -> void:
	var seen: Dictionary = {}
	for c: Dictionary in _file.get("cases", []):
		seen[c["type"]] = true
		assert_true(KNOWN_TYPES.has(c["type"]), "unknown case type '%s' (%s): port it, then add it here" % [c["type"], c["name"]])
	for kind: String in KNOWN_TYPES:
		assert_true(seen.has(kind), "no '%s' cases in %s" % [kind, FILE])


func test_arrow_table_matches() -> void:
	# The eight arrows, in order, are part of the spec too
	_check(Array(AudioAccess.ARROWS), _file.get("arrows", []), "arrows")
	gut.p("[golden] %s arrows: %d value(s) checked" % [FILE, _checked])
	_checked = 0


func test_access_gains() -> void:
	var cases: Array = _cases("access_gains")
	for c: Dictionary in cases:
		for i: int in c["steps"].size():
			var step: Dictionary = c["steps"][i]
			_check(AudioAccess.user_bus_gains(step["buses"], step["sliders"]), step["expect"], "%s step %d" % [c["name"], i])
	_report("access_gains", cases.size())


func test_access_arrow() -> void:
	var cases: Array = _cases("access_arrow")
	for c: Dictionary in cases:
		for i: int in c["steps"].size():
			var step: Dictionary = c["steps"][i]
			var dx: float = step["dx"]
			var dy: float = step["dy"]
			var hw: float = step["half_w"]
			var hh: float = step["half_h"]
			var where: String = "%s step %d (dx %s, dy %s)" % [c["name"], i, dx, dy]
			_check(AudioAccess.caption_direction(dx, dy, hw, hh), step["dir"], where + " dir", 0.0)
			_check(AudioAccess.caption_arrow(dx, dy, hw, hh), step["arrow"], where + " arrow")
	_report("access_arrow", cases.size())
