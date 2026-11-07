# ---------------------------------------------------------------------------
# narrator.gd
# Purpose : Menu narration (#165): every focus change, value change and screen says a short line ("Music volume,
#           slider, 70 percent"), so a blind or low-vision player can use the title, settings and pause screens.
# Usage   : FrontEnd adds one. Narrator.describe(control) is the line for any control (the access drive reports it
#           for every focusable control, and tools/access/sweep.py fails a control that says "unlabelled").
# Notes   : The line is always worked out (Shell.last_narration); it is spoken only with access.narration on, through
#           Godot's text to speech (DisplayServer.tts_speak; project.godot turns it on), interrupting the line
#           before. Godot 4.5+ also has screen reader support through AccessKit, which is not checked here
#           (verify with a screen reader). Role and on/off words come from the string tables (narrate.*).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name Narrator
extends Node

const SPEECH_VOLUME: int = 80 # 0..100, DisplayServer.tts_speak

var front: FrontEnd
var _focused: Control = null
var _line: String = ""


func _init(p_front: FrontEnd) -> void:
	front = p_front
	name = "Narrator"
	process_mode = Node.PROCESS_MODE_ALWAYS


func _ready() -> void:
	get_viewport().gui_focus_changed.connect(_on_focus)
	front.screen_shown.connect(_on_screen)


func _on_focus(c: Control) -> void:
	_focused = c
	_say(describe(c))


func _on_screen(_screen: String) -> void:
	var top: ShellScreen = front.top()
	if top == null:
		return
	var heading: Label = top.find_child("Heading", true, false) as Label
	if heading == null:
		heading = top.find_child("Title", true, false) as Label
	_say(Bindings.narration_line(heading.text if heading != null else top.screen_name, Shell.t("narrate.screen")))


func _process(_delta: float) -> void:
	# a value that changes under focus (a slider moved, a toggle flipped) is said again
	if _focused != null and is_instance_valid(_focused) and _focused.has_focus():
		var now: String = describe(_focused)
		if now != _line:
			_say(now)


func _say(line: String) -> void:
	_line = line
	Shell.last_narration = line
	if not bool(Shell.access("narration")):
		return
	var voices: PackedStringArray = DisplayServer.tts_get_voices_for_language(Shell.locale.left(2))
	if voices.is_empty():
		voices = PackedStringArray(DisplayServer.tts_get_voices().map(func(v: Dictionary) -> String: return v["id"]))
	if voices.is_empty():
		return # no speech on this system (headless runs have none)
	DisplayServer.tts_speak(line, voices[0], SPEECH_VOLUME, 1.0, 1.0, 0, true)


## The line a control says: its label (the settings row's name, or its own text), its role, its value.
static func describe(c: Control) -> String:
	var row_label: String = _row_label(c)
	if c is CheckButton or c is CheckBox:
		var on: bool = (c as BaseButton).button_pressed
		return Bindings.narration_line(row_label if row_label != "" else (c as Button).text, Shell.t("narrate.toggle"),
				Shell.t("narrate.on" if on else "narrate.off"))
	if c is Range:
		var r: Range = c
		var value: String = ("%d%%" % roundi(r.value * 100.0)) if r.max_value <= 1.0 else str(r.value)
		return Bindings.narration_line(row_label, Shell.t("narrate.slider"), value)
	if c is OptionStepper:
		var s: OptionStepper = c
		var value: String = s.labels[s.index] if s.index < s.labels.size() else s.text
		return Bindings.narration_line(row_label, Shell.t("narrate.choice"), value)
	if c is Button:
		if row_label != "":
			return Bindings.narration_line(row_label, Shell.t("narrate.button"), (c as Button).text)
		return Bindings.narration_line((c as Button).text, Shell.t("narrate.button"))
	return Bindings.narration_line(row_label if row_label != "" else c.tooltip_text, "")


## The name label of the settings row a control sits in ("" outside a row).
static func _row_label(c: Control) -> String:
	var node: Node = c.get_parent()
	while node != null and not (node is PanelContainer and str(node.name).begins_with("Row_")):
		node = node.get_parent()
	if node == null:
		return ""
	var label: Label = node.find_child("Label", true, false) as Label
	return label.text if label != null else ""

# {{FOOTER}}
