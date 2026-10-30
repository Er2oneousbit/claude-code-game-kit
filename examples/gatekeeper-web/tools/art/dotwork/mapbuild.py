#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# mapbuild.py
# Purpose : ASCII map -> a Godot scene painted by Godot's own terrain solver inside the game (TileMapLayers +
#           y-sorted props), a preview rendered from the cells Godot chose, and a per-layer check report.
# Usage   : a "map" inside a pack spec's "ground" entry: {"name", "rows", "legend", "objects", "props",
#           "decal_density"}
# Notes   : Legend: per character the terrains painted there, base first; "none" = no base (interior void).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import json
import os
import random

import numpy as np
from PIL import Image

import fcore as core
import godotrun
GD = r'''extends SceneTree
# Dotwork mapbuild: paint the layers listed in the job JSON with Godot's terrain solver, save the scene, dump cells.
# blob check (Match Corners and Sides): every painted cell must hold the tile whose 8 bits are its painted
# neighbours (corner bits only where both sides are painted), and nothing may land outside the painted cells
const NB = [TileSet.CELL_NEIGHBOR_TOP_SIDE, TileSet.CELL_NEIGHBOR_TOP_RIGHT_CORNER, TileSet.CELL_NEIGHBOR_RIGHT_SIDE,
	TileSet.CELL_NEIGHBOR_BOTTOM_RIGHT_CORNER, TileSet.CELL_NEIGHBOR_BOTTOM_SIDE, TileSet.CELL_NEIGHBOR_BOTTOM_LEFT_CORNER,
	TileSet.CELL_NEIGHBOR_LEFT_SIDE, TileSet.CELL_NEIGHBOR_TOP_LEFT_CORNER]
const OFF = [Vector2i(0, -1), Vector2i(1, -1), Vector2i(1, 0), Vector2i(1, 1), Vector2i(0, 1), Vector2i(-1, 1),
	Vector2i(-1, 0), Vector2i(-1, -1)]

func canon(m):
	for c in [1, 3, 5, 7]:
		if not ((m >> ((c + 7) % 8)) & 1 and (m >> ((c + 1) % 8)) & 1):
			m &= ~(1 << c)
	return m

func blob_bad(layer, cells, tid):
	var painted = {}
	for c in cells:
		painted[c] = true
	var bad = 0
	for c in cells:
		var td = layer.get_cell_tile_data(c)
		if td == null:
			bad += 1
			continue
		var want = 0
		var got = 0
		for b in range(8):
			if painted.has(c + OFF[b]):
				want |= 1 << b
			if td.get_terrain_peering_bit(NB[b]) == tid:
				got |= 1 << b
		if got != canon(want):
			bad += 1
	return bad + layer.get_used_cells().size() - cells.size()

func _init():
	var job = JSON.parse_string(FileAccess.get_file_as_string(OS.get_cmdline_user_args()[0]))
	var ts = load(job["tileset"])
	var root = Node2D.new()
	root.name = job["name"]
	var rep = {"layers": [], "w": job["w"], "h": job["h"]}
	for L in job["layers"]:
		var layer = TileMapLayer.new()
		layer.name = L["name"]
		layer.tile_set = ts
		root.add_child(layer)
		layer.owner = root
		var cells = []
		if L["kind"] == "terrain":
			for c in L["cells"]:
				cells.append(Vector2i(int(c[0]), int(c[1])))
			layer.set_cells_terrain_connect(cells, 0, int(L["terrain"]))  # editor defaults
		else:
			for c in L["cells"]:
				layer.set_cell(Vector2i(int(c[0]), int(c[1])), int(c[2]), Vector2i(int(c[3]), int(c[4])))
		var used = []
		for p in layer.get_used_cells():
			var ac = layer.get_cell_atlas_coords(p)
			used.append([p.x, p.y, layer.get_cell_source_id(p), ac.x, ac.y])
		var bad = blob_bad(layer, cells, int(L["terrain"])) if L["kind"] == "terrain" else 0
		rep["layers"].append({"name": L["name"], "kind": L["kind"], "cells": used, "mismatches": bad})
	# props: prop scenes (StaticBody2D, origin at the feet) under one y-sorted node, so characters added later
	# to the same node pass in front of / behind them by their feet
	if job.has("props") and job["props"].size() > 0:
		var holder = Node2D.new()
		holder.name = "Props"
		holder.y_sort_enabled = true
		root.add_child(holder)
		holder.owner = root
		var placed = 0
		for pr in job["props"]:
			var sc = load(pr["scene"])
			if sc == null:
				continue
			var inst = sc.instantiate()
			inst.position = Vector2(float(pr["x"]), float(pr["y"]))
			holder.add_child(inst)
			inst.owner = root
			placed += 1
		rep["props_placed"] = placed
	var ps = PackedScene.new()
	rep["pack_error"] = ps.pack(root)
	rep["save_error"] = ResourceSaver.save(ps, job["scene"])
	var f = FileAccess.open(OS.get_cmdline_user_args()[1], FileAccess.WRITE)
	f.store_string(JSON.stringify(rep))
	f.close()
	print("DOTWORK_MAP saved=", rep["save_error"])
	quit()
'''


def plan(m, ground):
    """Turn the ASCII map into the job's layer list (base cells with a seeded variant pick, overlay cells, decals)."""
    rows = m["rows"]
    h, w = len(rows), max(len(r) for r in rows)
    rng = random.Random(int(m.get("seed", 1)))
    src = {s["name"]: (i, s) for i, s in enumerate(ground["sources"])}
    bases = [s["name"] for s in ground["sources"] if s["kind"] == "base"]
    overlays = [s["name"] for s in ground["sources"] if s["kind"] == "overlay"]
    base_cells, over_cells = [], {o: [] for o in overlays}
    covered = set()
    for y, row in enumerate(rows):
        for x, ch in enumerate(row.ljust(w)):
            names = m["legend"].get(ch, [])
            # "none" in a legend entry = no base tile (the black void around classic 16-bit RPG interiors)
            b = None if "none" in names else next((n for n in names if n in bases), bases[0] if bases else None)
            if b:
                sid, s = src[b]
                k = rng.choices(range(len(s["tiles"])), [t.get("probability", 1.0) for t in s["tiles"]])[0]
                base_cells.append([x, y, sid, s["tiles"][k]["x"], 0])
            for n in names:
                if n in over_cells:
                    over_cells[n].append([x, y])
                    covered.add((x, y))
    layers = [{"name": "Base", "kind": "tiles", "cells": base_cells}]
    for o in overlays:
        if over_cells[o]:
            sid, s = src[o]
            layers.append({"name": o.title().replace("_", ""), "kind": "terrain", "terrain": s["tiles"][0]["terrain"],
                           "cells": over_cells[o]})
    if "decals" in src:
        sid, s = src["decals"]
        dens = float(m.get("decal_density", 0.08))
        # decals only on plain base cells (two cells away from overlays so they never sit on a path edge)
        near = {(x + dx, y + dy) for (x, y) in covered for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        dec = [[x, y, sid, rng.randrange(len(s["tiles"])), 0] for y in range(h) for x in range(w)
               if (x, y) not in near and rng.random() < dens]
        layers.append({"name": "Decals", "kind": "tiles", "cells": dec})
    if m.get("objects") and "fixtures" in src:
        # objects: [{"fixture": "door_wood", "at": [x, y]}] -> the fixture's tiles from its top-left cell
        sid, s = src["fixtures"]
        cells = []
        for o in m["objects"]:
            f = s["fixtures"][o["fixture"]]
            for j in range(f["w"] * f["h"]):
                i = f["first"] + j
                cells.append([o["at"][0] + j % f["w"], o["at"][1] + j // f["w"], sid, i % s["cols"], i // s["cols"]])
        layers.append({"name": "Fixtures", "kind": "tiles", "cells": cells})
    return layers, w, h


def plan_props(m, T, res_root, art_dir):
    """map "props": [{"prop": "oak_tree", "at": [x, y]}] -> scene path + feet position (cell bottom-centre)."""
    # the prop name builds a file path (the preview opens spr_<name>.png): snake it like the props lane does
    return [{"name": core.snake(o["prop"]), "scene": f"{res_root}/{art_dir}/props/prop_{core.snake(o['prop'])}.tscn",
             "x": o["at"][0] * T + T // 2, "y": (o["at"][1] + 1) * T} for o in m.get("props", [])]


def render(report, ground, pack, conf):
    """Preview from Godot's own cell choices: blit each layer's atlas regions in layer order."""
    T = ground["tile_px"]
    atl = {}
    for i, s in enumerate(ground["sources"]):
        p = core.asset(conf, s["atlas_res"].replace(conf["fixed"]["res_root"] + "/", "").replace("/", os.sep))
        atl[i] = Image.open(p).convert("RGBA")
    W, H = int(report["w"]), int(report["h"])  # Godot JSON numbers come back as floats
    img = Image.new("RGBA", (W * T, H * T), (0, 0, 0, 255))
    for L in report["layers"]:
        for x, y, sid, ax, ay in L["cells"]:
            x, y, ax, ay = int(x), int(y), int(ax), int(ay)
            if 0 <= x < W and 0 <= y < H:
                tile = atl[int(sid)].crop((ax * T, ay * T, ax * T + T, ay * T + T))
                img.alpha_composite(tile, (x * T, y * T))
    return img.convert("RGB")


def render_props(img, props, pack, conf):
    """Prop sprites with their feet on the placement point, drawn in y order (what y-sort shows in Godot)."""
    img = img.convert("RGBA")
    for pr in sorted(props, key=lambda p: p["y"]):
        f = core.art(conf, "props", f"spr_{pr['name']}.png")
        if not os.path.exists(f):
            continue
        im = Image.open(f).convert("RGBA")
        bb = im.getbbox()
        if not bb:
            continue
        im = im.crop(bb)
        img.alpha_composite(im, (int(pr["x"] - im.width // 2), int(pr["y"] - im.height)))
    return img.convert("RGB")


def build(m, ground, pack, conf):
    """Paint the map with Godot's own terrain solver inside the game project, save the scene under
    <assets>/maps/, write the preview + report under <src>/maps/."""
    settings = core.SETTINGS
    if not settings.godot():
        core.log(f"map {m.get('name', 'map')}: skipped (--engine none: maps are painted by Godot)")
        return None, {}
    godotrun.project_ok(settings)
    name = core.snake(m.get("name", "map"))
    layers, w, h = plan(m, ground)
    props = plan_props(m, ground["tile_px"], conf["fixed"]["res_root"], conf["fixed"]["art_dir"])
    code, out = godotrun.import_project(settings)   # new atlases / scenes must be imported before they load
    if code != 0:
        raise core.JobError(f"Godot import failed before painting {name}:\n{out[-1500:]}")
    scene = core.asset(conf, "maps", f"{name}.tscn")
    os.makedirs(os.path.dirname(scene), exist_ok=True)   # ResourceSaver does not create folders
    job = {"name": name.title().replace("_", ""), "tileset": ground["res"], "w": w, "h": h, "layers": layers,
           "scene": godotrun.res_of(settings, scene), "props": props}
    jp, rp = core.work("mapbuild", f"{name}_job.json"), core.work("mapbuild", f"{name}_report.json")
    core.write_text(jp, json.dumps(job))
    if os.path.exists(rp):
        os.remove(rp)
    code, out = godotrun.run_script(settings, "dotwork_mapbuild", GD, (jp, rp))
    if not os.path.exists(rp):
        raise core.JobError(f"mapbuild: Godot wrote no report for {name}\n{out[-2000:]}")
    report = json.load(open(rp, encoding="utf-8"))  # Godot writes UTF-8
    outd = core.src(conf, "maps")
    os.makedirs(outd, exist_ok=True)
    img = render_props(render(report, ground, pack, conf), props, pack, conf)
    core.save_clean(img, os.path.join(outd, f"{name}_preview.png"))
    core.save_clean(img.resize((img.width * 3, img.height * 3), Image.NEAREST), os.path.join(outd, f"{name}_preview_3x.png"))
    summary = {L["name"]: {"cells": len(L["cells"]), "mismatches": L["mismatches"]} for L in report["layers"]}
    core.write_text(os.path.join(outd, f"{name}_report.json"),
                    json.dumps({"map": name, "size": [w, h], "layers": summary, "save_error": report["save_error"],
                                "props_placed": report.get("props_placed", 0), "props_requested": len(props)}, indent=1))
    bad = sum(int(v["mismatches"]) for v in summary.values())
    core.log(f"map {name}: {w}x{h}, layers {list(summary)}, mismatches {bad}, save_error {report['save_error']}")
    if bad or int(report["save_error"]) != 0:
        raise core.JobError(f"map {name}: {bad} wrong cells / save error {report['save_error']} (see {name}_report.json)")
    return scene, summary
