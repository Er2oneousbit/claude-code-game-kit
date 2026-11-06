# ---------------------------------------------------------------------------
# ui_theme.gd
# Purpose : The look of the menus: assets/ui/theme_<name>.tres when there is one (Dotwork's UI kit, tools/art/dotwork,
#           the widgets lane, makes them), otherwise a plain built-in theme with a clearly visible focus outline,
#           scaled by the player's text size.
# Usage   : ui_root.theme = UiTheme.make(Shell.access("text_scale"))
#           panel.add_theme_stylebox_override("panel", UiTheme.focus_row())   # outline a focused settings row
# Notes   : The first theme_*.tres in assets/ui/ (sorted by name) wins; delete or rename it to get the plain theme
#           back. The focus state is a 2 px outline (a shape change, not only a colour change) so it reads for
#           colour-blind players and on a TV. Sizes are in pixels of the 640x360 base resolution.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name UiTheme
extends RefCounted

const THEME_DIR: String = "res://assets/ui"
const THEME_PREFIX: String = "theme_"
const BASE_FONT_SIZE: int = 12
const MIN_FONT_SIZE: int = 6
const TITLE_FONT: float = 2.5 # title size as a multiple of the body font
const HEADING_FONT: float = 1.5
const HEADING_TYPE: StringName = &"HeadingLabel" # theme variations carrying those sizes
const TITLE_TYPE: StringName = &"TitleLabel"
const BG: Color = Color(0.08, 0.09, 0.15)
const PANEL: Color = Color(0.12, 0.14, 0.22, 0.96)
const BUTTON: Color = Color(0.17, 0.19, 0.31)
const BUTTON_HOVER: Color = Color(0.23, 0.26, 0.42)
const BUTTON_PRESSED: Color = Color(0.30, 0.34, 0.55)
const BORDER: Color = Color(0.32, 0.36, 0.52)
const TEXT: Color = Color(0.91, 0.93, 0.97)
const TEXT_DIM: Color = Color(0.62, 0.66, 0.78)
const FOCUS: Color = Color(1.0, 0.82, 0.40) # outline colour of the focused control
const FOCUS_WIDTH: int = 2
const BUTTON_TYPES: PackedStringArray = ["Button", "CheckButton", "CheckBox", "OptionButton"]


static func find_theme_file() -> String:
	if not DirAccess.dir_exists_absolute(THEME_DIR):
		return ""
	var found: PackedStringArray = []
	for file: String in DirAccess.get_files_at(THEME_DIR):
		var name: String = file.trim_suffix(".remap")
		if name.begins_with(THEME_PREFIX) and name.ends_with(".tres"):
			found.append(THEME_DIR.path_join(name))
	found.sort()
	return found[0] if not found.is_empty() else ""


static func make(text_scale: float) -> Theme:
	var theme: Theme = null
	var file: String = find_theme_file()
	if file != "":
		var loaded: Theme = load(file) as Theme
		if loaded != null:
			theme = loaded.duplicate(true)
	if theme == null:
		theme = plain()
	var base: int = theme.default_font_size if theme.has_default_font_size() else BASE_FONT_SIZE
	theme.default_font_size = maxi(MIN_FONT_SIZE, roundi(base * text_scale))
	# headings and titles are theme variations, so a text-size change resizes them on the open screen too (a size
	# fixed when the label was built stayed small: tools/access/sweep.py, #91)
	for variation: Array in [[HEADING_TYPE, HEADING_FONT], [TITLE_TYPE, TITLE_FONT]]:
		theme.set_type_variation(variation[0], "Label")
		theme.set_font_size("font_size", variation[0], roundi(theme.default_font_size * float(variation[1])))
	return theme


static func plain() -> Theme:
	var th: Theme = Theme.new()
	th.default_font_size = BASE_FONT_SIZE
	var focus: StyleBoxFlat = focus_box()
	for type: String in BUTTON_TYPES:
		th.set_stylebox("normal", type, _box(BUTTON, BORDER))
		th.set_stylebox("hover", type, _box(BUTTON_HOVER, BORDER))
		th.set_stylebox("pressed", type, _box(BUTTON_PRESSED, TEXT_DIM)) # selected tab: not the focus colour
		th.set_stylebox("hover_pressed", type, _box(BUTTON_PRESSED, TEXT_DIM))
		th.set_stylebox("disabled", type, _box(BUTTON.darkened(0.3), BORDER.darkened(0.3)))
		th.set_stylebox("focus", type, focus)
		th.set_color("font_color", type, TEXT)
		th.set_color("font_hover_color", type, TEXT)
		th.set_color("font_pressed_color", type, TEXT)
		th.set_color("font_hover_pressed_color", type, TEXT)
		th.set_color("font_focus_color", type, FOCUS)
		th.set_color("font_disabled_color", type, TEXT_DIM)
	th.set_color("font_color", "Label", TEXT)
	th.set_stylebox("panel", "PanelContainer", _box(PANEL, BORDER, 8))
	th.set_stylebox("panel", "Panel", _box(PANEL, BORDER, 8))
	var track: StyleBoxFlat = _box(BUTTON, BORDER, 0)
	track.content_margin_top = 3
	track.content_margin_bottom = 3
	th.set_stylebox("slider", "HSlider", track)
	th.set_stylebox("grabber_area", "HSlider", _box(BUTTON_PRESSED, BUTTON_PRESSED, 0))
	th.set_stylebox("grabber_area_highlight", "HSlider", _box(FOCUS.darkened(0.2), FOCUS.darkened(0.2), 0))
	th.set_stylebox("focus", "HSlider", focus) # Slider draws none itself: FocusSlider draws this one
	th.set_stylebox("background", "ProgressBar", _box(BUTTON, BORDER, 0))
	th.set_stylebox("fill", "ProgressBar", _box(FOCUS.darkened(0.15), FOCUS.darkened(0.15), 0))
	return th


static func focus_box() -> StyleBoxFlat:
	var sb: StyleBoxFlat = StyleBoxFlat.new()
	sb.draw_center = false
	sb.set_border_width_all(FOCUS_WIDTH)
	sb.border_color = FOCUS
	sb.set_corner_radius_all(3)
	sb.set_expand_margin_all(2)
	return sb


static func focus_row() -> StyleBoxFlat:
	# Behind a settings row whose control has focus: outline plus a slightly lighter background
	var sb: StyleBoxFlat = _box(Color(BUTTON_HOVER, 0.45), FOCUS, 3)
	sb.set_border_width_all(FOCUS_WIDTH)
	return sb


static func empty_row() -> StyleBoxFlat:
	var sb: StyleBoxFlat = _box(Color(0, 0, 0, 0), Color(0, 0, 0, 0), 3)
	sb.set_border_width_all(FOCUS_WIDTH) # same size as focus_row, so rows do not jump
	return sb


static func backdrop() -> Color:
	return BG


static func _box(fill: Color, border: Color, pad: int = 6) -> StyleBoxFlat:
	var sb: StyleBoxFlat = StyleBoxFlat.new()
	sb.bg_color = fill
	sb.border_color = border
	sb.set_border_width_all(1)
	sb.set_corner_radius_all(3)
	sb.content_margin_left = pad
	sb.content_margin_right = pad
	sb.content_margin_top = maxi(1, pad / 3)
	sb.content_margin_bottom = maxi(1, pad / 3)
	return sb
