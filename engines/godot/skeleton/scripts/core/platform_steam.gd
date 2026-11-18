# ---------------------------------------------------------------------------
# platform_steam.gd
# Purpose : The Steam backend for the platform layer (#84, docs/PLATFORM.md) through GodotSteam (MIT, verify; the
#           GDExtension or the precompiled editor), used only when GodotSteam is installed and Steam answers.
#           Without it, PlatformSteam.make() returns null and the game runs the null backend exactly as before.
# Usage   : var backend: Object = PlatformSteam.make(defs, Shell.data_dir)   # null: no GodotSteam or no Steam
#           Shell.platform = PlatformLayer.Service.new(Shell.data_dir, text, backend)
# Notes   : Gated at run time: the script never names the Steam class (a project without GodotSteam must parse it);
#           it asks Engine.has_singleton("Steam") and calls the singleton by name. Method and signal names follow
#           GodotSteam 4.x's docs (steamInitEx, setAchievement, setStatInt / setStatFloat, storeStats,
#           indicateAchievementProgress, resetAllStats, setRichPresence, clearRichPresence, fileWrite,
#           run_callbacks, getAchievement, getStatInt / getStatFloat, the overlay_toggled and user_stats_stored
#           signals) (verify against the installed GodotSteam). Stats arrive with the SDK's init in Steamworks 1.61
#           and later (verify). A store that fails later (user_stats_stored with a result other than 1, k_EResultOK)
#           is handed to the layer by take_store_failure(): its stats and unlocks go back on the queue. The adapter
#           starts Steam whether or not data/achievements.json exists (presence, the overlay and cloud saves need it
#           too). The game needs steam_appid.txt (480 while testing) next to the dev build, never in a shipped depot
#           (docs/PLATFORM.md section 5).
#
# Pseudocode:
#   make: no Steam singleton -> null ; steamInitEx() not ok -> null ; else a backend over the singleton
#   send(call): the matching GodotSteam call; store_stats returns what storeStats() returned
#   remote: getAchievement / getStatInt / getStatFloat for every defined id
#   update: run_callbacks() ; overlay_toggled -> our overlay_toggled (the Shell connects it to the pause hook)
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): user_stats_stored failures reach the layer
#           (take_store_failure); make() takes a binding for tests; Steam starts without achievements too
# ---------------------------------------------------------------------------
class_name PlatformSteam
extends RefCounted

## The overlay opened (true) or closed; Shell connects it to the front end's pause hook.
signal overlay_toggled(active: bool)

const SINGLETON: String = "Steam"
const RESULT_OK: int = 1 # Steam's k_EResultOK

var name: String = "steam"
var _steam: Object
var _defs: Dictionary
var _data_dir: String
var _staged: Array = [] # set_stat / set_achievement calls since the last store_stats
var _inflight: Array = [] # the batches stores accepted, oldest first, until their UserStatsStored arrives
var _failed: Array = [] # batches whose UserStatsStored failed, for take_store_failure()


## The Steam backend, or null (no GodotSteam, or Steam not running or not owning the app). Started whether or not
## the game has achievements. binding: a GodotSteam-shaped object (tests); null asks for the Steam singleton.
static func make(defs: Dictionary, data_dir: String, binding: Object = null) -> Object:
	var steam: Object = binding
	if steam == null:
		if not Engine.has_singleton(SINGLETON):
			return null
		steam = Engine.get_singleton(SINGLETON)
	var init: Variant = steam.call("steamInitEx")
	var ok: bool = typeof(init) == TYPE_DICTIONARY and int((init as Dictionary).get("status", -1)) == 0
	if not ok:
		Log.warn("platform", "GodotSteam is installed but Steam did not start: %s (the null backend runs)" % [init])
		return null
	return PlatformSteam.new(steam, defs, data_dir)


func _init(steam: Object, defs: Dictionary, data_dir: String) -> void:
	_steam = steam
	_defs = defs
	_data_dir = data_dir
	if _steam.has_signal("overlay_toggled"):
		_steam.connect("overlay_toggled", _on_overlay)
	if _steam.has_signal("user_stats_stored"):
		_steam.connect("user_stats_stored", _on_stats_stored)


func available() -> bool:
	return true


func remote() -> Dictionary:
	var unlocked: Array = []
	for a: Dictionary in _defs.get("achievements", []):
		var r: Variant = _steam.call("getAchievement", a["id"])
		if typeof(r) == TYPE_DICTIONARY and (r as Dictionary).get("achieved", false):
			unlocked.append(a["id"])
	var stats: Dictionary = {}
	for s: Dictionary in _defs.get("stats", []):
		stats[s["id"]] = _steam.call("getStatInt" if s["type"] == "int" else "getStatFloat", s["id"])
	return {"unlocked": unlocked, "stats": stats}


func send(call: Array) -> bool:
	match str(call[0]):
		"set_achievement":
			_staged.append(call.duplicate())
			_steam.call("setAchievement", call[1])
		"set_stat":
			_staged.append(call.duplicate())
			if _stat_type(call[1]) == "int":
				_steam.call("setStatInt", call[1], int(call[2]))
			else:
				_steam.call("setStatFloat", call[1], float(call[2]))
		"store_stats":
			var ok: bool = bool(_steam.call("storeStats"))
			if ok:
				_inflight.append(_staged)
			_staged = []
			return ok
		"indicate_progress":
			_steam.call("indicateAchievementProgress", call[1], int(call[2]), int(call[3]))
		"reset_all_stats":
			_steam.call("resetAllStats", bool(call[1]))
		"set_presence":
			_steam.call("setRichPresence", call[1], call[2])
		"clear_presence":
			_steam.call("clearRichPresence")
		"cloud_write":
			var bytes: PackedByteArray = FileAccess.get_file_as_bytes(_data_dir.path_join(str(call[1])))
			_steam.call("fileWrite", call[1], bytes)
	return true


func update() -> void:
	_steam.call("run_callbacks")


func _stat_type(id: Variant) -> String:
	for s: Dictionary in _defs.get("stats", []):
		if s["id"] == id:
			return s["type"]
	return "float"


## The oldest store that failed after storeStats() accepted it (its set_stat / set_achievement calls), or null.
func take_store_failure() -> Variant:
	return _failed.pop_front() if not _failed.is_empty() else null


func _on_stats_stored(_game: int = 0, result: int = RESULT_OK) -> void:
	if _inflight.is_empty():
		return
	var batch: Array = _inflight.pop_front()
	if result != RESULT_OK:
		_failed.append(batch)


func _on_overlay(active: bool, _user_initiated: bool = false, _app_id: int = 0) -> void:
	overlay_toggled.emit(active)

# {{FOOTER}}
