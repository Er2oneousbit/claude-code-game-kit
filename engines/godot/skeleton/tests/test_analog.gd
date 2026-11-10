# ---------------------------------------------------------------------------
# test_analog.gd
# Purpose : Analog input (#274): scripts/core/analog.gd's radial, rescaled stick deadzone, invert_y and trigger
#           deadzone; the left stick InputBinder gives the move_* actions on top of the default (d-pad) bindings;
#           and what the game reads from the Shell: move_vector(), stick(), triggers(), held_actions().
# Usage   : python tools/dev.py test --filter test_analog.gd
# Notes   : The same cases as the Bevy shell's logic/analog.rs tests, with up as -y (Godot's convention). Stick
#           moves are parsed as InputEventJoypadMotion (pad 0); Shell.pad_override stands in for the hardware where
#           the Shell reads joypad axes. Every test puts the input map and the stick back.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

const EPS: float = 0.0001


func after_each() -> void:
	_move_stick(Vector2.ZERO)
	Shell.pad_override = {}
	Shell.settings = GameSettings.defaults()
	InputMap.load_from_project_settings()


func _move_stick(v: Vector2) -> void:
	for axis: JoyAxis in [JOY_AXIS_LEFT_X, JOY_AXIS_LEFT_Y]:
		var ev: InputEventJoypadMotion = InputEventJoypadMotion.new()
		ev.device = 0
		ev.axis = axis
		ev.axis_value = v.x if axis == JOY_AXIS_LEFT_X else v.y
		Input.parse_input_event(ev)
	Input.flush_buffered_events()


func _apply(invert_y: bool = false) -> void:
	var input: Dictionary = Shell.settings["input"]
	input["invert_y"] = invert_y
	InputBinder.apply(input["bindings"], float(input["deadzone"]), invert_y)


func test_the_stick_is_still_inside_the_deadzone_and_rescales_from_zero_past_it() -> void:
	assert_eq(Analog.stick(Vector2(0.15, 0.1), 0.2, false), Vector2.ZERO)
	var x: float = Analog.stick(Vector2(0.21, 0.0), 0.2, false).x # a small push, never a jump to 0.2
	assert_true(x > 0.0 and x < 0.02, str(x))
	assert_almost_eq(Analog.stick(Vector2(0.6, 0.0), 0.2, false), Vector2(0.5, 0.0), Vector2(EPS, EPS))
	assert_almost_eq(Analog.stick(Vector2(1.0, 0.0), 0.2, false), Vector2(1.0, 0.0), Vector2(EPS, EPS))
	var d: Vector2 = Analog.stick(Vector2(1.0, 1.0), 0.2, false) # past full deflection: length 1, direction kept
	assert_almost_eq(d.length(), 1.0, EPS)
	assert_almost_eq(d.x, d.y, EPS)
	assert_almost_eq(Analog.stick(Vector2(-0.3, 0.4), 0.0, false), Vector2(-0.3, 0.4), Vector2(EPS, EPS))


func test_invert_y_flips_only_the_vertical_axis() -> void:
	assert_almost_eq(Analog.stick(Vector2(0.0, -1.0), 0.2, true), Vector2(0.0, 1.0), Vector2(EPS, EPS))
	assert_almost_eq(Analog.stick(Vector2(1.0, 0.0), 0.2, true), Vector2(1.0, 0.0), Vector2(EPS, EPS))


func test_triggers_rescale_past_their_deadzone_and_ignore_bad_values() -> void:
	assert_eq(Analog.trigger(0.04), 0.0)
	assert_eq(Analog.trigger(1.0), 1.0)
	assert_almost_eq(Analog.trigger(0.525), 0.5, EPS)
	assert_eq(Analog.trigger(-0.5, 0.0), 0.0, "a trigger never goes negative")
	assert_eq(Analog.trigger(NAN, 0.0), 0.0)
	assert_eq(Analog.stick(Vector2(NAN, -1.0), 0.0, false), Vector2(0.0, -1.0))
	assert_eq(Analog.hold_deadzone(0.0), Analog.STICK_HOLD_MIN, "a drifting stick never holds a move action")
	assert_eq(Analog.hold_deadzone(0.4), 0.4)


func test_the_move_actions_get_the_stick_unless_a_game_action_has_it() -> void:
	var defaults: Dictionary = Bindings.DEFAULT_BINDINGS.duplicate(true)
	assert_eq_deep(InputBinder.stick_bindings(defaults, false), {"move_left": "pad_axis:leftx-",
			"move_right": "pad_axis:leftx+", "move_up": "pad_axis:lefty-", "move_down": "pad_axis:lefty+"})
	var inverted: Dictionary = InputBinder.stick_bindings(defaults, true)
	assert_eq(inverted["move_up"], "pad_axis:lefty+")
	assert_eq(inverted["move_down"], "pad_axis:lefty-")
	defaults["jump"] = ["key:space", "pad_axis:leftx-"] # the player put jump on the stick
	defaults["ui_right"] = ["key:right", "pad_axis:leftx+"] # menus may share it (another group)
	var taken: Dictionary = InputBinder.stick_bindings(defaults, false)
	assert_false(taken.has("move_left"))
	assert_eq(taken["move_right"], "pad_axis:leftx+")
	defaults.erase("move_up")
	assert_false(InputBinder.stick_bindings(defaults, false).has("move_up"), "no action, no stick")


func test_the_stick_moves_the_player_with_the_default_bindings() -> void:
	_apply()
	_move_stick(Vector2(0.0, -0.6))
	assert_true(Input.is_action_pressed("move_up"), "the stick holds move_up")
	assert_false(Input.is_action_pressed("move_down"))
	assert_almost_eq(Shell.move_vector(), Vector2(0.0, -0.5), Vector2(EPS, EPS))
	assert_eq(Shell.held_actions(), PackedStringArray(["move_up"]))
	_move_stick(Vector2(0.1, 0.0)) # drift: inside the deadzone
	assert_eq(Shell.move_vector(), Vector2.ZERO)
	assert_eq(Shell.held_actions(), PackedStringArray([]))


func test_invert_y_flips_the_stick_but_not_the_keys() -> void:
	_apply(true)
	_move_stick(Vector2(0.0, -1.0))
	assert_true(Input.is_action_pressed("move_down"), "stick up is down with invert_y")
	assert_almost_eq(Shell.move_vector(), Vector2(0.0, 1.0), Vector2(EPS, EPS))
	_move_stick(Vector2.ZERO)
	Input.action_press("move_up") # what the W key does
	assert_almost_eq(Shell.move_vector(), Vector2(0.0, -1.0), Vector2(EPS, EPS))
	Input.action_release("move_up")


func test_the_shell_shapes_the_raw_stick_and_triggers() -> void:
	Shell.pad_override = {"left": Vector2(0.6, 0.0), "left_trigger": 0.525, "right_trigger": 1.0}
	assert_almost_eq(Shell.stick(), Vector2(0.5, 0.0), Vector2(EPS, EPS))
	assert_almost_eq(Shell.triggers(), Vector2(0.5, 1.0), Vector2(EPS, EPS))
	(Shell.settings["input"] as Dictionary)["invert_y"] = true
	Shell.pad_override = {"left": Vector2(0.0, -1.0)}
	assert_almost_eq(Shell.stick(), Vector2(0.0, 1.0), Vector2(EPS, EPS))
	assert_eq(Shell.triggers(), Vector2.ZERO, "missing values read as rest")

# {{FOOTER}}
