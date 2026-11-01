# ---------------------------------------------------------------------------
# loading_screen.gd
# Purpose : The loading screen between the menu and play: loads the play scene on a background thread and shows
#           a progress bar, then hands the scene to FrontEnd.
# Usage   : front.start_play()   (opens this with FrontEnd.PLAY_SCENE)
# Notes   : The bar never moves faster than MIN_SHOW_S allows, so a fast load does not flash the screen. A load
#           error returns to the title and logs it. Replace scenes/play.tscn with your game's first level, or
#           pass another scene path to LoadingScreen.new().
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name LoadingScreen
extends ShellScreen

const MIN_SHOW_S: float = 0.6
const BAR_SIZE: Vector2 = Vector2(240, 10)

var scene_path: String
var _elapsed: float = 0.0
var _bar: ProgressBar
var _percent: Label
var _done: bool = false


func _init(p_front: FrontEnd, p_scene_path: String) -> void:
	super(p_front, "loading")
	scene_path = p_scene_path


func _ready() -> void:
	super()
	var err: Error = ResourceLoader.load_threaded_request(scene_path)
	if err != OK:
		Log.error("shell", "cannot load %s (%s)" % [scene_path, error_string(err)])
		_done = true
		front.show_title.call_deferred()


func build() -> void:
	var col: VBoxContainer = centered_column()
	col.add_child(label(Shell.t("loading.title"), 1.0, "Heading"))
	_bar = ProgressBar.new()
	_bar.name = "Progress"
	_bar.custom_minimum_size = BAR_SIZE
	_bar.show_percentage = false # its own text would bypass the string tables
	col.add_child(_bar)
	_percent = label(Shell.t("fmt.percent", {"n": 0}), 1.0, "Percent")
	_percent.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	col.add_child(_percent)


func on_cancel() -> void:
	pass # loading cannot be cancelled


func _process(delta: float) -> void:
	if _done:
		return
	_elapsed += delta
	var progress: Array = []
	var status: ResourceLoader.ThreadLoadStatus = ResourceLoader.load_threaded_get_status(scene_path, progress)
	var real: float = 1.0 if status == ResourceLoader.THREAD_LOAD_LOADED else (float(progress[0]) if not progress.is_empty() else 0.0)
	var shown: float = minf(real, _elapsed / MIN_SHOW_S)
	_bar.value = shown * 100.0
	_percent.text = Shell.t("fmt.percent", {"n": roundi(shown * 100.0)})
	if status == ResourceLoader.THREAD_LOAD_FAILED or status == ResourceLoader.THREAD_LOAD_INVALID_RESOURCE:
		_done = true
		Log.error("shell", "loading %s failed" % scene_path)
		front.show_title()
	elif status == ResourceLoader.THREAD_LOAD_LOADED and _elapsed >= MIN_SHOW_S:
		_done = true
		var packed: PackedScene = ResourceLoader.load_threaded_get(scene_path) as PackedScene
		front.enter_world(packed.instantiate(), "play")
