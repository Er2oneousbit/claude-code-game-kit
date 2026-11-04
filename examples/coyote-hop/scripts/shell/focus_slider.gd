# ---------------------------------------------------------------------------
# focus_slider.gd
# Purpose : An HSlider that shows keyboard and gamepad focus with the theme's focus outline, so a focused slider
#           looks different from a hovered one.
# Usage   : var slider := FocusSlider.new()   (instead of HSlider.new(); everything else is the same)
# Notes   : Godot's Slider has no focus stylebox (4.7: only slider, grabber_area, grabber_area_highlight) and draws
#           the same highlight for hover and focus. This draws the "focus" stylebox of the HSlider theme type on
#           top when the theme has one (UiTheme.plain does), else the Button one, so a Dotwork UI kit theme's
#           focus outline shows here too. Like a Button, it hides the outline while focus is hidden (focus taken
#           with a mouse click).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name FocusSlider
extends HSlider


func ring() -> StyleBox:
	# The outline to draw now, or null: only while the slider has visible focus
	if not has_focus(true):
		return null
	if has_theme_stylebox("focus"):
		return get_theme_stylebox("focus")
	return get_theme_stylebox("focus", "Button") # always set: Godot's default theme has one


func _notification(what: int) -> void:
	if what == NOTIFICATION_FOCUS_ENTER or what == NOTIFICATION_FOCUS_EXIT:
		queue_redraw()


func _draw() -> void:
	# Runs after the slider's own drawing, so the outline sits on top of the track and grabber
	var sb: StyleBox = ring()
	if sb != null:
		draw_style_box(sb, Rect2(Vector2.ZERO, size))
