# ---------------------------------------------------------------------------
# test_access_colours.gd
# Purpose : The demo palette per colour-blind setting comes from data/access/colours.json, the file
#           tools/access/colour_check.py checks (#169), and the full-screen filter runs only when that file asks for
#           it and has no palette for the mode.
# Usage   : python tools/dev.py test --filter test_access_colours.gd
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest


func test_every_mode_in_the_file_is_the_palette_the_demo_draws() -> void:
	var data: Dictionary = AccessColours.load_data()
	var palettes: Dictionary = data["palettes"]
	assert_eq(palettes.size(), 4, "none and each colour-blind mode")
	for mode: String in palettes:
		var pal: Dictionary = AccessColours.palette(data, mode)
		for key: String in palettes[mode]:
			assert_eq(pal[key], Color.html(str(palettes[mode][key])), "%s.%s" % [mode, key])


func test_the_filter_runs_only_when_asked_and_no_palette_covers_the_mode() -> void:
	var data: Dictionary = AccessColours.load_data()
	assert_false(bool(data.get("filter", true)), "the kit's own file swaps palettes instead (#169)")
	assert_eq(AccessColours.filter_mode(data, "deuteranopia"), "none")
	var filtered: Dictionary = {"filter": true, "palettes": {"none": {"player": "#ffffff"}}}
	assert_eq(AccessColours.filter_mode(filtered, "deuteranopia"), "deuteranopia")
	assert_eq(AccessColours.palette(filtered, "tritanopia")["player"], Color.WHITE, "a mode with no palette: none")
	var both: Dictionary = {"filter": true, "palettes": {"none": {}, "protanopia": {}}}
	assert_eq(AccessColours.filter_mode(both, "protanopia"), "none", "its own palette wins over the filter")


func test_a_missing_file_gives_an_empty_palette() -> void:
	var data: Dictionary = AccessColours.load_data("res://no/such/colours.json")
	assert_eq(AccessColours.palette(data, "none"), {})
	assert_eq(AccessColours.filter_mode(data, "protanopia"), "none")

# {{FOOTER}}
