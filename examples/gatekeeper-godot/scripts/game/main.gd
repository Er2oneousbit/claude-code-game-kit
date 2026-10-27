# ---------------------------------------------------------------------------
# main.gd
# Purpose : Gatekeeper (Godot): talk your way past a guard. Builds the scene (wall, gate,
#           guard, notice, trust bar) and the UI (start choice, chat log, input), runs the
#           conversation through GuardBrain and the rules in GateRules.
# Usage   : Main scene. User args after "--": --autoplay (winning script, scripted guard),
#           --autoplay=rude (losing script), --llm (load the local model first), --debug,
#           --voice / --no-voice (live voice in headless runs / off; needs FISH_API_KEY, see guard_voice.gd).
# Notes   : Markers for dev.py smoke and scenario runs: BOOT_OK, MODEL_READY, INTENT, GATE_OPEN,
#           TURNED_AWAY. The model is optional at every step; the scripted guard plays the same game.
#           Tiles from Kenney Tiny Dungeon (A-0003): 40 wall, 48 floor, 45 door, 97 guard, 84 traveler.
#           Sounds: ElevenLabs (A-0006 to A-0009, the web twin's files), with an ambience loop at the wall.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends Node2D

const TILES: Texture2D = preload("res://assets/art/tilemap_packed.png")
const SND_OPEN: AudioStream = preload("res://assets/audio/gate-open.mp3")
const SND_AWAY: AudioStream = preload("res://assets/audio/turned-away.mp3")
const SND_TALK: AudioStream = preload("res://assets/audio/guard-talk.mp3")
const SND_AMBIENCE: AudioStreamWAV = preload("res://assets/audio/gate-ambience.wav")
const AMBIENCE_DB: float = -10.0   # under the guard and the gate
const SCALE: int = 3
const T: int = 16 * SCALE
const WIN_SCRIPT: Array[String] = ["Good evening, guard.", "That armor looks well kept.", "Captain Wren asked me to come tonight."]
const RUDE_SCRIPT: Array[String] = ["Open the gate.", "Open it or I will break your nose.", "Last chance before I hurt you."]

var rng := RandomNumberGenerator.new()
var brain: GuardBrain
var state: Dictionary
var busy := false
var debug := false
var door: Sprite2D
var guard: Sprite2D
var trust_bar: ColorRect
var trust_label: Label
var start_panel: PanelContainer
var chat_panel: PanelContainer
var log_box: RichTextLabel
var input: LineEdit
var ai_button: Button
var status: Label
var sfx: AudioStreamPlayer
var voice: GuardVoice


func _ready() -> void:
	rng.seed = Tuning.SEED
	brain = GuardBrain.new(rng)
	state = GateRules.new_state(Tuning.RULES)
	var args := OS.get_cmdline_user_args()
	debug = args.has("--debug")
	_build_world()
	_build_ui()
	sfx = AudioStreamPlayer.new()
	add_child(sfx)
	_start_ambience()
	voice = GuardVoice.new()
	add_child(voice)
	Log.info("core", "BOOT_OK Gatekeeper")
	var auto := ""
	for a in args:
		if a.begins_with("--autoplay"):
			auto = "rude" if a == "--autoplay=rude" else "win"
	if args.has("--llm"):
		await _use_model()
	elif auto != "":
		_begin()
	if auto != "":
		for line in (RUDE_SCRIPT if auto == "rude" else WIN_SCRIPT):
			if state.outcome != "talking":
				break
			await say(line)
		if state.outcome == "talking":
			Log.info("game", "SCRIPT_ENDED trust=%d" % state.trust)
		await get_tree().create_timer(1.0).timeout   # autoplay is for checks: never leave a window hanging
		var waited := 0.0
		while not voice.idle() and waited < Tuning.VOICE_DRAIN_S:   # let queued lines finish speaking
			await get_tree().create_timer(0.25).timeout
			waited += 0.25
		get_tree().quit()


# ---- world --------------------------------------------------------------------
func _tile(index: int, pos: Vector2, tint := Color.WHITE) -> Sprite2D:
	var s := Sprite2D.new()
	s.texture = TILES
	s.region_enabled = true
	s.region_rect = Rect2((index % 12) * 16, int(index / 12.0) * 16, 16, 16)
	s.centered = false
	s.scale = Vector2(SCALE, SCALE)
	s.position = pos
	s.modulate = tint
	s.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	add_child(s)
	return s


func _build_world() -> void:
	RenderingServer.set_default_clear_color(Color("0b0b14"))
	var cols := ceili(640.0 / T)
	for y in range(ceili(360.0 / T)):
		for x in range(cols):
			_tile(40 if y < 3 else 48, Vector2(x * T, y * T), Color("8a8ab0") if y < 3 else Color("9a8a78"))
	var gate_x := int(cols / 2.0) * T
	door = _tile(45, Vector2(gate_x, 2 * T))
	guard = _tile(97, Vector2(gate_x + T * 1.2, 3 * T + 6))
	var traveler := _tile(84, Vector2(gate_x - T * 0.2, 3 * T + T * 2.4))
	traveler.flip_h = true
	var notice := ColorRect.new()
	notice.color = Color("e9dcb8")
	notice.position = Vector2(gate_x - T * 3.4, T * 0.6)
	notice.size = Vector2(T * 2.6, T * 1.5)
	add_child(notice)
	var text := Label.new()
	text.text = "NOTICE\nGate closed by order\nof Captain Wren."
	text.add_theme_color_override("font_color", Color("3a2a10"))
	text.add_theme_font_size_override("font_size", 14)
	text.position = notice.position + Vector2(8, 6)
	add_child(text)
	var night := ColorRect.new()
	night.color = Color(0.04, 0.04, 0.19, 0.25)
	night.size = Vector2(640, 360)
	night.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(night)


# ---- UI -----------------------------------------------------------------------
func _build_ui() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var bar_bg := ColorRect.new()
	bar_bg.color = Color(0, 0, 0, 0.6)
	bar_bg.position = Vector2(12, 8)
	bar_bg.size = Vector2(204, 12)
	layer.add_child(bar_bg)
	trust_bar = ColorRect.new()
	trust_bar.position = Vector2(14, 10)
	trust_bar.size = Vector2(0, 8)
	layer.add_child(trust_bar)
	trust_label = Label.new()
	trust_label.position = Vector2(224, 2)
	trust_label.add_theme_font_size_override("font_size", 13)
	layer.add_child(trust_label)

	start_panel = _panel(layer)
	var box := VBoxContainer.new()
	start_panel.add_child(box)
	var intro := Label.new()
	intro.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	intro.custom_minimum_size = Vector2(580, 0)
	intro.text = ("The gate is shut and a guard stands in your way. Type what you would say to him.\n"
		+ "The AI guard is a small language model (%s) running on THIS computer through the NobodyWho plugin. "
		+ "Nothing you type leaves your machine. The scripted guard plays the same game without it.") % Tuning.MODEL_NAME
	box.add_child(intro)
	var row := HBoxContainer.new()
	box.add_child(row)
	ai_button = Button.new()
	ai_button.text = "Talk to the AI guard"
	ai_button.pressed.connect(func() -> void: _use_model())
	row.add_child(ai_button)
	var plain := Button.new()
	plain.text = "Play with the scripted guard"
	plain.pressed.connect(_begin)
	row.add_child(plain)
	status = Label.new()
	status.add_theme_font_size_override("font_size", 12)
	box.add_child(status)
	var problem := GuardBrain.model_problem()
	if problem != "":
		ai_button.disabled = true
		status.text = "AI guard unavailable: " + problem

	chat_panel = _panel(layer)
	chat_panel.visible = false
	var chat_box := VBoxContainer.new()
	chat_panel.add_child(chat_box)
	log_box = RichTextLabel.new()
	log_box.bbcode_enabled = true
	log_box.scroll_following = true
	log_box.custom_minimum_size = Vector2(600, 96)
	chat_box.add_child(log_box)
	var say_row := HBoxContainer.new()
	chat_box.add_child(say_row)
	input = LineEdit.new()
	input.max_length = GateIntent.MAX_INPUT
	input.placeholder_text = "Say something to the guard..."
	input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	input.text_submitted.connect(func(t: String) -> void: _submit(t))
	say_row.add_child(input)
	var again := Button.new()
	again.text = "Start over"
	again.pressed.connect(func() -> void: get_tree().reload_current_scene())
	say_row.add_child(again)


func _panel(layer: CanvasLayer) -> PanelContainer:
	var p := PanelContainer.new()
	p.position = Vector2(12, 222)
	p.size = Vector2(616, 130)
	layer.add_child(p)
	return p


# ---- flow ---------------------------------------------------------------------
func _use_model() -> void:
	ai_button.disabled = true
	status.text = "Loading %s..." % Tuning.MODEL_NAME
	var err: String = await brain.load_model()
	if err != "":
		Log.warn("ai", "model unavailable: " + err)
		status.text = "AI guard unavailable (%s): the scripted guard takes over." % err
	else:
		Log.info("ai", "MODEL_READY")
	_begin()


func _begin() -> void:
	start_panel.visible = false
	chat_panel.visible = true
	_add("sys", "You are talking to an AI guard running on your computer. He will improvise; the rules do not."
		if brain.has_model() else "You are talking to the scripted guard.")
	_add("guard", "Halt. The gate is closed.")
	_show(false)
	input.grab_focus()


func _submit(text: String) -> void:
	input.clear()
	if text.strip_edges() != "":
		say(text.strip_edges())


func _add(kind: String, text: String) -> void:
	var safe := text.replace("[", "[lb]")   # player and model text are never BBCode
	match kind:
		"you":
			log_box.append_text("[color=#9a94a8]You: %s[/color]\n" % safe)
		"guard":
			log_box.append_text("[color=#ffd27a][b]Bram:[/b][/color] %s\n" % safe)
			voice.speak(text)   # optional live voice; silent without FISH_API_KEY
		_:
			log_box.append_text("[i][color=#9a94a8]%s[/color][/i]\n" % safe)


func say(text: String) -> void:
	if busy or state.outcome != "talking":
		return
	busy = true
	_add("you", text)
	var r: Dictionary = await brain.reply(get_tree(), text, GateRules.mood(state, Tuning.RULES))
	var step := GateRules.apply_intent(state, r.intent, Tuning.RULES)
	state = step.state
	_add("guard", r.line)
	if debug or r.why != "":
		_add("sys", "[%s, trust %+d, %s%s%s]" % [r.intent, step.delta, r.source,
			(" %d ms" % r.ms) if r.ms else "", (", " + r.why) if r.why != "" else ""])
	Log.info("game", "INTENT %s (%s) trust=%d" % [r.intent, r.source, state.trust])
	if r.why != "":
		Log.warn("ai", "FALLBACK: " + r.why)
	if r.source == "model":
		Log.info("ai", "MODEL_REPLY %d ms: %s" % [r.ms, r.line])
	_show(true)
	if state.outcome != "talking":
		_add("guard", GuardLines.outcome_line(state.outcome, rng))
		_finish()
	busy = false


func _show(spoke: bool) -> void:
	trust_bar.size.x = 200.0 * state.trust / 100.0
	trust_bar.color = Color("7fd07f") if state.trust >= Tuning.RULES.open_at else Color("ffd27a")
	trust_label.text = "trust %d   turns left %d" % [state.trust, state.turns_left]
	if spoke:
		sfx.stream = SND_TALK
		sfx.play()
		var tw := create_tween()
		tw.tween_property(guard, "position:y", guard.position.y - 4, 0.09)
		tw.tween_property(guard, "position:y", guard.position.y, 0.09)


# The wall at night, looping under everything. The WAV loops forward over its whole length (set here, so the
# file's import settings stay default); a headless run has no audio device, which is fine.
func _start_ambience() -> void:
	var loop := SND_AMBIENCE.duplicate() as AudioStreamWAV
	loop.loop_mode = AudioStreamWAV.LOOP_FORWARD
	loop.loop_begin = 0
	loop.loop_end = int(loop.get_length() * loop.mix_rate)
	var player := AudioStreamPlayer.new()
	player.stream = loop
	player.volume_db = AMBIENCE_DB
	add_child(player)
	player.play()


func _finish() -> void:
	if state.outcome == "open":
		sfx.stream = SND_OPEN
		create_tween().tween_property(door, "modulate:a", 0.0, 0.6)
		create_tween().tween_property(guard, "position:x", guard.position.x + T, 0.6)
		Log.info("game", "GATE_OPEN")
	else:
		sfx.stream = SND_AWAY
		Log.info("game", "TURNED_AWAY")
	sfx.play()
