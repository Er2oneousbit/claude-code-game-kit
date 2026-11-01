# ---------------------------------------------------------------------------
# atomic_file.gd
# Purpose : Crash-safe text files: write <file>.tmp, flush, keep <file>.bak of the previous version, then rename
#           the tmp over the target. A crash or power cut at any point leaves either the old file or the new one,
#           never half of each.
# Usage   : var err := AtomicFile.write_text(path, text)          # keeps <path>.bak of the old contents
#           var text: Variant = AtomicFile.read_text(path)        # String, or null when the file is missing
# Notes   : Paths are absolute OS paths or user:// paths. write_tmp() and commit() are the two halves of
#           write_text(), public so a test can stop between them (that is the crash case). A stale <file>.tmp from
#           a crash is simply overwritten by the next write. Renaming over an existing file replaces it on Windows,
#           Linux and macOS (checked on Godot 4.7.2, Windows).
#
# Pseudocode:
#   write_tmp: open <path>.tmp for writing, store, flush, close
#   commit:    keep_backup and <path> exists -> copy <path> to <path>.bak; rename <path>.tmp -> <path>
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name AtomicFile
extends RefCounted

const TMP_SUFFIX: String = ".tmp"
const BAK_SUFFIX: String = ".bak"


static func write_text(path: String, text: String, keep_backup: bool = true) -> Error:
	var err: Error = write_tmp(path, text)
	if err != OK:
		return err
	return commit(path, keep_backup)


static func write_tmp(path: String, text: String) -> Error:
	var dir: String = path.get_base_dir()
	if dir != "" and not DirAccess.dir_exists_absolute(dir):
		var made: Error = DirAccess.make_dir_recursive_absolute(dir)
		if made != OK:
			return made
	var f: FileAccess = FileAccess.open(path + TMP_SUFFIX, FileAccess.WRITE)
	if f == null:
		return FileAccess.get_open_error()
	f.store_string(text)
	f.flush() # on disk before the rename makes it the real file
	var write_err: Error = f.get_error()
	f.close()
	return write_err


static func commit(path: String, keep_backup: bool = true) -> Error:
	if not FileAccess.file_exists(path + TMP_SUFFIX):
		return ERR_FILE_NOT_FOUND
	if keep_backup and FileAccess.file_exists(path):
		var copied: Error = DirAccess.copy_absolute(path, path + BAK_SUFFIX)
		if copied != OK:
			return copied
	return DirAccess.rename_absolute(path + TMP_SUFFIX, path)


static func read_text(path: String) -> Variant:
	if not FileAccess.file_exists(path):
		return null
	var f: FileAccess = FileAccess.open(path, FileAccess.READ)
	if f == null:
		return null
	var text: String = f.get_as_text()
	f.close()
	return text

# {{FOOTER}}
