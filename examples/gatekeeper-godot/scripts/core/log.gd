# ---------------------------------------------------------------------------
# log.gd  (autoload name: Log)
# Purpose : Tiny channel-based logger so output is greppable and toggleable, plus the game's log file
#           (logs/game.log in the data folder) and an in-memory tail for crash files and bug reports.
# Usage   : Log.info("physics", "landed"), Log.warn(...), Log.error(...), Log.debug(...)
#           Enable channels in debug builds: Log.enable_channel("ai")
#           Verbose debug output: run the game with `-- --debug` (see dev.py run --debug).
#           Log.tail(50) -> the last 50 lines; Log.raw("MARKER text") prints a line exactly as given.
# Notes   : Errors also call push_error so the editor debugger shows them.
#           dev.py smoke fails if output contains "ERROR". That is intentional.
#           Autoload name "Log" must NOT also be a class_name (global name clash).
#           The Shell autoload calls open_file() at boot; lines logged before that are kept and written then.
#           Each launch rotates the old logs: game.log -> game.1.log ... game.5.log (KEEP_LOGS), oldest dropped.
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# Updated : 2026-11-01 with Claude (Opus 5.5, claude-opus-5-5): log file with rotation, tail for crash files
# ---------------------------------------------------------------------------
extends Node

const KEEP_LOGS: int = 5 # rotated logs kept next to game.log
const TAIL_LINES: int = 200 # lines remembered for crash files and bug reports
const PENDING_MAX: int = 500 # lines kept before open_file() (a runaway loop must not eat memory)

# Channels that print debug-level output. "core" is on by default.
var _debug_channels: Dictionary = {"core": true}
# Master switch for debug-level logs, set by the --debug user arg.
var debug_enabled: bool = false
var _file: FileAccess = null
var _pending: PackedStringArray = []
var _tail: PackedStringArray = []


func _ready() -> void:
	# User args come after "--" on the command line.
	debug_enabled = OS.get_cmdline_user_args().has("--debug")
	if debug_enabled:
		info("core", "debug logging enabled")


func enable_channel(channel: String) -> void:
	_debug_channels[channel] = true


func debug(channel: String, msg: String) -> void:
	# Debug lines only print when the master switch AND the channel are on.
	if debug_enabled and _debug_channels.get(channel, false):
		_emit("[DEBUG][%s] %s" % [channel, msg])


func info(channel: String, msg: String) -> void:
	_emit("[INFO][%s] %s" % [channel, msg])


func warn(channel: String, msg: String) -> void:
	push_warning("[%s] %s" % [channel, msg])
	_emit("[WARN][%s] %s" % [channel, msg])


func error(channel: String, msg: String) -> void:
	push_error("[%s] %s" % [channel, msg])
	_emit("[ERROR][%s] %s" % [channel, msg])


func raw(line: String) -> void:
	# A line printed exactly as given (smoke markers like SETTINGS_WRITTEN), also kept in the file and tail
	_emit(line)


func open_file(path: String, header: String) -> bool:
	# Rotate old logs, start a new file with header as the first line, write what was logged so far
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	_rotate(path)
	_file = FileAccess.open(path, FileAccess.WRITE)
	if _file == null:
		return false
	_file.store_line(header)
	for line: String in _pending:
		_file.store_line(line)
	_pending.clear()
	_file.flush()
	return true


func tail(lines: int = 50) -> PackedStringArray:
	return _tail.slice(maxi(0, _tail.size() - lines))


func _emit(line: String) -> void:
	print(line)
	_tail.append(line)
	if _tail.size() > TAIL_LINES:
		_tail = _tail.slice(_tail.size() - TAIL_LINES)
	if _file != null:
		_file.store_line(line)
		_file.flush() # a crash must not lose the last lines
	elif _pending.size() < PENDING_MAX:
		_pending.append(line)


func _rotate(path: String) -> void:
	# game.log -> game.1.log, game.1.log -> game.2.log, ... the oldest beyond KEEP_LOGS is deleted
	var stem: String = path.get_basename()
	var ext: String = "." + path.get_extension()
	var oldest: String = "%s.%d%s" % [stem, KEEP_LOGS, ext]
	if FileAccess.file_exists(oldest):
		DirAccess.remove_absolute(oldest)
	for i: int in range(KEEP_LOGS - 1, 0, -1):
		var src: String = "%s.%d%s" % [stem, i, ext]
		if FileAccess.file_exists(src):
			DirAccess.rename_absolute(src, "%s.%d%s" % [stem, i + 1, ext])
	if FileAccess.file_exists(path):
		DirAccess.rename_absolute(path, "%s.1%s" % [stem, ext])
