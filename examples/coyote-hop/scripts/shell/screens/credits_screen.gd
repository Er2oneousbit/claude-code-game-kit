# ---------------------------------------------------------------------------
# credits_screen.gd
# Purpose : Credits: scrolls CREDITS.md (made from docs/ASSET_LOG.md, see SOP-04) or a placeholder until it exists.
# Usage   : front.open_credits()   (from the main menu)
# Notes   : The text scrolls by itself (not with reduce motion); up/down scroll by hand and stop the auto-scroll.
#           Markdown is shown as plain text with HTML comments and heading marks removed (plain_text, tested in
#           tests/test_credits_text.gd against data/golden/credits.json). Exports include CREDITS.md through
#           the include filter in export_presets.cfg.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name CreditsScreen
extends ShellScreen

const SCROLL_PX_PER_S: float = 14.0
const MANUAL_STEP_PX: int = 24
const START_DELAY_S: float = 1.0
const COMMENT_OPEN: String = "<!--"
const COMMENT_CLOSE: String = "-->"

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
	var plain: String = "" if typeof(text) == TYPE_NIL else plain_text(str(text))
	if plain == "":
		return Shell.t("credits.placeholder")
	return Shell.content(plain)


## CREDITS.md as the screen shows it: HTML comments out (tools/credits.py writes one, #279), heading marks off.
static func plain_text(markdown: String) -> String:
	var lines: PackedStringArray = []
	for line: String in strip_html_comments(markdown).split("\n"):
		lines.append(line.lstrip("#").strip_edges() if line.begins_with("#") else line.strip_edges(false, true))
	return "\n".join(lines).strip_edges()


## Every <!-- --> comment removed, one line or many (an unclosed one runs to the end); a line that held only
## comments goes, with one blank line after it when a blank line came before. tools/golden_vectors.py
## strip_html_comments is the spec, data/golden/credits.json the cases.
static func strip_html_comments(text: String) -> String:
	var out: PackedStringArray = []
	var in_comment: bool = false
	var skip_blank: bool = false
	for line: String in text.replace("\r\n", "\n").split("\n"):
		var kept: String = ""
		var had: bool = in_comment
		var i: int = 0
		while true:
			if in_comment:
				var end: int = line.find(COMMENT_CLOSE, i)
				if end < 0:
					break
				in_comment = false
				i = end + COMMENT_CLOSE.length()
			else:
				var start: int = line.find(COMMENT_OPEN, i)
				if start < 0:
					kept += line.substr(i)
					break
				kept += line.substr(i, start - i)
				in_comment = true
				had = true
				i = start + COMMENT_OPEN.length()
		if had and _blank(kept):
			skip_blank = out.is_empty() or _blank(out[out.size() - 1])
			continue
		if skip_blank and _blank(kept):
			skip_blank = false
			continue
		skip_blank = false
		out.append(kept)
	return "\n".join(out)


static func _blank(line: String) -> bool:
	for ch: String in line:
		if ch != " " and ch != "\t":
			return false
	return true


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
