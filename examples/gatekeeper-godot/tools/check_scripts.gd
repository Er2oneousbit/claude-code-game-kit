# ---------------------------------------------------------------------------
# check_scripts.gd
# Purpose : Compile-check GDScript files inside the real project, so autoloads
#           (Log, ...) and global class names resolve. Used by `dev.py check`.
# Usage   : godot --headless --path . -s res://tools/check_scripts.gd -- res://a.gd res://b.gd
#           Prints CHECK_FAIL <path> per broken script, then CHECK_DONE <n> <failed>.
#           Exit code 1 if any script failed, else 0.
# Notes   : Replaces `--check-only --script`, which runs outside the project's
#           autoloads and reports "Identifier not found" for every autoload use
#           (seen on Godot 4.7.2). Parse and type errors still print SCRIPT ERROR.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends SceneTree


func _initialize() -> void:
	var paths: PackedStringArray = OS.get_cmdline_user_args()
	var own_path: String = get_script().resource_path
	var failed: int = 0
	for path in paths:
		# Recompiling the running script crashes Godot 4.7.2 (signal 11), so never check ourselves
		if path == own_path:
			continue
		# CACHE_MODE_IGNORE: always recompile, never trust a cached copy
		var res: Resource = ResourceLoader.load(path, "", ResourceLoader.CACHE_MODE_IGNORE)
		var script: Script = res as Script
		if script == null or not script.can_instantiate():
			failed += 1
			print("CHECK_FAIL ", path)
	print("CHECK_DONE ", paths.size(), " ", failed)
	quit(1 if failed > 0 else 0)
