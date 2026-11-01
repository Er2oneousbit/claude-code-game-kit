# ---------------------------------------------------------------------------
# golden_util.gd
# Purpose : Helpers for the golden-vector tests: load data/golden/<file>.json and compare JSON-like values
#           structurally (numbers within a tolerance, arrays in order, objects as key sets).
# Usage   : const Golden = preload("res://tests/golden_util.gd")
#           var file: Dictionary = Golden.load_file("juice.json")
#           var diff: String = Golden.diff(actual, expected, tolerance)   # "" when equal, else where they differ
# Notes   : Not a test file (no test_ prefix), so GUT does not run it on its own. Godot parses every JSON number
#           as a float, so an int 0 equals a float 0.0 here. The vectors come from tools/golden_vectors.py (the
#           reference); never copy expected values into test code.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends RefCounted

const GOLDEN_DIR: String = "res://data/golden"


static func load_file(name: String) -> Dictionary:
	var path: String = GOLDEN_DIR.path_join(name)
	if not FileAccess.file_exists(path):
		return {}
	var json: JSON = JSON.new()
	if json.parse(FileAccess.get_file_as_string(path)) != OK or typeof(json.data) != TYPE_DICTIONARY:
		return {}
	return json.data


static func is_num(v: Variant) -> bool:
	return typeof(v) == TYPE_INT or typeof(v) == TYPE_FLOAT


static func diff(actual: Variant, expected: Variant, tolerance: float, where: String = "$") -> String:
	if is_num(expected) or is_num(actual):
		if not (is_num(expected) and is_num(actual)):
			return "%s: expected %s, got %s" % [where, expected, actual]
		if absf(float(actual) - float(expected)) > tolerance:
			return "%s: expected %s, got %s (off by %s)" % [where, expected, actual,
					absf(float(actual) - float(expected))]
		return ""
	if typeof(actual) != typeof(expected):
		return "%s: expected %s (%s), got %s (%s)" % [where, expected, type_string(typeof(expected)), actual,
				type_string(typeof(actual))]
	match typeof(expected):
		TYPE_ARRAY:
			var a: Array = actual
			var e: Array = expected
			if a.size() != e.size():
				return "%s: expected %d items %s, got %d %s" % [where, e.size(), e, a.size(), a]
			for i: int in e.size():
				var d: String = diff(a[i], e[i], tolerance, "%s[%d]" % [where, i])
				if d != "":
					return d
			return ""
		TYPE_DICTIONARY:
			var ad: Dictionary = actual
			var ed: Dictionary = expected
			var ak: Array = ad.keys()
			var ek: Array = ed.keys()
			ak.sort()
			ek.sort()
			if ak != ek:
				return "%s: expected keys %s, got %s" % [where, ek, ak]
			for k: Variant in ek:
				var d: String = diff(ad[k], ed[k], tolerance, "%s.%s" % [where, k])
				if d != "":
					return d
			return ""
	if actual != expected:
		return "%s: expected %s, got %s" % [where, expected, actual]
	return ""
