# ---------------------------------------------------------------------------
# test_golden_platform.gd
# Purpose : Checks the platform layer (scripts/core/platform_layer.gd) against every case in
#           data/golden/platform.json, then the Service the shell owns (the cached state file, the save hook,
#           nothing written without data/achievements.json) and the GodotSteam adapter against a fake binding.
# Usage   : python tools/dev.py test      (or --filter test_golden_platform.gd)
# Notes   : A case type this file does not know fails test_every_case_type_is_known. A step's calls are what the
#           rules sent to their backend during that step; "fail_store" is the null backend's hook (its next
#           store_stats fails). Expected values are only ever read from the JSON.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

const Golden = preload("res://tests/golden_util.gd")
const FILE: String = "platform.json"
const KNOWN_TYPES: PackedStringArray = ["platform_format", "achievements_load", "cloud_partition", "overlay",
		"platform_script", "platform_state_load", "null_backend"]
const SAMPLE: String = '{"stats": [{"id": "kills", "max": 100, "increment_only": true}], "achievements": [{"id": "first", "name": "First"}, {"id": "kills_10", "name": "Ten", "stat": "kills", "threshold": 10}]}'

var _file: Dictionary = {}
var _tol: float = 0.0


func before_all() -> void:
	_file = Golden.load_file(FILE)
	_tol = float(_file.get("tolerance", 0.0))


func _cases(kind: String) -> Array:
	var out: Array = []
	for c: Dictionary in _file.get("cases", []):
		if c["type"] == kind:
			out.append(c)
	assert_gt(out.size(), 0, "%s has no '%s' cases" % [FILE, kind])
	return out


func _check(actual: Variant, expected: Variant, where: String) -> void:
	var d: String = Golden.diff(actual, expected, _tol)
	assert_eq(d, "", "%s: %s" % [where, d])


func test_every_case_type_is_known() -> void:
	assert_false(_file.is_empty(), "res://data/golden/%s is missing or not JSON (it ships from the kit)" % FILE)
	for c: Dictionary in _file.get("cases", []):
		assert_true(KNOWN_TYPES.has(c["type"]), "unknown case type '%s' (%s): port it, then add it here" % [c["type"], c["name"]])


func test_format() -> void:
	for c: Dictionary in _cases("platform_format"):
		_check({"state_format": PlatformLayer.FORMAT, "state_file": PlatformLayer.STATE_FILE,
				"state_version": PlatformLayer.STATE_VERSION, "id_max": PlatformLayer.ID_MAX,
				"stat_types": Array(PlatformLayer.STAT_TYPES), "presence_max_keys": PlatformLayer.PRESENCE_MAX_KEYS,
				"presence_max_value_bytes": PlatformLayer.PRESENCE_MAX_VALUE_BYTES,
				"cloud_modes": Array(PlatformLayer.CLOUD_MODES),
				"cloud_local_names": Array(PlatformLayer.CLOUD_LOCAL_NAMES),
				"cloud_local_suffixes": Array(PlatformLayer.CLOUD_LOCAL_SUFFIXES),
				"cloud_local_dirs": Array(PlatformLayer.CLOUD_LOCAL_DIRS),
				"overlay_pause_screens": Array(PlatformLayer.OVERLAY_PAUSE_SCREENS),
				"type": c["type"], "name": c["name"]}, c, "format")


func test_achievements_load() -> void:
	for c: Dictionary in _cases("achievements_load"):
		for p: Array in c["points"]:
			var r: Dictionary = PlatformLayer.achievements_load(p[1])
			_check(r["defs"], p[2], "%s: defs" % p[0])
			_check(r["problems"], p[3], "%s: problems" % p[0])


func test_cloud_partition() -> void:
	for c: Dictionary in _cases("cloud_partition"):
		for p: Array in c["points"]:
			_check(PlatformLayer.cloud_partition(p[0]), p[1], "'%s'" % p[0])


func test_overlay() -> void:
	for c: Dictionary in _cases("overlay"):
		for p: Array in c["points"]:
			_check(PlatformLayer.overlay_action(p[0], p[1]), p[2], "%s" % [p])


func _step(p: PlatformLayer.Rules, nb: PlatformLayer.NullBackend, op: Array) -> Dictionary:
	match str(op[0]):
		"fail_store":
			nb.fail_stores += 1
			return {"out": null, "calls": []}
		"overlay":
			return {"out": PlatformLayer.overlay_action(op[1], op[2]), "calls": []}
		"unlock":
			return p.unlock(op[1])
		"set_stat":
			return p.set_stat(op[1], op[2])
		"add_stat":
			return p.add_stat(op[1], op[2])
		"flush":
			return p.flush()
		"set_presence":
			return p.set_presence(op[1], op[2])
		"clear_presence":
			return p.clear_presence()
		"saved":
			return p.saved(op[1])
		"connect":
			return p.connect_remote(op[1])
		"disconnect":
			return p.disconnect_remote()
		"reset_all":
			return p.reset_all()
	assert_true(false, "unknown step %s" % [op])
	return {}


func test_platform_script() -> void:
	for c: Dictionary in _cases("platform_script"):
		var nb: PlatformLayer.NullBackend = PlatformLayer.NullBackend.new()
		var p: PlatformLayer.Rules = PlatformLayer.Rules.new(c["defs"], nb, c["online"], c["cloud"])
		var i: int = 0
		for s: Dictionary in c["steps"]:
			var r: Dictionary = _step(p, nb, s["op"])
			var where: String = "%s step %d %s" % [c["name"], i, s["op"]]
			_check(r["out"], s["out"], where + ": out")
			_check(r["calls"], s["calls"], where + ": calls")
			_check(p.state(), s["state"], where + ": state")
			_check(p.presence_list(), s["presence"], where + ": presence")
			_check(p.online, s["online"], where + ": online")
			i += 1


func test_platform_state_load() -> void:
	for c: Dictionary in _cases("platform_state_load"):
		for p: Array in c["points"]:
			var r: Dictionary = PlatformLayer.state_load(c["defs"], p[1])
			_check(r["state"], p[2], "%s: state" % p[0])
			_check(r["problems"], p[3], "%s: problems" % p[0])


func test_null_backend() -> void:
	for c: Dictionary in _cases("null_backend"):
		var nb: PlatformLayer.NullBackend = PlatformLayer.NullBackend.new()
		var i: int = 0
		for s: Array in c["sends"]:
			var call: Array = s[0]
			var got: Variant = null
			if call.size() == 1 and call[0] == "fail_next_store":
				nb.fail_stores += 1
			else:
				got = nb.send(call)
			var keys: Array = nb.presence.keys()
			keys.sort()
			var pres: Array = []
			for k: Variant in keys:
				pres.append([k, nb.presence[k]])
			var where: String = "send %d %s" % [i, call]
			_check(got, s[1], where + ": ok")
			_check(nb.remote(), s[2], where + ": remote")
			_check(pres, s[3], where + ": presence")
			_check(nb.cloud, s[4], where + ": cloud")
			i += 1
		_check(nb.calls, c["calls"], "calls")


func _scratch() -> String:
	var dir: String = OS.get_user_data_dir().path_join("test_platform_%d" % Time.get_ticks_usec())
	DirAccess.make_dir_recursive_absolute(dir)
	return dir


func test_service_without_achievements_writes_nothing() -> void:
	var dir: String = _scratch()
	var ps: PlatformLayer.Service = PlatformLayer.Service.new(dir, null)
	assert_false(ps.active)
	assert_eq(ps.unlock("first"), "unknown")
	assert_eq(ps.flush(), "nothing")
	assert_eq(ps.saved("save_1.json"), "cloud")
	assert_eq(DirAccess.get_files_at(dir).size(), 0, "no file without data/achievements.json")


func test_service_caches_the_state_file() -> void:
	var dir: String = _scratch()
	var ps: PlatformLayer.Service = PlatformLayer.Service.new(dir, SAMPLE)
	assert_eq(ps.add_stat("kills", 12), "ok")
	assert_eq(ps.unlock("first"), "unlocked")
	var again: PlatformLayer.Service = PlatformLayer.Service.new(dir, SAMPLE)
	_check(again.rules.unlocked, ["kills_10", "first"], "reloaded unlocks")
	assert_eq(again.unlock("first"), "already")
	assert_false(FileAccess.file_exists(dir.path_join("platform_state.json.tmp")), "no .tmp left behind")


func test_save_store_calls_saved() -> void:
	var dir: String = _scratch()
	var ps: PlatformLayer.Service = PlatformLayer.Service.new(dir, SAMPLE, null, "api")
	var seen: Array = []
	var hook: Callable = func(name: String) -> void:
		seen.append(name)
		ps.saved(name)
	SaveStore.on_saved = hook
	var err: Error = SaveStore.write_slot(dir, 1, {"level": 1})
	SaveStore.on_saved = Callable()
	assert_eq(err, OK)
	_check(seen, ["save_1.json"], "saved names")
	_check((ps.backend as PlatformLayer.NullBackend).cloud, ["save_1.json"], "cloud writes")


# ---- the GodotSteam adapter against a fake binding (no GodotSteam, no Steam) --------------------------------

class FakeSteam:
	extends Object
	signal overlay_toggled(active: bool, user_initiated: bool, app_id: int)
	signal user_stats_stored(game: int, result: int)
	var log: Array = []
	var store_ok: bool = true
	var achieved: Dictionary = {"first": true}

	func setAchievement(id: String) -> bool:
		log.append(["setAchievement", id])
		return true

	func setStatInt(id: String, v: int) -> bool:
		log.append(["setStatInt", id, v])
		return true

	func setStatFloat(id: String, v: float) -> bool:
		log.append(["setStatFloat", id, v])
		return true

	func storeStats() -> bool:
		log.append(["storeStats"])
		return store_ok

	func getAchievement(id: String) -> Dictionary:
		return {"ret": true, "achieved": achieved.get(id, false)}

	func getStatInt(_id: String) -> int:
		return 4

	func getStatFloat(_id: String) -> float:
		return 0.0

	func setRichPresence(k: String, v: String) -> bool:
		log.append(["setRichPresence", k, v])
		return true

	func steamInitEx() -> Dictionary:
		return {"status": 0, "verbal": "Steamworks active"}

	func run_callbacks() -> void:
		log.append(["run_callbacks"])


func test_steam_adapter_maps_calls_and_a_refused_store() -> void:
	var fake: FakeSteam = FakeSteam.new()
	var defs: Dictionary = PlatformLayer.achievements_load(SAMPLE)["defs"]
	var steam: PlatformSteam = PlatformSteam.new(fake, defs, _scratch())
	_check(steam.remote(), {"unlocked": ["first"], "stats": {"kills": 4}}, "remote")
	var rules: PlatformLayer.Rules = PlatformLayer.Rules.new(defs, steam, true)
	assert_eq(rules.add_stat("kills", 12)["out"], "ok")
	_check(fake.log, [["setStatInt", "kills", 12], ["setAchievement", "kills_10"], ["storeStats"]],
			"the threshold unlock flushed at once")
	fake.log.clear()
	fake.store_ok = false
	assert_eq(rules.unlock("first")["out"], "unlocked")
	assert_false(rules.online, "a refused StoreStats takes the layer offline")
	assert_eq(rules.set_presence("status", "Menu")["out"], "ok")
	_check(fake.log, [["setAchievement", "first"], ["storeStats"]], "offline: presence waits")
	var seen: Array = []
	steam.overlay_toggled.connect(func(on: bool) -> void: seen.append(on))
	fake.overlay_toggled.emit(true, true, 480)
	_check(seen, [true], "the overlay signal reaches the shell")
	steam.update()
	_check(fake.log.back(), ["run_callbacks"], "update runs the callbacks")
	fake.free()


func test_steam_starts_without_achievements() -> void:
	# docs/PLATFORM.md section 6: an enabled adapter starts Steam whether or not data/achievements.json exists
	var fake: FakeSteam = FakeSteam.new()
	var none: Dictionary = PlatformLayer.achievements_load(null)["defs"]
	var steam: Object = PlatformSteam.make(none, _scratch(), fake)
	assert_not_null(steam, "no achievements file: Steam still starts (presence, overlay, cloud)")
	var ps: PlatformLayer.Service = PlatformLayer.Service.new(_scratch(), null, steam)
	assert_eq(ps.set_presence("status", "Menu"), "ok")
	_check(fake.log, [["setRichPresence", "status", "Menu"]], "presence reaches Steam without achievements")
	fake.free()


func test_a_late_user_stats_stored_failure_requeues_the_store() -> void:
	var fake: FakeSteam = FakeSteam.new()
	var dir: String = _scratch()
	var defs: Dictionary = PlatformLayer.achievements_load(SAMPLE)["defs"]
	var steam: PlatformSteam = PlatformSteam.make(defs, dir, fake)
	var ps: PlatformLayer.Service = PlatformLayer.Service.new(dir, SAMPLE, steam)
	assert_eq(ps.unlock("first"), "already", "the store reported first as achieved")
	assert_eq(ps.add_stat("kills", 12), "ok")   # the store had 4: 16, kills_10 unlocks and flushes
	assert_true(ps.rules.online)
	_check(ps.rules.pending_unlocks, [], "accepted by storeStats: nothing pending")
	fake.user_stats_stored.emit(480, 2) # k_EResultFail
	ps.update()
	assert_false(ps.rules.online, "a late failure takes the layer offline")
	_check(ps.rules.state()["pending"], {"stats": ["kills"], "unlocks": ["kills_10"], "cloud": []}, "the batch is queued again")
	fake.log.clear()
	ps.rules.connect_remote({})
	_check(fake.log, [["setStatInt", "kills", 16], ["setAchievement", "kills_10"], ["storeStats"]], "connect sends it again")
	fake.user_stats_stored.emit(480, 1) # this one succeeded
	ps.update()
	assert_true(ps.rules.online)
	fake.free()


func test_steam_adapter_is_off_without_godotsteam() -> void:
	if Engine.has_singleton("Steam"):
		pass_test("GodotSteam is installed here: make() may return a backend")
		return
	assert_null(PlatformSteam.make({}, _scratch()), "no GodotSteam: the null backend")
