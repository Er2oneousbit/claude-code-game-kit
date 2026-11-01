# ---------------------------------------------------------------------------
# option_stepper.gd
# Purpose : A "< value >" picker that works the same with a mouse, keys and a gamepad: left/right (or the d-pad)
#           step through the choices, accept or a click moves to the next one.
# Usage   : var s := OptionStepper.new()
#           s.setup(["small", "medium", "large"], [Shell.t("value.subtitle_size.small"), ...], current)
#           s.changed.connect(func(v: Variant) -> void: Shell.set_value("access", "subtitle_size", v))
# Notes   : A Button underneath, so it takes the theme's focus outline. The arrows are drawn, not text, so they
#           need no translation; the theme's side padding is widened by ARROW_PAD so they never cover the value.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name OptionStepper
extends Button

signal changed(value: Variant)

const ARROW_PAD: int = 12 # extra side padding that holds the arrows
const ARROW_INSET: float = 4.0
const STATES: PackedStringArray = ["normal", "hover", "pressed", "hover_pressed", "disabled", "focus"]

var values: Array = []
var labels: PackedStringArray = []
var index: int = 0
var _padding: bool = false # guards the theme-changed notification our own overrides cause


func setup(p_values: Array, p_labels: PackedStringArray, current: Variant) -> void:
	values = p_values
	labels = p_labels
	index = maxi(0, _find(current))
	_refresh()


func value() -> Variant:
	return values[index] if index < values.size() else null


func step(delta: int) -> void:
	if values.is_empty():
		return
	index = posmod(index + delta, values.size())
	_refresh()
	changed.emit(values[index])


func _ready() -> void:
	focus_mode = Control.FOCUS_ALL
	_pad_styles()


func _notification(what: int) -> void:
	if what == NOTIFICATION_THEME_CHANGED and not _padding:
		_pad_styles()


func _gui_input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_left", true):
		step(-1)
		accept_event()
	elif event.is_action_pressed("ui_right", true):
		step(1)
		accept_event()


func _pressed() -> void:
	step(1)


func _draw() -> void:
	var font: Font = get_theme_font("font")
	var font_size: int = get_theme_font_size("font_size")
	var colour: Color = get_theme_color("font_focus_color" if has_focus() else "font_color")
	var y: float = (size.y + font.get_ascent(font_size) - font.get_descent(font_size)) / 2.0
	var right_w: float = font.get_string_size(">", HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x
	draw_string(font, Vector2(ARROW_INSET, y), "<", HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, colour)
	draw_string(font, Vector2(size.x - ARROW_INSET - right_w, y), ">", HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, colour)


func _pad_styles() -> void:
	_padding = true
	begin_bulk_theme_override()
	for state: String in STATES:
		remove_theme_stylebox_override(state)
	for state: String in STATES:
		var sb: StyleBox = get_theme_stylebox(state)
		if sb == null:
			continue
		var padded: StyleBox = sb.duplicate()
		padded.content_margin_left = sb.get_margin(SIDE_LEFT) + ARROW_PAD
		padded.content_margin_right = sb.get_margin(SIDE_RIGHT) + ARROW_PAD
		add_theme_stylebox_override(state, padded)
	end_bulk_theme_override()
	_padding = false


func _refresh() -> void:
	if values.is_empty():
		text = ""
		return
	text = labels[index] if index < labels.size() else str(values[index])
	queue_redraw()


func _find(v: Variant) -> int:
	for i: int in values.size():
		var a: Variant = values[i]
		var same_kind: bool = typeof(a) == typeof(v) or (GameSettings.is_num(a) and GameSettings.is_num(v))
		if same_kind and a == v:
			return i
	return -1

# {{FOOTER}}
