# ---------------------------------------------------------------------------
# help_screen.gd
# Purpose : "What now?" from the pause menu (#167, cognitive access): the current goal, the last line someone said,
#           and the controls for play, so a player who lost track (a break, a memory or attention difference) can
#           pick up again without guessing.
# Usage   : front.open_help()   (from the pause menu); the game sets the goal: Shell.set_objective(Shell.t("..."))
# Notes   : The goal is whatever the game last set (empty: "no goal set yet"); the last line comes from
#           Shell.history (the subtitle bar records every line it shows). Controls follow the device in use.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name HelpScreen
extends ShellScreen

const CONTROL_ACTIONS: PackedStringArray = ["move_left", "move_right", "jump", "attack", "interact", "pause"]
const SCROLL_STEP_PX: int = 24

var _scroll: ScrollContainer


func _init(p_front: FrontEnd) -> void:
	super(p_front, "help")


func build() -> void:
	var col: VBoxContainer = margin_box()
	col.add_child(label(Shell.t("help.title"), UiTheme.HEADING_FONT, "Heading"))
	_scroll = ScrollContainer.new()
	var scroll: ScrollContainer = _scroll
	scroll.name = "Scroll"
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	col.add_child(scroll)
	var body: VBoxContainer = VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(body)
	var goal: String = Shell.objective
	body.add_child(_wrapped(Shell.t("help.objective", {"text": goal}) if goal != "" else Shell.t("help.no_objective"),
			"Objective"))
	var last: Dictionary = Shell.history.back() if not Shell.history.is_empty() else {}
	if not last.is_empty():
		body.add_child(_wrapped(Shell.t("help.last_line", {"name": Shell.content(str(last["name"])),
				"text": Shell.content(str(last["text"]))}), "LastLine"))
	body.add_child(label(Shell.t("help.controls"), 1.0, "ControlsHeading"))
	for action: String in CONTROL_ACTIONS:
		body.add_child(_wrapped("%s: %s" % [Shell.t("action." + action), Shell.binding_text(Shell.prompt_for(action))],
				"Control_" + action))
	col.add_child(button(Shell.t("settings.back"), "Back", front.back))


func _unhandled_input(event: InputEvent) -> void:
	if is_top() and (event.is_action_pressed("ui_up", true) or event.is_action_pressed("ui_down", true)):
		var dir: int = -1 if event.is_action_pressed("ui_up", true) else 1
		_scroll.scroll_vertical += dir * SCROLL_STEP_PX
		get_viewport().set_input_as_handled()
		return
	super(event)


func _wrapped(text: String, node_name: String) -> Label:
	var l: Label = label(text, 1.0, node_name)
	l.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	l.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return l
