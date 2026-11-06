# ---------------------------------------------------------------------------
# shell.gd  (autoload name: Shell)
# Purpose : The game's runtime services, shared by every screen: the data folder, settings (load, apply, save),
#           strings in the player's language, input bindings and prompt glyphs, the log file, crash files,
#           opt-in telemetry and the debug bug-report key.
# Usage   : Shell.t("menu.play")                       # a UI string in the current language
#           Shell.tn("demo.hits", 3)                   # with plural forms
#           Shell.settings.access.reduce_motion        # read a setting
#           Shell.set_value("audio", "master", 0.5)    # change one (applied at once; save_settings() writes it)
#           Shell.effective_shake(); Shell.game_speed(); Shell.telemetry("level_start", "1-2")
# Notes   : User args (after "--"): --data-dir <dir> (default user://), --locale <code> (this run only; "pseudo"
#           is the test locale), --smoke (a dev.py smoke run: a crash exits 1, no pause on focus loss),
#           --drive <scenario> (scripts/shell/smoke_drive.gd), --capture (tools/capture.gd is taking a picture).
#           Files in the data folder: settings.json (+ .bak), save_<slot>.json (+ .bak), logs/game.log (+ 5
#           rotated), crashes/crash_<time>.txt, telemetry.csv (only after the player said yes), bug_<time>/ (F8 in
#           debug builds). When the engine runs a tool script (GUT tests, dev.py check) the Shell stays passive:
#           defaults only, no files, no hooks. Autoload name "Shell" must NOT also be a class_name.
#           A missing or broken settings.json is recovered from settings.json.tmp or .bak (see
#           read_settings_file), so resetting settings by hand means deleting all three files.
#
# Pseudocode:
#   boot: args -> data folder -> log file -> crash hook -> settings.json, else its .tmp / .bak (fixed by
#         GameSettings) -> string tables -> apply audio, accessibility, language; display and input only when
#         settings came from disk (else the front end applies them) -> telemetry "session_start" (with consent)
#   save: settings.json parses -> it becomes .bak; atomic write (AtomicFile)
#   each frame: a script error caught by CrashHook -> crash file, CRASH_WRITTEN <path>; smoke run -> exit 1
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends Node

signal settings_changed(section: String, key: String)
signal locale_changed
signal device_changed(device: String)
signal focus_lost

const SETTINGS_FILE: String = "settings.json"
const TELEMETRY_FILE: String = "telemetry.csv"
const LOG_FILE: String = "logs/game.log"
const CRASH_DIR: String = "crashes"
const I18N_DIR: String = "res://data/i18n"
const DIALOGUE_FILE: String = "res://data/dialogue/sample.built.json"
const CREDITS_FILE: String = "res://CREDITS.md"
const GLYPH_DIR: String = "res://assets/ui/glyphs"
const AUDIO_BUSES: PackedStringArray = ["Music", "SFX", "UI", "Voice"] # created at boot when missing
const BUS_SETTING: Dictionary = {"Master": "master", "Music": "music", "SFX": "sfx", "UI": "ui", "Voice": "voice"}
const CRASH_LOG_LINES: int = 50
const BUG_LOG_LINES: int = 200
const BUG_REPORT_KEY: Key = KEY_F8
const GAME_SCRIPTS: PackedStringArray = ["res://tools/capture.gd"] # -s scripts that run the real game
const PAD_PLAYSTATION: PackedStringArray = ["playstation", "dualshock", "dualsense", "sony", "ps3", "ps4", "ps5"]
const PAD_XBOX: PackedStringArray = ["xbox", "xinput"]
const AXIS_DEVICE_SWITCH: float = 0.5 # a stick must move this far to count as "the player picked up the pad"
const CAPTURE_MOUSE_REGION: PackedVector2Array = [Vector2(0, 0), Vector2(1, 0), Vector2(1, 1), Vector2(0, 1)]
const WINDOW_MODES: Dictionary = {"windowed": DisplayServer.WINDOW_MODE_WINDOWED,
		"fullscreen": DisplayServer.WINDOW_MODE_EXCLUSIVE_FULLSCREEN,
		"borderless": DisplayServer.WINDOW_MODE_FULLSCREEN}

var data_dir: String = ""
var settings: Dictionary = GameSettings.defaults()
var settings_problems: PackedStringArray = []
var settings_source: String = "none" # load_settings(): "file", "backup" or "tmp" (recovered), "none" (defaults)
var tables: Dictionary = {}
var locale: String = "en"
var locale_override: String = ""
var last_device: String = "keyboard"
var smoke: bool = false
var capture: bool = false
var drive: String = ""
# cognitive access (#167): the goal the game sets for "What now?", and every subtitle line shown (newest last)
const MAX_HISTORY: int = 50
var objective: String = ""
var history: Array[Dictionary] = []
var capture_ready: bool = false # set by the smoke drive when the screen to photograph is up
var run_seed: int = -1 # set it when a run uses a seed: crash files then name it
var current_screen: String = ""
var session_id: String = ""
var version: String = ""
var active: bool = true # false while the engine runs a tool script (GUT, check)
var _crash_file: String = ""
var _missing_keys: Dictionary = {}
var _color_filter: ColorFilter = null
var colours: Dictionary = {} # data/access/colours.json (AccessColours)


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	version = str(ProjectSettings.get_setting("application/config/version", "0.0.0"))
	tables = I18n.load_tables(I18N_DIR)
	active = not _is_tool_run()
	if not active:
		set_process(false)
		set_process_input(false)
		return
	_parse_args()
	if capture and DisplayServer.get_name() != "headless":
		# The real mouse must not hover anything in a screenshot run: the window lets it pass through
		DisplayServer.window_set_mouse_passthrough(CAPTURE_MOUSE_REGION)
	session_id = Telemetry.new_session()
	DirAccess.make_dir_recursive_absolute(data_dir)
	Log.open_file(path(LOG_FILE), _log_header())
	if not CrashHook.install():
		Log.warn("shell", "no crash hook on this Godot version (needs 4.5+): crash files are not written")
	load_settings()
	colours = AccessColours.load_data()
	_color_filter = ColorFilter.new()
	add_child(_color_filter)
	if settings_source != "none":
		# The player saved settings (settings.json, or the .bak / .tmp a cut-off save left behind)
		apply_all()
	else:
		# Nothing saved yet: leave the project's own window size and input map alone (a game with its own main
		# scene keeps its look and controls). The kit's front end calls apply_all() when it starts.
		_apply_audio()
		_apply_access()
		_update_locale(false)
	Log.info("shell", "data folder: %s" % data_dir)
	telemetry("session_start", version)


func _process(_delta: float) -> void:
	var errors: Array[Dictionary] = CrashHook.take()
	if errors.is_empty() or _crash_file != "":
		return # one crash file per launch: later errors are in the log
	_crash_file = write_crash(errors[0])
	Log.raw("CRASH_WRITTEN " + _crash_file)
	Log.error("shell", "script error, crash file written: %s" % _crash_file)
	if smoke:
		get_tree().quit(1)


func _input(event: InputEvent) -> void:
	var device: String = _device_of(event)
	if device != "" and device != last_device:
		last_device = device
		device_changed.emit(device)
	if OS.is_debug_build() and event is InputEventKey:
		var key: InputEventKey = event
		if key.pressed and not key.echo and key.keycode == BUG_REPORT_KEY:
			bug_report()


func _notification(what: int) -> void:
	if what == NOTIFICATION_APPLICATION_FOCUS_OUT and active and not smoke:
		focus_lost.emit()


# ---- data folder and files ----------------------------------------------------

func path(relative: String) -> String:
	return data_dir.path_join(relative)


func load_settings() -> void:
	var loaded: Dictionary = read_settings_file(path(SETTINGS_FILE))
	settings = loaded["settings"]
	settings_problems = loaded["problems"]
	settings_source = loaded["source"]
	if settings_source != "none" and not settings_problems.is_empty():
		Log.warn("settings", "fixed %d value(s) in %s: %s" % [settings_problems.size(),
				str(loaded["path"]).get_file(), ", ".join(settings_problems)])


func read_settings_file(file: String) -> Dictionary:
	# {"settings", "problems", "source", "path"}. source "file": settings.json (values fixed as needed);
	# "tmp" / "backup": settings.json was missing or did not parse and a copy that parses was used; "none":
	# nothing usable on disk, defaults. Order: settings.json missing -> .tmp, .bak (a save cut off between
	# AtomicFile's delete and rename: .tmp is the new text, .bak the previous); settings.json broken -> .bak, .tmp
	# (.bak is the last good version, a .tmp is a save that never finished).
	var text: Variant = AtomicFile.read_text(file)
	var loaded: Dictionary = GameSettings.load_text(text)
	var missing: bool = typeof(text) == TYPE_NIL
	if not missing and _parses(loaded):
		return _from(loaded, "file", file)
	var order: PackedStringArray = [AtomicFile.BAK_SUFFIX, AtomicFile.TMP_SUFFIX]
	if missing:
		order.reverse()
	for suffix: String in order:
		var other: Variant = AtomicFile.read_text(file + suffix)
		if typeof(other) == TYPE_NIL:
			continue
		var recovered: Dictionary = GameSettings.load_text(other)
		if _parses(recovered):
			Log.warn("settings", "%s %s, using %s" % [file.get_file(), "missing" if missing else "unreadable",
					(file + suffix).get_file()])
			return _from(recovered, "backup" if suffix == AtomicFile.BAK_SUFFIX else "tmp", file + suffix)
	return _from(loaded, "none" if missing else "file", file)


func write_settings_file(file: String, values: Dictionary) -> Error:
	# Only a settings.json that parses becomes the .bak: a corrupt one must not replace the last good backup
	var current: Variant = AtomicFile.read_text(file)
	var keep_backup: bool = typeof(current) != TYPE_NIL and _parses(GameSettings.load_text(current))
	return AtomicFile.write_text(file, GameSettings.to_text(values), keep_backup)


func save_settings() -> String:
	var file: String = path(SETTINGS_FILE)
	var err: Error = write_settings_file(file, settings)
	if err != OK:
		Log.error("settings", "could not save %s (%s)" % [file, error_string(err)])
		return ""
	Log.info("settings", "saved %s" % file)
	telemetry("settings_saved")
	return file


func write_crash(entry: Dictionary) -> String:
	DirAccess.make_dir_recursive_absolute(path(CRASH_DIR))
	var file: String = path(CRASH_DIR).path_join("crash_%s.txt" % _stamp())
	var lines: PackedStringArray = [
		"crash report",
		"game: %s %s" % [ProjectSettings.get_setting("application/config/name", ""), version],
		"engine: Godot %s (%s build), %s" % [Engine.get_version_info().string,
				"debug" if OS.is_debug_build() else "release", OS.get_name()],
		"time: %s" % Time.get_datetime_string_from_system(),
		"seed: %s" % (str(run_seed) if run_seed >= 0 else "none"),
		"screen: %s" % current_screen,
		"error: %s" % entry.get("message", "?"),
		"at: %s:%s in %s()" % [entry.get("file", "?"), entry.get("line", "?"), entry.get("function", "?")],
		"",
		"backtrace:",
		str(entry.get("backtrace", "")).strip_edges(false, true),
		"",
		"log tail (last %d lines):" % CRASH_LOG_LINES,
	]
	lines.append_array(Log.tail(CRASH_LOG_LINES))
	AtomicFile.write_text(file, "\n".join(lines) + "\n", false)
	telemetry("crash", str(entry.get("message", "")))
	return file


func bug_report() -> String:
	# F8 in debug builds: log tail, settings and a screenshot in bug_<time>/ for an issue report
	var dir: String = path("bug_%s" % _stamp())
	DirAccess.make_dir_recursive_absolute(dir)
	AtomicFile.write_text(dir.path_join("log_tail.txt"), "\n".join(Log.tail(BUG_LOG_LINES)) + "\n", false)
	AtomicFile.write_text(dir.path_join("settings.json"), GameSettings.to_text(settings), false)
	AtomicFile.write_text(dir.path_join("info.txt"), "game %s %s\nengine Godot %s\nscreen %s\nseed %s\ntime %s\n" % [
			ProjectSettings.get_setting("application/config/name", ""), version, Engine.get_version_info().string,
			current_screen, run_seed, Time.get_datetime_string_from_system()], false)
	if DisplayServer.get_name() != "headless":
		var image: Image = get_viewport().get_texture().get_image()
		if image != null:
			image.save_png(dir.path_join("screenshot.png"))
	Log.raw("BUG_REPORT " + dir)
	return dir


func telemetry(event: String, detail: String = "") -> void:
	# Appends one row to telemetry.csv, only when the player agreed; nothing leaves the computer
	if active:
		Telemetry.append(path(TELEMETRY_FILE), GameSettings.telemetry_allowed(settings), session_id, event, detail)


# ---- settings -----------------------------------------------------------------

func set_value(section: String, key: String, value: Variant) -> void:
	(settings[section] as Dictionary)[key] = value
	match section:
		"display":
			_apply_display()
		"audio":
			_apply_audio()
		"input":
			_apply_input()
		"access":
			_apply_access()
	settings_changed.emit(section, key)


func set_language(code: String) -> void:
	settings["language"] = code
	locale_override = ""
	_update_locale(true)
	settings_changed.emit("language", "language")


func set_bindings(bindings: Dictionary) -> void:
	(settings["input"] as Dictionary)["bindings"] = bindings
	_apply_input()
	settings_changed.emit("input", "bindings")


func apply_all() -> void:
	_apply_display()
	_apply_audio()
	_apply_input()
	_apply_access()
	_update_locale(false)


func access(key: String) -> Variant:
	return (settings["access"] as Dictionary).get(key)


## The goal "What now?" shows on the pause menu (#167); "" clears it. Pass translated text (Shell.t()).
func set_objective(text: String) -> void:
	objective = text


## Records a line the player saw, for "Dialogue history" and "What now?" (the subtitle bar calls it).
func record_line(speaker: String, text: String) -> void:
	history.append({"name": speaker, "text": text})
	if history.size() > MAX_HISTORY:
		history.pop_front()


## The game's important colours for the current colour-blind setting ({name: Color}, data/access/colours.json).
func palette() -> Dictionary:
	return AccessColours.palette(colours, str(access("colorblind")))


func effective_shake() -> float:
	return GameSettings.effective_shake(settings)


func telemetry_allowed() -> bool:
	return GameSettings.telemetry_allowed(settings)


func game_speed() -> float:
	return float(access("game_speed"))


# ---- strings ------------------------------------------------------------------

func t(key: String, args: Dictionary = {}, fallback: String = "") -> String:
	# A UI string in the current language. fallback is used (and translated by nobody) when no table has key.
	if locale == I18n.PSEUDO_LOCALE:
		var raw: Variant = I18n.lookup(tables, I18n.FALLBACK, key)
		if typeof(raw) == TYPE_NIL:
			if fallback == "":
				_missing(key)
				return key # left without brackets on purpose: the pseudo check flags it
			raw = fallback
		return I18n.fill(I18n.pseudo(str(raw)), args)
	var found: Variant = I18n.lookup(tables, locale, key)
	if typeof(found) == TYPE_NIL:
		if fallback != "":
			return I18n.fill(fallback, args)
		_missing(key)
		return key
	return I18n.fill(str(found), args)


func tn(key: String, n: float, args: Dictionary = {}) -> String:
	var a: Dictionary = args.duplicate()
	a["n"] = n
	var rules: String = I18n.FALLBACK if locale == I18n.PSEUDO_LOCALE else locale
	return t(key + "." + I18n.plural(rules, n), a)


func content(text: String) -> String:
	# Text from data files (dialogue, credits): shown as written, pseudo-localized in the "pseudo" locale
	return I18n.pseudo(text) if locale == I18n.PSEUDO_LOCALE else text


func locales() -> PackedStringArray:
	var out: PackedStringArray = []
	var names: Array = tables.keys()
	names.sort()
	if names.has(I18n.FALLBACK):
		out.append(I18n.FALLBACK)
	for name: String in names:
		if not out.has(name):
			out.append(name)
	if OS.is_debug_build():
		out.append(I18n.PSEUDO_LOCALE)
	return out


# ---- bindings and glyphs ------------------------------------------------------

func glyph_set() -> String:
	return Bindings.glyph_set(str((settings["input"] as Dictionary)["glyphs"]), last_device)


func bindings() -> Dictionary:
	return (settings["input"] as Dictionary)["bindings"]


func prompt_for(action: String) -> String:
	return Bindings.prompt_binding(bindings(), action, glyph_set())


func binding_text(binding: String, gset: String = "") -> String:
	if binding == "":
		return t("controls.unbound")
	var set_name: String = gset if gset != "" else glyph_set()
	return t("binding." + binding.replace(":", "."), {}, InputBinder.label(set_name, binding))


func glyph_texture(binding: String, gset: String = "") -> Texture2D:
	# assets/ui/glyphs/<glyph_name>.png, or null (then show binding_text instead)
	if binding == "":
		return null
	var file: String = GLYPH_DIR.path_join(Bindings.glyph_name(gset if gset != "" else glyph_set(), binding) + ".png")
	return load(file) as Texture2D if ResourceLoader.exists(file) else null


# ---- internals ----------------------------------------------------------------

func _parses(loaded: Dictionary) -> bool:
	# A GameSettings.load_text() result that came from real JSON settings (values may still have been fixed)
	var problems: PackedStringArray = loaded["problems"]
	return not (problems.has("unreadable") or problems.has("not an object"))


func _from(loaded: Dictionary, source: String, file: String) -> Dictionary:
	loaded["source"] = source
	loaded["path"] = file
	return loaded


func _apply_display() -> void:
	var d: Dictionary = settings["display"]
	Engine.max_fps = int(d["frame_cap"])
	if DisplayServer.get_name() == "headless":
		return
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_ENABLED if d["vsync"] else DisplayServer.VSYNC_DISABLED)
	if capture:
		return # screenshots keep the project's window so they compare across runs
	var mode: DisplayServer.WindowMode = WINDOW_MODES.get(d["mode"], DisplayServer.WINDOW_MODE_WINDOWED)
	if DisplayServer.window_get_mode() != mode:
		DisplayServer.window_set_mode(mode)
	if mode == DisplayServer.WINDOW_MODE_WINDOWED:
		var usable: Rect2i = DisplayServer.screen_get_usable_rect()
		var want: Vector2i = Vector2i(int(d["resolution"][0]), int(d["resolution"][1]))
		if usable.size.x > 0:
			want = Vector2i(mini(want.x, usable.size.x), mini(want.y, usable.size.y))
		if DisplayServer.window_get_size() != want:
			DisplayServer.window_set_size(want)
			DisplayServer.window_set_position(usable.position + (usable.size - want) / 2)


func _apply_audio() -> void:
	for bus: String in AUDIO_BUSES:
		if AudioServer.get_bus_index(bus) < 0:
			AudioServer.add_bus()
			var idx: int = AudioServer.bus_count - 1
			AudioServer.set_bus_name(idx, bus)
			AudioServer.set_bus_send(idx, "Master")
	var audio: Dictionary = settings["audio"]
	for bus: String in BUS_SETTING:
		var idx: int = AudioServer.get_bus_index(bus)
		var volume: float = float(audio[BUS_SETTING[bus]])
		AudioServer.set_bus_mute(idx, volume <= 0.0)
		AudioServer.set_bus_volume_db(idx, linear_to_db(maxf(volume, 0.0001)))
	# Mono: a stereo enhancer with pan pullout 0 folds both channels together on the master bus
	var mono_slot: int = -1
	for i: int in AudioServer.get_bus_effect_count(0):
		if AudioServer.get_bus_effect(0, i) is AudioEffectStereoEnhance:
			mono_slot = i
	if mono_slot < 0:
		var fx: AudioEffectStereoEnhance = AudioEffectStereoEnhance.new()
		fx.pan_pullout = 0.0
		AudioServer.add_bus_effect(0, fx)
		mono_slot = AudioServer.get_bus_effect_count(0) - 1
	AudioServer.set_bus_effect_enabled(0, mono_slot, bool(audio["mono"]))


func _apply_input() -> void:
	var input: Dictionary = settings["input"]
	InputBinder.apply(input["bindings"], float(input["deadzone"]))


func _apply_access() -> void:
	if _color_filter != null:   # only when colours.json asks for the filter (#169: it hurt the demo's pairs)
		_color_filter.set_mode(AccessColours.filter_mode(colours, str(access("colorblind"))))


func _update_locale(emit: bool) -> void:
	var wanted: String = locale_override if locale_override != "" else str(settings["language"])
	if wanted != locale:
		locale = wanted
		if emit:
			locale_changed.emit()


func _missing(key: String) -> void:
	if not _missing_keys.has(key):
		_missing_keys[key] = true
		Log.warn("i18n", "no string for '%s' in %s" % [key, locale])


func _parse_args() -> void:
	var args: PackedStringArray = OS.get_cmdline_user_args()
	var i: int = 0
	while i < args.size():
		var value: String = args[i + 1] if i + 1 < args.size() else ""
		match args[i]:
			"--data-dir":
				data_dir = value
				i += 1
			"--drive":
				drive = value
				i += 1
			"--locale":
				locale_override = value
				i += 1
			"--smoke":
				smoke = true
			"--capture":
				capture = true
		i += 1
	if data_dir == "":
		data_dir = OS.get_user_data_dir()
	elif data_dir.is_relative_path():
		# Relative to the project in the editor, to the executable in an exported game
		var base: String = ProjectSettings.globalize_path("res://") if OS.has_feature("editor") \
				else OS.get_executable_path().get_base_dir()
		data_dir = base.path_join(data_dir).simplify_path()


func _is_tool_run() -> bool:
	var args: PackedStringArray = OS.get_cmdline_args()
	for i: int in args.size():
		if (args[i] == "-s" or args[i] == "--script") and i + 1 < args.size():
			for ok: String in GAME_SCRIPTS:
				if args[i + 1] == ok or args[i + 1].ends_with(ok.trim_prefix("res://")):
					return false
			return true
	return false


func _device_of(event: InputEvent) -> String:
	if event is InputEventKey:
		return "keyboard"
	if event is InputEventMouseButton:
		return "mouse"
	if event is InputEventJoypadButton or (event is InputEventJoypadMotion
			and absf((event as InputEventJoypadMotion).axis_value) > AXIS_DEVICE_SWITCH):
		var pad_name: String = Input.get_joy_name(event.device).to_lower()
		for word: String in PAD_PLAYSTATION:
			if pad_name.contains(word):
				return "pad_playstation"
		for word: String in PAD_XBOX:
			if pad_name.contains(word):
				return "pad_xbox"
		return "pad_other"
	return ""


func _stamp() -> String:
	var d: Dictionary = Time.get_datetime_dict_from_system()
	return "%04d%02d%02d_%02d%02d%02d_%03d" % [d["year"], d["month"], d["day"], d["hour"], d["minute"],
			d["second"], Time.get_ticks_msec() % 1000]


func _log_header() -> String:
	return "%s %s | Godot %s | %s build | %s | started %s" % [ProjectSettings.get_setting("application/config/name", ""),
			version, Engine.get_version_info().string, "debug" if OS.is_debug_build() else "release", OS.get_name(),
			Time.get_datetime_string_from_system()]

# {{FOOTER}}
