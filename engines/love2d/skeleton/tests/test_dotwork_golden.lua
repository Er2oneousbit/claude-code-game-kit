-- ---------------------------------------------------------------------------
-- test_dotwork_golden.lua
-- Purpose : The Dotwork asset importer (src/core/dotwork_manifest.lua, src/game/dotwork_loader.lua) against the
--           spec's golden fixture: loads data/golden/dotwork/assets/dotwork/golden.assets.json and compares what it
--           built with data/golden/dotwork/expected.json (the reference loader's result) to 1e-6, one test per
--           asset (the three maps' terrain, placed cells and centres included). Plus the pieces expected.json
--           cannot show: frame timing, tile flags, the spec's hash and roll vectors, the corners4 rule, isometric
--           centres, stamps, BMFont text layout, version refusal, unknown kinds, layer kinds and fields, broken
--           references.
-- Usage   : python tools/dev.py test     (or --filter dotwork)
-- Notes   : Headless: PNGs are checked with love.image (no window). Drawing is covered by the smoke run, which
--           draws the starter scene's Dotwork art when the game has manifests. Never copy expected values into this
--           file: they come from expected.json, written by tools/art/dotwork/assetspec.py; the explicit vectors
--           below are the spec's own (ASSET_MANIFEST.md "Variants" and "Placing tiles").
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): the loaded result's new map
--           fields, the extra kinds compared instead of skipped, the vectors and rule cases.
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local Golden = require("tests.helpers.golden")
local Json = require("src.core.json")
local Manifest = require("src.core.dotwork_manifest")
local Loader = require("src.game.dotwork_loader")

-- ---- Tunables ----------------------------------------------------------------
local DIR = "data/golden/dotwork/"
local MANIFEST = DIR .. "assets/dotwork/golden.assets.json"
local EXPECTED = DIR .. "expected.json"
local TOL = 1e-6                          -- the spec's tolerance (expected.json rounds to 6 decimals)

local function read_json(path)
  local text = love.filesystem.read(path)
  if not text then error("cannot read " .. path .. " (it ships with the kit: restore it)", 0) end
  return Json.decode(text)
end

local expected = read_json(EXPECTED)
local model = Loader.load(MANIFEST)

-- a resolved path back to the manifest-relative form expected.json uses (m: the model it came from)
local function rel(path, m)
  if path == nil then return nil end
  local prefix = (m or model).base .. "/"
  return path:sub(1, #prefix) == prefix and path:sub(#prefix + 1) or path
end

local function list_less(p, q)                  -- lexicographic order of number lists (corner tuples)
  for i = 1, math.max(#p, #q) do
    if p[i] == nil then return true end
    if q[i] == nil then return false end
    if p[i] ~= q[i] then return p[i] < q[i] end
  end
  return false
end

-- ---- The importer's objects in the loaded-result shape (spec "Golden fixture and loaded result") ----
local shape = {}

function shape.animated_sprite(a, m)
  local clips = {}
  for name, c in pairs(a.clips) do
    local rects, seconds = {}, {}
    for i, f in ipairs(c.frames) do rects[i], seconds[i] = f.rect, f.duration end
    clips[name] = { frames = #c.frames, rects = rects, seconds = seconds, length = c.length, loop = c.loop,
                    pivot = c.pivot, texture = rel(c.sheet, m) }
  end
  return { blend = a.blend, clips = clips, directions = a.directions }
end

function shape.sprite(a)
  local coll = {}
  for i, r in ipairs(a.collision) do coll[i] = { r[1], r[2], r[3], r[4] } end
  return { size = a.size, pivot = a.pivot, collision = coll }
end

function shape.icon(a)
  local sizes = {}
  for i, s in ipairs(a.sizes) do sizes[i] = s.size end
  return { sizes = sizes }
end

function shape.portrait(a)
  local names = {}
  for i, e in ipairs(a.expressions) do names[i] = e.name end
  table.sort(names)
  return { size = a.size, expressions = names, animation = a.animation }
end

function shape.tileset(a)
  local coll, anim, masks, seen = 0, 0, {}, {}
  for _, t in ipairs(a.tile_list) do
    if #t.collision > 0 then coll = coll + 1 end
    if t.anim then anim = anim + 1 end
    if t.terrain ~= nil then
      local tk = t.terrain_set .. "/" .. t.terrain
      local v = t.mask ~= nil and t.mask or Manifest.corner_list(t.corners)
      local key = Manifest.mask_key(t)
      masks[tk], seen[tk] = masks[tk] or {}, seen[tk] or {}
      if not seen[tk][key] then
        seen[tk][key] = true
        table.insert(masks[tk], v)
      end
    end
  end
  for _, list in pairs(masks) do
    table.sort(list, function(p, q)
      if type(p) == "number" then return p < q end
      return list_less(p, q)
    end)
  end
  local terrains = {}
  for sid, set in pairs(a.terrain_sets) do
    for tid, t in pairs(set.terrains) do terrains[sid .. "/" .. tid] = t.name end
  end
  return { tile_size = a.tile_size, shape = a.shape, tiles = #a.tile_list, collision_tiles = coll,
           animated_tiles = anim, terrains = terrains, masks = masks }
end

function shape.map(a)
  local layers, terrain, placed, centres, objects = {}, {}, {}, {}, {}
  for _, L in ipairs(a.layers) do
    layers[L.name] = L.count
    if L.kind == "terrain" and a.tileset then
      local cells = {}
      for i, c in ipairs(L.cells) do cells[i] = { c.x, c.y, c.key, c.tile or Json.null } end
      terrain[L.name] = cells
    end
    if a.tileset then
      local drawn = {}
      for _, c in ipairs(L.cells) do
        if c.tile then drawn[#drawn + 1] = { c.x, c.y, c.tile[1], c.tile[2], c.tile[3], c.left, c.top } end
      end
      placed[L.name] = drawn
    end
  end
  for i, c in ipairs(a.centres) do centres[i] = { c.x, c.y, c.cx, c.cy } end
  for i, o in ipairs(a.objects) do objects[i] = { o.asset, o.x, o.y } end
  return { size = a.size, shape = a.shape, tile_size = a.tile_size, layers = layers, terrain = terrain,
           placed = placed, centres = centres, objects = objects }
end

-- The extra kinds: a background's layers as [w, h, vx, vy, repeat]; the others are loaded (their kind).
function shape.background(a)
  local layers = {}
  for i, L in ipairs(a.layers) do layers[i] = { L.size[1], L.size[2], L.velocity[1], L.velocity[2], L["repeat"] } end
  return { layers = layers }
end

for _, k in ipairs({ "particles", "transition", "normal_map", "image" }) do
  shape[k] = function(a) return { kind = a.kind } end
end

function shape.font(a)
  local sample = a.chars[65] or a.char_list[1]
  return { line_height = a.line_height, base = a.base, chars = #a.char_list, pages = #a.pages,
           sample = sample and sample.raw }
end

function shape.ui_kit(a)
  local parts = {}
  for name, p in pairs(a.parts) do parts[name] = { size = p.size, margins = p.margins, hotspot = p.hotspot } end
  return { parts = parts }
end

local T = {}

-- One test per asset of expected.json, every kind compared field by field (the extra kinds included).
for _, key in ipairs(Json.sorted_keys(expected.assets)) do
  local kind, name = key:match("^([^/]+)/(.+)$")
  T["test_asset_" .. key:gsub("%W", "_")] = function()
    A.truthy(shape[kind], key .. ": no shape for kind " .. kind)
    local a = model[kind] and model[kind][name]
    A.truthy(a, key .. " was not imported")
    Golden.expect(shape[kind](a), expected.assets[key], TOL, key)
  end
end

function T.test_header_matches()
  A.eq(model.pack, expected.pack)
  A.eq(model.version, expected.version)
end

function T.test_no_asset_beyond_expected()
  local n = 0
  for _, a in ipairs(model.order) do
    n = n + 1
    A.truthy(expected.assets[a.kind .. "/" .. a.name], a.kind .. "/" .. a.name .. " is not in expected.json")
  end
  A.eq(n + #model.skipped, #Json.sorted_keys(expected.assets), "every asset imported or skipped once")
end

-- Every kind of the golden pack loads now (spec 1.1.0): nothing is skipped and nothing warns.
function T.test_golden_pack_loads_without_warnings()
  A.eq(#model.warnings, 0, table.concat(model.warnings, "\n"))
  A.eq(#model.skipped, 0, "no kind of the golden pack is skipped")
  A.eq(#model.problems, 0, table.concat(model.problems, "\n"))
end

-- ---- The extra kinds are exposed by name with their data ---------------------------------------
function T.test_extra_kinds_exposed()
  local bg = model.background.hills
  A.truthy(bg, "background hills")
  A.eq(#bg.layers, 2)
  A.eq(bg.layers[2]["repeat"], "x")
  A.truthy(bg.layers[2].repeat_x and not bg.layers[2].repeat_y, "repeat x wraps x only")
  A.eq(bg.layers[2].velocity[1], -4)
  A.eq(bg.layers[2].image, model.base .. "/art/battle/bg/spr_bg_hills_clouds_near.png", "paths resolve")
  local p = model.particles.vfx_embers_particles
  A.truthy(p and p.texture:match("%.png$"), "particles texture")
  A.eq(p.emitter.amount, 12)
  A.eq(p.emitter.lifetime, 1.4)
  A.eq(p.emitter.one_shot, false)
  local t = model.transition.transition_wipe
  A.eq(t.transition, "wipe")
  A.eq(t.size[1], 8)
  local n = model.normal_map.spr_crate_n
  A.eq(n.convention, "opengl")
  A.truthy(n.target:match("spr_crate%.png$"), "the lit target is a resolved path")
  local img = model.image.logo_golden
  A.eq(img.role, "logo")
  A.eq(img.size[2], 4)
  for _, k in ipairs(Manifest.EXTRA_KINDS) do
    local found = false
    for _, a in ipairs(model.order) do if a.kind == k then found = true end end
    A.truthy(found, k .. " is in model.order")
  end
end

function T.test_golden_files_ship_and_fit()
  local problems = Loader.verify(model)
  A.eq(#problems, 0, table.concat(problems, "\n"))
  A.truthy(#model.files > 40, "the golden pack names its PNGs and the .fnt (" .. #model.files .. " files)")
end

-- ---- A sheet render_sprites.py rendered from the golden rigged character (#290) ----
-- Rows are directions, columns frames: a clip's rects sit on its own row of a shared sheet.
local CHAR = "data/golden/character/sprites/"

function T.test_rendered_character_loads_as_its_expected_json()
  local want = read_json(CHAR .. "expected.json")
  local m = Loader.load(CHAR .. "dotwork/character.assets.json")
  A.eq(#m.warnings, 0, table.concat(m.warnings, "\n"))
  local n = 0
  for _, key in ipairs(Json.sorted_keys(want.assets)) do
    local kind, name = key:match("^([^/]+)/(.+)$")
    local a = m[kind] and m[kind][name]
    A.truthy(a, key .. " was not imported")
    Golden.expect(shape[kind](a, m), want.assets[key], TOL, key)
    n = n + 1
  end
  A.truthy(n > 0, "the rendered character has an asset")
  local problems = Loader.verify(m)
  A.eq(#problems, 0, table.concat(problems, "\n"))
end

-- ---- Timing: each frame's own duration, not fps ----------------------------------
function T.test_player_uses_frame_durations()
  local clip = model.animated_sprite.hero.clips.walk_s          -- durations 0.125 0.125 0.25 0.125 (holds 1 1 2 1)
  local p = Manifest.player(clip)
  -- t = 0.1 0.2 0.3 0.45 0.55 0.65 (wraps to 0.025): frame 3 is the held one (0.25 to 0.5)
  local steps = { { 0.1, 1 }, { 0.1, 2 }, { 0.1, 3 }, { 0.15, 3 }, { 0.1, 4 }, { 0.1, 1 } }
  for i, s in ipairs(steps) do
    p:update(s[1])
    A.eq(p.index, s[2], "walk_s step " .. i .. " (t=" .. p.t .. ")")
  end
  A.falsy(p.done, "a looping clip never ends")
end

function T.test_one_shot_holds_last_frame()
  local p = Manifest.player(model.animated_sprite.hero.clips.attack_e)   -- 0.1 0.2 0.1, no loop
  p:update(0.15)
  A.eq(p.index, 2, "the long hit frame")
  p:update(1)
  A.eq(p.index, 3)
  A.truthy(p.done)
end

-- ---- Autotile rule ----------------------------------------------------------------------
function T.test_canon_folds_256_masks_into_47()
  local seen, n = {}, 0
  for m = 0, 255 do
    local c = Manifest.canon(m)
    if not seen[c] then seen[c], n = true, n + 1 end
  end
  A.eq(n, 47)
  A.eq(Manifest.canon(255), 255)
  A.eq(Manifest.canon(2), 0, "NE alone does not count")
end

function T.test_sides4_keeps_side_bits_only()
  local painted = Manifest.painted_set({ { 1, 1 }, { 1, 0 }, { 2, 0 }, { 2, 1 } })
  A.eq(Manifest.cell_mask(painted, 1, 1, "sides4"), 1 + 4)       -- N and E; the NE corner is dropped
  A.eq(Manifest.cell_mask(painted, 1, 1), 1 + 2 + 4)             -- blob: NE counts, both sides are set
end

-- corners4 on a 3x3 block: a corner is the terrain when all four cells meeting there are painted
function T.test_corners4_on_a_3x3_block()
  local cells = {}
  for y = 0, 2 do for x = 0, 2 do cells[#cells + 1] = { x, y } end end
  local painted = Manifest.painted_set(cells)
  A.eq(Manifest.cell_mask(painted, 1, 1, "corners4"), 170, "the centre holds all four corners")
  A.eq(Manifest.cell_mask(painted, 0, 0, "corners4"), 8, "top-left cell: SE only")
  A.eq(Manifest.cell_mask(painted, 1, 0, "corners4"), 40, "top-middle cell: SE and SW")
  A.eq(Manifest.cell_mask(painted, 2, 2, "corners4"), 128, "bottom-right cell: NW only")
end

-- A corners4 tile's key: the sum of the corner bits holding its own terrain, names by shape
function T.test_corners4_tile_keys_by_shape()
  local sq = { terrain = 1, corners = { top_left = 1, top_right = 0, bottom_right = 1, bottom_left = 0 } }
  A.eq(Manifest.terrain_key(sq, "corners4", "square"), 128 + 8)
  local iso = { terrain = 1, corners = { top = 0, right = 1, bottom = 0, left = 1 } }
  A.eq(Manifest.terrain_key(iso, "corners4", "isometric"), 2 + 32)
  A.eq(Manifest.terrain_key(iso, "corners4", "square"), nil, "iso corner names are not a square tile's")
  A.eq(Manifest.terrain_key({ terrain = 1, mask = 255 }, "blob47", "square"), 255)
  local ts = model.tileset.meadow
  A.truthy(Manifest.candidates(ts, 0, 0, 170), "meadow grass has a tile with all four corners")
  A.falsy(Manifest.candidates(ts, 0, 0, 1), "no grass tile answers to a side bit")
end

-- ---- The variant pick: the spec's vectors (ASSET_MANIFEST.md "Variants: the probability pick") ----
function T.test_hash32_vectors()
  A.eq(Manifest.hash32(0), 1800329511)
  A.eq(Manifest.hash32(1), 3028713910)
  A.eq(Manifest.hash32(0xFFFFFFFF), 4268016002)
  A.eq(Manifest.hash32(0xFFFFFFFF + 1), Manifest.hash32(0), "the input is taken modulo 2^32")
  for _, k in ipairs({ 0, 1, 7, 0xFFFF, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF }) do
    local h = Manifest.hash32(k)
    A.truthy(h >= 0 and h < 4294967296 and h == math.floor(h), "hash32(" .. k .. ") is a 32-bit integer")
  end
end

function T.test_cell_roll_vectors()
  A.near(Manifest.cell_roll(0, 0, 0), 0.169182, TOL)
  A.near(Manifest.cell_roll(3, 1, 1), 0.765973, TOL)
  A.near(Manifest.cell_roll(3, 2, 1), 0.531301, TOL)
  A.near(Manifest.cell_roll(-1, -1, 0), 0.992978, TOL, "coordinates wrap at 16 bits")
  A.near(Manifest.cell_roll(0x10003, 1, 1), Manifest.cell_roll(3, 1, 1), 0, "wrapped x rolls the same")
end

function T.test_pick_walks_weights_in_order()
  local c = { { 1, "base" }, { 0.6, "variant" } }
  A.eq(Manifest.pick_variant(c, 0), "base")
  A.eq(Manifest.pick_variant(c, 0.624), "base")           -- 0.624 * 1.6 = 0.9984 < 1
  A.eq(Manifest.pick_variant(c, 0.626), "variant")
  A.eq(Manifest.pick_variant(c, 0.999999), "variant")
  A.eq(Manifest.pick_variant({ { 0, "a" }, { 0, "b" } }, 0.5), "a", "all weights 0: the first")
  A.eq(Manifest.pick_variant({ { 0, "a" }, { 1, "b" } }, 0.0), "b", "weight 0 is never picked")
end

-- the yard's two full path cells: (3, 1) rolls the variant, (3, 2) the base tile (the layer is index 1)
function T.test_yard_path_variant_is_the_pick()
  local layer = model.map.yard.layers[2]
  A.eq(layer.name, "Path")
  A.eq(layer.index, 1, "0-based layer index")
  local by = {}
  for _, c in ipairs(layer.cells) do by[c.x .. "," .. c.y] = c end
  A.eq(by["3,1"].key, 255)
  A.eq(by["3,2"].key, 255)
  A.eq(#by["3,1"].variants, 2, "two tiles share key 255")
  A.falsy(by["3,1"].tile[2] == by["3,2"].tile[2], "the two full cells pick different variants")
end

-- ---- Placing tiles: isometric centres and origins ----------------------------------------------
function T.test_isometric_centres()
  local ts = { 16, 8 }
  local function c(x, y) local cx, cy = Manifest.cell_centre("isometric", x, y, ts) return { cx, cy } end
  A.same(c(0, 0), { 8, 4 }, 0)
  A.same(c(1, 0), { 16, 8 }, 0)
  A.same(c(0, 1), { 0, 8 }, 0)
  A.same(c(3, 2), { 16, 24 }, 0)
  local sx, sy = Manifest.cell_centre("square", 2, 3, { 8, 8 })
  A.same({ sx, sy }, { 20, 28 }, 0)
  A.eq(#model.map.isle.centres, 12, "every cell of the 4x3 isle, y outer then x")
  A.eq(model.map.isle.centres[2].x, 1)
  A.eq(model.map.isle.centres[5].y, 1)
end

function T.test_tile_origin_default_and_own()
  local atlas = { tile_size = { 16, 12 } }
  local ox, oy = Manifest.tile_origin({}, atlas)
  A.same({ ox, oy }, { 8, 6 }, 0, "the atlas tile's centre")
  ox, oy = Manifest.tile_origin({ origin = { 8, 8 } }, atlas)
  A.same({ ox, oy }, { 8, 8 }, 0)
  local blocks = model.map.isle.layers[3]
  A.eq(blocks.name, "Blocks")
  A.eq(blocks.cells[1].top, blocks.cells[1].cy - 8, "a raised block: its origin on the diamond's centre")
end

-- ---- Stamps: a layer of [x, y, stamp] expands into the stamp's tiles ----------------------------
function T.test_stamps_layer_expands()
  local ts = model.tileset.ground_yard
  A.eq(#ts.stamp_list, 1)
  A.eq(ts.stamp_list[1].name, "door")
  local cells = Manifest.expand_stamps(ts, { { 7, 0, 0 } })
  A.eq(#cells, 2, "a 1x2 door is two tiles")
  A.eq(cells[1].x, 7); A.eq(cells[1].y, 0)
  A.eq(cells[2].x, 7); A.eq(cells[2].y, 1, "tile j at (x + j % w, y + floor(j / w))")
  A.same(cells[1].tile, ts.stamp_list[1].tiles[1], 0)
  A.eq(cells[2].stamp, 0, "the stamp's 0-based index")
  local fixtures = model.map.yard.layers[5]
  A.eq(fixtures.kind, "stamps")
  A.eq(fixtures.count, 2, "a stamps layer counts its expanded tiles")
  -- a 2x2 stamp from a fake tileset: reading order
  local fake = { stamp_list = { { index = 0, size = { 2, 2 }, tiles = { { 0, 0, 0 }, { 0, 1, 0 }, { 0, 0, 1 }, { 0, 1, 1 } } } } }
  local four = Manifest.expand_stamps(fake, { { 3, 5, 0 } })
  A.same({ four[2].x, four[2].y, four[3].x, four[3].y, four[4].x, four[4].y }, { 4, 5, 3, 6, 4, 6 }, 0)
end


-- ---- Tile flags: transpose first, then flip -------------------------------------------------
-- Maps texel centre (u, v) of a w x w tile through love.graphics.draw's transform about the tile centre.
local function apply(flags, u, v, w)
  local r, sx, sy = Manifest.tile_transform(flags)
  local px, py = (u - w / 2) * sx, (v - w / 2) * sy
  local c, s = math.cos(r), math.sin(r)
  return px * c - py * s + w / 2, px * s + py * c + w / 2
end

function T.test_tile_flags()
  local w = 4
  for flags = 0, 7 do
    for _, p in ipairs({ { 0.5, 1.5 }, { 3.5, 0.5 }, { 2.5, 2.5 } }) do
      local u, v = p[1], p[2]
      if flags >= 4 then u, v = v, u end                       -- transpose
      if flags % 2 == 1 then u = w - u end                     -- flip h
      if math.floor(flags / 2) % 2 == 1 then v = w - v end     -- flip v
      local x, y = apply(flags, p[1], p[2], w)
      A.near(x, u, 1e-9, "flags " .. flags .. " x")
      A.near(y, v, 1e-9, "flags " .. flags .. " y")
    end
  end
end

-- ---- Font: layout from chars matches LÖVE's BMFont metrics (11.5: A 4, AB 7, BA 8, space 3) ----
function T.test_text_layout_kerning()
  local font = model.font.tiny
  local function width(s) local _, w = Manifest.layout_text(font, s) return w end
  A.eq(width("A"), 4)
  A.eq(width("AB"), 7, "kerning A,B = -1")
  A.eq(width("BA"), 8)
  A.eq(width(" "), 3)
  A.eq(width("AZ"), 4, "a glyph the font lacks is skipped")
  local glyphs, _, h = Manifest.layout_text(font, "A\nB")
  A.eq(#glyphs, 2)
  A.eq(glyphs[2].y, font.line_height)
  A.eq(h, 2 * font.line_height)
end

-- ---- Version, kinds, fields, references ------------------------------------------------------
local function doc(fields)
  local d = { format = "dotwork-assets", version = "1.0.0", pack = "t", base = "..", assets = {} }
  for k, v in pairs(fields or {}) do d[k] = v end
  return d
end

function T.test_refuses_another_major()
  local ok, err = pcall(Manifest.parse, doc({ version = "2.0.0" }), "assets/dotwork/t.assets.json")
  A.falsy(ok)
  A.truthy(tostring(err):find("2.0.0", 1, true) and tostring(err):find("major 1", 1, true), tostring(err))
  A.truthy(pcall(Manifest.parse, doc({ version = "1.7.3" }), "assets/dotwork/t.assets.json"), "a newer minor loads")
  A.falsy(pcall(Manifest.parse, doc({ format = "other" }), "assets/dotwork/t.assets.json"))
end

function T.test_unknown_kind_and_field_warn_once()
  local m = Manifest.parse(doc({ assets = {
    { kind = "hologram", name = "a" }, { kind = "hologram", name = "b" },
    { kind = "icon", name = "i", sizes = { { size = 8, image = "art/i.png" } }, sparkle = true },
    { kind = "icon", name = "j", sizes = {}, sparkle = 2 } } }), "assets/dotwork/t.assets.json")
  A.eq(#m.warnings, 2, table.concat(m.warnings, "\n"))
  A.eq(#m.skipped, 2)
  A.truthy(m.icon.i and m.icon.j, "known kinds still load")
  A.eq(m.icon.i.sizes[1].image, "assets/art/i.png", "paths resolve through base")
end

function T.test_broken_references_are_problems()
  local m = Manifest.parse(doc({ assets = {
    { kind = "map", name = "m", tileset = "nope", size = { 2, 2 }, tile_size = { 8, 8 }, layers = {},
      objects = { { asset = "ghost", x = 0, y = 0 } } } } }), "assets/dotwork/t.assets.json")
  A.eq(#m.problems, 2, table.concat(m.problems, "\n"))
end

function T.test_paths_never_leave_the_game_folder()
  A.falsy(pcall(Manifest.parse, doc({ assets = {
    { kind = "icon", name = "i", sizes = { { size = 8, image = "../../x.png" } } } } }), "assets/dotwork/t.json"))
  A.eq(Manifest.normalize("a/b/../c/./d.png"), "a/c/d.png")
end

-- ---- Layer kinds, stamps and keys the tileset cannot answer ---------------------------------------
local function tiny_tileset(fields)
  local t = { kind = "tileset", name = "t", tile_size = { 8, 8 }, shape = "square", terrain_sets = {},
              atlases = { { id = 0, name = "a", role = "base", image = "art/a.png", tile_size = { 8, 8 }, columns = 1,
                            rows = 1, tiles = { { col = 0, row = 0 } } } } }
  for k, v in pairs(fields or {}) do t[k] = v end
  return t
end

function T.test_unknown_layer_kind_warns_once_and_a_bad_stamp_is_a_problem()
  local m = Manifest.parse(doc({ assets = {
    tiny_tileset({ stamps = { { name = "s", size = { 1, 1 }, solid = false, tiles = { { 0, 0, 0 } } } } }),
    { kind = "map", name = "m", tileset = "t", size = { 4, 4 }, tile_size = { 8, 8 }, layers = {
      { name = "A", kind = "hologram", cells = { { 0, 0 } } }, { name = "B", kind = "hologram", cells = { { 1, 1 } } },
      { name = "C", kind = "stamps", cells = { { 0, 0, 0 }, { 2, 2, 7 } } } } } } }), "assets/dotwork/t.assets.json")
  A.eq(#m.warnings, 1, table.concat(m.warnings, "\n"))
  A.truthy(m.warnings[1]:find("hologram", 1, true), m.warnings[1])
  A.eq(m.map.m.layers[1].count, 0)
  A.eq(m.map.m.layers[3].count, 1, "the known stamp is placed")
  A.eq(#m.problems, 1, table.concat(m.problems, "\n"))
  A.truthy(m.problems[1]:find("stamp 7", 1, true), m.problems[1])
  A.eq(m.map.m.layers[3].cells[1].left, 0)
  A.eq(m.map.m.layers[3].cells[1].top, 0)
end

-- a terrain key no tile answers to: the cell stays empty, one warning for the layer
function T.test_missing_terrain_tile_warns_once_per_layer()
  local m = Manifest.parse(doc({ assets = {
    tiny_tileset({ terrain_sets = { { id = 0, mode = "sides4", terrains = { { id = 0, name = "x", color = "#fff" } } } },
                   atlases = { { id = 0, name = "a", role = "base", image = "art/a.png", tile_size = { 8, 8 },
                                 columns = 1, rows = 1,
                                 tiles = { { col = 0, row = 0, terrain_set = 0, terrain = 0, mask = 0 } } } } }),
    { kind = "map", name = "m", tileset = "t", size = { 4, 4 }, tile_size = { 8, 8 }, layers = {
      { name = "T", kind = "terrain", terrain_set = 0, terrain = 0, cells = { { 0, 0 }, { 1, 0 }, { 3, 3 } } } } } } }),
    "assets/dotwork/t.assets.json")
  A.eq(#m.warnings, 1, table.concat(m.warnings, "\n"))
  local L = m.map.m.layers[1]
  A.eq(#L.cells, 3, "every painted cell is listed")
  A.eq(L.count, 1, "only the lone cell (mask 0) has a tile")
  A.falsy(L.cells[1].tile, "(0,0) needs E, which no tile has")
end

return T

-- {{FOOTER}}
