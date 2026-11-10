# ---------------------------------------------------------------------------
# input_binder.gd
# Purpose : Bridges the kit's binding strings ("key:space", "pad:south", "pad_axis:leftx-", "mouse:left") and
#           Godot's InputMap: applies the settings' bindings to the actions, turns a pressed key or button back
#           into a binding string (rebinding), and gives a readable text label when there is no glyph art.
# Usage   : InputBinder.apply(settings.input.bindings, settings.input.deadzone, settings.input.invert_y)
#           (Shell does this on change)
#           var b := InputBinder.from_event(event)                               # "" when not bindable
#           InputBinder.label(gset, "pad:south")                                 # "A" for the Xbox set
# Notes   : Keys use physical keycodes, so WASD stays in the same place on AZERTY or Dvorak layouts; the label
#           shows what is printed on the player's key. pad: names follow positions (south = bottom face button),
#           so one binding fits Xbox, PlayStation and Nintendo pads. Triggers l2/r2 are axes in Godot.
#           Godot's built-in ui_* actions are replaced by the kit's bindings (ui_accept is Enter and pad south).
#           The left stick: apply() also gives move_left/right/up/down the matching stick direction (#274), so
#           Input.get_vector() and is_action_pressed() follow the stick with the default bindings (d-pad only).
#           invert_y swaps the stick's up and down there; a stick direction the player bound to any game action is
#           left alone. Those actions' deadzone is the player's, at least Analog.STICK_HOLD_MIN, so a drifting
#           stick does not walk the player.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name InputBinder
extends RefCounted

const AXIS_PRESS: float = 0.6 # how far a stick or trigger must move to count as pressed while rebinding
const PAD_BUTTONS: Dictionary = {
	"south": JOY_BUTTON_A, "east": JOY_BUTTON_B, "west": JOY_BUTTON_X, "north": JOY_BUTTON_Y,
	"select": JOY_BUTTON_BACK, "guide": JOY_BUTTON_GUIDE, "start": JOY_BUTTON_START,
	"l3": JOY_BUTTON_LEFT_STICK, "r3": JOY_BUTTON_RIGHT_STICK, "l1": JOY_BUTTON_LEFT_SHOULDER,
	"r1": JOY_BUTTON_RIGHT_SHOULDER, "dpad_up": JOY_BUTTON_DPAD_UP, "dpad_down": JOY_BUTTON_DPAD_DOWN,
	"dpad_left": JOY_BUTTON_DPAD_LEFT, "dpad_right": JOY_BUTTON_DPAD_RIGHT,
}
const PAD_TRIGGERS: Dictionary = {"l2": JOY_AXIS_TRIGGER_LEFT, "r2": JOY_AXIS_TRIGGER_RIGHT}
const PAD_AXES: Dictionary = {"leftx": JOY_AXIS_LEFT_X, "lefty": JOY_AXIS_LEFT_Y, "rightx": JOY_AXIS_RIGHT_X,
		"righty": JOY_AXIS_RIGHT_Y}
const MOUSE_BUTTONS: Dictionary = {"left": MOUSE_BUTTON_LEFT, "right": MOUSE_BUTTON_RIGHT,
		"middle": MOUSE_BUTTON_MIDDLE}
# The left stick direction each move action follows on top of the player's bindings (up is -y)
const MOVE_STICK: Dictionary = {"move_left": "pad_axis:leftx-", "move_right": "pad_axis:leftx+",
		"move_up": "pad_axis:lefty-", "move_down": "pad_axis:lefty+"}


static func apply(bindings: Dictionary, deadzone: float, invert_y: bool = false) -> void:
	for action: String in bindings:
		var dz: float = Analog.hold_deadzone(deadzone) if MOVE_STICK.has(action) else deadzone
		if not InputMap.has_action(action):
			InputMap.add_action(action, dz)
		else:
			InputMap.action_set_deadzone(action, dz)
		InputMap.action_erase_events(action)
		for binding: Variant in bindings[action]:
			var ev: InputEvent = to_event(str(binding))
			if ev != null:
				InputMap.action_add_event(action, ev)
	var sticks: Dictionary = stick_bindings(bindings, invert_y)
	for action: String in sticks:
		InputMap.action_add_event(action, to_event(sticks[action]))


static func stick_bindings(bindings: Dictionary, invert_y: bool) -> Dictionary:
	# {move action: "pad_axis:..."}: the left stick directions apply() adds on top of the player's bindings. None for
	# a move action the bindings lack, or one whose stick direction some game action (no ui_*) is bound to already.
	var taken: Dictionary = {}
	for action: String in bindings:
		if not action.begins_with("ui_"):
			for binding: Variant in bindings[action]:
				taken[str(binding)] = true
	var out: Dictionary = {}
	for action: String in MOVE_STICK:
		var binding: String = MOVE_STICK[action]
		if invert_y and binding.begins_with("pad_axis:lefty"):
			binding = "pad_axis:lefty+" if binding.ends_with("-") else "pad_axis:lefty-"
		if bindings.has(action) and not taken.has(binding):
			out[action] = binding
	return out


static func split(binding: String) -> PackedStringArray:
	# ["kind", "name"]; a binding without ":" is ["kind", ""]
	var colon: int = binding.find(":")
	if colon < 0:
		return PackedStringArray([binding, ""])
	return PackedStringArray([binding.substr(0, colon), binding.substr(colon + 1)])


static func to_event(binding: String) -> InputEvent:
	var parts: PackedStringArray = split(binding)
	var kind: String = parts[0]
	var name: String = parts[1]
	match kind:
		"key":
			var code: Key = OS.find_keycode_from_string(name.replace("_", " "))
			if code == KEY_NONE:
				return null
			var k: InputEventKey = InputEventKey.new()
			k.physical_keycode = code
			return k
		"mouse":
			if not MOUSE_BUTTONS.has(name):
				return null
			var m: InputEventMouseButton = InputEventMouseButton.new()
			m.button_index = MOUSE_BUTTONS[name]
			return m
		"pad":
			if PAD_BUTTONS.has(name):
				var b: InputEventJoypadButton = InputEventJoypadButton.new()
				b.button_index = PAD_BUTTONS[name]
				b.device = -1 # any pad
				return b
			if PAD_TRIGGERS.has(name):
				var t: InputEventJoypadMotion = InputEventJoypadMotion.new()
				t.axis = PAD_TRIGGERS[name]
				t.axis_value = 1.0
				t.device = -1
				return t
		"pad_axis":
			var axis: String = name.trim_suffix("+").trim_suffix("-")
			if PAD_AXES.has(axis) and (name.ends_with("+") or name.ends_with("-")):
				var a: InputEventJoypadMotion = InputEventJoypadMotion.new()
				a.axis = PAD_AXES[axis]
				a.axis_value = 1.0 if name.ends_with("+") else -1.0
				a.device = -1
				return a
	return null


static func from_event(event: InputEvent) -> String:
	# The binding string for a press, or "" (releases, small stick moves, unknown buttons)
	if event is InputEventKey:
		var key: InputEventKey = event
		if not key.pressed or key.echo:
			return ""
		var code: Key = key.physical_keycode if key.physical_keycode != KEY_NONE else key.keycode
		return "key:" + OS.get_keycode_string(code).to_lower().replace(" ", "_")
	if event is InputEventMouseButton:
		var mb: InputEventMouseButton = event
		for name: String in MOUSE_BUTTONS:
			if mb.pressed and MOUSE_BUTTONS[name] == mb.button_index:
				return "mouse:" + name
		return ""
	if event is InputEventJoypadButton:
		var jb: InputEventJoypadButton = event
		for name: String in PAD_BUTTONS:
			if jb.pressed and PAD_BUTTONS[name] == jb.button_index:
				return "pad:" + name
		return ""
	if event is InputEventJoypadMotion:
		var jm: InputEventJoypadMotion = event
		if absf(jm.axis_value) < AXIS_PRESS:
			return ""
		for name: String in PAD_TRIGGERS:
			if PAD_TRIGGERS[name] == jm.axis:
				return "pad:" + name
		for name: String in PAD_AXES:
			if PAD_AXES[name] == jm.axis:
				return "pad_axis:" + name + ("+" if jm.axis_value > 0.0 else "-")
	return ""


static func label(gset: String, binding: String) -> String:
	# English text for a binding (Shell.binding_text() runs it through the string tables)
	if binding == "":
		return ""
	var parts: PackedStringArray = split(binding)
	match parts[0]:
		"key":
			var code: Key = OS.find_keycode_from_string(parts[1].replace("_", " "))
			if code == KEY_NONE:
				return parts[1].capitalize()
			# What the player's own keyboard layout prints on that physical key (no layouts without a window)
			var shown: Key = KEY_NONE
			if DisplayServer.get_name() != "headless":
				shown = DisplayServer.keyboard_get_keycode_from_physical(code)
			return OS.get_keycode_string(shown if shown != KEY_NONE else code)
		"mouse":
			return "Mouse " + parts[1].capitalize()
	# Pad buttons: the face-button name of the active set (A, Cross, South), sticks as "Left Stick"
	var art: String = Bindings.glyph_name(gset, binding)
	if parts[0] == "pad_axis":
		return ("Left Stick " if parts[1].begins_with("left") else "Right Stick ") + parts[1].right(2).to_upper()
	var short: String = art.substr(art.find("_") + 1)
	return short.to_upper() if short.length() <= 2 else short.capitalize() # "LB", "Cross", "Dpad Up"

# {{FOOTER}}
