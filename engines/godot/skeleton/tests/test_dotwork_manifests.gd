# ---------------------------------------------------------------------------
# test_dotwork_manifests.gd
# Purpose : Every real Dotwork asset manifest of the game (assets/dotwork/*.assets.json) loads through the importer
#           (DotworkAssets), every file it names ships at the size it says, and every map builds its TileMapLayers:
#           the stand-in for Dotwork's own `verify` for packs Godot has no Dotwork resources for (a 3D model rendered
#           to sprites by render_sprites.py --manifest). A game with no manifests passes and says so.
# Usage   : python tools/dev.py test     (or --filter test_dotwork_manifests.gd)
# Notes   : Fails on a manifest that does not parse, another major version, a missing or mis-sized PNG, a rect
#           outside its image, or a broken reference (a map's tileset, a portrait's animation, a tile a map names).
#           Warnings (an unknown kind or layer kind, a terrain key no tile answers to, an unknown field) are
#           printed, not failed.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): created with the Godot importer (#307)
# ---------------------------------------------------------------------------
extends GutTest


func test_every_game_manifest_loads() -> void:
	var paths: PackedStringArray = DotworkAssets.find()
	var bad: PackedStringArray = []
	for path: String in paths:
		var model: Dictionary = DotworkAssets.load_manifest(path)
		bad.append_array(DotworkAssets.verify(model))
		if model.has("error"):
			continue
		for w: String in model["warnings"]:
			gut.p("WARN " + w)
		for map_name: String in model["map"]:
			var root: Node2D = DotworkAssets.map_node(model["map"][map_name])
			if root.get_child_count() == 0 and not (model["map"][map_name]["layers"] as Array).is_empty():
				bad.append("%s: map %s built no layers" % [path, map_name])
			root.free()
	if paths.is_empty():
		gut.p("DOTWORK no manifests in %s (nothing to check)" % DotworkAssets.DIR)
	else:
		gut.p("DOTWORK %d manifest(s) checked in %s, %d problem(s)" % [paths.size(), DotworkAssets.DIR, bad.size()])
	assert_eq(bad.size(), 0, "%d problem(s):\n  %s" % [bad.size(), "\n  ".join(bad)])

# {{FOOTER}}
