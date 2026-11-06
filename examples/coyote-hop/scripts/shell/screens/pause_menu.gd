# ---------------------------------------------------------------------------
# pause_menu.gd
# Purpose : The pause menu over the running game: Resume, Settings, Quit to title.
# Usage   : front.pause()   (the pause action, or automatically when the window loses focus)
# Notes   : The game tree is paused (get_tree().paused) while this is open; the menus run in PROCESS_MODE_ALWAYS.
#           Cancel or the pause action again resumes. Quit to title saves through the play scene's _exit_tree().
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name PauseMenu
extends ShellScreen

const BACKDROP_ALPHA: float = 0.6


func _init(p_front: FrontEnd) -> void:
	super(p_front, "pause")
	opaque = false # the paused game stays visible behind the backdrop


func build() -> void:
	var shade: ColorRect = ColorRect.new()
	shade.name = "Backdrop"
	shade.color = Color(0, 0, 0, BACKDROP_ALPHA)
	shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(shade)
	var col: VBoxContainer = centered_column(true)
	var title: Label = label(Shell.t("pause.title"), UiTheme.HEADING_FONT, "Heading")
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	col.add_child(title)
	col.add_child(button(Shell.t("pause.resume"), "Resume", front.resume))
	col.add_child(button(Shell.t("pause.help"), "Help", front.open_help)) # #167: what now, and what was said
	col.add_child(button(Shell.t("pause.history"), "History", front.open_history))
	col.add_child(button(Shell.t("menu.settings"), "Settings", front.open_settings))
	col.add_child(button(Shell.t("pause.quit_to_title"), "QuitToTitle", front.quit_to_title))


func on_cancel() -> void:
	front.resume()


func _unhandled_input(event: InputEvent) -> void:
	if is_top() and event.is_action_pressed("pause") and not event.is_action_pressed("ui_cancel"):
		get_viewport().set_input_as_handled()
		front.resume()
		return
	super(event)
