# ---------------------------------------------------------------------------
# main.gd
# Purpose : Entry scene. Builds the level from LevelData with Kenney tiles, spawns
#           the player, plays music and sounds, counts coins, time and falls,
#           respawns on a fall, and ends the run at the flag.
# Usage   : Attached to scenes/main.tscn (the main scene).
#           Keys: A/D or arrows to move, Space/W/Up to jump, R to restart, F1 debug overlay.
#           `godot --path . -- --autoplay` runs a bot that plays the level (proof it is beatable).
# Notes   : Prints BOOT_OK for `dev.py smoke`. Everything is built in code so the
#           scene file stays one node; numbers live in Tuning, layout in LevelData,
#           atlas math in Sprites. Assets and licenses: docs/ASSET_LOG.md.
#
# Pseudocode:
#   ready: register input actions, build background, platforms, decor, coins, goal,
#          spawn player + camera, HUD, audio players; start the music
#   physics tick: fell below FALL_LIMIT_Y -> respawn, falls += 1 (checked after the flag too);
#                 until the flag: autoplay bot (optional), the clock runs from the first move or jump
#   coin touched (before the flag) -> count it, hide it
#   goal touched -> stop the clock, lock the player's controls, jingle, show the result
#   R restarts at any point (coins come back, jingle stops, clock waits for input again)
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): player frozen at the flag, fall
#           check and coin guard after it, clock starts on first input, restart stops the jingle
# ---------------------------------------------------------------------------
extends Node2D

const AUTOPLAY_TIMEOUT: float = 30.0     # s before the bot reports failure
const ACTIONS: Dictionary = {
	"move_left": [KEY_A, KEY_LEFT],
	"move_right": [KEY_D, KEY_RIGHT],
	"jump": [KEY_SPACE, KEY_W, KEY_UP],
	"restart": [KEY_R],
	"debug_overlay": [KEY_F1],
}
# Tile indices in tilemap_packed.png (see the labelled sheet in HOW_IT_WAS_MADE.md)
const GRASS_TOP: Array[int] = [1, 2, 3]       # left, middle, right
const DIRT: Array[int] = [121, 122, 123]
const BRIDGE: Array[int] = [48, 49, 50]
const BRIDGE_SINGLE: int = 47
const COIN_FRAMES: Array[int] = [151, 152]
const FLAG_FRAMES: Array[int] = [111, 112]
const FLAG_POLE: int = 131
const SKY_COLOR: Color = Color("d7f2f5")
const SFX: Dictionary = {
	"jump": preload("res://assets/audio/sfx/jump.wav"),
	"coin": preload("res://assets/audio/sfx/coin.wav"),
	"fall": preload("res://assets/audio/sfx/fall.wav"),
	"land": preload("res://assets/audio/sfx/land.wav"),
	"goal": preload("res://assets/audio/music/goal.wav"),
}
const MUSIC: AudioStreamWAV = preload("res://assets/audio/music/theme.wav")

var player: Player
var hud: Label
var debug_label: Label
var music: AudioStreamPlayer
var sfx_players: Dictionary = {}
var coins: Array[Area2D] = []
var coins_taken: int = 0
var elapsed: float = 0.0
var falls: int = 0
var finished: bool = false
var started: bool = false   # the clock waits for the first move or jump input
var autoplay: bool = false


func _ready() -> void:
	RenderingServer.set_default_clear_color(SKY_COLOR)
	_register_actions()
	_build_background()
	_build_level()
	_spawn_player()
	_build_hud()
	_build_audio()
	autoplay = OS.get_cmdline_user_args().has("--autoplay")
	get_tree().auto_accept_quit = false   # window close goes through _quit_cleanly()
	Log.info("core", "BOOT_OK Coyote Hop%s" % (" (autoplay)" if autoplay else ""))


func _register_actions() -> void:
	for action: String in ACTIONS:
		if not InputMap.has_action(action):
			InputMap.add_action(action)
		for key: int in ACTIONS[action]:
			var ev := InputEventKey.new()
			ev.physical_keycode = key as Key
			InputMap.action_add_event(action, ev)
	var pad_jump := InputEventJoypadButton.new()
	pad_jump.button_index = JOY_BUTTON_A
	InputMap.action_add_event("jump", pad_jump)
	for pair: Array in [["move_left", JOY_BUTTON_DPAD_LEFT], ["move_right", JOY_BUTTON_DPAD_RIGHT]]:
		var pad := InputEventJoypadButton.new()
		pad.button_index = pair[1]
		InputMap.action_add_event(pair[0], pad)


# Hills strip from the backgrounds sheet (first 4 columns), scaled to the
# screen height and repeated, scrolling slower than the level.
func _build_background() -> void:
	var strip := Sprite2D.new()
	strip.texture = Sprites.BACKGROUNDS
	strip.region_enabled = true
	strip.region_rect = Rect2(0, 0, 96, 72)
	strip.centered = false
	var scale_y: float = 180.0 / 72.0
	strip.scale = Vector2(scale_y, scale_y)
	var parallax := Parallax2D.new()
	parallax.scroll_scale = Vector2(0.4, 1.0)
	parallax.repeat_size = Vector2(96.0 * scale_y, 0.0)
	parallax.repeat_times = 4
	parallax.add_child(strip)
	add_child(parallax)


func _build_level() -> void:
	for r: Rect2i in LevelData.PLATFORMS:
		var px: Rect2 = LevelData.tile_rect(r)
		var body := StaticBody2D.new()
		body.position = px.get_center()
		body.add_child(_rect_shape(px.size))
		add_child(body)
		for x in range(r.size.x):
			var edge: int = 0 if x == 0 else (2 if x == r.size.x - 1 else 1)
			for y in range(r.size.y):
				var index: int
				if r.size.y == 1:
					index = BRIDGE_SINGLE if r.size.x == 1 else BRIDGE[edge]
				else:
					index = GRASS_TOP[edge] if y == 0 else DIRT[edge]
				_place_tile(index, Vector2i(r.position.x + x, r.position.y + y))
	for d: Vector2i in LevelData.DECOR:
		_place_tile(d.y, Vector2i(d.x, _floor_row_at(d.x) - 1))
	for c: Vector2i in LevelData.COINS:
		coins.append(_build_coin(c))
	_build_goal()


func _place_tile(index: int, cell: Vector2i) -> void:
	var s := Sprites.tile(index)
	s.position = Vector2(cell * Tuning.TILE)
	add_child(s)


func _floor_row_at(column: int) -> int:
	for r: Rect2i in LevelData.PLATFORMS:
		if column >= r.position.x and column < r.end.x:
			return r.position.y
	return 10


func _build_coin(cell: Vector2i) -> Area2D:
	var coin := Area2D.new()
	coin.position = Vector2(cell * Tuning.TILE) + Vector2(Tuning.TILE, Tuning.TILE) / 2.0
	var shape := CollisionShape2D.new()
	var circle := CircleShape2D.new()
	circle.radius = 6.0
	shape.shape = circle
	coin.add_child(shape)
	var anim := AnimatedSprite2D.new()
	anim.sprite_frames = Sprites.frames(Sprites.TILES, COIN_FRAMES, 4.0)
	anim.play("default")
	coin.add_child(anim)
	coin.body_entered.connect(_on_coin_body_entered.bind(coin))
	add_child(coin)
	return coin


func _build_goal() -> void:
	var goal_rect: Rect2 = LevelData.goal_px()
	var flag := AnimatedSprite2D.new()
	flag.sprite_frames = Sprites.frames(Sprites.TILES, FLAG_FRAMES, 3.0)
	flag.centered = false
	flag.position = goal_rect.position
	flag.play("default")
	add_child(flag)
	_place_tile(FLAG_POLE, LevelData.GOAL_TILE + Vector2i(0, 1))
	var goal := Area2D.new()
	goal.position = goal_rect.get_center()
	goal.add_child(_rect_shape(goal_rect.size))
	goal.body_entered.connect(_on_goal_body_entered)
	add_child(goal)


func _spawn_player() -> void:
	player = Player.new()
	add_child(player)
	player.respawn(LevelData.spawn_px())
	player.jumped.connect(_play.bind("jump"))
	player.landed.connect(_play.bind("land"))
	var cam := Camera2D.new()
	cam.zoom = Vector2(Tuning.CAMERA_ZOOM, Tuning.CAMERA_ZOOM)
	cam.limit_left = 0
	cam.limit_top = 0
	cam.limit_right = LevelData.level_width_px()
	cam.limit_bottom = 10 * Tuning.TILE
	cam.position_smoothing_enabled = true   # Player.respawn() resets it, so a respawn does not pan
	player.add_child(cam)


func _build_hud() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var style := LabelSettings.new()
	style.font_size = 18
	style.font_color = Color("ffffff")
	style.outline_size = 6
	style.outline_color = Color("1d2b53")
	hud = Label.new()
	hud.position = Vector2(10, 6)
	hud.label_settings = style
	layer.add_child(hud)
	debug_label = Label.new()
	debug_label.position = Vector2(10, 330)
	debug_label.label_settings = style
	debug_label.visible = false
	layer.add_child(debug_label)


func _build_audio() -> void:
	music = AudioStreamPlayer.new()
	music.stream = MUSIC   # loops by itself: chiptune.py writes the loop points into the WAV
	music.volume_db = Tuning.MUSIC_DB
	add_child(music)
	# Headless runs (dev.py smoke, CI) have no audio out, and quitting mid-song there leaves the
	# playback held by the mixer thread, which Godot reports as a leaked resource at exit.
	if DisplayServer.get_name() != "headless":
		music.play()
	for key: String in SFX:
		var p := AudioStreamPlayer.new()
		p.stream = SFX[key]
		p.volume_db = Tuning.SFX_DB
		add_child(p)
		sfx_players[key] = p


func _play(key: String) -> void:
	(sfx_players[key] as AudioStreamPlayer).play()


func _physics_process(delta: float) -> void:
	if Input.is_action_just_pressed("restart"):
		_restart()
	if Input.is_action_just_pressed("debug_overlay"):
		debug_label.visible = not debug_label.visible
	# Before the finished check, so nothing can fall forever whatever happens after the flag.
	if player.global_position.y > Tuning.FALL_LIMIT_Y:
		falls += 1
		Log.info("game", "fell (%d)" % falls)
		_play("fall")
		player.respawn(LevelData.spawn_px())
	if finished:
		return
	if autoplay:
		_autoplay_step()
	if not started:
		started = _has_run_input()
	if started:
		elapsed += delta
	hud.text = "Coins %d/%d   Time %.1f   Falls %d" % [coins_taken, coins.size(), elapsed, falls]
	debug_label.text = "coyote %.2f  buffer %.2f  vel (%d, %d)  floor %s   (R restart)" % [
		player.coyote.time_left, player.buffer.time_left, player.velocity.x, player.velocity.y, player.is_on_floor()]


func _has_run_input() -> bool:
	return Input.get_axis("move_left", "move_right") != 0.0 or Input.is_action_pressed("jump")


# Bot: hold right, jump when the player's front edge reaches the end of the
# platform under it, keep jump held until the apex for full height.
func _autoplay_step() -> void:
	Input.action_press("move_right")
	if player.is_on_floor():
		var front: float = player.global_position.x + Tuning.PLAYER_SIZE.x / 2.0
		for rect: Rect2 in LevelData.platforms_px():
			if front >= rect.position.x and front < rect.end.x and front >= rect.end.x - 4.0:
				Input.action_press("jump")
	elif player.velocity.y >= 0.0:
		Input.action_release("jump")
	if elapsed > AUTOPLAY_TIMEOUT:
		Log.error("game", "autoplay did not reach the goal in %.0f s (falls %d)" % [AUTOPLAY_TIMEOUT, falls])
		get_tree().quit(1)


func _on_coin_body_entered(body: Node2D, coin: Area2D) -> void:
	if finished or body != player or not coin.visible:
		return
	coin.visible = false
	coin.set_deferred("monitoring", false)
	coins_taken += 1
	_play("coin")


func _on_goal_body_entered(body: Node2D) -> void:
	if body != player or finished:
		return
	finished = true
	player.controls_enabled = false   # the fox stops at the flag instead of running off the level
	music.volume_db = Tuning.MUSIC_DB - 12.0
	_play("goal")
	hud.text = "You made it! %.1f s, %d/%d coins, %d falls.  R to restart" % [elapsed, coins_taken, coins.size(), falls]
	Log.info("game", "GOAL_REACHED %.2f s, %d/%d coins, %d falls" % [elapsed, coins_taken, coins.size(), falls])
	if autoplay:
		Input.action_release("move_right")
		Input.action_release("jump")
		get_tree().create_timer(1.5).timeout.connect(_quit_autoplay)


func _quit_autoplay() -> void:
	await _quit_cleanly()


# Stop audio, give the mixer thread a moment to release the streams, then quit.
# Quitting mid-sound makes Godot report the audio playback as a leaked resource.
func _quit_cleanly() -> void:
	_stop_audio()
	await get_tree().create_timer(0.1).timeout
	get_tree().quit()


func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST:
		_quit_cleanly()


# Any exit (window close, --quit-after, autoplay): streams still playing at shutdown
# are reported as leaked resources, which `dev.py smoke` rightly treats as errors.
func _exit_tree() -> void:
	_stop_audio()


func _stop_audio() -> void:
	if music:
		music.stop()
		music.stream = null
	for p: AudioStreamPlayer in sfx_players.values():
		p.stop()
		p.stream = null


func _restart() -> void:
	elapsed = 0.0
	falls = 0
	finished = false
	started = false
	coins_taken = 0
	for coin: Area2D in coins:
		coin.visible = true
		coin.set_deferred("monitoring", true)
	music.volume_db = Tuning.MUSIC_DB
	(sfx_players["goal"] as AudioStreamPlayer).stop()
	player.controls_enabled = true
	player.respawn(LevelData.spawn_px())   # also snaps the camera and faces the fox right


func _rect_shape(size: Vector2) -> CollisionShape2D:
	var shape := CollisionShape2D.new()
	var rect := RectangleShape2D.new()
	rect.size = size
	shape.shape = rect
	return shape
