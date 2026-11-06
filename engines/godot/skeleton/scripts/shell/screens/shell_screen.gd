# ---------------------------------------------------------------------------
# shell_screen.gd
# Purpose : Base class for the front-end screens (title, main menu, settings, credits, loading, pause): built in
#           code, rebuilt when the language or text size changes, cancel goes back one screen, focus remembered.
# Usage   : class_name MyScreen extends ShellScreen
#           func _init(p_front: FrontEnd) -> void: super(p_front, "my_screen")
#           func build() -> void: var col := centered_column(); col.add_child(button(Shell.t("menu.play"), "Play", f))
# Notes   : Every visible string goes through Shell.t() (the pseudo-locale check in smoke runs fails otherwise).
#           Give focusable controls stable node names: rebuild() and the smoke drive find them by name.
#           Only the top screen of FrontEnd's stack reacts to input; screens below it are hidden.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name ShellScreen
extends Control

const MARGIN: int = 14
const BUTTON_WIDTH: int = 170
const COLUMN_SEPARATION: int = 6

var front: FrontEnd
var screen_name: String = ""
var opaque: bool = true # paints the theme background; overlays (the pause menu) set it false
var _last_focus: String = ""


func _init(p_front: FrontEnd, p_screen_name: String) -> void:
	front = p_front
	screen_name = p_screen_name
	name = p_screen_name.to_pascal_case()
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_STOP


func _ready() -> void:
	build()


func build() -> void:
	pass # each screen adds its controls here


func _draw() -> void:
	if opaque:
		draw_rect(Rect2(Vector2.ZERO, size), UiTheme.backdrop())


func focus_first() -> void:
	var c: Control = _first_focusable(self)
	if c != null:
		c.grab_focus()


func rebuild() -> void:
	# Same screen, new strings or sizes: keep the focused control by name
	var owner_node: Control = get_viewport().gui_get_focus_owner()
	var focused: String = owner_node.name if owner_node != null and is_ancestor_of(owner_node) else _last_focus
	for child: Node in get_children():
		remove_child(child)
		child.queue_free()
	build()
	if not _focus_named(focused):
		focus_first()


func remember_focus() -> void:
	var owner_node: Control = get_viewport().gui_get_focus_owner()
	_last_focus = owner_node.name if owner_node != null and is_ancestor_of(owner_node) else ""


func restore_focus() -> void:
	if not _focus_named(_last_focus):
		focus_first()


func is_top() -> bool:
	return front != null and front.top() == self and is_visible_in_tree()


func on_cancel() -> void:
	front.back()


func _unhandled_input(event: InputEvent) -> void:
	if is_top() and event.is_action_pressed("ui_cancel"):
		get_viewport().set_input_as_handled()
		on_cancel()


# ---- builders -----------------------------------------------------------------

func label(text: String, font_scale: float = 1.0, node_name: String = "") -> Label:
	var l: Label = Label.new()
	l.text = text
	if node_name != "":
		l.name = node_name
	if font_scale == UiTheme.HEADING_FONT:
		l.theme_type_variation = UiTheme.HEADING_TYPE # follows text_scale live (ui_theme.gd)
	elif font_scale == UiTheme.TITLE_FONT:
		l.theme_type_variation = UiTheme.TITLE_TYPE
	elif font_scale != 1.0:
		l.add_theme_font_size_override("font_size", roundi(get_theme_default_font_size() * font_scale))
	return l


func button(text: String, node_name: String, on_press: Callable) -> Button:
	var b: Button = Button.new()
	b.text = text
	b.name = node_name
	b.custom_minimum_size.x = BUTTON_WIDTH
	b.pressed.connect(on_press)
	return b


## A column in the middle of the screen; on_panel puts it on the theme's panel (a menu over the game, so the game's
## HUD never shows through behind its text: tools/access/sweep.py, #91).
func centered_column(on_panel: bool = false) -> VBoxContainer:
	var center: CenterContainer = CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	center.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(center)
	var parent: Control = center
	if on_panel:
		var panel: PanelContainer = PanelContainer.new()
		panel.name = "Panel"
		center.add_child(panel)
		parent = panel
	var col: VBoxContainer = VBoxContainer.new()
	col.alignment = BoxContainer.ALIGNMENT_CENTER
	col.add_theme_constant_override("separation", COLUMN_SEPARATION)
	parent.add_child(col)
	return col


func margin_box() -> VBoxContainer:
	var m: MarginContainer = MarginContainer.new()
	m.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	for side: String in ["margin_left", "margin_right", "margin_top", "margin_bottom"]:
		m.add_theme_constant_override(side, MARGIN)
	add_child(m)
	var col: VBoxContainer = VBoxContainer.new()
	col.add_theme_constant_override("separation", COLUMN_SEPARATION)
	m.add_child(col)
	return col


func _focus_named(node_name: String) -> bool:
	if node_name == "":
		return false
	var n: Node = find_child(node_name, true, false)
	if n is Control and (n as Control).focus_mode != Control.FOCUS_NONE and (n as Control).is_visible_in_tree():
		(n as Control).grab_focus()
		return true
	return false


func _first_focusable(node: Node) -> Control:
	for child: Node in node.get_children():
		if child is Control and (child as Control).visible:
			var c: Control = child
			if c.focus_mode == Control.FOCUS_ALL:
				return c
			var inner: Control = _first_focusable(c)
			if inner != null:
				return inner
	return null

# {{FOOTER}}
