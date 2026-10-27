# ---------------------------------------------------------------------------
# test_audio.gd
# Purpose : GUT tests for the created audio: the theme loops by itself (loop points written into the
#           WAV by tools/audio/chiptune.py, picked up by Godot's default "Detect From WAV" import),
#           the goal jingle and the effects play once.
# Usage   : python tools/dev.py test      (needs the GUT addon in addons/gut/)
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest

const THEME_SECONDS: float = 25.6   # 16 bars at 150 bpm, see assets/audio/src/theme.song.json


func test_theme_loops_over_the_whole_song() -> void:
	var theme: AudioStreamWAV = load("res://assets/audio/music/theme.wav")
	assert_eq(theme.loop_mode, AudioStreamWAV.LOOP_FORWARD, "the theme must loop without code")
	assert_eq(theme.loop_begin, 0)
	assert_almost_eq(theme.loop_end / float(theme.mix_rate), THEME_SECONDS, 0.01, "loop end = song end")


func test_jingle_and_effects_play_once() -> void:
	for path: String in ["res://assets/audio/music/goal.wav", "res://assets/audio/sfx/jump.wav",
			"res://assets/audio/sfx/coin.wav", "res://assets/audio/sfx/fall.wav", "res://assets/audio/sfx/land.wav"]:
		var s: AudioStreamWAV = load(path)
		assert_eq(s.loop_mode, AudioStreamWAV.LOOP_DISABLED, path)
