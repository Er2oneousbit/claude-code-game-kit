# ---------------------------------------------------------------------------
# dotwork_assets.gd
# Purpose : The Godot importer for Dotwork's asset manifest (tools/art/dotwork/ASSET_MANIFEST.md): finds the game's
#           packs (assets/dotwork/*.assets.json), checks every file they name, and turns a parsed manifest
#           (DotworkManifest) into Godot objects: SpriteFrames with each frame's own duration, AnimatedSprite2D with
#           the clip's pivot, Sprite2D props with their collision box and contact shadow, a TileSet per tileset and a
#           Node2D of TileMapLayers per map with the spec's terrain pick and placement, FontFile, NinePatchRect, and
#           the extra kinds as textures plus data (a lit CanvasTexture for a normal map).
# Usage   : var art: Dictionary = DotworkAssets.load_all()      # {"models": [...], "problems": [...]}
#           var model: Dictionary = DotworkAssets.load_manifest("res://assets/dotwork/hero.assets.json")
#           var hero: AnimatedSprite2D = DotworkAssets.animated_sprite(model["animated_sprite"]["hero"])
#           DotworkAssets.play(hero, "walk_s")                  # the clip and its pivot (offset)
#           add_child(DotworkAssets.map_node(model["map"]["yard"]))
#           var crate: Sprite2D = DotworkAssets.sprite(model["sprite"]["crate"])   # feet on its position
#           DotworkAssets.verify(model)                         # missing files, wrong sizes, broken references
# Notes   : Godot also gets Dotwork's own resources (SpriteFrames .tres, TileSet .tres, map scenes); this importer
#           is what a pack without them needs (a 3D model rendered to sprites by tools/blender/render_sprites.py
#           --manifest) and draws a map with the same tiles as every other engine. Textures: the imported resource
#           when Godot imported the PNG (an exported game has only that), else the PNG decoded at run time (a folder
#           with .gdignore, such as the golden fixture). Filtering is the project's (nearest); every node built
#           here sets TEXTURE_FILTER_NEAREST too. The TileSet carries no terrain sets (cells come resolved; Dotwork's
#           own TileSet .tres is the one for painting terrain by hand in the editor). An exported game needs
#           assets/dotwork/* in the preset's include_filter (the kit's presets have it).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): created, the Godot importer (#307)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   find(dir): every *.assets.json in dir, sorted;  load_manifest(path): read -> JSON -> DotworkManifest.parse
#   verify(model): model problems + every listed file exists, a PNG has the listed size, every rect fits in it
#   sprite_frames(asset): per clip an animation at speed = fps; a frame = the sheet rect (AtlasTexture) with
#     relative duration = seconds * fps, so each frame shows exactly its seconds
#   tile_set(ts): TileSet (square, or isometric diamond-down) of the map cell size; per atlas a TileSetAtlasSource
#     with id = the atlas id, its region size, tiles with probability, texture_origin from origin, collision
#     polygons, the surface custom data, animation columns
#   map_node(map): per layer a TileMapLayer; each placed cell set_cell(cell, atlas, (col, row), flags); props under
#     a y-sorted Props node
class_name DotworkAssets
extends RefCounted

# ---- Tunables ----------------------------------------------------------------
const DIR: String = "res://assets/dotwork" # <assets_dir>/dotwork in a Godot game
const LOG_CHANNEL: String = "dotwork"

static var _textures: Dictionary = {} # path -> Texture2D, so a sheet is decoded once


# ---- Finding and loading ----------------------------------------------------------
static func find(dir: String = DIR) -> PackedStringArray:
	var out: PackedStringArray = []
	if not DirAccess.dir_exists_absolute(dir):
		return out
	for name: String in DirAccess.get_files_at(dir):
		if name.ends_with(DotworkManifest.SUFFIX):
			out.append(dir.path_join(name))
	out.sort()
	return out


## The parsed manifest, or {"error": message} (unreadable, not JSON, another major, a missing field).
static func load_manifest(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {"error": "%s: no such file" % path}
	var json: JSON = JSON.new()
	if json.parse(FileAccess.get_file_as_string(path)) != OK:
		return {"error": "%s: not JSON (line %d: %s)" % [path, json.get_error_line(), json.get_error_message()]}
	return DotworkManifest.parse(json.data, path)


## Every pack of the game: {"models": [model, ...], "problems": [line, ...]}; warnings and problems are logged.
static func load_all(dir: String = DIR) -> Dictionary:
	var out: Dictionary = {"models": [], "problems": []}
	for path: String in find(dir):
		var model: Dictionary = load_manifest(path)
		if model.has("error"):
			out["problems"].append(model["error"])
			_warn(model["error"])
			continue
		for w: String in model["warnings"]:
			_warn(w)
		for p: String in model["problems"]:
			out["problems"].append(p)
			_warn(p)
		out["models"].append(model)
	return out


## Through the game's Log autoload when it runs, else push_warning: looked up at run time, so this script also
## compiles in a `godot --script` tool run, which has no autoloads.
static func _warn(msg: String) -> void:
	var tree: SceneTree = Engine.get_main_loop() as SceneTree
	var logger: Node = tree.root.get_node_or_null("Log") if tree != null else null
	if logger != null and logger.has_method("warn"):
		logger.call("warn", LOG_CHANNEL, msg)
	else:
		push_warning("[%s] %s" % [LOG_CHANNEL, msg])


## The first asset of that kind and name across the loaded packs ({} when none): names are unique per pack only.
static func find_asset(models: Array, kind: String, name: String) -> Dictionary:
	for m: Dictionary in models:
		if (m.get(kind, {}) as Dictionary).has(name):
			return m[kind][name]
	return {}


# ---- Textures ------------------------------------------------------------------------
## The texture at a resolved manifest path: Godot's imported resource when there is one, else the PNG decoded now.
## null when neither loads.
static func texture(path: String) -> Texture2D:
	if _textures.has(path):
		return _textures[path]
	var tex: Texture2D = null
	if ResourceLoader.exists(path, "Texture2D"):
		tex = load(path) as Texture2D
	elif FileAccess.file_exists(path):
		var img: Image = Image.new()
		if img.load_png_from_buffer(FileAccess.get_file_as_bytes(path)) == OK:
			tex = ImageTexture.create_from_image(img)
	if tex != null:
		_textures[path] = tex
	return tex


## Drops the texture cache (after a pack is rebuilt while the game runs).
static func clear_cache() -> void:
	_textures.clear()


static func _exists(path: String) -> bool:
	return FileAccess.file_exists(path) or ResourceLoader.exists(path)


## Problem lines for a model: its broken references, missing files, PNGs of the wrong size, rects outside them.
static func verify(model: Dictionary) -> PackedStringArray:
	var out: PackedStringArray = []
	if model.has("error"):
		out.append(model["error"])
		return out
	for p: String in model["problems"]:
		out.append(p)
	for f: Dictionary in model["files"]:
		var path: String = f["path"]
		if not _exists(path):
			out.append("%s: %s names %s, which is missing" % [model["path"], f["where"], f["rel"]])
			continue
		if not path.ends_with(".png"):
			continue
		var tex: Texture2D = texture(path)
		if tex == null:
			out.append("%s: %s: %s does not load as an image" % [model["path"], f["where"], f["rel"]])
			continue
		var w: int = tex.get_width()
		var h: int = tex.get_height()
		if f["size"] != null and (w != int(f["size"][0]) or h != int(f["size"][1])):
			out.append("%s: %s: %s is %dx%d, the manifest says %dx%d" % [model["path"], f["where"], f["rel"], w, h,
					int(f["size"][0]), int(f["size"][1])])
		for r: Array in f["rects"]:
			if float(r[0]) < 0 or float(r[1]) < 0 or float(r[0]) + float(r[2]) > w or float(r[1]) + float(r[3]) > h:
				out.append("%s: %s: rect %s is outside %s (%dx%d)" % [model["path"], r[4], r.slice(0, 4), f["rel"],
						w, h])
	return out


# ---- Animated sprites ----------------------------------------------------------------
## A clip's frame as a texture: its rect in the sheet, or its own PNG (the whole file, or a rect of it).
static func frame_texture(clip: Dictionary, frame: Dictionary) -> Texture2D:
	var r: Array = frame["rect"]
	var region: Rect2 = Rect2(float(r[0]), float(r[1]), float(r[2]), float(r[3]))
	var src: Texture2D = texture(clip["sheet"] if clip["sheet"] != "" else frame["file"])
	if src == null:
		return null
	if clip["sheet"] == "" and region == Rect2(Vector2.ZERO, src.get_size()):
		return src
	var at: AtlasTexture = AtlasTexture.new()
	at.atlas = src
	at.region = region
	return at


## SpriteFrames: one animation per clip, in the manifest's order, speed = fps, each frame's relative duration =
## seconds * fps (Godot shows a frame duration / speed seconds), so holds come out exact.
static func sprite_frames(asset: Dictionary) -> SpriteFrames:
	var sf: SpriteFrames = SpriteFrames.new()
	if sf.has_animation("default"):
		sf.remove_animation("default")
	for name: String in asset["clip_order"]:
		var clip: Dictionary = asset["clips"][name]
		var fps: float = float(clip["fps"])
		var speed: float = fps if fps > 0.0 else 1.0
		sf.add_animation(name)
		sf.set_animation_speed(name, speed)
		sf.set_animation_loop(name, bool(clip["loop"]))
		for f: Dictionary in clip["frames"]:
			sf.add_frame(name, frame_texture(clip, f), float(f["duration"]) * speed)
	return sf


## The AnimatedSprite2D offset that puts a clip's pivot on the node's position (centered frames).
static func clip_offset(clip: Dictionary) -> Vector2:
	return Vector2(float(clip["frame_size"][0]) / 2.0 - float(clip["pivot"][0]),
			float(clip["frame_size"][1]) / 2.0 - float(clip["pivot"][1]))


## An AnimatedSprite2D of the asset, showing its first clip; play() switches clips with their pivots.
static func animated_sprite(asset: Dictionary) -> AnimatedSprite2D:
	var node: AnimatedSprite2D = AnimatedSprite2D.new()
	node.name = str(asset["name"])
	node.sprite_frames = sprite_frames(asset)
	node.centered = true
	node.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	var offsets: Dictionary = {}
	for name: String in asset["clip_order"]:
		offsets[name] = clip_offset(asset["clips"][name])
	node.set_meta("dotwork_offsets", offsets)
	if asset["blend"] == "add":
		var mat: CanvasItemMaterial = CanvasItemMaterial.new()
		mat.blend_mode = CanvasItemMaterial.BLEND_MODE_ADD
		node.material = mat
	if not (asset["clip_order"] as Array).is_empty():
		node.animation = asset["clip_order"][0]
		node.offset = offsets[node.animation]
	return node


## Plays a clip with its own pivot. keep: the clip already playing goes on (a walk that keeps its direction).
static func play(node: AnimatedSprite2D, clip: String, keep: bool = true) -> void:
	if keep and node.animation == clip and node.is_playing():
		return
	var offsets: Dictionary = node.get_meta("dotwork_offsets", {})
	node.offset = offsets.get(clip, node.offset)
	node.play(clip)


# ---- Sprites (props, enemies) --------------------------------------------------------
## A Sprite2D with its pivot on the node's position, a Shadow child behind it, and a StaticBody2D "Body" with one
## RectangleShape2D per collision rect (one-way rects stay one-way).
static func sprite(asset: Dictionary) -> Sprite2D:
	var node: Sprite2D = Sprite2D.new()
	node.name = str(asset["name"])
	node.texture = texture(asset["image"])
	node.centered = true
	node.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	var size: Vector2 = Vector2(float(asset["size"][0]), float(asset["size"][1]))
	var pivot: Vector2 = Vector2(float(asset["pivot"][0]), float(asset["pivot"][1]))
	node.offset = size / 2.0 - pivot
	if asset["shadow"] != null:
		var sh: Sprite2D = Sprite2D.new()
		sh.name = "Shadow"
		sh.texture = texture(asset["shadow"]["image"])
		sh.position = Vector2(float(asset["shadow"]["offset"][0]), float(asset["shadow"]["offset"][1]))
		sh.show_behind_parent = true
		sh.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
		node.add_child(sh)
	if not (asset["collision"] as Array).is_empty():
		var body: StaticBody2D = StaticBody2D.new()
		body.name = "Body"
		node.add_child(body)
		for c: Dictionary in asset["collision"]:
			var r: Array = c["rect"]
			var shape: CollisionShape2D = CollisionShape2D.new()
			var rect: RectangleShape2D = RectangleShape2D.new()
			rect.size = Vector2(float(r[2]), float(r[3]))
			shape.shape = rect
			shape.position = Vector2(float(r[0]) + float(r[2]) / 2.0, float(r[1]) + float(r[3]) / 2.0) - pivot
			shape.one_way_collision = bool(c["one_way"])
			body.add_child(shape)
	return node


# ---- Tiles ---------------------------------------------------------------------------
## The texture_origin that puts a tile's origin (its image point drawn on the cell centre) on the cell centre:
## Godot draws the region centred, moved up by texture_origin (Dotwork's writer: origin = region / 2 + texture_origin).
static func texture_origin(tile: Dictionary, atlas: Dictionary) -> Vector2i:
	var o: Vector2 = DotworkManifest.tile_origin(tile, atlas)
	return Vector2i(roundi(o.x - float(atlas["tile_size"][0]) / 2.0), roundi(o.y - float(atlas["tile_size"][1]) / 2.0))


## A TileSet of a manifest tileset: the map cell size and shape, one TileSetAtlasSource per atlas (source id = atlas
## id), every tile with its probability, origin, collision (physics layer 0), surface (custom data) and animation.
static func tile_set(ts: Dictionary) -> TileSet:
	var out: TileSet = TileSet.new()
	var cell: Vector2 = Vector2(float(ts["tile_size"][0]), float(ts["tile_size"][1]))
	out.tile_size = Vector2i(cell)
	if ts["shape"] == "isometric":
		out.tile_shape = TileSet.TILE_SHAPE_ISOMETRIC
		out.tile_layout = TileSet.TILE_LAYOUT_DIAMOND_DOWN
	var physics: bool = false
	for t: Dictionary in ts["tile_list"]:
		physics = physics or not (t["collision"] as Array).is_empty()
	if physics:
		out.add_physics_layer()
	var custom: String = str(ts["custom_data"]) if ts["custom_data"] != null else ""
	if custom != "":
		out.add_custom_data_layer()
		out.set_custom_data_layer_name(0, custom)
		out.set_custom_data_layer_type(0, TYPE_STRING)
	for atlas: Dictionary in ts["atlases"]:
		var src: TileSetAtlasSource = TileSetAtlasSource.new()
		src.texture = texture(atlas["image"])
		src.texture_region_size = Vector2i(int(atlas["tile_size"][0]), int(atlas["tile_size"][1]))
		out.add_source(src, int(atlas["id"]))
		for t: Dictionary in ts["tile_list"]:
			if t["atlas"] != atlas["id"]:
				continue
			var at: Vector2i = Vector2i(int(t["col"]), int(t["row"]))
			var frames: int = int(t["anim"]["frames"]) if typeof(t["anim"]) == TYPE_DICTIONARY else 1
			if src.texture == null or not src.has_room_for_tile(at, Vector2i.ONE, frames, Vector2i.ZERO, frames):
				continue # a missing atlas or a slot taken: verify() and the model's problems name it
			src.create_tile(at)
			if frames > 1:
				src.set_tile_animation_columns(at, frames)
				src.set_tile_animation_frames_count(at, frames)
				src.set_tile_animation_speed(at, float(t["anim"]["fps"]))
			var td: TileData = src.get_tile_data(at, 0)
			td.probability = float(t["probability"])
			td.texture_origin = texture_origin(t, atlas)
			if custom != "" and t["surface"] != null:
				td.set_custom_data(custom, str(t["surface"]))
			var i: int = 0
			for c: Dictionary in t["collision"]:
				var r: Array = c["rect"]
				var x0: float = float(r[0]) - cell.x / 2.0 # rects are in tile pixels; polygons centre-relative
				var y0: float = float(r[1]) - cell.y / 2.0
				var x1: float = x0 + float(r[2])
				var y1: float = y0 + float(r[3])
				td.add_collision_polygon(0)
				td.set_collision_polygon_points(0, i, PackedVector2Array([Vector2(x0, y0), Vector2(x1, y0),
						Vector2(x1, y1), Vector2(x0, y1)]))
				td.set_collision_polygon_one_way(0, i, bool(c["one_way"]))
				i += 1
	return out


## A map cell's flags (1 flip h, 2 flip v, 4 transpose) as a TileMapLayer alternative id.
static func flags_to_alternative(flags: int) -> int:
	var alt: int = 0
	if flags & DotworkManifest.FLIP_H:
		alt |= TileSetAtlasSource.TRANSFORM_FLIP_H
	if flags & DotworkManifest.FLIP_V:
		alt |= TileSetAtlasSource.TRANSFORM_FLIP_V
	if flags & DotworkManifest.TRANSPOSE:
		alt |= TileSetAtlasSource.TRANSFORM_TRANSPOSE
	return alt


## A Node2D named after the map: one TileMapLayer per manifest layer (drawn first to last, cells already resolved by
## DotworkManifest: terrain picked, stamps expanded), and the objects as sprites under a y-sorted "Props" node (each
## object already names its sprite asset). tiles: a TileSet to share between maps, else one is built.
static func map_node(map: Dictionary, tiles: TileSet = null) -> Node2D:
	var root: Node2D = Node2D.new()
	root.name = str(map["name"])
	if (map["tileset"] as Dictionary).is_empty():
		return root
	var ts: TileSet = tiles if tiles != null else tile_set(map["tileset"])
	for L: Dictionary in map["layers"]:
		var layer: TileMapLayer = TileMapLayer.new()
		layer.name = str(L["name"])
		layer.tile_set = ts
		layer.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
		layer.modulate.a = float(L["opacity"])
		# on a diamond grid a taller tile overdraws the one above it: sort cells by their screen y
		layer.y_sort_enabled = map["shape"] == "isometric"
		for c: Dictionary in L["cells"]:
			if c["tile"] == null:
				continue
			var t: Array = c["tile"]
			layer.set_cell(Vector2i(int(c["x"]), int(c["y"])), int(t[0]), Vector2i(int(t[1]), int(t[2])),
					flags_to_alternative(int(c.get("flags", 0))))
		root.add_child(layer)
	if not (map["objects"] as Array).is_empty():
		var props: Node2D = Node2D.new()
		props.name = "Props"
		props.y_sort_enabled = true
		root.add_child(props)
		for o: Dictionary in map["objects"]:
			if (o["sprite"] as Dictionary).is_empty():
				continue
			var s: Sprite2D = sprite(o["sprite"])
			s.position = Vector2(float(o["x"]), float(o["y"]))
			props.add_child(s)
	return root


# ---- Fonts and UI --------------------------------------------------------------------
## The BMFont: Godot's imported FontFile when the .fnt was imported, else loaded from the file now. null on failure.
static func font(asset: Dictionary) -> FontFile:
	var path: String = asset["file"]
	if ResourceLoader.exists(path, "FontFile"):
		return load(path) as FontFile
	var f: FontFile = FontFile.new()
	if f.load_bitmap_font(path) != OK:
		return null
	return f


## A NinePatchRect of a UI kit part with its margins (left, top, right, bottom), drawn 1:1.
static func nine_patch(kit: Dictionary, part_name: String) -> NinePatchRect:
	var part: Dictionary = kit["parts"].get(part_name, {})
	var node: NinePatchRect = NinePatchRect.new()
	if part.is_empty():
		return node
	node.name = part_name
	node.texture = texture(part["image"])
	node.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	if part["margins"] != null:
		var m: Array = part["margins"]
		node.patch_margin_left = int(m[0])
		node.patch_margin_top = int(m[1])
		node.patch_margin_right = int(m[2])
		node.patch_margin_bottom = int(m[3])
	node.size = Vector2(float(part["size"][0]), float(part["size"][1]))
	return node


# ---- The extra kinds (textures plus data; the node that uses them is the game's) ------------------
## A background as a Node2D of Sprite2D layers, first to last, each texture repeating when its layer repeats
## (scroll a layer by moving its region_rect by velocity * delta: the layer's data stays in the manifest).
static func background(asset: Dictionary) -> Node2D:
	var root: Node2D = Node2D.new()
	root.name = str(asset["name"])
	var i: int = 0
	for L: Dictionary in asset["layers"]:
		var s: Sprite2D = Sprite2D.new()
		s.name = str(L["name"]) if L["name"] != null else "Layer%d" % i
		s.texture = texture(L["image"])
		s.centered = false
		s.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
		s.scale = Vector2.ONE * float(L["scale"])
		if L["repeat"] != "none":
			s.texture_repeat = CanvasItem.TEXTURE_REPEAT_ENABLED
			s.region_enabled = true
			s.region_rect = Rect2(Vector2.ZERO, Vector2(float(L["size"][0]), float(L["size"][1])))
		s.set_meta("dotwork_layer", L)
		root.add_child(s)
		i += 1
	return root


## A normal map's target lit by it: a CanvasTexture (diffuse = the target, normal = the map) for a Sprite2D under
## a Light2D. Dotwork's normal maps are OpenGL style (green up), what Godot expects.
static func lit_texture(asset: Dictionary) -> CanvasTexture:
	var ct: CanvasTexture = CanvasTexture.new()
	ct.diffuse_texture = texture(asset["target"])
	ct.normal_texture = texture(asset["image"])
	return ct
