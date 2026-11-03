# ---------------------------------------------------------------------------
# audio_access.gd
# Purpose : Audio accessibility rules (engine-free, so GUT runs them headless against data/golden/access.json): which
#           settings slider turns which bus of data/audio_events.json up or down, and which arrow a directional
#           caption gets when the sound comes from off screen.
# Usage   : AudioAccess.user_bus_gains(events["buses"], Shell.settings["audio"])   # {"music": 0.8, "ambience": 1.0, ...}
#           AudioAccess.caption_arrow(src.x - view_mid.x, src.y - view_mid.y, view.x / 2, view.y / 2)   # "" | "←" | "↗"
#           bar.caption("growl", {"dx": dx, "dy": dy, "half_w": hw, "half_h": hh})      # SubtitleBar uses the arrow
# Notes   : A port of tools/audio/wavesmith/access.py (the reference). Sliders are linear 0..1 (settings.audio). A bus
#           follows the slider named in SLIDER_FOR_BUS; when one of its parent buses already follows the same slider
#           it gets 1, so a slider never counts twice (ambience under sfx); buses without a slider get 1; bad values
#           clamp to 0..1 and a missing or non-numeric one counts as 1. Parents default to "master"; a cycle stops
#           after one step per bus. In this skeleton the Shell already applies the sliders to the fixed AudioServer
#           buses Master, Music, SFX, UI and Voice (shell.gd _apply_audio), and Godot's bus sends obey the same
#           never-twice rule on their own; so nothing here is wired into the shell. Use user_bus_gains only for buses
#           your game mixes itself (a logical bus that is NOT routed through one of those AudioServer buses),
#           or you apply a slider twice.
#           Arrows: screen coordinates (y grows downwards), eight directions, nothing while the source is inside the
#           view (edges included); k = floor(atan2(dy, dx) / 45 degrees + 0.5) mod 8, clockwise from the right.
#           GDScript's round() is not used for k: floor(x + 0.5) is the rule in every engine.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name AudioAccess
extends RefCounted

# Bus name -> settings slider. Edit it when your audio_events.json uses other bus names.
const SLIDER_FOR_BUS: Dictionary = {"master": "master", "music": "music", "sfx": "sfx", "ambience": "sfx", "ui": "ui",
		"dialogue": "voice", "voice": "voice"}
const ARROWS: PackedStringArray = ["→", "↘", "↓", "↙", "←", "↖", "↑", "↗"] # k = 0..7, clockwise from the right (y down)
const LEFT_ARROWS: String = "←↖↙" # captions put these before the text, the rest after it


static func clamp01(v: Variant) -> float:
	# A slider value: numbers clamp to 0..1; anything else (missing, text, bool, NaN, infinity) counts as 1
	if typeof(v) != TYPE_INT and typeof(v) != TYPE_FLOAT:
		return 1.0
	var f: float = float(v)
	if not is_finite(f):
		return 1.0
	return clampf(f, 0.0, 1.0)


static func _parent_of(buses: Dictionary, bus: Variant) -> Variant:
	# A bus's parent; a bus without one (or whose parent is not text: a number, null) hangs under "master", and
	# master itself has none (null), as in access.py
	var entry: Variant = buses.get(bus)
	var p: Variant = (entry as Dictionary).get("parent") if typeof(entry) == TYPE_DICTIONARY else null
	if typeof(p) == TYPE_STRING or typeof(p) == TYPE_STRING_NAME:
		return p
	return null if typeof(bus) == TYPE_STRING and bus == "master" else "master"


static func user_bus_gains(buses: Dictionary, sliders: Dictionary, mapping: Dictionary = SLIDER_FOR_BUS) -> Dictionary:
	# {bus: linear gain} from the player's sliders, a slider never applied twice down one branch
	var out: Dictionary = {}
	var count: int = buses.size()
	for bus: Variant in buses:
		var slider: Variant = mapping.get(bus)
		var inherited: bool = false
		# walk up the parents, at most one step per bus, so a cycle cannot hang
		var p: Variant = _parent_of(buses, bus)
		var n: int = 0
		while p != null and n < count:
			if slider != null and mapping.get(p) == slider:
				inherited = true
			p = _parent_of(buses, p)
			n += 1
		out[bus] = 1.0 if slider == null or inherited else clamp01(sliders.get(slider))
	return out


static func caption_direction(dx: float, dy: float, half_w: float, half_h: float) -> int:
	# -1 while the source is inside the view (edges included), else 0..7 clockwise from the right
	if not (is_finite(dx) and is_finite(dy)):
		return -1
	if absf(dx) <= half_w and absf(dy) <= half_h:
		return -1
	return posmod(floori(atan2(dy, dx) / (PI / 4.0) + 0.5), 8)


static func caption_arrow(dx: float, dy: float, half_w: float, half_h: float) -> String:
	var k: int = caption_direction(dx, dy, half_w, half_h)
	return "" if k < 0 else ARROWS[k]


static func with_arrow(text: String, arrow: String) -> String:
	# The arrow on the side the sound comes from: left-pointing arrows before the text, the rest after it
	if arrow == "":
		return text
	return "%s %s" % [arrow, text] if LEFT_ARROWS.contains(arrow) else "%s %s" % [text, arrow]

# {{FOOTER}}
