# ---------------------------------------------------------------------------
# atomic_file.gd
# Purpose : Safer text files: write <file>.tmp, flush, keep <file>.bak of the previous version, then rename the
#           tmp over the target, so this code never leaves <file> half old and half new.
# Usage   : var err := AtomicFile.write_text(path, text)          # keeps <path>.bak of the old contents
#           var text: Variant = AtomicFile.read_text(path)        # String, or null when the file is missing
# Notes   : Paths are absolute OS paths or user:// paths. write_tmp() and commit() are the two halves of
#           write_text(), public so a test can stop between them (that is the crash case). A stale <file>.tmp from
#           a crash is simply overwritten by the next write.
#           What is guaranteed, exactly:
#           - <file> only changes by a rename, never by writing into it. If the game crashes, <file> holds the
#             old text or the new text, or (Windows, below) is missing; never a mix.
#           - flush() hands the text to the operating system. It is not an fsync: after a power cut or an OS
#             crash (not just the game crashing), the newest .tmp or <file> can come back empty or damaged.
#           - rename_absolute() is POSIX rename on Linux and macOS: one step that replaces the target. On Windows
#             Godot deletes an existing target first and then moves the .tmp in: two steps. A crash between them,
#             or a .tmp held open by another program (antivirus, backup or sync tools) so the move fails, leaves
#             no <file>, only <file>.tmp (the new text) and <file>.bak (the previous one, with keep_backup).
#             Checked on Godot 4.7.2, Windows: with the .tmp held open, rename fails and <file> is gone.
#           The readers cover those gaps: Shell.read_settings_file() takes <file>.tmp and then <file>.bak when
#           <file> is missing (.bak, then .tmp, when it does not parse), and SaveStore.read_slot() takes <file>.bak
#           when the save is missing or does not parse. Callers pass keep_backup = false when the current <file>
#           does not parse, so a damaged file never replaces a good .bak.
#
# Pseudocode:
#   write_tmp: open <path>.tmp for writing, store, flush (to the OS, not to the disk), close
#   commit:    keep_backup and <path> exists -> copy <path> to <path>.bak; rename <path>.tmp -> <path>
#              (Windows: delete <path>, then move; see Notes)
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
	f.flush() # to the OS before the rename makes it the real file (not an fsync: see Notes)
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
	return DirAccess.rename_absolute(path + TMP_SUFFIX, path) # Windows: two steps, <path> can be left missing


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
