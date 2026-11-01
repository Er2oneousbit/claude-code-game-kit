# ---------------------------------------------------------------------------
# test_atomic_file.gd
# Purpose : AtomicFile and SaveStore against the real filesystem, in a temporary folder: the write is atomic, the
#           previous good save becomes .bak, a crash between write and rename leaves the old file intact, a corrupt
#           save falls back to its backup, and a save from a newer build is never overwritten.
# Usage   : python tools/dev.py test --filter test_atomic_file.gd
# Notes   : The crash is simulated by calling AtomicFile.write_tmp() and never commit(). Files go to
#           user://gut_atomic_<time>/ and are deleted afterwards.
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


func test_newer_save_is_never_overwritten() -> void:
	var path: String = SaveStore.slot_path(_dir, 4)
	var newer: String = JSON.stringify({"format": "save", "version": SaveStore.SAVE_VERSION + 1, "data": {}})
	_write_raw(path, newer)
	assert_eq(SaveStore.write_slot(_dir, 4, {"health": 1}), ERR_ALREADY_EXISTS)
	assert_eq(AtomicFile.read_text(path), newer)
	assert_eq(SaveStore.read_slot(_dir, 4)["source"], "none")

# {{FOOTER}}
