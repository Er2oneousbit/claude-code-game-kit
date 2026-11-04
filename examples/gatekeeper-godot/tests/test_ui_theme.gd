# ---------------------------------------------------------------------------
# test_ui_theme.gd
# Purpose : The menus' focus outline: every focusable control in the plain theme gets an outline in the focus
#           colour that is not its hover look, and sliders (which Godot draws with one highlight for hover and
#           focus) get that outline from FocusSlider.
# Usage   : python tools/dev.py test --filter test_ui_theme.gd
# Notes   : SOP-20: focus visible on every control. No running game needed; the slider test adds one node to the
#           test tree.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest


func _is_focus_outline(sb: StyleBox) -> bool:
	var flat: StyleBoxFlat = sb as StyleBoxFlat
	return flat != null and not flat.draw_center and flat.border_color == UiTheme.FOCUS \
		and flat.border_width_left == UiTheme.FOCUS_WIDTH


func test_every_focusable_type_has_an_outline_unlike_hover() -> void:
	var th: Theme = UiTheme.plain()
	for type: String in UiTheme.BUTTON_TYPES:
		assert_true(_is_focus_outline(th.get_stylebox("focus", type)), "%s focus is the outline" % type)
		assert_false(_is_focus_outline(th.get_stylebox("hover", type)), "%s hover is not" % type)
	assert_true(_is_focus_outline(th.get_stylebox("focus", "HSlider")), "HSlider focus is the outline")
	assert_false(_is_focus_outline(th.get_stylebox("grabber_area_highlight", "HSlider")),
		"the slider's hover highlight is not the outline")


func test_godot_sliders_have_no_focus_style_of_their_own() -> void:
	# Why FocusSlider exists; if a later Godot adds one, FocusSlider may be retired (both would draw)
	assert_false(ThemeDB.get_default_theme().get_stylebox_list("HSlider").has("focus"))


func test_focus_slider_outlines_focus_only() -> void:
	var host: Control = Control.new()
	host.theme = UiTheme.plain()
	add_child_autofree(host)
	var slider: FocusSlider = FocusSlider.new()
	host.add_child(slider)
	assert_null(slider.ring(), "no outline without focus (hover only highlights)")
	slider.grab_focus()
	assert_true(slider.has_focus())
	assert_true(_is_focus_outline(slider.ring()), "focused: the theme's focus outline")
	slider.release_focus()
	assert_null(slider.ring(), "outline gone when focus leaves")
	slider.grab_focus(true) # focus taken by a mouse click is hidden, as on a Button
	assert_null(slider.ring(), "no outline while focus is hidden")


func test_focus_slider_falls_back_to_the_button_outline() -> void:
	# A theme without an HSlider focus style (a Dotwork UI kit theme) still gets an outline: the Button one
	var host: Control = Control.new()
	var th: Theme = Theme.new()
	var button_focus: StyleBoxFlat = UiTheme.focus_box()
	th.set_stylebox("focus", "Button", button_focus)
	host.theme = th
	add_child_autofree(host)
	var slider: FocusSlider = FocusSlider.new()
	host.add_child(slider)
	slider.grab_focus()
	assert_eq(slider.ring(), button_focus)
