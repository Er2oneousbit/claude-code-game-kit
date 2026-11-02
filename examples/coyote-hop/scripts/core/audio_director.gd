# ---------------------------------------------------------------------------
# audio_director.gd
# Purpose : Audio director (engine-free): decides how each game sound plays. Which file of the event (no
#           back-to-back repeats), its pitch and volume within the event's ranges, voice limits (steal the oldest
#           or refuse), cooldowns, and how far a trigger bus (dialogue) ducks other buses (music, ambience).
#           Data comes from data/audio_events.json ({ seed?, events, ducking? }).
# Usage   : var director := AudioDirector.new(events_json)          # the parsed audio_events.json Dictionary
#           var d: Dictionary = director.play("step_stone", now_ms)  # d.result: "played" | "cooldown" | "capped"
#           if d["result"] == "played": start files[d.variant] at d.pitch_ratio, d.gain_db; stop voice d.stolen
#           each frame: for bus in (gains := director.duck(now_ms)): set that bus's duck gain to gains[bus] dB
# Notes   : Decisions only: no AudioStreamPlayer here, so tests run it headless. The spec is
#           tools/audio/wavesmith/audio_events.py; every step of data/golden/audio.json must come out the same
#           (tests/test_golden_audio.gd). The random source is Park-Miller kept as an int (products stay below
#           2^53), randomness is drawn in a fixed order (variant, pitch, volume) and never by a rejected play.
#           Times are milliseconds as 64-bit floats; calls must come in time order. GDScript has no exceptions:
#           an out-of-order call or an unknown event is reported with push_error and the call does nothing
#           (play returns {"result": "error"}, duck returns {}). lengths_ms per file: from the loaded streams.
#
# Pseudocode:
#   play(e, t) -> drop finished voices -> cooldown? "cooldown" -> at max_voices: steal oldest or "capped"
#              -> variant by pick rule -> pitch -> volume -> new voice (ends at t + length / pitch ratio)
#   duck(t)    -> per ducking rule: walk the trigger bus's voice edges since the last call, ramp in dB
#                 (towards depth_db over attack_ms while a trigger voice plays, back to 0 over release_ms),
#                 then forget trigger voices that ended at or before t
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name AudioDirector
extends RefCounted

const DEFAULT_MAX_VOICES: int = 8
const DEFAULT_PICK: String = "random_no_repeat"
const DEFAULT_STEAL: String = "oldest"
const PM_M: int = 2147483647 # Park-Miller modulus (2^31 - 1)
const PM_A: int = 16807 # Park-Miller multiplier
const HASH_MUL: int = 31 # event id hash: h = h * 31 + char code
const SEED_MUL: int = 7919 # mixes the global seed into each event's seed


# Park-Miller minimal standard generator: exact in 64-bit ints, so every language agrees
class ParkMiller:
	extends RefCounted

	var s: int

	func _init(p_seed: int) -> void:
		s = posmod(p_seed, PM_M)
		if s == 0:
			s = 1

	func next() -> float:
		# A float in [0, 1)
		s = (s * PM_A) % PM_M
		return float(s - 1) / float(PM_M - 1)


var events: Dictionary # event name -> event Dictionary (bus, files, lengths_ms, pick, ...)
var ducking: Array # ducking rules: trigger, targets, depth_db, attack_ms, release_ms
var rng_seed: int
var _rng: Dictionary = {} # event name -> ParkMiller (one random stream per event)
var _voices: Array[Dictionary] = [] # playing voices: id, event, bus, start, end (end shortened when stolen)
var _history: Array[Dictionary] = [] # trigger-bus voices (same Dictionaries) the ducking envelopes may still need
var _triggers: Dictionary = {} # bus name -> true for every ducking rule's trigger bus
var _next_id: int = 1
var _last_play: Dictionary = {} # event name -> time of its last accepted play
var _last_variant: Dictionary = {} # event name -> file index it played last
var _bags: Dictionary = {} # event name -> Array of file indices left in the shuffle bag
var _duck_state: Array[Dictionary] = [] # per ducking rule: gain (dB) and t (ms) of the last duck() call
var _now: float = 0.0


func _init(params: Dictionary) -> void:
	events = params.get("events", {})
	ducking = params.get("ducking", [])
	rng_seed = int(params.get("seed", 1)) # whole number >= 0 (validated); JSON gives a float, exact below 2^53
	var names: Array = events.keys()
	names.sort()
	for event_name: String in names:
		_rng[event_name] = ParkMiller.new(event_seed(event_name, rng_seed))
	for rule: Dictionary in ducking:
		_duck_state.append({"gain": 0.0, "t": 0.0})
		_triggers[rule["trigger"]] = true


static func event_seed(event_id: String, global_seed: int) -> int:
	# Polynomial hash of the ASCII id mod 2^31 - 1, mixed with the global seed; never 0
	var h: int = 0
	for i: int in event_id.length():
		h = (h * HASH_MUL + event_id.unicode_at(i)) % PM_M # ids are ASCII (validated), so code point = byte
	var out: int = (h + posmod(global_seed, PM_M) * SEED_MUL) % PM_M
	return out if out != 0 else 1


func _clock(t: float) -> bool:
	if t < _now:
		push_error("AudioDirector: calls must come in time order (%s ms after %s ms)" % [t, _now])
		return false
	_now = t
	return true


func _pick(event_name: String, ev: Dictionary, rng: ParkMiller) -> int:
	var n: int = ev["files"].size()
	var last: int = int(_last_variant.get(event_name, -1))
	var rule: String = ev.get("pick", DEFAULT_PICK)
	if n == 1:
		return 0
	if rule == "sequence":
		return (last + 1) % n
	if rule == "random":
		return mini(int(rng.next() * n), n - 1)
	if rule == "random_no_repeat":
		if last < 0:
			return mini(int(rng.next() * n), n - 1)
		var k: int = mini(int(rng.next() * (n - 1)), n - 2) # one of the other n - 1 files
		return k + 1 if k >= last else k
	# shuffle: refill with Fisher-Yates when empty, then take from the front
	var bag: Array = _bags.get(event_name, [])
	if bag.is_empty():
		bag = range(n)
		for i: int in range(n - 1, 0, -1):
			var j: int = mini(int(rng.next() * (i + 1)), i)
			var tmp: int = bag[i]
			bag[i] = bag[j]
			bag[j] = tmp
		if bag[0] == last: # never the same file twice across a refill
			var first: int = bag[0]
			bag[0] = bag[1]
			bag[1] = first
	var idx: int = bag.pop_front()
	_bags[event_name] = bag
	return idx


func play(event_name: String, t_ms: float) -> Dictionary:
	if not events.has(event_name):
		push_error("AudioDirector: unknown audio event '%s'" % event_name)
		return {"result": "error"}
	if not _clock(t_ms):
		return {"result": "error"}
	var ev: Dictionary = events[event_name]
	_voices = _voices.filter(func(v: Dictionary) -> bool: return v["end"] > t_ms)
	var cooldown: float = ev.get("cooldown_ms", 0.0)
	if cooldown != 0.0 and _last_play.has(event_name) and t_ms - float(_last_play[event_name]) < cooldown:
		return {"result": "cooldown"}
	var mine: Array[Dictionary] = _voices.filter(func(v: Dictionary) -> bool: return v["event"] == event_name)
	var stolen: Variant = null
	if mine.size() >= int(ev.get("max_voices", DEFAULT_MAX_VOICES)):
		if ev.get("steal", DEFAULT_STEAL) == "none":
			return {"result": "capped"}
		var victim: Dictionary = mine[0] # oldest: earliest start, then lowest id
		for v: Dictionary in mine:
			if v["start"] < victim["start"] or (v["start"] == victim["start"] and v["id"] < victim["id"]):
				victim = v
		victim["end"] = t_ms # it stops now (the ducking envelope sees that through _history)
		var victim_id: int = victim["id"]
		_voices = _voices.filter(func(v: Dictionary) -> bool: return v["id"] != victim_id)
		stolen = victim_id
	var rng: ParkMiller = _rng[event_name]
	var idx: int = _pick(event_name, ev, rng)
	var pitch: Array = ev.get("pitch_semitones", [0.0, 0.0])
	var lo: float = pitch[0]
	var hi: float = pitch[1]
	var semis: float = lo if lo == hi else lo + (hi - lo) * rng.next()
	var vol: Array = ev.get("volume_db", [0.0, 0.0])
	var vlo: float = vol[0]
	var vhi: float = vol[1]
	var gain: float = vlo if vlo == vhi else vlo + (vhi - vlo) * rng.next()
	var ratio: float = pow(2.0, semis / 12.0)
	var length: float = ev["lengths_ms"][idx]
	var voice: Dictionary = {"id": _next_id, "event": event_name, "bus": ev["bus"], "start": t_ms,
			"end": t_ms + length / ratio}
	_next_id += 1
	_voices.append(voice)
	if _triggers.has(voice["bus"]): # only a trigger bus voice can move a ducking envelope
		_history.append(voice)
	_last_play[event_name] = t_ms
	_last_variant[event_name] = idx
	return {"result": "played", "variant": idx, "pitch_semitones": semis, "pitch_ratio": ratio, "gain_db": gain,
			"voice": voice["id"], "stolen": stolen, "ends_ms": voice["end"]}


func duck(t_ms: float) -> Dictionary:
	# {target bus: duck gain in dB} at t_ms, every rule advanced to t_ms
	if not _clock(t_ms):
		return {}
	var out: Dictionary = {}
	for r: int in ducking.size():
		var rule: Dictionary = ducking[r]
		var st: Dictionary = _duck_state[r]
		var since: float = st["t"]
		var trigger: Array[Dictionary] = _history.filter(func(v: Dictionary) -> bool: return v["bus"] == rule["trigger"])
		var edge_set: Dictionary = {} # unique voice starts and ends strictly between the last call and now
		for v: Dictionary in trigger:
			for e: float in [float(v["start"]), float(v["end"])]:
				if since < e and e < t_ms:
					edge_set[e] = true
		var edges: Array = edge_set.keys()
		edges.sort()
		edges.append(t_ms)
		var gain: float = st["gain"]
		var at: float = since
		for edge: float in edges:
			var active: bool = false
			for v: Dictionary in trigger:
				if v["start"] <= at and at < v["end"]:
					active = true
					break
			gain = _ramp(gain, active, rule, edge - at)
			at = edge
		st["gain"] = gain
		st["t"] = t_ms
		for bus: String in rule["targets"]:
			out[bus] = minf(float(out.get(bus, 0.0)), gain)
	# Every rule now stands at t_ms: a voice that ended at or before t_ms adds no later edge and is never active
	# again, so it can go (keeps duck() cheap in a long session; results are unchanged)
	_history = _history.filter(func(v: Dictionary) -> bool: return v["end"] > t_ms)
	return out


static func _ramp(gain: float, active: bool, rule: Dictionary, dt: float) -> float:
	# One straight-line step in dB over dt ms: down towards depth_db while active, back up to 0 when not
	var depth: float = rule["depth_db"]
	if active:
		var attack: float = rule.get("attack_ms", 0.0)
		if attack <= 0.0:
			return depth
		return maxf(depth, gain + depth / attack * dt)
	var release: float = rule.get("release_ms", 0.0)
	if release <= 0.0:
		return 0.0
	return minf(0.0, gain - depth / release * dt)
