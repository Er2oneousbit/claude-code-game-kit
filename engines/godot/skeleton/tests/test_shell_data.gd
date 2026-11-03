# ---------------------------------------------------------------------------
# test_shell_data.gd
# Purpose : The data-side pieces of the front end without a running game: telemetry only with consent, the sample
#           dialogue file (barks, typewriter reveal, cues), the shipped string tables, binding strings that
#           survive the trip to a Godot InputEvent and back, and the music player's plan for a change asked while
#           a track waits out a stinger.
# Usage   : python tools/dev.py test --filter test_shell_data.gd
# Notes   : Engine-free where possible; the telemetry test writes to a temporary user:// folder.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

const DIALOGUE: String = "res://data/dialogue/sample.built.json"


func test_telemetry_writes_nothing_without_consent() -> void:
	var path: String = OS.get_user_data_dir().path_join("gut_telemetry_%d.csv" % Time.get_ticks_usec())
	for consent: String in ["unset", "no"]:
		var s: Dictionary = GameSettings.defaults()
		s["telemetry"]["consent"] = consent
		assert_false(Telemetry.append(path, GameSettings.telemetry_allowed(s), "abc", "screen", "title"))
		assert_false(FileAccess.file_exists(path), "consent %s must not create the file" % consent)
	assert_true(Telemetry.append(path, true, "abc", "screen", "title, with comma"))
	assert_true(Telemetry.append(path, true, "abc", "quit"))
	var lines: PackedStringArray = FileAccess.get_file_as_string(path).strip_edges().split("\n")
	assert_eq(lines.size(), 3, "header plus two rows")
	assert_eq(lines[0], Telemetry.HEADER)
	assert_true(lines[1].ends_with(",abc,screen,\"title, with comma\""), lines[1])
	DirAccess.remove_absolute(path)


func test_menus_drive_steps_towards_the_target_from_any_start() -> void:
	# smoke --drive menus must reach master 0.5 from a data folder seeded with any value, not only 1.0
	var t: float = SmokeDrive.TARGET_MASTER
	assert_eq(SmokeDrive.slide_action(1.0, t), "ui_left")
	assert_eq(SmokeDrive.slide_action(0.3, t), "ui_right")
	assert_eq(SmokeDrive.slide_action(0.0, t), "ui_right")
	assert_eq(SmokeDrive.slide_action(t, t), "")
	# a slider with 0.05 steps gets there from every value it can hold, within the press budget
	for start: int in 21:
		var v: float = start * 0.05
		var presses: int = 0
		while SmokeDrive.slide_action(v, t) != "" and presses < SmokeDrive.MAX_SLIDER_STEPS:
			v += -0.05 if SmokeDrive.slide_action(v, t) == "ui_left" else 0.05
			v = snappedf(v, 0.05)
			presses += 1
		assert_almost_eq(v, t, 1e-6, "from %s" % (start * 0.05))


func test_a_change_from_a_track_in_a_stinger_gap_is_planned_from_its_entry() -> void:
	# boss enters two bars after the switch (a 2-bar stinger plays first). A beat-quantized change asked in that gap
	# switches when boss enters, as the LÖVE, web and Unity players plan it, not inside the gap (#70)
	var music: Dictionary = {"sample_rate": 48000, "tracks": {
			"explore": {"bpm": 120, "beats_per_bar": 4, "bars": 4, "stems": {"a": "e.wav"}},
			"boss": {"bpm": 120, "beats_per_bar": 4, "bars": 4, "stems": {"a": "b.wav"}}},
			"stingers": {"hit": {"file": "s.wav", "bars": 2}},
			"transitions": [{"from": "*", "to": "boss", "quantize": "bar", "stinger": "hit"},
				{"from": "boss", "to": "explore", "quantize": "beat"}]}
	var go: Dictionary = MusicDirector.plan(music, "explore", 0, 0, "boss", 1000)
	var since: int = int(go["to_start_at"])
	assert_eq(since, 96000 * 3, "switch on bar 1, boss two stinger bars later")
	var deck: Dictionary = {"track": "boss", "since": since, "entry": 0}
	var asked: int = int(go["stinger_at"]) + 1000
	assert_lt(int(MusicDirector.plan(music, "boss", since, 0, "explore", asked)["switch_at"]), since,
			"planned from the request time, the switch would fall in the gap")
	var p: Dictionary = MusicPlayer.plan_change(music, deck, "explore", asked)
	assert_eq_deep(p, MusicDirector.plan(music, "boss", since, 0, "explore", since))
	assert_eq(int(p["switch_at"]), since)
	var later: int = since + 30000 # after boss entered, the request time counts as usual
	assert_eq_deep(MusicPlayer.plan_change(music, deck, "explore", later),
			MusicDirector.plan(music, "boss", since, 0, "explore", later))


func test_sample_dialogue_reads_and_gates_barks() -> void:
	var dlg: Dictionary = DialogueData.parse(FileAccess.get_file_as_string(DIALOGUE))
	assert_false(dlg.is_empty(), "sample.built.json parses")
	var intro: Dictionary = DialogueData.line(dlg, "guide.intro")
	var bark: Dictionary = DialogueData.line(dlg, "box.ouch")
	var access: Dictionary = GameSettings.defaults()["access"]
	assert_true(DialogueData.should_show(intro, access))
	assert_false(DialogueData.should_show(bark, access), "barks are off by default")
	access["subtitle_barks"] = true
	assert_true(DialogueData.should_show(bark, access))
	access["subtitles"] = false
	assert_false(DialogueData.should_show(intro, access), "subtitles off hides every line")
	assert_eq(DialogueData.revealed(intro, -1.0), 0)
	assert_eq(DialogueData.revealed(intro, 100.0), str(intro["text"]).length())
	assert_gt(DialogueData.cue_lines(intro, 0.1).size(), 0)
	assert_eq(DialogueData.cue_lines(intro, 100.0).size(), 0)
	assert_false(DialogueData.caption(dlg, "box_hit").is_empty())


func test_unknown_dialogue_version_is_refused() -> void:
	assert_true(DialogueData.parse("{\"version\": 2, \"lines\": {}}").is_empty())
	assert_true(DialogueData.parse("not json").is_empty())


func test_string_tables_cover_english_and_fall_back() -> void:
	var tables: Dictionary = I18n.load_tables("res://data/i18n")
	assert_true(tables.has("en") and tables.has("fr"))
	for key: String in tables["fr"]:
		if not key.begins_with("binding."):
			assert_true((tables["en"] as Dictionary).has(key), "fr has '%s' but en does not" % key)
	assert_eq(I18n.translate(tables, "fr", "menu.play"), "Jouer")
	assert_eq(I18n.translate(tables, "fr", "menu.juice"), tables["en"]["menu.juice"], "missing French falls back")


func test_bindings_round_trip_through_input_events() -> void:
	for action: String in Bindings.DEFAULT_BINDINGS:
		for binding: String in Bindings.DEFAULT_BINDINGS[action]:
			var ev: InputEvent = InputBinder.to_event(binding)
			assert_not_null(ev, "no InputEvent for %s" % binding)
			if ev is InputEventKey:
				(ev as InputEventKey).pressed = true
			elif ev is InputEventJoypadButton:
				(ev as InputEventJoypadButton).pressed = true
			assert_eq(InputBinder.from_event(ev), binding)
	for binding: String in ["pad:l2", "pad_axis:leftx-", "pad_axis:righty+", "mouse:right", "key:f5"]:
		assert_eq(InputBinder.from_event(_pressed(InputBinder.to_event(binding))), binding)


func _pressed(ev: InputEvent) -> InputEvent:
	if ev is InputEventMouseButton:
		(ev as InputEventMouseButton).pressed = true
	elif ev is InputEventKey:
		(ev as InputEventKey).pressed = true
	return ev

# {{FOOTER}}
