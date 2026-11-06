# ---------------------------------------------------------------------------
# history_screen.gd
# Purpose : "Dialogue history" from the pause menu (#167, cognitive access): every line said so far, newest last, so
#           a player who missed or forgot a line can read it again at their own pace.
# Usage   : front.open_history()   (from the pause menu)
# Notes   : Reads Shell.history (the subtitle bar records each line it shows, up to Shell.MAX_HISTORY); it scrolls to
#           the newest line, and up/down scroll by hand.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name HistoryScreen
extends ShellScreen

const SCROLL_STEP_PX: int = 24

var _scroll: ScrollContainer


func _init(p_front: FrontEnd) -> void:
	super(p_front, "history")


func build() -> void:
	var col: VBoxContainer = margin_box()
	col.add_child(label(Shell.t("history.title"), UiTheme.HEADING_FONT, "Heading"))
	_scroll = ScrollContainer.new()
	_scroll.name = "Scroll"
	_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	col.add_child(_scroll)
	var body: VBoxContainer = VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_scroll.add_child(body)
	if Shell.history.is_empty():
		body.add_child(label(Shell.t("history.empty"), 1.0, "Empty"))
	for i: int in Shell.history.size():
		var entry: Dictionary = Shell.history[i]
		var l: Label = label(Shell.t("help.last_line", {"name": Shell.content(str(entry["name"])),
				"text": Shell.content(str(entry["text"]))}), 1.0, "Line_%d" % i)
		l.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		l.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		body.add_child(l)
	col.add_child(button(Shell.t("settings.back"), "Back", front.back))
	(func() -> void: _scroll.scroll_vertical = int(_scroll.get_v_scroll_bar().max_value)).call_deferred() # newest


func _unhandled_input(event: InputEvent) -> void:
	# up and down scroll the lines (Back keeps the focus), as on the credits
	if is_top() and (event.is_action_pressed("ui_up", true) or event.is_action_pressed("ui_down", true)):
		var dir: int = -1 if event.is_action_pressed("ui_up", true) else 1
		_scroll.scroll_vertical += dir * SCROLL_STEP_PX
		get_viewport().set_input_as_handled()
		return
	super(event)
