# ---------------------------------------------------------------------------
# capture.gd
# Purpose : Boot the game's main scene in a real window and save what it draws: one screenshot of the last frame,
#           and/or a burst of frames (one PNG every N milliseconds) to turn into a GIF. Seeing an animation move is the
#           only reliable way to judge it; one still frame cannot show a punch.
# Usage   : python tools/dev.py smoke --screenshot captures/progress/03-punch.png
#           python tools/dev.py smoke --record captures/frames-03   (then tools/art/frames_to_gif.py)
#           Direct: godot --path . -s res://tools/capture.gd -- --frames 120 --shot <abs.png> --record <abs dir> --every-ms 66
#           With a smoke drive: dev.py smoke --drive show:settings --screenshot captures/settings.png
# Notes   : Needs a window: headless Godot has no renderer, so dev.py runs this without --headless after the
#           headless smoke passed. A window opens for a few seconds. Paths are absolute (dev.py passes them).
#           With --drive, the picture is taken when the drive has opened its screen (the Shell autoload's
#           capture_ready), READY_SETTLE_FRAMES later, instead of after --frames; dev.py adds --fixed-fps 60 so the
#           picture is the same on every run. Other user args (--data-dir, --locale, --smoke) are for the Shell.
#           Exit 0 done, 1 a save failed or the drive never got there, 2 bad arguments or a main scene that is
#           missing or does not load.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-10-26: bursts timed in real milliseconds (monitors are not all 60 Hz)
# Updated : 2026-11-01 with Claude (Opus 5.5, claude-opus-5-5): --drive waits for Shell.capture_ready
# Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): a main scene that fails to load and a --frames or
#           --every-ms that is not a whole number exit 2 (they gave a blank capture and exit 0, or a silent 1)
# ---------------------------------------------------------------------------
extends SceneTree

const DEFAULT_FRAMES: int = 120
const DEFAULT_EVERY_MS: int = 66 # milliseconds between burst saves; real time, so a 144 Hz monitor spaces them the same
const DRIVE_TIMEOUT_FRAMES: int = 3600 # a drive that never reaches its screen fails instead of hanging
const READY_SETTLE_FRAMES: int = 2 # frames between capture_ready and the picture (the frame must be drawn first)

var _shot: String = ""
var _record: String = ""
var _frames: int = DEFAULT_FRAMES
var _every_ms: int = DEFAULT_EVERY_MS
var _last_ms: int = -1
var _frame: int = 0
var _saved: int = 0
var _failed: bool = false
var _drive: String = ""
var _ready_frames: int = 0
var _stopped: bool = false # quit() was called: no more frames are saved


func _initialize() -> void:
	var args: PackedStringArray = OS.get_cmdline_user_args()
	var i: int = 0
	while i < args.size():
		var key: String = args[i]
		var value: String = args[i + 1] if i + 1 < args.size() else ""
		match key:
			"--shot":
				_shot = value
			"--record":
				_record = value
			"--frames":
				if not value.is_valid_int() or value.to_int() < 1:
					_stop(2, "capture: --frames needs a whole number of 1 or more, got %s" % value)
					return
				_frames = value.to_int()
			"--every-ms":
				if not value.is_valid_int() or value.to_int() < 1:
					_stop(2, "capture: --every-ms needs a whole number of 1 or more, got %s" % value)
					return
				_every_ms = value.to_int()
			"--drive":
				_drive = value # the Shell runs it; we only wait for it
			_:
				i -= 1 # not ours (e.g. --debug for the Log autoload): skip one
		i += 2
	if _shot == "" and _record == "":
		_stop(2, "capture: give --shot <file.png> and/or --record <folder>")
		return
	if _record != "":
		DirAccess.make_dir_recursive_absolute(_record)
	if _shot != "":
		DirAccess.make_dir_recursive_absolute(_shot.get_base_dir())
	var main_scene: String = ProjectSettings.get_setting("application/run/main_scene", "")
	if main_scene == "":
		_stop(2, "capture: the project has no main scene (Project Settings > Application > Run)")
		return
	var err: Error = change_scene_to_file(main_scene)
	if err != OK:
		_stop(2, "capture: could not load the main scene %s (%s)" % [main_scene, error_string(err)])


func _stop(code: int, message: String) -> void:
	push_error(message)
	_stopped = true
	quit(code)


func _process(_delta: float) -> bool:
	if _stopped:
		return false
	_frame += 1
	var now: int = Time.get_ticks_msec()
	if _record != "" and (_last_ms < 0 or now - _last_ms >= _every_ms):
		_last_ms = now
		_save(_record.path_join("f%05d.png" % _saved))
		_saved += 1
	if _drive != "":
		var shell: Node = root.get_node_or_null("Shell")
		if shell != null and bool(shell.get("capture_ready")):
			_ready_frames += 1
			if _ready_frames > READY_SETTLE_FRAMES:
				_finish()
		elif _frame >= DRIVE_TIMEOUT_FRAMES:
			_stop(1, "capture: drive %s never reached its screen" % _drive)
		return false
	if _frame >= _frames:
		_finish()
	return false


func _finish() -> void:
	if _shot != "":
		_save(_shot)
	print("CAPTURE_DONE frames=%d saved=%d" % [_frame, _saved])
	_stopped = true
	quit(1 if _failed else 0)


func _save(path: String) -> void:
	var image: Image = root.get_texture().get_image()
	var err: Error = image.save_png(path)
	if err != OK:
		push_error("capture: could not save %s (%s)" % [path, error_string(err)])
		_failed = true
