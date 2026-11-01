# ---------------------------------------------------------------------------
# game_settings.gd
# Purpose : The player's settings as data (engine-free): built-in defaults, the schema (ranges, choices), loading
#           a settings file that may be old, hand-edited or broken, and the two derived values the game reads
#           (effective shake, telemetry allowed).
# Usage   : var loaded := GameSettings.load_text(text)      # {"settings": Dictionary, "problems": PackedStringArray}
#           var s: Dictionary = loaded.settings              # s.audio.master, s.access.reduce_motion, ...
#           var text := GameSettings.to_text(s)              # what Shell writes to settings.json
# Notes   : Missing fields take defaults, bad ones are fixed (each fix is one problem), unknown keys are kept as they
#           are so a newer game's file survives an older build. Every engine of the kit reads the same file shape.
#           Godot parses every JSON number as a float, so numbers compare numerically. scripts/shell/shell.gd owns
#           the live copy, applies it and saves it. Tested against data/golden/shell.json.
#
# Pseudocode:
#   parse JSON; unreadable or not an object -> defaults + one problem
#   copy every key; version = 1; language: a string of 2..12 characters, else "en"
#   per schema section: not an object -> problem, treat as {}; per field: missing -> default,
#     else fix by rule (bool / num clamp / enum / resolution), a change is a problem
#   input.bindings: not an object -> defaults; per action a list of strings (others dropped, one problem)
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name GameSettings
extends RefCounted

const VERSION: int = 1
const DIFFICULTIES: Array = ["story", "easy", "normal", "hard"]
const COLORBLIND: Array = ["none", "protanopia", "deuteranopia", "tritanopia"]
const SUB_SIZES: Array = ["small", "medium", "large", "xl"]
const GLYPH_SETS: Array = ["auto", "keyboard", "xbox", "playstation", "generic"]
const DISPLAY_MODES: Array = ["windowed", "fullscreen", "borderless"]
const FRAME_CAPS: Array = [0, 30, 60, 120, 144, 240]
const CONSENT: Array = ["unset", "yes", "no"]
const LANG_MIN: int = 2 # a language tag is 2..12 characters ("en", "fr-CA", "zh-Hant-TW")
const LANG_MAX: int = 12

const DEFAULT_SETTINGS: Dictionary = {
	"version": 1,
	"display": {"mode": "windowed", "vsync": true, "frame_cap": 0, "resolution": [1920, 1080], "ui_scale": 1.0},
	"audio": {"master": 1.0, "music": 0.8, "sfx": 1.0, "ui": 1.0, "voice": 1.0, "mono": false},
	"language": "en",
	"access": {"text_scale": 1.0, "subtitles": true, "subtitle_size": "medium", "subtitle_background": 0.6,
			"speaker_names": true, "subtitle_barks": false, "captions_sfx": false, "colorblind": "none",
			"reduce_motion": false, "shake_scale": 1.0, "flash_limit": true, "hold_to_toggle": false,
			"difficulty": "normal", "game_speed": 1.0},
	"input": {"bindings": Bindings.DEFAULT_BINDINGS, "deadzone": 0.2, "invert_y": false, "glyphs": "auto"},
	"telemetry": {"consent": "unset"},
}

# Per field: ["num", lo, hi] | ["bool"] | ["enum", values] | ["res"]; the default comes from DEFAULT_SETTINGS.
# Field order here is the order of the rows in the settings screen.
const SCHEMA: Dictionary = {
	"display": {"mode": ["enum", DISPLAY_MODES], "vsync": ["bool"], "frame_cap": ["enum", FRAME_CAPS],
			"resolution": ["res"], "ui_scale": ["num", 0.75, 2.0]},
	"audio": {"master": ["num", 0.0, 1.0], "music": ["num", 0.0, 1.0], "sfx": ["num", 0.0, 1.0],
			"ui": ["num", 0.0, 1.0], "voice": ["num", 0.0, 1.0], "mono": ["bool"]},
	"access": {"text_scale": ["num", 0.75, 2.0], "subtitles": ["bool"], "subtitle_size": ["enum", SUB_SIZES],
			"subtitle_background": ["num", 0.0, 1.0], "speaker_names": ["bool"], "subtitle_barks": ["bool"],
			"captions_sfx": ["bool"], "colorblind": ["enum", COLORBLIND], "reduce_motion": ["bool"],
			"shake_scale": ["num", 0.0, 1.0], "flash_limit": ["bool"], "hold_to_toggle": ["bool"],
			"difficulty": ["enum", DIFFICULTIES], "game_speed": ["num", 0.5, 1.0]},
	"input": {"deadzone": ["num", 0.0, 0.9], "invert_y": ["bool"], "glyphs": ["enum", GLYPH_SETS]},
	"telemetry": {"consent": ["enum", CONSENT]},
}


static func defaults() -> Dictionary:
	return DEFAULT_SETTINGS.duplicate(true)


static func load_text(text: Variant) -> Dictionary:
	# text: the file's contents, or null when there is no file
	var problems: Array = [] # a plain Array: it is filled inside _fix_bindings too
	var raw: Variant = {}
	if typeof(text) != TYPE_NIL:
		var json: JSON = JSON.new()
		if json.parse(str(text)) != OK:
			return {"settings": defaults(), "problems": PackedStringArray(["unreadable"])}
		raw = json.data
	if typeof(raw) != TYPE_DICTIONARY:
		return {"settings": defaults(), "problems": PackedStringArray(["not an object"])}
	var src_all: Dictionary = raw
	var out: Dictionary = src_all.duplicate(true)
	out["version"] = VERSION
	var lang: Variant = src_all.get("language", "en")
	if typeof(lang) == TYPE_STRING and str(lang).length() >= LANG_MIN and str(lang).length() <= LANG_MAX:
		out["language"] = lang
	else:
		out["language"] = "en"
		if src_all.has("language"):
			problems.append("language")
	for section: String in SCHEMA:
		var fields: Dictionary = SCHEMA[section]
		var src: Variant = src_all.get(section, {})
		if typeof(src) != TYPE_DICTIONARY:
			problems.append(section)
			src = {}
		var sec: Dictionary = (src as Dictionary).duplicate(true)
		var defaults_sec: Dictionary = DEFAULT_SETTINGS[section]
		for name: String in fields:
			var default_value: Variant = defaults_sec[name]
			if (src as Dictionary).has(name):
				var fixed: Array = _fix(fields[name], src[name], default_value)
				if fixed[1]:
					problems.append("%s.%s" % [section, name])
				sec[name] = fixed[0]
			else:
				sec[name] = _copy(default_value)
		if section == "input":
			if (src as Dictionary).has("bindings"):
				sec["bindings"] = _fix_bindings(src["bindings"], problems)
			else:
				sec["bindings"] = Bindings.defaults()
		out[section] = sec
	return {"settings": out, "problems": PackedStringArray(problems)}


static func to_text(settings: Dictionary) -> String:
	return JSON.stringify(settings, "\t") + "\n"


static func effective_shake(settings: Dictionary) -> float:
	var access: Dictionary = settings["access"]
	return 0.0 if access["reduce_motion"] else float(access["shake_scale"])


static func telemetry_allowed(settings: Dictionary) -> bool:
	var consent: Variant = settings["telemetry"]["consent"]
	return typeof(consent) == TYPE_STRING and consent == "yes"


static func is_num(v: Variant) -> bool:
	return typeof(v) == TYPE_INT or typeof(v) == TYPE_FLOAT


static func _fix(rule: Array, value: Variant, default_value: Variant) -> Array:
	# [fixed value, was it a problem]
	match str(rule[0]):
		"bool":
			return [value, false] if typeof(value) == TYPE_BOOL else [default_value, true]
		"num":
			if not is_num(value) or is_nan(float(value)):
				return [default_value, true]
			var clamped: float = minf(maxf(float(value), float(rule[1])), float(rule[2]))
			return [clamped, clamped != float(value)]
		"enum":
			for allowed: Variant in rule[1]:
				if typeof(allowed) == typeof(value) or (is_num(allowed) and is_num(value)):
					if value == allowed:
						return [allowed, false]
			return [default_value, true]
		"res":
			if typeof(value) == TYPE_ARRAY and (value as Array).size() == 2:
				var ok: bool = true
				for n: Variant in value:
					if not is_num(n) or float(n) < 1.0 or float(n) != floorf(float(n)):
						ok = false
				if ok:
					return [[int(value[0]), int(value[1])], false]
			return [_copy(default_value), true]
	push_error("GameSettings: unknown rule %s" % [rule])
	return [default_value, true]


static func _fix_bindings(value: Variant, problems: Array) -> Dictionary:
	var out: Dictionary = Bindings.defaults()
	if typeof(value) != TYPE_DICTIONARY:
		problems.append("input.bindings")
		return out
	for action: Variant in value:
		var lst: Variant = value[action]
		if typeof(lst) != TYPE_ARRAY:
			problems.append("input.bindings.%s" % action)
			continue
		var clean: Array = []
		for b: Variant in lst:
			if typeof(b) == TYPE_STRING:
				clean.append(b)
		if clean.size() != (lst as Array).size():
			problems.append("input.bindings.%s" % action)
		out[str(action)] = clean
	return out


static func _copy(v: Variant) -> Variant:
	if typeof(v) == TYPE_DICTIONARY or typeof(v) == TYPE_ARRAY:
		return v.duplicate(true)
	return v

# {{FOOTER}}
