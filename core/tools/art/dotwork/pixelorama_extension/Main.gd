# ---------------------------------------------------------------------------
# Main.gd
# Purpose : the Dotwork panel inside Pixelorama 1.2.4 (a tab named Dotwork): for the project open in Pixelorama it
#           shows which game asset the .pxo is (Dotwork's manifests: the game files, Dotwork's QA notes, whether a
#           re-export would stop and why), and has "Re-export to game" (saves the .pxo, then runs
#           dotwork.py pixelorama --reexport --clear-export-path and shows the result), "Next asset" (opens the next
#           Dotwork .pxo of the game) and "Show in game folder" (the shipped files in the file manager).
# Usage   : python tools/art/dotwork/dotwork.py pixelorama --install-extension (in the game folder), restart
#           Pixelorama, Edit > Preferences > Extensions > Dotwork panel > Enable. Window > Panels shows or hides it.
# Notes   : Which Python runs Dotwork, where dotwork.py and the game are: user://dotwork_panel.json, written by the
#           install (one row per game; the .pxo's folder picks the row). Dotwork runs in a thread
#           (Logic.run_process), so Pixelorama stays responsive while it works; a second click waits for the first run.
#           A run has a time limit, and closing Pixelorama (or turning the extension off) kills it rather than waiting
#           (#255). The panel never
#           edits a game file itself: everything goes through the same command line you would type.
#           The exams drive it through reexport() and the finished signal (tests/test_pixelorama.py).
#           Before saving, the project's export folder is blanked: Pixelorama would write this machine's folder
#           into the .pxo, which the game's repository must not hold.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends Node

signal info_ready(answer: Dictionary)  ## after each refresh: the --info answer ({} when there was none)
signal finished(result: Dictionary)  ## after each re-export: panel_logic.summarize's result

const Logic := preload("res://src/Extensions/DotworkPanel/panel_logic.gd")
const CONFIG_PATH := "user://dotwork_panel.json"
const PANEL_NAME := "Dotwork"
const MIN_WIDTH := 260  # px: the panel's narrowest
const STATUS_HEIGHT := 160  # px: the result box under the asset's text

var panel: VBoxContainer
var title_label: Label
var body_label: Label
var status_text: TextEdit
var reexport_button: Button
var next_button: Button
var folder_button: Button
var refresh_button: Button
var answer: Dictionary = {}
var busy := false
var _thread: Thread
var _stop := [false]  # set when the panel goes away: the running Dotwork is killed, not waited for (#255)
var _fold_case := OS.get_name() == "Windows"


func _ready() -> void:
	_build_ui()
	ExtensionsApi.panel.add_node_as_tab(panel)
	ExtensionsApi.signals.signal_project_switched(refresh)
	ExtensionsApi.signals.signal_project_saved(_on_saved)
	await get_tree().process_frame
	refresh()


func _exit_tree() -> void:
	ExtensionsApi.signals.signal_project_switched(refresh, true)
	ExtensionsApi.signals.signal_project_saved(_on_saved, true)
	_stop[0] = true  # #255: the run kills Dotwork (and its Godot) within a poll, so this wait is short
	if _thread and _thread.is_started():
		_thread.wait_to_finish()
	if is_instance_valid(panel):
		ExtensionsApi.panel.remove_node_from_tab(panel)


# -------------------------------------------------- the panel
func _build_ui() -> void:
	panel = VBoxContainer.new()
	panel.name = PANEL_NAME
	panel.custom_minimum_size.x = MIN_WIDTH
	title_label = Label.new()
	title_label.text = "Dotwork"
	title_label.add_theme_font_size_override("font_size", 16)
	panel.add_child(title_label)
	var row := HBoxContainer.new()
	reexport_button = _button(row, "Re-export to game", reexport,
		"Save this .pxo, then run dotwork.py pixelorama --reexport for the game")
	refresh_button = _button(row, "Refresh", refresh, "Ask Dotwork again which asset this is")
	panel.add_child(row)
	var row2 := HBoxContainer.new()
	next_button = _button(row2, "Next asset", open_next, "Open the game's next Dotwork .pxo")
	folder_button = _button(row2, "Show in game folder", show_in_folder,
		"Show the shipped files of this asset in the file manager")
	panel.add_child(row2)
	# the asset's text scrolls on its own, so a long file list never pushes the result out of a short panel
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	body_label = Label.new()
	body_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(body_label)
	panel.add_child(scroll)
	status_text = TextEdit.new()
	status_text.editable = false
	status_text.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	status_text.custom_minimum_size.y = STATUS_HEIGHT
	panel.add_child(status_text)


func _button(parent: Container, text: String, action: Callable, tip: String) -> Button:
	var b := Button.new()
	b.text = text
	b.tooltip_text = tip
	b.pressed.connect(action)
	parent.add_child(b)
	return b


func _set_busy(value: bool) -> void:
	busy = value
	_update_buttons()


## Buttons follow the state: all wait while Dotwork runs; Next and Show need an answer that names them.
func _update_buttons() -> void:
	for b in [reexport_button, refresh_button]:
		b.disabled = busy
	folder_button.disabled = busy or str(answer.get("folder", "")) == ""
	next_button.disabled = busy or str(answer.get("next", "")) == ""


func _status(lines: PackedStringArray) -> void:
	status_text.text = "\n".join(lines)


# -------------------------------------------------- which game, which asset
func _current_path() -> String:
	var project: Project = ExtensionsApi.project.current_project
	return project.save_path if project else ""


## The config row for path, or {"error": why}.
func _game_for(path: String) -> Dictionary:
	var config := Logic.load_config(CONFIG_PATH)
	if config.has("error"):
		return config
	if path.is_empty() or path.get_extension().to_lower() != "pxo":
		return {"error": "Open (or save) a .pxo from the game's Dotwork sources: <game>/assets_src/pixelorama/ "
			+ "(dotwork.py pixelorama builds them)."}
	var game := Logic.find_game(config, path, _fold_case)
	if game.is_empty():
		var why := "%s is not in the Dotwork sources of a game the panel knows. From that game, %s." % [path,
			Logic.INSTALL_HINT]
		return {"error": why}
	var broken := Logic.check_game(game)
	return {"error": broken} if broken != "" else game


## Ask Dotwork which asset the open .pxo is (dotwork.py pixelorama --info) and show it.
func refresh() -> void:
	if busy:
		return
	var path := _current_path()
	var game := _game_for(path)
	if game.has("error"):
		answer = {}
		title_label.text = "Dotwork"
		body_label.text = game["error"]
		_update_buttons()
		info_ready.emit({})
		return
	body_label.text = "Asking Dotwork about %s ..." % path.get_file()
	_run(game, Logic.info_args(game, path), _on_info)


func _on_info(code: int, output: String, game: Dictionary) -> void:
	answer = Logic.parse_info(output)
	var text := Logic.describe(answer)
	title_label.text = text[0]
	body_label.text = text[1]
	if answer.is_empty():
		_status(Logic.summarize(code, output, game.get("python", ""))["lines"])
	_update_buttons()
	info_ready.emit(answer)


func _on_saved() -> void:
	if not busy:
		refresh()


# -------------------------------------------------- actions
## Save the open .pxo and re-export the game's Dotwork sources; emits finished with the result.
func reexport() -> void:
	if busy:
		return
	var project: Project = ExtensionsApi.project.current_project
	var path := _current_path()
	var game := _game_for(path)
	if game.has("error"):
		_status(PackedStringArray(["[error] " + game["error"]]))
		finished.emit({"ok": false, "code": 2, "changed": -1, "lines": PackedStringArray([game["error"]])})
		return
	_set_busy(true)
	# Pixelorama refills a blank export folder with the file's own folder after a save; blank it before each one
	project.export_profile.directory_path = ""
	if not OpenSave.save_pxo_file(path, false, project):
		_set_busy(false)
		var why := "[error] Pixelorama could not save %s (see its error message); nothing was re-exported" % path
		_status(PackedStringArray([why]))
		finished.emit({"ok": false, "code": 1, "changed": -1, "lines": PackedStringArray([why])})
		return
	_status(PackedStringArray(["Saved %s. Re-exporting with Dotwork (verify runs Godot: this can take a minute) ..."
		% path.get_file()]))
	busy = false  # _run sets it again; the save's own refresh was skipped while busy
	_run(game, Logic.reexport_args(game), _on_reexported)


func _on_reexported(code: int, output: String, game: Dictionary) -> void:
	var result := Logic.summarize(code, output, game.get("python", ""))
	var lines := PackedStringArray(["Re-export %s (exit %d):" % ["done" if result["ok"] else "FAILED", code]])
	lines.append_array(result["lines"])
	_status(lines)
	finished.emit(result)
	refresh()


## Open the game's next Dotwork .pxo (or switch to its tab when it is open already).
func open_next() -> void:
	var next := str(answer.get("next", ""))
	if next.is_empty() or busy:
		return
	var want := Logic.norm(next, _fold_case)
	for p: Project in Global.projects:
		if Logic.norm(p.save_path, _fold_case) == want:
			ExtensionsApi.project.current_project = p
			return
	OpenSave.open_pxo_file(next)


## Show the asset's shipped files in the system's file manager.
func show_in_folder() -> void:
	var folder := str(answer.get("folder", ""))
	if folder.is_empty():
		return
	var err := OS.shell_show_in_file_manager(folder)
	if err != OK:
		_status(PackedStringArray(["[error] could not open the file manager at %s (%s)" % [folder,
			error_string(err)]]))


# -------------------------------------------------- running Dotwork
## Run Python with args in a thread; done(code, output, game) runs on the main thread after.
func _run(game: Dictionary, args: PackedStringArray, done: Callable) -> void:
	_set_busy(true)
	# Pixelorama started from a menu has none of your shell's variables: Godot for verify comes from the config
	if str(game.get("godot_bin", "")) != "" and OS.get_environment("GODOT_BIN").is_empty():
		OS.set_environment("GODOT_BIN", game["godot_bin"])
	OS.set_environment("PYTHONIOENCODING", "utf-8")
	_thread = Thread.new()
	_thread.start(_execute.bind(game, args, done))


func _execute(game: Dictionary, args: PackedStringArray, done: Callable) -> void:
	var limit := Logic.RUN_LIMIT_S if "--reexport" in args else Logic.INFO_LIMIT_S
	var r: Dictionary = Logic.run_process(game["python"], args, limit, _stop)
	if r["stopped"]:
		return  # the panel is going away: nothing to show
	_finish.call_deferred(r["code"], r["output"], game, done)


func _finish(code: int, output: String, game: Dictionary, done: Callable) -> void:
	_thread.wait_to_finish()
	_thread = null
	_set_busy(false)
	done.call(code, output, game)
