# ---------------------------------------------------------------------------
# test_golden_dotwork.gd
# Purpose : The Dotwork importer (scripts/core/dotwork_manifest.gd, dotwork_assets.gd) against the spec's golden
#           fixture: loads data/golden/dotwork/assets/dotwork/golden.assets.json and compares what it built with
#           data/golden/dotwork/expected.json (the reference loader's result) to 1e-6, every asset of every kind,
#           the three maps' terrain, placed cells and centres included. Where Godot holds the number (a frame's
#           seconds in the SpriteFrames, a prop's collision box, a TileSet's tile counts, TileMapLayer.map_to_local
#           and the tiles it holds, texture_origin), the number is read back from the Godot object. Plus what
#           expected.json cannot show: the spec's hash and roll vectors, the corners4 rule, the variant pick,
#           stamps, tile flags, version refusal, unknown kinds, layer kinds and fields, broken references.
# Usage   : python tools/dev.py test     (or --filter test_golden_dotwork.gd)
# Notes   : Never copy expected values into this file: they come from expected.json, written by
#           tools/art/dotwork/assetspec.py; the explicit vectors below are the spec's own (ASSET_MANIFEST.md
#           "Variants" and "Placing tiles"). The golden folder has a .gdignore, so its PNGs are decoded at run time
#           (DotworkAssets.texture), as in a game whose PNGs Godot has not imported yet.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): created with the Godot importer (#307)
# ---------------------------------------------------------------------------
extends GutTest

const Golden = preload("res://tests/golden_util.gd")
const DIR: String = "res://data/golden/dotwork/"
const MANIFEST: String = DIR + "assets/dotwork/golden.assets.json"
const EXPECTED: String = "dotwork/expected.json"
const CHAR_DIR: String = "res://data/golden/character/sprites/"
const TOL: float = 1e-6 # the spec's tolerance (expected.json rounds to 6 decimals)
const FLOAT32_TOL: float = 1e-4 # numbers Godot keeps as 32-bit floats (Vector2): the spec allows float32 precision

var _expected: Dictionary = {}
var _model: Dictionary = {}


func before_all() -> void:
	_expected = Golden.load_file(EXPECTED)
	_model = DotworkAssets.load_manifest(MANIFEST)


func _check(actual: Variant, expected: Variant, where: String, tol: float = TOL) -> void:
	var d: String = Golden.diff(actual, expected, tol, where)
	assert_eq(d, "", d)


# a resolved path back to the manifest-relative form expected.json uses
func _rel(path: String, model: Dictionary) -> Variant:
	if path == "":
		return null
	var prefix: String = str(model["base"]) + "/"
	return path.substr(prefix.length()) if path.begins_with(prefix) else path


func _assets_of(kind: String) -> Array:
	var out: Array = []
	for key: String in _expected.get("assets", {}):
		if key.begins_with(kind + "/"):
			out.append(key.substr(kind.length() + 1))
	out.sort()
	return out


func _compare_kind(kind: String, shaper: Callable) -> void:
	var names: Array = _assets_of(kind)
	assert_gt(names.size(), 0, "expected.json has no %s" % kind)
	for asset_name: String in names:
		var a: Dictionary = _model.get(kind, {}).get(asset_name, {})
		assert_false(a.is_empty(), "%s/%s was not imported" % [kind, asset_name])
		if not a.is_empty():
			var key: String = "%s/%s" % [kind, asset_name]
			_check(shaper.call(a, _model), _expected["assets"][key], key)


# ---- The importer's objects in the loaded-result shape (spec "Golden fixture and loaded result") ----
# Seconds, rects and the loop flag are read back from the SpriteFrames; the pivot from the node's offset.
func _shape_animated_sprite(a: Dictionary, m: Dictionary) -> Dictionary:
	var sf: SpriteFrames = DotworkAssets.sprite_frames(a)
	var node: AnimatedSprite2D = DotworkAssets.animated_sprite(a)
	var clips: Dictionary = {}
	for clip_name: String in a["clip_order"]:
		var c: Dictionary = a["clips"][clip_name]
		var rects: Array = []
		var seconds: Array = []
		var length: float = 0.0
		for i: int in sf.get_frame_count(clip_name):
			var tex: Texture2D = sf.get_frame_texture(clip_name, i)
			var at: AtlasTexture = tex as AtlasTexture
			var r: Rect2 = at.region if at != null else Rect2(Vector2.ZERO, tex.get_size())
			rects.append([r.position.x, r.position.y, r.size.x, r.size.y])
			var s: float = sf.get_frame_duration(clip_name, i) / sf.get_animation_speed(clip_name)
			seconds.append(s)
			length += s
		var offset: Vector2 = node.get_meta("dotwork_offsets")[clip_name]
		var pivot: Vector2 = Vector2(float(c["frame_size"][0]), float(c["frame_size"][1])) / 2.0 - offset
		clips[clip_name] = {"frames": sf.get_frame_count(clip_name), "rects": rects, "seconds": seconds,
				"length": length, "loop": sf.get_animation_loop(clip_name), "pivot": [pivot.x, pivot.y],
				"texture": _rel(c["sheet"], m)}
	node.free()
	return {"blend": a["blend"], "clips": clips, "directions": a["directions"]}


# The pivot and collision boxes read back from the Sprite2D and its StaticBody2D.
func _shape_sprite(a: Dictionary, _m: Dictionary) -> Dictionary:
	var node: Sprite2D = DotworkAssets.sprite(a)
	var size: Vector2 = node.texture.get_size()
	var pivot: Vector2 = size / 2.0 - node.offset
	var coll: Array = []
	var body: Node = node.get_node_or_null("Body")
	if body != null:
		for shape: CollisionShape2D in body.get_children():
			var rs: Vector2 = (shape.shape as RectangleShape2D).size
			var tl: Vector2 = shape.position + pivot - rs / 2.0
			coll.append([tl.x, tl.y, rs.x, rs.y])
	node.free()
	return {"size": [size.x, size.y], "pivot": [pivot.x, pivot.y], "collision": coll}


func _shape_icon(a: Dictionary, _m: Dictionary) -> Dictionary:
	var sizes: Array = []
	for s: Dictionary in a["sizes"]:
		sizes.append(s["size"])
	return {"sizes": sizes}


func _shape_portrait(a: Dictionary, _m: Dictionary) -> Dictionary:
	var names: Array = []
	for e: Dictionary in a["expressions"]:
		names.append(e["name"])
	names.sort()
	return {"size": a["size"], "expressions": names, "animation": a["animation"]}


# Tile size, shape, tile counts read back from the TileSet; terrains and keys from the parsed tiles (the TileSet
# carries no terrain sets: cells arrive resolved).
func _shape_tileset(a: Dictionary, _m: Dictionary) -> Dictionary:
	var ts: TileSet = DotworkAssets.tile_set(a)
	var tiles: int = 0
	var coll: int = 0
	var anim: int = 0
	for si: int in ts.get_source_count():
		var src: TileSetAtlasSource = ts.get_source(ts.get_source_id(si)) as TileSetAtlasSource
		for ti: int in src.get_tiles_count():
			var at: Vector2i = src.get_tile_id(ti)
			tiles += 1
			if ts.get_physics_layers_count() > 0 and src.get_tile_data(at, 0).get_collision_polygons_count(0) > 0:
				coll += 1
			if src.get_tile_animation_frames_count(at) > 1:
				anim += 1
	var masks: Dictionary = {}
	var seen: Dictionary = {}
	for t: Dictionary in a["tile_list"]:
		if t["terrain"] == null:
			continue
		var tk: String = "%d/%d" % [t["terrain_set"], t["terrain"]]
		var v: Variant = t["mask"] if t["mask"] != null else DotworkManifest.corner_list(t["corners"])
		if not masks.has(tk):
			masks[tk] = []
			seen[tk] = {}
		if not (seen[tk] as Dictionary).has(str(v)):
			seen[tk][str(v)] = true
			masks[tk].append(v)
	for tk: String in masks:
		(masks[tk] as Array).sort() # numbers, or corner lists (Godot sorts arrays element by element)
	var terrains: Dictionary = {}
	for sid: int in a["terrain_sets"]:
		for tid: int in a["terrain_sets"][sid]["terrains"]:
			terrains["%d/%d" % [sid, tid]] = a["terrain_sets"][sid]["terrains"][tid]["name"]
	var shape: String = "isometric" if ts.tile_shape == TileSet.TILE_SHAPE_ISOMETRIC else "square"
	return {"tile_size": [ts.tile_size.x, ts.tile_size.y], "shape": shape, "tiles": tiles, "collision_tiles": coll,
			"animated_tiles": anim, "terrains": terrains, "masks": masks}


# Counts, placed cells and centres read back from the TileMapLayers map_node built: the tile each layer holds at a
# cell, its centre from map_to_local, the image's top-left from the centre less (region / 2 + texture_origin).
func _shape_map(a: Dictionary, _m: Dictionary) -> Dictionary:
	var root: Node2D = DotworkAssets.map_node(a)
	var layers: Dictionary = {}
	var terrain: Dictionary = {}
	var placed: Dictionary = {}
	var first: TileMapLayer = null
	for L: Dictionary in a["layers"]:
		var layer: TileMapLayer = root.get_node(NodePath(str(L["name"])))
		if first == null:
			first = layer
		layers[L["name"]] = layer.get_used_cells().size()
		if L["kind"] == "terrain":
			var cells: Array = []
			for c: Dictionary in L["cells"]:
				cells.append([c["x"], c["y"], c["key"], c["tile"]])
			terrain[L["name"]] = cells
		var drawn: Array = []
		for c: Dictionary in L["cells"]:
			if c["tile"] == null:
				continue
			var at: Vector2i = Vector2i(c["x"], c["y"])
			var src_id: int = layer.get_cell_source_id(at)
			var ac: Vector2i = layer.get_cell_atlas_coords(at)
			var src: TileSetAtlasSource = layer.tile_set.get_source(src_id) as TileSetAtlasSource
			var td: TileData = layer.get_cell_tile_data(at)
			var centre: Vector2 = layer.map_to_local(at)
			var tl: Vector2 = centre - Vector2(src.texture_region_size) / 2.0 - Vector2(td.texture_origin)
			drawn.append([at.x, at.y, src_id, ac.x, ac.y, tl.x, tl.y])
		placed[L["name"]] = drawn
	var centres: Array = []
	for y: int in int(a["size"][1]):
		for x: int in int(a["size"][0]):
			var p: Vector2 = first.map_to_local(Vector2i(x, y))
			centres.append([x, y, p.x, p.y])
	var objects: Array = []
	for o: Dictionary in a["objects"]:
		objects.append([o["asset"], o["x"], o["y"]])
	var shape: String = "isometric" if first.tile_set.tile_shape == TileSet.TILE_SHAPE_ISOMETRIC else "square"
	var tsz: Vector2i = first.tile_set.tile_size
	root.free()
	return {"size": a["size"], "shape": shape, "tile_size": [tsz.x, tsz.y], "layers": layers, "terrain": terrain,
			"placed": placed, "centres": centres, "objects": objects}


func _shape_font(a: Dictionary, _m: Dictionary) -> Dictionary:
	var sample: Dictionary = a["chars"].get(65, a["char_list"][0] if not (a["char_list"] as Array).is_empty() else {})
	return {"line_height": a["line_height"], "base": a["base"], "chars": (a["char_list"] as Array).size(),
			"pages": (a["pages"] as Array).size(), "sample": sample.get("raw")}


func _shape_ui_kit(a: Dictionary, _m: Dictionary) -> Dictionary:
	var parts: Dictionary = {}
	for part_name: String in a["parts"]:
		var p: Dictionary = a["parts"][part_name]
		parts[part_name] = {"size": p["size"], "margins": p["margins"], "hotspot": p["hotspot"]}
	return {"parts": parts}


func _shape_background(a: Dictionary, _m: Dictionary) -> Dictionary:
	var layers: Array = []
	for L: Dictionary in a["layers"]:
		layers.append([L["size"][0], L["size"][1], L["velocity"][0], L["velocity"][1], L["repeat"]])
	return {"layers": layers}


func _shape_kind(a: Dictionary, _m: Dictionary) -> Dictionary:
	return {"kind": a["kind"]}


# ---- Every asset of expected.json -------------------------------------------------------------
func test_fixture_loaded() -> void:
	assert_false(_expected.is_empty(), "res://data/golden/%s is missing (it ships from the kit)" % EXPECTED)
	assert_false(_model.has("error"), str(_model.get("error", "")))
	assert_eq(_model.get("pack"), _expected.get("pack"))
	assert_eq(_model.get("version"), _expected.get("version"))


func test_every_expected_kind_is_compared() -> void:
	var known: PackedStringArray = DotworkManifest.PARSE_ORDER
	var n: int = 0
	for key: String in _expected.get("assets", {}):
		assert_true(known.has(key.get_slice("/", 0)), "%s: no comparison for this kind" % key)
		n += 1
	var imported: int = 0
	for a: Dictionary in _model.get("order", []):
		assert_true((_expected["assets"] as Dictionary).has("%s/%s" % [a["kind"], a["name"]]),
				"%s/%s is not in expected.json" % [a["kind"], a["name"]])
		imported += 1
	assert_eq(imported + (_model.get("skipped", []) as Array).size(), n, "every asset imported or skipped once")


func test_golden_pack_loads_without_warnings() -> void:
	assert_eq(_model.get("warnings", ["no model"]), [], "warnings")
	assert_eq(_model.get("skipped", ["no model"]), [], "no kind of the golden pack is skipped")
	assert_eq(_model.get("problems", ["no model"]), [], "problems")


func test_animated_sprites() -> void:
	_compare_kind("animated_sprite", _shape_animated_sprite)


func test_sprites() -> void:
	_compare_kind("sprite", _shape_sprite)


func test_icons_and_portraits() -> void:
	_compare_kind("icon", _shape_icon)
	_compare_kind("portrait", _shape_portrait)


func test_tilesets() -> void:
	_compare_kind("tileset", _shape_tileset)


func test_maps() -> void:
	_compare_kind("map", _shape_map)


func test_fonts_and_ui_kits() -> void:
	_compare_kind("font", _shape_font)
	_compare_kind("ui_kit", _shape_ui_kit)


func test_extra_kinds() -> void:
	_compare_kind("background", _shape_background)
	for kind: String in ["particles", "transition", "normal_map", "image"]:
		_compare_kind(kind, _shape_kind)


func test_golden_files_ship_and_fit() -> void:
	var problems: PackedStringArray = DotworkAssets.verify(_model)
	assert_eq(problems.size(), 0, "\n".join(problems))
	assert_gt((_model.get("files", []) as Array).size(), 40, "the golden pack names its PNGs and the .fnt")


# ---- A sheet render_sprites.py rendered from the golden rigged character (#290, the /make-character 2D route) ----
func test_rendered_character_loads_as_its_expected_json() -> void:
	var want: Dictionary = Golden.load_file("character/sprites/expected.json")
	assert_false(want.is_empty(), "res://data/golden/character/sprites/expected.json is missing")
	var m: Dictionary = DotworkAssets.load_manifest(CHAR_DIR + "dotwork/character.assets.json")
	assert_false(m.has("error"), str(m.get("error", "")))
	if m.has("error"):
		return
	assert_eq(m["warnings"], [], "warnings")
	var n: int = 0
	for key: String in want.get("assets", {}):
		var kind: String = key.get_slice("/", 0)
		var a: Dictionary = m.get(kind, {}).get(key.get_slice("/", 1), {})
		assert_false(a.is_empty(), key + " was not imported")
		if kind == "animated_sprite" and not a.is_empty():
			# a pivot of 36.94 comes back from a float32 Vector2 offset: compare at float32 precision (spec)
			_check(_shape_animated_sprite(a, m), want["assets"][key], key, FLOAT32_TOL)
		n += 1
	assert_gt(n, 0, "the rendered character has an asset")
	var problems: PackedStringArray = DotworkAssets.verify(m)
	assert_eq(problems.size(), 0, "\n".join(problems))


# ---- Timing: each frame's own duration, not fps ----------------------------------
func test_frame_durations_and_holds() -> void:
	var clip: Dictionary = _model["animated_sprite"]["hero"]["clips"]["walk_s"] # holds 1 1 2 1 at 8 fps
	var sf: SpriteFrames = DotworkAssets.sprite_frames(_model["animated_sprite"]["hero"])
	assert_almost_eq(sf.get_frame_duration("walk_s", 2) / sf.get_animation_speed("walk_s"), 0.25, TOL,
			"the held frame shows twice as long")
	# t = 0.1 0.2 0.3 0.45 0.55 0.65 (wraps to 0.025): frame index 2 is the held one (0.25 to 0.5)
	var steps: Array = [[0.1, 0], [0.2, 1], [0.3, 2], [0.45, 2], [0.55, 3], [0.025, 0]]
	for s: Array in steps:
		assert_eq(DotworkManifest.frame_at(clip, s[0]), s[1], "walk_s at t=%s" % s[0])
	assert_false(sf.get_animation_loop("attack_e"), "an attack plays once")


func test_play_switches_pivot() -> void:
	var hero: AnimatedSprite2D = DotworkAssets.animated_sprite(_model["animated_sprite"]["hero"])
	add_child_autofree(hero)
	DotworkAssets.play(hero, "walk_e")
	assert_eq(hero.animation, &"walk_e")
	assert_eq(hero.offset, Vector2(0, -12), "feet on the node: 16x24 frames, pivot [8, 24]")
	var spark: AnimatedSprite2D = DotworkAssets.animated_sprite(_model["animated_sprite"]["fx_spark"])
	add_child_autofree(spark)
	assert_eq(spark.offset, Vector2.ZERO, "an effect is centred")
	assert_eq((spark.material as CanvasItemMaterial).blend_mode, CanvasItemMaterial.BLEND_MODE_ADD, "blend add")


# ---- Autotile rule ----------------------------------------------------------------------
func test_canon_folds_256_masks_into_47() -> void:
	var seen: Dictionary = {}
	for m: int in 256:
		seen[DotworkManifest.canon(m)] = true
	assert_eq(seen.size(), 47)
	assert_eq(DotworkManifest.canon(255), 255)
	assert_eq(DotworkManifest.canon(2), 0, "NE alone does not count")


func test_sides4_keeps_side_bits_only() -> void:
	var painted: Dictionary = DotworkManifest.painted_set([[1, 1], [1, 0], [2, 0], [2, 1]])
	assert_eq(DotworkManifest.cell_mask(painted, 1, 1, "sides4"), 1 + 4, "N and E; the NE corner is dropped")
	assert_eq(DotworkManifest.cell_mask(painted, 1, 1), 1 + 2 + 4, "blob: NE counts, both sides are set")


func test_corners4_on_a_3x3_block() -> void:
	var cells: Array = []
	for y: int in 3:
		for x: int in 3:
			cells.append([x, y])
	var painted: Dictionary = DotworkManifest.painted_set(cells)
	assert_eq(DotworkManifest.cell_mask(painted, 1, 1, "corners4"), 170, "the centre holds all four corners")
	assert_eq(DotworkManifest.cell_mask(painted, 0, 0, "corners4"), 8, "top-left cell: SE only")
	assert_eq(DotworkManifest.cell_mask(painted, 1, 0, "corners4"), 40, "top-middle cell: SE and SW")
	assert_eq(DotworkManifest.cell_mask(painted, 2, 2, "corners4"), 128, "bottom-right cell: NW only")


func test_corners4_tile_keys_by_shape() -> void:
	var sq: Dictionary = {"terrain": 1, "corners": {"top_left": 1, "top_right": 0, "bottom_right": 1, "bottom_left": 0}}
	assert_eq(DotworkManifest.terrain_key(sq, "corners4", "square"), 128 + 8)
	var iso: Dictionary = {"terrain": 1, "corners": {"top": 0, "right": 1, "bottom": 0, "left": 1}}
	assert_eq(DotworkManifest.terrain_key(iso, "corners4", "isometric"), 2 + 32)
	assert_eq(DotworkManifest.terrain_key(iso, "corners4", "square"), -1, "iso corner names are not a square tile's")
	assert_eq(DotworkManifest.terrain_key({"terrain": 1, "mask": 255}, "blob47", "square"), 255)
	var ts: Dictionary = _model["tileset"]["meadow"]
	assert_false(DotworkManifest.candidates(ts, 0, 0, 170).is_empty(), "meadow grass has an all-corners tile")
	assert_true(DotworkManifest.candidates(ts, 0, 0, 1).is_empty(), "no grass tile answers to a side bit")


# ---- The variant pick: the spec's vectors (ASSET_MANIFEST.md "Variants: the probability pick") ----
func test_hash32_vectors() -> void:
	assert_eq(DotworkManifest.hash32(0), 1800329511)
	assert_eq(DotworkManifest.hash32(1), 3028713910)
	assert_eq(DotworkManifest.hash32(0xFFFFFFFF), 4268016002)
	assert_eq(DotworkManifest.hash32(0x100000000), DotworkManifest.hash32(0), "the input is taken modulo 2^32")
	for k: int in [0, 1, 7, 0xFFFF, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF]:
		var h: int = DotworkManifest.hash32(k)
		assert_true(h >= 0 and h <= 0xFFFFFFFF, "hash32(%d) is a 32-bit value" % k)


func test_cell_roll_vectors() -> void:
	assert_almost_eq(DotworkManifest.cell_roll(0, 0, 0), 0.169182, TOL)
	assert_almost_eq(DotworkManifest.cell_roll(3, 1, 1), 0.765973, TOL)
	assert_almost_eq(DotworkManifest.cell_roll(3, 2, 1), 0.531301, TOL)
	assert_almost_eq(DotworkManifest.cell_roll(-1, -1, 0), 0.992978, TOL, "coordinates wrap at 16 bits")
	assert_eq(DotworkManifest.cell_roll(0x10003, 1, 1), DotworkManifest.cell_roll(3, 1, 1), "wrapped x rolls the same")


func test_pick_walks_weights_in_order() -> void:
	var c: Array = [[1.0, "base"], [0.6, "variant"]]
	assert_eq(DotworkManifest.pick_variant(c, 0.0), "base")
	assert_eq(DotworkManifest.pick_variant(c, 0.624), "base") # 0.624 * 1.6 = 0.9984 < 1
	assert_eq(DotworkManifest.pick_variant(c, 0.626), "variant")
	assert_eq(DotworkManifest.pick_variant(c, 0.999999), "variant")
	assert_eq(DotworkManifest.pick_variant([[0, "a"], [0, "b"]], 0.5), "a", "all weights 0: the first")
	assert_eq(DotworkManifest.pick_variant([[0, "a"], [1, "b"]], 0.0), "b", "weight 0 is never picked")


# the yard's two full path cells: (3, 1) rolls the variant, (3, 2) the base tile (the layer is index 1); Godot's
# own terrain solver would roll its own dice here, the importer sets the spec's pick
func test_yard_path_variant_is_the_pick() -> void:
	var layer: Dictionary = _model["map"]["yard"]["layers"][1]
	assert_eq(layer["name"], "Path")
	assert_eq(layer["index"], 1, "0-based layer index")
	var by: Dictionary = {}
	for c: Dictionary in layer["cells"]:
		by[Vector2i(c["x"], c["y"])] = c
	assert_eq(by[Vector2i(3, 1)]["key"], 255)
	assert_eq(by[Vector2i(3, 2)]["key"], 255)
	assert_eq((by[Vector2i(3, 1)]["variants"] as Array).size(), 2, "two tiles share key 255")
	assert_ne(by[Vector2i(3, 1)]["tile"][1], by[Vector2i(3, 2)]["tile"][1],
			"the two full cells pick different variants")
	var root: Node2D = DotworkAssets.map_node(_model["map"]["yard"])
	var path: TileMapLayer = root.get_node("Path")
	assert_eq(path.get_cell_atlas_coords(Vector2i(3, 1)), Vector2i(by[Vector2i(3, 1)]["tile"][1],
			by[Vector2i(3, 1)]["tile"][2]), "the TileMapLayer holds the pick")
	root.free()


# ---- Placing tiles: isometric centres and origins ----------------------------------------------
func test_isometric_centres_are_godots() -> void:
	var c: Callable = func(x: int, y: int) -> Vector2: return DotworkManifest.cell_centre("isometric", x, y, [16, 8])
	assert_eq(c.call(0, 0), Vector2(8, 4))
	assert_eq(c.call(1, 0), Vector2(16, 8))
	assert_eq(c.call(0, 1), Vector2(0, 8))
	assert_eq(c.call(3, 2), Vector2(16, 24))
	assert_eq(DotworkManifest.cell_centre("square", 2, 3, [8, 8]), Vector2(20, 28))
	var layer: TileMapLayer = TileMapLayer.new()
	layer.tile_set = DotworkAssets.tile_set(_model["tileset"]["iso_isle"])
	for p: Vector2i in [Vector2i(0, 0), Vector2i(1, 0), Vector2i(0, 1), Vector2i(3, 2), Vector2i(-2, 5)]:
		assert_eq(layer.map_to_local(p), DotworkManifest.cell_centre("isometric", p.x, p.y, [16, 8]),
				"map_to_local %s" % p)
	layer.free()
	assert_eq((_model["map"]["isle"]["centres"] as Array).size(), 12, "every cell of the 4x3 isle, y outer then x")


func test_tile_origin_and_texture_origin() -> void:
	var atlas: Dictionary = {"tile_size": [16, 12]}
	assert_eq(DotworkManifest.tile_origin({}, atlas), Vector2(8, 6), "the atlas tile's centre")
	assert_eq(DotworkManifest.tile_origin({"origin": [8, 8]}, atlas), Vector2(8, 8))
	assert_eq(DotworkAssets.texture_origin({"origin": [8, 8]}, atlas), Vector2i(0, 2), "lifted 2 px above centred")
	var blocks: Dictionary = _model["map"]["isle"]["layers"][2]
	assert_eq(blocks["name"], "Blocks")
	assert_eq(blocks["cells"][0]["top"], blocks["cells"][0]["cy"] - 8, "a raised block: its origin on the centre")


# ---- Stamps: a layer of [x, y, stamp] expands into the stamp's tiles ----------------------------
func test_stamps_layer_expands() -> void:
	var ts: Dictionary = _model["tileset"]["ground_yard"]
	assert_eq((ts["stamp_list"] as Array).size(), 1)
	assert_eq(ts["stamp_list"][0]["name"], "door")
	var cells: Array = DotworkManifest.expand_stamps(ts, [[7, 0, 0]])
	assert_eq(cells.size(), 2, "a 1x2 door is two tiles")
	assert_eq([cells[0]["x"], cells[0]["y"], cells[1]["x"], cells[1]["y"]], [7, 0, 7, 1])
	assert_eq(cells[0]["tile"], ts["stamp_list"][0]["tiles"][0])
	assert_eq(cells[1]["stamp"], 0)
	var fixtures: Dictionary = _model["map"]["yard"]["layers"][4]
	assert_eq(fixtures["kind"], "stamps")
	assert_eq(fixtures["count"], 2, "a stamps layer counts its expanded tiles")
	var fake: Dictionary = {"stamp_list": [{"index": 0, "size": [2, 2],
			"tiles": [[0, 0, 0], [0, 1, 0], [0, 0, 1], [0, 1, 1]]}]}
	var four: Array = DotworkManifest.expand_stamps(fake, [[3, 5, 0]])
	assert_eq([four[1]["x"], four[1]["y"], four[2]["x"], four[2]["y"], four[3]["x"], four[3]["y"]], [4, 5, 3, 6, 4, 6])


# ---- Tile flags: the manifest's bits as TileMapLayer alternative ids ----------------------------
func test_tile_flags_to_alternatives() -> void:
	assert_eq(DotworkAssets.flags_to_alternative(0), 0)
	assert_eq(DotworkAssets.flags_to_alternative(1), TileSetAtlasSource.TRANSFORM_FLIP_H)
	assert_eq(DotworkAssets.flags_to_alternative(2), TileSetAtlasSource.TRANSFORM_FLIP_V)
	assert_eq(DotworkAssets.flags_to_alternative(7), TileSetAtlasSource.TRANSFORM_FLIP_H
			| TileSetAtlasSource.TRANSFORM_FLIP_V | TileSetAtlasSource.TRANSFORM_TRANSPOSE)


# ---- Fonts, UI, the extra kinds as Godot objects ---------------------------------------------
func test_font_loads_as_a_fontfile() -> void:
	var f: FontFile = DotworkAssets.font(_model["font"]["tiny"])
	assert_not_null(f, "the .fnt loads (FontFile.load_bitmap_font)")
	if f != null:
		assert_eq(int(f.get_height()), int(_model["font"]["tiny"]["line_height"]), "line height")


func test_ui_and_extra_kinds_build() -> void:
	var np: NinePatchRect = DotworkAssets.nine_patch(_model["ui_kit"]["windows"], "ui_window_plain")
	assert_not_null(np.texture)
	assert_eq(np.patch_margin_left, 3)
	np.free()
	var bg: Node2D = DotworkAssets.background(_model["background"]["hills"])
	assert_eq(bg.get_child_count(), 2)
	assert_eq((bg.get_child(1) as Sprite2D).texture_repeat, CanvasItem.TEXTURE_REPEAT_ENABLED, "repeat x wraps")
	bg.free()
	var lit: CanvasTexture = DotworkAssets.lit_texture(_model["normal_map"]["spr_crate_n"])
	assert_not_null(lit.diffuse_texture, "the lit target")
	assert_not_null(lit.normal_texture, "its normal map")
	var p: Dictionary = _model["particles"]["vfx_embers_particles"]
	assert_not_null(DotworkAssets.texture(p["texture"]), "particles texture")
	assert_eq(int(p["emitter"]["amount"]), 12)
	assert_not_null(DotworkAssets.texture(_model["transition"]["transition_wipe"]["image"]))
	assert_not_null(DotworkAssets.texture(_model["image"]["logo_golden"]["image"]))


func test_prop_on_the_map_stands_on_its_feet() -> void:
	var root: Node2D = DotworkAssets.map_node(_model["map"]["yard"])
	var crate: Sprite2D = root.get_node("Props/crate")
	assert_eq(crate.position, Vector2(12, 40), "the pivot on the object's point")
	assert_eq(crate.offset, Vector2(0, -8), "16x16 with pivot [8, 16]")
	root.free()


# ---- Version, kinds, fields, references ------------------------------------------------------
func _doc(fields: Dictionary = {}) -> Dictionary:
	var d: Dictionary = {"format": "dotwork-assets", "version": "1.0.0", "pack": "t", "base": "..", "assets": []}
	d.merge(fields, true)
	return d


func test_refuses_another_major() -> void:
	var m: Dictionary = DotworkManifest.parse(_doc({"version": "2.0.0"}), "res://assets/dotwork/t.assets.json")
	assert_true(m.has("error"))
	assert_string_contains(str(m.get("error", "")), "2.0.0")
	assert_string_contains(str(m.get("error", "")), "major 1")
	assert_false(DotworkManifest.parse(_doc({"version": "1.7.3"}), "res://a/t.assets.json").has("error"),
			"a newer minor loads")
	assert_true(DotworkManifest.parse(_doc({"format": "other"}), "res://a/t.assets.json").has("error"))


func test_unknown_kind_and_field_warn_once() -> void:
	var m: Dictionary = DotworkManifest.parse(_doc({"assets": [
		{"kind": "hologram", "name": "a"}, {"kind": "hologram", "name": "b"},
		{"kind": "icon", "name": "i", "sizes": [{"size": 8, "image": "art/i.png"}], "sparkle": true},
		{"kind": "icon", "name": "j", "sizes": [], "sparkle": 2}]}), "res://assets/dotwork/t.assets.json")
	assert_eq((m["warnings"] as Array).size(), 2, "\n".join(m["warnings"]))
	assert_eq((m["skipped"] as Array).size(), 2)
	assert_true(m["icon"].has("i") and m["icon"].has("j"), "known kinds still load")
	assert_eq(m["icon"]["i"]["sizes"][0]["image"], "res://assets/art/i.png", "paths resolve through base")


func test_broken_references_are_problems() -> void:
	var m: Dictionary = DotworkManifest.parse(_doc({"assets": [
		{"kind": "map", "name": "m", "tileset": "nope", "size": [2, 2], "tile_size": [8, 8], "layers": [],
		"objects": [{"asset": "ghost", "x": 0, "y": 0}]}]}), "res://assets/dotwork/t.assets.json")
	assert_eq((m["problems"] as Array).size(), 2, "\n".join(m["problems"]))
	assert_eq(DotworkAssets.verify(m).size(), 2, "verify() names them")


func test_paths_never_leave_the_game_folder() -> void:
	var m: Dictionary = DotworkManifest.parse(_doc({"assets": [
		{"kind": "icon", "name": "i", "sizes": [{"size": 8, "image": "../../x.png"}]}]}), "res://assets/dotwork/t.json")
	assert_true(m.has("error"), "a path with .. is refused")
	assert_eq(DotworkManifest.normalize("res://a/b/../c/./d.png"), "res://a/c/d.png")
	assert_eq(DotworkManifest.normalize("res://../x.png"), "", "above the root")
	assert_eq(DotworkManifest.dirname("res://assets/dotwork/t.json"), "res://assets/dotwork")


func test_missing_file_is_a_problem() -> void:
	var m: Dictionary = DotworkManifest.parse(_doc({"assets": [
		{"kind": "icon", "name": "i", "sizes": [{"size": 8, "image": "art/nowhere.png"}]}]}),
		"res://assets/dotwork/t.assets.json")
	var problems: PackedStringArray = DotworkAssets.verify(m)
	assert_eq(problems.size(), 1)
	assert_string_contains(problems[0] if problems.size() > 0 else "", "missing")


func _tiny_tileset(fields: Dictionary = {}) -> Dictionary:
	var t: Dictionary = {"kind": "tileset", "name": "t", "tile_size": [8, 8], "shape": "square", "terrain_sets": [],
			"atlases": [{"id": 0, "name": "a", "role": "base", "image": "art/a.png", "tile_size": [8, 8],
			"columns": 1, "rows": 1, "tiles": [{"col": 0, "row": 0}]}]}
	t.merge(fields, true)
	return t


func test_unknown_layer_kind_warns_once_and_a_bad_stamp_is_a_problem() -> void:
	var m: Dictionary = DotworkManifest.parse(_doc({"assets": [
		_tiny_tileset({"stamps": [{"name": "s", "size": [1, 1], "solid": false, "tiles": [[0, 0, 0]]}]}),
		{"kind": "map", "name": "m", "tileset": "t", "size": [4, 4], "tile_size": [8, 8], "layers": [
			{"name": "A", "kind": "hologram", "cells": [[0, 0]]}, {"name": "B", "kind": "hologram", "cells": [[1, 1]]},
			{"name": "C", "kind": "stamps", "cells": [[0, 0, 0], [2, 2, 7]]}]}]}), "res://assets/dotwork/t.assets.json")
	assert_eq((m["warnings"] as Array).size(), 1, "\n".join(m["warnings"]))
	assert_string_contains(str(m["warnings"][0]) if (m["warnings"] as Array).size() > 0 else "", "hologram")
	assert_eq(m["map"]["m"]["layers"][0]["count"], 0)
	assert_eq(m["map"]["m"]["layers"][2]["count"], 1, "the known stamp is placed")
	assert_eq((m["problems"] as Array).size(), 1, "\n".join(m["problems"]))
	assert_string_contains(str(m["problems"][0]) if (m["problems"] as Array).size() > 0 else "", "stamp 7")
	assert_eq(m["map"]["m"]["layers"][2]["cells"][0]["left"], 0.0)
	assert_eq(m["map"]["m"]["layers"][2]["cells"][0]["top"], 0.0)


func test_missing_terrain_tile_warns_once_per_layer() -> void:
	var m: Dictionary = DotworkManifest.parse(_doc({"assets": [
		_tiny_tileset({"terrain_sets": [{"id": 0, "mode": "sides4",
				"terrains": [{"id": 0, "name": "x", "color": "#fff"}]}],
				"atlases": [{"id": 0, "name": "a", "role": "base", "image": "art/a.png", "tile_size": [8, 8],
				"columns": 1, "rows": 1, "tiles": [{"col": 0, "row": 0, "terrain_set": 0, "terrain": 0, "mask": 0}]}]}),
		{"kind": "map", "name": "m", "tileset": "t", "size": [4, 4], "tile_size": [8, 8], "layers": [
			{"name": "T", "kind": "terrain", "terrain_set": 0, "terrain": 0, "cells": [[0, 0], [1, 0], [3, 3]]}]}]}),
		"res://assets/dotwork/t.assets.json")
	assert_eq((m["warnings"] as Array).size(), 1, "\n".join(m["warnings"]))
	var L: Dictionary = m["map"]["m"]["layers"][0]
	assert_eq((L["cells"] as Array).size(), 3, "every painted cell is listed")
	assert_eq(L["count"], 1, "only the lone cell (mask 0) has a tile")
	assert_null(L["cells"][0]["tile"], "(0,0) needs E, which no tile has")

# {{FOOTER}}
