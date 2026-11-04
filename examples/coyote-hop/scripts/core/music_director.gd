# ---------------------------------------------------------------------------
# music_director.gd
# Purpose : The adaptive-music rules of data/music.json (engine-free, so GUT runs them headless against
#           data/golden/music.json): the sample grid, loop points, where playback is, the next beat / bar / phrase /
#           loop end, which transition rule applies, and the plan for a change (when, fade, stinger, entry point).
# Usage   : var music: Dictionary = JSON.parse_string(text)          # data/music.json
#           var p: Dictionary = MusicDirector.plan(music, "explore", since, entry, "combat", now)
#           p.switch_at, p.from_stop_at, p.to_start_at, p.to_offset, p.stinger_at  (whole samples; stinger_at may be null)
#           MusicDirector.loop_points(music.tracks.explore, music.sample_rate)   # [loop start, loop end)
# Notes   : A port of tools/audio/wavesmith/music.py (the reference): every value is a whole number of samples and
#           must match the golden file exactly (tolerance 0). Beat k starts at floor(k * 60 * rate / bpm + 0.5);
#           GDScript's round() is not used (the rule is floor(x + 0.5) in every engine). Godot parses every JSON
#           number as a float, so counts are turned into ints before they are used as samples, and each division is
#           written as a float division (int / int truncates in GDScript, Python's / never does). GDScript has no
#           exceptions: an unknown track, quantize or stinger is reported with push_error and plan() returns {}.
#           scripts/shell/music_player.gd plays the plans.
#
# Pseudocode:
#   beat_sample(k) = floor(k * 60 * rate / bpm + 0.5); bar b starts at beat_sample(b * beats_per_bar)
#   position(track, since, entry, now): p = now - since + entry; past the loop end -> wrap into the loop
#   plan(from, to, now): rule (exact pair, from "*", to "*", default) -> next boundary of its quantize at or after p
#                        -> switch_at = now + (boundary - p); stinger? target enters after the stinger's bars
#                        -> target entry offset 0, or the same place in the bar when "sync" and the grids match
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name MusicDirector
extends RefCounted

const QUANTIZE: PackedStringArray = ["immediate", "beat", "bar", "phrase", "loop_end"]
const DEFAULT_RULE: Dictionary = {"quantize": "bar", "fade_ms": 0, "sync": false}
const DEFAULT_BEATS_PER_BAR: int = 4
const DEFAULT_PHRASE_BARS: int = 4


static func beats_per_bar(track: Dictionary) -> int:
	return int(track.get("beats_per_bar", DEFAULT_BEATS_PER_BAR))


static func beat_sample(k: float, bpm: float, rate: int) -> int:
	# First sample of beat k (k may be any whole number; a stinger's bars may make it a fraction)
	return floori(k * 60.0 * rate / bpm + 0.5)


static func bar_sample(b: int, track: Dictionary, rate: int) -> int:
	return beat_sample(b * beats_per_bar(track), float(track["bpm"]), rate)


static func bar_index_at(sample: int, track: Dictionary, rate: int) -> int:
	# The bar that contains `sample`: a float estimate, then corrected on the rounded grid so it is exact
	var bpm: float = float(track["bpm"])
	var b: int = floori(float(sample) * bpm / float(60 * rate * beats_per_bar(track)))
	while bar_sample(b + 1, track, rate) <= sample:
		b += 1
	while b > 0 and bar_sample(b, track, rate) > sample:
		b -= 1
	return b


static func loop_points(track: Dictionary, rate: int) -> PackedInt64Array:
	# [loop start, loop end) in samples: the loop plays forever after the intro (the bars before loop_start_bar)
	return PackedInt64Array([bar_sample(int(track.get("loop_start_bar", 0)), track, rate),
			bar_sample(int(track["bars"]), track, rate)])


static func position(track: Dictionary, rate: int, since: int, now: int, entry: int = 0) -> int:
	# Where in the track (samples from its start) playback is at `now`, when it started at `since` from `entry`
	var p: int = now - since + entry
	var lp: PackedInt64Array = loop_points(track, rate)
	if p >= lp[1]:
		p = lp[0] + posmod(p - lp[0], lp[1] - lp[0])
	return p


static func next_boundary(track: Dictionary, rate: int, p: int, quantize: String,
		phrase_bars: int = DEFAULT_PHRASE_BARS) -> int:
	# The first boundary of the given kind at or after track position p (a loop position: 0 <= p < loop end)
	if quantize == "immediate":
		return p
	var lp: PackedInt64Array = loop_points(track, rate)
	if quantize == "loop_end":
		return lp[1]
	var bpb: int = beats_per_bar(track)
	var step: int = 0
	if quantize == "beat":
		step = 1
	elif quantize == "bar":
		step = bpb
	elif quantize == "phrase":
		step = bpb * phrase_bars
	else: # a typo must not mean "phrase"; plan() checks the name before it gets here
		push_error("MusicDirector: unknown quantize '%s'" % quantize)
		return p
	var bpm: float = float(track["bpm"])
	# the beat at or after p, then up to the next multiple of step (counted from the track's first beat)
	var k: int = floori(float(p) * bpm / float(60 * rate))
	while beat_sample(k, bpm, rate) < p:
		k += 1
	while posmod(k, step) != 0:
		k += 1
	return mini(beat_sample(k, bpm, rate), lp[1])


static func rule_for(data: Dictionary, from: String, to: String) -> Dictionary:
	# Exact pair, then from "*", then to "*"; each merged over the file's default_transition and DEFAULT_RULE
	var base: Dictionary = DEFAULT_RULE.duplicate()
	var file_default: Variant = data.get("default_transition", {})
	if typeof(file_default) == TYPE_DICTIONARY:
		base.merge(file_default, true)
	var rules: Variant = data.get("transitions", [])
	if typeof(rules) != TYPE_ARRAY:
		return base
	for want: Array in [[from, to], ["*", to], [from, "*"]]:
		for r: Variant in rules:
			if typeof(r) == TYPE_DICTIONARY and r.get("from") == want[0] and r.get("to") == want[1]:
				var out: Dictionary = base.duplicate()
				out.merge(r, true)
				return out
	return base


static func plan(data: Dictionary, from: String, since: int, entry: int, to: String, now: int) -> Dictionary:
	# When and how to change from track `from` (playing since sample `since` from offset `entry`) to `to`, asked at
	# sample `now`: {switch_at, from_stop_at, fade, to_offset, to_start_at, stinger, stinger_at}
	var tracks: Dictionary = data.get("tracks", {})
	if not tracks.has(from) or not tracks.has(to):
		push_error("MusicDirector: unknown track '%s'" % (to if tracks.has(from) else from))
		return {}
	var rate: int = int(data["sample_rate"])
	var a: Dictionary = tracks[from]
	var b: Dictionary = tracks[to]
	var rule: Dictionary = rule_for(data, from, to)
	if not QUANTIZE.has(str(rule["quantize"])):
		push_error("MusicDirector: unknown quantize '%s'" % rule["quantize"])
		return {}
	var p: int = position(a, rate, since, now, entry)
	var boundary: int = next_boundary(a, rate, p, str(rule["quantize"]), int(rule.get("phrase_bars", DEFAULT_PHRASE_BARS)))
	var switch_at: int = now + (boundary - p)
	var fade: int = floori(float(rule.get("fade_ms", 0)) * rate / 1000.0 + 0.5)
	var stinger: Variant = rule.get("stinger")
	var has_stinger: bool = typeof(stinger) == TYPE_STRING and stinger != "" # Python: a truthy name
	var out: Dictionary = {"switch_at": switch_at, "from_stop_at": switch_at + fade, "fade": fade, "to_offset": 0,
			"to_start_at": switch_at, "stinger": stinger, "stinger_at": null}
	if has_stinger:
		var stingers: Dictionary = data.get("stingers", {})
		if not stingers.has(stinger):
			push_error("MusicDirector: unknown stinger '%s'" % stinger)
			return {}
		out["stinger_at"] = switch_at
		# the target enters after the stinger's bars, counted on the target's own grid
		out["to_start_at"] = switch_at + beat_sample(float(stingers[stinger]["bars"]) * beats_per_bar(b),
				float(b["bpm"]), rate)
	elif bool(rule.get("sync", false)) and float(a["bpm"]) == float(b["bpm"]) and beats_per_bar(a) == beats_per_bar(b):
		# keep the beat: enter the target at the same place in its bar (bar boundaries are where they line up)
		out["to_offset"] = boundary - bar_sample(bar_index_at(boundary, a, rate), a, rate)
	return out
