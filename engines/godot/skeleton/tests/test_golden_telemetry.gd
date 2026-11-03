# ---------------------------------------------------------------------------
# test_golden_telemetry.gd
# Purpose : Checks the GDScript Telemetry (telemetry.csv header, session id, time format, CSV quoting) against every
#           case in data/golden/telemetry.json, so every engine's telemetry.csv has the same columns.
# Usage   : python tools/dev.py test      (or --filter test_golden_telemetry.gd)
# Notes   : A case type this file does not know fails test_every_case_type_is_known, so a new vector type cannot be
#           skipped silently. Expected values are only ever read from the JSON (tools/golden_vectors.py writes it).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

const Golden = preload("res://tests/golden_util.gd")
const FILE: String = "telemetry.json"
const KNOWN_TYPES: PackedStringArray = ["telemetry_format", "telemetry_row"]

var _file: Dictionary = {}


func before_all() -> void:
	_file = Golden.load_file(FILE)


func _cases(kind: String) -> Array:
	var out: Array = []
	for c: Dictionary in _file.get("cases", []):
		if c["type"] == kind:
			out.append(c)
	return out


func test_file_loaded() -> void:
	assert_false(_file.is_empty(), "res://data/golden/%s is missing or not JSON (it ships from the kit)" % FILE)


func test_every_case_type_is_known() -> void:
	var seen: Dictionary = {}
	for c: Dictionary in _file.get("cases", []):
		seen[c["type"]] = true
		assert_true(KNOWN_TYPES.has(c["type"]), "unknown case type '%s' (%s): port it, then add it here" % [c["type"], c["name"]])
	for kind: String in KNOWN_TYPES:
		assert_true(seen.has(kind), "no '%s' cases in %s" % [kind, FILE])


func test_telemetry_format() -> void:
	var cases: Array = _cases("telemetry_format")
	assert_gt(cases.size(), 0, "no telemetry_format cases")
	for c: Dictionary in cases:
		assert_eq(Telemetry.HEADER, str(c["header"]), "header")
		assert_eq(Telemetry.SESSION_LENGTH, int(c["session_length"]), "session id length")
		var chars: String = str(c["session_chars"])
		for _i: int in 20:
			var sid: String = Telemetry.new_session()
			assert_eq(sid.length(), int(c["session_length"]), "session id '%s' length" % sid)
			for ch: String in sid:
				assert_true(chars.contains(ch), "session id '%s' holds '%s'" % [sid, ch])


func test_telemetry_row() -> void:
	var cases: Array = _cases("telemetry_row")
	assert_gt(cases.size(), 0, "no telemetry_row cases")
	var n: int = 0
	for c: Dictionary in cases:
		for p: Array in c["points"]:
			var got: String = Telemetry.row(Telemetry.time_string(float(p[0])), str(p[1]), str(p[2]), str(p[3]))
			assert_eq(got, str(p[4]), "%s point %d" % [c["name"], n])
			n += 1
	gut.p("[golden] %s telemetry_row: %d point(s) checked" % [FILE, n])

# {{FOOTER}}
