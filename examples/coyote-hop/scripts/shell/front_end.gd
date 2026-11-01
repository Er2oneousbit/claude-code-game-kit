# ---------------------------------------------------------------------------
# front_end.gd
# Purpose : The screen flow: boot -> title -> main menu -> settings / credits / play (through the loading screen)
#           / juice demo, the pause menu over play, and back again. Owns the menu layer, the theme and the world
#           node that holds the running game.
# Usage   : scripts/game/main.gd adds one: add_child(FrontEnd.new())
#           Screens call front.open_settings(), front.start_play(), front.back(), front.pause(), ...
# Notes   : Screens are a stack: push shows a screen over the last one (hidden while covered), back() pops it, and
#           cancel always means back(). The world node pauses with the tree; this node and the menus keep running.
#           The pause action, or losing window focus, pauses play. In a smoke run with --locale pseudo every screen
#           is checked by LabelAudit once it is shown; a problem prints PSEUDO_FAIL and exits 1.
#           --drive <scenario> adds a SmokeDrive (scripts/shell/smoke_drive.gd).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name FrontEnd
extends Node

signal screen_shown(screen_name: String)

const PLAY_SCENE: String = "res://scenes/play.tscn"
const UI_LAYER: int = 10
const AUDIT_SETTLE_FRAMES: int = 3 # containers lay out over a frame or two

var consent_asked: bool = false # the telemetry question is asked once per launch
var ui_theme: Theme
var world: Node
var world_node: Node = null
var world_name: String = ""
var ui_layer: CanvasLayer
var ui_root: Control
var stack: Array[ShellScreen] = []
var audited_screens: int = 0
var _look: String = "" # text and UI scale the theme was built for


func _ready() -> void:
	name = "FrontEnd"
	process_mode = Node.PROCESS_MODE_ALWAYS
	world = Node.new()
	world.name = "World"
	world.process_mode = Node.PROCESS_MODE_PAUSABLE
	add_child(world)
	ui_layer = CanvasLayer.new()
	ui_layer.name = "UI"
	ui_layer.layer = UI_LAYER
	add_child(ui_layer)
	Shell.apply_all() # the kit's front end owns the window and the input map
	ui_root = Control.new()
	ui_root.name = "Root"
	ui_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	ui_layer.add_child(ui_root)
	_apply_look()
	get_viewport().size_changed.connect(_layout)
	Shell.settings_changed.connect(_on_settings_changed)
	Shell.locale_changed.connect(rebuild_all)
	Shell.focus_lost.connect(_on_focus_lost)
	screen_shown.connect(_on_screen_shown)
	show_title()
	if Shell.drive != "":
		add_child(SmokeDrive.new(self))


func _unhandled_input(event: InputEvent) -> void:
	if world_node != null and stack.is_empty() and event.is_action_pressed("pause"):
		get_viewport().set_input_as_handled()
		pause()


# ---- the stack ----------------------------------------------------------------

func top() -> ShellScreen:
	return stack.back() if not stack.is_empty() else null


func current_name() -> String:
	return top().screen_name if top() != null else world_name


func push(screen: ShellScreen) -> void:
	var covered: ShellScreen = top()
	if covered != null:
		covered.remember_focus()
		covered.hide()
	stack.append(screen)
	ui_root.add_child(screen)
	screen.focus_first()
	_shown()


func replace(screen: ShellScreen) -> void:
	_clear_stack()
	push(screen)


func back() -> void:
	var t: ShellScreen = top()
	if t == null:
		return
	if t is PauseMenu:
		resume()
		return
	if stack.size() <= 1:
		return # the title has nothing behind it
	stack.pop_back()
	ui_root.remove_child(t)
	t.queue_free()
	var under: ShellScreen = top()
	under.show()
	under.restore_focus()
	_shown()


func rebuild_all() -> void:
	for s: ShellScreen in stack:
		s.rebuild()
	if world_node != null and world_node.has_method("relabel"):
		world_node.relabel()


# ---- screens ------------------------------------------------------------------

func show_title() -> void:
	get_tree().paused = false
	_clear_world()
	replace(TitleScreen.new(self))


func open_main_menu() -> void:
	push(MainMenu.new(self))


func open_settings() -> void:
	push(SettingsScreen.new(self))


func open_credits() -> void:
	push(CreditsScreen.new(self))


func start_play() -> void:
	replace(LoadingScreen.new(self, PLAY_SCENE))


func start_juice() -> void:
	enter_world(JuiceDemo.new(), "juice")


func enter_world(node: Node, world_label: String) -> void:
	_clear_stack()
	_clear_world()
	world_node = node
	world_name = world_label
	world.add_child(node)
	if node.has_method("apply_theme"):
		node.apply_theme(ui_theme)
	Shell.telemetry("play_start", world_label)
	_shown()


func pause() -> void:
	if world_node == null or not stack.is_empty():
		return
	get_tree().paused = true
	push(PauseMenu.new(self))


func resume() -> void:
	var t: ShellScreen = top()
	if t is PauseMenu:
		stack.pop_back()
		ui_root.remove_child(t)
		t.queue_free()
	get_tree().paused = false
	_shown()


func quit_to_title() -> void:
	show_title()


func quit_game() -> void:
	Log.info("shell", "quit")
	get_tree().quit()


# ---- pseudo-locale check ------------------------------------------------------

func audit_now(where: String) -> bool:
	# Prints PSEUDO_FAIL lines and exits 1 on any problem (only used in smoke runs)
	audited_screens += 1
	var problems: PackedStringArray = LabelAudit.audit(get_tree().root)
	for p: String in problems:
		Log.raw("PSEUDO_FAIL %s: %s" % [where, p])
	if not problems.is_empty():
		Log.raw("DRIVE_FAIL pseudo check: %d problem(s) on %s" % [problems.size(), where])
		get_tree().quit(1)
	return problems.is_empty()


# ---- internals ----------------------------------------------------------------

func _shown() -> void:
	var now: String = current_name()
	Shell.current_screen = now
	Shell.telemetry("screen", now)
	screen_shown.emit(now)


func _on_screen_shown(screen: String) -> void:
	if not (Shell.smoke and Shell.locale == I18n.PSEUDO_LOCALE):
		return
	for i: int in AUDIT_SETTLE_FRAMES:
		await get_tree().process_frame
	if current_name() == screen:
		audit_now(screen)


func _clear_stack() -> void:
	for s: ShellScreen in stack:
		ui_root.remove_child(s)
		s.queue_free()
	stack.clear()


func _clear_world() -> void:
	if world_node != null:
		world.remove_child(world_node) # the play scene saves in _exit_tree
		world_node.queue_free()
	world_node = null
	world_name = ""


func _on_focus_lost() -> void:
	pause()


func _on_settings_changed(_section: String, key: String) -> void:
	if key == "text_scale" or key == "ui_scale":
		_apply_look()


func _apply_look() -> void:
	var text_scale: float = float(Shell.access("text_scale"))
	var look: String = "%s|%s" % [text_scale, Shell.settings["display"]["ui_scale"]]
	if look == _look:
		return
	_look = look
	ui_theme = UiTheme.make(text_scale)
	ui_root.theme = ui_theme
	if world_node != null and world_node.has_method("apply_theme"):
		world_node.apply_theme(ui_theme)
	_layout()


func _layout() -> void:
	var s: float = float(Shell.settings["display"]["ui_scale"])
	ui_layer.scale = Vector2(s, s)
	ui_root.position = Vector2.ZERO
	ui_root.size = get_viewport().get_visible_rect().size / s
