# ---------------------------------------------------------------------------
# settings_screen.gd
# Purpose : The settings screen: tabs for Display, Audio, Controls, Accessibility, Language and Privacy, one row
#           per settings field (built from GameSettings.SCHEMA), rebinding with "press a key", conflicts shown as
#           swaps, Reset to defaults. Back (or cancel) saves settings.json.
# Usage   : front.open_settings()   (from the main menu or the pause menu)
# Notes   : Changes apply at once (Shell.set_value); Back writes the file. Focus: left/right on the tab row picks a
#           tab, down enters it, up from the first row returns to the tabs; sliders and pickers use left/right,
#           switches use accept. The focused row gets an outline (UiTheme.focus_row). While a binding waits for
#           input, Escape (or REBIND_TIMEOUT_S) cancels. Slot 0 takes keys and mouse buttons, slot 1 pad input.
#           Field names come from the strings setting.<section>.<field>; choices from value.<field>.<choice>.
#
# Pseudocode:
#   build: title, tab buttons, a scroll area holding the current tab's rows, Back
#   tab rows: per schema field a label + control (switch / slider + value / picker); Controls adds one row per
#     action: name, prompt glyph, keyboard slot, pad slot; then Reset
#   link focus explicitly (rows in a column, Back last, tabs on top) so keys and the d-pad never get lost
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name SettingsScreen
extends ShellScreen

const TABS: PackedStringArray = ["display", "audio", "controls", "access", "language", "privacy"]
const TAB_SECTIONS: Dictionary = {"display": "display", "audio": "audio", "access": "access"}
const CONTROLS_FIELDS: PackedStringArray = ["deadzone", "invert_y", "glyphs"]
const CONTROL_WIDTH: int = 150
const VALUE_WIDTH: int = 46
const BIND_WIDTH: int = 96
const GLYPH_PX: int = 16 # glyph art is drawn at the largest whole multiple of its size that fits this height
const STEPS: Dictionary = {"display.ui_scale": 0.25, "access.text_scale": 0.25} # slider steps; others DEFAULT_STEP
const DEFAULT_STEP: float = 0.05
const TIMES_FIELDS: PackedStringArray = ["display.ui_scale", "access.text_scale"] # shown as 1.25x, others as %
const RESOLUTIONS: Array = [[1280, 720], [1600, 900], [1920, 1080], [2560, 1440], [3840, 2160]]
const REBIND_TIMEOUT_S: float = 6.0

const PRESETS_FILE: String = "res://data/input/presets.json" # the one-handed layouts (#166)
const PRESET_NAMES: PackedStringArray = ["one_hand_left", "one_hand_right"]
var _tab: String = "display"
var _tab_buttons: Dictionary = {}
var _content: VBoxContainer
var _back: Button
var _status: Label
var _grid: Array = [] # focusable controls of the current tab, one Array per row, top to bottom
var _capture: Array = [] # [action, slot] while waiting for a key or button
var _capture_left: float = 0.0
var _status_text: String = ""


func _init(p_front: FrontEnd) -> void:
	super(p_front, "settings")


func build() -> void:
	var col: VBoxContainer = margin_box()
	col.add_child(label(Shell.t("settings.title"), UiTheme.HEADING_FONT, "Heading"))
	# a flow, not a row: at 200 % text the six tabs wrap to a second line instead of pushing the screen wider
	# (tools/access/sweep.py found "Privacy" and the title off screen, #91)
	var tabs: HFlowContainer = HFlowContainer.new()
	tabs.name = "Tabs"
	tabs.add_theme_constant_override("h_separation", 4)
	tabs.add_theme_constant_override("v_separation", 4)
	col.add_child(tabs)
	_tab_buttons.clear()
	for tab: String in TABS:
		var b: Button = Button.new()
		b.name = "Tab_" + tab
		b.text = Shell.t("settings.tab." + tab)
		b.toggle_mode = true
		b.focus_entered.connect(_select_tab.bind(tab))
		b.pressed.connect(_select_tab.bind(tab))
		tabs.add_child(b)
		_tab_buttons[tab] = b
	for i: int in TABS.size(): # left and right walk the tabs in order, also across a wrap
		var b: Button = _tab_buttons[TABS[i]]
		b.focus_neighbor_right = NodePath("../Tab_" + TABS[(i + 1) % TABS.size()])
		b.focus_neighbor_left = NodePath("../Tab_" + TABS[(i - 1 + TABS.size()) % TABS.size()])
	var scroll: ScrollContainer = ScrollContainer.new()
	scroll.name = "Scroll"
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.follow_focus = true
	col.add_child(scroll)
	_content = VBoxContainer.new()
	_content.name = "Rows"
	_content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_content.add_theme_constant_override("separation", 2)
	scroll.add_child(_content)
	var bottom: HBoxContainer = HBoxContainer.new()
	col.add_child(bottom)
	_back = button(Shell.t("settings.back"), "Back", _close)
	bottom.add_child(_back)
	_status = label("", 1.0, "Status") # rebinding messages: next to Back, so they are always on screen
	_status.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_status.modulate = UiTheme.FOCUS
	bottom.add_child(_status)
	_fill_tab()


func focus_first() -> void:
	(_tab_buttons[_tab] as Control).grab_focus()


func current_tab() -> String:
	return _tab


func capturing() -> bool:
	return not _capture.is_empty()


func on_cancel() -> void:
	if capturing():
		_end_capture("")
	else:
		_close()


func _close() -> void:
	if capturing():
		_end_capture("")
	Shell.save_settings()
	front.back()


func _select_tab(tab: String) -> void:
	if tab == _tab and _content.get_child_count() > 0:
		_mark_tabs()
		return
	_tab = tab
	_status_text = ""
	_fill_tab()


func _mark_tabs() -> void:
	for tab: String in _tab_buttons:
		(_tab_buttons[tab] as Button).set_pressed_no_signal(tab == _tab)


func _fill_tab() -> void:
	for child: Node in _content.get_children():
		_content.remove_child(child)
		child.queue_free()
	_grid.clear()
	_status.text = _status_text if _tab == "controls" else ""
	_mark_tabs()
	match _tab:
		"display", "audio", "access":
			for field: String in GameSettings.SCHEMA[TAB_SECTIONS[_tab]]:
				_add_field(TAB_SECTIONS[_tab], field)
		"controls":
			for field: String in CONTROLS_FIELDS:
				_add_field("input", field)
			_add_bindings()
		"language":
			_add_language()
		"privacy":
			_add_field("telemetry", "consent")
			var note: Label = label(Shell.t("privacy.note"), 1.0, "PrivacyNote")
			note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
			note.modulate = UiTheme.TEXT_DIM
			_content.add_child(note)
	_link_focus()


# ---- rows -----------------------------------------------------------------------

func _row(field_id: String, title: String) -> HBoxContainer:
	# A row: a panel that outlines itself while one of its controls has focus, holding a label and controls
	var panel: PanelContainer = PanelContainer.new()
	panel.name = "Row_" + field_id
	panel.add_theme_stylebox_override("panel", UiTheme.empty_row())
	_content.add_child(panel)
	var row: HBoxContainer = HBoxContainer.new()
	row.add_theme_constant_override("separation", 6)
	panel.add_child(row)
	var name_label: Label = label(title, 1.0, "Label")
	name_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	name_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	name_label.custom_minimum_size.x = 60
	row.add_child(name_label)
	return row


func _watch_focus(c: Control, row: HBoxContainer) -> void:
	var panel: PanelContainer = row.get_parent()
	c.focus_entered.connect(func() -> void: panel.add_theme_stylebox_override("panel", UiTheme.focus_row()))
	c.focus_exited.connect(func() -> void: panel.add_theme_stylebox_override("panel", UiTheme.empty_row()))


func _add_field(section: String, field: String) -> void:
	var rule: Array = GameSettings.SCHEMA[section][field]
	var current: Variant = Shell.settings[section][field]
	var row: HBoxContainer = _row("%s_%s" % [section, field], Shell.t("setting.%s.%s" % [section, field]))
	var control: Control
	var value_label: Label = label("", 1.0, "Value")
	value_label.custom_minimum_size.x = VALUE_WIDTH
	value_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	match str(rule[0]):
		"bool":
			var sw: CheckButton = CheckButton.new()
			sw.button_pressed = bool(current)
			sw.text = Shell.t("value.on" if bool(current) else "value.off")
			sw.toggled.connect(func(on: bool) -> void:
				sw.text = Shell.t("value.on" if on else "value.off")
				Shell.set_value(section, field, on))
			control = sw
		"num":
			var slider: FocusSlider = FocusSlider.new() # an HSlider with a focus outline
			slider.min_value = float(rule[1])
			slider.max_value = float(rule[2])
			slider.step = float(STEPS.get("%s.%s" % [section, field], DEFAULT_STEP))
			slider.value = float(current)
			slider.size_flags_vertical = Control.SIZE_SHRINK_CENTER
			value_label.text = _num_text(section, field, float(current))
			slider.value_changed.connect(func(v: float) -> void:
				value_label.text = _num_text(section, field, v)
				Shell.set_value(section, field, v))
			control = slider
		"enum", "res":
			var stepper: OptionStepper = OptionStepper.new()
			var choices: Array = RESOLUTIONS.duplicate(true) if rule[0] == "res" else (rule[1] as Array).duplicate()
			var names: PackedStringArray = []
			if rule[0] == "res" and not _has_resolution(choices, current):
				choices.append(current)
			for v: Variant in choices:
				names.append(_choice_text(field, v))
			stepper.setup(choices, names, current)
			stepper.changed.connect(func(v: Variant) -> void: Shell.set_value(section, field, v))
			control = stepper
	control.name = "Setting_%s_%s" % [section, field]
	control.custom_minimum_size.x = CONTROL_WIDTH
	row.add_child(control)
	row.add_child(value_label)
	_watch_focus(control, row)
	_grid.append([control])


func _add_language() -> void:
	var row: HBoxContainer = _row("language", Shell.t("setting.language"))
	var codes: PackedStringArray = Shell.locales()
	var names: PackedStringArray = []
	for code: String in codes:
		names.append(Shell.t("lang." + code, {}, code))
	var stepper: OptionStepper = OptionStepper.new()
	stepper.name = "Setting_language"
	stepper.custom_minimum_size.x = CONTROL_WIDTH
	stepper.setup(Array(codes), names, Shell.locale)
	stepper.changed.connect(func(code: Variant) -> void: Shell.set_language(str(code)))
	row.add_child(stepper)
	_watch_focus(stepper, row)
	_grid.append([stepper])
	var note: Label = label(Shell.t("language.note"), 1.0, "LanguageNote")
	note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	note.modulate = UiTheme.TEXT_DIM
	_content.add_child(note)


func _add_bindings() -> void:
	var gset: String = Shell.glyph_set()
	var pad_set: String = "generic" if gset == "keyboard" else gset
	var bindings: Dictionary = Shell.bindings()
	var clashes: PackedStringArray = Bindings.duplicates(bindings)
	var head: Label = label(Shell.t("controls.bindings"), 1.0, "BindingsHeading")
	head.modulate = UiTheme.TEXT_DIM
	_content.add_child(head)
	for action: String in Bindings.ACTION_ORDER:
		if not bindings.has(action):
			continue
		var title: String = Shell.t("action." + action)
		if clashes.has(action):
			title += " " + Shell.t("controls.conflict")
		var row: HBoxContainer = _row("bind_" + action, title)
		row.add_child(_glyph_view(Shell.prompt_for(action), gset))
		var slots: Array = []
		for slot: int in 2:
			var lst: Array = bindings[action]
			var binding: String = str(lst[slot]) if slot < lst.size() else ""
			var b: Button = Button.new()
			b.name = "Bind_%s_%d" % [action, slot]
			b.custom_minimum_size.x = BIND_WIDTH
			b.text = Shell.binding_text(binding, "keyboard" if slot == 0 else pad_set)
			b.pressed.connect(_start_capture.bind(action, slot))
			row.add_child(b)
			_watch_focus(b, row)
			slots.append(b)
		_grid.append(slots)
	var reset_row: HFlowContainer = HFlowContainer.new() # wraps at 200 % text
	_content.add_child(reset_row)
	var reset: Button = button(Shell.t("controls.reset"), "ResetBindings", _reset_bindings)
	reset_row.add_child(reset)
	# one-handed layouts (#166, motor access), from data/input/presets.json
	var row: Array = [reset]
	for preset: String in PRESET_NAMES:
		var b: Button = button(Shell.t("controls.preset." + preset), "Preset_" + preset, _apply_preset.bind(preset))
		reset_row.add_child(b)
		row.append(b)
	_grid.append(row)


func _glyph_view(binding: String, gset: String) -> Control:
	var tex: Texture2D = Shell.glyph_texture(binding, gset)
	if tex != null:
		var view: TextureRect = TextureRect.new()
		view.name = "Glyph"
		view.texture = tex
		view.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
		view.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		view.stretch_mode = TextureRect.STRETCH_SCALE
		var k: int = maxi(1, floori(float(GLYPH_PX) / maxf(1.0, tex.get_height()))) # whole multiples only
		view.custom_minimum_size = tex.get_size() * k
		var cell: CenterContainer = CenterContainer.new() # same width as the text fallback, so columns line up
		cell.custom_minimum_size.x = VALUE_WIDTH
		cell.add_child(view)
		return cell
	var text: Label = label(Shell.binding_text(binding, gset), 1.0, "Glyph")
	text.custom_minimum_size.x = VALUE_WIDTH
	text.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	text.modulate = UiTheme.TEXT_DIM
	return text


# ---- rebinding --------------------------------------------------------------------

func _start_capture(action: String, slot: int) -> void:
	_capture = [action, slot]
	_capture_left = REBIND_TIMEOUT_S
	var b: Button = _content.find_child("Bind_%s_%d" % [action, slot], true, false)
	b.text = Shell.t("controls.press_key" if slot == 0 else "controls.press_button")
	_status.text = Shell.t("controls.capture_hint")


func _end_capture(binding: String) -> void:
	var action: String = _capture[0]
	var slot: int = _capture[1]
	_capture = []
	_status_text = ""
	if binding != "":
		var result: Dictionary = Bindings.rebind(Shell.bindings(), action, slot, binding)
		if not result.is_empty():
			Shell.set_bindings(result["bindings"])
			var swapped: PackedStringArray = []
			for c: Array in result["conflicts"]:
				swapped.append(Shell.t("action." + str(c[0])))
			_status_text = Shell.t("controls.swapped", {"actions": ", ".join(swapped)}) if not swapped.is_empty() \
					else Shell.t("controls.bound", {"action": Shell.t("action." + action),
							"binding": Shell.binding_text(binding)})
	_fill_tab()
	_focus_named("Bind_%s_%d" % [action, slot])


## Every action from the preset, the rest from the defaults; the player can rebind anything after.
func _apply_preset(preset: String) -> void:
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(PRESETS_FILE))
	if typeof(parsed) != TYPE_DICTIONARY or not (parsed.get("presets", {}) as Dictionary).has(preset):
		push_warning("%s has no preset %s" % [PRESETS_FILE, preset])
		return
	var bindings: Dictionary = Bindings.defaults()
	var chosen: Dictionary = parsed["presets"][preset]["bindings"]
	for action: String in chosen:
		bindings[action] = (chosen[action] as Array).duplicate()
	Shell.set_bindings(bindings)
	_status_text = Shell.t("controls.preset_done")
	_fill_tab()
	_focus_named("Preset_" + preset)


func _reset_bindings() -> void:
	Shell.set_bindings(Bindings.defaults())
	_status_text = Shell.t("controls.reset_done")
	_fill_tab()
	_focus_named("ResetBindings")


func _input(event: InputEvent) -> void:
	if not capturing() or not is_top():
		return
	if event is InputEventKey and (event as InputEventKey).pressed and (event as InputEventKey).keycode == KEY_ESCAPE:
		get_viewport().set_input_as_handled()
		_end_capture("")
		return
	var binding: String = InputBinder.from_event(event)
	if binding == "":
		if event is InputEventKey or event is InputEventJoypadButton or event is InputEventAction:
			get_viewport().set_input_as_handled() # nothing else reacts while we wait
		return
	var is_pad: bool = binding.begins_with("pad")
	if is_pad == (int(_capture[1]) == 1):
		get_viewport().set_input_as_handled()
		_end_capture(binding)


func _process(delta: float) -> void:
	if capturing():
		_capture_left -= delta
		if _capture_left <= 0.0:
			_end_capture("")


# ---- helpers ----------------------------------------------------------------------

func _link_focus() -> void:
	# Explicit neighbours: up/down walk the rows (same column when the row has one), Back is last, tabs on top
	var tab_button: Control = _tab_buttons[_tab]
	var first: Control = _grid[0][0] if not _grid.is_empty() else _back
	for tab: String in _tab_buttons:
		var tb: Control = _tab_buttons[tab]
		tb.focus_neighbor_bottom = tb.get_path_to(first)
		tb.focus_neighbor_top = tb.get_path_to(_back)
	for r: int in _grid.size():
		var cells: Array = _grid[r]
		for col: int in cells.size():
			var c: Control = cells[col]
			var up: Control = tab_button if r == 0 else _pick(_grid[r - 1], col)
			var down: Control = _back if r == _grid.size() - 1 else _pick(_grid[r + 1], col)
			c.focus_neighbor_top = c.get_path_to(up)
			c.focus_neighbor_bottom = c.get_path_to(down)
			c.focus_neighbor_left = c.get_path_to(cells[col - 1] if col > 0 else c)
			c.focus_neighbor_right = c.get_path_to(cells[col + 1] if col + 1 < cells.size() else c)
	var last: Control = _pick(_grid[_grid.size() - 1], 0) if not _grid.is_empty() else tab_button
	_back.focus_neighbor_top = _back.get_path_to(last)
	_back.focus_neighbor_bottom = _back.get_path_to(tab_button)


func _pick(cells: Array, col: int) -> Control:
	return cells[mini(col, cells.size() - 1)]


func _num_text(section: String, field: String, v: float) -> String:
	if TIMES_FIELDS.has("%s.%s" % [section, field]):
		return Shell.t("fmt.times", {"n": snappedf(v, 0.01)})
	return Shell.t("fmt.percent", {"n": roundi(v * 100.0)})


func _choice_text(field: String, v: Variant) -> String:
	match field:
		"frame_cap":
			return Shell.t("value.frame_cap.off") if int(v) == 0 else Shell.t("fmt.fps", {"n": int(v)})
		"resolution":
			return Shell.t("fmt.resolution", {"w": int(v[0]), "h": int(v[1])})
	return Shell.t("value.%s.%s" % [field, v])


func _has_resolution(choices: Array, v: Variant) -> bool:
	for c: Array in choices:
		if typeof(v) == TYPE_ARRAY and (v as Array).size() == 2 and int(c[0]) == int(v[0]) and int(c[1]) == int(v[1]):
			return true
	return false

# {{FOOTER}}
