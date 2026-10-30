#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# verify.py
# Purpose : prove what Dotwork just made works in the game itself: import the project (its own tools/dev.py import
#           when it has one), load every .tres / .tscn / .fnt the run wrote with a headless loader (SpriteFrames
#           animations, TileSet terrains painted shape by shape and checked cell by cell, scenes instantiated, fonts
#           measured), then the game's smoke test (tools/dev.py smoke) when it exists.
# Usage   : python dotwork.py verify [--project GAME]     (also runs at the end of `dotwork.py pack` unless --no-verify)
# Notes   : Overlay TileSets (lane_ground, metadata dotwork_overlays) get the blob check: painting a shape on an empty
#           layer must give exactly the painted cells with the right tiles. Pair TileSets get the corner check.
#           Writes <work>/verify_report.json. The pack command exits 1 when ok is false.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
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
			print("DOTWORK_OK ", p, " SpriteFrames anims=", r.get_animation_names().size())
		elif r is TileSet:
			print("DOTWORK_OK ", p, " TileSet sources=", r.get_source_count(), " terrain_sets=", r.get_terrain_sets_count())
			# layered ground TileSets (lane_ground) carry metadata/dotwork_overlays: test each overlay terrain on an
			# empty layer; pair TileSets (lane_tiles) get the two-terrain test
			# a TileSet without terrains (iso floors and blocks are placed tile by tile) has nothing to paint
			var t = 0 if r.get_terrain_sets_count() == 0 else (
				_overlay_test(r, r.get_meta("dotwork_overlays")) if r.has_meta("dotwork_overlays") else (
				_overlay_test(r, r.get_meta("dotwork_sides"), true) if r.has_meta("dotwork_sides") else _terrain_test(r)))
			if t > 0:
				bad += 1
			print("DOTWORK_TERRAIN ", p, " mismatched_corners=", t)
		elif r is FontFile:
			# Dotwork glyph fonts (BMFont): must report a height and lay out a sample string
			var fs = r.fixed_size if r.fixed_size > 0 else 16
			var h = r.get_height(fs)
			var w = r.get_string_size("Hello, world! 0123", HORIZONTAL_ALIGNMENT_LEFT, -1, fs).x
			print("DOTWORK_OK ", p, " FontFile size=", fs, " height=", h, " sample_w=", w)
			if h <= 0 or w <= 0:
				bad += 1
		elif r is PackedScene:
			var n = r.instantiate()
			print("DOTWORK_OK ", p, " scene root=", n.get_class())
			n.free()
		else:
			print("DOTWORK_OK ", p, " ", r.get_class())
	print("DOTWORK_DONE bad=", bad)
	quit(1 if bad > 0 else 0)

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
'''


def verify(settings, files):
    """Prove the files load in the game itself: import (the game's tools/dev.py when present), the loader above on
    every .tres / .tscn / .fnt this run wrote (terrain sets are painted and checked), then the game's smoke test.
    files: project-relative paths (the manifest's rows). Writes <work>/verify_report.json."""
    godotrun.project_ok(settings)
    res = sorted({godotrun.res_of(settings, os.path.join(settings.project, f)) for f in files
                  if f.endswith((".tres", ".tscn", ".fnt"))})
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
    code, out = godotrun.smoke(settings)
    report["smoke_exit"], report["smoke_tail"] = code, (out or "")[-800:]
    report["ok"] = (report["import_exit"] == 0 and not report["import_errors"] and report["load_exit"] == 0
                    and report["smoke_exit"] in (0, None))
    core.write_text(core.work("verify_report.json"), json.dumps(report, indent=1))
    core.log(f"verify: ok={report['ok']} import={report['import_exit']} errors={len(report['import_errors'])} "
             f"load={report['load_exit']} smoke={report['smoke_exit']} ({len(res)} resources)")
    return report
