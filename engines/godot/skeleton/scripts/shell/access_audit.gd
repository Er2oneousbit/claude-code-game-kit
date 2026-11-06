# ---------------------------------------------------------------------------
# access_audit.gd
# Purpose : What a player sees on one screen, as data for tools/access/sweep.py (#91, #85): every visible text with
#           its size, colour, the colour behind it and whether it fits; which controls focus can reach with the
#           arrow keys and the gamepad, and whether focus looks different from hover.
# Usage   : var report := AccessAudit.screen(get_tree().root, "settings/audio")   # a Dictionary, logged as JSON
#           (python tools/dev.py smoke --drive access runs it on every screen; sweep.py checks the result)
# Notes   : Headless Godot draws nothing, so colours come from the theme, never from pixels: a text's background is
#           the nearest thing behind it in the tree (its own button style, a panel, a ColorRect) blended down to the
#           screen's clear colour. A text over the game world has no background in the tree: it is reported with
#           what lies between it and the game (its panel layers), and an outline counts as its background. Sizes
#           are in the design resolution (project.godot's viewport size); sweep.py scales them to the window the way
#           the report's "scaling" says (integer: whole numbers, as the stretch does).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name AccessAudit
extends RefCounted

const BUTTON_STATES: PackedStringArray = ["normal", "focus"] # the states a player reads a button in
const SIDES: Array[Side] = [SIDE_LEFT, SIDE_TOP, SIDE_RIGHT, SIDE_BOTTOM]
const MAX_FOCUS: int = 400 # focus graph walk limit (a screen with more controls is reported, not walked)


## The report for the screen under root: {"screen", "base", "texts": [...], "focus": {...}}.
static func screen(root: Node, where: String) -> Dictionary:
	var texts: Array = []
	var focusable: Array[Control] = []
	_walk(root, texts, focusable)
	var vp: Vector2 = root.get_viewport().get_visible_rect().size
	var win: Vector2i = root.get_tree().root.size
	return {"screen": where, "visible": [vp.x, vp.y], "window": [win.x, win.y],
			"design": [ProjectSettings.get_setting("display/window/size/viewport_width"),
					ProjectSettings.get_setting("display/window/size/viewport_height")],
			"scaling": ProjectSettings.get_setting("display/window/stretch/scale_mode", "fractional"),
			"texts": texts, "focus": _focus(root, focusable)}


## Which actions have a gamepad binding and which a keyboard one (the shell's navigation must have both).
static func input_report(actions: PackedStringArray) -> Dictionary:
	var out: Dictionary = {}
	for action: String in actions:
		var pad: bool = false
		var keys: bool = false
		for e: InputEvent in InputMap.action_get_events(action):
			pad = pad or e is InputEventJoypadButton or e is InputEventJoypadMotion
			keys = keys or e is InputEventKey
		out[action] = {"gamepad": pad, "keyboard": keys}
	return out


# ---- texts ----------------------------------------------------------------------

static func _walk(node: Node, texts: Array, focusable: Array[Control]) -> void:
	if node is CanvasItem and not (node as CanvasItem).is_visible_in_tree():
		return
	if node is CanvasLayer and not (node as CanvasLayer).visible:
		return
	if node is Control:
		var c: Control = node
		if c.focus_mode == Control.FOCUS_ALL:
			focusable.append(c)
		if c is Button and (c as Button).text.strip_edges() != "":
			for state: String in BUTTON_STATES:
				texts.append(_text(c, (c as Button).text, state))
		elif c is Label and (c as Label).text.strip_edges() != "" and (c as Label).visible_ratio > 0.0:
			texts.append(_text(c, (c as Label).text, ""))
	for child: Node in node.get_children():
		_walk(child, texts, focusable)


static func _text(c: Control, text: String, state: String) -> Dictionary:
	var colour_name: String = "font_color"
	if state == "focus":
		colour_name = "font_focus_color"
	var fg: Color = c.get_theme_color(colour_name) * _modulate(c) # what is drawn: theme colour times modulates
	var outline: int = c.get_theme_constant("outline_size")
	var bg: Variant = _background(c, state)
	var row: Dictionary = {
		"node": str(c.get_path()), "text": text.strip_edges().left(60), "state": state,
		"px": c.get_theme_font_size("font_size"), "fg": "#" + fg.to_html(false),
		"bg": null if bg == null else "#" + (bg as Color).to_html(false),
		"outline": "#" + c.get_theme_color("font_outline_color").to_html(false) if outline > 0 else null,
		"fits": _fits(c, text),
	}
	if bg == null: # over the game: what lies between the text and the world, top first, for a worst-case check
		var layers: Array = []
		for col: Color in _layers(c, state):
			layers.append(["#" + col.to_html(false), snappedf(col.a, 0.001)])
		row["over_game"] = layers
	return row


## The background colours from c outward until one is opaque (top first), as _background walks them.
static func _layers(c: Control, state: String) -> Array[Color]:
	var layers: Array[Color] = []
	var node: Node = c
	var first: bool = true
	while node != null:
		var col: Variant = _own_background(node, state if first else "")
		first = false
		if col != null and (col as Color).a > 0.0:
			layers.append(col)
			if (col as Color).a >= 0.999:
				break
		if node is CanvasLayer or node == c.get_tree().root:
			break
		node = node.get_parent()
	return layers


## The product of c's self_modulate and every modulate from c up to its canvas layer.
static func _modulate(c: CanvasItem) -> Color:
	var m: Color = c.self_modulate
	var node: Node = c
	while node is CanvasItem:
		m *= (node as CanvasItem).modulate
		node = node.get_parent()
	return Color(m.r, m.g, m.b, 1.0)


## The opaque colour behind c (its own style for a button state, then each ancestor's), or null over the game.
static func _background(c: Control, state: String) -> Variant:
	var layers: Array[Color] = _layers(c, state)
	if layers.is_empty() or layers[-1].a < 0.999:
		if not _is_menu(c):
			return null
		layers.append(RenderingServer.get_default_clear_color())
	var out: Color = layers[-1]
	for i: int in range(layers.size() - 2, -1, -1):
		out = out.lerp(Color(layers[i].r, layers[i].g, layers[i].b), layers[i].a)
	out.a = 1.0
	return out


static func _own_background(node: Node, state: String) -> Variant:
	if node is ColorRect:
		return (node as ColorRect).color
	if node is ShellScreen and (node as ShellScreen).opaque: # an opaque screen draws its backdrop in _draw()
		return UiTheme.backdrop()
	var box: StyleBox = null
	if node is Button and state != "":
		# Godot draws the focus box over the normal one: a focus box that fills nothing shows normal's fill
		box = (node as Control).get_theme_stylebox(state)
		if state == "focus" and not (box is StyleBoxFlat and (box as StyleBoxFlat).draw_center):
			box = (node as Control).get_theme_stylebox("normal")
	elif node is PanelContainer or node is Panel:
		box = (node as Control).get_theme_stylebox("panel")
	if box is StyleBoxFlat and (box as StyleBoxFlat).draw_center:
		return (box as StyleBoxFlat).bg_color
	return null


## True when the text is part of the menus (a front-end screen), not a HUD drawn over the game.
static func _is_menu(c: Control) -> bool:
	var node: Node = c
	while node != null:
		if node is ShellScreen:
			return true
		node = node.get_parent()
	return false


static func _fits(c: Control, text: String) -> bool:
	if c is Label and (c as Label).autowrap_mode != TextServer.AUTOWRAP_OFF:
		return (c as Label).get_visible_line_count() >= (c as Label).get_line_count()
	var font: Font = c.get_theme_font("font")
	var size: int = c.get_theme_font_size("font_size")
	var width: float = 0.0
	for line: String in text.split("\n"):
		width = maxf(width, font.get_string_size(line, HORIZONTAL_ALIGNMENT_LEFT, -1, size).x)
	var style: StyleBox = c.get_theme_stylebox("normal")
	if c is Button and style != null:
		width += style.get_margin(SIDE_LEFT) + style.get_margin(SIDE_RIGHT)
	if width > c.size.x + 0.5:
		return false
	var box: Rect2 = c.get_global_transform_with_canvas() * Rect2(Vector2.ZERO, c.size)
	var node: Node = c.get_parent()
	while node != null and not node is ScrollContainer:
		node = node.get_parent()
	if node != null: # scrolled out of view vertically is what scrolling is for; sideways it must fit (LabelAudit)
		var scroll: ScrollContainer = node
		var area: Rect2 = scroll.get_global_transform_with_canvas() * Rect2(Vector2.ZERO, scroll.size)
		return box.position.x >= area.position.x - 0.5 and box.end.x <= area.end.x + 0.5
	return c.get_viewport_rect().grow(0.5).encloses(box)


# ---- focus ----------------------------------------------------------------------

static func _focus(root: Node, focusable: Array[Control]) -> Dictionary:
	var start: Control = root.get_viewport().gui_get_focus_owner()
	var reached: Dictionary = {}
	if start != null:
		var queue: Array[Control] = [start]
		reached[start] = true
		while not queue.is_empty() and reached.size() < MAX_FOCUS:
			var c: Control = queue.pop_front()
			var next: Array[Control] = [c.find_next_valid_focus(), c.find_prev_valid_focus()]
			for side: Side in SIDES:
				next.append(c.find_valid_focus_neighbor(side))
			for n: Control in next:
				if n != null and not reached.has(n) and n.is_visible_in_tree():
					reached[n] = true
					queue.append(n)
	var missed: PackedStringArray = []
	for c: Control in focusable:
		if not reached.has(c):
			missed.append(str(c.get_path()))
	var same_as_hover: PackedStringArray = []
	for c: Control in focusable:
		if c is BaseButton and _style_key(c.get_theme_stylebox("focus")) == _style_key(c.get_theme_stylebox("hover")):
			same_as_hover.append(str(c.get_path()))
	return {"start": str(start.get_path()) if start != null else "", "controls": focusable.size(),
			"reached": reached.size(), "unreached": missed, "focus_like_hover": same_as_hover}


## What a style box draws, as a comparable value (an empty box draws nothing: a focus that looks like nothing).
static func _style_key(box: StyleBox) -> String:
	if box == null or box is StyleBoxEmpty:
		return "empty"
	if box is StyleBoxFlat:
		var f: StyleBoxFlat = box
		return "flat %s %s %s %d %d" % [f.draw_center, f.bg_color.to_html(), f.border_color.to_html(),
				f.border_width_left + f.border_width_top + f.border_width_right + f.border_width_bottom,
				f.expand_margin_left]
	return "%s %s" % [box.get_class(), box.get_instance_id()]
