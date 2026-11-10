# ---------------------------------------------------------------------------
# play.gd
# Purpose : PROTOTYPE placeholder for the game itself (scenes/play.tscn): a square you move around, saved in
#           save slot 1 when you leave, so the front end, pause menu, loading screen and save files have
#           something real to work with.
# Usage   : Main menu > Play (through the loading screen). Move with move_left/right/up/down, pause with pause.
# Notes   : Replace this scene with your game. Keep the pattern: game time = delta * Shell.game_speed(), strings
#           through Shell.t(), save through SaveStore in _exit_tree() (FrontEnd removes the scene on Quit to
#           title), apply_theme() for HUD controls (a CanvasLayer does not inherit the menu theme), movement from
#           Shell.move_vector() (keys, d-pad and the analog stick; Shell.triggers() and Shell.held_actions() too).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends Node2D

const SAVE_SLOT: int = 1
const SPEED: float = 90.0 # px per second
const PLAYER_SIZE: Vector2 = Vector2(12, 12)
const START: Vector2 = Vector2(314, 200)
const ARENA: Rect2 = Rect2(20, 60, 600, 280)
const HUD_LAYER: int = 5
const HUD_MARGIN: int = 10
const FLOOR_COLOR: Color = Color(0.14, 0.17, 0.25)
const PLAYER_COLOR: Color = Color(0.45, 0.85, 0.75)

var _pos: Vector2 = START
var _visits: int = 0
var _player: ColorRect
var _hud_root: Control
var _hint: Label
var _info: Label


func _ready() -> void:
	_load()
	_visits += 1
	var floor_rect: ColorRect = ColorRect.new()
	floor_rect.color = FLOOR_COLOR
	floor_rect.position = ARENA.position
	floor_rect.size = ARENA.size
	add_child(floor_rect)
	_player = ColorRect.new()
	_player.name = "Player"
	_player.color = PLAYER_COLOR
	_player.size = PLAYER_SIZE
	add_child(_player)
	var hud: CanvasLayer = CanvasLayer.new()
	hud.layer = HUD_LAYER
	add_child(hud)
	_hud_root = Control.new()
	_hud_root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_hud_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	hud.add_child(_hud_root)
	var col: VBoxContainer = VBoxContainer.new()
	col.position = Vector2(HUD_MARGIN, HUD_MARGIN)
	_hud_root.add_child(col)
	_hint = Label.new()
	_hint.name = "Hint"
	col.add_child(_hint)
	_info = Label.new()
	_info.name = "Info"
	_info.modulate = UiTheme.TEXT_DIM
	col.add_child(_info)
	relabel()
	Shell.locale_changed.connect(relabel)
	Log.info("game", "play started (visit %d)" % _visits)


func apply_theme(theme: Theme) -> void:
	_hud_root.theme = theme


func relabel() -> void:
	_hint.text = Shell.t("play.placeholder", {"pause": Shell.binding_text(Shell.prompt_for("pause"))})
	_info.text = Shell.t("play.info", {"visits": _visits,
			"difficulty": Shell.t("value.difficulty." + str(Shell.access("difficulty")))})


func _physics_process(delta: float) -> void:
	var dt: float = delta * Shell.game_speed()
	var dir: Vector2 = Shell.move_vector() # invert_y is in there, for the stick only
	_pos = (_pos + dir * SPEED * dt).clamp(ARENA.position, ARENA.end - PLAYER_SIZE)
	_player.position = _pos


func _exit_tree() -> void:
	_save()


func _load() -> void:
	var r: Dictionary = SaveStore.read_slot(Shell.data_dir, SAVE_SLOT)
	if typeof(r["envelope"]) == TYPE_NIL:
		if r["source"] == "none" and not (r["problems"] as PackedStringArray).has("primary: missing"):
			Log.warn("game", "save slot %d not loaded: %s" % [SAVE_SLOT, ", ".join(r["problems"])])
		return
	var data: Dictionary = r["envelope"]["data"]
	_pos = Vector2(float(data.get("x", START.x)), float(data.get("y", START.y)))
	_visits = int(data.get("visits", 0))


func _save() -> void:
	if not Shell.active:
		return
	var err: Error = SaveStore.write_slot(Shell.data_dir, SAVE_SLOT, {"health": 3, "level": 1,
			"difficulty": Shell.access("difficulty"), "x": _pos.x, "y": _pos.y, "visits": _visits})
	if err != OK:
		Log.warn("game", "save slot %d not written (%s)" % [SAVE_SLOT, error_string(err)])
