# ---------------------------------------------------------------------------
# dialogue_data.gd
# Purpose : Reads the audio pipeline's dialogue.built.json (format v0, "version": 1) for subtitles (engine-free):
#           which line to show, which subtitle chunk (cue) is on screen at time t, and how many characters a
#           typewriter has revealed.
# Usage   : var dlg := DialogueData.parse(text)                 # {} when the file is not a built dialogue file
#           var line: Dictionary = DialogueData.line(dlg, "guide.intro")
#           if DialogueData.should_show(line, Shell.settings.access): ...
#           DialogueData.cue_lines(line, t)   # ["Welcome, traveler.", "The bakery opens at dawn."]
#           DialogueData.revealed(line, t)    # characters of line.text visible at t (typewriter)
# Notes   : Fields this reader does not know are ignored (the format only ever adds fields). A line is "line"
#           (story: always subtitled when subtitles are on) or "bark" (ambient: only with subtitle_barks).
#           Without reveal data the typewriter runs at DEFAULT_CPS. The format comes from Wavesmith's dialogue
#           subcommand (tools/audio/wavesmith); data/dialogue/sample.built.json is a small hand-made example of it.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name DialogueData
extends RefCounted

const FORMAT_VERSION: int = 1
const DEFAULT_CPS: float = 30.0 # characters per second when a line has no reveal data
const HOLD_S: float = 1.0 # a line stays this long after its last cue or character


static func parse(text: Variant) -> Dictionary:
	if typeof(text) != TYPE_STRING:
		return {}
	var json: JSON = JSON.new()
	if json.parse(text) != OK or typeof(json.data) != TYPE_DICTIONARY:
		return {}
	var d: Dictionary = json.data
	if not GameSettings.is_num(d.get("version")) or int(d["version"]) != FORMAT_VERSION:
		return {}
	if typeof(d.get("lines")) != TYPE_DICTIONARY:
		return {}
	return {"lines": d["lines"], "captions": d.get("captions", {}), "style": d.get("style", {}),
			"locale": str(d.get("locale", "en"))}


static func line(dlg: Dictionary, id: String) -> Dictionary:
	var lines: Variant = dlg.get("lines", {})
	if typeof(lines) == TYPE_DICTIONARY and typeof(lines.get(id)) == TYPE_DICTIONARY:
		var out: Dictionary = (lines[id] as Dictionary).duplicate(true)
		out["id"] = id
		return out
	return {}


static func caption(dlg: Dictionary, event_id: String) -> Dictionary:
	var caps: Variant = dlg.get("captions", {})
	if typeof(caps) == TYPE_DICTIONARY and typeof(caps.get(event_id)) == TYPE_DICTIONARY:
		return caps[event_id]
	return {}


static func should_show(entry: Dictionary, access: Dictionary) -> bool:
	if entry.is_empty() or not bool(access.get("subtitles", true)):
		return false
	var kind: Variant = entry.get("kind", "line")
	if typeof(kind) == TYPE_STRING and kind == "bark":
		return bool(access.get("subtitle_barks", false))
	return true


static func duration(entry: Dictionary) -> float:
	if GameSettings.is_num(entry.get("duration_s")):
		return float(entry["duration_s"])
	return str(entry.get("text", "")).length() / DEFAULT_CPS


static func revealed(entry: Dictionary, t: float) -> int:
	var text: String = str(entry.get("text", ""))
	var reveal: Variant = entry.get("reveal")
	if typeof(reveal) != TYPE_ARRAY or (reveal as Array).is_empty():
		var d: float = maxf(duration(entry), 0.001)
		return clampi(floori(text.length() * t / d), 0, text.length())
	var count: int = 0
	for r: Variant in reveal:
		if typeof(r) == TYPE_DICTIONARY and GameSettings.is_num(r.get("t")) and float(r["t"]) <= t:
			count += 1
	return mini(count, text.length())


static func cue_lines(entry: Dictionary, t: float) -> PackedStringArray:
	# The subtitle chunk on screen at t; the whole text when the line has no cues
	var cues: Variant = entry.get("cues")
	if typeof(cues) != TYPE_ARRAY or (cues as Array).is_empty():
		return PackedStringArray([str(entry.get("text", ""))]) if t <= duration(entry) else PackedStringArray()
	for cue: Variant in cues:
		if typeof(cue) != TYPE_DICTIONARY:
			continue
		var start: float = float(cue.get("start", 0.0))
		var end: float = float(cue.get("end", 0.0))
		if t >= start and t < end and typeof(cue.get("lines")) == TYPE_ARRAY:
			return PackedStringArray(cue["lines"])
	return PackedStringArray()


static func finished(entry: Dictionary, t: float) -> bool:
	return t > duration(entry) + HOLD_S

# {{FOOTER}}
