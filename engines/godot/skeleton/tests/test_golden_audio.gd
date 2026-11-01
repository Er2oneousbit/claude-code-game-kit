# ---------------------------------------------------------------------------
# test_golden_audio.gd
# Purpose : Checks the GDScript AudioDirector (variant picks, pitch and volume draws, voice cap and stealing,
#           cooldowns, ducking envelopes) against every case in data/golden/audio.json, the kit's golden vectors.
# Usage   : python tools/dev.py test      (or --filter test_golden_audio.gd)
# Notes   : One test per case type; each prints how many cases and values it checked. A case type this file does
#           not know fails test_every_case_type_is_known, so a new vector type cannot be skipped silently.
#           Expected values are only ever read from the JSON (tools/audio/audio_events.py vectors --write writes
#           it). "stolen" is null when nothing was stolen; the comparison treats null as equal to null only.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

const Golden = preload("res://tests/golden_util.gd")
const FILE: String = "audio.json"
const KNOWN_TYPES: PackedStringArray = ["audio_director"]

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


func _check(actual: Variant, expected: Variant, where: String) -> void:
	_checked += 1
	var d: String = Golden.diff(actual, expected, _tol)
	assert_eq(d, "", "%s: %s" % [where, d])


func _report(kind: String, cases: int) -> void:
	assert_gt(cases, 0, "%s has no '%s' cases" % [FILE, kind])
	gut.p("[golden] %s %s: %d case(s), %d value(s) checked" % [FILE, kind, cases, _checked])
	_checked = 0


func _bad_call(c: Dictionary, step: Dictionary) -> void:
	fail_test("%s '%s': unknown step call '%s'" % [c["type"], c["name"], step.get("call")])


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


func test_audio_director() -> void:
	var cases: Array = _cases("audio_director")
	for c: Dictionary in cases:
		var d: AudioDirector = AudioDirector.new(c["params"]) # a fresh director per case: state never leaks
		for i: int in c["steps"].size():
			var step: Dictionary = c["steps"][i]
			match step["call"]:
				"play":
					_check(d.play(step["event"], float(step["t_ms"])), step["expect"], "%s step %d" % [c["name"], i])
				"duck":
					_check(d.duck(float(step["t_ms"])), step["expect"], "%s step %d" % [c["name"], i])
				_:
					_bad_call(c, step)
	_report("audio_director", cases.size())

# {{FOOTER}}
