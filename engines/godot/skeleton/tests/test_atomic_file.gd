# ---------------------------------------------------------------------------
# test_atomic_file.gd
# Purpose : AtomicFile, SaveStore and the Shell's settings file against the real filesystem, in a temporary
#           folder: the write is atomic, the previous good save becomes .bak, a crash between write and rename
#           leaves the old file intact, a corrupt save falls back to its backup, a save from a newer build is never
#           overwritten, settings.json missing or broken is recovered from its .tmp / .bak, and a corrupt
#           settings.json never replaces a good settings.json.bak.
# Usage   : python tools/dev.py test --filter test_atomic_file.gd
# Notes   : The crash is simulated by calling AtomicFile.write_tmp() and never commit(); the Windows cut-off save
#           by doing commit()'s steps by hand and stopping after the delete. Files go to
#           user://gut_atomic_<time>/ and are deleted afterwards. The Shell is passive under GUT; its
#           read_settings_file() and write_settings_file() take a path, so they run here as they do in the game.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

var _dir: String = ""


func before_each() -> void:
	_dir = OS.get_user_data_dir().path_join("gut_atomic_%d_%d" % [Time.get_ticks_usec(), randi()])
	DirAccess.make_dir_recursive_absolute(_dir)


func after_each() -> void:
	for f: String in DirAccess.get_files_at(_dir):
		DirAccess.remove_absolute(_dir.path_join(f))
	DirAccess.remove_absolute(_dir)


func _write_raw(path: String, text: String) -> void:
	var f: FileAccess = FileAccess.open(path, FileAccess.WRITE)
	f.store_string(text)
	f.close()


func test_write_creates_file_without_leftovers() -> void:
	var path: String = _dir.path_join("a.json")
	assert_eq(AtomicFile.write_text(path, "one"), OK)
	assert_eq(AtomicFile.read_text(path), "one")
	assert_false(FileAccess.file_exists(path + ".tmp"), "the tmp file is renamed away")
	assert_false(FileAccess.file_exists(path + ".bak"), "no backup on the first write")


func test_second_write_keeps_previous_as_bak() -> void:
	var path: String = _dir.path_join("a.json")
	AtomicFile.write_text(path, "one")
	assert_eq(AtomicFile.write_text(path, "two"), OK)
	assert_eq(AtomicFile.read_text(path), "two")
	assert_eq(AtomicFile.read_text(path + ".bak"), "one")


func test_crash_between_write_and_rename_leaves_old_file() -> void:
	var path: String = _dir.path_join("a.json")
	AtomicFile.write_text(path, "good")
	assert_eq(AtomicFile.write_tmp(path, "half-written new version"), OK)
	# ...the game dies here: commit() never runs
	assert_eq(AtomicFile.read_text(path), "good", "the real file is untouched")
	assert_eq(AtomicFile.write_text(path, "next"), OK, "a stale .tmp does not block the next write")
	assert_eq(AtomicFile.read_text(path), "next")


func test_missing_file_reads_as_null() -> void:
	assert_null(AtomicFile.read_text(_dir.path_join("nope.json")))


func test_save_slot_round_trip_and_backup() -> void:
	assert_eq(SaveStore.write_slot(_dir, 1, {"health": 5, "level": 2, "difficulty": "hard"}), OK)
	assert_eq(SaveStore.write_slot(_dir, 1, {"health": 4, "level": 3, "difficulty": "hard"}), OK)
	var r: Dictionary = SaveStore.read_slot(_dir, 1)
	assert_eq(r["source"], "primary")
	assert_eq(int(r["envelope"]["data"]["level"]), 3)
	var bak: Dictionary = SaveStore.parse(AtomicFile.read_text(SaveStore.slot_path(_dir, 1) + ".bak"))
	assert_eq(int(bak["envelope"]["data"]["level"]), 2, "the previous save is the backup")


func test_corrupt_save_falls_back_to_backup() -> void:
	SaveStore.write_slot(_dir, 2, {"health": 5, "level": 1, "difficulty": "normal"})
	SaveStore.write_slot(_dir, 2, {"health": 5, "level": 2, "difficulty": "normal"})
	_write_raw(SaveStore.slot_path(_dir, 2), "{\"format\": \"save\", \"vers") # torn write
	var r: Dictionary = SaveStore.read_slot(_dir, 2)
	assert_eq(r["source"], "backup")
	assert_eq(int(r["envelope"]["data"]["level"]), 1)


func test_corrupt_primary_does_not_replace_good_backup() -> void:
	SaveStore.write_slot(_dir, 3, {"health": 5, "level": 7, "difficulty": "normal"})
	SaveStore.write_slot(_dir, 3, {"health": 5, "level": 8, "difficulty": "normal"})
	_write_raw(SaveStore.slot_path(_dir, 3), "garbage")
	SaveStore.write_slot(_dir, 3, {"health": 5, "level": 9, "difficulty": "normal"})
	var bak: Dictionary = SaveStore.parse(AtomicFile.read_text(SaveStore.slot_path(_dir, 3) + ".bak"))
	assert_eq(int(bak["envelope"]["data"]["level"]), 7, "the good backup survives a corrupt primary")


func _settings(master: float) -> Dictionary:
	var s: Dictionary = GameSettings.defaults()
	(s["audio"] as Dictionary)["master"] = master
	return s


func _master(loaded: Dictionary) -> float:
	var s: Dictionary = loaded["settings"]
	var audio: Dictionary = s["audio"]
	return float(audio["master"])


func test_settings_cut_off_between_delete_and_rename_recover_the_new_text() -> void:
	var file: String = _dir.path_join("settings.json")
	assert_eq(Shell.write_settings_file(file, _settings(0.3)), OK)
	# commit() by hand, the way it runs on Windows, and the game dies after the delete
	assert_eq(AtomicFile.write_tmp(file, GameSettings.to_text(_settings(0.6))), OK)
	assert_eq(DirAccess.copy_absolute(file, file + ".bak"), OK)
	assert_eq(DirAccess.remove_absolute(file), OK)
	var r: Dictionary = Shell.read_settings_file(file)
	assert_eq(r["source"], "tmp", "settings.json missing: the finished .tmp is the newest choice")
	assert_eq(_master(r), 0.6)
	DirAccess.remove_absolute(file + ".tmp")
	r = Shell.read_settings_file(file)
	assert_eq(r["source"], "backup", "no .tmp: the previous version from .bak")
	assert_eq(_master(r), 0.3)
	DirAccess.remove_absolute(file + ".bak")
	assert_eq(Shell.read_settings_file(file)["source"], "none", "nothing on disk: defaults, the player chose nothing")


func test_settings_recovery_skips_copies_that_do_not_parse() -> void:
	var file: String = _dir.path_join("settings.json")
	_write_raw(file + ".tmp", "{\"audio\": {\"mas") # a save torn while writing the .tmp
	_write_raw(file + ".bak", GameSettings.to_text(_settings(0.4)))
	var r: Dictionary = Shell.read_settings_file(file)
	assert_eq(r["source"], "backup")
	assert_eq(_master(r), 0.4)
	_write_raw(file, "garbage")
	_write_raw(file + ".tmp", GameSettings.to_text(_settings(0.9)))
	r = Shell.read_settings_file(file)
	assert_eq(r["source"], "backup", "settings.json broken: .bak (last good) before an unfinished .tmp")
	assert_eq(_master(r), 0.4)


func test_corrupt_settings_do_not_replace_good_backup() -> void:
	var file: String = _dir.path_join("settings.json")
	Shell.write_settings_file(file, _settings(0.7))
	Shell.write_settings_file(file, _settings(0.8))
	assert_eq(_master(GameSettings.load_text(AtomicFile.read_text(file + ".bak"))), 0.7)
	_write_raw(file, "{\"version\": 1, \"aud") # torn
	assert_eq(Shell.write_settings_file(file, _settings(0.9)), OK)
	assert_eq(_master(GameSettings.load_text(AtomicFile.read_text(file))), 0.9)
	assert_eq(_master(GameSettings.load_text(AtomicFile.read_text(file + ".bak"))), 0.7,
			"the good backup survives a corrupt settings.json")


func test_newer_save_is_never_overwritten() -> void:
	var path: String = SaveStore.slot_path(_dir, 4)
	var newer: String = JSON.stringify({"format": "save", "version": SaveStore.SAVE_VERSION + 1, "data": {}})
	_write_raw(path, newer)
	assert_eq(SaveStore.write_slot(_dir, 4, {"health": 1}), ERR_ALREADY_EXISTS)
	assert_eq(AtomicFile.read_text(path), newer)
	assert_eq(SaveStore.read_slot(_dir, 4)["source"], "none")


func test_newer_backup_blocks_saving_too() -> void:
	# A newer build saved twice, then the primary was deleted: writing it would be fine, but the next save would
	# copy the old build's file over the newer .bak. Every port refuses the slot instead.
	var path: String = SaveStore.slot_path(_dir, 5)
	var newer: String = JSON.stringify({"format": "save", "version": SaveStore.SAVE_VERSION + 1, "data": {}})
	_write_raw(path + ".bak", newer)
	assert_eq(SaveStore.write_slot(_dir, 5, {"health": 1}), ERR_ALREADY_EXISTS)
	assert_false(FileAccess.file_exists(path), "no primary was written")
	assert_eq(AtomicFile.read_text(path + ".bak"), newer)

# {{FOOTER}}
