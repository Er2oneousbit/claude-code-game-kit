# ---------------------------------------------------------------------------
# juice_demo.gd
# Purpose : The juice demo (debug builds, main menu > Juice demo): every engine-free juice module wired to a tiny
#           scene so you can feel and tune them. Hit the box: camera shake with trauma, hitstop, squash on a
#           spring, a screen flash through the FlashLimiter; walk: follow camera with a deadzone and look-ahead;
#           jump: input buffer plus coyote time; guard: a held action that honours hold_to_toggle; a subtitle line.
# Usage   : FrontEnd.start_juice(). Keys: move_left/right, jump, attack (near the box), interact (guard), pause.
# Notes   : Time: hitstop and the flash limiter take REAL time (the frame delta); everything else takes game time
#           = hitstop.scaled_dt(real) * Shell.game_speed(). Shake strength is Shell.effective_shake() (0 with
#           reduce motion). The FlashLimiter always applies; the flash_limit setting (default on) also softens
#           the flash to FLASH_GENTLE opacity. Built in code; copy the parts you want into your game.
#
# Pseudocode (each physics tick):
#   game_dt = hitstop.scaled_dt(delta) * game_speed
#   guard from interact (held, or toggled with hold_to_toggle); jump = buffered press + coyote window
#   move, gravity, land (squash); springs, follow camera and shake update on game_dt
#   attack near the box -> hit() (after the updates, so the kick shows in full during the freeze)
#   the flash fades on real time
#   hit(): trauma, hitstop, box spring kick, flash if the limiter allows, bark and caption, telemetry
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name JuiceDemo
extends Node2D

const GRAVITY: float = 900.0
const MOVE_SPEED: float = 120.0
const GUARD_SPEED_FACTOR: float = 0.5
const JUMP_SPEED: float = 300.0
const GROUND_Y: float = 290.0
const WORLD_LEFT: float = -360.0
const WORLD_RIGHT: float = 1320.0
const PLAYER_SIZE: Vector2 = Vector2(12, 18)
const PLAYER_START: Vector2 = Vector2(330.0, GROUND_Y) # feet
const BOX_SIZE: Vector2 = Vector2(30, 30)
const BOX_POS: Vector2 = Vector2(380.0, GROUND_Y) # bottom centre
const HIT_RANGE: float = 70.0
const TRAUMA_PER_HIT: float = 0.55
const HITSTOP_S: float = 0.09
const BOX_KICK: float = 0.45 # squash amount on a hit (spring pulls it back with a wobble)
const LAND_SQUASH: float = 0.3
const JUMP_STRETCH: float = -0.25
const FLASH_FULL: float = 0.85 # flash opacity with flash_limit off (still rate limited)
const FLASH_GENTLE: float = 0.3 # with flash_limit on: a soft tint
const FLASH_FADE_S: float = 0.12
const CAMERA_LIFT: float = 70.0 # the camera looks this far above the player's feet
const COYOTE_S: float = 0.1
const BUFFER_S: float = 0.12
const INTRO_LINE: String = "guide.intro"
const HIT_BARK: String = "box.ouch"
const HIT_CAPTION: String = "box_hit"
const USE_TYPEWRITER: bool = true
const HUD_LAYER: int = 5
const FLASH_LAYER: int = 6
const HUD_MARGIN: int = 10
const SKY: Color = Color(0.10, 0.12, 0.20)
const GROUND: Color = Color(0.20, 0.24, 0.33)
const PILLAR: Color = Color(0.14, 0.17, 0.27)
const PILLAR_EVERY: float = 90.0
const PLAYER_COLOR: Color = Color(0.45, 0.85, 0.75)
const BOX_COLOR: Color = Color(0.95, 0.55, 0.30)
const SHIELD_COLOR: Color = Color(0.55, 0.75, 1.0, 0.8)

var shake: Shake = Shake.new()
var hitstop: Hitstop = Hitstop.new()
var follow: FollowCamera = FollowCamera.new(64.0, 48.0, 0.25, 8.0, PLAYER_START.x, PLAYER_START.y - CAMERA_LIFT)
var buffer: InputBuffer = InputBuffer.new(BUFFER_S)
var coyote: CoyoteTimer = CoyoteTimer.new(COYOTE_S)
var box_spring: Spring = Spring.new(4.0, 0.3)
var player_spring: Spring = Spring.new(5.0, 0.5)
var limiter: FlashLimiter = FlashLimiter.new()
var subtitles: SubtitleBar
var hits: int = 0
var guarding: bool = false

var _pos: Vector2 = PLAYER_START
var _vel: Vector2 = Vector2.ZERO
var _on_floor: bool = true
var _real_clock: float = 0.0
var _flash_alpha: float = 0.0
var _camera: Camera2D
var _player: ColorRect
var _box: ColorRect
var _shield: Line2D
var _hud_root: Control
var _title: Label
var _hint: Label
var _hits_label: Label
var _guard_label: Label
var _flash: ColorRect


func _ready() -> void:
	name = "JuiceDemo"
	_build_world()
	_build_hud()
	relabel()
	Shell.locale_changed.connect(relabel)
	Shell.device_changed.connect(_on_device_changed) # prompts follow the device in use
	Shell.settings_changed.connect(_on_settings_changed)
	subtitles.typewriter = USE_TYPEWRITER
	subtitles.play(INTRO_LINE)


func apply_theme(theme: Theme) -> void:
	_hud_root.theme = theme


func relabel() -> void:
	var text: Callable = func(action: String) -> String: return Shell.binding_text(Shell.prompt_for(action))
	_title.text = Shell.t("demo.title")
	_hint.text = Shell.t("demo.hint", {"left": text.call("move_left"), "right": text.call("move_right"),
			"jump": text.call("jump"), "attack": text.call("attack"), "guard": text.call("interact"),
			"pause": text.call("pause")})
	_hits_label.text = Shell.tn("demo.hits", hits)
	_guard_label.text = Shell.t("demo.guarding")


func _physics_process(delta: float) -> void:
	_real_clock += delta
	var dt: float = hitstop.scaled_dt(delta) * Shell.game_speed()
	_update_guard()
	coyote.update(dt, _on_floor)
	buffer.update(dt)
	if Input.is_action_just_pressed("jump"):
		buffer.press("jump")
	if coyote.can_jump() and buffer.consume("jump"):
		coyote.consume()
		_vel.y = -JUMP_SPEED
		_on_floor = false
		player_spring.x = JUMP_STRETCH
	var axis: float = Input.get_axis("move_left", "move_right")
	_vel.x = axis * MOVE_SPEED * (GUARD_SPEED_FACTOR if guarding else 1.0)
	_vel.y += GRAVITY * dt
	_pos += _vel * dt
	_pos.x = clampf(_pos.x, WORLD_LEFT, WORLD_RIGHT)
	if _pos.y >= GROUND_Y:
		if not _on_floor:
			player_spring.x = LAND_SQUASH
		_pos.y = GROUND_Y
		_vel.y = 0.0
		_on_floor = true
	else:
		_on_floor = false
	box_spring.update(dt)
	player_spring.update(dt)
	follow.update(dt, _pos.x, _pos.y - CAMERA_LIFT, _vel.x, 0.0)
	shake.update(dt, Shell.effective_shake())
	# After the updates: the full kick is drawn and then held by the hitstop freeze
	if Input.is_action_just_pressed("attack") and absf(_pos.x - BOX_POS.x) <= HIT_RANGE:
		hit()
	_flash_alpha *= exp(-delta / FLASH_FADE_S) # real time: the flash fades even while the hit freezes the game
	_draw_state()


func hit() -> void:
	hits += 1
	shake.add_trauma(TRAUMA_PER_HIT)
	hitstop.hit(HITSTOP_S)
	box_spring.x = BOX_KICK
	box_spring.v = 0.0
	if limiter.request(_real_clock): # always limited; the setting only softens it
		_flash_alpha = FLASH_GENTLE if bool(Shell.access("flash_limit")) else FLASH_FULL
	subtitles.play(HIT_BARK) # shown only with subtitle_barks on
	subtitles.caption(HIT_CAPTION) # shown only with captions_sfx on
	_hits_label.text = Shell.tn("demo.hits", hits)
	Shell.telemetry("demo_hit", str(hits))


func _on_device_changed(_device: String) -> void:
	relabel()


func _on_settings_changed(_section: String, _key: String) -> void:
	relabel()


func _update_guard() -> void:
	if bool(Shell.access("hold_to_toggle")):
		if Input.is_action_just_pressed("interact"):
			guarding = not guarding
	else:
		guarding = Input.is_action_pressed("interact")


func _draw_state() -> void:
	_player.position = _pos - Vector2(PLAYER_SIZE.x / 2.0, PLAYER_SIZE.y)
	_player.scale = Spring.squash(player_spring.x)
	_box.scale = Spring.squash(box_spring.x)
	_shield.position = _pos - Vector2(0, PLAYER_SIZE.y / 2.0)
	_shield.visible = guarding
	_guard_label.visible = guarding
	_camera.position = follow.position()
	_camera.offset = shake.offset()
	_camera.rotation = shake.angle
	_flash.color = Color(1, 1, 1, _flash_alpha)
	_flash.visible = _flash_alpha > 0.01


func _build_world() -> void:
	var sky: ColorRect = ColorRect.new()
	sky.color = SKY
	sky.position = Vector2(WORLD_LEFT - 400, -400)
	sky.size = Vector2(WORLD_RIGHT - WORLD_LEFT + 800, GROUND_Y + 400)
	add_child(sky)
	var x: float = WORLD_LEFT
	while x < WORLD_RIGHT:
		var pillar: ColorRect = ColorRect.new() # landmarks, so camera movement is visible
		pillar.color = PILLAR
		pillar.position = Vector2(x, GROUND_Y - 120)
		pillar.size = Vector2(18, 120)
		add_child(pillar)
		x += PILLAR_EVERY
	var ground: ColorRect = ColorRect.new()
	ground.color = GROUND
	ground.position = Vector2(WORLD_LEFT - 400, GROUND_Y)
	ground.size = Vector2(WORLD_RIGHT - WORLD_LEFT + 800, 200)
	add_child(ground)
	_box = ColorRect.new()
	_box.name = "Box"
	_box.color = BOX_COLOR
	_box.size = BOX_SIZE
	_box.position = BOX_POS - Vector2(BOX_SIZE.x / 2.0, BOX_SIZE.y)
	_box.pivot_offset = Vector2(BOX_SIZE.x / 2.0, BOX_SIZE.y) # squash from the floor up
	add_child(_box)
	_player = ColorRect.new()
	_player.name = "Player"
	_player.color = PLAYER_COLOR
	_player.size = PLAYER_SIZE
	_player.pivot_offset = Vector2(PLAYER_SIZE.x / 2.0, PLAYER_SIZE.y)
	add_child(_player)
	_shield = Line2D.new()
	_shield.width = 2.0
	_shield.default_color = SHIELD_COLOR
	for i: int in 17:
		_shield.add_point(Vector2.from_angle(TAU * i / 16.0) * 14.0)
	_shield.visible = false
	add_child(_shield)
	_camera = Camera2D.new()
	_camera.ignore_rotation = false
	add_child(_camera)
	_camera.make_current()


func _build_hud() -> void:
	var hud: CanvasLayer = CanvasLayer.new()
	hud.name = "Hud"
	hud.layer = HUD_LAYER
	add_child(hud)
	_hud_root = Control.new()
	_hud_root.name = "Root"
	_hud_root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_hud_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	hud.add_child(_hud_root)
	var margin: MarginContainer = MarginContainer.new()
	margin.set_anchors_and_offsets_preset(Control.PRESET_TOP_WIDE)
	margin.mouse_filter = Control.MOUSE_FILTER_IGNORE
	for side: String in ["margin_left", "margin_right", "margin_top"]:
		margin.add_theme_constant_override(side, HUD_MARGIN)
	_hud_root.add_child(margin)
	var col: VBoxContainer = VBoxContainer.new()
	col.mouse_filter = Control.MOUSE_FILTER_IGNORE
	margin.add_child(col)
	var top: HBoxContainer = HBoxContainer.new()
	col.add_child(top)
	_title = Label.new()
	_title.name = "Title"
	_title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	top.add_child(_title)
	_hits_label = Label.new()
	_hits_label.name = "Hits"
	top.add_child(_hits_label)
	_hint = Label.new()
	_hint.name = "Hint"
	_hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_hint.modulate = UiTheme.TEXT_DIM
	col.add_child(_hint)
	_guard_label = Label.new()
	_guard_label.name = "Guarding"
	_guard_label.visible = false
	col.add_child(_guard_label)
	subtitles = SubtitleBar.new()
	_hud_root.add_child(subtitles)
	var flash_layer: CanvasLayer = CanvasLayer.new()
	flash_layer.name = "Flash"
	flash_layer.layer = FLASH_LAYER
	add_child(flash_layer)
	_flash = ColorRect.new()
	_flash.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_flash.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_flash.visible = false
	flash_layer.add_child(_flash)

# {{FOOTER}}
