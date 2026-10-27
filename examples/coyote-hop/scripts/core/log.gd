# ---------------------------------------------------------------------------
# log.gd  (autoload name: Log)
# Purpose : Tiny channel-based logger so output is greppable and toggleable.
# Usage   : Log.info("physics", "landed"), Log.warn(...), Log.error(...), Log.debug(...)
#           Enable channels in debug builds: Log.enable_channel("ai")
#           Verbose debug output: run the game with `-- --debug` (see dev.py run --debug).
# Notes   : Errors also call push_error so the editor debugger shows them.
#           dev.py smoke fails if output contains "ERROR". That is intentional.
#           Autoload name "Log" must NOT also be a class_name (global name clash).
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# ---------------------------------------------------------------------------
extends Node

# Channels that print debug-level output. "core" is on by default.
var _debug_channels: Dictionary = {"core": true}
# Master switch for debug-level logs, set by the --debug user arg.
var debug_enabled: bool = false


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
		print("[DEBUG][%s] %s" % [channel, msg])


func info(channel: String, msg: String) -> void:
	print("[INFO][%s] %s" % [channel, msg])


func warn(channel: String, msg: String) -> void:
	push_warning("[%s] %s" % [channel, msg])
	print("[WARN][%s] %s" % [channel, msg])


func error(channel: String, msg: String) -> void:
	push_error("[%s] %s" % [channel, msg])
	print("[ERROR][%s] %s" % [channel, msg])
