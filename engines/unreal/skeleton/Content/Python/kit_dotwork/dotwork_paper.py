# ---------------------------------------------------------------------------
# dotwork_paper.py
# Purpose : Turns a Dotwork asset manifest (tools/art/dotwork/ASSET_MANIFEST.md) into Paper2D assets, and reads
#           those assets back into the manifest's "loaded result" (data/golden/dotwork/expected.json) so a test can
#           prove they hold the same numbers.
# Usage   : imp = dotwork_paper.Importer("assets/dotwork/town.assets.json"); imp.run(); imp.save()
#           Importer(path, transient=True) builds into the transient package (tests); loaded(imp) reads back.
#           The script to run: python tools/dev.py exec Content/Python/kit_dotwork/import_dotwork.py
# Notes   : What each kind becomes (under /Game/Dotwork/<pack>/):
#             every PNG          Textures/<its folder>/T_<file>: nearest filter, no mips, uncompressed, Pixels2D group,
#                                clamped (background layers wrap on their repeat axes; normal maps linear)
#             sprite             Sprites/S_<name>: custom pivot, collision boxes (Use 3D Physics)
#             animated_sprite    Sprites/<name>/S_<name>_<clip>_<i> per frame, Flipbooks/FB_<name>_<clip> per clip at
#                                a rate where every frame's duration is a whole frame run (dotwork_spec.flipbook_rate)
#             icon               textures only (one per size)
#             portrait           Sprites/S_<name>_<expression> per expression; talking: the animated_sprite's flipbooks
#             font               Fonts/F_<name>: an offline Font (Characters from chars, the pages as its textures)
#             ui_kit             UI/SB_<kit>_<part>: a Slate Brush asset (Box with the 9-slice margins, else Image)
#             tileset            TileSets/TS_<name>_<atlas>: one PaperTileSet per atlas, per-tile collision boxes,
#                                the surface as each tile's user data name, and the DrawingOffset that puts the
#                                atlas's tiles where the spec draws them (centre minus origin; taller iso blocks)
#             map                Maps/TM_<name>: a PaperTileMap (Orthogonal or IsometricDiamond), terrain layers
#                                resolved by cell_mask and the variant pick (Paper2D has no autotiling), stamps
#                                layers expanded, layer 0 on top as Paper2D draws it
#             particles          the mask texture, its emitter JSON as the texture's dotwork.emitter metadata tag
#           Facts no Paper2D type holds go into the asset's metadata tags (dotwork.loop, dotwork.blend,
#           dotwork.directions, dotwork.hotspot, dotwork.objects, dotwork.animated_tiles, dotwork.emitter ...).
#           Where a map pixel is: Paper2D centres cell (0, 0) on the tile map's origin in both projections
#           (UPaperTileMap::GetTileToLocalParameters: the orthogonal corner is (-w/2, +h/2), the diamond's steps are
#           (w/2, -h/2) and (-w/2, -h/2) in its X right, Z up plane), so the spec's map pixel (px, py), y down,
#           is local (px - w/2, 0, -(py - h/2)) (map_to_local); its diamond grid is Godot's, no cell conversion.
#           Two properties are hidden from Python: a tile layer's name (UPaperTileLayer::LayerName: the layers come
#           from Paper2D's own Tiled importer, which names them) and an offline font's page textures (UFont::Textures:
#           set with the `set` console command, which only the pythonscript commandlet runs, so fonts are imported
#           through `dev.py exec`; a full editor session builds the font without pages and says so).
#           Re-running updates the assets in place (same names), so levels and Blueprints that use them keep working.
#           Pseudocode
#             load + version check; texture(rel) imports a PNG once per path
#             core kinds in build order (sprite, animated_sprite, icon, portrait, font, ui_kit, tileset, map),
#             then background / particles / transition / normal_map / image as textures; unknown kinds: one warning
#             map: a PaperTileMapComponent owns a scratch map (SetTile only edits a map its component owns); its layers
#             move into the TM_ asset
#             a failing asset is an error line; run() raises after trying every asset
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): corners4 terrain, the variant
#           pick by layer index, stamps layers, DrawingOffset from the tiles' origins, the loaded result's placed cells
#           and centres read back from Paper2D, particles loaded (texture + emitter tag)
# ---------------------------------------------------------------------------
import json
import os
import re
import uuid

import unreal

from kit_dotwork import dotwork_spec as spec

# ---- Tunables ------------------------------------------------------------------
DEST_ROOT = "/Game/Dotwork"                 # assets of pack <p> go to /Game/Dotwork/<p>
TRANSIENT_TEXTURES = "/Temp/DotworkImport"  # tests: textures here, every other object in the transient package
PIXELS_PER_UNIT = 1.0                       # one art pixel = one Unreal unit (cm); Paper2D's sprite default
META = "dotwork."                           # metadata tag prefix
SKIPPED_KINDS = ()                          # every spec 1.1.0 kind is built (particles: texture + emitter tag, #286
                                            # for a Niagara system); unknown kinds get one warning
FLIP_BITS = {1: 1 << 31, 2: 1 << 30, 4: 1 << 29}   # manifest flags -> EPaperTileFlags (H, V, diagonal)
PROJECTION = {"square": "ORTHOGONAL", "isometric": "ISOMETRIC_DIAMOND"}   # tileset shape -> TileMapProjectionMode
TILE_INDEX_MASK = ~(7 << 29)
BAD_NAME = re.compile(r"[^A-Za-z0-9_]")


def slate_vector(x, y):
    """FSlateBrush::ImageSize: a DeprecateSlateVector2D in UE 5.x (no constructor arguments), a Vector2D before."""
    cls = getattr(unreal, "DeprecateSlateVector2D", None)
    if cls is None:
        return unreal.Vector2D(x, y)
    v = cls()
    v.import_text(f"(X={x},Y={y})")
    return v


def transient_package():
    """/Engine/Transient: objects here are never saved (Python has no get_transient_package)."""
    return unreal.find_object(None, "/Engine/Transient")


def safe(name):
    """An asset or folder name Unreal accepts (manifest names may hold . and -)."""
    return BAD_NAME.sub("_", str(name))


def map_to_local(px, py, tile_size):
    """A map pixel (x right, y down, cell (0, 0)'s top-left at (0, 0)) as a Paper2D local position (X, Z) in the
    tile map's X right, Z up plane: Paper2D centres cell (0, 0) on the origin in both projections."""
    return px - tile_size[0] / 2, -(py - tile_size[1] / 2)


def local_to_map(vec, tile_size):
    """The inverse: a Paper2D local position (an unreal.Vector) as a map pixel [px, py]."""
    return [vec.x + tile_size[0] / 2, -vec.z + tile_size[1] / 2]


def say(text):
    unreal.log(f"[dotwork] {text}")


class ImportFailed(Exception):
    """One or more assets of a manifest could not be built (each reason is logged as an error)."""


class Importer:
    """Builds one manifest's Paper2D assets. records[<kind>/<name>] keeps what was built, for loaded()."""

    def __init__(self, manifest_path, dest=None, transient=False):
        self.path = os.path.abspath(manifest_path)
        self.doc = spec.load(self.path)
        self.base = spec.base_dir(self.path, self.doc)
        self.pack = safe(self.doc.get("pack", "pack"))
        self.transient = transient
        self.run_id = uuid.uuid4().hex[:8]
        self.dest = dest or f"{DEST_ROOT}/{self.pack}"
        self.tex_root = f"{TRANSIENT_TEXTURES}/{self.run_id}/{self.pack}" if transient else f"{self.dest}/Textures"
        self.tools = unreal.AssetToolsHelpers.get_asset_tools()
        self.textures, self.tex_rel = {}, {}
        self.records, self.made, self.errors, self.warnings = {}, [], [], []
        self.font_pages_blocked = False             # True in a full editor session (see _font)

    # ---- helpers -------------------------------------------------------------------------------
    def warn(self, text):
        self.warnings.append(text)
        unreal.log_warning(f"[dotwork] {self.pack}: {text}")

    def new(self, cls, factory, folder, name):
        """An asset to fill: the existing one at folder/name (updated in place), a new one, or (transient) a new
        object in the transient package."""
        name = safe(name)
        if self.transient:
            return unreal.new_object(cls, transient_package(), f"{name}_{self.run_id}")
        path = f"{folder}/{name}"
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            obj = unreal.load_asset(path)
            if not isinstance(obj, cls):
                raise RuntimeError(f"{path} exists and is a {obj.get_class().get_name()}, not a {cls.__name__}")
        else:
            obj = self.tools.create_asset(name, folder, cls, factory() if factory else None)
            if obj is None:
                raise RuntimeError(f"could not create {path}")
        self.made.append(obj)
        return obj

    def tag(self, obj, key, value):
        """A metadata tag on a saved asset (the transient objects of a test have no package to hold one)."""
        if not self.transient:
            unreal.EditorAssetLibrary.set_metadata_tag(obj, META + key, value if isinstance(value, str)
                                                       else json.dumps(value, separators=(",", ":")))

    def console_set(self, obj, prop, text):
        """Sets a property Python cannot reach through the `set` console command (ImportText + PostEditChange)."""
        unreal.SystemLibrary.execute_console_command(None, f"set {obj.get_path_name()} {prop} {text}")

    def texture(self, rel, repeat="none", normal=False):
        """The texture of a manifest PNG, imported once per path with the pixel-art settings."""
        if rel in self.textures:
            return self.textures[rel]
        src = spec.resolve(self.base, rel)
        if not os.path.isfile(src):
            raise spec.ManifestError(f"{rel} not found under {self.base}")
        folder = "/".join([self.tex_root] + [safe(p) for p in rel.split("/")[:-1]])
        name = "T_" + safe(os.path.splitext(rel.split("/")[-1])[0])
        task = unreal.AssetImportTask()
        for key, value in (("filename", src), ("destination_path", folder), ("destination_name", name),
                           ("automated", True), ("replace_existing", True), ("save", False)):
            task.set_editor_property(key, value)
        self.tools.import_asset_tasks([task])
        paths = task.get_editor_property("imported_object_paths")
        tex = unreal.load_asset(paths[0]) if paths else None
        if not isinstance(tex, unreal.Texture2D):
            raise RuntimeError(f"could not import {rel} as a texture")
        wrap, clamp = unreal.TextureAddress.TA_WRAP, unreal.TextureAddress.TA_CLAMP
        tex.set_editor_properties({
            "srgb": not normal,
            "compression_settings": (unreal.TextureCompressionSettings.TC_NORMALMAP if normal
                                     else unreal.TextureCompressionSettings.TC_EDITOR_ICON),
            "lod_group": unreal.TextureGroup.TEXTUREGROUP_PIXELS2D,
            "filter": unreal.TextureFilter.TF_NEAREST,
            "mip_gen_settings": unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS,
            "address_x": wrap if "x" in repeat else clamp,
            "address_y": wrap if "y" in repeat else clamp})
        self.tag(tex, "file", rel)
        self.textures[rel] = tex
        self.tex_rel[tex.get_path_name()] = rel
        if not self.transient:
            self.made.append(tex)
        return tex

    def sprite(self, folder, name, tex, rect, pivot, collision=()):
        """A PaperSprite on rect of tex; pivot and collision rects in the rect's own pixels (y down: Paper2D's
        texture space is y down too and flips to its X right, Z up plane itself)."""
        x, y, w, h = rect
        sp = self.new(unreal.PaperSprite, unreal.PaperSpriteFactory, folder, name)
        sp.set_editor_property("source_texture", tex)
        sp.set_editor_property("source_uv", unreal.Vector2D(x, y))
        sp.set_editor_property("source_dimension", unreal.Vector2D(w, h))
        sp.set_editor_property("snap_pivot_to_pixel_grid", False)   # a centred pivot on an odd size is a half pixel
        sp.set_editor_property("pivot_mode", unreal.SpritePivotMode.CUSTOM)
        sp.set_editor_property("custom_pivot_point", unreal.Vector2D(x + pivot[0], y + pivot[1]))
        sp.set_editor_property("pixels_per_unreal_unit", PIXELS_PER_UNIT)
        geometry = sp.get_editor_property("collision_geometry")
        geometry.set_editor_property("geometry_type", unreal.SpritePolygonMode.FULLY_CUSTOM)
        geometry.set_editor_property("shapes", [box_shape(x + r[0], y + r[1], r[2], r[3]) for r in collision])
        sp.set_editor_property("collision_geometry", geometry)
        sp.set_editor_property("sprite_collision_domain", unreal.SpriteCollisionMode.USE3D_PHYSICS if collision
                               else unreal.SpriteCollisionMode.NONE)
        return sp

    # ---- the run -------------------------------------------------------------------------------
    def run(self):
        """Builds every asset; raises ImportFailed after trying them all when any failed."""
        core, extra, skipped = spec.ordered(self.doc["assets"])
        for a in core + extra:
            key = f"{a['kind']}/{a.get('name')}"
            try:
                getattr(self, "_" + (a["kind"] if a["kind"] in spec.CORE_ORDER else "texture_only"))(a)
            except Exception as exc:          # one broken asset must not hide the others
                self.errors.append(f"{key}: {exc}")
                unreal.log_error(f"[dotwork] {self.pack}: {key}: {exc}")
        for kind in sorted({a.get("kind") for a in skipped}):
            n = sum(1 for a in skipped if a.get("kind") == kind)
            why = "not built in Unreal yet" if kind in SKIPPED_KINDS else "unknown kind (newer spec?)"
            self.warn(f"skipped {n} {kind} asset(s): {why}")
        if self.errors:
            raise ImportFailed(f"{self.pack}: {len(self.errors)} asset(s) failed: " + "; ".join(self.errors))
        say(f"{self.pack}: built {len(self.records)} asset(s) from {os.path.basename(self.path)}"
            + (f", {len(self.warnings)} warning(s)" if self.warnings else ""))
        return self

    def save(self):
        """Writes every created or updated asset (nothing to save in transient mode)."""
        for obj in self.made:
            if not unreal.EditorAssetLibrary.save_loaded_asset(obj, False):
                raise ImportFailed(f"could not save {obj.get_path_name()}")
        say(f"{self.pack}: saved {len(self.made)} asset(s) under {self.dest}")

    # ---- core kinds ------------------------------------------------------------------------------
    def _sprite(self, a):
        tex = self.texture(a["image"])
        w, h = a["size"]
        sp = self.sprite(f"{self.dest}/Sprites", f"S_{a['name']}", tex, [0, 0, w, h], a["pivot"],
                         [c["rect"] for c in a.get("collision") or []])
        rec = {"kind": "sprite", "sprite": sp}
        if a.get("shadow"):
            sh = a["shadow"]
            stex = self.texture(sh["image"])
            sw, shh = stex.blueprint_get_size_x(), stex.blueprint_get_size_y()
            rec["shadow"] = self.sprite(f"{self.dest}/Sprites", f"S_{a['name']}_shadow", stex, [0, 0, sw, shh],
                                        [sw / 2, shh / 2])
            self.tag(sp, "shadow_offset", sh.get("offset", [0, 0]))
        self.tag(sp, "role", a.get("role", ""))
        self.records[f"sprite/{a['name']}"] = rec

    def _animated_sprite(self, a):
        clips = {}
        for c in a["clips"]:
            frames = c["frames"]
            rate, runs, exact = spec.flipbook_rate(c.get("fps"), [f["duration"] for f in frames])
            if not exact:
                self.warn(f"{a['name']}/{c['name']}: no frame rate makes every duration whole; "
                          f"{rate:g} fps rounds them")
            sheet = c.get("sheet")
            keys = []
            for i, (f, run) in enumerate(zip(frames, runs)):
                tex = self.texture(sheet or f["file"])
                sp = self.sprite(f"{self.dest}/Sprites/{safe(a['name'])}", f"S_{a['name']}_{c['name']}_{i:02d}",
                                 tex, f["rect"], c["pivot"])
                k = unreal.PaperFlipbookKeyFrame()
                k.set_editor_property("sprite", sp)
                k.set_editor_property("frame_run", run)
                keys.append(k)
            fb = self.new(unreal.PaperFlipbook, unreal.PaperFlipbookFactory, f"{self.dest}/Flipbooks",
                          f"FB_{a['name']}_{c['name']}")
            fb.set_editor_property("frames_per_second", rate)
            fb.set_editor_property("key_frames", keys)
            self.tag(fb, "loop", "true" if c["loop"] else "false")
            self.tag(fb, "blend", a.get("blend", "normal"))
            if a.get("directions"):
                self.tag(fb, "directions", a["directions"])
            clips[c["name"]] = {"flipbook": fb, "sheet": sheet, "files": sorted({f["file"] for f in frames}),
                                "loop": c["loop"]}
        self.records[f"animated_sprite/{a['name']}"] = {"kind": "animated_sprite", "clips": clips,
                                                        "blend": a.get("blend", "normal"),
                                                        "directions": a.get("directions") or {}}

    def _icon(self, a):
        self.records[f"icon/{a['name']}"] = {"kind": "icon",
                                             "textures": [self.texture(s["image"]) for s in a["sizes"]]}

    def _portrait(self, a):
        w, h = a["size"]
        sprites = {}
        for e in a["expressions"]:
            sprites[e["name"]] = self.sprite(f"{self.dest}/Sprites", f"S_{a['name']}_{e['name']}",
                                             self.texture(e["image"]), [0, 0, w, h], [w / 2, h / 2])
        if a.get("animation") and f"animated_sprite/{a['animation']}" not in self.records:
            self.warn(f"portrait {a['name']}: its animation {a['animation']!r} was not built")
        first = sprites[a["expressions"][0]["name"]]
        self.tag(first, "animation", a.get("animation") or "")
        self.records[f"portrait/{a['name']}"] = {"kind": "portrait", "sprites": sprites,
                                                 "animation": a.get("animation")}

    def _font(self, a):
        """An offline Font: Characters indexed by code point (no remap table), metrics from the BMFont header.
        Offline fonts keep one advance per glyph (its width) plus one font-wide Kerning, so a glyph's xoffset and
        the kerning pairs cannot be kept; the most common gap between glyphs becomes the Kerning."""
        pages = [self.texture(p) for p in a["pages"]]
        chars = a["chars"]
        gaps = [c[7] - c[3] - c[5] for c in chars if c[3] > 0]
        kerning = max(set(gaps), key=gaps.count) if gaps else 0
        top = max((c[0] for c in chars if c[0] <= 0xFFFF), default=0)
        table = [unreal.FontCharacter() for _ in range(top + 1)]
        dropped = 0
        for code, x, y, w, h, xoff, yoff, xadv, page in chars:
            if code > 0xFFFF:
                dropped += 1
                continue
            fc = table[code]
            if w > 0:
                fc.set_editor_properties({"start_u": x, "start_v": y, "u_size": w, "v_size": h,
                                          "vertical_offset": yoff, "texture_index": page})
            else:                             # a space: advance only, nothing drawn (no height)
                fc.set_editor_properties({"u_size": max(0, xadv - kerning), "texture_index": page})
            if xoff or (w > 0 and xadv - w != kerning):
                dropped += 1
        font = self.new(unreal.Font, unreal.FontFactory, f"{self.dest}/Fonts", f"F_{a['name']}")
        font.set_editor_properties({"font_cache_type": unreal.FontCacheType.OFFLINE, "characters": table,
                                    "em_scale": 1.0, "ascent": float(a["base"]),
                                    "descent": float(a["line_height"] - a["base"]), "leading": 0.0,
                                    # the pages and chars are already at the font's `scale`: draw 1:1
                                    "kerning": kerning, "scaling_factor": 1.0,
                                    "legacy_font_size": max(1, a["line_height"])})
        self.console_set(font, "IsRemapped", "0")
        self.console_set(font, "Textures", "(" + ",".join(t.get_path_name() for t in pages) + ")")
        if font_page_count(font) != len(pages):
            # The full editor refuses `set` ("Set commands not allowed in the editor"); the pythonscript commandlet
            # (dev.py exec) runs it. A Font without its pages draws nothing, so a saved import must not have one.
            self.font_pages_blocked = True
            if not self.transient:
                raise RuntimeError("the font's pages could not be attached in this editor session: run "
                                   "python tools/dev.py exec Content/Python/kit_dotwork/import_dotwork.py")
            self.warn(f"font {a['name']}: pages not attached (the editor blocks `set`; dev.py exec attaches them)")
        if dropped:
            self.warn(f"font {a['name']}: {dropped} glyph(s) keep their pixels but not their exact offset or advance "
                      "(an offline Font has neither per glyph)")
        if a.get("kerning"):
            self.warn(f"font {a['name']}: {len(a['kerning'])} kerning pair(s) dropped (offline Fonts have none)")
        self.tag(font, "tint", "true" if a.get("tint", True) else "false")
        self.records[f"font/{a['name']}"] = {"kind": "font", "font": font, "codes": sorted(c[0] for c in chars),
                                             "pages": len(pages)}

    def _ui_kit(self, a):
        parts = {}
        for p in a["parts"]:
            tex = self.texture(p["image"])
            w, h = p["size"]
            # The image and its margins are already drawn at the part's `scale` (Dotwork upscales the pixels):
            # the brush shows it 1:1
            brush = unreal.SlateBrush()
            brush.set_editor_property("resource_object", tex)
            brush.set_editor_property("image_size", slate_vector(w, h))
            m = p.get("margins")
            if m:
                brush.set_editor_property("draw_as", unreal.SlateBrushDrawType.BOX)
                brush.set_editor_property("margin", unreal.Margin(m[0] / w, m[1] / h, m[2] / w, m[3] / h))
            else:
                brush.set_editor_property("draw_as", unreal.SlateBrushDrawType.IMAGE)
            asset = self.new(unreal.SlateBrushAsset, getattr(unreal, "SlateBrushAssetFactory", None),
                             f"{self.dest}/UI", f"SB_{a['name']}_{p['name']}")
            asset.set_editor_property("brush", brush)
            for key in ("role", "state", "control", "glyph"):
                if p.get(key):
                    self.tag(asset, key, p[key])
            if p.get("hotspot"):
                self.tag(asset, "hotspot", p["hotspot"])
            parts[p["name"]] = {"texture": tex, "brush": asset, "hotspot": p.get("hotspot")}
        self.records[f"ui_kit/{a['name']}"] = {"kind": "ui_kit", "parts": parts}

    def _tileset(self, a):
        atlases, animated, odd_origins = {}, [], []
        for at in a["atlases"]:
            tex = self.texture(at["image"])
            tw, th = at.get("tile_size") or a["tile_size"]
            ts = self.new(unreal.PaperTileSet, unreal.PaperTileSetFactory, f"{self.dest}/TileSets",
                          f"TS_{a['name']}_{at['name']}")
            ts.set_editor_property("tile_sheet", tex)
            ts.set_editor_property("tile_size", unreal.IntPoint(tw, th))
            # Where the spec draws the atlas's tiles (centre minus origin) against where Paper2D draws them (the
            # cell's top-left, taller tiles bottom-aligned): one DrawingOffset per tile set
            (dx, dy), odd = spec.drawing_offset({"tile_size": [tw, th], "tiles": at["tiles"]}, a["tile_size"])
            ts.set_editor_property("drawing_offset", unreal.IntPoint(dx, dy))
            odd_origins += [[at["id"]] + cell for cell in odd]
            across = tex.blueprint_get_size_x() // tw         # Paper2D's WidthInTiles (index = row * across + col)
            data = [unreal.PaperTileMetadata() for _ in ts.get_editor_property("per_tile_data")]
            for t in at["tiles"]:
                i = t["row"] * across + t["col"]
                if i >= len(data):
                    raise RuntimeError(f"tile {[at['id'], t['col'], t['row']]} lies outside {at['image']}")
                md = data[i]
                if t.get("surface"):
                    md.set_editor_property("user_data_name", t["surface"])
                if t.get("collision"):
                    cd = md.get_editor_property("collision_data")
                    cd.set_editor_property("geometry_type", unreal.SpritePolygonMode.FULLY_CUSTOM)
                    cd.set_editor_property("shapes", [box_shape(*c["rect"]) for c in t["collision"]])
                    md.set_editor_property("collision_data", cd)
                if t.get("anim"):
                    animated.append([at["id"], t["col"], t["row"], t["anim"]["frames"], t["anim"]["fps"]])
            ts.set_editor_property("per_tile_data", data)
            self.tag(ts, "atlas", {"tileset": a["name"], "id": at["id"], "role": at.get("role", "")})
            atlases[at["id"]] = {"tileset": ts, "across": across, "tile_size": [tw, th], "offset": [dx, dy]}
        if animated:
            self.warn(f"tileset {a['name']}: {len(animated)} animated tile(s) show their first frame (Paper2D tile "
                      "maps have no tile animation; the frames are in metadata dotwork.animated_tiles)")
            for info in atlases.values():
                self.tag(info["tileset"], "animated_tiles", animated)
        if odd_origins:
            self.warn(f"tileset {a['name']}: {len(odd_origins)} tile(s) {odd_origins[:4]} want another origin than "
                      "their atlas's first tile, or a half-pixel one; a PaperTileSet has one whole-pixel Drawing "
                      "Offset for all its tiles (put such tiles in an atlas of their own)")
        masks, n = {}, 0
        for at in a["atlases"]:
            for t in at["tiles"]:
                n += 1
                if "terrain" in t:
                    tk = f"{t.get('terrain_set', 0)}/{t['terrain']}"
                    v = t["mask"] if "mask" in t else [t["corners"][c] for c in sorted(t["corners"])]
                    masks.setdefault(tk, [])
                    if v not in masks[tk]:
                        masks[tk].append(v)
        self.records[f"tileset/{a['name']}"] = {
            "kind": "tileset", "doc": a, "atlases": atlases, "tiles": n, "animated": len(animated),
            "terrains": {f"{s['id']}/{t['id']}": t["name"] for s in a["terrain_sets"] for t in s["terrains"]},
            "masks": {k: sorted(v) for k, v in sorted(masks.items())}}

    def _map(self, a):
        rec_ts = self.records.get(f"tileset/{a['tileset']}")
        if rec_ts is None:
            raise RuntimeError(f"tileset {a['tileset']!r} was not built")
        ts_doc, atlases = rec_ts["doc"], rec_ts["atlases"]
        (mw, mh), (tw, th) = a["size"], a.get("tile_size") or ts_doc["tile_size"]
        layers = a["layers"]
        comp = unreal.new_object(unreal.PaperTileMapComponent)
        comp.create_new_tile_map(mw, mh, tw, th, PIXELS_PER_UNIT, False)
        named = self.named_layers(a, tw, th)       # empty layers with the manifest's names, Paper2D order
        for layer in named:
            layer.rename(f"Scratch_{uuid.uuid4().hex[:8]}", comp.get_editor_property("tile_map"))
        comp.get_editor_property("tile_map").set_editor_property("tile_layers", named)
        shape = ts_doc.get("shape", "square")
        if shape not in PROJECTION:
            raise RuntimeError(f"tileset {a['tileset']} has shape {shape!r}; Paper2D draws square and isometric")
        if list(a.get("tile_size") or (tw, th)) != list(ts_doc["tile_size"]):
            self.warn(f"map {a['name']}: its tile_size {a.get('tile_size')} differs from tileset {a['tileset']}'s "
                      f"{ts_doc['tile_size']}; the tile sets' Drawing Offsets were made for the tileset's cell")
        terrain, drawn = {}, {}                    # drawn[layer name] = [[x, y, atlas, col, row], ...] in draw order

        def put(x, y, pi, atlas, col, row, flags=0):
            info = atlases[atlas]
            packed = row * info["across"] + col
            for bit, value in FLIP_BITS.items():
                if flags & bit:
                    packed |= value
            if packed >= 1 << 31:
                packed -= 1 << 32                # PackedTileIndex is a signed int32
            tile = unreal.PaperTileInfo()
            tile.set_editor_property("tile_set", info["tileset"])
            tile.set_editor_property("packed_tile_index", packed)
            comp.set_tile(x, y, pi, tile)

        for i, L in enumerate(layers):
            pi = spec.paper_layer_index(i, len(layers))
            if L["kind"] not in spec.LAYER_KINDS:
                self.warn(f"map {a['name']}: layer {L['name']} of unknown kind {L['kind']!r} skipped (newer spec?)")
                drawn[L["name"]] = []
                continue
            if L["kind"] == "terrain":
                # the key per cell (mask or corner bits) and the variant picked with the cell's roll and this
                # layer's index: the same tile on every engine
                cells = spec.resolve_terrain(ts_doc, L, i)
                terrain[L["name"]] = cells
                missing = sum(1 for _, _, _, tile in cells if tile is None)
                if missing:
                    self.warn(f"map {a['name']} layer {L['name']}: {missing} terrain cell(s) have no tile with "
                              "their key (left empty; a corners4 shape must be 2 cells thick)")
            placed = spec.placed_cells(ts_doc, L, i)    # tiles as listed, terrain resolved, stamps expanded
            drawn[L["name"]] = placed
            flags = {tuple(c[:2]): c[5] for c in L["cells"] if len(c) > 5} if L["kind"] == "tiles" else {}
            for x, y, atlas, col, row in placed:
                put(x, y, pi, atlas, col, row, flags.get((x, y), 0))
        built = comp.get_editor_property("tile_map")
        target = self.new(unreal.PaperTileMap, unreal.PaperTileMapFactory, f"{self.dest}/Maps", f"TM_{a['name']}")
        # Swap layers: the new ones move into the asset, the asset's old ones into the scratch map (a layer's outer
        # must stay a PaperTileMap: Paper2D casts it, and a layer moved into a package crashes the editor)
        old_layers = list(target.get_editor_property("tile_layers"))
        moved = []
        for pi, layer in enumerate(built.get_editor_property("tile_layers")):
            layer.rename(f"Layer_{pi}_{uuid.uuid4().hex[:8]}", target)
            moved.append(layer)
        for old in old_layers:
            old.rename(f"Old_{uuid.uuid4().hex[:8]}", built)
        target.set_editor_properties({
            "map_width": mw, "map_height": mh, "tile_width": tw, "tile_height": th,
            "pixels_per_unreal_unit": PIXELS_PER_UNIT,
            "projection_mode": getattr(unreal.TileMapProjectionMode, PROJECTION[shape])})
        target.set_editor_property("tile_layers", moved)
        if a.get("objects"):
            self.tag(target, "objects", a["objects"])
        self.tag(target, "shape", shape)
        self.records[f"map/{a['name']}"] = {"kind": "map", "map": target, "doc": a, "terrain": terrain,
                                            "drawn": drawn, "tileset": rec_ts, "shape": shape, "tile_size": [tw, th]}

    def named_layers(self, a, tw, th):
        """Empty tile layers named as the manifest's, in Paper2D order (layer 0 on top), with each layer's opacity.
        UPaperTileLayer::LayerName is hidden from Python and the editor refuses the `set` command, but Paper2D's
        own Tiled importer names its layers: a Tiled JSON map with these layers and no tiles is imported into
        /Temp and its layers are taken (it reverses Tiled's bottom-first order itself)."""
        mw, mh = a["size"]
        tiled = {"version": 1, "type": "map", "orientation": "orthogonal", "renderorder": "right-down",
                 "width": mw, "height": mh, "tilewidth": tw, "tileheight": th, "tilesets": [],
                 "layers": [{"name": L["name"], "type": "tilelayer", "x": 0, "y": 0, "width": mw, "height": mh,
                             "visible": True, "opacity": float(L.get("opacity", 1.0)), "data": [0] * (mw * mh)}
                            for L in a["layers"]]}
        folder = os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir()),
                              "Dotwork")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"layers_{self.run_id}_{safe(a['name'])}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(tiled, f)
        try:
            task = unreal.AssetImportTask()
            for key, value in (("filename", path), ("destination_path", f"{TRANSIENT_TEXTURES}/{self.run_id}/layers"),
                               ("destination_name", f"L_{safe(a['name'])}"), ("automated", True), ("save", False),
                               ("replace_existing", True), ("factory", unreal.PaperTiledImporterFactory())):
                task.set_editor_property(key, value)
            self.tools.import_asset_tasks([task])
            paths = task.get_editor_property("imported_object_paths")
        finally:
            os.remove(path)
        scratch = unreal.load_asset(paths[0]) if paths else None
        if not isinstance(scratch, unreal.PaperTileMap):
            raise RuntimeError("Paper2D's Tiled importer did not make the layer stack (is the Paper2D plugin on?)")
        named = list(scratch.get_editor_property("tile_layers"))
        got = [str(L.get_editor_property("layer_name")) for L in named]
        want = [L["name"] for L in reversed(a["layers"])]
        if got != want:
            raise RuntimeError(f"layer stack came back as {got}, expected {want}")
        return named

    # ---- extra kinds: textures (plus what the texture's metadata can hold) -------------------------------
    def _texture_only(self, a):
        """background: a texture per layer (wrapping on its repeat axes, the velocity as a tag); particles: the
        mask texture with the emitter JSON as its dotwork.emitter tag (no file beside it under Content/: the editor's
        auto-import, on by default, would offer any .json there as a DataTable; a Niagara system is #286);
        transition, normal_map (linear, the lit target as a tag) and image: the texture."""
        k = a["kind"]
        if k == "background":
            texs = [self.texture(L["image"], repeat=L.get("repeat", "none")) for L in a["layers"]]
            for L, t in zip(a["layers"], texs):
                self.tag(t, "velocity", L.get("velocity", [0, 0]))
            self.records[f"background/{a['name']}"] = {"kind": k, "textures": texs, "doc": a}
            return
        if k == "particles":
            tex = self.texture(a["texture"])
            self.tag(tex, "emitter", a.get("emitter") or {})
            self.records[f"particles/{a['name']}"] = {"kind": k, "texture": tex, "emitter": a.get("emitter") or {}}
            return
        tex = self.texture(a["image"], normal=(k == "normal_map"))
        if k == "normal_map":
            self.tag(tex, "target", a.get("target", ""))
        if k == "transition":
            self.tag(tex, "transition", a.get("transition", ""))
        self.records[f"{k}/{a['name']}"] = {"kind": k, "texture": tex, "doc": a}


def box_shape(x, y, w, h):
    """A Paper2D box collision shape from a top-left rect. BoxSize and BoxPosition are read-only to Python's
    property setters, so the struct is filled from text."""
    shape = unreal.SpriteGeometryShape()
    if not shape.import_text(f"(ShapeType=Box,BoxSize=(X={w},Y={h}),BoxPosition=(X={x + w / 2},Y={y + h / 2}))"):
        raise RuntimeError("could not build a collision box")
    return shape


# ---- reading the assets back --------------------------------------------------------------------
def _uvdim(sp):
    uv, dim = sp.get_editor_property("source_uv"), sp.get_editor_property("source_dimension")
    return uv, dim


def _rel(imp, tex):
    return imp.tex_rel.get(tex.get_path_name()) if tex else None


def _size(tex):
    return [tex.blueprint_get_size_x(), tex.blueprint_get_size_y()]


def loaded(imp):
    """The loaded result (expected.json's "assets") read from the Paper2D objects imp built. Facts no engine type
    holds (loop, directions, hotspots, map objects, tile masks) come from imp's records."""
    r6 = spec.round6
    out = {}
    for key, rec in imp.records.items():
        kind = rec["kind"]
        if kind == "animated_sprite":
            clips = {}
            for name, c in rec["clips"].items():
                fb = c["flipbook"]
                rate = fb.get_editor_property("frames_per_second")
                rects, secs, texs = [], [], set()
                for k in fb.get_editor_property("key_frames"):
                    sp = k.get_editor_property("sprite")
                    uv, dim = _uvdim(sp)
                    rects.append([r6(uv.x), r6(uv.y), r6(dim.x), r6(dim.y)])
                    secs.append(r6(k.get_editor_property("frame_run") / rate))
                    texs.add(_rel(imp, sp.get_editor_property("source_texture")))
                first = fb.get_editor_property("key_frames")[0].get_editor_property("sprite")
                uv, _ = _uvdim(first)
                piv = first.get_editor_property("custom_pivot_point")
                if c["sheet"]:
                    texture = c["sheet"] if texs == {c["sheet"]} else f"textures {sorted(map(str, texs))}"
                else:
                    texture = None if texs == set(c["files"]) else f"textures {sorted(map(str, texs))}"
                clips[name] = {"frames": len(rects), "rects": rects, "seconds": secs,
                               "length": r6(fb.get_total_duration()), "loop": c["loop"],
                               "pivot": [r6(piv.x - uv.x), r6(piv.y - uv.y)], "texture": texture}
            out[key] = {"blend": rec["blend"], "clips": clips, "directions": rec["directions"]}
        elif kind == "sprite":
            sp = rec["sprite"]
            uv, dim = _uvdim(sp)
            piv = sp.get_editor_property("custom_pivot_point")
            boxes = []
            for s in sp.get_editor_property("collision_geometry").get_editor_property("shapes"):
                bs, bp = s.get_editor_property("box_size"), s.get_editor_property("box_position")
                boxes.append([r6(bp.x - bs.x / 2 - uv.x), r6(bp.y - bs.y / 2 - uv.y), r6(bs.x), r6(bs.y)])
            out[key] = {"size": [r6(dim.x), r6(dim.y)], "pivot": [r6(piv.x - uv.x), r6(piv.y - uv.y)],
                        "collision": boxes}
        elif kind == "icon":
            out[key] = {"sizes": sorted(t.blueprint_get_size_x() for t in rec["textures"])}
        elif kind == "portrait":
            first = next(iter(rec["sprites"].values()))
            _, dim = _uvdim(first)
            out[key] = {"size": [r6(dim.x), r6(dim.y)], "expressions": sorted(rec["sprites"]),
                        "animation": rec["animation"]}
        elif kind == "font":
            out[key] = _font_back(rec)
        elif kind == "ui_kit":
            parts = {}
            for name, p in rec["parts"].items():
                w, h = _size(p["texture"])
                brush = p["brush"].get_editor_property("brush")
                margins = None
                if brush.get_editor_property("draw_as") == unreal.SlateBrushDrawType.BOX:
                    m = brush.get_editor_property("margin")
                    margins = [r6(m.left * w), r6(m.top * h), r6(m.right * w), r6(m.bottom * h)]
                parts[name] = {"size": [w, h], "margins": margins, "hotspot": p["hotspot"]}
            out[key] = {"parts": parts}
        elif kind == "tileset":
            coll = 0
            for info in rec["atlases"].values():
                for md in info["tileset"].get_editor_property("per_tile_data"):
                    coll += bool(md.get_editor_property("collision_data").get_editor_property("shapes"))
            a = rec["doc"]
            out[key] = {"tile_size": a["tile_size"], "shape": a["shape"], "tiles": rec["tiles"],
                        "collision_tiles": coll, "animated_tiles": rec["animated"], "terrains": rec["terrains"],
                        "masks": rec["masks"]}
        elif kind == "map":
            out[key] = _map_back(rec)
        elif kind == "background":
            layers = []
            for L, t in zip(rec["doc"]["layers"], rec["textures"]):
                wrap = unreal.TextureAddress.TA_WRAP
                rep = ("x" if t.get_editor_property("address_x") == wrap else "") + \
                      ("y" if t.get_editor_property("address_y") == wrap else "")
                layers.append(_size(t) + [r6(L["velocity"][0]), r6(L["velocity"][1]), rep or "none"])
            out[key] = {"layers": layers}
        else:
            out[key] = {"kind": kind}
    return out


def _font_back(rec):
    font = rec["font"]
    chars = font.get_editor_property("characters")
    kerning = font.get_editor_property("kerning")
    present = [i for i, c in enumerate(chars) if c.get_editor_property("u_size") or c.get_editor_property("v_size")]

    def row(i):
        """[id, x, y, w, h, xoffset, yoffset, xadvance, page] as the BMFont table has it; xoffset is always 0 (an
        offline Font has none) and a glyph without height (a space) has width 0 and only its advance."""
        c = chars[i]
        u, v = c.get_editor_property("u_size"), c.get_editor_property("v_size")
        return [i, c.get_editor_property("start_u"), c.get_editor_property("start_v"), u if v else 0, v, 0,
                c.get_editor_property("vertical_offset"), u + kerning, c.get_editor_property("texture_index")]

    ascent, descent = font.get_editor_property("ascent"), font.get_editor_property("descent")
    sample = row(65) if 65 in present else (row(present[0]) if present else None)
    return {"line_height": spec.round6(ascent + descent), "base": spec.round6(ascent), "chars": len(present),
            "pages": font_page_count(font), "sample": sample}


def font_page_count(font):
    """How many page textures an offline Font holds. UFont::Textures is hidden from Python, so the font is
    exported as T3D text (into Saved/) and its Textures(i)= lines are counted."""
    out = os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir()), "Dotwork",
                       f"{safe(font.get_name())}.t3d")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    task = unreal.AssetExportTask()
    for key, value in (("object", font), ("filename", out), ("automated", True), ("prompt", False),
                       ("replace_identical", True), ("exporter", unreal.ObjectExporterT3D())):
        task.set_editor_property(key, value)
    if not unreal.Exporter.run_asset_export_task(task):
        raise RuntimeError(f"could not export {font.get_path_name()} to read its pages")
    with open(out, "rb") as f:
        raw = f.read()
    os.remove(out)
    # Unreal writes text files as UTF-16 with a byte order mark when they hold non-ASCII, else plain
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")
    return len(re.findall(r"^\s*Textures\(\d+\)=", text, re.M))


def _map_back(rec):
    """The map's loaded result from the PaperTileMap: sizes and shape from the asset, every cell's tile from
    GetTile, centres from Paper2D's own GetTileCenterPosition (so an isometric map proves Paper2D's diamond grid
    is the spec's), and where each drawn tile's image lands from Paper2D's render rule (the cell's top-left plus the
    tile set's DrawingOffset, taller tiles bottom-aligned: PaperTileMapComponent::RebuildRenderData). Which cells
    a layer draws, and in what order, comes from the import record (Paper2D keeps no cell order)."""
    tm, a = rec["map"], rec["doc"]
    comp = unreal.new_object(unreal.PaperTileMapComponent)
    comp.set_tile_map(tm)
    w, h = tm.get_editor_property("map_width"), tm.get_editor_property("map_height")
    tile_size = [tm.get_editor_property("tile_width"), tm.get_editor_property("tile_height")]
    mode = tm.get_editor_property("projection_mode")
    shape = next((s for s, name in PROJECTION.items() if mode == getattr(unreal.TileMapProjectionMode, name)),
                 str(mode))
    paper_layers = tm.get_editor_property("tile_layers")
    by_set = {info["tileset"].get_path_name(): aid for aid, info in rec["tileset"]["atlases"].items()}
    sets = {}                                    # atlas id -> (across, tile height, drawing offset) from the asset
    for aid, info in rec["tileset"]["atlases"].items():
        ts = info["tileset"]
        off = ts.get_editor_property("drawing_offset")
        sets[aid] = (info["across"], ts.get_editor_property("tile_size").y, [off.x, off.y])

    def tile(x, y, pi):
        t = comp.get_tile(x, y, pi)
        ts = t.get_editor_property("tile_set")
        packed = t.get_editor_property("packed_tile_index")
        if ts is None or packed == -1:
            return None
        aid = by_set.get(ts.get_path_name())
        across = sets[aid][0] if aid in sets else 1
        idx = packed & TILE_INDEX_MASK
        return [aid, idx % across, idx // across]

    def centre(x, y):
        return local_to_map(comp.get_tile_center_position(x, y, 0, False), tile_size)

    def corner(x, y, aid):
        """The image's top-left in map pixels: the cell's top-left (its centre less half a cell), plus the tile
        set's DrawingOffset, plus the bottom alignment of a tile taller than the cell."""
        _, th, (dx, dy) = sets[aid]
        cx, cy = centre(x, y)
        return [spec.round6(cx - tile_size[0] / 2 + dx), spec.round6(cy - tile_size[1] / 2 + dy + tile_size[1] - th)]

    layers, terrain, placed = {}, {}, {}
    n = len(a["layers"])
    for i, L in enumerate(a["layers"]):
        pi = spec.paper_layer_index(i, n)
        name = str(paper_layers[pi].get_editor_property("layer_name"))
        layers[name] = sum(1 for y in range(h) for x in range(w) if tile(x, y, pi) is not None)
        if L["name"] in rec["terrain"]:
            terrain[name] = [[x, y, m, tile(x, y, pi)] for x, y, m, _ in rec["terrain"][L["name"]]]
        cells = []
        for x, y, *_ in rec["drawn"].get(L["name"], []):
            got = tile(x, y, pi)
            cells.append([x, y] + (got + corner(x, y, got[0]) if got else [None, None, None, None, None]))
        placed[name] = cells
    return {"size": [w, h], "shape": shape, "tile_size": tile_size, "layers": layers, "terrain": terrain,
            "placed": placed,
            "centres": [[x, y] + [spec.round6(v) for v in centre(x, y)] for y in range(h) for x in range(w)],
            "objects": [[o["asset"], spec.round6(o["x"]), spec.round6(o["y"])] for o in a.get("objects") or []]}


def texture_settings_problems(imp):
    """Textures that lost the pixel-art settings (nearest, no mips, uncompressed): empty when all are right."""
    bad = []
    for rel, t in imp.textures.items():
        if t.get_editor_property("filter") != unreal.TextureFilter.TF_NEAREST:
            bad.append(f"{rel}: filter {t.get_editor_property('filter')}")
        if t.get_editor_property("mip_gen_settings") != unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS:
            bad.append(f"{rel}: mips {t.get_editor_property('mip_gen_settings')}")
    return bad
