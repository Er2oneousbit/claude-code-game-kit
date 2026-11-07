# ---------------------------------------------------------------------------
# test_golden_shell.gd
# Purpose : Checks the GDScript shell logic (GameSettings, Bindings, SaveStore, I18n) against every case in
#           data/golden/shell.json, the kit's golden vectors.
# Usage   : python tools/dev.py test      (or --filter test_golden_shell.gd)
# Notes   : One test per case type; each prints how many cases and values it checked. A case type this file does
#           not know fails test_every_case_type_is_known. The plural cases use the key "apples", which is how
#           tools/golden_vectors.py builds them (the key is not stored in the JSON); expected values are only ever
#           read from the JSON.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

const Golden = preload("res://tests/golden_util.gd")
const FILE: String = "shell.json"
const KNOWN_TYPES: PackedStringArray = ["defaults", "settings_load", "rebind", "glyph_set", "glyph_name",
		"prompt_binding", "save_load", "tr", "plural", "pseudo", "narration"]
const PLURAL_KEY: String = "apples" # as in tools/golden_vectors.py build_shell()

var _file: Dictionary = {}
var _tol: float = 0.0
var _checked: int = 0


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


func test_file_loaded() -> void:
	assert_false(_file.is_empty(), "res://data/golden/%s is missing or not JSON (it ships from the kit)" % FILE)
	assert_eq(int(_file.get("save_version", -1)), SaveStore.SAVE_VERSION, "SaveStore.SAVE_VERSION differs from the vectors")


func test_every_case_type_is_known() -> void:
	var seen: Dictionary = {}
	for c: Dictionary in _file.get("cases", []):
		seen[c["type"]] = true
		assert_true(KNOWN_TYPES.has(c["type"]), "unknown case type '%s' (%s): port it, then add it here" % [c["type"], c["name"]])
	for kind: String in KNOWN_TYPES:
		assert_true(seen.has(kind), "no '%s' cases in %s" % [kind, FILE])


func test_defaults() -> void:
	var cases: Array = _cases("defaults")
	for c: Dictionary in cases:
		_check(GameSettings.defaults(), c["expect"], c["name"])
	_report("defaults", cases.size())


func test_settings_load() -> void:
	var cases: Array = _cases("settings_load")
	for c: Dictionary in cases:
		var r: Dictionary = GameSettings.load_text(c["input"])
		_check(r["settings"], c["expect"], "%s: settings" % c["name"])
		_check(r["problems"].size(), c["problems"], "%s: problem count %s" % [c["name"], r["problems"]])
		_check(GameSettings.effective_shake(r["settings"]), c["effective_shake"], "%s: effective_shake" % c["name"])
		_check(GameSettings.telemetry_allowed(r["settings"]), c["telemetry_allowed"], "%s: telemetry_allowed" % c["name"])
	_report("settings_load", cases.size())


func test_rebind() -> void:
	var cases: Array = _cases("rebind")
	for c: Dictionary in cases:
		var r: Dictionary = Bindings.rebind(c["bindings"], c["action"], int(c["slot"]), c["binding"])
		_check(r, c["expect"], c["name"])
	_report("rebind", cases.size())


func test_glyph_set() -> void:
	var cases: Array = _cases("glyph_set")
	for c: Dictionary in cases:
		for p: Array in c["points"]:
			_check(Bindings.glyph_set(p[0], p[1]), p[2], "%s %s" % [c["name"], p])
	_report("glyph_set", cases.size())


func test_narration() -> void:
	var cases: Array = _cases("narration")
	for c: Dictionary in cases:
		for p: Array in c["points"]:
			_check(Bindings.narration_line(p[0], p[1], p[2]), p[3], "%s %s" % [c["name"], p])
	_report("narration", cases.size())


func test_glyph_name() -> void:
	var cases: Array = _cases("glyph_name")
	for c: Dictionary in cases:
		for p: Array in c["points"]:
			_check(Bindings.glyph_name(p[0], p[1]), p[2], "%s %s" % [c["name"], p])
	_report("glyph_name", cases.size())


func test_prompt_binding() -> void:
	var cases: Array = _cases("prompt_binding")
	for c: Dictionary in cases:
		for p: Array in c["points"]:
			_check(Bindings.prompt_binding(c["bindings"], p[0], p[1]), p[2], "%s %s" % [c["name"], p])
	_report("prompt_binding", cases.size())


func test_save_load() -> void:
	var cases: Array = _cases("save_load")
	for c: Dictionary in cases:
		assert_eq(int(c["current_version"]), SaveStore.SAVE_VERSION, "%s: save version" % c["name"])
		var r: Dictionary = SaveStore.load_texts(c["primary"], c["backup"])
		var e: Dictionary = c["expect"]
		_check(r["envelope"], e["envelope"], "%s: envelope" % c["name"])
		_check(r["source"], e["source"], "%s: source" % c["name"])
		_check(r["problems"].size(), e["problems"], "%s: problem count %s" % [c["name"], r["problems"]])
	_report("save_load", cases.size())


func test_tr() -> void:
	var cases: Array = _cases("tr")
	for c: Dictionary in cases:
		for p: Array in c["points"]:
			_check(I18n.translate(c["tables"], p[0], p[1], p[2]), p[3], "%s %s" % [c["name"], p])
	_report("tr", cases.size())


func test_plural() -> void:
	var cases: Array = _cases("plural")
	for c: Dictionary in cases:
		for p: Array in c["points"]:
			_check(I18n.plural(p[0], float(p[1])), p[2], "%s category %s" % [c["name"], p])
			_check(I18n.translate_plural(c["tables"], p[0], PLURAL_KEY, float(p[1])), p[3], "%s text %s" % [c["name"], p])
	_report("plural", cases.size())


func test_pseudo() -> void:
	var cases: Array = _cases("pseudo")
	for c: Dictionary in cases:
		for p: Array in c["points"]:
			_check(I18n.pseudo(p[0]), p[1], "%s %s" % [c["name"], p])
	_report("pseudo", cases.size())

# {{FOOTER}}
