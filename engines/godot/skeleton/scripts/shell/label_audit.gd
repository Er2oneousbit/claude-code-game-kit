# ---------------------------------------------------------------------------
# label_audit.gd
# Purpose : The pseudo-locale check: every visible Label and Button on screen must show text that went through
#           the string tables (pseudo text starts with "["), must fit its box, and must stay on screen.
# Usage   : var problems := LabelAudit.audit(get_tree().root)    # [] when everything fits
#           (dev.py smoke --locale pseudo runs it after every screen; see scripts/shell/front_end.gd)
# Notes   : Only meaningful with the "pseudo" locale, where every string is about 40 % longer and bracketed:
#           a missing "[" means the text never went through Shell.t() (or the key is missing), a missing "]" or
#           a box narrower than the text means clipping. Text inside a ScrollContainer may scroll out of view
#           vertically (that is what scrolling is for) but must fit horizontally. checked counts the labels seen.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name LabelAudit
extends RefCounted

const SLACK_PX: float = 0.5 # rounding allowance

static var checked: int = 0


static func audit(root: Node) -> PackedStringArray:
	var problems: PackedStringArray = []
	_walk(root, root, problems)
	return problems


static func _walk(node: Node, root: Node, problems: PackedStringArray) -> void:
	if node is CanvasItem and not (node as CanvasItem).is_visible_in_tree():
		return
	if node is CanvasLayer and not (node as CanvasLayer).visible:
		return
	if node is Label:
		_check(node as Control, (node as Label).text, root, problems)
	elif node is Button:
		_check(node as Control, (node as Button).text, root, problems)
	for child: Node in node.get_children():
		_walk(child, root, problems)


static func _check(c: Control, text: String, root: Node, problems: PackedStringArray) -> void:
	var shown: String = text.strip_edges()
	if shown == "":
		return
	checked += 1
	var where: String = str(root.get_path_to(c))
	if not shown.begins_with("["):
		problems.append("%s '%s': not passed through Shell.t() (or the key is missing)" % [where, shown])
		return
	if not shown.ends_with("]"):
		problems.append("%s '%s': cut at the end" % [where, shown])
		return
	var need: float = _needed_width(c, text)
	if c is Label and (c as Label).autowrap_mode != TextServer.AUTOWRAP_OFF:
		var label: Label = c
		if label.get_visible_line_count() < label.get_line_count():
			problems.append("%s '%s': clipped (%d of %d lines fit)" % [where, shown, label.get_visible_line_count(),
					label.get_line_count()])
			return
	elif need > c.size.x + SLACK_PX:
		problems.append("%s '%s': clipped (needs %d px, has %d px)" % [where, shown, ceili(need), floori(c.size.x)])
		return
	var box: Rect2 = c.get_global_transform_with_canvas() * Rect2(Vector2.ZERO, c.size)
	var screen: Rect2 = c.get_viewport_rect()
	var scroll: ScrollContainer = _scroll_parent(c)
	if scroll != null:
		var area: Rect2 = scroll.get_global_transform_with_canvas() * Rect2(Vector2.ZERO, scroll.size)
		if box.position.x < area.position.x - SLACK_PX or box.end.x > area.end.x + SLACK_PX:
			problems.append("%s '%s': wider than its scroll area" % [where, shown])
	elif not screen.grow(SLACK_PX).encloses(box):
		problems.append("%s '%s': off screen (%s outside %s)" % [where, shown, box, screen])


static func _needed_width(c: Control, text: String) -> float:
	var font: Font = c.get_theme_font("font")
	var font_size: int = c.get_theme_font_size("font_size")
	var width: float = 0.0
	for line: String in text.split("\n"):
		width = maxf(width, font.get_string_size(line, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x)
	var style: StyleBox = c.get_theme_stylebox("normal")
	if style != null:
		width += style.get_margin(SIDE_LEFT) + style.get_margin(SIDE_RIGHT)
	if c is Button and (c as Button).icon != null:
		width += (c as Button).icon.get_width() + c.get_theme_constant("h_separation")
	return width


static func _scroll_parent(c: Node) -> ScrollContainer:
	var p: Node = c.get_parent()
	while p != null:
		if p is ScrollContainer:
			return p
		p = p.get_parent()
	return null

# {{FOOTER}}
