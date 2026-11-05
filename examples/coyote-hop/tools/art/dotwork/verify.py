#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# verify.py
# Purpose : prove what Dotwork just made works in the game itself: import the project (its own tools/dev.py import
#           when it has one), load every .tres / .tscn / .fnt the run wrote with a headless loader (SpriteFrames
#           animations and held frames, TileSet terrains painted shape by shape and checked cell by cell, scenes
#           instantiated with their particle emitters and line trails checked, fonts measured, ShaderMaterials
#           compiled), then the game's smoke test (tools/dev.py smoke) when it exists.
# Usage   : python dotwork.py verify [--project GAME]     (also runs at the end of `dotwork.py pack` unless --no-verify)
# Notes   : Overlay TileSets (lane_ground, metadata dotwork_overlays) get the blob check: painting a shape on an empty
#           layer must give exactly the painted cells with the right tiles. Pair TileSets get the corner check. A
#           TileSet from Pixelorama (metadata dotwork_pixelorama) only loads; every TileMapLayer in a scene must find
#           a tile for each of its cells.
#           Lit resources (lane_lighting): every CanvasTexture needs a diffuse and a same-size normal map whose pixels,
#           as Godot imported them, decode to unit normals facing the camera (z > 0); occluders need a polygon, point
#           lights a texture, a TileMapLayer on a lit TileSet a tile in every cell. Headless Godot renders nothing,
#           so the lit look itself is not checked here (the lighting lane's review sheet shows a numpy preview).
#           Writes <work>/verify_report.json. The pack command exits 1 when ok is false.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-04 with Claude (Opus 5.5, claude-opus-5-5): every TileMapLayer cell must find its tile; a
#           Pixelorama TileSet is loaded, not terrain-painted
# ---------------------------------------------------------------------------
import json
import os
import re

import fcore as core
import godotrun

# Import-log lines that are not about Dotwork's files and must not fail its check. Empty [preset.N.options] sections in
# export_presets.cfg (Godot's ConfigFile drops sections without keys) log this on some imports; export is unaffected.
IGNORED_ERRORS = ('Cannot get keys from nonexistent section "preset.',)
# An error is a line with one of Godot's error markers (the kit's dev.py scans for the same ones), not any line that
# merely contains "error": a game path such as res://maps/terror_bridge.tscn used to fail every verify (2026-10-30).
ERROR_LINE = re.compile(r"SCRIPT ERROR|Parse Error|\bERROR:|\[ERROR\]|Failed to load|^\s*\[FAIL\]")

LOADER = r'''extends SceneTree
# Dotwork verify loader: load every resource listed in the file given after "--" and report what it contains.
func _init():
	var f = FileAccess.open(OS.get_cmdline_user_args()[0], FileAccess.READ)
	var bad = 0
	while not f.eof_reached():
		var p = f.get_line().strip_edges()
		if p == "":
			continue
		var r = load(p)
		if r == null:
			print("DOTWORK_FAIL ", p)
			bad += 1
		elif r is SpriteFrames:
			# frames whose duration is not 1.0 (holds) are counted; the line is unchanged when there are none
			var held = 0
			for a in r.get_animation_names():
				for i in r.get_frame_count(a):
					if not is_equal_approx(r.get_frame_duration(a, i), 1.0):
						held += 1
			var extra = (" held=" + str(held)) if held > 0 else ""
			# lit copies (lane_lighting): every CanvasTexture frame needs its diffuse and a same-size normal map
			var lf = _lit_frames(r)
			print("DOTWORK_OK ", p, " SpriteFrames anims=", r.get_animation_names().size(), extra, "" if lf[0] == 0 else str(" lit_frames=", lf[0]))
			bad += lf[1]
		elif r is ShaderMaterial:
			# the headless (dummy) renderer compiles the shader: one that fails still loads, but lists no uniforms
			var u = r.shader.get_shader_uniform_list().size() if r.shader != null else -1
			if u < 0 or (u == 0 and r.shader.code.contains("uniform ")):
				print("DOTWORK_FAIL ", p, " ShaderMaterial: its shader does not compile")
				bad += 1
			else:
				print("DOTWORK_OK ", p, " ShaderMaterial uniforms=", u)
		elif r is TileSet:
			print("DOTWORK_OK ", p, " TileSet sources=", r.get_source_count(), " terrain_sets=", r.get_terrain_sets_count())
			# layered ground TileSets (lane_ground) carry metadata/dotwork_overlays: test each overlay terrain on an
			# empty layer; pair TileSets (lane_tiles) get the two-terrain test
			# a TileSet without terrains (iso floors and blocks are placed tile by tile) has nothing to paint
			# a hand-made TileSet (Pixelorama tilemaps, metadata dotwork_pixelorama) has the terrains you gave its tiles:
			# it loads, and its maps are checked cell by cell; a terrain you left half done is yours to finish
			var t = 0 if r.get_terrain_sets_count() == 0 or r.has_meta("dotwork_pixelorama") else (
				_overlay_test(r, r.get_meta("dotwork_overlays")) if r.has_meta("dotwork_overlays") else (
				_overlay_test(r, r.get_meta("dotwork_sides"), true) if r.has_meta("dotwork_sides") else (
				_iso_test(r) if r.has_meta("dotwork_iso") else _terrain_test(r))))
			if t > 0:
				bad += 1
			print("DOTWORK_TERRAIN ", p, " mismatched_corners=", t)
			var ls = _lit_sources(r)
			if ls[0] > 0:
				print("DOTWORK_LIT ", p, " lit_sources=", ls[0])
			bad += ls[1]
		elif r is FontFile:
			# Dotwork glyph fonts (BMFont): must report a height and lay out a sample string
			var fs = r.fixed_size if r.fixed_size > 0 else 16
			var h = r.get_height(fs)
			var w = r.get_string_size("Hello, world! 0123", HORIZONTAL_ALIGNMENT_LEFT, -1, fs).x
			print("DOTWORK_OK ", p, " FontFile size=", fs, " height=", h, " sample_w=", w)
			if h <= 0 or w <= 0:
				bad += 1
		elif r is CanvasTexture:
			print("DOTWORK_OK ", p, " CanvasTexture size=", r.get_size())
			bad += _canvas_bad(r)
		elif r is PackedScene:
			var n = r.instantiate()
			print("DOTWORK_OK ", p, " scene root=", n.get_class())
			bad += _fx_check(p, n)
			bad += _map_check(p, n)
			var lit = _lit_scene(n)
			if lit[0] != "":
				print("DOTWORK_LIT ", p, lit[0])
			bad += lit[1]
			n.free()
		else:
			print("DOTWORK_OK ", p, " ", r.get_class())
	print("DOTWORK_DONE bad=", bad)
	quit(1 if bad > 0 else 0)

# Particle and trail nodes in a scene (lane_vfx): a GPUParticles2D needs a ParticleProcessMaterial, a texture and at
# least one particle; a Line2D trail needs two points and a gradient. Each is printed with what a game tunes. Returns
# the number of broken nodes.
# Maps (mapbuild, Pixelorama tilemaps): every cell of every TileMapLayer must find its tile in the TileSet (a cell
# whose atlas slot or source is gone draws nothing and logs no error).
func _map_check(p, node):
	var bad = 0
	if node is TileMapLayer and node.tile_set != null:
		var missing = 0
		for c in node.get_used_cells():
			if node.get_cell_tile_data(c) == null:
				missing += 1
		print("DOTWORK_MAP ", p, " layer=", node.name, " cells=", node.get_used_cells().size(), " missing=", missing)
		if missing > 0:
			print("DOTWORK_FAIL ", p, " ", node.name, ": ", missing, " cells hold no tile of the TileSet")
			bad += 1
	for c in node.get_children():
		bad += _map_check(p, c)
	return bad

func _fx_check(p, node):
	var bad = 0
	if node is GPUParticles2D:
		var pm = node.process_material
		var ok = pm is ParticleProcessMaterial and node.texture != null and node.amount > 0
		print("DOTWORK_PARTICLES ", p, " node=", node.name, " amount=", node.amount, " one_shot=", node.one_shot,
			" explosiveness=", node.explosiveness, " lifetime=", node.lifetime, " texture=", node.texture != null,
			" material=", pm.get_class() if pm else "none",
			" color_ramp=", pm is ParticleProcessMaterial and pm.color_ramp != null)
		if not ok:
			bad += 1
	elif node is Line2D:
		print("DOTWORK_LINE ", p, " node=", node.name, " points=", node.points.size(), " gradient=", node.gradient != null)
		if node.points.size() < 2 or node.gradient == null:
			bad += 1
	for c in node.get_children():
		bad += _fx_check(p, c)
	return bad
# Lit resources (lane_lighting). A CanvasTexture needs a diffuse and a normal texture of the same size; headless Godot
# draws nothing, so this proves the resources are wired, not what the light looks like. Returns 1 when broken.
func _canvas_bad(t):
	if t.diffuse_texture == null or t.normal_texture == null:
		print("DOTWORK_LIT_FAIL CanvasTexture without a diffuse or a normal texture")
		return 1
	if t.diffuse_texture.get_size() != t.normal_texture.get_size():
		print("DOTWORK_LIT_FAIL ", t.normal_texture.resource_path, " is ", t.normal_texture.get_size(), ", its diffuse ", t.diffuse_texture.get_size())
		return 1
	return _normal_bad(t.normal_texture)

# A normal map as Godot imported it: sampled pixels (about 4096 per texture) must decode to unit normals (8-bit
# rounding allowed) with z > 0. A diffuse PNG in the normal slot, or a lossy import, fails this.
func _normal_bad(tex):
	var img = tex.get_image()
	if img == null:
		return 0
	if img.is_compressed():
		img.decompress()
	var w = img.get_width()
	var h = img.get_height()
	var step = max(1, int(sqrt(w * h / 4096.0)))
	for y in range(0, h, step):
		for x in range(0, w, step):
			var c = img.get_pixel(x, y)
			var n = Vector3(c.r * 2.0 - 1.0, c.g * 2.0 - 1.0, c.b * 2.0 - 1.0)
			if n.z <= 0.0 or abs(n.length() - 1.0) > 0.06:
				print("DOTWORK_LIT_FAIL ", tex.resource_path, " pixel ", x, ",", y, " = ", c, " is not a unit normal facing the camera")
				return 1
	return 0

# [CanvasTexture frames, broken ones] of a SpriteFrames
func _lit_frames(sf):
	var n = 0
	var b = 0
	for a in sf.get_animation_names():
		for i in range(sf.get_frame_count(a)):
			var t = sf.get_frame_texture(a, i)
			if t is CanvasTexture:
				n += 1
				b += _canvas_bad(t)
	return [n, b]

# [atlas sources with a CanvasTexture, broken ones] of a TileSet; a lit atlas must still hold its tiles
func _lit_sources(ts):
	var n = 0
	var b = 0
	for i in range(ts.get_source_count()):
		var s = ts.get_source(ts.get_source_id(i))
		if s is TileSetAtlasSource and s.texture is CanvasTexture:
			n += 1
			b += _canvas_bad(s.texture)
			if s.get_tiles_count() == 0:
				print("DOTWORK_LIT_FAIL lit atlas source ", ts.get_source_id(i), " has no tiles")
				b += 1
	return [n, b]

# [summary or "", broken count] of an instantiated scene: occluders need a polygon, point lights a texture, lit
# sprites need sound CanvasTextures, and a TileMapLayer on a lit TileSet must find a tile in every painted cell. Scenes
# without lighting nodes print nothing extra.
func _lit_scene(root):
	var occ = 0
	var lights = 0
	var mods = 0
	var lit = 0
	var cells = 0
	var b = 0
	var nodes = [root]
	nodes.append_array(root.find_children("*", "", true, false))
	for c in nodes:
		if c is LightOccluder2D:
			occ += 1
			if c.occluder == null or c.occluder.polygon.size() < 3:
				print("DOTWORK_LIT_FAIL ", c.name, ": LightOccluder2D without a polygon")
				b += 1
		elif c is PointLight2D:
			lights += 1
			if c.texture == null:
				print("DOTWORK_LIT_FAIL ", c.name, ": PointLight2D without a texture lights nothing")
				b += 1
		elif c is CanvasModulate:
			mods += 1
		elif c is Sprite2D and c.texture is CanvasTexture:
			lit += 1
			b += _canvas_bad(c.texture)
		elif c is AnimatedSprite2D and c.sprite_frames != null and _lit_frames(c.sprite_frames)[0] > 0:
			lit += 1
			b += _lit_frames(c.sprite_frames)[1]
		elif c is TileMapLayer and c.tile_set != null and _lit_sources(c.tile_set)[0] > 0:
			lit += 1
			for cell in c.get_used_cells():
				cells += 1
				if c.get_cell_tile_data(cell) == null:
					b += 1
			if cells == 0:
				print("DOTWORK_LIT_FAIL ", c.name, ": a lit TileMapLayer with no cells")
				b += 1
	if occ + lights + mods + lit == 0:
		return ["", b]
	return [str(" occluders=", occ, " lights=", lights, " canvas_modulate=", mods, " lit_nodes=", lit, " lit_cells=", cells), b]

# Overlay terrains (lane_ground: 47-tile blob, Match Corners and Sides): paint each shape on an EMPTY layer with the
# editor's default settings; every painted cell must get the tile whose 8 bits are its painted neighbours, and no
# tile may land outside the shape (what you paint is what you get). Returns the number of wrong / extra cells.
const NB = [TileSet.CELL_NEIGHBOR_TOP_SIDE, TileSet.CELL_NEIGHBOR_TOP_RIGHT_CORNER, TileSet.CELL_NEIGHBOR_RIGHT_SIDE,
	TileSet.CELL_NEIGHBOR_BOTTOM_RIGHT_CORNER, TileSet.CELL_NEIGHBOR_BOTTOM_SIDE, TileSet.CELL_NEIGHBOR_BOTTOM_LEFT_CORNER,
	TileSet.CELL_NEIGHBOR_LEFT_SIDE, TileSet.CELL_NEIGHBOR_TOP_LEFT_CORNER]
const OFF = [Vector2i(0, -1), Vector2i(1, -1), Vector2i(1, 0), Vector2i(1, 1), Vector2i(0, 1), Vector2i(-1, 1),
	Vector2i(-1, 0), Vector2i(-1, -1)]

func _canon(m):
	for c in [1, 3, 5, 7]:
		if not ((m >> ((c + 7) % 8)) & 1 and (m >> ((c + 1) % 8)) & 1):
			m &= ~(1 << c)
	return m

# sides_only: a Match Sides set (lane_platforms) is judged on its four sides; its corners carry no terrain
func _overlay_test(ts, ids, sides_only = false):
	var rect = []
	for y in range(3, 7):
		for x in range(4, 10):
			rect.append(Vector2i(x, y))
	var ring = rect.duplicate()
	for p in [Vector2i(6, 4), Vector2i(7, 4), Vector2i(6, 5), Vector2i(7, 5)]:
		ring.erase(p)
	var shapes = [rect, ring, [Vector2i(3, 3), Vector2i(4, 4), Vector2i(5, 5)], [Vector2i(6, 5)],
		[Vector2i(2, 5), Vector2i(3, 5), Vector2i(4, 5), Vector2i(5, 5), Vector2i(6, 5)],
		[Vector2i(1, 9), Vector2i(2, 9), Vector2i(1, 10), Vector2i(2, 10), Vector2i(3, 10)]]
	var total = 0
	for tid in ids:
		for s in shapes:
			var layer = TileMapLayer.new()
			layer.tile_set = ts
			layer.set_cells_terrain_connect(s, 0, int(tid))
			for c in s:
				var td = layer.get_cell_tile_data(c)
				if td == null:
					total += 1
					continue
				var want = 0
				var got = 0
				for b in range(8):
					if sides_only and b % 2 == 1:
						continue
					if s.has(c + OFF[b]):
						want |= 1 << b
					if td.get_terrain_peering_bit(NB[b]) == int(tid):
						got |= 1 << b
				if got != (want if sides_only else _canon(want)):
					total += 1
			total += layer.get_used_cells().size() - s.size()
			layer.free()
	return total

# Paint a base terrain everywhere, then a shape of the other terrain, with Godot's own terrain tool; every pair of
# neighbouring cells must agree on the terrain of their shared corners. Shapes: rectangle, rectangle + bump,
# diagonal, single cell, 1-wide line; both directions (a into b, b into a). Returns total disagreements.
func _terrain_test(ts):
	var rect = []
	for y in range(3, 7):
		for x in range(4, 10):
			rect.append(Vector2i(x, y))
	var bump = rect.duplicate()
	bump.append(Vector2i(10, 4))
	var shapes = [rect, bump, [Vector2i(3, 3), Vector2i(4, 4), Vector2i(5, 5)], [Vector2i(6, 5)],
		[Vector2i(2, 5), Vector2i(3, 5), Vector2i(4, 5), Vector2i(5, 5), Vector2i(6, 5)]]
	var total = 0
	for s in shapes:
		total += _paint_check(ts, 1, 0, s) + _paint_check(ts, 0, 1, s)
	return total

func _paint_check(ts, base, paint, shape):
	var layer = TileMapLayer.new()
	layer.tile_set = ts
	var all = []
	for y in range(10):
		for x in range(14):
			all.append(Vector2i(x, y))
	# base fill with ignore_empty_terrains = false: on an EMPTY layer the default (true) leaves the region's outer
	# ring unpainted, which a test run on 2026-10-29 misread as a TileSet bug
	layer.set_cells_terrain_connect(all, 0, base, false)
	layer.set_cells_terrain_connect(shape, 0, paint)
	var bad = 0
	for y in range(9):
		for x in range(13):
			var a = layer.get_cell_tile_data(Vector2i(x, y))
			var r = layer.get_cell_tile_data(Vector2i(x + 1, y))
			var d = layer.get_cell_tile_data(Vector2i(x, y + 1))
			if a == null or r == null or d == null:
				bad += 1
				continue
			if a.get_terrain_peering_bit(TileSet.CELL_NEIGHBOR_TOP_RIGHT_CORNER) != r.get_terrain_peering_bit(TileSet.CELL_NEIGHBOR_TOP_LEFT_CORNER):
				bad += 1
			if a.get_terrain_peering_bit(TileSet.CELL_NEIGHBOR_BOTTOM_RIGHT_CORNER) != r.get_terrain_peering_bit(TileSet.CELL_NEIGHBOR_BOTTOM_LEFT_CORNER):
				bad += 1
			if a.get_terrain_peering_bit(TileSet.CELL_NEIGHBOR_BOTTOM_LEFT_CORNER) != d.get_terrain_peering_bit(TileSet.CELL_NEIGHBOR_TOP_LEFT_CORNER):
				bad += 1
	layer.free()
	return bad

# Isometric transitions (lane_iso, metadata dotwork_iso): one Match Corners set per material pair. Same shapes and
# both directions as the square test, but neighbours come from Godot's own layout (get_neighbor_cell): a diamond
# shares a side with the cell below-right (my right / bottom corners = its top / left) and below-left (my left /
# bottom corners = its top / right). A neighbour outside the painted area is skipped.
func _iso_test(ts):
	var rect = []
	for y in range(3, 7):
		for x in range(4, 10):
			rect.append(Vector2i(x, y))
	var bump = rect.duplicate()
	bump.append(Vector2i(10, 4))
	var shapes = [rect, bump, [Vector2i(3, 3), Vector2i(4, 4), Vector2i(5, 5)], [Vector2i(6, 5)],
		[Vector2i(2, 5), Vector2i(3, 5), Vector2i(4, 5), Vector2i(5, 5), Vector2i(6, 5)]]
	var total = 0
	for tset in range(ts.get_terrain_sets_count()):
		for s in shapes:
			total += _iso_check(ts, tset, 1, 0, s) + _iso_check(ts, tset, 0, 1, s)
	return total

func _iso_check(ts, tset, base, paint, shape):
	var layer = TileMapLayer.new()
	layer.tile_set = ts
	var all = {}
	for y in range(10):
		for x in range(14):
			all[Vector2i(x, y)] = true
	layer.set_cells_terrain_connect(all.keys(), tset, base, false)
	layer.set_cells_terrain_connect(shape, tset, paint)
	var bad = 0
	var pairs = [[TileSet.CELL_NEIGHBOR_BOTTOM_RIGHT_SIDE, TileSet.CELL_NEIGHBOR_RIGHT_CORNER, TileSet.CELL_NEIGHBOR_TOP_CORNER,
			TileSet.CELL_NEIGHBOR_BOTTOM_CORNER, TileSet.CELL_NEIGHBOR_LEFT_CORNER],
		[TileSet.CELL_NEIGHBOR_BOTTOM_LEFT_SIDE, TileSet.CELL_NEIGHBOR_LEFT_CORNER, TileSet.CELL_NEIGHBOR_TOP_CORNER,
			TileSet.CELL_NEIGHBOR_BOTTOM_CORNER, TileSet.CELL_NEIGHBOR_RIGHT_CORNER]]
	for c in all.keys():
		var a = layer.get_cell_tile_data(c)
		if a == null:
			bad += 1
			continue
		for p in pairs:
			var n = layer.get_neighbor_cell(c, p[0])
			if not all.has(n):
				continue
			var d = layer.get_cell_tile_data(n)
			if d == null:
				bad += 1
				continue
			if a.get_terrain_peering_bit(p[1]) != d.get_terrain_peering_bit(p[2]):
				bad += 1
			if a.get_terrain_peering_bit(p[3]) != d.get_terrain_peering_bit(p[4]):
				bad += 1
	layer.free()
	return bad
'''


def project_images(project):
    """res:// paths of the icon and boot splash project.godot names (the store lane's "apply" sets them), so verify
    proves they import and load as well."""
    p = os.path.join(project, "project.godot")
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        return sorted(set(re.findall(r'^(?:config/icon|boot_splash/image)="(res://[^"]+)"', f.read(), re.M)))


def verify(settings, files):
    """Prove the files load in the game itself: import (the game's tools/dev.py when present), the loader above on
    every .tres / .tscn / .fnt this run wrote (terrain sets are painted and checked) and the project's icon and boot
    splash, then the game's smoke test.
    files: project-relative paths (the manifest's rows). Writes <work>/verify_report.json."""
    godotrun.project_ok(settings)
    res = sorted({godotrun.res_of(settings, os.path.join(settings.project, f)) for f in files
                  if f.endswith((".tres", ".tscn", ".fnt"))} | set(project_images(settings.project)))
    report = {"project": settings.project, "resources": res}
    code, out = godotrun.import_project(settings)
    report["import_exit"], report["import_log_tail"] = code, out[-2000:]
    report["import_errors"] = [l for l in out.splitlines() if ERROR_LINE.search(l)
                               and not any(k in l for k in IGNORED_ERRORS)][:50]
    lst = core.work("verify", "resources.txt")
    core.write_text(lst, "\n".join(res) + "\n")
    code, out = godotrun.run_script(settings, "dotwork_verify_loader", LOADER, (lst,))
    report["load_exit"] = code
    report["load_lines"] = [l for l in out.splitlines() if l.startswith("DOTWORK_")]
    # UI kit previews (lane_uikit): walk the focus chain with ui_down / ui_up in a running SceneTree
    focus_ok = True
    for r in [r for r in res if re.search(r"/uikit_preview_[^/]+\.tscn$", r)]:
        import lane_uikit
        ok, lines = lane_uikit.focus_check(settings, r)
        focus_ok = focus_ok and ok
        report.setdefault("focus_lines", []).extend([f"{r}: {l}" for l in lines] or [f"{r}: no output"])
        core.log(f"verify focus walk {r}: {lines[-1] if lines else 'no output'}")
    code, out = godotrun.smoke(settings)
    report["smoke_exit"], report["smoke_tail"] = code, (out or "")[-800:]
    report["ok"] = (report["import_exit"] == 0 and not report["import_errors"] and report["load_exit"] == 0
                    and report["smoke_exit"] in (0, None) and focus_ok)
    core.write_text(core.work("verify_report.json"), json.dumps(report, indent=1))
    core.log(f"verify: ok={report['ok']} import={report['import_exit']} errors={len(report['import_errors'])} "
             f"load={report['load_exit']} smoke={report['smoke_exit']} ({len(res)} resources)")
    return report
