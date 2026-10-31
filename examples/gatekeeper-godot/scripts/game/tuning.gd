# ---------------------------------------------------------------------------
# tuning.gd
# Purpose : Every number and model setting in one place. Same rules as the web version.
# Notes   : The model never sees these numbers: trust math is game code, not prompt.
#           MODEL_PATH is Qwen2.5 1.5B Instruct (Apache-2.0, official Qwen GGUF, 1.1 GB, A-0002),
#           run by the NobodyWho plugin (EUPL-1.2, A-0001). Neither is in git: tools/setup_ai.py.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name Tuning
extends RefCounted

const RULES: Dictionary = {
	"start_trust": 20, "open_at": 70, "turns": 8, "max_threats": 2, "max_flattery": 2,
	# other is 0 on purpose: a line the guard did not understand must not cost the player
	"delta": {"greeting": 5, "flattery": 10, "bribe": -15, "threat": -25, "mentions_captain": 45, "question": 0, "other": 0},
}

const MODEL_PATH: String = "res://models/qwen2.5-1.5b-instruct-q4_k_m.gguf"
const MODEL_NAME: String = "Qwen2.5 1.5B"
const N_CTX: int = 2048
const REPLY_TIMEOUT_S: float = 12.0   # a model reply slower than this falls back to the scripted line
const LOAD_TIMEOUT_S: float = 90.0    # loading plus the warm-up reply; slower than this and the scripted guard plays
const SEED: int = 7

# Live voice (proof of concept, scripts/game/guard_voice.gd): your own Fish Audio key in FISH_API_KEY
const VOICE_MODEL: String = "s2.1-pro-free"   # costs nothing; "s2.1-pro" is billed per use on a Fish Audio developer account
const VOICE_ID: String = "afe69eaecd7b49d1b564b06421ce3706"   # "Calm Reflective Male", a Fish Audio licensed voice
const VOICE_TIMEOUT_S: float = 20.0   # a line slower than this is skipped (the text is already on screen)
const VOICE_DB: float = 0.0
const VOICE_DRAIN_S: float = 60.0      # autoplay waits at most this long for queued lines before quitting
