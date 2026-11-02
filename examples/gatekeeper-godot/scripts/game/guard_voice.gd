# ---------------------------------------------------------------------------
# guard_voice.gd
# Purpose : Optional live voice for Bram (proof of concept): each guard line, scripted or improvised by the
#           local model, is spoken with Fish Audio text to speech while you play.
# Usage   : var v := GuardVoice.new(); add_child(v); v.speak("Halt.")
#           Needs YOUR Fish Audio API key in the FISH_API_KEY environment variable; nothing is shipped.
#           Optional FISH_VOICE_ID picks another voice (`python tools/audio/wavesmith/fish_tts.py voices`).
#           User args: --voice speaks in headless runs too (tests), --no-voice turns it off.
# Notes   : Text always shows; the voice is extra and never blocks or breaks the game. Without a key it
#           stays off (VOICE_OFF). A rejected key or empty balance (401/402/403) turns it off for the
#           session; other errors skip one line. Every line that plays is cached in user://voice_cache by
#           sha256(model|voice|text), so repeats cost nothing; a 200 that is not audio is skipped and never
#           cached, so one bad answer cannot break that line for good. The key is read at runtime and never
#           logged, saved or exported. Live generation: ASSET_LOG "live", Fish Audio's terms apply (verify).
#
# Pseudocode
#   _ready: key/voice from the environment -> enabled? -> log VOICE_ON or VOICE_OFF (why)
#   speak: queue -> next: cache hit that plays? play : (drop a broken cached file) POST /v1/tts
#          -> 200 and playable: cache + play | 200 but not audio: skip | auth/balance error: off
#   play: AudioStreamMP3 from the bytes, wait its length (headless audio may never send `finished`) -> next
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-02 with Claude (Fable 5.1, claude-fable-5-1): a reply is checked before it is cached (#4)
# ---------------------------------------------------------------------------
class_name GuardVoice
extends Node

const API_URL: String = "https://api.fish.audio/v1/tts"
const KEY_ENV: String = "FISH_API_KEY"
const VOICE_ENV: String = "FISH_VOICE_ID"
const CACHE_DIR: String = "user://voice_cache"
const STOP_CODES: Array[int] = [401, 402, 403]   # the key or the balance: no point trying the next line

var enabled: bool = false
var _key: String = ""
var _voice: String = ""
var _queue: Array[String] = []
var _busy: bool = false
var _current: String = ""
var _t0: int = 0
var _http: HTTPRequest
var _player: AudioStreamPlayer


# Voice runs only with a key, and in a window unless --voice forces it (smoke tests must not spend credits).
static func should_enable(key: String, headless: bool, forced: bool, refused: bool) -> bool:
	return key != "" and not refused and (forced or not headless)


static func cache_path(model: String, voice: String, text: String) -> String:
	return "%s/%s.mp3" % [CACHE_DIR, ("%s|%s|%s" % [model, voice, text]).sha256_text()]


static func request_body(text: String, voice: String) -> String:
	return JSON.stringify({"text": text, "reference_id": voice, "format": "mp3", "latency": "balanced"})


## The bytes as a stream that plays, or null when they are not audio (a 200 with an error page, a cut-off file).
static func playable(bytes: PackedByteArray) -> AudioStreamMP3:
	if not looks_like_mp3(bytes):
		return null   # text, JSON, nothing: decided here, so the decoder prints no error for an error page
	var stream := AudioStreamMP3.new()
	stream.data = bytes
	return stream if stream.get_length() > 0.0 else null


## MP3 data starts with an ID3 tag or a frame sync (0xFF, then a byte with its top three bits set).
static func looks_like_mp3(bytes: PackedByteArray) -> bool:
	if bytes.size() < 4:
		return false
	if bytes[0] == 0x49 and bytes[1] == 0x44 and bytes[2] == 0x33:   # "ID3"
		return true
	return bytes[0] == 0xFF and (bytes[1] & 0xE0) == 0xE0


## The cached reply at path as a stream, or null. A cached file that does not play is deleted (an older build
## cached replies unchecked), so the line is fetched again instead of failing for good.
static func cached_stream(path: String) -> AudioStreamMP3:
	if not FileAccess.file_exists(path):
		return null
	var stream := playable(FileAccess.get_file_as_bytes(path))
	if stream == null:
		DirAccess.remove_absolute(path)
	return stream


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	_key = OS.get_environment(KEY_ENV).strip_edges()
	_voice = OS.get_environment(VOICE_ENV).strip_edges()
	if _voice == "":
		_voice = Tuning.VOICE_ID
	var headless := DisplayServer.get_name() == "headless"
	enabled = should_enable(_key, headless, args.has("--voice"), args.has("--no-voice"))
	_http = HTTPRequest.new()
	_http.timeout = Tuning.VOICE_TIMEOUT_S
	_http.request_completed.connect(_on_done)
	add_child(_http)
	_player = AudioStreamPlayer.new()
	add_child(_player)
	if enabled:
		Log.info("voice", "VOICE_ON Fish Audio, model %s, voice %s" % [Tuning.VOICE_MODEL, _voice])
	elif _key == "":
		Log.info("voice", "VOICE_OFF (set %s to hear Bram, see README)" % KEY_ENV)
	else:
		Log.info("voice", "VOICE_OFF (%s)" % ("--no-voice" if args.has("--no-voice") else "headless run, add --voice"))


func idle() -> bool:
	return not _busy and _queue.is_empty()


func speak(text: String) -> void:
	if not enabled or text.strip_edges() == "":
		return
	_queue.append(text.strip_edges())
	_next()


func _next() -> void:
	if _busy or _queue.is_empty() or not enabled:
		return
	_busy = true
	_current = _queue.pop_front()
	_t0 = Time.get_ticks_msec()
	var cached := cached_stream(cache_path(Tuning.VOICE_MODEL, _voice, _current))
	if cached != null:
		_play(cached, true)
		return
	var headers := PackedStringArray(["Authorization: Bearer " + _key, "Content-Type: application/json",
		"model: " + Tuning.VOICE_MODEL])
	var err := _http.request(API_URL, headers, HTTPClient.METHOD_POST, request_body(_current, _voice))
	if err != OK:
		_fail("request not sent (%s)" % error_string(err), false)


func _on_done(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS:
		_fail("network problem (HTTPRequest result %d)" % result, false)
		return
	if code != 200:
		_fail("HTTP %d: %s" % [code, body.get_string_from_utf8().substr(0, 160)], STOP_CODES.has(code))
		return
	var stream := playable(body)
	if stream == null:
		_fail("the reply was not playable audio (%d bytes), not cached" % body.size(), false)
		return
	DirAccess.make_dir_recursive_absolute(CACHE_DIR)   # only a reply that plays is kept for next time
	var f := FileAccess.open(cache_path(Tuning.VOICE_MODEL, _voice, _current), FileAccess.WRITE)
	if f:
		f.store_buffer(body)
		f.close()
	_play(stream, false)


func _play(stream: AudioStreamMP3, cached: bool) -> void:
	var seconds := stream.get_length()
	_player.stream = stream
	_player.volume_db = Tuning.VOICE_DB
	_player.play()
	Log.info("voice", "VOICE_OK %.1f s of speech, %s in %d ms" % [seconds,
		"cache" if cached else "%d KB" % int(stream.data.size() / 1024.0), Time.get_ticks_msec() - _t0])
	await get_tree().create_timer(seconds + 0.15).timeout
	_busy = false
	_next()


func _fail(why: String, stop: bool) -> void:
	Log.warn("voice", "VOICE_FAIL " + why + (": voice off for this session" if stop else ": line skipped"))
	if stop:
		enabled = false
		_queue.clear()
	_busy = false
	_next()
