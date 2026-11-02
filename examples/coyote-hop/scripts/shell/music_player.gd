# ---------------------------------------------------------------------------
# music_player.gd
# Purpose : Plays data/music.json: each track's stems loop together on the bar grid, and a change of track
#           happens on the sample the music director plans (next beat, bar, phrase or loop end), with an optional
#           fade and stinger, all on the "Music" AudioServer bus (so the Shell's music slider applies once).
# Usage   : var music := MusicPlayer.new(); add_child(music)  # loads res://data/music.json (or music.load_music(d))
#           music.start("explore")                     # now (cuts whatever plays)
#           music.request("combat")                    # returns the plan (music samples), {} when nothing changes
#           music.set_stem_gain("explore", "drums", 0.0)   # layers: a stem's level, linear 0..1
#           music.audible_sample()                     # about where the listener is now (gameplay sync)
# Notes   : How it is exact. Godot cannot start an AudioStreamPlayer on a chosen future sample: play() takes effect
#           on whichever mix step the audio thread runs next, and AudioStreamPlayback.start(seconds) seeks up to one
#           sample off, often between samples (measured on 4.7.2). So no player starts or stops for a transition.
#           At load it starts one AudioStreamPlayer per stem slot (DECKS decks x the most stems any track has, plus
#           one for stingers), each fed by an AudioStreamGenerator, all in one AudioServer.lock() so they begin on
#           the same mix step; every frame it pushes the same number of frames into each. A deck's frames come from
#           AudioStreamPlayback.mix_audio() on the stem's own playback (decoded and looped by Godot in C++), with
#           silence before the deck's start sample and after its stop sample, so a switch, a stinger and a fade
#           start land on an exact frame of one shared timeline. Entry offsets are reached by decoding from 0, not
#           by seeking. Loop points come from the director (bar grid), not from the file: Godot 4.7.2 imports a
#           'smpl' loop one frame short, and its WAV loop plays loop_begin + 1 .. loop_end, which _loop_shift()
#           measures once so [start, end) is exact.
#           Precision, MEASURED on Godot 4.7.2 (PCM WAV stems, music.json at 44.1 kHz): with Movie Maker at a
#           44.1 kHz mix, every frame of a 15 s run (three 2-stem tracks, loop wraps, a beat switch with a sync
#           entry, a 200 ms fade, a stinger, a replaced pending switch) equals the plan: 0 frames off, fades within
#           0.05 of a 16-bit step, except that Godot's WAV playback drops a non-looping file's last 6 frames (the
#           stinger's tail). At a 48 kHz mix (Movie Maker, and the real WASAPI driver recorded with
#           AudioEffectRecord) Godot resamples each stem: switches land on the nearest output frame and the new
#           track's phase is within 0.1 of a music sample. Not measured: lossy import (QOA, Godot's WAV import
#           default; set compress/mode to PCM for music), OGG and MP3 stems (they loop at the file's end with
#           loop_offset as the loop start, so cut them to exactly the loop end, and keep the stems of one track
#           and the stingers in one format: decoders differ in start latency), and the CPU cost.
#           Costs: the generators hold buffer_s of audio, so a plan is made from about buffer_s ahead of what is
#           heard (request() cannot change frames already pushed); a frame hitch longer than buffer_s is a dropout
#           (every generator skips alike, so they stay in step). Fades are a straight line in gain from switch_at
#           to from_stop_at, computed per frame in GDScript (the only per-sample script work). set_stem_gain() uses
#           the slot player's volume, so it applies from about now, not on a planned sample. A request while a
#           switch is still pending replaces it. The player never reads the volume sliders: the Shell sets the
#           Music bus (shell.gd _apply_audio).
#
# Pseudocode:
#   load_music(data): streams per file (a copy with loop points from the director) -> slot players + generators,
#                     started together -> prime with silence
#   _process: n = frames every generator can take (up to buffer_s queued) -> per deck and stem slot: silence
#             before start, mix_audio between start and stop (times the fade line), silence after -> push to all
#   request(to): cancel a pending switch -> plan = MusicDirector.plan(current, since, entry, to, now = next frame)
#                -> current deck: fade from switch_at, stop at from_stop_at -> stinger deck at stinger_at
#                -> a free deck plays `to` from to_start_at, decoded up to to_offset
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name MusicPlayer
extends Node

const MUSIC_FILE: String = "res://data/music.json"
const AUDIO_ROOT: String = "res://assets/audio" # stem and stinger paths in music.json are relative to it
const BUS: String = "Music"
const DECKS: int = 3 # a track, the one it fades from, and one spare so a quick re-request never cuts a fade
const DISCARD_CHUNK: int = 8192 # frames decoded at a time while skipping to an entry offset
const NEVER: int = 9223372036854775807 # "no stop planned" (max int64)

@export var buffer_s: float = 0.2 # audio queued ahead of the mix: latency of a request versus dropout safety

var data: Dictionary = {}
var rate: int = 0 # music.json sample_rate: the director's samples
var out_rate: int = 0 # the AudioServer mix rate: the timeline's frames
var _streams: Dictionary = {} # file -> AudioStream (a copy with the director's loop points)
var _slots: int = 0 # stem slots per deck
var _players: Array[AudioStreamPlayer] = [] # deck d, slot s at d * _slots + s; the last one is the stinger slot
var _gens: Array[AudioStreamGeneratorPlayback] = []
var _capacity: int = 0 # frames a generator's ring buffer holds (it rounds buffer_length up)
var _target: int = 0 # frames we keep queued (buffer_s)
var _decks: Array[Dictionary] = [] # track, since, entry (samples); start, stop, fade_start, fade_end (frames); playbacks
var _cur: int = -1 # the deck of the current (or pending) track
var _prev: Dictionary = {} # what request() changed on the deck it switches from, so a pending switch can be undone
var _stinger: Dictionary = {} # playback, start (frame)
var _written: int = 0 # timeline frame of the next frame to push
static var _shift: int = -1 # Godot's WAV loop offset, measured once by _loop_shift()
static var _lead: int = -1 # frames a fresh playback outputs before its first sample, measured once by _preroll()


func _ready() -> void:
	if data.is_empty() and FileAccess.file_exists(MUSIC_FILE):
		var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(MUSIC_FILE))
		if typeof(parsed) == TYPE_DICTIONARY:
			load_music(parsed)
		else:
			Log.warn("music", "%s is not JSON: no music" % MUSIC_FILE)


func load_music(music: Dictionary, root: String = AUDIO_ROOT) -> bool:
	# Loads every stem and stinger and starts the slot players; false (and no music) when something is missing
	if not _players.is_empty():
		Log.warn("music", "load_music() runs once per MusicPlayer")
		return false
	if not GameSettings.is_num(music.get("sample_rate")) or typeof(music.get("tracks")) != TYPE_DICTIONARY:
		Log.warn("music", "music data needs sample_rate and tracks (validate it: wavesmith.py music validate)")
		return false
	data = music
	rate = int(music["sample_rate"])
	out_rate = int(AudioServer.get_mix_rate())
	if out_rate != rate:
		Log.info("music", "music at %d Hz, mixer at %d Hz: Godot resamples, switches round to the nearest frame"
				% [rate, out_rate])
	for track_name: String in data["tracks"]:
		var t: Dictionary = data["tracks"][track_name]
		var lp: PackedInt64Array = MusicDirector.loop_points(t, rate)
		_slots = maxi(_slots, (t["stems"] as Dictionary).size())
		for stem: String in t["stems"]:
			if not _load_stream(root, str(t["stems"][stem]), lp[0], lp[1]):
				return false
	for st: Dictionary in (data.get("stingers", {}) as Dictionary).values():
		if not _load_stream(root, str(st["file"]), -1, -1):
			return false
	_start_slots()
	return true


func _load_stream(root: String, file: String, loop_start: int, loop_end: int) -> bool:
	# A private copy of the stream (other players of the same file keep their settings); loop_start -1 = no loop
	if _streams.has(file):
		return true
	var path: String = root.path_join(file)
	var res: Resource = load(path) if ResourceLoader.exists(path) else null
	if not res is AudioStream:
		Log.warn("music", "%s is missing or not audio: no music" % path)
		return false
	var s: AudioStream = res.duplicate()
	if s is AudioStreamWAV:
		var w: AudioStreamWAV = s
		if w.mix_rate != rate:
			Log.warn("music", "%s is %d Hz, music.json says %d Hz: its bar points will be off" % [path, w.mix_rate, rate])
		if loop_start < 0:
			w.loop_mode = AudioStreamWAV.LOOP_DISABLED
		else:
			w.loop_mode = AudioStreamWAV.LOOP_FORWARD
			w.loop_begin = loop_start - _loop_shift()
			w.loop_end = loop_end - _loop_shift()
	elif "loop" in s: # AudioStreamOggVorbis, AudioStreamMP3: the loop end is the file's end
		s.set("loop", loop_start >= 0)
		if loop_start >= 0 and "loop_offset" in s:
			s.set("loop_offset", float(loop_start) / rate)
	_streams[file] = s
	return true


static func _loop_shift() -> int:
	# Which frames a forward WAV loop plays: [begin, end) gives 0; Godot 4.7.2 plays begin + 1 .. end, giving 1
	if _shift >= 0:
		return _shift
	var got: PackedInt32Array = _probe_values(_probe_wav(4, 12), 24)
	_shift = 0
	for i: int in got.size() - 1:
		# values are frame + 1; [4, 12) wraps from frame 11 to frame 4, Godot 4.7.2 from frame 12 to frame 5
		if got[i] == 13 and got[i + 1] == 6:
			_shift = 1
	return _shift


static func _probe_wav(loop_begin: int, loop_end: int) -> AudioStreamWAV:
	# 16 frames at the mixer's rate (no resampling); frame i holds (i + 1) * 1000, read back as i + 1
	var w: AudioStreamWAV = AudioStreamWAV.new()
	var bytes: PackedByteArray = PackedByteArray()
	bytes.resize(32)
	for i: int in 16:
		bytes.encode_s16(i * 2, (i + 1) * 1000)
	w.format = AudioStreamWAV.FORMAT_16_BITS
	w.mix_rate = int(AudioServer.get_mix_rate())
	w.data = bytes
	if loop_end > 0:
		w.loop_mode = AudioStreamWAV.LOOP_FORWARD
		w.loop_begin = loop_begin
		w.loop_end = loop_end
	return w


static func _probe_values(w: AudioStreamWAV, frames: int) -> PackedInt32Array:
	var pb: AudioStreamPlayback = w.instantiate_playback()
	pb.start(0.0)
	var out: PackedInt32Array = PackedInt32Array()
	for v: Vector2 in pb.mix_audio(1.0, frames):
		out.append(roundi(v.x * 32.768))
	return out


static func _preroll() -> int:
	# A fresh WAV playback's mix_audio() starts with a few frames of resampler history (2 on Godot 4.7.2);
	# every deck decodes them away at launch, so a deck's first frame is its entry sample
	if _lead < 0:
		_lead = maxi(0, _probe_values(_probe_wav(0, 0), 12).find(1))
	return _lead


func _start_slots() -> void:
	if AudioServer.get_bus_index(BUS) < 0:
		Log.warn("music", "no '%s' bus (the Shell makes it at boot): music plays on Master" % BUS)
	for i: int in DECKS * _slots + 1:
		var p: AudioStreamPlayer = AudioStreamPlayer.new()
		p.name = "MusicSlot%d" % i
		var gen: AudioStreamGenerator = AudioStreamGenerator.new()
		gen.mix_rate_mode = AudioStreamGenerator.MIX_RATE_OUTPUT
		gen.buffer_length = buffer_s
		p.stream = gen
		p.bus = BUS
		add_child(p)
		_players.append(p)
	for d: int in DECKS:
		_decks.append(_idle_deck())
	_target = maxi(1, roundi(buffer_s * out_rate))
	# every slot starts on the same mix step and gets the same frames from then on: that is the shared timeline
	AudioServer.lock()
	for p: AudioStreamPlayer in _players:
		p.play()
		_gens.append(p.get_stream_playback())
	_capacity = _gens[0].get_frames_available()
	_target = mini(_target, _capacity)
	_pump()
	AudioServer.unlock()


func _idle_deck() -> Dictionary:
	return {"track": "", "since": 0, "entry": 0, "start": NEVER, "stop": NEVER, "fade_start": NEVER,
			"fade_end": NEVER, "playbacks": [], "stems": PackedStringArray()}


func frame_of(sample: int) -> int:
	# Music sample -> timeline frame (the same number when the mixer runs at the music's rate)
	return sample if out_rate == rate else floori(float(sample) * out_rate / rate + 0.5)


func sample_of(frame: int) -> int:
	return frame if out_rate == rate else floori(float(frame) * rate / out_rate + 0.5)


func now_sample() -> int:
	# The earliest music sample a plan can still change (the next frame to be pushed)
	return sample_of(_written)


func audible_sample() -> int:
	# About the music sample the listener hears now: minus what is queued and the driver's latency
	if _gens.is_empty():
		return 0
	var queued: int = _capacity - _gens[0].get_frames_available()
	return sample_of(_written - queued - roundi(AudioServer.get_output_latency() * out_rate))


var track: String:
	get:
		return "" if _cur < 0 else str(_decks[_cur]["track"])


func start(track_name: String) -> bool:
	# Plays a track from its start at the next frame, cutting whatever plays
	if not _ready_for(track_name):
		return false
	for d: Dictionary in _decks:
		d["stop"] = mini(int(d["stop"]), _written)
	_stinger = {}
	_prev = {}
	_cur = 0
	_launch(0, track_name, now_sample(), 0)
	return true


func stop(fade_ms: float = 0.0) -> void:
	# Fades the music out from the next frame (0: cut)
	var fade: int = frame_of(floori(fade_ms * rate / 1000.0 + 0.5))
	for d: Dictionary in _decks:
		if int(d["stop"]) > _written:
			d["fade_start"] = mini(int(d["fade_start"]), _written)
			d["fade_end"] = mini(int(d["fade_end"]), _written + fade)
			d["stop"] = mini(int(d["stop"]), _written + fade)
	_stinger = {}
	_prev = {}
	_cur = -1


func request(to: String, now: int = -1) -> Dictionary:
	# Plans and schedules a change to `to` (now: a music sample, default and minimum the next frame); returns the
	# plan, or {} when `to` already plays or nothing could be planned (with nothing playing, `to` starts now)
	if not _ready_for(to):
		return {}
	if _cur < 0:
		start(to)
		return {}
	_cancel_pending()
	var cur: Dictionary = _decks[_cur]
	if cur["track"] == to:
		return {}
	var at: int = maxi(now, now_sample())
	var p: Dictionary = MusicDirector.plan(data, cur["track"], cur["since"], cur["entry"], to, at)
	if p.is_empty():
		return {}
	var switch_frame: int = frame_of(p["switch_at"])
	_prev = {"deck": _cur, "stop": cur["stop"], "fade_start": cur["fade_start"], "fade_end": cur["fade_end"],
			"switch": switch_frame}
	cur["fade_start"] = switch_frame
	cur["fade_end"] = frame_of(p["from_stop_at"])
	cur["stop"] = frame_of(p["from_stop_at"])
	if p["stinger_at"] != null:
		var st: Dictionary = data["stingers"][p["stinger"]]
		var pb: AudioStreamPlayback = (_streams[str(st["file"])] as AudioStream).instantiate_playback()
		pb.start(0.0)
		_skip(pb, _preroll())
		_stinger = {"playback": pb, "start": frame_of(p["stinger_at"])}
	var next: int = _free_deck(frame_of(p["to_start_at"]))
	_cur = next
	_launch(next, to, p["to_start_at"], p["to_offset"])
	return p


func set_stem_gain(track_name: String, stem: String, value: float) -> void:
	# A stem's level (linear 0..1) on the current track, from about now (the slot player's volume)
	if _cur < 0 or _decks[_cur]["track"] != track_name:
		return
	var i: int = (_decks[_cur]["stems"] as PackedStringArray).find(stem)
	if i < 0:
		Log.warn("music", "track %s has no stem %s" % [track_name, stem])
		return
	_players[_cur * _slots + i].volume_linear = clampf(value, 0.0, 1.0)


func _ready_for(track_name: String) -> bool:
	if _players.is_empty():
		Log.warn("music", "no music loaded (data/music.json and its files)")
		return false
	if not (data["tracks"] as Dictionary).has(track_name):
		Log.warn("music", "unknown track '%s'" % track_name)
		return false
	return true


func _cancel_pending() -> void:
	# A switch whose start frame is not pushed yet is undone: its deck goes idle, the old deck plays on as before
	if _prev.is_empty() or int(_prev["switch"]) < _written:
		_prev = {}
		return
	_decks[_cur] = _idle_deck()
	_cur = int(_prev["deck"])
	for key: String in ["stop", "fade_start", "fade_end"]:
		_decks[_cur][key] = _prev[key]
	if not _stinger.is_empty() and int(_stinger["start"]) >= _written:
		_stinger = {}
	_prev = {}


func _silent_from(d: int) -> int:
	# The timeline frame from which deck d is silent (-1: idle)
	return -1 if int(_decks[d]["start"]) == NEVER else int(_decks[d]["stop"])


func _free_deck(from_frame: int) -> int:
	# The deck (not the current one) that falls silent first; cut short when it still sounds at from_frame
	var best: int = -1
	for d: int in DECKS:
		if d != _cur and (best < 0 or _silent_from(d) < _silent_from(best)):
			best = d
	if _silent_from(best) > from_frame:
		_decks[best]["stop"] = maxi(_written, from_frame)
	return best


func _launch(d: int, track_name: String, since: int, entry: int) -> void:
	# Fresh playbacks of every stem, decoded up to `entry`; they sound from timeline frame frame_of(since)
	var t: Dictionary = data["tracks"][track_name]
	var playbacks: Array[AudioStreamPlayback] = []
	var stems: PackedStringArray = PackedStringArray()
	var skip: int = frame_of(entry) + _preroll()
	for stem: String in t["stems"]:
		var pb: AudioStreamPlayback = (_streams[str(t["stems"][stem])] as AudioStream).instantiate_playback()
		pb.start(0.0) # from 0: a seek in seconds lands a fraction of a sample off
		_skip(pb, skip)
		playbacks.append(pb)
		stems.append(stem)
	var deck: Dictionary = _idle_deck()
	deck.merge({"track": track_name, "since": since, "entry": entry, "start": frame_of(since),
			"playbacks": playbacks, "stems": stems}, true)
	# the slots may still carry a previous track's stem levels: back to full
	for i: int in _slots:
		_players[d * _slots + i].volume_linear = 1.0
	_decks[d] = deck


static func _skip(pb: AudioStreamPlayback, frames: int) -> void:
	# Decodes and drops frames (exact, unlike a seek)
	var left: int = frames
	while left > 0:
		left -= maxi(1, pb.mix_audio(1.0, mini(left, DISCARD_CHUNK)).size())


func _process(_delta: float) -> void:
	_pump()


func _pump() -> void:
	if _gens.is_empty():
		return
	var n: int = _target - (_capacity - _gens[0].get_frames_available())
	for g: AudioStreamGeneratorPlayback in _gens:
		n = mini(n, g.get_frames_available())
	if n <= 0:
		return
	var t0: int = _written
	for d: int in DECKS:
		var deck: Dictionary = _decks[d]
		for i: int in _slots:
			var pbs: Array = deck["playbacks"]
			_gens[d * _slots + i].push_buffer(_render(deck, pbs[i] if i < pbs.size() else null, t0, n))
		if int(deck["stop"]) < t0 + n and not (deck["playbacks"] as Array).is_empty():
			deck["playbacks"] = [] # done: free the decoders
	_gens[DECKS * _slots].push_buffer(_render_stinger(t0, n))
	_written = t0 + n


static func _silence(n: int) -> PackedVector2Array:
	var out: PackedVector2Array = PackedVector2Array()
	out.resize(n)
	out.fill(Vector2.ZERO)
	return out


func _render(deck: Dictionary, pb: AudioStreamPlayback, t0: int, n: int) -> PackedVector2Array:
	# n frames of one stem slot from timeline frame t0: silence, the stem (times the fade), silence. Whole runs
	# are joined in C++ (append_array); only frames inside a fade are touched one by one.
	var a: int = clampi(int(deck["start"]) - t0, 0, n)
	var b: int = clampi(int(deck["stop"]) - t0, a, n)
	if pb == null or b <= a:
		return _silence(n)
	var out: PackedVector2Array = _silence(a)
	var sound: PackedVector2Array = pb.mix_audio(1.0, b - a)
	if sound.size() < b - a:
		sound.append_array(_silence(b - a - sound.size()))
	var fs: int = int(deck["fade_start"])
	var fe: int = int(deck["fade_end"])
	if fe > fs: # the fade line: gain 1 at fade_start, 0 at fade_end
		for j: int in range(clampi(fs - t0 - a, 0, b - a), clampi(fe - t0 - a, 0, b - a)):
			sound[j] *= 1.0 - float(t0 + a + j - fs) / float(fe - fs)
	out.append_array(sound)
	out.append_array(_silence(n - b))
	return out


func _render_stinger(t0: int, n: int) -> PackedVector2Array:
	var a: int = n if _stinger.is_empty() else clampi(int(_stinger["start"]) - t0, 0, n)
	if a >= n:
		return _silence(n)
	var out: PackedVector2Array = _silence(a)
	var sound: PackedVector2Array = (_stinger["playback"] as AudioStreamPlayback).mix_audio(1.0, n - a)
	out.append_array(sound)
	if sound.size() < n - a: # the stinger ended
		_stinger = {}
		out.append_array(_silence(n - a - sound.size()))
	return out


func _exit_tree() -> void:
	# stop the slots and drop the decoders. Godot 4.7.2 still reports one leaked AudioStreamGeneratorPlayback
	# per slot when the game quits while they play (a lone AudioStreamPlayer with a generator does the same)
	_gens.clear()
	for p: AudioStreamPlayer in _players:
		p.stop()
	for d: Dictionary in _decks:
		d["playbacks"] = []
	_stinger = {}
