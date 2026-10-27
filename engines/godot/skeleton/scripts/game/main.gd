# ---------------------------------------------------------------------------
# main.gd
# Purpose : Entry scene script. Announces a successful boot so `dev.py smoke`
#           can verify the game starts without errors.
# Usage   : Attached to scenes/main.tscn (the project's main scene).
# Notes   : PROTOTYPE: replace with your real boot flow (menu, loading, etc.).
#           Keep the "BOOT_OK" line (or update tools/dev.py smoke to match).
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# ---------------------------------------------------------------------------
extends Node


func _ready() -> void:
	Log.info("core", "BOOT_OK {{GAME_NAME}}")

# {{FOOTER}}
