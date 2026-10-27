# ---------------------------------------------------------------------------
# capture.gd
# Purpose : Boot the game's main scene in a real window and save what it draws: one screenshot of the last frame,
#           and/or a burst of frames (one PNG every N milliseconds) to turn into a GIF. Seeing an animation move is the
#           only reliable way to judge it; one still frame cannot show a punch.
# Usage   : python tools/dev.py smoke --screenshot captures/progress/03-punch.png
#           python tools/dev.py smoke --record captures/frames-03   (then tools/art/frames_to_gif.py)
#           Direct: godot --path . -s res://tools/capture.gd -- --frames 120 --shot <abs.png> --record <abs dir> --every-ms 66
# Notes   : Needs a window: headless Godot has no renderer, so dev.py runs this without --headless after the
#           headless smoke passed. A window opens for a few seconds. Paths are absolute (dev.py passes them).
#           Exit 0 done, 1 a save failed, 2 bad arguments or no main scene.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-10-26: bursts timed in real milliseconds (monitors are not all 60 Hz)
# ---------------------------------------------------------------------------
extends SceneTree

const DEFAULT_FRAMES: int = 120
const DEFAULT_EVERY_MS: int = 66 # milliseconds between burst saves; real time, so a 144 Hz monitor spaces them the same

var _shot: String = ""
var _record: String = ""
var _frames: int = DEFAULT_FRAMES
var _every_ms: int = DEFAULT_EVERY_MS
var _last_ms: int = -1
var _frame: int = 0
var _saved: int = 0
var _failed: bool = false


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
				_frames = maxi(1, value.to_int())
			"--every-ms":
				_every_ms = maxi(1, value.to_int())
			_:
				i -= 1 # not ours (e.g. --debug for the Log autoload): skip one
		i += 2
	if _shot == "" and _record == "":
		push_error("capture: give --shot <file.png> and/or --record <folder>")
		quit(2)
		return
	if _record != "":
		DirAccess.make_dir_recursive_absolute(_record)
	if _shot != "":
		DirAccess.make_dir_recursive_absolute(_shot.get_base_dir())
	var main_scene: String = ProjectSettings.get_setting("application/run/main_scene", "")
	if main_scene == "":
		push_error("capture: the project has no main scene (Project Settings > Application > Run)")
		quit(2)
		return
	change_scene_to_file(main_scene)


func _process(_delta: float) -> bool:
	_frame += 1
	var now: int = Time.get_ticks_msec()
	if _record != "" and (_last_ms < 0 or now - _last_ms >= _every_ms):
		_last_ms = now
		_save(_record.path_join("f%05d.png" % _saved))
		_saved += 1
	if _frame >= _frames:
		if _shot != "":
			_save(_shot)
		print("CAPTURE_DONE frames=%d saved=%d" % [_frame, _saved])
		quit(1 if _failed else 0)
	return false


func _save(path: String) -> void:
	var image: Image = root.get_texture().get_image()
	var err: Error = image.save_png(path)
	if err != OK:
		push_error("capture: could not save %s (%s)" % [path, error_string(err)])
		_failed = true
