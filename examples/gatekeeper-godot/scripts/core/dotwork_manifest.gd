# ---------------------------------------------------------------------------
# dotwork_manifest.gd
# Purpose : Reads a Dotwork asset manifest (<pack>.assets.json, spec in tools/art/dotwork/ASSET_MANIFEST.md) into
#           plain Dictionaries: sprites, animated sprites with per-frame durations, icons, portraits, BMFont fonts,
#           UI kits, tilesets and maps whose terrain layers are resolved with the spec's autotile rules (blob47,
#           sides4, corners4) and variant pick (cell_roll), stamps layers expanded into tiles, every placed cell with
#           its draw position, plus the extra kinds (background, particles, transition, normal_map, image) as data.
#           Engine-free: no textures or nodes, so tests run it headless; DotworkAssets builds the Godot objects.
# Usage   : var model: Dictionary = DotworkManifest.parse(doc, "res://assets/dotwork/town.assets.json")
#           if model.has("error"): ...                         # a broken manifest (format, major, missing field)
#           model["animated_sprite"]["hero"]["clips"]["walk_s"]["frames"][0]["duration"]   # seconds
#           model["map"]["yard"]["layers"][1]["cells"][0]     # {x, y, key, tile = [atlas, col, row], cx, cy, left, top}
#           model["map"]["yard"]["centres"]                    # [{x, y, cx, cy}]: every cell's centre in map pixels
#           DotworkManifest.cell_roll(3, 1, 1)                 # 0.765973 (the spec's vector)
#           DotworkManifest.cell_centre("isometric", 1, 0, [16, 8])   # Vector2(16, 8)
#           model["warnings"]  skipped kinds and fields (print them)   model["problems"]  broken references (fail)
#           model["files"]     every file the manifest names, with the size it must have (DotworkAssets.verify)
# Notes   : Version rule: reads every 1.x.y manifest (spec 1.1.0; 1.0.0 packs still load), refuses another major
#           with a message naming both. Unknown kinds, layer kinds and fields: one warning each, skipped. Paths come
#           out resolved from the manifest's folder: join(dirname(manifest), base, path), "res://" kept. Godot's
#           JSON gives every number as a float: int() before any bit operation. A terrain cell's tile is the
#           spec's pick (the same tile in every engine, and in Dotwork's own Godot map scenes since #307), not
#           Godot's terrain solver's own roll. The port follows engines/love2d's dotwork_manifest.lua and
#           tools/art/dotwork/assetspec.py (the reference) line for line.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): created, the Godot importer (#307)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   parse(doc, path): check format and major version -> base = normalize(dirname(path) / doc.base)
#     for each kind in dependency order (sprite, animated_sprite, icon, portrait, font, ui_kit, tileset, map,
#     then the extra kinds): convert every asset (required fields checked, unknown fields warned, paths resolved)
#   tileset: terrain tiles filed by terrain and key (mask, or the sum of the corner bits holding the tile's own
#     terrain) as [weight, tile] candidates in atlas order (atlases by id, tiles in list order)
#   map terrain layer: painted = its cells; key = cell_mask(painted, x, y, mode); tile = pick(candidates of key,
#     cell_roll(x, y, layer_index))
#   map stamps layer: each [x, y, stamp] -> the stamp's tiles, tile j at (x + j % w, y + j / w)
#   every placed cell: centre = cell_centre(shape, x, y, map tile_size); left, top = centre - tile origin
class_name DotworkManifest
extends RefCounted

# ---- Tunables (the spec's constants) -------------------------------------------
const FORMAT: String = "dotwork-assets"
const MAJOR: int = 1 # the spec major this importer reads (spec 1.1.0; 1.0.0 loads too)
const SUFFIX: String = ".assets.json"
const CORE_KINDS: PackedStringArray = ["animated_sprite", "sprite", "icon", "portrait", "tileset", "map", "font",
		"ui_kit"]
const EXTRA_KINDS: PackedStringArray = ["background", "particles", "transition", "normal_map", "image"]
# parse order: a portrait names an animated_sprite, a map names a tileset and sprite objects
const PARSE_ORDER: PackedStringArray = ["sprite", "animated_sprite", "icon", "portrait", "font", "ui_kit", "tileset",
		"map", "background", "particles", "transition", "normal_map", "image"]
# N NE E SE S SW W NW, y down: bit b is NB8[b]
const NB8: Array[Vector2i] = [Vector2i(0, -1), Vector2i(1, -1), Vector2i(1, 0), Vector2i(1, 1), Vector2i(0, 1),
		Vector2i(-1, 1), Vector2i(-1, 0), Vector2i(-1, -1)]
const SIDES_ONLY: int = 1 | 4 | 16 | 64 # N, E, S, W
const CORNERS_ONLY: int = 2 | 8 | 32 | 128 # NE, SE, SW, NW
# a corners4 tile's corner names per shape and the mask bit of the cell across that corner (spec "Autotiling"):
# a diamond's top corner touches the cell up the screen, which is NW in map coordinates
const CORNER_BITS: Dictionary = {
	"square": {"top_left": 128, "top_right": 2, "bottom_right": 8, "bottom_left": 32},
	"isometric": {"top": 128, "right": 2, "bottom": 8, "left": 32},
}
const FLIP_H: int = 1
const FLIP_V: int = 2
const TRANSPOSE: int = 4
const M32: int = 0xFFFFFFFF
const TWO_32: float = 4294967296.0

# Fields each kind may carry (spec 1.1.0). Others are warned about once and ignored.
const KNOWN: Dictionary = {
	"background": ["kind", "name", "role", "layers", "godot"],
	"bg_layer": ["name", "image", "size", "velocity", "repeat", "wobble_px", "scale"],
	"particles": ["kind", "name", "texture", "emitter", "godot"],
	"transition": ["kind", "name", "image", "size", "transition", "godot"],
	"normal_map": ["kind", "name", "image", "size", "target", "convention", "godot"],
	"image": ["kind", "name", "role", "image", "size", "pivot", "godot"],
	"animated_sprite": ["kind", "name", "role", "blend", "clips", "directions", "godot"],
	"sprite": ["kind", "name", "role", "image", "size", "pivot", "content_rect", "collision", "shadow", "godot"],
	"icon": ["kind", "name", "sizes"],
	"portrait": ["kind", "name", "size", "expressions", "animation"],
	"tileset": ["kind", "name", "tile_size", "shape", "terrain_sets", "atlases", "stamps", "custom_data", "godot"],
	"map": ["kind", "name", "tileset", "size", "tile_size", "layers", "objects", "godot"],
	"font": ["kind", "name", "file", "pages", "line_height", "base", "scale", "tint", "chars", "kerning", "license"],
	"ui_kit": ["kind", "name", "role", "parts", "godot"],
	"clip": ["name", "fps", "loop", "holds", "frame_size", "pivot", "sheet", "frames", "length"],
	"tile": ["col", "row", "terrain_set", "terrain", "mask", "corners", "probability", "surface", "collision", "anim",
			"origin"],
}

# ---- parse state (one instance per parse() call) ----------------------------------
var _model: Dictionary = {}
var _path: String = ""
var _base: String = ""
var _error: String = "" # the first fatal problem; parse() returns {"error": ...} when set
var _warned: Dictionary = {}
var _files_by_path: Dictionary = {}


# ---- Autotiling (the spec's rules, ported) -----------------------------------------
## A corner bit only counts when both sides next to it are set: 256 raw masks fold into the 47 blob masks.
static func canon(m: int) -> int:
	for c: int in [1, 3, 5, 7]: # NE, SE, SW, NW
		if not ((m >> ((c + 7) % 8)) & 1 and (m >> ((c + 1) % 8)) & 1):
			m &= ~(1 << c)
	return m


## painted: a set of Vector2i cells of one terrain (painted_set). mode: "blob47" (the canon mask), "sides4" (N E S W
## bits) or "corners4" (the corner bits of the canon mask: a corner is the terrain when all four cells meeting there
## are painted).
static func cell_mask(painted: Dictionary, x: int, y: int, mode: String = "blob47") -> int:
	var m: int = 0
	for b: int in NB8.size():
		if painted.has(Vector2i(x, y) + NB8[b]):
			m |= 1 << b
	if mode == "sides4":
		return m & SIDES_ONLY
	if mode == "corners4":
		return canon(m) & CORNERS_ONLY
	return canon(m)


static func painted_set(cells: Array) -> Dictionary:
	var out: Dictionary = {}
	for c: Array in cells:
		out[Vector2i(int(c[0]), int(c[1]))] = true
	return out


## The key a tileset tile answers to: its mask (blob47, sides4), or the sum of the corner bits whose corner holds the
## tile's own terrain (corners4, corner names by shape). -1 when it has neither, or the corner names are not the
## shape's.
static func terrain_key(tile: Dictionary, mode: String, shape: String) -> int:
	if mode != "corners4":
		return int(tile["mask"]) if tile.get("mask") != null else -1
	var corners: Variant = tile.get("corners")
	if typeof(corners) != TYPE_DICTIONARY:
		return -1
	var names: Dictionary = CORNER_BITS.get(shape, CORNER_BITS["square"])
	var cd: Dictionary = corners
	if cd.size() != names.size():
		return -1
	var key: int = 0
	for name: String in names:
		if not cd.has(name):
			return -1
		if tile.get("terrain") != null and int(cd[name]) == int(tile["terrain"]):
			key += int(names[name])
	return key


## A corners4 tile's corners as a list in sorted corner-name order (the spec's comparable form).
static func corner_list(corners: Dictionary) -> Array:
	var names: Array = corners.keys()
	names.sort()
	var out: Array = []
	for name: String in names:
		out.append(int(corners[name]))
	return out


# ---- The variant pick (spec "Variants: the probability pick") ----------------------------
## Bob Jenkins' 32-bit integer hash: only shifts, adds and xors, every step masked to 32 bits (GDScript ints are
## 64-bit, so no step overflows).
static func hash32(k: int) -> int:
	k &= M32
	k = (k + 0x7ED55D16 + (k << 12)) & M32
	k = (k ^ 0xC761C23C ^ (k >> 19)) & M32
	k = (k + 0x165667B1 + (k << 5)) & M32
	k = ((k + 0xD3A2646C) ^ (k << 9)) & M32
	k = (k + 0xFD7046C5 + (k << 3)) & M32
	return (k ^ 0xB55A4F09 ^ (k >> 16)) & M32


## The roll in [0, 1) that picks cell (x, y)'s variant on the layer at layer_index (0-based: the layer's position in
## the map's layers list). Coordinates wrap at 16 bits, so negative cells roll too.
static func cell_roll(x: int, y: int, layer_index: int) -> float:
	return float(hash32(hash32(((x & 0xFFFF) << 16) | (y & 0xFFFF)) + layer_index)) / TWO_32


## cands: [[weight, value], ...] in atlas order. The value whose weight span holds roll * total; the first when every
## weight is 0 (weight 0 is never picked otherwise).
static func pick_variant(cands: Array, roll: float) -> Variant:
	var total: float = 0.0
	for c: Array in cands:
		total += float(c[0])
	if total <= 0.0:
		return cands[0][1]
	var u: float = roll * total
	for c: Array in cands:
		u -= float(c[0])
		if u < 0.0:
			return c[1]
	return cands[cands.size() - 1][1]


# ---- Placing tiles (spec "Placing tiles") ------------------------------------------------
## The centre of cell (x, y) in map pixels, y down: squares in rows; isometric diamonds in Godot's diamond-down
## layout (x runs down-right, y down-left, cell (0, 0) at (w/2, h/2)). TileMapLayer.map_to_local gives the same.
static func cell_centre(shape: String, x: int, y: int, tile_size: Array) -> Vector2:
	var w: float = float(tile_size[0])
	var h: float = float(tile_size[1])
	if shape == "isometric":
		return Vector2((x - y + 1) * w / 2.0, (x + y + 1) * h / 2.0)
	return Vector2((x + 0.5) * w, (y + 0.5) * h)


## The image point drawn on the cell centre: the tile's own origin, else the atlas tile's centre (the atlas's tile
## size, which can be taller than the map cell: iso blocks).
static func tile_origin(tile: Dictionary, atlas: Dictionary) -> Vector2:
	if tile.get("origin") != null:
		return Vector2(float(tile["origin"][0]), float(tile["origin"][1]))
	return Vector2(float(atlas["tile_size"][0]) / 2.0, float(atlas["tile_size"][1]) / 2.0)


static func tile_key(atlas: int, col: int, row: int) -> String:
	return "%d,%d,%d" % [atlas, col, row]


# ---- Paths ----------------------------------------------------------------------
## "res://a/b/../c" -> "res://a/c". "" when ".." climbs above the root.
static func normalize(path: String) -> String:
	var scheme: String = ""
	var rest: String = path.replace("\\", "/")
	var at: int = rest.find("://")
	if at >= 0:
		scheme = rest.substr(0, at + 3)
		rest = rest.substr(at + 3)
	var lead: String = "/" if rest.begins_with("/") else ""
	var out: PackedStringArray = []
	for part: String in rest.split("/", false):
		if part == "..":
			if out.is_empty():
				return ""
			out.remove_at(out.size() - 1)
		elif part != ".":
			out.append(part)
	return scheme + lead + "/".join(out)


static func dirname(path: String) -> String:
	var i: int = path.rfind("/")
	if i < 0:
		return "."
	if i > 0 and path[i - 1] == "/": # "res://x.json": the folder is "res://"
		return path.substr(0, i + 1)
	return path.substr(0, i)


## A manifest path must be relative, forward slashes, no "..", no drive (spec "Where it lives").
static func safe_rel(p: Variant) -> bool:
	if typeof(p) != TYPE_STRING:
		return false
	var s: String = p
	if s == "" or s.contains("\\") or s.begins_with("/") or s.contains("://"):
		return false
	if s.length() > 1 and s[1] == ":":
		return false
	return not ("/" + s + "/").contains("/../")


# ---- Timing ---------------------------------------------------------------------
## The frame index (0-based) showing at time t (seconds) of a clip, from the frames' own durations.
static func frame_at(clip: Dictionary, t: float) -> int:
	var starts: Array = clip["starts"]
	var frames: Array = clip["frames"]
	for i: int in starts.size():
		if t < float(starts[i]) + float(frames[i]["duration"]):
			return i
	return maxi(0, frames.size() - 1)


# ---- The document ---------------------------------------------------------------------
## doc: the decoded JSON; path: the manifest's path (res:// or any path FileAccess reads).
## Returns the model, or {"error": message} for a manifest that cannot load.
static func parse(doc: Variant, path: String) -> Dictionary:
	var p: DotworkManifest = DotworkManifest.new()
	return p._parse(doc, path)


## "" when the header is fine, else the message (format, MAJOR.MINOR.PATCH, another major named with ours).
static func check_header(doc: Variant, path: String) -> String:
	if typeof(doc) != TYPE_DICTIONARY or (doc as Dictionary).get("format") != FORMAT:
		var fmt: Variant = (doc as Dictionary).get("format") if typeof(doc) == TYPE_DICTIONARY else null
		return "%s: not a Dotwork asset manifest (format is %s, expected %s)" % [path, fmt, FORMAT]
	var version: String = str((doc as Dictionary).get("version", ""))
	var re: RegEx = RegEx.create_from_string("^(\\d+)\\.\\d+\\.\\d+$")
	var m: RegExMatch = re.search(version)
	if m == null:
		return "%s: version %s is not MAJOR.MINOR.PATCH" % [path, version]
	var major: int = int(m.get_string(1))
	if major != MAJOR:
		return ("%s: manifest version %s is major %d; this importer reads major %d (%d.x.y): update the importer " +
				"or rebuild the pack") % [path, version, major, MAJOR, MAJOR]
	return ""


func _parse(doc: Variant, path: String) -> Dictionary:
	var head: String = check_header(doc, path)
	if head != "":
		return {"error": head}
	var d: Dictionary = doc
	_path = path
	_model = {"path": path, "pack": d.get("pack"), "version": d.get("version"), "warnings": [], "problems": [],
			"files": [], "order": [], "skipped": []}
	for k: String in PARSE_ORDER:
		_model[k] = {}
	var base_field: Variant = d.get("base")
	_base = normalize(dirname(path) + "/" + (str(base_field) if base_field != null else "."))
	_model["base"] = _base
	if typeof(d.get("assets")) != TYPE_ARRAY:
		return {"error": "%s: document: field 'assets' is missing" % path}
	var by_kind: Dictionary = {}
	var skipped: Dictionary = {}
	var i: int = 0
	for a: Variant in d["assets"]:
		i += 1
		if typeof(a) != TYPE_DICTIONARY or typeof((a as Dictionary).get("kind")) != TYPE_STRING \
				or typeof((a as Dictionary).get("name")) != TYPE_STRING:
			return {"error": "%s: asset %d: has no kind or name" % [path, i]}
		var ad: Dictionary = a
		if PARSE_ORDER.has(ad["kind"]):
			if not by_kind.has(ad["kind"]):
				by_kind[ad["kind"]] = []
			by_kind[ad["kind"]].append(ad)
		else:
			if not skipped.has(ad["kind"]):
				skipped[ad["kind"]] = true
				_warn("%s: kind '%s' is not in spec %d.x: skipped" % [path, ad["kind"], MAJOR])
			_model["skipped"].append({"kind": ad["kind"], "name": ad["name"]})
			_extra_files(ad, "%s %s" % [ad["kind"], ad["name"]])
	for kind: String in PARSE_ORDER:
		for a: Dictionary in by_kind.get(kind, []):
			var where: String = "%s %s" % [kind, a["name"]]
			_unknown_fields(a, KNOWN[kind], kind)
			if (_model[kind] as Dictionary).has(a["name"]):
				_fail(where, "two %s assets are named %s" % [kind, a["name"]])
			var obj: Dictionary = call("_convert_" + kind, a, where)
			if _error != "":
				return {"error": _error}
			_model[kind][a["name"]] = obj
			_model["order"].append(obj)
	return _model


# ---- Parsing helpers --------------------------------------------------------------
func _fail(where: String, msg: String) -> void:
	if _error == "":
		_error = "%s: %s: %s" % [_path, where, msg]


func _warn(msg: String) -> void:
	_model["warnings"].append(msg)


func _problem(msg: String) -> void:
	_model["problems"].append("%s: %s" % [_path, msg])


static func _is_num(v: Variant) -> bool:
	return typeof(v) == TYPE_INT or typeof(v) == TYPE_FLOAT


## The field, checked; a default of the right shape (and the first fatal error recorded) when it is wrong.
func _need(t: Dictionary, field: String, kind: String, where: String) -> Variant:
	var v: Variant = t.get(field)
	var ok: bool = false
	match kind:
		"number":
			ok = _is_num(v)
		"string":
			ok = typeof(v) == TYPE_STRING
		"boolean":
			ok = typeof(v) == TYPE_BOOL
		"list":
			ok = typeof(v) == TYPE_ARRAY
		"dict":
			ok = typeof(v) == TYPE_DICTIONARY
		"pair":
			ok = typeof(v) == TYPE_ARRAY and (v as Array).size() >= 2 and _is_num(v[0]) and _is_num(v[1])
		"rect":
			ok = typeof(v) == TYPE_ARRAY and (v as Array).size() >= 4 and _is_num(v[0]) and _is_num(v[1]) \
					and _is_num(v[2]) and _is_num(v[3])
	if ok:
		return v
	_fail(where, "field '%s' is missing or not a %s" % [field, kind])
	match kind:
		"number":
			return 0
		"string":
			return ""
		"boolean":
			return false
		"dict":
			return {}
		"pair":
			return [0, 0]
		"rect":
			return [0, 0, 0, 0]
	return []


func _unknown_fields(t: Dictionary, known: Array, label: String) -> void:
	for field: Variant in t:
		if not known.has(field):
			var key: String = "%s.%s" % [label, field]
			if not _warned.has(key):
				_warned[key] = true
				_warn("%s: %s field '%s' is not in spec %d.x: ignored" % [_path, label, field, MAJOR])


## A manifest path -> a resolved path, and the file listed for DotworkAssets.verify (size, rects inside it).
func _file(rel: Variant, where: String, want_size: Variant = null, rects: Array = []) -> String:
	if not safe_rel(rel):
		_fail(where, "path %s is not a plain relative path" % [rel])
		return ""
	var full: String = normalize(_base + "/" + str(rel))
	if full == "":
		_fail(where, "path %s leaves the game folder" % [rel])
		return ""
	var f: Dictionary = _files_by_path.get(full, {})
	if f.is_empty():
		f = {"path": full, "rel": rel, "where": where, "size": null, "rects": []}
		_files_by_path[full] = f
		_model["files"].append(f)
	if want_size != null and f["size"] == null:
		f["size"] = [int(want_size[0]), int(want_size[1])]
	for r: Array in rects:
		f["rects"].append([r[0], r[1], r[2], r[3], where])
	return full


static func _pair(p: Variant) -> Array:
	return [p[0], p[1]]


static func _rect(r: Variant) -> Array:
	return [r[0], r[1], r[2], r[3]]


func _collision_list(list: Variant, where: String) -> Array:
	var out: Array = []
	if typeof(list) != TYPE_ARRAY:
		return out
	var i: int = 0
	for s: Variant in list:
		i += 1
		if typeof(s) != TYPE_DICTIONARY:
			_fail(where, "collision %d is not an object" % i)
			continue
		var r: Array = _need(s, "rect", "rect", "%s collision %d" % [where, i])
		out.append({"rect": _rect(r), "one_way": (s as Dictionary).get("one_way") == true})
	return out


# ---- Kinds --------------------------------------------------------------------------
func _convert_sprite(a: Dictionary, where: String) -> Dictionary:
	var size: Array = _pair(_need(a, "size", "pair", where))
	var s: Dictionary = {"kind": "sprite", "name": a["name"], "role": a.get("role"), "size": size,
			"pivot": _pair(_need(a, "pivot", "pair", where)),
			"content_rect": _rect(a["content_rect"]) if a.get("content_rect") != null else null,
			"collision": _collision_list(a.get("collision"), where), "shadow": null}
	s["image"] = _file(_need(a, "image", "string", where), where, size)
	if typeof(a.get("shadow")) == TYPE_DICTIONARY:
		var sh: Dictionary = a["shadow"]
		s["shadow"] = {"image": _file(_need(sh, "image", "string", where + " shadow"), where + " shadow"),
				"offset": _pair(_need(sh, "offset", "pair", where + " shadow"))}
	return s


func _convert_animated_sprite(a: Dictionary, where: String) -> Dictionary:
	var s: Dictionary = {"kind": "animated_sprite", "name": a["name"], "role": a.get("role"),
			"blend": a["blend"] if a.get("blend") != null else "normal", "clips": {}, "clip_order": [],
			"directions": {}}
	var ci: int = 0
	for c: Variant in _need(a, "clips", "list", where):
		ci += 1
		if typeof(c) != TYPE_DICTIONARY:
			_fail(where, "clip %d is not an object" % ci)
			continue
		var cd: Dictionary = c
		var cw: String = "%s clip %s" % [where, cd.get("name", ci)]
		_unknown_fields(cd, KNOWN["clip"], "clip")
		var fs: Array = _pair(_need(cd, "frame_size", "pair", cw))
		var clip: Dictionary = {"name": _need(cd, "name", "string", cw), "fps": _need(cd, "fps", "number", cw),
				"loop": _need(cd, "loop", "boolean", cw), "frame_size": fs,
				"pivot": _pair(_need(cd, "pivot", "pair", cw)), "frames": [], "starts": [], "length": 0.0,
				"sheet": ""}
		if cd.get("sheet") != null:
			clip["sheet"] = _file(cd["sheet"], cw + " sheet")
		var fi: int = 0
		for f: Variant in _need(cd, "frames", "list", cw):
			fi += 1
			var fw: String = "%s frame %d" % [cw, fi]
			if typeof(f) != TYPE_DICTIONARY:
				_fail(fw, "is not an object")
				continue
			var rect: Array = _rect(_need(f, "rect", "rect", fw))
			var duration: float = float(_need(f, "duration", "number", fw))
			var file: String = _file(_need(f, "file", "string", fw), fw, fs, [] if clip["sheet"] != "" else [rect])
			if clip["sheet"] != "":
				_file(cd["sheet"], cw + " sheet", null, [rect])
			clip["starts"].append(clip["length"])
			clip["frames"].append({"file": file, "rect": rect, "duration": duration})
			clip["length"] = float(clip["length"]) + duration
		if (s["clips"] as Dictionary).has(clip["name"]):
			_fail(cw, "two clips are named %s" % clip["name"])
		s["clips"][clip["name"]] = clip
		s["clip_order"].append(clip["name"])
	if typeof(a.get("directions")) == TYPE_DICTIONARY:
		for action: String in a["directions"]:
			s["directions"][action] = {}
			for dir: String in a["directions"][action]:
				var clip_name: Variant = a["directions"][action][dir]
				if not (s["clips"] as Dictionary).has(clip_name):
					_problem("%s: direction %s/%s names clip %s, which it does not have" % [where, action, dir,
							clip_name])
				s["directions"][action][dir] = clip_name
	return s


func _convert_icon(a: Dictionary, where: String) -> Dictionary:
	var s: Dictionary = {"kind": "icon", "name": a["name"], "sizes": [], "by_size": {}}
	var i: int = 0
	for e: Variant in _need(a, "sizes", "list", where):
		i += 1
		var ew: String = "%s size %d" % [where, i]
		if typeof(e) != TYPE_DICTIONARY:
			_fail(ew, "is not an object")
			continue
		var n: int = int(_need(e, "size", "number", ew))
		var img: String = _file(_need(e, "image", "string", ew), "%s size %d" % [where, n], [n, n])
		s["sizes"].append({"size": n, "image": img})
		s["by_size"][n] = img
	(s["sizes"] as Array).sort_custom(func(p: Dictionary, q: Dictionary) -> bool: return p["size"] < q["size"])
	return s


func _convert_portrait(a: Dictionary, where: String) -> Dictionary:
	var size: Array = _pair(_need(a, "size", "pair", where))
	var s: Dictionary = {"kind": "portrait", "name": a["name"], "size": size, "expressions": [], "by_name": {},
			"animation": a.get("animation")}
	var i: int = 0
	for e: Variant in _need(a, "expressions", "list", where):
		i += 1
		if typeof(e) != TYPE_DICTIONARY:
			_fail("%s expression %d" % [where, i], "is not an object")
			continue
		var name: String = _need(e, "name", "string", "%s expression %d" % [where, i])
		var img: String = _file(_need(e, "image", "string", where + " " + name), where + " " + name, size)
		s["expressions"].append({"name": name, "image": img})
		s["by_name"][name] = img
	if s["animation"] != null and not (_model["animated_sprite"] as Dictionary).has(s["animation"]):
		_problem("%s: animation %s is not an animated_sprite in this manifest" % [where, s["animation"]])
	return s


func _convert_font(a: Dictionary, where: String) -> Dictionary:
	var s: Dictionary = {"kind": "font", "name": a["name"], "line_height": _need(a, "line_height", "number", where),
			"base": _need(a, "base", "number", where), "scale": _need(a, "scale", "number", where),
			"tint": _need(a, "tint", "boolean", where), "chars": {}, "char_list": [], "kerning": {}, "pages": [],
			"license": a.get("license")}
	s["file"] = _file(_need(a, "file", "string", where), where + " .fnt")
	var per_page: Dictionary = {}
	var i: int = 0
	for c: Variant in _need(a, "chars", "list", where):
		i += 1
		if typeof(c) != TYPE_ARRAY or (c as Array).size() < 9:
			_fail(where, "char %d is not [id, x, y, w, h, xoffset, yoffset, xadvance, page]" % i)
			continue
		var raw: Array = []
		for k: int in 9:
			raw.append(int(c[k]))
		var row: Dictionary = {"id": raw[0], "x": raw[1], "y": raw[2], "w": raw[3], "h": raw[4], "xoffset": raw[5],
				"yoffset": raw[6], "xadvance": raw[7], "page": raw[8], "raw": raw}
		s["chars"][row["id"]] = row
		s["char_list"].append(row)
		if not per_page.has(row["page"]):
			per_page[row["page"]] = []
		if row["w"] > 0 and row["h"] > 0:
			per_page[row["page"]].append([row["x"], row["y"], row["w"], row["h"]])
	var pi: int = 0
	for p: Variant in _need(a, "pages", "list", where):
		s["pages"].append(_file(p, "%s page %d" % [where, pi], null, per_page.get(pi, [])))
		pi += 1
	if typeof(a.get("kerning")) == TYPE_ARRAY:
		for k: Array in a["kerning"]:
			var first: int = int(k[0])
			if not (s["kerning"] as Dictionary).has(first):
				s["kerning"][first] = {}
			s["kerning"][first][int(k[1])] = int(k[2])
	return s


func _convert_ui_kit(a: Dictionary, where: String) -> Dictionary:
	var s: Dictionary = {"kind": "ui_kit", "name": a["name"], "role": a.get("role"), "parts": {}, "part_order": []}
	var i: int = 0
	for p: Variant in _need(a, "parts", "list", where):
		i += 1
		if typeof(p) != TYPE_DICTIONARY:
			_fail(where, "part %d is not an object" % i)
			continue
		var pd: Dictionary = p
		var pw: String = "%s part %s" % [where, pd.get("name", i)]
		var size: Array = _pair(_need(pd, "size", "pair", pw))
		var part: Dictionary = {"name": _need(pd, "name", "string", pw), "role": pd.get("role"), "size": size,
				"scale": pd["scale"] if pd.get("scale") != null else 1, "state": pd.get("state"),
				"control": pd.get("control"), "glyph": pd.get("glyph"),
				"margins": _rect(pd["margins"]) if pd.get("margins") != null else null,
				"stretch_margin": pd.get("stretch_margin"),
				"hotspot": _pair(pd["hotspot"]) if pd.get("hotspot") != null else null}
		part["image"] = _file(_need(pd, "image", "string", pw), pw, size)
		s["parts"][part["name"]] = part
		s["part_order"].append(part["name"])
	return s


func _convert_tileset(a: Dictionary, where: String) -> Dictionary:
	var s: Dictionary = {"kind": "tileset", "name": a["name"], "tile_size": _pair(_need(a, "tile_size", "pair", where)),
			"shape": _need(a, "shape", "string", where), "terrain_sets": {}, "atlases": [], "atlas_by_id": {},
			"tiles": {}, "tile_list": [], "by_key": {}, "stamps": {}, "stamp_list": [],
			"custom_data": a.get("custom_data")}
	for ts: Variant in _need(a, "terrain_sets", "list", where):
		if typeof(ts) != TYPE_DICTIONARY:
			continue
		var tset: Dictionary = {"id": int(ts.get("id", 0)), "mode": str(ts.get("mode", "blob47")), "terrains": {}}
		for t: Dictionary in ts.get("terrains", []):
			tset["terrains"][int(t.get("id", 0))] = {"id": int(t.get("id", 0)), "name": t.get("name"),
					"color": t.get("color")}
		s["terrain_sets"][tset["id"]] = tset
	var ai: int = 0
	for at: Variant in _need(a, "atlases", "list", where):
		ai += 1
		if typeof(at) != TYPE_DICTIONARY:
			_fail(where, "atlas %d is not an object" % ai)
			continue
		var ad: Dictionary = at
		var aw: String = "%s atlas %s" % [where, ad.get("name", ai)]
		var tsz: Array = _pair(_need(ad, "tile_size", "pair", aw))
		var atlas: Dictionary = {"id": int(_need(ad, "id", "number", aw)), "name": ad.get("name"),
				"role": ad.get("role"), "tile_size": tsz, "columns": int(_need(ad, "columns", "number", aw)),
				"rows": int(_need(ad, "rows", "number", aw))}
		atlas["image"] = _file(_need(ad, "image", "string", aw), aw, null,
				[[0, 0, atlas["columns"] * int(tsz[0]), atlas["rows"] * int(tsz[1])]])
		s["atlases"].append(atlas)
		s["atlas_by_id"][atlas["id"]] = atlas
		for t: Variant in _need(ad, "tiles", "list", aw):
			if typeof(t) != TYPE_DICTIONARY:
				_fail(aw, "a tile is not an object")
				continue
			var td: Dictionary = t
			_unknown_fields(td, KNOWN["tile"], "tile")
			var col: int = int(_need(td, "col", "number", aw))
			var row: int = int(_need(td, "row", "number", aw))
			var tile: Dictionary = {"atlas": atlas["id"], "col": col, "row": row,
					"terrain_set": int(td["terrain_set"]) if td.get("terrain_set") != null else 0,
					"terrain": int(td["terrain"]) if td.get("terrain") != null else null,
					"mask": int(td["mask"]) if td.get("mask") != null else null, "corners": td.get("corners"),
					"probability": float(td["probability"]) if td.get("probability") != null else 1.0,
					"surface": td.get("surface"),
					"collision": _collision_list(td.get("collision"), "%s tile %d,%d" % [aw, col, row]),
					"anim": td.get("anim"), "origin": _pair(td["origin"]) if td.get("origin") != null else null}
			var frames: int = int(tile["anim"]["frames"]) if typeof(tile["anim"]) == TYPE_DICTIONARY else 1
			if col + frames - 1 >= atlas["columns"] or row >= atlas["rows"]:
				_problem("%s: tile %d,%d is outside the %dx%d atlas" % [aw, col, row, atlas["columns"],
						atlas["rows"]])
			s["tiles"][tile_key(atlas["id"], col, row)] = tile
			s["tile_list"].append(tile)
	# terrain tiles filed by "set/terrain" and key as [weight, tile] candidates in atlas order: atlases by id,
	# tiles in list order (the spec's pick walks them in exactly this order)
	var ids: Array = (s["atlas_by_id"] as Dictionary).keys()
	ids.sort()
	for id: int in ids:
		for tile: Dictionary in s["tile_list"]:
			if tile["atlas"] != id or tile["terrain"] == null:
				continue
			var tset: Dictionary = s["terrain_sets"].get(tile["terrain_set"], {})
			var key: int = terrain_key(tile, tset.get("mode", "blob47"), s["shape"])
			if key < 0:
				continue
			var tk: String = "%d/%d" % [tile["terrain_set"], tile["terrain"]]
			if not (s["by_key"] as Dictionary).has(tk):
				s["by_key"][tk] = {}
			if not (s["by_key"][tk] as Dictionary).has(key):
				s["by_key"][tk][key] = []
			s["by_key"][tk][key].append([tile["probability"], tile])
	var si: int = 0
	for st: Variant in (a["stamps"] if typeof(a.get("stamps")) == TYPE_ARRAY else []):
		var sw: String = "%s stamp %s" % [where, (st as Dictionary).get("name", si)]
		var stamp: Dictionary = {"index": si, "name": _need(st, "name", "string", sw),
				"size": _pair(_need(st, "size", "pair", sw)), "solid": (st as Dictionary).get("solid") == true,
				"tiles": []}
		for t: Array in _need(st, "tiles", "list", sw):
			var tt: Array = [int(t[0]), int(t[1]), int(t[2])]
			stamp["tiles"].append(tt)
			if not (s["tiles"] as Dictionary).has(tile_key(tt[0], tt[1], tt[2])):
				_problem("%s names tile %s, which the tileset does not have" % [sw, tile_key(tt[0], tt[1], tt[2])])
		s["stamps"][stamp["name"]] = stamp
		s["stamp_list"].append(stamp) # a map's stamps layer names a stamp by its 0-based index
		si += 1
	return s


## The [weight, tile] candidates of a terrain for a key, in atlas order ([] when no tile answers to it).
static func candidates(tileset: Dictionary, terrain_set: int, terrain: int, key: int) -> Array:
	var by_terrain: Dictionary = tileset["by_key"].get("%d/%d" % [terrain_set, terrain], {})
	return by_terrain.get(key, [])


## Each painted cell of a terrain layer -> {x, y, key, tile: [atlas, col, row] or null, variants}, sorted by y then
## x. key is cell_mask's; the tile is picked among the candidates with that key by probability with
## cell_roll(x, y, layer_index), so every engine picks the same variant; null when no tile has the key.
static func resolve_terrain(tileset: Dictionary, terrain_set: int, terrain: int, cells: Array,
		layer_index: int) -> Array:
	var tset: Dictionary = tileset["terrain_sets"].get(terrain_set, {})
	var mode: String = tset.get("mode", "blob47")
	var painted: Dictionary = painted_set(cells)
	var order: Array = painted.keys()
	order.sort_custom(func(p: Vector2i, q: Vector2i) -> bool: return p.y < q.y or (p.y == q.y and p.x < q.x))
	var out: Array = []
	for c: Vector2i in order: # a cell listed twice paints once (painted is a set)
		var key: int = cell_mask(painted, c.x, c.y, mode)
		var list: Array = candidates(tileset, terrain_set, terrain, key)
		var tile: Variant = null
		if not list.is_empty():
			var t: Dictionary = pick_variant(list, cell_roll(c.x, c.y, layer_index))
			tile = [t["atlas"], t["col"], t["row"]]
		out.append({"x": c.x, "y": c.y, "key": key, "tile": tile, "variants": list, "flags": 0})
	return out


## Each [x, y, stamp] of a stamps layer -> the stamp's tiles as cells {x, y, tile, stamp}, tile j at
## (x + j % w, y + j / w), in the order of the layer's cells. A bad stamp index is skipped (parse() reports it).
static func expand_stamps(tileset: Dictionary, cells: Array) -> Array:
	var out: Array = []
	var stamps: Array = tileset["stamp_list"]
	for c: Array in cells:
		var si: int = int(c[2]) if c.size() > 2 else -1
		if si < 0 or si >= stamps.size():
			continue
		var stamp: Dictionary = stamps[si]
		var sw: int = int(stamp["size"][0])
		var j: int = 0
		for t: Array in stamp["tiles"]:
			out.append({"x": int(c[0]) + j % sw, "y": int(c[1]) + floori(float(j) / float(sw)),
					"tile": [t[0], t[1], t[2]], "stamp": si, "flags": 0})
			j += 1
	return out


## Where a placed cell's image lands: cx, cy (the cell centre) and left, top (the centre less the tile's origin).
static func _place_cell(cell: Dictionary, map: Dictionary, ts: Dictionary) -> void:
	var t: Array = cell["tile"]
	var tile: Dictionary = ts["tiles"].get(tile_key(t[0], t[1], t[2]), {})
	if tile.is_empty():
		return
	var atlas: Dictionary = ts["atlas_by_id"][tile["atlas"]]
	var c: Vector2 = cell_centre(map["shape"], cell["x"], cell["y"], map["tile_size"])
	var o: Vector2 = tile_origin(tile, atlas)
	cell["cx"] = c.x
	cell["cy"] = c.y
	cell["left"] = c.x - o.x
	cell["top"] = c.y - o.y


func _convert_map(a: Dictionary, where: String) -> Dictionary:
	var s: Dictionary = {"kind": "map", "name": a["name"], "tileset_name": _need(a, "tileset", "string", where),
			"size": _pair(_need(a, "size", "pair", where)), "tile_size": _pair(_need(a, "tile_size", "pair", where)),
			"layers": [], "objects": [], "centres": []}
	var ts: Dictionary = _model["tileset"].get(s["tileset_name"], {})
	s["tileset"] = ts
	s["shape"] = ts.get("shape", "square")
	if ts.is_empty():
		_problem("%s: tileset %s is not in this manifest" % [where, s["tileset_name"]])
	var mw: int = int(s["size"][0])
	var mh: int = int(s["size"][1])
	for y: int in mh:
		for x: int in mw:
			var c: Vector2 = cell_centre(s["shape"], x, y, s["tile_size"])
			s["centres"].append({"x": x, "y": y, "cx": c.x, "cy": c.y})
	var li: int = 0
	for L: Variant in _need(a, "layers", "list", where):
		var ld: Dictionary = L if typeof(L) == TYPE_DICTIONARY else {}
		var lw: String = "%s layer %s" % [where, ld.get("name", li)]
		var layer: Dictionary = {"name": _need(ld, "name", "string", lw), "kind": _need(ld, "kind", "string", lw),
				"index": li, "opacity": float(ld["opacity"]) if ld.get("opacity") != null else 1.0, "cells": [],
				"count": 0}
		var raw: Array = _need(ld, "cells", "list", lw)
		var bad: bool = false
		for c: Array in raw:
			if not bad and not (int(c[0]) >= 0 and int(c[0]) < mw and int(c[1]) >= 0 and int(c[1]) < mh):
				_problem("%s: cell %d,%d is outside the %dx%d map" % [lw, int(c[0]), int(c[1]), mw, mh])
				bad = true
		match layer["kind"]:
			"tiles":
				for c: Array in raw:
					var tile: Array = [int(c[2]), int(c[3]), int(c[4])]
					layer["cells"].append({"x": int(c[0]), "y": int(c[1]), "tile": tile,
							"flags": int(c[5]) if c.size() > 5 else 0})
					if not ts.is_empty() and not bad and not (ts["tiles"] as Dictionary).has(tile_key(tile[0],
							tile[1], tile[2])):
						_problem("%s: cell %d,%d names tile %s, which the tileset does not have" % [lw, int(c[0]),
								int(c[1]), tile_key(tile[0], tile[1], tile[2])])
						bad = true
			"terrain":
				layer["terrain_set"] = int(ld["terrain_set"]) if ld.get("terrain_set") != null else 0
				layer["terrain"] = int(_need(ld, "terrain", "number", lw))
				if not ts.is_empty():
					var tset: Dictionary = ts["terrain_sets"].get(layer["terrain_set"], {})
					if tset.is_empty() or not (tset["terrains"] as Dictionary).has(layer["terrain"]):
						_problem("%s: terrain %d is not in tileset %s" % [lw, layer["terrain"], ts["name"]])
					else:
						layer["cells"] = resolve_terrain(ts, layer["terrain_set"], layer["terrain"], raw, li)
						var missing: int = 0
						for c: Dictionary in layer["cells"]:
							if c["tile"] == null:
								missing += 1
						if missing > 0: # the validator refuses such a map; the cells stay empty
							_warn("%s: %s: %d cell(s) need a key (%s) the terrain has no tile for: left empty" % [
									_path, lw, missing, tset["mode"]])
			"stamps":
				if not ts.is_empty():
					for c: Array in raw:
						var si: int = int(c[2]) if c.size() > 2 else -1
						if si < 0 or si >= (ts["stamp_list"] as Array).size():
							_problem("%s: cell %d,%d names stamp %d, which the tileset does not have (%d stamps)" % [
									lw, int(c[0]), int(c[1]), si, (ts["stamp_list"] as Array).size()])
					layer["cells"] = expand_stamps(ts, raw)
			_:
				var k: String = "layer." + str(layer["kind"])
				if not _warned.has(k):
					_warned[k] = true
					_warn("%s: %s: layer kind '%s' is not in spec %d.x: skipped" % [_path, lw, layer["kind"], MAJOR])
		if not ts.is_empty():
			for cell: Dictionary in layer["cells"]:
				if cell["tile"] != null:
					_place_cell(cell, s, ts)
					layer["count"] += 1
		else:
			layer["count"] = raw.size()
		s["layers"].append(layer)
		li += 1
	var oi: int = 0
	for o: Variant in (a["objects"] if typeof(a.get("objects")) == TYPE_ARRAY else []):
		oi += 1
		var ow: String = "%s object %d" % [where, oi]
		var od: Dictionary = o if typeof(o) == TYPE_DICTIONARY else {}
		var obj: Dictionary = {"asset": _need(od, "asset", "string", ow), "x": _need(od, "x", "number", ow),
				"y": _need(od, "y", "number", ow)}
		obj["sprite"] = _model["sprite"].get(obj["asset"], {}) # props are sprites (mapbuild places them)
		if (obj["sprite"] as Dictionary).is_empty():
			_problem("%s: %s is not a sprite in this manifest" % [ow, obj["asset"]])
		s["objects"].append(obj)
	return s


# ---- The extra kinds (loaded as data; the node that uses them is the game's) ----------------
func _convert_background(a: Dictionary, where: String) -> Dictionary:
	var s: Dictionary = {"kind": "background", "name": a["name"], "role": a.get("role"), "layers": []}
	var i: int = 0
	for L: Variant in _need(a, "layers", "list", where):
		i += 1
		var ld: Dictionary = L if typeof(L) == TYPE_DICTIONARY else {}
		var lw: String = "%s layer %s" % [where, ld.get("name", i)]
		_unknown_fields(ld, KNOWN["bg_layer"], "background layer")
		var size: Array = _pair(_need(ld, "size", "pair", lw))
		var rep: String = str(ld["repeat"]) if ld.get("repeat") != null else "none"
		var layer: Dictionary = {"name": ld.get("name"), "size": size,
				"velocity": _pair(_need(ld, "velocity", "pair", lw)), "repeat": rep,
				"repeat_x": rep == "x" or rep == "xy", "repeat_y": rep == "y" or rep == "xy",
				"wobble_px": ld["wobble_px"] if ld.get("wobble_px") != null else 0,
				"scale": ld["scale"] if ld.get("scale") != null else 1}
		layer["image"] = _file(_need(ld, "image", "string", lw), lw, size)
		s["layers"].append(layer)
	return s


## particles: the white mask texture and the emitter JSON as Dotwork writes it, kept whole.
func _convert_particles(a: Dictionary, where: String) -> Dictionary:
	var s: Dictionary = {"kind": "particles", "name": a["name"], "emitter": _need(a, "emitter", "dict", where)}
	s["texture"] = _file(_need(a, "texture", "string", where), where + " texture")
	return s


func _convert_transition(a: Dictionary, where: String) -> Dictionary:
	var size: Array = _pair(_need(a, "size", "pair", where))
	var s: Dictionary = {"kind": "transition", "name": a["name"], "size": size,
			"transition": _need(a, "transition", "string", where)}
	s["image"] = _file(_need(a, "image", "string", where), where, size)
	return s


## normal_map: the map and the image it lights (both ship); green up (opengl, what Godot expects) unless said.
func _convert_normal_map(a: Dictionary, where: String) -> Dictionary:
	var size: Array = _pair(_need(a, "size", "pair", where))
	var s: Dictionary = {"kind": "normal_map", "name": a["name"], "size": size,
			"convention": a["convention"] if a.get("convention") != null else "opengl"}
	s["image"] = _file(_need(a, "image", "string", where), where, size)
	s["target"] = _file(_need(a, "target", "string", where), where + " target")
	return s


func _convert_image(a: Dictionary, where: String) -> Dictionary:
	var size: Array = _pair(_need(a, "size", "pair", where))
	var s: Dictionary = {"kind": "image", "name": a["name"], "role": a.get("role"), "size": size,
			"pivot": _pair(a["pivot"]) if a.get("pivot") != null else null}
	s["image"] = _file(_need(a, "image", "string", where), where, size)
	return s


## The file paths of a skipped (unknown) kind, so verify() still checks they ship.
func _extra_files(a: Dictionary, where: String) -> void:
	for field: String in ["image", "texture", "target"]:
		if typeof(a.get(field)) == TYPE_STRING:
			_file(a[field], where + " " + field)
	if typeof(a.get("layers")) == TYPE_ARRAY:
		var i: int = 0
		for L: Variant in a["layers"]:
			i += 1
			if typeof(L) == TYPE_DICTIONARY and typeof((L as Dictionary).get("image")) == TYPE_STRING:
				_file(L["image"], "%s layer %d" % [where, i])
