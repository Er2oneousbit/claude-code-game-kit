-- ---------------------------------------------------------------------------
-- test_dotwork_golden.lua
-- Purpose : The Dotwork asset importer (src/core/dotwork_manifest.lua, src/game/dotwork_loader.lua) against the
--           spec's golden fixture: loads data/golden/dotwork/assets/dotwork/golden.assets.json and compares what it
--           built with data/golden/dotwork/expected.json (the reference loader's result) to 1e-6, one test per
--           asset. Plus the pieces expected.json cannot show: frame timing, tile flags, BMFont text layout, version
--           refusal, unknown kinds and fields, broken references.
-- Usage   : python tools/dev.py test     (or --filter dotwork)
-- Notes   : Headless: PNGs are checked with love.image (no window). Drawing is covered by the smoke run, which
--           draws the starter scene's Dotwork art when the game has manifests. Never copy expected values into this
--           file: they come from expected.json, written by tools/art/dotwork/assetspec.py.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
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
  local layers, terrain, objects = {}, {}, {}
  for _, L in ipairs(a.layers) do
    layers[L.name] = L.count
    if L.kind == "terrain" and a.tileset then
      local cells = {}
      for i, c in ipairs(L.cells) do cells[i] = { c.x, c.y, c.mask, c.tile or Json.null } end
      terrain[L.name] = cells
    end
  end
  for i, o in ipairs(a.objects) do objects[i] = { o.asset, o.x, o.y } end
  return { size = a.size, layers = layers, terrain = terrain, objects = objects }
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

-- One test per asset of expected.json: core kinds compared field by field, extra kinds must be the skipped ones.
local core = {}
for _, k in ipairs(Manifest.CORE_KINDS) do core[k] = true end
local skipped = {}
for _, s in ipairs(model.skipped) do skipped[s.kind .. "/" .. s.name] = true end

for _, key in ipairs(Json.sorted_keys(expected.assets)) do
  local kind, name = key:match("^([^/]+)/(.+)$")
  T["test_asset_" .. key:gsub("%W", "_")] = function()
    if core[kind] then
      local a = model[kind][name]
      A.truthy(a, key .. " was not imported")
      Golden.expect(shape[kind](a), expected.assets[key], TOL, key)
    else
      A.truthy(skipped[key], key .. " (an extra kind) should be listed as skipped")
    end
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

function T.test_warnings_name_each_skipped_kind_once()
  local kinds = {}
  for _, w in ipairs(model.warnings) do
    local k = w:match("kind '([%w_]+)'")
    A.truthy(k, "unexpected warning: " .. w)
    A.falsy(kinds[k], "kind " .. k .. " warned twice")
    kinds[k] = true
  end
  for _, k in ipairs(Manifest.EXTRA_KINDS) do A.truthy(kinds[k], "no warning for the skipped kind " .. k) end
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

return T

-- {{FOOTER}}
