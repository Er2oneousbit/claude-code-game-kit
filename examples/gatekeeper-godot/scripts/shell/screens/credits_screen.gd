# ---------------------------------------------------------------------------
# credits_screen.gd
# Purpose : Credits: scrolls CREDITS.md (made from docs/ASSET_LOG.md, see SOP-04) or a placeholder until it exists.
# Usage   : front.open_credits()   (from the main menu)
# Notes   : The text scrolls by itself (not with reduce motion); up/down scroll by hand and stop the auto-scroll.
#           Markdown is shown as plain text with the heading marks removed. Exports include CREDITS.md through
#           the include filter in export_presets.cfg.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name CreditsScreen
extends ShellScreen

const SCROLL_PX_PER_S: float = 14.0
const MANUAL_STEP_PX: int = 24
const START_DELAY_S: float = 1.0

var _scroll: ScrollContainer
var _offset: float = 0.0
var _auto: bool = true
var _delay: float = START_DELAY_S


func _init(p_front: FrontEnd) -> void:
	super(p_front, "credits")


func build() -> void:
	var col: VBoxContainer = margin_box()
	col.add_child(label(Shell.t("credits.title"), UiTheme.HEADING_FONT, "Heading"))
	_scroll = ScrollContainer.new()
	_scroll.name = "Scroll"
	_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	col.add_child(_scroll)
	var body: Label = label(_credits_text(), 1.0, "Body")
	body.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_scroll.add_child(body)
	col.add_child(button(Shell.t("settings.back"), "Back", front.back))


func _credits_text() -> String:
	var text: Variant = AtomicFile.read_text(Shell.CREDITS_FILE)
	if typeof(text) == TYPE_NIL or str(text).strip_edges() == "":
		return Shell.t("credits.placeholder")
	var lines: PackedStringArray = []
	for line: String in str(text).split("\n"):
		lines.append(line.lstrip("#").strip_edges() if line.begins_with("#") else line.strip_edges(false, true))
	return Shell.content("\n".join(lines).strip_edges())


func _process(delta: float) -> void:
	if _scroll == null or not _auto or bool(Shell.access("reduce_motion")):
		return
	_delay -= delta
	if _delay > 0.0:
		return
	_offset += SCROLL_PX_PER_S * delta
	_scroll.scroll_vertical = int(_offset)


func _unhandled_input(event: InputEvent) -> void:
	if is_top() and (event.is_action_pressed("ui_up", true) or event.is_action_pressed("ui_down", true)):
		_auto = false
		var dir: int = -1 if event.is_action_pressed("ui_up", true) else 1
		_scroll.scroll_vertical += dir * MANUAL_STEP_PX
		get_viewport().set_input_as_handled()
		return
	super(event)
