# ---------------------------------------------------------------------------
# test_shell_data.gd
# Purpose : The data-side pieces of the front end without a running game: telemetry only with consent, the sample
#           dialogue file (barks, typewriter reveal, cues), the shipped string tables, and binding strings that
#           survive the trip to a Godot InputEvent and back.
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
