#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# assetmap.py
# Purpose : write the engine-neutral asset manifest (ASSET_MANIFEST.md) of one Dotwork pack,
#           <assets_dir>/dotwork/<pack>.assets.json, from that pack's provenance manifest
#           (<src_dir>/dotwork/manifest_<pack>.json): its rows (one per shipped file) and its records (what each Godot
#           resource was built from: godot.record, kept under --engine none too). Every engine's importer reads it.
# Usage   : imported by dotwork.py (pack, character, aseprite / pixelorama --reexport, manifest)
# Notes   : Standard library only (the golden-fixture builder runs it without Pillow or numpy).
#           Godot is the reference: an animated sprite is the SpriteFrames' animations (files, fps, loop, holds), a
#           tileset is the TileSet's sources and tiles (peering bits as masks, collision polygons as rects), a prop is
#           its scene's origin and footprint box, a map is the plan mapbuild hands Godot's terrain solver.
#           Pseudocode:
#             for each record: frames -> animated_sprite, tileset -> tileset, prop -> sprite (+ collision),
#                              map -> map; skip a record whose files are gone (stale)
#             for each row not used yet, grouped: icons by name and size, portraits by name, enemies (+ shadow),
#                backgrounds (battle, platform, scenes, weather), fonts (.fnt parsed), UI parts by folder,
#                particles, transitions, normal maps, Pixelorama tilemaps; any PNG left -> image
#             assets sorted by kind and name; written only when the text changed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import json
import os
import posixpath
import re

import assetspec
import godot

GENERATOR = "dotwork"
MODES = {"match_corners_and_sides": "blob47", "match_corners": "corners4", "match_sides": "sides4"}
SQUARE_CORNERS = ("top_left", "top_right", "bottom_left", "bottom_right")   # godot.CORNERS order
KIND_ORDER = {k: i for i, k in enumerate(assetspec.KINDS)}
UI_KINDS = ("ui_window", "ui_9slice", "ui_button", "ui_panel", "ui_texture", "ui_gauge", "ui_cursor", "ui_glyph",
            "ui_symbol", "screen_logo")
BACKDROP_KINDS = ("scene_backdrop", "scene", "background")   # "scene" rows that are PNGs come from img2px
DIR_CLIP = re.compile(r"^(.+)_(" + "|".join(assetspec.DIRECTIONS) + r")$")


def manifest_path(assets_abs, pack):
    return os.path.join(assets_abs, "dotwork", _safe_name(pack) + assetspec.SUFFIX)


def _safe_name(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(s)).strip("_") or "asset"


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, int(c))):02x}" for c in list(rgb)[:3])


def _num(x):
    """Whole floats as ints (2.0 -> 2), so the JSON reads like the data."""
    return int(x) if isinstance(x, float) and x == int(x) else x


def pivot_of(anchor, w, h):
    """The point of a frame that sits on the node origin, from the anchor word Dotwork's rows carry (Godot's
    AnimatedSprite2D is centred when a lane gives no anchor)."""
    a = (anchor or "").lower()
    if a.startswith("tail_tip"):          # emote balloons: the tail's tip, under the left third (lane_balloons.bubble)
        return [w // 4, h]
    if "bottom" in a or a.startswith("feet"):
        return [_num(w / 2), h]
    if a == "right":                      # projectile trails: the head of the trail
        return [w, _num(h / 2)]
    if a == "top_left":
        return [0, 0]
    return [_num(w / 2), _num(h / 2)]


class Writer:
    """One pack's provenance manifest data -> the neutral document."""

    def __init__(self, project, assets_dir, data, pack):
        self.project = os.path.abspath(project)
        self.assets_rel = assets_dir.replace("\\", "/").strip("/")
        self.rows = [r for r in data.get("assets", []) if isinstance(r, dict) and "file" in r]
        self.by_file = {r["file"]: r for r in self.rows}
        self.ents = data.get("entities") or {}
        self.pack = pack
        self.used = set()
        self.assets = []
        self.warnings = []
        self.sizes = {}

    # ---- paths -------------------------------------------------------------------------
    def arel(self, game_rel):
        """Game-relative -> relative to the assets folder (None outside it: store art in assets_src ships nowhere)."""
        pre = self.assets_rel + "/"
        return game_rel[len(pre):] if game_rel.startswith(pre) else None

    @staticmethod
    def game_of_res(res):
        """res://x/y -> x/y: Godot's res:// is the game folder, whatever Dotwork's res_root says."""
        return res[len("res://"):] if res.startswith("res://") else res

    def full(self, game_rel):
        return os.path.join(self.project, *game_rel.split("/"))

    def exists(self, game_rel):
        return os.path.isfile(self.full(game_rel))

    def size(self, game_rel):
        if game_rel not in self.sizes:
            self.sizes[game_rel] = list(assetspec.png_size(self.full(game_rel)))
        return self.sizes[game_rel]

    def role(self, game_rel):
        """The art folder an asset sits in (characters, fx, props, ui, tiles ...): after <assets>/<art>/."""
        a = self.arel(game_rel) or game_rel
        parts = a.split("/")
        return parts[1] if len(parts) > 2 and parts[0] == "art" else parts[0]

    def godot_ref(self, game_rel):
        return self.arel(game_rel) if self.exists(game_rel) and self.arel(game_rel) else None

    def add(self, asset):
        asset = {k: v for k, v in asset.items() if v is not None}
        asset["name"] = _safe_name(asset["name"])
        names = {(a["kind"], a["name"]) for a in self.assets}
        base, n = asset["name"], 2
        while (asset["kind"], asset["name"]) in names:
            asset["name"] = f"{base}_{n}"
            n += 1
        self.assets.append(asset)
        return asset

    def use(self, *game_rels):
        self.used.update(game_rels)

    # ---- records ---------------------------------------------------------------------------
    def animated(self, key, rec):
        frames_dir = self.game_of_res(rec["res_dir"]).rstrip("/")
        anims = rec.get("animations") or {}
        stem = posixpath.basename(key)[:-len(".tres")] if key.endswith(".tres") else posixpath.basename(key)
        stem = re.sub(r"_frames$", "", stem)
        clips, blend, used = [], "normal", []
        for anim, (files, fps, loop, holds) in anims.items():
            paths = [posixpath.join(frames_dir, f) for f in files]
            if not paths or not all(self.exists(p) and self.arel(p) for p in paths):
                self.warnings.append(f"{key}: animation {anim} names frames that are not in the game; skipped")
                return
            sizes = {tuple(self.size(p)) for p in paths}
            if len(sizes) != 1:
                self.warnings.append(f"{key}: animation {anim} has frames of {len(sizes)} sizes; skipped")
                return
            fw, fh = sizes.pop()
            anchor = next((self.by_file[p]["anchor"] for p in paths if self.by_file.get(p, {}).get("anchor")), None)
            if any(self.by_file.get(p, {}).get("blend") == "add" for p in paths):
                blend = "add"
            sheet = self.find_sheet(anim, frames_dir, stem, fw, fh, len(paths), used)
            frames = []
            for i, p in enumerate(paths):
                hold = holds[i] if holds else 1.0
                frames.append({"file": self.arel(p), "rect": [i * fw, 0, fw, fh] if sheet else [0, 0, fw, fh],
                               "duration": hold / fps})
            clip = {"name": anim, "fps": _num(fps), "loop": bool(loop),
                    "holds": [_num(h) for h in holds] if holds else None, "frame_size": [fw, fh],
                    "pivot": pivot_of(anchor, fw, fh), "sheet": self.arel(sheet) if sheet else None,
                    "frames": frames, "length": sum(f["duration"] for f in frames)}
            clips.append({k: v for k, v in clip.items() if v is not None})
            used += paths + ([sheet, sheet[:-4] + ".json"] if sheet else [])
        if not clips:
            return
        dirs = {}
        for c in clips:
            m = DIR_CLIP.match(c["name"])
            if m:
                dirs.setdefault(m.group(1), {})[m.group(2)] = c["name"]
        self.use(*used)
        self.add({"kind": "animated_sprite", "name": stem, "role": self.role(frames_dir + "/x"),
                  "blend": blend, "clips": clips, "directions": dirs or None, "godot": self.godot_ref(key)})

    def find_sheet(self, anim, frames_dir, stem, fw, fh, n, claimed):
        """The horizontal strip Dotwork ships beside the frames for other engines: the sheet row naming this
        animation, else <anything>_<anim>_sheet.png (characters, status, trails), else <asset>_sheet.png (a spell's or
        projectile's main clip); in the frames' folder or its parent, unclaimed, and exactly n frames of fw x fh."""
        parent = posixpath.dirname(frames_dir)
        cands = [r["file"] for r in self.rows if r.get("kind") == "sheet" and r["file"].endswith(".png")
                 and posixpath.dirname(r["file"]) in (frames_dir, parent) and self.exists(r["file"])
                 and r["file"] not in claimed and r["file"] not in self.used]
        named = {f: self.by_file[f] for f in cands}
        pick = ([f for f in cands if named[f].get("animation") == anim]
                + [f for f in cands if posixpath.basename(f).endswith(f"_{anim}_sheet.png")]
                + [f for f in cands if posixpath.basename(f) == f"{stem}_sheet.png" and not named[f].get("animation")])
        for f in pick:
            if self.size(f) == [fw * n, fh]:
                return f
        return None

    def prop(self, key, rec):
        tex = self.game_of_res(rec["texture"])
        if not (self.exists(tex) and self.arel(tex)):
            return
        self.sprite(tex, "props", rec["bbox"], rec["offset"], rec["footprint"] if rec.get("solid") else None,
                    rec.get("shape_y"), self.godot_ref(key))

    def sprite(self, tex, role, bbox, off, footprint=None, shape_y=None, godot_ref=None, shadow=None):
        w, h = self.size(tex)
        px, py = _num(w / 2 - off[0]), _num(h / 2 - off[1])
        coll = None
        if footprint:
            fw, fh = footprint
            coll = [{"rect": [_num(px - fw / 2), _num(py + shape_y - fh / 2), fw, fh]}]
        x0, y0, x1, y1 = bbox
        name = re.sub(r"^spr_", "", posixpath.basename(tex)[:-4])
        self.use(tex)
        self.add({"kind": "sprite", "name": name, "role": role, "image": self.arel(tex), "size": [w, h],
                  "pivot": [px, py], "content_rect": [x0, y0, x1 - x0, y1 - y0], "collision": coll,
                  "shadow": shadow, "godot": godot_ref})

    def tileset(self, key, rec):
        tw, th = rec["tile_size"]
        sets_in = rec.get("terrain_sets")
        if sets_in is None:
            sets_in = [{"mode": rec.get("mode", "match_corners"), "terrains": rec.get("terrains") or []}]
        sets = [{"id": i, "mode": MODES[s["mode"]],
                 "terrains": [{"id": j, "name": str(t[0]), "color": _hex(t[1])} for j, t in enumerate(s["terrains"])]}
                for i, s in enumerate(sets_in) if s.get("terrains")]
        physics = rec.get("physics", True)
        atlases, stamps, used = [], [], []
        for i, src in enumerate(rec["sources"]):
            img = self.game_of_res(src["atlas_res"])
            if not (self.exists(img) and self.arel(img)):
                self.warnings.append(f"{key}: atlas {img} is not in the game; tileset skipped")
                return
            used.append(img)
            rw, rh = src.get("region") or [tw, th]
            W, H = self.size(img)
            tiles = [self.tile(t, tw, th, rw, rh, physics, bool(rec.get("custom"))) for t in src["tiles"]]
            atlases.append({"id": i, "name": src.get("name") or posixpath.basename(img)[:-4],
                            "role": src.get("kind") or "atlas", "image": self.arel(img), "tile_size": [rw, rh],
                            "columns": max(1, W // rw), "rows": max(1, H // rh), "tiles": tiles})
            cols = src.get("cols", 12)
            for fname, f in sorted((src.get("fixtures") or {}).items()):
                stamps.append({"name": fname, "size": [f["w"], f["h"]], "solid": bool(f.get("solid")),
                               "tiles": [[i, (f["first"] + j) % cols, (f["first"] + j) // cols]
                                         for j in range(f["w"] * f["h"])]})
        stem = posixpath.basename(key)[:-len(".tres")]
        self.use(*used)
        return self.add({"kind": "tileset", "name": re.sub(r"_tileset$", "", stem), "tile_size": [tw, th],
                         "shape": rec.get("shape", "square"), "terrain_sets": sets, "atlases": atlases,
                         "stamps": stamps or None, "custom_data": rec.get("custom") or None,
                         "godot": self.godot_ref(key)})

    @staticmethod
    def tile(t, tw, th, rw, rh, physics, custom):
        """One Godot atlas tile (as godot.tileset_layers takes it) -> a neutral tile."""
        d = {"col": int(t["x"]), "row": int(t["y"])}
        tid = t.get("terrain")
        if tid is not None and tid >= 0:
            d["terrain_set"] = int(t.get("terrain_set", 0))
            d["terrain"] = int(tid)
            if "peers" in t:   # 8 peering bits N, NE, E, SE, S, SW, W, NW: set where the peer is this terrain
                d["mask"] = sum(1 << b for b, p in enumerate(t["peers"]) if p == tid)
            elif isinstance(t.get("corners"), dict):
                d["corners"] = {k: int(v) for k, v in t["corners"].items()}
            elif t.get("corners") is not None:
                d["corners"] = {k: int(v) for k, v in zip(SQUARE_CORNERS, t["corners"])}
        if t.get("probability", 1.0) != 1.0:
            d["probability"] = t["probability"]
        if custom and t.get("custom") is not None:
            d["surface"] = str(t["custom"])
        coll = []
        if physics:
            h = tw // 2   # godot._quad: quadrant boxes in tile-centre coordinates
            for ci in t.get("solid") or []:
                x0, y0 = (-h if ci in (0, 2) else 0), (-h if ci in (0, 1) else 0)
                coll.append([x0, y0, x0 + h, y0 + h])
            coll += [list(r) for r in t.get("solid_rects") or []]
        if coll:   # centre coordinates -> the tile's top-left corner, as [x, y, w, h]
            d["collision"] = [dict({"rect": [_num(x0 + tw / 2), _num(y0 + th / 2), x1 - x0, y1 - y0]},
                                   **({"one_way": True} if t.get("one_way") else {}))
                              for x0, y0, x1, y1 in coll]
        if t.get("anim"):
            d["anim"] = {"frames": int(t["anim"]["frames"]), "fps": _num(float(t["anim"]["fps"]))}
        if t.get("origin_y"):   # Godot texture_origin: the image is drawn this far up from the cell centre
            d["origin"] = [_num(rw / 2), _num(rh / 2 + t["origin_y"])]
        return d

    def map(self, key, rec, tilesets):
        ts = tilesets.get(self.game_of_res(rec["tileset"]))
        if ts is None:
            self.warnings.append(f"{key}: its tileset {rec['tileset']} is not in this pack; map skipped")
            return
        T = int(rec["tile_px"])
        tile_size = [int(v) for v in rec["tile_size"]] if rec.get("tile_size") else [T, T]   # an iso map's diamond
        stamp_index = {s["name"]: i for i, s in enumerate(ts.get("stamps") or [])}
        layers = []
        for L in rec["layers"]:
            if L["kind"] == "terrain":
                layers.append({"name": L["name"], "kind": "terrain", "terrain_set": int(L.get("terrain_set", 0)),
                               "terrain": int(L["terrain"]), "cells": [[int(c[0]), int(c[1])] for c in L["cells"]]})
            elif L.get("stamps") and all(s[2] in stamp_index for s in L["stamps"]):
                # mapbuild expands fixtures into cells for Godot's painter and names the stamps it placed: the
                # manifest keeps the stamps (kind "stamps", 1.1.0), so every engine places the whole piece
                layers.append({"name": L["name"], "kind": "stamps",
                               "cells": [[int(s[0]), int(s[1]), stamp_index[s[2]]] for s in L["stamps"]]})
            else:
                layers.append({"name": L["name"], "kind": "tiles", "cells": [[int(v) for v in c[:5]] for c in L["cells"]]})
        objects = [{"asset": _safe_name(p["name"]), "x": _num(p["x"]), "y": _num(p["y"])} for p in rec.get("props") or []]
        self.add({"kind": "map", "name": posixpath.basename(key)[:-len(".tscn")], "tileset": ts["name"],
                  "size": [int(rec["w"]), int(rec["h"])], "tile_size": tile_size, "layers": layers,
                  "objects": objects or None, "godot": self.godot_ref(key)})

    # ---- rows ---------------------------------------------------------------------------------
    def free_rows(self, kinds=None):
        return [r for r in self.rows if r["file"] not in self.used and (kinds is None or r.get("kind") in kinds)
                and self.arel(r["file"]) is not None and self.exists(r["file"])]

    def icons(self):
        groups = {}
        for r in self.free_rows(("icon",)):
            m = re.match(r"ui_icon_(.+)_(\d+)\.png$", posixpath.basename(r["file"]))
            if m:
                groups.setdefault(m.group(1), []).append((int(m.group(2)), r["file"]))
        for name, sizes in sorted(groups.items()):
            self.use(*[f for _, f in sizes])
            self.add({"kind": "icon", "name": name,
                      "sizes": [{"size": s, "image": self.arel(f)} for s, f in sorted(sizes)]})

    def portraits(self):
        groups = {}
        for r in self.rows:   # every portrait row: the talking frames' animated sprite shares some of these files
            if r.get("kind") != "portrait" or not self.arel(r["file"]) or not self.exists(r["file"]):
                continue
            m = re.match(r"spr_(.+)_portrait(?:_(.+))?\.png$", posixpath.basename(r["file"]))
            if m:
                groups.setdefault(m.group(1), []).append((r.get("expression") or m.group(2) or "neutral", r["file"]))
        anims = {a["name"] for a in self.assets if a["kind"] == "animated_sprite"}
        for name, ex in sorted(groups.items()):
            ex.sort(key=lambda e: (e[0] != "neutral", e[0]))
            self.use(*[f for _, f in ex])
            self.add({"kind": "portrait", "name": name, "size": self.size(ex[0][1]),
                      "expressions": [{"name": _safe_name(n), "image": self.arel(f)} for n, f in ex],
                      "animation": f"portrait_{name}" if f"portrait_{name}" in anims else None})

    def enemies(self):
        for r in self.free_rows(("enemy",)):
            f = r["file"]
            w, h = self.size(f)
            bb = r.get("content_bbox") or [0, 0, w, h]
            off = [0, round(h / 2 - bb[3])]   # lane_enemies: centred Sprite2D, the content bottom (feet) on y = 0
            sh = f[:-4] + "_shadow.png"
            shadow = None
            if sh in self.by_file and self.exists(sh):
                shadow = {"image": self.arel(sh), "offset": [_num(self.by_file[sh].get("offset_x", 0)), 0]}
                self.use(sh)
            scn = posixpath.join(posixpath.dirname(f), "enemy_" + re.sub(r"^spr_enemy_", "", posixpath.basename(f))[:-4] + ".tscn")
            self.sprite(f, self.role(f), bb, [off[0], off[1]], godot_ref=self.godot_ref(scn), shadow=shadow)

    def plain_props(self):
        """Props without a scene record ("scene": false): the same origin as a scene would give, no collision."""
        for r in self.free_rows(("prop",)):
            w, h = self.size(r["file"])
            bb = r.get("content_bbox") or [0, 0, w, h]
            off, _ = godot.prop_geometry((w, h), bb)
            self.sprite(r["file"], "props", bb, off)

    def backgrounds(self):
        for r in self.free_rows(("battle_bg",)):
            f = r["file"]
            stem = posixpath.basename(f)[:-4]
            layers = [self.layer(f, [0, 0], "none", scale=r.get("display_scale"))]
            for lr in sorted(self.free_rows(("battle_bg_layer",)), key=lambda x: x["file"]):
                if posixpath.dirname(lr["file"]) == posixpath.dirname(f) and posixpath.basename(lr["file"]).startswith(stem + "_"):
                    layers.append(self.layer(lr["file"], [_num(lr.get("scroll_px_per_s", 0)), 0], "x",
                                             name=posixpath.basename(lr["file"])[len(stem) + 1:-4],
                                             scale=r.get("display_scale")))
            self.add({"kind": "background", "name": re.sub(r"^spr_bg_", "", stem), "role": "battle", "layers": layers})
        for r in self.free_rows(BACKDROP_KINDS):
            if not r["file"].endswith(".png"):
                continue
            rep = "x" if r.get("seamless") == "horizontal" else "none"
            self.add({"kind": "background", "name": re.sub(r"^spr_", "", posixpath.basename(r["file"])[:-4]),
                      "role": self.role(r["file"]), "layers": [self.layer(r["file"], [0, 0], rep)]})
        groups = {}
        for r in self.free_rows(("weather_tile",)):
            m = re.match(r"weather_(.+)_" + re.escape(str(r.get("layer", ""))) + r"\.png$", posixpath.basename(r["file"]))
            groups.setdefault(m.group(1) if m else posixpath.basename(r["file"])[:-4], []).append(r)
        for name, rs in sorted(groups.items()):
            self.add({"kind": "background", "name": f"weather_{name}", "role": "weather", "layers": [
                self.layer(r["file"], [_num(v) for v in r.get("velocity_px_s", [0, 0])], "xy", name=r.get("layer"),
                           wobble=r.get("wobble_px")) for r in rs]})

    def layer(self, f, vel, rep, name=None, wobble=None, scale=None):
        self.use(f)
        return {k: v for k, v in {"name": name, "image": self.arel(f), "size": self.size(f), "velocity": vel,
                                  "repeat": rep, "wobble_px": wobble, "scale": scale}.items() if v is not None}

    def fonts(self):
        for r in self.free_rows(("font",)):
            f = r["file"]
            if not f.endswith(".fnt"):
                continue
            parsed = parse_fnt(self.full(f))
            folder = posixpath.dirname(f)
            pages = [posixpath.join(folder, p) for p in parsed["pages"]]
            if not all(self.exists(p) for p in pages):
                self.warnings.append(f"{f}: a page named in the font is missing; font skipped")
                continue
            lic = next((x["file"] for x in self.rows if x.get("kind") == "license"
                        and posixpath.dirname(x["file"]) == folder and self.exists(x["file"])), None)
            page_row = self.by_file.get(pages[0], {})
            self.use(f, *pages, *([lic] if lic else []))
            self.add({"kind": "font", "name": re.sub(r"^font_", "", posixpath.basename(f)[:-4]), "file": self.arel(f),
                      "pages": [self.arel(p) for p in pages], "line_height": parsed["line_height"],
                      "base": parsed["base"], "scale": int(r.get("scale") or page_row.get("scale") or 1),
                      "tint": not r.get("gradient"), "chars": parsed["chars"], "kerning": parsed["kerning"] or None,
                      "license": self.arel(lic) if lic else None})

    def ui(self):
        groups = {}
        for r in self.free_rows(UI_KINDS):
            if r["file"].endswith(".png"):
                groups.setdefault(posixpath.dirname(r["file"]), []).append(r)
        for folder, rs in sorted(groups.items()):
            parts = []
            for r in sorted(rs, key=lambda x: x["file"]):
                f = r["file"]
                w, h = self.size(f)
                m = r.get("patch_margins") or r.get("margins")
                if isinstance(m, dict):
                    m = [m.get("left", 0), m.get("top", 0), m.get("right", 0), m.get("bottom", 0)]
                elif r.get("patch_margin") is not None:
                    m = [int(r["patch_margin"])] * 4
                parts.append({k: v for k, v in {
                    "name": _safe_name(posixpath.basename(f)[:-4]), "role": r["kind"].replace("ui_", ""),
                    "image": self.arel(f), "size": [w, h], "scale": int(r.get("scale") or 1),
                    "state": r.get("state"), "control": r.get("gauge"), "margins": [int(v) for v in m] if m else None,
                    "stretch_margin": r.get("stretch_margin"), "hotspot": r.get("hotspot"),
                    "glyph": r.get("glyph") or r.get("symbol")}.items() if v is not None})
                self.use(f)
            rel = self.arel(folder) or folder
            self.add({"kind": "ui_kit", "name": rel.split("/")[-1], "role": "/".join(rel.split("/")[1:-1]) or "ui",
                      "parts": parts})

    def particles(self):
        for r in self.free_rows(("particles_json",)):
            folder = posixpath.dirname(r["file"])
            tex = next((x["file"] for x in self.rows if x.get("kind") == "particle_texture"
                        and posixpath.dirname(x["file"]) == folder and x["file"] not in self.used
                        and self.exists(x["file"])), None)
            if tex is None:
                continue
            with open(self.full(r["file"]), encoding="utf-8") as fh:
                emitter = json.load(fh)
            self.use(r["file"], tex)
            self.add({"kind": "particles", "name": posixpath.basename(r["file"])[:-5], "texture": self.arel(tex),
                      "emitter": emitter})

    def simple(self):
        for r in self.free_rows(("transition_rule",)):
            self.use(r["file"])
            self.add({"kind": "transition", "name": posixpath.basename(r["file"])[:-4], "image": self.arel(r["file"]),
                      "size": self.size(r["file"]), "transition": str(r.get("transition", ""))})
        for r in self.free_rows(("normal_map",)):
            target = r.get("pairs_with")
            if not target or not self.arel(target) or not self.exists(target) or not r["file"].endswith(".png"):
                continue
            self.use(r["file"])
            self.add({"kind": "normal_map", "name": posixpath.basename(r["file"])[:-4], "image": self.arel(r["file"]),
                      "size": self.size(r["file"]), "target": self.arel(target), "convention": "opengl"})

    def tilemaps(self, tilesets):
        """Pixelorama tilemaps (pxo_tiles: <name>_map.json beside <name>_tileset.tres): one map per frame."""
        for r in self.free_rows(("map_data",)):
            f = r["file"]
            ts = tilesets.get(f[:-len("_map.json")] + "_tileset.tres")
            if ts is None:
                continue
            with open(self.full(f), encoding="utf-8") as fh:
                doc = json.load(fh)
            cols = int(doc.get("columns", 16))
            frames = doc.get("frames") or []
            stem = posixpath.basename(f)[:-len("_map.json")]
            for k, layers in enumerate(frames):
                out, xs, ys = [], [0], [0]
                for L in layers:
                    cells = []
                    for x, y, j, fl in L["cells"]:
                        if j <= 0:
                            continue
                        cell = [x, y, int(L["tileset"]), (j - 1) % cols, (j - 1) // cols] + ([fl] if fl else [])
                        cells.append(cell)
                        xs.append(x)
                        ys.append(y)
                    out.append({"name": L["name"], "kind": "tiles", "cells": cells,
                                "opacity": L.get("opacity") if L.get("opacity", 1) != 1 else None})
                if min(xs) < 0 or min(ys) < 0:
                    self.warnings.append(f"{f}: cells left of or above 0,0; map skipped")
                    continue
                self.add({"kind": "map", "name": stem if len(frames) == 1 else f"{stem}_{k:02d}", "tileset": ts["name"],
                          "size": [max(xs) + 1, max(ys) + 1], "tile_size": list(doc["tile_size"]),
                          "layers": [{k2: v for k2, v in L.items() if v is not None} for L in out]})
            self.use(f)

    def leftovers(self):
        for r in self.free_rows():
            f = r["file"]
            if not f.lower().endswith(".png"):
                continue
            self.use(f)
            w, h = self.size(f)
            self.add({"kind": "image", "name": posixpath.basename(f)[:-4], "role": r.get("kind", "image"),
                      "image": self.arel(f), "size": [w, h],
                      "pivot": pivot_of(r["anchor"], w, h) if r.get("anchor") else None})

    # ---- all ------------------------------------------------------------------------------------
    def build(self):
        ents = sorted(self.ents.items())
        for key, rec in ents:
            if rec.get("kind") == "frames":
                self.animated(key, rec)
        tilesets = {}
        for key, rec in ents:
            if rec.get("kind") == "tileset":
                ts = self.tileset(key, rec)
                if ts:
                    tilesets[key] = ts
        for key, rec in ents:
            if rec.get("kind") == "prop":
                self.prop(key, rec)
            elif rec.get("kind") == "map":
                self.map(key, rec, tilesets)
        self.icons()
        self.portraits()
        self.enemies()
        self.plain_props()
        self.backgrounds()
        self.fonts()
        self.ui()
        self.particles()
        self.simple()
        self.tilemaps(tilesets)
        self.leftovers()
        self.assets.sort(key=lambda a: (KIND_ORDER[a["kind"]], a["name"]))
        return {"format": assetspec.FORMAT, "version": assetspec.VERSION, "pack": str(self.pack),
                "generator": GENERATOR, "base": "..", "assets": self.assets}


def parse_fnt(path):
    """An AngelCode BMFont text file -> pages, metrics, chars [id, x, y, w, h, xoffset, yoffset, xadvance, page] and
    kerning [first, second, amount]."""
    out = {"pages": [], "line_height": 1, "base": 0, "chars": [], "kerning": []}
    pages = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            tag, _, rest = line.strip().partition(" ")
            kv = dict(re.findall(r'(\w+)=("[^"]*"|\S+)', rest))
            val = {k: v.strip('"') for k, v in kv.items()}
            if tag == "common":
                out["line_height"], out["base"] = int(val["lineHeight"]), int(val["base"])
            elif tag == "page":
                pages[int(val["id"])] = val["file"]
            elif tag == "char":
                out["chars"].append([int(val[k]) for k in ("id", "x", "y", "width", "height", "xoffset", "yoffset",
                                                           "xadvance", "page")])
            elif tag == "kerning":
                out["kerning"].append([int(val["first"]), int(val["second"]), int(val["amount"])])
    out["pages"] = [pages[k] for k in sorted(pages)]
    out["chars"].sort()
    return out


def build(project, assets_dir, data, pack):
    """(document, warnings) for one pack's provenance manifest data."""
    w = Writer(project, assets_dir, data, pack)
    return w.build(), w.warnings


def text_of(doc):
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def write(project, assets_dir, data, pack):
    """Write <assets_dir>/dotwork/<pack>.assets.json when its text changed. Returns (path, changed, warnings)."""
    doc, warns = build(project, assets_dir, data, pack)
    path = manifest_path(os.path.join(project, assets_dir), pack)
    text = text_of(doc)
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return path, False, warns
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path, True, warns
