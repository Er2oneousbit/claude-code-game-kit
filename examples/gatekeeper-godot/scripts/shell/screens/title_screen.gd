# ---------------------------------------------------------------------------
# title_screen.gd
# Purpose : The title screen: game name, "press any key or button", the version, and (first run only) the
#           telemetry question: Yes / No / Later.
# Usage   : front.show_title()   (FrontEnd builds it)
# Notes   : The consent question shows while the setting is "unset", once per launch: Later keeps it unset, so
#           the next launch asks again; Yes or No is saved at once. Focus starts on Later, the choice that
#           changes nothing. Any key, button or click (with no question open) opens the main menu.
#           With reduce motion on, the prompt does not blink.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name TitleScreen
extends ShellScreen

const BLINK_PERIOD_S: float = 1.2
const BLINK_MIN_ALPHA: float = 0.35
const CONSENT_WIDTH: int = 360

var _prompt: Label
var _dialog: PanelContainer = null
var _clock: float = 0.0


func _init(p_front: FrontEnd) -> void:
	super(p_front, "title")


func build() -> void:
	var col: VBoxContainer = centered_column()
	var title: Label = label(Shell.t("game.title"), UiTheme.TITLE_FONT, "Title")
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	col.add_child(title)
	_prompt = label(Shell.t("title.press_any"), 1.0, "Prompt")
	_prompt.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	col.add_child(_prompt)
	var ver: Label = label(Shell.t("title.version", {"version": Shell.version}), 1.0, "Version")
	ver.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_RIGHT)
	ver.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	ver.grow_vertical = Control.GROW_DIRECTION_BEGIN
	ver.position -= Vector2(MARGIN, MARGIN)
	ver.modulate = UiTheme.TEXT_DIM
	add_child(ver)
	_dialog = null
	if str(Shell.settings["telemetry"]["consent"]) == "unset" and not front.consent_asked:
		_build_consent()


func consent_open() -> bool:
	return _dialog != null


func focus_first() -> void:
	if _dialog != null:
		(_dialog.find_child("Later", true, false) as Control).grab_focus()


func _build_consent() -> void:
	var center: CenterContainer = CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(center)
	_dialog = PanelContainer.new()
	_dialog.name = "Consent"
	center.add_child(_dialog)
	var col: VBoxContainer = VBoxContainer.new()
	col.add_theme_constant_override("separation", COLUMN_SEPARATION)
	_dialog.add_child(col)
	col.add_child(label(Shell.t("consent.title"), UiTheme.HEADING_FONT, "ConsentTitle"))
	var body: Label = label(Shell.t("consent.body"), 1.0, "ConsentBody")
	body.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.custom_minimum_size.x = CONSENT_WIDTH
	col.add_child(body)
	var row: HBoxContainer = HBoxContainer.new()
	row.alignment = BoxContainer.ALIGNMENT_CENTER
	col.add_child(row)
	for choice: Array in [["yes", "ConsentYes"], ["no", "ConsentNo"], ["unset", "Later"]]:
		var b: Button = button(Shell.t("consent." + str(choice[0])), choice[1], _answer.bind(choice[0]))
		b.custom_minimum_size.x = 0
		row.add_child(b)


func _answer(choice: String) -> void:
	front.consent_asked = true
	if choice != "unset":
		Shell.set_value("telemetry", "consent", choice)
		Shell.save_settings()
		Shell.telemetry("consent", choice) # written only when the answer was yes
	Log.info("shell", "telemetry consent: %s" % choice)
	_dialog.get_parent().queue_free()
	_dialog = null


func _process(delta: float) -> void:
	_clock += delta
	if _prompt == null:
		return
	if bool(Shell.access("reduce_motion")):
		_prompt.modulate.a = 1.0
	else:
		var wave: float = 0.5 + 0.5 * cos(_clock * TAU / BLINK_PERIOD_S)
		_prompt.modulate.a = lerpf(BLINK_MIN_ALPHA, 1.0, wave)


func _unhandled_input(event: InputEvent) -> void:
	if not is_top() or _dialog != null:
		return
	if _is_press(event):
		get_viewport().set_input_as_handled()
		front.open_main_menu()


func _is_press(event: InputEvent) -> bool:
	if event is InputEventKey:
		var key: InputEventKey = event
		return key.pressed and not key.echo and key.keycode != Shell.BUG_REPORT_KEY
	if event is InputEventJoypadButton or event is InputEventMouseButton or event is InputEventAction:
		return event.is_pressed()
	return false
