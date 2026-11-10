# ---------------------------------------------------------------------------
# main_menu.gd
# Purpose : The main menu: Play, Juice demo (debug builds only), Settings, Credits, Quit.
# Usage   : front.open_main_menu()   (from the title screen)
# Notes   : Cancel goes back to the title. Quit is hidden in web builds (a browser tab cannot quit itself).
#           Add your own entries with button(Shell.t("menu.<key>"), "<NodeName>", callable) and a string in
#           data/i18n/en.json.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name MainMenu
extends ShellScreen


func _init(p_front: FrontEnd) -> void:
	super(p_front, "main_menu")


func build() -> void:
	var col: VBoxContainer = centered_column()
	var title: Label = label(Shell.t("game.title", {"name": Shell.game_name()}), UiTheme.HEADING_FONT, "Title")
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	col.add_child(title)
	col.add_child(button(Shell.t("menu.play"), "Play", front.start_play))
	if OS.is_debug_build():
		col.add_child(button(Shell.t("menu.juice"), "JuiceDemo", front.start_juice))
	col.add_child(button(Shell.t("menu.settings"), "Settings", front.open_settings))
	col.add_child(button(Shell.t("menu.credits"), "Credits", front.open_credits))
	if not OS.has_feature("web"):
		col.add_child(button(Shell.t("menu.quit"), "Quit", front.quit_game))

# {{FOOTER}}
