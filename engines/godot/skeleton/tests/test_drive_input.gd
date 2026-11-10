# ---------------------------------------------------------------------------
# test_drive_input.gd
# Purpose : #276: while a smoke drive runs, a real key or gamepad press or stick (a stray key, a virtual pad on a
#           shared machine) must not reach the game, the shell or the menus; the drive's own presses must; and in
#           normal play the same real event is read as always.
# Usage   : python tools/dev.py test --filter test_drive_input.gd
# Notes   : A real event is played the way the OS delivers it: Input.parse_input_event (Input's state) then the
#           viewport's push_input (every node's _input, then the GUI). SmokeDrive.RealInputGuard is what a drive
#           adds last under the root; Shell is the autoload (its _input is off in a test run, so each test turns it
#           on). The kit's default bindings are applied (InputBinder) and every test puts the input map back.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

const ACTIONS: PackedStringArray = ["move_right", "ui_right", "ui_accept"]

var _guard: Node = null


func before_each() -> void:
	Shell.settings = GameSettings.defaults()
	var input: Dictionary = Shell.settings["input"]
	InputBinder.apply(input["bindings"], float(input["deadzone"]), bool(input["invert_y"]))
	Shell.set_process_input(true) # as in a game run (a test run turns the Shell's _input off)
	Shell.last_device = "pad_xbox"
	Shell.pad_override = {}


func after_each() -> void:
	if is_instance_valid(_guard):
		if _guard.is_inside_tree():
			get_tree().root.remove_child(_guard)
		_guard.free()
	_guard = null
	_stick(0.0)
	for action: String in ACTIONS:
		Input.action_release(action)
	Shell.set_process_input(false)
	Shell.pad_override = {}
	Shell.last_device = "keyboard"
	Shell.settings = GameSettings.defaults()
	InputMap.load_from_project_settings()


func _start_drive() -> void:
	_guard = SmokeDrive.RealInputGuard.new()
	get_tree().root.add_child(_guard)


func _deliver(ev: InputEvent) -> void:
	# what the OS path does: Input first, then the viewport (nodes' _input, the GUI, _unhandled_input)
	Input.parse_input_event(ev)
	Input.flush_buffered_events()
	get_viewport().push_input(ev)


func _key(keycode: Key) -> InputEventKey:
	var ev: InputEventKey = InputEventKey.new()
	ev.keycode = keycode
	ev.physical_keycode = keycode
	ev.pressed = true
	return ev


func _pad_a() -> InputEventJoypadButton:
	var b: InputEventJoypadButton = InputEventJoypadButton.new()
	b.device = 0
	b.button_index = JOY_BUTTON_A
	b.pressed = true
	return b


func _stick(x: float) -> void:
	var m: InputEventJoypadMotion = InputEventJoypadMotion.new()
	m.device = 0
	m.axis = JOY_AXIS_LEFT_X
	m.axis_value = x
	_deliver(m)


func test_normal_play_reads_a_real_key_and_pad() -> void:
	_deliver(_key(KEY_D)) # move_right's key
	assert_true(Input.is_action_pressed("move_right"), "the held key holds move_right")
	assert_eq(Shell.last_device, "keyboard", "the prompts switch to the keyboard")
	_deliver(_pad_a())
	assert_true(Input.is_action_pressed("ui_accept"), "pad A (south) accepts")
	assert_true(Shell.last_device.begins_with("pad"))
	_stick(0.9)
	assert_true(Shell.move_vector().x > 0.5, "the stick steers")


func test_a_drive_ignores_a_real_key() -> void:
	_start_drive()
	_deliver(_key(KEY_D))
	assert_false(Input.is_action_pressed("move_right"), "a real key holds nothing during a drive")
	assert_false(Shell.held_actions().has("move_right"))
	assert_eq(Shell.last_device, "pad_xbox", "the Shell never saw it: the prompts stay where the drive put them")


func test_a_drive_ignores_a_real_gamepad_button_and_stick() -> void:
	_start_drive()
	_deliver(_pad_a())
	assert_false(Input.is_action_pressed("ui_accept"), "a virtual pad's A accepts nothing during a drive")
	_stick(0.9)
	assert_false(Input.is_action_pressed("move_right"), "nor does its stick hold move_right")
	assert_eq(Shell.move_vector(), Vector2.ZERO)
	assert_eq(Shell.pad_axes()["left"], Vector2.ZERO, "the raw stick is not read either (pad_override at rest)")
	Shell.last_device = "keyboard"
	_deliver(_pad_a())
	assert_eq(Shell.last_device, "keyboard", "and the prompts do not switch to it")


func test_the_drives_own_presses_still_pass() -> void:
	_start_drive()
	var a: InputEventAction = InputEventAction.new()
	a.action = "ui_right"
	a.pressed = true
	assert_true(SmokeDrive.RealInputGuard.injected(a), "an action event is always the drive's")
	_deliver(a)
	assert_true(Input.is_action_pressed("ui_right"), "the drive's action press lands")
	var b: InputEventJoypadButton = _pad_a()
	assert_false(SmokeDrive.RealInputGuard.injected(b), "an unmarked pad event is a real one")
	Shell.last_device = "keyboard"
	_deliver(SmokeDrive.RealInputGuard.mark(b))
	assert_true(Input.is_action_pressed("ui_accept"), "the drive's own pad press (a pad access run) lands")
	assert_true(Shell.last_device.begins_with("pad"), "and switches the prompts to the pad")


func test_the_hardware_is_read_again_when_the_drive_ends() -> void:
	_start_drive()
	assert_eq(Shell.pad_axes()["left"], Vector2.ZERO)
	get_tree().root.remove_child(_guard)
	assert_eq(Shell.pad_override, {}, "no stand-in left behind")
	Shell.pad_override = {"left": Vector2(0.5, 0.0)} # a test's own stand-in survives a drive
	get_tree().root.add_child(_guard)
	assert_eq(Shell.pad_axes()["left"], Vector2(0.5, 0.0))
	get_tree().root.remove_child(_guard)
	assert_eq(Shell.pad_override, {"left": Vector2(0.5, 0.0)})

# {{FOOTER}}
