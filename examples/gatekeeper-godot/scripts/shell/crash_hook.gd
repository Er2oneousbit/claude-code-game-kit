# ---------------------------------------------------------------------------
# crash_hook.gd
# Purpose : The unhandled-error hook: notices every GDScript runtime error (null calls, bad indexes, type errors)
#           so the Shell can write crashes/crash_<time>.txt and, in a smoke run, exit with code 1.
# Usage   : CrashHook.install()                 # once, at boot (the Shell does it)
#           for e in CrashHook.take(): ...      # each frame: errors since the last call, oldest first
# Notes   : Godot does not stop the game on a script error: the failing function returns and the game goes on,
#           which is why errors must be caught here. The hook is a Logger (Godot 4.5 and later; the project needs
#           4.6, see MIN_GODOT in tools/dev.py). Loggers can be called from any thread, so the queue is behind a
#           mutex and the Shell does the file work on the main thread. Only script errors count (push_error and
#           engine warnings do not make a crash file).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name CrashHook
extends RefCounted

const MAX_QUEUED: int = 20 # a loop that errors every frame must not fill memory


## The Logger Godot calls on every error; it hands script errors to CrashHook.record().
class ErrorLogger extends Logger:
	func _log_error(function: String, file: String, line: int, code: String, rationale: String,
			_editor_notify: bool, error_type: int, script_backtraces: Array[ScriptBacktrace]) -> void:
		if error_type != ERROR_TYPE_SCRIPT:
			return
		var trace: String = ""
		for bt: ScriptBacktrace in script_backtraces:
			trace += bt.format(0, 2)
		CrashHook.record({"function": function, "file": file, "line": line,
				"message": rationale if rationale != "" else code, "backtrace": trace})


static var _mutex: Mutex = Mutex.new()
static var _queue: Array[Dictionary] = []
static var _logger: ErrorLogger = null


static func install() -> void:
	if _logger != null:
		return
	_logger = ErrorLogger.new()
	OS.add_logger(_logger)


static func installed() -> bool:
	return _logger != null


static func record(entry: Dictionary) -> void:
	_mutex.lock()
	if _queue.size() < MAX_QUEUED:
		_queue.append(entry)
	_mutex.unlock()


static func take() -> Array[Dictionary]:
	_mutex.lock()
	var out: Array[Dictionary] = _queue.duplicate()
	_queue.clear()
	_mutex.unlock()
	return out
