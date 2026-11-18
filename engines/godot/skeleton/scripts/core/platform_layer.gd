# ---------------------------------------------------------------------------
# platform_layer.gd
# Purpose : The engine-free platform layer (#84, docs/PLATFORM.md): achievements, stats, rich presence, the
#           overlay's pause hook and cloud saves, kept here and sent to a backend. Every game runs the null backend
#           (it records every call); the GodotSteam adapter (platform_steam.gd) replaces it when GodotSteam is
#           installed. Checked against data/golden/platform.json (every case).
# Usage   : Shell.platform.unlock("first_win") ; Shell.platform.add_stat("enemies_defeated", 1)
#           Shell.platform.flush()                         # at checkpoints (the front end flushes on pause and quit)
#           Shell.platform.set_presence("status", "In the crypt")
#           pure parts: PlatformLayer.achievements_load(text), cloud_partition(path), overlay_action(active, screen),
#           PlatformLayer.Rules.new(defs, backend), PlatformLayer.NullBackend.new(), state_load(defs, text)
# Notes   : A backend is any object with available() -> bool, remote() -> Dictionary, send(call: Array) -> bool
#           (false only for a store_stats the store refused) and update(). Godot parses every JSON number as a
#           float: whole numbers are judged by value, an int stat stores int(value). With no data/achievements.json
#           every call is "unknown" and nothing is written, so a game without achievements runs exactly as before.
#           The state file (<user-data>/platform_state.json) is a cache, written atomically only when it changed.
#
# Pseudocode:
#   Rules op -> update local state -> online: send calls to the backend one at a time, in order
#   flush: set_stat per pending stat (definition order), set_achievement per pending unlock, store_stats;
#          a false store_stats keeps everything and goes offline; then cloud_write per pending cloud file
#   Service: defs <- data/achievements.json ; state <- platform_state.json ; backend available ->
#          connect(backend.remote()) ; after every op: write the state file when it changed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): Rules.store_failed and Service.update take a store
#           that failed after it was accepted (Steam's UserStatsStored) back onto the queue
# ---------------------------------------------------------------------------
class_name PlatformLayer
extends RefCounted

# ---- Tunables (the same in every engine: data/golden/platform.json "names and limits") ------
const FORMAT: String = "platform_state"
const STATE_VERSION: int = 1
const STATE_FILE: String = "platform_state.json"
const ACHIEVEMENTS_FILE: String = "res://data/achievements.json"
const ID_MAX: int = 64
const STAT_TYPES: PackedStringArray = ["int", "float"]
const PRESENCE_MAX_KEYS: int = 30 # Steam's rich presence limits (verify)
const PRESENCE_MAX_VALUE_BYTES: int = 255
const CLOUD_MODES: PackedStringArray = ["auto", "api"]
const CLOUD_LOCAL_NAMES: PackedStringArray = ["settings.json", STATE_FILE, "telemetry.csv", "log_tail.txt"]
const CLOUD_LOCAL_SUFFIXES: PackedStringArray = [".tmp", ".log"]
const CLOUD_LOCAL_DIRS: PackedStringArray = ["logs", "crashes", "captures"]
const OVERLAY_PAUSE_SCREENS: PackedStringArray = ["play"]
## "auto" (Steam Auto-Cloud, no code, preferred) or "api" (the adapter writes cloud files itself).
const CLOUD_MODE: String = "auto"


# ---- small rules --------------------------------------------------------------

## An achievement, stat or presence key name: 1 to 64 ASCII characters, a letter first.
static func id_ok(v: Variant) -> bool:
	if typeof(v) != TYPE_STRING:
		return false
	var s: String = v
	if s.is_empty() or s.length() > ID_MAX:
		return false
	for i: int in s.length():
		var c: int = s.unicode_at(i)
		var letter: bool = (c >= 65 and c <= 90) or (c >= 97 and c <= 122)
		if i == 0 and not letter:
			return false
		if not (letter or (c >= 48 and c <= 57) or c == 95):
			return false
	return true


## A finite number (JSON true is never 1 here).
static func num_ok(v: Variant) -> bool:
	return (typeof(v) == TYPE_INT or typeof(v) == TYPE_FLOAT) and is_finite(float(v))


## Whole by value, never by type (Godot reads every JSON number as a float).
static func whole(v: Variant) -> bool:
	return num_ok(v) and floorf(float(v)) == float(v)


static func _ok_for(kind: String, v: Variant) -> bool:
	return whole(v) if kind == "int" else num_ok(v)


static func stat_value(sdef: Dictionary, v: Variant) -> Variant:
	return int(v) if sdef["type"] == "int" else float(v)


static func clamp_stat(sdef: Dictionary, v: Variant) -> Variant:
	var x: float = maxf(float(v), float(sdef["min"]))
	if sdef["max"] != null:
		x = minf(x, float(sdef["max"]))
	return stat_value(sdef, x)


static func stat_initial(sdef: Dictionary) -> Variant:
	return clamp_stat(sdef, 0)


static func _empty_defs() -> Dictionary:
	return {"version": STATE_VERSION, "stats": [], "achievements": []}


static func _parse(text: String) -> Array:
	# [ok, value]: JSON.parse_string cannot tell "null" from a parse error
	var json: JSON = JSON.new()
	if json.parse(text) != OK:
		return [false, null]
	return [true, json.data]


## data/achievements.json text (null or "" = no file) -> {"defs": {...}, "problems": n}.
static func achievements_load(text: Variant) -> Dictionary:
	if typeof(text) != TYPE_STRING or (text as String).is_empty():
		return {"defs": _empty_defs(), "problems": 0}
	var parsed: Array = _parse(text)
	if not parsed[0] or typeof(parsed[1]) != TYPE_DICTIONARY:
		return {"defs": _empty_defs(), "problems": 1}
	var raw: Dictionary = parsed[1]
	var problems: int = 0
	var stats: Array = []
	var achievements: Array = []
	var raw_stats: Variant = raw.get("stats", [])
	if typeof(raw_stats) != TYPE_ARRAY:
		raw_stats = []
		problems += 1
	var by_id: Dictionary = {}
	for s: Variant in raw_stats:
		var ok: bool = typeof(s) == TYPE_DICTIONARY and id_ok((s as Dictionary).get("id")) \
				and not by_id.has((s as Dictionary).get("id"))
		var kind: Variant = null
		var lo: Variant = null
		var hi: Variant = null
		var inc: Variant = null
		if ok:
			var d: Dictionary = s
			kind = d.get("type", "int")
			lo = d.get("min", 0)
			hi = d.get("max", null)
			inc = d.get("increment_only", false)
			ok = typeof(kind) == TYPE_STRING and STAT_TYPES.has(kind) and _ok_for(kind, lo) \
					and (hi == null or (_ok_for(kind, hi) and float(hi) >= float(lo))) and typeof(inc) == TYPE_BOOL
		if not ok:
			problems += 1
			continue
		var conv: Callable = func(x: Variant) -> Variant: return int(x) if kind == "int" else float(x)
		var sdef: Dictionary = {"id": (s as Dictionary)["id"], "type": kind, "min": conv.call(lo),
				"max": null if hi == null else conv.call(hi), "increment_only": inc}
		stats.append(sdef)
		by_id[sdef["id"]] = sdef
	var raw_ach: Variant = raw.get("achievements", [])
	if typeof(raw_ach) != TYPE_ARRAY:
		raw_ach = []
		problems += 1
	var seen: Dictionary = {}
	for a: Variant in raw_ach:
		var ok: bool = typeof(a) == TYPE_DICTIONARY
		var d: Dictionary = a if ok else {}
		ok = ok and id_ok(d.get("id")) and not seen.has(d.get("id")) and typeof(d.get("name")) == TYPE_STRING \
				and d.get("name") != "" and typeof(d.get("description", "")) == TYPE_STRING
		var stat: Variant = d.get("stat", null) if ok else null
		var threshold: Variant = d.get("threshold", null) if ok else null
		var every: Variant = d.get("progress_every", null) if ok else null
		var sdef: Dictionary = {}
		if ok and stat != null:
			if typeof(stat) == TYPE_STRING and by_id.has(stat):
				sdef = by_id[stat]
			var kind: String = sdef.get("type", "float")
			ok = not sdef.is_empty() and _ok_for(kind, threshold) and float(threshold) > float(stat_initial(sdef)) \
					and (sdef["max"] == null or float(threshold) <= float(sdef["max"])) \
					and (every == null or (_ok_for(kind, every) and float(every) > 0.0 \
					and float(every) < float(threshold)))
		elif ok:
			ok = threshold == null and every == null # a threshold without a stat is a mistake
		if not ok:
			problems += 1
			continue
		seen[d["id"]] = true
		achievements.append({"id": d["id"], "name": d["name"], "description": d.get("description", ""),
				"stat": stat, "threshold": null if stat == null else stat_value(sdef, threshold),
				"progress_every": null if every == null else stat_value(sdef, every)})
	return {"defs": {"version": STATE_VERSION, "stats": stats, "achievements": achievements}, "problems": problems}


## Which user-data file syncs: "cloud" or "local". ASCII-only folding (never a locale's lowercase).
static func cloud_partition(path: String) -> String:
	var folded: String = ""
	for i: int in path.length():
		var c: int = path.unicode_at(i)
		folded += char(c + 32) if c >= 65 and c <= 90 else char(c)
	var parts: PackedStringArray = []
	for p: String in folded.replace("\\", "/").split("/"):
		if p != "" and p != ".":
			parts.append(p)
	if parts.is_empty():
		return "local"
	var name: String = parts[parts.size() - 1]
	if (parts.size() > 1 and CLOUD_LOCAL_DIRS.has(parts[0])) or CLOUD_LOCAL_NAMES.has(name):
		return "local"
	for s: String in CLOUD_LOCAL_SUFFIXES:
		if name.ends_with(s):
			return "local"
	return "cloud"


## The store overlay opened (active) or closed over `screen`: "pause" opens the pause menu; closing never resumes.
static func overlay_action(active: bool, screen: String) -> String:
	return "pause" if active and OVERLAY_PAUSE_SCREENS.has(screen) else "none"


static func _sorted_keys(d: Dictionary) -> Array:
	var keys: Array = d.keys()
	keys.sort()
	return keys


# ---- the null backend -----------------------------------------------------------

## The backend every game runs by default: records every call and keeps what a store would hold.
class NullBackend:
	extends RefCounted
	var name: String = "null"
	var calls: Array = []
	var unlocked: Array = []
	var stats: Dictionary = {}
	var presence: Dictionary = {}
	var cloud: Array = []
	## Test hook: the next N store_stats fail (a failed store lands nothing).
	var fail_stores: int = 0
	var _staged_unlocks: Array = []
	var _staged_stats: Dictionary = {}

	func available() -> bool:
		return true

	func remote() -> Dictionary:
		return {"unlocked": unlocked.duplicate(), "stats": stats.duplicate()}

	func update() -> void:
		pass

	func send(call: Array) -> bool:
		calls.append(call.duplicate())
		var n: String = call[0]
		match n:
			"set_achievement":
				if not _staged_unlocks.has(call[1]):
					_staged_unlocks.append(call[1])
			"set_stat":
				_staged_stats[call[1]] = call[2]
			"store_stats":
				if fail_stores > 0:
					fail_stores -= 1
					return false
				for u: Variant in _staged_unlocks:
					if not unlocked.has(u):
						unlocked.append(u)
				stats.merge(_staged_stats, true)
				_staged_unlocks = []
				_staged_stats = {}
			"reset_all_stats":
				unlocked = []
				stats = {}
				_staged_unlocks = []
				_staged_stats = {}
			"set_presence":
				if call[2] == "":
					presence.erase(call[1])
				else:
					presence[call[1]] = call[2]
			"clear_presence":
				presence = {}
			"cloud_write":
				if not cloud.has(call[1]):
					cloud.append(call[1])
		return true


# ---- the rules ------------------------------------------------------------------

## PLATFORM.md section 3. Every operation returns {"out": status word, "calls": the calls it sent, in order}.
class Rules:
	extends RefCounted
	var defs: Dictionary
	var backend: Object
	var online: bool
	var cloud: String
	var stat_defs: Dictionary = {}
	var ach_defs: Dictionary = {}
	var unlocked: Array = []
	var stats: Dictionary = {}
	var pending_stats: Array = []
	var pending_unlocks: Array = []
	var pending_cloud: Array = []
	var presence: Dictionary = {}
	var _sent: Array = []

	func _init(p_defs: Dictionary, p_backend: Object = null, p_online: bool = false, p_cloud: String = "auto") -> void:
		defs = p_defs
		backend = p_backend if p_backend != null else PlatformLayer.NullBackend.new()
		online = p_online
		cloud = p_cloud
		for s: Dictionary in defs["stats"]:
			stat_defs[s["id"]] = s
		for a: Dictionary in defs["achievements"]:
			ach_defs[a["id"]] = a
		_reset_local()

	func _reset_local() -> void:
		unlocked = []
		stats = {}
		for s: Dictionary in defs["stats"]:
			stats[s["id"]] = PlatformLayer.stat_initial(s)
		pending_stats = []
		pending_unlocks = []
		pending_cloud = []

	## What the state file holds (and what the golden steps compare).
	func state() -> Dictionary:
		var ps: Array = []
		for s: Dictionary in defs["stats"]:
			if pending_stats.has(s["id"]):
				ps.append(s["id"])
		return {"format": PlatformLayer.FORMAT, "version": PlatformLayer.STATE_VERSION,
				"unlocked": unlocked.duplicate(), "stats": stats.duplicate(),
				"pending": {"stats": ps, "unlocks": pending_unlocks.duplicate(), "cloud": pending_cloud.duplicate()}}

	## Takes over a loaded state (state_load's), e.g. at start.
	func restore(st: Dictionary) -> void:
		unlocked = (st["unlocked"] as Array).duplicate()
		stats = (st["stats"] as Dictionary).duplicate()
		pending_stats = (st["pending"]["stats"] as Array).duplicate()
		pending_unlocks = (st["pending"]["unlocks"] as Array).duplicate()
		pending_cloud = (st["pending"]["cloud"] as Array).duplicate()

	## The presence map as [[key, value], ...], keys sorted.
	func presence_list() -> Array:
		var out: Array = []
		for k: Variant in PlatformLayer._sorted_keys(presence):
			out.append([k, presence[k]])
		return out

	func _send(call: Array) -> bool:
		_sent.append(call)
		return backend.send(call)

	func _done(out: Variant) -> Dictionary:
		var calls: Array = _sent
		_sent = []
		return {"out": out, "calls": calls}

	func _unlock_local(id: String) -> void:
		unlocked.append(id)
		pending_unlocks.append(id)

	func unlock(id: Variant) -> Dictionary:
		if not ach_defs.has(id):
			return _done("unknown")
		if unlocked.has(id):
			return _done("already")
		_unlock_local(id)
		if online:
			_flush()
		return _done("unlocked")

	func _check(sid: String, old: Variant, now: Variant, notify: bool) -> bool:
		var did: bool = false
		for a: Dictionary in defs["achievements"]:
			if a["stat"] != sid or unlocked.has(a["id"]):
				continue
			if float(now) >= float(a["threshold"]):
				_unlock_local(a["id"])
				did = true
			elif notify and online and a["progress_every"] != null:
				var step: float = float(a["progress_every"])
				if floorf(float(now) / step) > floorf(float(old) / step):
					_send(["indicate_progress", a["id"], now, a["threshold"]])
		return did

	## v may be anything a caller (or a JSON file) passes: a non-number is refused, never coerced.
	func set_stat(id: Variant, v: Variant) -> Dictionary:
		if not stat_defs.has(id):
			return _done("unknown")
		var s: Dictionary = stat_defs[id]
		if not PlatformLayer._ok_for(s["type"], v):
			return _done("refused")
		var c: Variant = PlatformLayer.clamp_stat(s, v)
		var old: Variant = stats[id]
		if s["increment_only"] and float(c) < float(old):
			return _done("refused")
		if float(c) == float(old):
			return _done("same")
		stats[id] = c
		if not pending_stats.has(id):
			pending_stats.append(id)
		if _check(id, old, c, true) and online:
			_flush()
		return _done("clamped" if float(c) != float(v) else "ok")

	func add_stat(id: Variant, d: Variant) -> Dictionary:
		if not stat_defs.has(id):
			return _done("unknown")
		var s: Dictionary = stat_defs[id]
		if not PlatformLayer._ok_for(s["type"], d):
			return _done("refused")
		return set_stat(id, float(stats[id]) + float(d))

	func _flush() -> String:
		if not online:
			return "offline"
		if pending_stats.is_empty() and pending_unlocks.is_empty() and pending_cloud.is_empty():
			return "nothing"
		if not (pending_stats.is_empty() and pending_unlocks.is_empty()):
			for s: Dictionary in defs["stats"]:
				if pending_stats.has(s["id"]):
					_send(["set_stat", s["id"], stats[s["id"]]])
			for id: Variant in pending_unlocks:
				_send(["set_achievement", id])
			if not _send(["store_stats"]):
				online = false # the store said no: keep everything, wait for connect()
				return "failed"
			pending_stats = []
			pending_unlocks = []
		for p: Variant in pending_cloud:
			_send(["cloud_write", p])
		pending_cloud = []
		return "sent"

	func flush() -> Dictionary:
		return _done(_flush())

	func set_presence(key: Variant, value: Variant) -> Dictionary:
		if not PlatformLayer.id_ok(key) or typeof(value) != TYPE_STRING \
				or (value as String).to_utf8_buffer().size() > PlatformLayer.PRESENCE_MAX_VALUE_BYTES:
			return _done("refused")
		if value == "":
			if not presence.has(key):
				return _done("same")
			presence.erase(key)
		else:
			if presence.has(key) and presence[key] == value:
				return _done("same")
			if not presence.has(key) and presence.size() >= PlatformLayer.PRESENCE_MAX_KEYS:
				return _done("refused")
			presence[key] = value
		if online:
			_send(["set_presence", key, value])
		return _done("ok")

	func clear_presence() -> Dictionary:
		if presence.is_empty():
			return _done("same")
		presence = {}
		if online:
			_send(["clear_presence"])
		return _done("ok")

	## The save code calls this after its atomic write succeeded; path is relative to the user-data folder.
	func saved(path: String) -> Dictionary:
		var part: String = PlatformLayer.cloud_partition(path)
		if part == "cloud" and cloud == "api":
			if online:
				_send(["cloud_write", path])
			elif not pending_cloud.has(path):
				pending_cloud.append(path)
		return _done(part)

	func connect_remote(remote: Dictionary) -> Dictionary:
		online = true
		var ru: Variant = remote.get("unlocked", [])
		if typeof(ru) == TYPE_ARRAY:
			for id: Variant in ru:
				if typeof(id) != TYPE_STRING:
					continue
				if ach_defs.has(id) and not unlocked.has(id):
					unlocked.append(id)
				pending_unlocks.erase(id)
		var rs: Variant = remote.get("stats", {})
		if typeof(rs) != TYPE_DICTIONARY:
			rs = {}
		for s: Dictionary in defs["stats"]:
			var sid: String = s["id"]
			var r0: Variant = (rs as Dictionary).get(sid)
			if not PlatformLayer._ok_for(s["type"], r0):
				continue
			var r: Variant = PlatformLayer.clamp_stat(s, r0)
			var old: Variant = stats[sid]
			var now: Variant
			if s["increment_only"]:
				if float(r) >= float(old) and pending_stats.has(sid):
					pending_stats.erase(sid)
				now = r if float(r) > float(old) else old
			else:
				now = old if pending_stats.has(sid) else r
			stats[sid] = now
			_check(sid, old, now, false)
		_flush()
		if online:
			for pair: Array in presence_list():
				_send(["set_presence", pair[0], pair[1]])
		return _done("online" if online else "failed")

	func disconnect_remote() -> Dictionary:
		online = false
		return _done("offline")

	## A store the backend accepted failed later (Steam's UserStatsStored callback): the same as a refused
	## store_stats. The batch's stats and unlocks are pending again and the layer is offline until connect_remote().
	## batch: the set_stat / set_achievement calls that store carried.
	func store_failed(batch: Array) -> Dictionary:
		online = false
		for call: Variant in batch:
			var c: Array = call
			if c[0] == "set_stat" and stat_defs.has(c[1]) and not pending_stats.has(c[1]):
				pending_stats.append(c[1])
			elif c[0] == "set_achievement" and unlocked.has(c[1]) and not pending_unlocks.has(c[1]):
				pending_unlocks.append(c[1])
		return _done("failed")

	## Testing only: refused offline (a reset is never queued).
	func reset_all() -> Dictionary:
		if not online:
			return _done("offline")
		_reset_local()
		_send(["reset_all_stats", true])
		return _done("reset")


## platform_state.json text (null or "" = no file) -> {"state": {...}, "problems": n}.
static func state_load(defs: Dictionary, text: Variant) -> Dictionary:
	var p: Rules = Rules.new(defs)
	if typeof(text) != TYPE_STRING or (text as String).is_empty():
		return {"state": p.state(), "problems": 0}
	var parsed: Array = _parse(text)
	if not parsed[0] or typeof(parsed[1]) != TYPE_DICTIONARY:
		return {"state": p.state(), "problems": 1}
	var raw: Dictionary = parsed[1]
	var ver: Variant = raw.get("version")
	if raw.get("format") != FORMAT or not num_ok(ver) or float(ver) != STATE_VERSION:
		return {"state": p.state(), "problems": 1}
	var problems: Array = [0]
	var items: Callable = func(v: Variant, kind: int) -> Variant:
		if typeof(v) == kind:
			return v
		if v != null:
			problems[0] += 1
		return [] if kind == TYPE_ARRAY else {}
	for id: Variant in items.call(raw.get("unlocked"), TYPE_ARRAY):
		if typeof(id) == TYPE_STRING and p.ach_defs.has(id) and not p.unlocked.has(id):
			p.unlocked.append(id)
		else:
			problems[0] += 1
	var st: Dictionary = items.call(raw.get("stats"), TYPE_DICTIONARY)
	for sid: Variant in st:
		var v: Variant = st[sid]
		if not p.stat_defs.has(sid) or not _ok_for(p.stat_defs[sid]["type"], v):
			problems[0] += 1
			continue
		p.stats[sid] = clamp_stat(p.stat_defs[sid], v)
	var pending: Dictionary = items.call(raw.get("pending"), TYPE_DICTIONARY)
	for sid: Variant in items.call(pending.get("stats"), TYPE_ARRAY):
		if typeof(sid) == TYPE_STRING and p.stat_defs.has(sid) and not p.pending_stats.has(sid):
			p.pending_stats.append(sid)
		else:
			problems[0] += 1
	for id: Variant in items.call(pending.get("unlocks"), TYPE_ARRAY):
		if typeof(id) == TYPE_STRING and p.unlocked.has(id) and not p.pending_unlocks.has(id):
			p.pending_unlocks.append(id)
		else:
			problems[0] += 1
	for path: Variant in items.call(pending.get("cloud"), TYPE_ARRAY):
		if typeof(path) == TYPE_STRING and cloud_partition(path) == "cloud" and not p.pending_cloud.has(path):
			p.pending_cloud.append(path)
		else:
			problems[0] += 1
	return {"state": p.state(), "problems": problems[0]}


# ---- the service the shell owns -----------------------------------------------------

## The rules, the backend and the cached local state file. Shell.platform is one.
class Service:
	extends RefCounted
	var rules: Rules
	var backend: Object
	## False without data/achievements.json (or with an empty one): nothing is ever written.
	var active: bool = false
	var _dir: String
	var _last: String = ""

	func _init(dir: String, achievements_text: Variant, p_backend: Object = null,
			cloud: String = PlatformLayer.CLOUD_MODE) -> void:
		_dir = dir
		backend = p_backend if p_backend != null else PlatformLayer.NullBackend.new()
		var loaded: Dictionary = PlatformLayer.achievements_load(achievements_text)
		if int(loaded["problems"]) > 0:
			Log.warn("platform", "data/achievements.json: %d problem(s), those entries were dropped"
					% loaded["problems"])
		var defs: Dictionary = loaded["defs"]
		active = not ((defs["stats"] as Array).is_empty() and (defs["achievements"] as Array).is_empty())
		rules = PlatformLayer.Rules.new(defs, backend, false, cloud)
		if active:
			var text: Variant = AtomicFile.read_text(_path())
			var st: Dictionary = PlatformLayer.state_load(defs, text)
			if int(st["problems"]) > 0:
				Log.warn("platform", "%s: %d problem(s), the store's copy wins" % [PlatformLayer.STATE_FILE,
						st["problems"]])
			rules.restore(st["state"])
			_last = str(text) if typeof(text) == TYPE_STRING else ""
		if backend.available():
			rules.connect_remote(backend.remote())
		_persist()

	func _path() -> String:
		return _dir.path_join(PlatformLayer.STATE_FILE)

	func _persist() -> void:
		if not active:
			return
		var text: String = JSON.stringify(rules.state(), "\t") + "\n"
		if text == _last:
			return
		var err: Error = AtomicFile.write_text(_path(), text, false)
		if err == OK:
			_last = text
		else:
			Log.warn("platform", "%s not written (%s)" % [PlatformLayer.STATE_FILE, error_string(err)])

	func _after(r: Dictionary) -> String:
		_persist()
		return str(r["out"])

	func unlock(id: String) -> String:
		return _after(rules.unlock(id))

	func set_stat(id: String, v: float) -> String:
		return _after(rules.set_stat(id, v))

	func add_stat(id: String, d: float) -> String:
		return _after(rules.add_stat(id, d))

	## At checkpoints: level end, pause, quit.
	func flush() -> String:
		return _after(rules.flush())

	func set_presence(key: String, value: String) -> String:
		return _after(rules.set_presence(key, value))

	func clear_presence() -> String:
		return _after(rules.clear_presence())

	## After an atomic save: its cloud partition (and, in api mode, the cloud write or its queue).
	func saved(path: String) -> String:
		return _after(rules.saved(path))

	## The store overlay opened or closed over `screen`: "pause" means open the pause menu.
	func overlay(is_active: bool, screen: String) -> String:
		return PlatformLayer.overlay_action(is_active, screen)

	## Each frame: the backend's callbacks (the null backend does nothing); a store that failed late (a backend with
	## take_store_failure(), Steam's UserStatsStored) goes back on the queue and the layer goes offline.
	func update() -> void:
		backend.update()
		if backend.has_method("take_store_failure"):
			var batch: Variant = backend.call("take_store_failure")
			while batch != null:
				Log.warn("platform", "a store the backend accepted failed later: kept for the next connect")
				_after(rules.store_failed(batch))
				batch = backend.call("take_store_failure")

# {{FOOTER}}
