# ---------------------------------------------------------------------------
# access_colours.gd
# Purpose : The game's important colours per colour-blind setting, from data/access/colours.json: the palette the
#           demo (and your game) draws with, and whether the full-screen colour-blind filter runs at all.
# Usage   : var data := AccessColours.load_data()                 # once (Shell does it)
#           var pal := AccessColours.palette(data, "deuteranopia")  # {"player": Color, "target": Color, ...}
#           Shell.palette()                                        # the palette for the current setting
# Notes   : python tools/access/colour_check.py pairs checks the same file: every declared pair must stay apart as a
#           protanope, deuteranope or tritanope sees it (SOP-20). A mode with no palette there falls back to "none",
#           through the kit's colour-blind filter when "filter" is true. The filter is off in the kit's own file: on
#           the demo's colours it made the player and the box harder to tell apart, not easier (#169).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name AccessColours
extends RefCounted

const DATA_FILE: String = "res://data/access/colours.json"


## The colour data ({"filter": bool, "palettes": {mode: {name: "#rrggbb"}}}), or an empty palette set when the
## file is missing or broken (logged).
static func load_data(path: String = DATA_FILE) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {"filter": false, "palettes": {"none": {}}}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if typeof(parsed) != TYPE_DICTIONARY or typeof(parsed.get("palettes")) != TYPE_DICTIONARY:
		push_warning("%s is not a colour data file (palettes missing): the demo uses no palette" % path)
		return {"filter": false, "palettes": {"none": {}}}
	return parsed


## {name: Color} for a colour-blind mode; a mode without its own palette uses "none".
static func palette(data: Dictionary, mode: String) -> Dictionary:
	var palettes: Dictionary = data.get("palettes", {})
	var src: Dictionary = palettes.get(mode, palettes.get("none", {}))
	var out: Dictionary = {}
	for key in src:
		out[key] = Color.html(str(src[key]))
	return out


## The mode the full-screen filter should run in: the setting's mode only when the file asks for the filter and
## has no palette for that mode.
static func filter_mode(data: Dictionary, mode: String) -> String:
	if not bool(data.get("filter", false)) or data.get("palettes", {}).has(mode):
		return "none"
	return mode

# {{FOOTER}}
