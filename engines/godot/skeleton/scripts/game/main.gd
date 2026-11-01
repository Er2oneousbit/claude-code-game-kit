# ---------------------------------------------------------------------------
# main.gd
# Purpose : Entry scene script (boot). Announces a successful boot so `dev.py smoke` can verify the game starts
#           without errors, then hands over to the front end (title, menus, settings, play).
# Usage   : Attached to scenes/main.tscn (the project's main scene).
# Notes   : Keep the "BOOT_OK" line (or update tools/dev.py smoke to match). The Shell autoload has already
#           loaded settings and strings by now. To skip the menus while prototyping, replace the FrontEnd line
#           with your own scene; the screens live in scripts/shell/.
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# Updated : 2026-11-01 with Claude (Opus 5.5, claude-opus-5-5): boots into the front end (scripts/shell/)
# ---------------------------------------------------------------------------
extends Node


func _ready() -> void:
	Log.info("core", "BOOT_OK {{GAME_NAME}}")
	add_child(FrontEnd.new())

# {{FOOTER}}
