# ---------------------------------------------------------------------------
# save_store.gd
# Purpose : Save games (engine-free logic plus crash-safe files): a versioned envelope, migrations from older
#           versions, falling back to the backup when the save is corrupt, and refusing saves from a newer build.
# Usage   : var r := SaveStore.read_slot(Shell.data_dir, 1)   # {"envelope": {...} or null, "source", "problems"}
#           if r.envelope: var data: Dictionary = r.envelope.data
#           SaveStore.write_slot(Shell.data_dir, 1, {"health": 3, "level": 2, "difficulty": "normal"})
# Notes   : Files are save_<slot>.json with save_<slot>.json.bak (the previous good save). The envelope is
#           {"format": "save", "version": SAVE_VERSION, "data": {...}}. Bump SAVE_VERSION when the data changes
#           shape and add a step to _migrate(); never edit an old step. The two steps here are the kit's example
#           chain (v2 renamed hp to health, v3 added difficulty): replace them with your game's own.
#           A save from a newer version is never loaded and never overwritten. Tested against data/golden/shell.json.
#
# Pseudocode:
#   load_texts(primary, backup): for each of primary, backup: parse -> envelope or a problem; first good one wins,
#     migrated step by step up to SAVE_VERSION; none -> null, source "none"
#   write_slot: primary on disk is "newer" -> refuse; old primary readable -> keep it as .bak; atomic write
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name SaveStore
extends RefCounted

const SAVE_VERSION: int = 3
const FORMAT: String = "save"
const FILE_PATTERN: String = "save_%s.json"


static func parse(text: Variant) -> Dictionary:
	# {"envelope": Dictionary or null, "problem": "" | "missing" | "unreadable" | "not a save" | "bad version" | "newer"}
	if typeof(text) == TYPE_NIL:
		return {"envelope": null, "problem": "missing"}
	var json: JSON = JSON.new()
	if json.parse(str(text)) != OK:
		return {"envelope": null, "problem": "unreadable"}
	var env: Variant = json.data
	if typeof(env) != TYPE_DICTIONARY:
		return {"envelope": null, "problem": "not a save"}
	var fmt: Variant = env.get("format")
	if typeof(fmt) != TYPE_STRING or fmt != FORMAT or typeof(env.get("data")) != TYPE_DICTIONARY:
		return {"envelope": null, "problem": "not a save"}
	var v: Variant = env.get("version")
	if not GameSettings.is_num(v) or float(v) != floorf(float(v)) or float(v) < 1.0:
		return {"envelope": null, "problem": "bad version"}
	if float(v) > SAVE_VERSION:
		return {"envelope": null, "problem": "newer"}
	env["version"] = int(v)
	return {"envelope": env, "problem": ""}


static func migrate(env: Dictionary) -> Dictionary:
	var out: Dictionary = env.duplicate(true)
	while int(out["version"]) < SAVE_VERSION:
		out["data"] = _migrate(int(out["version"]), out["data"])
		out["version"] = int(out["version"]) + 1
	return out


static func load_texts(primary: Variant, backup: Variant) -> Dictionary:
	var problems: PackedStringArray = []
	var sources: Array = [["primary", primary], ["backup", backup]]
	for pair: Array in sources:
		var parsed: Dictionary = parse(pair[1])
		if typeof(parsed["envelope"]) != TYPE_NIL:
			return {"envelope": migrate(parsed["envelope"]), "source": pair[0], "problems": problems}
		problems.append("%s: %s" % [pair[0], parsed["problem"]])
	return {"envelope": null, "source": "none", "problems": problems}


static func slot_path(dir: String, slot: Variant) -> String:
	return dir.path_join(FILE_PATTERN % str(slot))


static func read_slot(dir: String, slot: Variant) -> Dictionary:
	var path: String = slot_path(dir, slot)
	return load_texts(AtomicFile.read_text(path), AtomicFile.read_text(path + AtomicFile.BAK_SUFFIX))


static func write_slot(dir: String, slot: Variant, data: Dictionary) -> Error:
	var path: String = slot_path(dir, slot)
	var current: Dictionary = parse(AtomicFile.read_text(path))
	if current["problem"] == "newer":
		return ERR_ALREADY_EXISTS # made by a newer build of the game: leave it alone
	var env: Dictionary = {"format": FORMAT, "version": SAVE_VERSION, "data": data}
	# Only a readable save becomes the backup: a corrupt primary must not replace a good .bak
	var keep_backup: bool = typeof(current["envelope"]) != TYPE_NIL
	return AtomicFile.write_text(path, JSON.stringify(env, "\t") + "\n", keep_backup)


static func _migrate(from_version: int, data: Dictionary) -> Dictionary:
	match from_version:
		1: # v2 renamed hp to health
			if data.has("hp"):
				data["health"] = data["hp"]
				data.erase("hp")
		2: # v3 added the difficulty the game was started on
			if not data.has("difficulty"):
				data["difficulty"] = "normal"
	return data
