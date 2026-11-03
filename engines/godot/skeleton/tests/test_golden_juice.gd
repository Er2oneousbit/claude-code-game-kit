# ---------------------------------------------------------------------------
# test_golden_juice.gd
# Purpose : Checks the GDScript juice modules (Shake, Hitstop, Easing, FollowCamera, InputBuffer, CoyoteTimer,
#           Spring, FlashLimiter) against every case in data/golden/juice.json, the kit's golden vectors.
# Usage   : python tools/dev.py test      (or --filter test_golden_juice.gd)
# Notes   : One test per case type; each prints how many cases and values it checked. A case type this file does
#           not know fails test_every_case_type_is_known, so a new vector type cannot be skipped silently.
#           Expected values are only ever read from the JSON (tools/golden_vectors.py writes it).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

const Golden = preload("res://tests/golden_util.gd")
const FILE: String = "juice.json"
const KNOWN_TYPES: PackedStringArray = ["noise", "shake", "hitstop", "ease", "follow", "input_buffer", "coyote",
		"spring", "squash", "flash_limiter"]

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


func test_noise() -> void:
	var cases: Array = _cases("noise")
	for c: Dictionary in cases:
		for p: Array in c["points"]:
			_check(Shake.noise(int(p[0]), float(p[1]), int(p[2])), p[3], "%s %s" % [c["name"], p])
	_report("noise", cases.size())


func test_shake() -> void:
	var cases: Array = _cases("shake")
	for c: Dictionary in cases:
		var pr: Dictionary = c["params"]
		var s: Shake = Shake.new(pr["max_offset"], pr["max_angle"], pr["decay"], pr["frequency"], int(pr["seed"]))
		for i: int in c["steps"].size():
			var step: Dictionary = c["steps"][i]
			match step["call"]:
				"add_trauma":
					s.add_trauma(step["a"])
				"update":
					s.update(step["dt"], step["intensity"])
					_check({"x": s.offset_x, "y": s.offset_y, "angle": s.angle, "trauma": s.trauma}, step["expect"],
							"%s step %d" % [c["name"], i])
				_:
					_bad_call(c, step)
	_report("shake", cases.size())


func test_hitstop() -> void:
	var cases: Array = _cases("hitstop")
	for c: Dictionary in cases:
		var h: Hitstop = Hitstop.new(c["params"]["max_s"])
		for i: int in c["steps"].size():
			var step: Dictionary = c["steps"][i]
			match step["call"]:
				"hit":
					h.hit(step["duration"])
				"scaled_dt":
					var dt: float = h.scaled_dt(step["dt"])
					_check({"dt": dt, "remaining": h.remaining}, step["expect"], "%s step %d" % [c["name"], i])
				_:
					_bad_call(c, step)
	_report("hitstop", cases.size())


func test_ease() -> void:
	var cases: Array = _cases("ease")
	for c: Dictionary in cases:
		for p: Array in c["points"]:
			assert_true(Easing.has(p[0]), "unknown easing '%s'" % p[0])
			_check(Easing.apply(p[0], float(p[1])), p[2], "%s %s t=%s" % [c["name"], p[0], p[1]])
	_report("ease", cases.size())


func test_follow() -> void:
	var cases: Array = _cases("follow")
	for c: Dictionary in cases:
		var pr: Dictionary = c["params"]
		var f: FollowCamera = FollowCamera.new(pr["deadzone_w"], pr["deadzone_h"], pr["lookahead"], pr["smoothing"],
				pr["x"], pr["y"])
		for i: int in c["steps"].size():
			var step: Dictionary = c["steps"][i]
			if step["call"] != "update":
				_bad_call(c, step)
				continue
			f.update(step["dt"], step["tx"], step["ty"], step["vx"], step["vy"])
			_check({"x": f.x, "y": f.y}, step["expect"], "%s step %d" % [c["name"], i])
	_report("follow", cases.size())


func test_input_buffer() -> void:
	var cases: Array = _cases("input_buffer")
	for c: Dictionary in cases:
		var b: InputBuffer = InputBuffer.new(c["params"]["window_s"])
		for i: int in c["steps"].size():
			var step: Dictionary = c["steps"][i]
			match step["call"]:
				"press":
					b.press(step["action"])
				"update":
					b.update(step["dt"])
				"consume":
					_check({"result": b.consume(step["action"])}, step["expect"], "%s step %d" % [c["name"], i])
				_:
					_bad_call(c, step)
	_report("input_buffer", cases.size())


func test_coyote() -> void:
	var cases: Array = _cases("coyote")
	for c: Dictionary in cases:
		var t: CoyoteTimer = CoyoteTimer.new(c["params"]["window_s"])
		for i: int in c["steps"].size():
			var step: Dictionary = c["steps"][i]
			match step["call"]:
				"update":
					t.update(step["dt"], step["on_floor"])
				"consume":
					t.consume()
				"can_jump":
					_check({"result": t.can_jump()}, step["expect"], "%s step %d" % [c["name"], i])
				_:
					_bad_call(c, step)
	_report("coyote", cases.size())


func test_spring() -> void:
	var cases: Array = _cases("spring")
	for c: Dictionary in cases:
		var pr: Dictionary = c["params"]
		var s: Spring = Spring.new(pr["frequency"], pr["damping"])
		s.x = pr["x"]
		s.v = pr["v"]
		s.target = pr["target"]
		for i: int in c["steps"].size():
			var step: Dictionary = c["steps"][i]
			if step["call"] != "update":
				_bad_call(c, step)
				continue
			var x: float = s.update(step["dt"])
			_check({"x": x, "v": s.v}, step["expect"], "%s step %d" % [c["name"], i])
	_report("spring", cases.size())


func test_squash() -> void:
	var cases: Array = _cases("squash")
	for c: Dictionary in cases:
		for p: Array in c["points"]:
			var sc: PackedFloat64Array = Spring.squash_xy(float(p[0])) # 64-bit: the logic, not a Vector2 packing
			_check([sc[0], sc[1]], [p[1], p[2]], "%s a=%s" % [c["name"], p[0]])
	_report("squash", cases.size())


func test_flash_limiter() -> void:
	var cases: Array = _cases("flash_limiter")
	for c: Dictionary in cases:
		var pr: Dictionary = c["params"]
		var fl: FlashLimiter = FlashLimiter.new(int(pr["max_flashes"]), pr["window_s"])
		for i: int in c["steps"].size():
			var step: Dictionary = c["steps"][i]
			if step["call"] != "request":
				_bad_call(c, step)
				continue
			_check({"result": fl.request(step["now"])}, step["expect"], "%s step %d" % [c["name"], i])
	_report("flash_limiter", cases.size())

# {{FOOTER}}
