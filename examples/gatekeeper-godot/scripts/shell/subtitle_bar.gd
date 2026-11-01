# ---------------------------------------------------------------------------
# subtitle_bar.gd
# Purpose : Subtitles and sound captions at the bottom of the screen, read from a dialogue.built.json file and
#           styled by the player's settings (on/off, size, background opacity, speaker names, barks, captions).
# Usage   : var bar := SubtitleBar.new(); hud_root.add_child(bar)
#           bar.play("guide.intro")               # a line id from data/dialogue/sample.built.json
#           bar.caption("box_hit")                # an SFX caption ("[box thuds]"), only with captions_sfx on
#           bar.typewriter = true                 # reveal letter by letter (from the file's reveal times)
# Notes   : Classic mode shows the file's cues (at most two lines of about 42 characters each); typewriter mode
#           shows the whole text as it is revealed. Barks (kind "bark") appear only with subtitle_barks on. Time
#           runs on the frame delta, so pausing the game pauses the line. Text from the file goes through
#           Shell.content(), so the pseudo locale marks it too. Not colour alone: the speaker name is text.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name SubtitleBar
extends MarginContainer

const SIZE_FONT: Dictionary = {"small": 10, "medium": 12, "large": 16, "xl": 20} # px at the 640x360 base
const SIDE_MARGIN: int = 48
const BOTTOM_MARGIN: int = 14
const CAPTION_MIN_S: float = 1.0

var typewriter: bool = false
var dialogue: Dictionary = {}
var _line: Dictionary = {}
var _t: float = 0.0
var _caption_left: float = 0.0
var _panel: PanelContainer
var _speaker: Label
var _text: Label
var _caption: Label
var _style: StyleBoxFlat


func _init() -> void:
	name = "SubtitleBar"
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	grow_vertical = Control.GROW_DIRECTION_BEGIN
	add_theme_constant_override("margin_left", SIDE_MARGIN)
	add_theme_constant_override("margin_right", SIDE_MARGIN)
	add_theme_constant_override("margin_bottom", BOTTOM_MARGIN)
	var column: VBoxContainer = VBoxContainer.new()
	column.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(column)
	_caption = _make_label("Caption")
	column.add_child(_caption)
	_panel = PanelContainer.new()
	_panel.name = "Panel"
	_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_style = StyleBoxFlat.new()
	_style.set_corner_radius_all(3)
	_style.content_margin_left = 8
	_style.content_margin_right = 8
	_style.content_margin_top = 3
	_style.content_margin_bottom = 3
	_panel.add_theme_stylebox_override("panel", _style)
	column.add_child(_panel)
	var lines: VBoxContainer = VBoxContainer.new()
	lines.add_theme_constant_override("separation", 0)
	_panel.add_child(lines)
	_speaker = _make_label("Speaker")
	lines.add_child(_speaker)
	_text = _make_label("Text")
	lines.add_child(_text)
	_panel.hide()
	_caption.hide()


func _ready() -> void:
	if dialogue.is_empty():
		dialogue = DialogueData.parse(AtomicFile.read_text(Shell.DIALOGUE_FILE))
	Shell.settings_changed.connect(_on_settings_changed)
	_restyle()


func play(id: String) -> bool:
	# Starts a line; false when it does not exist or the settings hide it (subtitles off, a bark without barks on)
	var entry: Dictionary = DialogueData.line(dialogue, id)
	if not DialogueData.should_show(entry, Shell.settings["access"]):
		return false
	_line = entry
	_t = 0.0
	_restyle()
	_update()
	_panel.show()
	return true


func caption(event_id: String) -> bool:
	if not bool(Shell.access("captions_sfx")):
		return false
	var entry: Dictionary = DialogueData.caption(dialogue, event_id)
	if entry.is_empty():
		return false
	_caption.text = Shell.content(str(entry.get("text", "")))
	_caption_left = maxf(CAPTION_MIN_S, float(entry.get("min_s", CAPTION_MIN_S)))
	_caption.show()
	return true


func is_playing() -> bool:
	return not _line.is_empty()


func is_fully_shown() -> bool:
	return is_playing() and DialogueData.revealed(_line, _t) >= str(_line.get("text", "")).length()


func _process(delta: float) -> void:
	if _caption_left > 0.0:
		_caption_left -= delta
		if _caption_left <= 0.0:
			_caption.hide()
	if _line.is_empty():
		return
	_t += delta
	if DialogueData.finished(_line, _t):
		_line = {}
		_panel.hide()
		return
	_update()


func _update() -> void:
	var speaker: String = str(_line.get("name", ""))
	_speaker.visible = bool(Shell.access("speaker_names")) and speaker != ""
	_speaker.text = Shell.content(speaker)
	var colour: Variant = _line.get("color")
	_speaker.add_theme_color_override("font_color",
			Color.html(colour) if typeof(colour) == TYPE_STRING and Color.html_is_valid(colour) else UiTheme.FOCUS)
	if typewriter:
		var full: String = str(_line.get("text", ""))
		_text.text = Shell.content(full)
		var shown: int = DialogueData.revealed(_line, _t)
		_text.visible_ratio = 1.0 if full.is_empty() else float(shown) / float(full.length())
	else:
		_text.visible_ratio = 1.0
		_text.text = Shell.content("\n".join(DialogueData.cue_lines(_line, _t)))


func _restyle() -> void:
	var access: Dictionary = Shell.settings["access"]
	var font_size: int = int(SIZE_FONT.get(access["subtitle_size"], SIZE_FONT["medium"]))
	for l: Label in [_speaker, _text, _caption]:
		l.add_theme_font_size_override("font_size", font_size)
	_style.bg_color = Color(0, 0, 0, float(access["subtitle_background"]))
	if not bool(access["subtitles"]) and is_playing():
		_line = {}
		_panel.hide()


func _on_settings_changed(section: String, _key: String) -> void:
	if section == "access":
		_restyle()


func _make_label(node_name: String) -> Label:
	var l: Label = Label.new()
	l.name = node_name
	l.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	l.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	l.mouse_filter = Control.MOUSE_FILTER_IGNORE
	l.add_theme_color_override("font_outline_color", Color.BLACK)
	l.add_theme_constant_override("outline_size", 2)
	return l
