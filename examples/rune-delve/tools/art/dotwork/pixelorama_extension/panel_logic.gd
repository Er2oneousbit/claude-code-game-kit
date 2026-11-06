# ---------------------------------------------------------------------------
# panel_logic.gd
# Purpose : the Dotwork panel's logic without any of Pixelorama's UI (Main.gd draws the panel): read the config
#           dotwork.py pixelorama --install-extension wrote, find which game an open .pxo belongs to, build the
#           Dotwork command lines, and turn Dotwork's output into what the panel shows.
# Usage   : const Logic := preload("res://src/Extensions/DotworkPanel/panel_logic.gd") (Main.gd); plain Godot runs
#           it headless in Dotwork's exam (tests/test_pixelorama.py), so it names no Pixelorama class.
# Notes   : The config (user://dotwork_panel.json) is {"games": [{"project", "python", "dotwork", "sources",
#           "godot_bin"}]}: full paths on this machine, one row per game. A .pxo belongs to the game whose
#           "sources" folder (<src_dir>/pixelorama) holds it; paths compare with / separators, and without case on
#           Windows. Dotwork answers --info with one line "DOTWORK_PANEL <JSON>" and marks its own lines
#           "[ OK ]", "[warn]", "[info]", "[error]" and "[FAIL]"; exit 0 ok, 1 a task failed, 2 environment.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends RefCounted

const MARKER := "DOTWORK_PANEL "
const MARKS := ["[ OK ]", "[warn]", "[info]", "[error]", "[FAIL]"]
const INSTALL_HINT := "run  python tools/art/dotwork/dotwork.py pixelorama --install-extension  in the game folder"
const LOG_TIME := 20  # characters of "YYYY-MM-DD HH:MM:SS " before a Dotwork log line's message
const MAX_LINES := 12  # lines of Dotwork's output shown when it printed none of its marked lines
const FILES_SHOWN := 6  # game files the panel lists by name (the count is always shown)
const RUN_LIMIT_S := 900.0  # seconds a Dotwork run may take before it is stopped (a re-export with verify: minutes)
const INFO_LIMIT_S := 120.0  # seconds for --info (no Godot)
const POLL_MS := 50  # how often a run checks for its end, its limit and a stop
const READ_CHUNK := 65536  # bytes read from Dotwork's output at a time


## The config as a Dictionary, or {"error": why} when it is missing or broken.
static func load_config(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {"error": "Dotwork is not set up for this Pixelorama yet: %s, then restart Pixelorama." % INSTALL_HINT}
	var text := FileAccess.get_file_as_string(path)
	var data = JSON.parse_string(text)
	if typeof(data) != TYPE_DICTIONARY or typeof(data.get("games")) != TYPE_ARRAY:
		return {"error": "%s is not a Dotwork panel config: %s again." % [path, INSTALL_HINT]}
	return data


## A path in one form: / separators, no trailing /, lower case when fold_case (Windows).
static func norm(path: String, fold_case: bool) -> String:
	var p := path.replace("\\", "/").simplify_path()
	while p.length() > 1 and p.ends_with("/"):
		p = p.substr(0, p.length() - 1)
	return p.to_lower() if fold_case else p


## The config row of the game whose Dotwork sources hold pxo_path, or {} (the longest match wins, so a game
## inside another game's folder still finds its own row).
static func find_game(config: Dictionary, pxo_path: String, fold_case: bool) -> Dictionary:
	var file := norm(pxo_path, fold_case)
	var best := {}
	var best_len := -1
	for game in config.get("games", []):
		if typeof(game) != TYPE_DICTIONARY or typeof(game.get("sources")) != TYPE_STRING:
			continue
		var src := norm(game["sources"], fold_case)
		if src != "" and file.begins_with(src + "/") and src.length() > best_len:
			best = game
			best_len = src.length()
	return best


## Why this game's row cannot run Dotwork ("" when it can): a Python or a dotwork.py that moved, a game folder gone.
static func check_game(game: Dictionary) -> String:
	for key in ["python", "dotwork", "project"]:
		if typeof(game.get(key)) != TYPE_STRING or str(game[key]).is_empty():
			return "the panel config has no %s for this game: %s again." % [key, INSTALL_HINT]
	if not FileAccess.file_exists(game["python"]):
		return "Python is not at %s any more: %s again with the Python you run Dotwork with." % [
			game["python"], INSTALL_HINT]
	if not FileAccess.file_exists(game["dotwork"]):
		return "dotwork.py is not at %s any more (the game moved?): %s again." % [game["dotwork"], INSTALL_HINT]
	if not DirAccess.dir_exists_absolute(game["project"]):
		return "the game folder %s is gone: %s again from where the game is now." % [game["project"], INSTALL_HINT]
	return ""


## Arguments for Python: what the panel shows for one .pxo.
static func info_args(game: Dictionary, pxo_path: String) -> PackedStringArray:
	return PackedStringArray([game["dotwork"], "pixelorama", "--info", pxo_path, "--project", game["project"]])


## Arguments for Python: the re-export (every Dotwork .pxo of the game; untouched ones change no file), with the
## export folder Pixelorama saves in each .pxo blanked, so the game's repository never holds a path of this machine.
static func reexport_args(game: Dictionary) -> PackedStringArray:
	return PackedStringArray([game["dotwork"], "pixelorama", "--reexport", "--clear-export-path", "--project",
		game["project"]])


## The JSON of the last DOTWORK_PANEL line in Dotwork's output, or {} when there is none.
static func parse_info(output: String) -> Dictionary:
	var lines := output.replace("\r\n", "\n").split("\n")
	for i in range(lines.size() - 1, -1, -1):
		var line := lines[i].strip_edges()
		if line.begins_with(MARKER):
			var data = JSON.parse_string(line.substr(MARKER.length()))
			if typeof(data) == TYPE_DICTIONARY:
				return data
	return {}


## What a Dotwork run did, for the panel: {"ok", "code", "lines" (its marked lines and re-export log lines, or the
## last lines of its output),
## "changed" (files the re-export changed, -1 when it did not say)}. code -1: Python could not be started.
static func summarize(code: int, output: String, python := "") -> Dictionary:
	if code == -1:
		return {"ok": false, "code": code, "changed": -1, "lines": PackedStringArray([
			"[error] could not start Python (%s): %s again with the Python you run Dotwork with." % [python,
			INSTALL_HINT]])}
	var marked := PackedStringArray()
	var all := PackedStringArray()
	var changed := -1
	for raw in output.replace("\r\n", "\n").split("\n"):
		var line := raw.strip_edges()
		if line.is_empty() or line.begins_with(MARKER):
			continue
		all.append(line)
		for m in MARKS:
			if line.begins_with(m):
				marked.append(line)
				break
		# Dotwork's log lines ("2026-11-04 20:15:52 pixelorama reexport character knight: 7 frames, ...") say what
		# each source gave: kept, without the time
		var stamped := line.length() > LOG_TIME and line.substr(0, 4).is_valid_int() and line[4] == "-"
		if stamped and line[13] == ":" and line.find(" reexport") > 0:
			marked.append(line.substr(LOG_TIME))
		var at := line.find("files changed")
		if line.begins_with("[ OK ] re-exported") and at > 0:
			var head := line.substr(0, at).strip_edges()
			var num := head.substr(head.rfind("(") + 1)
			if num.is_valid_int():
				changed = num.to_int()
	var shown := marked
	if shown.is_empty():
		shown = all.slice(maxi(0, all.size() - MAX_LINES))
	if code != 0 and shown.is_empty():
		shown = PackedStringArray(["[error] Dotwork stopped (exit %d) without a message." % code])
	return {"ok": code == 0, "code": code, "changed": changed, "lines": shown}


## The panel's text for one --info answer: (title, body) as two Strings in an Array.
static func describe(answer: Dictionary) -> Array:
	if answer.is_empty():
		return ["Dotwork", "Dotwork gave no answer for this file."]
	if not answer.get("ok", false):
		return ["Not a Dotwork asset", str(answer.get("error", "this file is not one of the game's Dotwork sources"))]
	var body := PackedStringArray()
	body.append("%s  (%s)" % [answer.get("file", ""), answer.get("position", "")])
	var files: Array = answer.get("files", [])
	var count := int(answer.get("file_count", files.size()))
	var home := str(answer.get("home", ""))
	body.append("Game files: %d%s" % [count, " in " + home if home != "" else ""])
	for f in files.slice(0, FILES_SHOWN):
		var name := str(f)
		body.append("- " + (name.substr(home.length()) if home != "" and name.begins_with(home) else name))
	if count > FILES_SHOWN:
		body.append("... %d more" % (count - FILES_SHOWN))
	if str(answer.get("refused", "")) != "":
		body.append("Re-export would stop: " + str(answer["refused"]))
	var qa: Array = answer.get("qa", [])
	if not qa.is_empty():
		body.append("QA notes:")
		for q in qa:
			body.append("- " + str(q))
	var notes: Array = answer.get("notes", [])
	for n in notes:
		body.append("Note: " + str(n))
	if str(answer.get("export_folder", "")) != "":
		body.append("This .pxo holds a folder of this machine (%s); the re-export blanks it." % answer["export_folder"])
	return [str(answer.get("what", "Dotwork asset")), "\n".join(body)]


## Run python with args and wait for it, at most limit_s seconds, checking stop[0] as it runs: {"code", "output"
## (stdout and stderr), "timed_out", "stopped"}. A run past its limit, or stopped (Pixelorama closing, the extension
## turned off), is killed with the processes it started (#255: OS.execute waited with no limit, so closing
## Pixelorama during a hung re-export hung Pixelorama). code is -1 when Python cannot start or was killed.
static func run_process(python: String, args: PackedStringArray, limit_s: float, stop: Array) -> Dictionary:
	var p := OS.execute_with_pipe(python, args, false)
	if p.is_empty():
		return {"code": -1, "output": "", "timed_out": false, "stopped": false}
	var pid: int = p["pid"]
	var out := PackedByteArray()
	var start := Time.get_ticks_msec()
	var timed_out := false
	var stopped := false
	while OS.is_process_running(pid):
		out.append_array(_drain(p))
		if not stop.is_empty() and stop[0]:
			stopped = true
		elif Time.get_ticks_msec() - start > limit_s * 1000.0:
			timed_out = true
		if stopped or timed_out:
			kill_tree(pid)
			break
		OS.delay_msec(POLL_MS)
	out.append_array(_drain(p))
	var output := out.get_string_from_utf8()
	if timed_out:
		output += ("\n[error] Dotwork ran for over %d s and was stopped (a hung Godot verify?): run the same "
			+ "command in a terminal to see where it waits\n") % int(limit_s)
	var code := OS.get_process_exit_code(pid) if not (timed_out or stopped) else -1
	return {"code": code, "output": output, "timed_out": timed_out, "stopped": stopped}


static func _drain(p: Dictionary) -> PackedByteArray:
	var got := PackedByteArray()
	for key in ["stdio", "stderr"]:
		var f: FileAccess = p[key]
		while true:
			var chunk := f.get_buffer(READ_CHUNK)
			if chunk.is_empty():
				break
			got.append_array(chunk)
	return got


## Kill a process and the ones it started: Dotwork runs Godot for verify. Windows: taskkill /T; elsewhere its direct
## children (pkill -P), then it (checked on Windows only, verify on Linux and macOS).
static func kill_tree(pid: int) -> void:
	if OS.get_name() == "Windows":
		OS.execute("taskkill", PackedStringArray(["/T", "/F", "/PID", str(pid)]), [], false, false)
	else:
		OS.execute("pkill", PackedStringArray(["-KILL", "-P", str(pid)]), [], false, false)
	if OS.is_process_running(pid):
		OS.kill(pid)
