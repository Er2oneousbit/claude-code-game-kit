# ---------------------------------------------------------------------------
# smoke_drive.gd
# Purpose : Scripted runs of the front end for `dev.py smoke --drive <scenario>`: it presses the same actions a
#           player would (ui_down, ui_accept, ...) and prints markers dev.py and tests read.
# Usage   : python tools/dev.py smoke --drive menus                 # change two settings, Back, check the file
#           python tools/dev.py smoke --drive crash                 # a script error -> crash file, exit 1
#           python tools/dev.py smoke --drive pseudo --locale pseudo        # every screen, nothing clipped
#           python tools/dev.py smoke --drive pseudo-plant --locale pseudo  # plus one label too small: exit 1
#           python tools/dev.py smoke --drive show:settings --screenshot captures/settings.png
#           (show: title, settings, pause, subtitle, juice)
# Notes   : Markers: DRIVE_DONE <scenario>, DRIVE_FAIL <why>, SETTINGS_BEFORE / SETTINGS_WRITTEN <path> ...,
#           CRASH_WRITTEN <path> (from Shell), PSEUDO_FAIL / PSEUDO_OK. Navigation goes through the real input
#           path (Viewport.push_input of InputEventAction), so a broken focus chain fails the run. Under
#           tools/capture.gd (--capture) a show: scenario sets Shell.capture_ready and keeps running instead of
#           quitting. dev.py runs drives with --fixed-fps 60, so every frame is 1/60 s of game time and pictures
#           repeat; headless, those frames run as fast as the CPU allows, so screen waits use real time (WAIT_MS).
#           MAX_NAV_STEPS bounds every "press until focused" loop.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name SmokeDrive
extends Node

const MAX_NAV_STEPS: int = 30
const WAIT_MS: int = 10000 # real time a screen gets to appear (headless frames run far faster than 60 per second,
		# so background loading needs a real-time budget, not a frame count)
const WAIT_FRAMES: int = 600 # game frames the subtitle line gets to finish
const SETTLE_FRAMES: int = 20 # frames a screen gets before it is photographed
const TARGET_MASTER: float = 0.5 # menus drives the master volume here from whatever the data folder held
const MAX_SLIDER_STEPS: int = 40 # presses a slider gets to reach its target (0..1 is 20 steps of 0.05)
const JUICE_HIT_FRAME: int = 40 # frames into the juice demo before the drive attacks
const JUICE_SHOT_FRAMES: int = 1 # frames after the hit; capture adds 3, still inside the hitstop freeze
const PLANTED_NAME: String = "PlantedTooSmall"
const PLANTED_WIDTH: float = 24.0
const SHOW_TARGETS: PackedStringArray = ["title", "settings", "pause", "subtitle", "juice"]

var front: FrontEnd
var scenario: String


func _init(p_front: FrontEnd) -> void:
	front = p_front
	scenario = Shell.drive
	name = "SmokeDrive"
	process_mode = Node.PROCESS_MODE_ALWAYS


func _ready() -> void:
	_run.call_deferred()


func _run() -> void:
	Log.info("drive", "scenario %s" % scenario)
	if scenario == "menus":
		await _menus()
	elif scenario == "crash":
		await _crash()
	elif scenario == "pseudo" or scenario == "pseudo-plant":
		await _pseudo(scenario == "pseudo-plant")
	elif scenario.begins_with("show:") and SHOW_TARGETS.has(scenario.trim_prefix("show:")):
		await _show(scenario.trim_prefix("show:"))
	else:
		_fail("unknown scenario '%s' (menus, crash, pseudo, pseudo-plant, show:<%s>)" % [scenario,
				"|".join(SHOW_TARGETS)])


# ---- scenarios ------------------------------------------------------------------

func _menus() -> void:
	var file: String = Shell.path(Shell.SETTINGS_FILE)
	var before: Dictionary = Shell.settings
	var before_master: float = float(before["audio"]["master"])
	var before_motion: bool = bool(before["access"]["reduce_motion"])
	Log.raw("SETTINGS_BEFORE %s master=%s reduce_motion=%s (%s)" % [file, before_master, before_motion,
			"file exists" if FileAccess.file_exists(file) else "no file yet"])
	if not await _to_main_menu():
		return
	if not await _nav_to("Settings", "ui_down") or not await _accept("settings"):
		return
	if not await _nav_to("Tab_audio", "ui_right") or not await _nav_to("Setting_audio_master", "ui_down"):
		return
	if not await _slide_to("audio", "master", TARGET_MASTER):
		return
	if not await _nav_to("Tab_audio", "ui_up") or not await _nav_to("Tab_access", "ui_right"):
		return
	if not await _nav_to("Setting_access_reduce_motion", "ui_down"):
		return
	await _press("ui_accept")
	await _press("ui_cancel") # Back saves
	if not await _wait_screen("main_menu"):
		return
	var loaded: Dictionary = GameSettings.load_text(AtomicFile.read_text(file))
	var s: Dictionary = loaded["settings"]
	var master: float = float(s["audio"]["master"])
	var motion: bool = bool(s["access"]["reduce_motion"])
	Log.raw("SETTINGS_WRITTEN %s master=%s reduce_motion=%s" % [file, master, motion])
	if absf(master - TARGET_MASTER) > 1e-6 or motion == before_motion:
		_fail("settings file does not hold master=%s and reduce_motion=%s" % [TARGET_MASTER, not before_motion])
		return
	Log.raw("TELEMETRY_FILE %s" % ("present" if FileAccess.file_exists(Shell.path(Shell.TELEMETRY_FILE))
			else "absent (consent %s)" % Shell.settings["telemetry"]["consent"]))
	if not await _nav_to("Quit", "ui_down"):
		return
	Log.raw("DRIVE_DONE menus")
	await _press("ui_accept") # Quit: exit code 0


func _crash() -> void:
	if not await _wait_screen("title"):
		return
	await _frames(5)
	Log.raw("DRIVE_CRASH raising a script error on purpose")
	_raise_script_error()
	await _frames(30) # Shell writes the crash file and quits with 1 on the next frame
	if not CrashHook.installed():
		_fail("no crash hook on this Godot version (the Logger hook needs 4.5+)")
	else:
		_fail("the crash hook did not write a crash file")


func _pseudo(plant: bool) -> void:
	if Shell.locale != I18n.PSEUDO_LOCALE:
		_fail("run it with --locale pseudo")
		return
	LabelAudit.checked = 0
	if not await _to_main_menu():
		return
	if plant:
		var tiny: Label = Label.new()
		tiny.name = PLANTED_NAME
		tiny.text = Shell.t("menu.play")
		tiny.clip_text = true
		tiny.custom_minimum_size = Vector2(PLANTED_WIDTH, 0)
		tiny.size = Vector2(PLANTED_WIDTH, 16)
		tiny.position = Vector2(8, 8)
		front.top().add_child(tiny)
		await _frames(2)
		front.audit_now("main_menu (planted)")
		await _frames(5)
		_fail("the planted label was not reported")
		return
	if not await _nav_to("Settings", "ui_down") or not await _accept("settings"):
		return
	for tab: String in SettingsScreen.TABS:
		if not await _nav_to("Tab_" + tab, "ui_right"):
			return
		await _frames(3)
		front.audit_now("settings/" + tab)
	await _press("ui_cancel")
	if not await _wait_screen("main_menu"):
		return
	if not await _nav_to("Credits", "ui_down") or not await _accept("credits"):
		return
	await _frames(3)
	await _press("ui_cancel")
	if not await _wait_screen("main_menu"):
		return
	if not await _nav_to("JuiceDemo", "ui_up") or not await _accept("juice"):
		return
	await _frames(30)
	front.audit_now("juice")
	if not await _pause_and_back():
		return
	if not await _to_main_menu():
		return
	if not await _nav_to("Play", "ui_up") or not await _accept("play"):
		return
	await _frames(10)
	if not await _pause_and_back():
		return
	Log.raw("PSEUDO_OK %d label(s) checked on %d screen(s)" % [LabelAudit.checked, front.audited_screens])
	_done(0)


func _show(target: String) -> void:
	match target:
		"title":
			if not await _wait_screen("title"):
				return
			await _dismiss_consent()
			await _frames(SETTLE_FRAMES)
		"settings":
			if not await _to_main_menu():
				return
			if not await _nav_to("Settings", "ui_down") or not await _accept("settings"):
				return
			if not await _nav_to("Tab_audio", "ui_right") or not await _nav_to("Setting_audio_master", "ui_down"):
				return
			await _frames(SETTLE_FRAMES)
		"pause":
			if not await _to_main_menu():
				return
			if not await _accept("play"):
				return # Play has focus first
			await _frames(SETTLE_FRAMES)
			await _press("pause")
			if not await _wait_screen("pause"):
				return
			await _frames(SETTLE_FRAMES)
		"subtitle", "juice":
			if not await _to_main_menu():
				return
			if not await _nav_to("JuiceDemo", "ui_down") or not await _accept("juice"):
				return
			var demo: JuiceDemo = front.world_node as JuiceDemo
			if target == "subtitle":
				for i: int in WAIT_FRAMES:
					if demo.subtitles.is_fully_shown():
						break
					await _frames(1)
				await _frames(SETTLE_FRAMES)
			else:
				await _frames(JUICE_HIT_FRAME)
				Input.action_press("attack")
				await _frames(1)
				Input.action_release("attack")
				await _frames(JUICE_SHOT_FRAMES)
	Log.raw("DRIVE_SHOWN %s" % target)
	_done(0)


# ---- steps --------------------------------------------------------------------

func _to_main_menu() -> bool:
	if not await _wait_screen("title"):
		return false
	await _dismiss_consent()
	await _frames(2)
	await _press("ui_accept") # "press any key"
	return await _wait_screen("main_menu")


func _dismiss_consent() -> void:
	var title: TitleScreen = front.top() as TitleScreen
	if title != null and title.consent_open():
		await _nav_to("Later", "ui_right")
		await _press("ui_accept")
		await _frames(2)


func _pause_and_back() -> bool:
	await _press("pause")
	if not await _wait_screen("pause"):
		return false
	if not await _nav_to("QuitToTitle", "ui_down"):
		return false
	await _press("ui_accept")
	return await _wait_screen("title")


func _accept(next_screen: String) -> bool:
	await _press("ui_accept")
	return await _wait_screen(next_screen)


func _press(action: String) -> void:
	# Through the viewport, like a key press: focused control first, then focus navigation, then _unhandled_input
	var down: InputEventAction = InputEventAction.new()
	down.action = action
	down.pressed = true
	get_viewport().push_input(down)
	await _frames(1)
	var up: InputEventAction = InputEventAction.new()
	up.action = action
	up.pressed = false
	get_viewport().push_input(up)
	await _frames(1)


func _nav_to(node_name: String, action: String) -> bool:
	# Press action until the control named node_name has focus
	for i: int in MAX_NAV_STEPS:
		var owner_node: Control = get_viewport().gui_get_focus_owner()
		if owner_node != null and owner_node.name == node_name:
			return true
		await _press(action)
	var owner_now: Control = get_viewport().gui_get_focus_owner()
	_fail("could not reach '%s' with %s (focus is on %s)" % [node_name, action,
			owner_now.name if owner_now != null else "nothing"])
	return false


static func slide_action(now: float, target: float) -> String:
	# The press that moves a slider from now towards target ("" once it is there)
	if absf(now - target) <= 1e-6:
		return ""
	return "ui_left" if now > target else "ui_right"


func _slide_to(section: String, field: String, target: float) -> bool:
	# Press left or right on the focused slider until the live setting equals target, from any start value
	for i: int in MAX_SLIDER_STEPS:
		var action: String = slide_action(float(Shell.settings[section][field]), target)
		if action == "":
			return true
		await _press(action)
	_fail("%s.%s did not reach %s (is %s)" % [section, field, target, Shell.settings[section][field]])
	return false


func _wait_screen(screen: String) -> bool:
	var start: int = Time.get_ticks_msec()
	while Time.get_ticks_msec() - start < WAIT_MS:
		if front.current_name() == screen:
			await _frames(2)
			return true
		await _frames(1)
	_fail("screen '%s' did not appear (now: '%s')" % [screen, front.current_name()])
	return false


func _frames(n: int) -> void:
	for i: int in n:
		await get_tree().process_frame


func _raise_script_error() -> void:
	var missing: Node = null
	missing.queue_free() # "Cannot call method 'queue_free' on a null value": a real runtime error


func _done(code: int) -> void:
	if Shell.capture:
		Shell.capture_ready = true # tools/capture.gd takes the picture and quits
		return
	Log.raw("DRIVE_DONE %s" % scenario)
	get_tree().quit(code)


func _fail(why: String) -> void:
	Log.raw("DRIVE_FAIL %s: %s" % [scenario, why])
	get_tree().quit(1)
