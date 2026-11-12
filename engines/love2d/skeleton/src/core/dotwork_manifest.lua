-- ---------------------------------------------------------------------------
-- dotwork_manifest.lua
-- Purpose : Reads a Dotwork asset manifest (<pack>.assets.json, spec in tools/art/dotwork/ASSET_MANIFEST.md) into
--           plain Lua tables the game draws from: sprites, animated sprites with per-frame durations, icons,
--           portraits, BMFont fonts, UI kits, tilesets and maps whose terrain layers are resolved with the spec's
--           autotile rules (blob47, sides4, corners4) and probability pick, stamps layers expanded into tiles,
--           every placed cell with its draw position, plus the extra kinds (background, particles, transition,
--           normal_map, image) as data. Engine-free: no love.* calls, so tests run it without a window.
-- Usage   : local Manifest = require("src.core.dotwork_manifest")
--           local model = Manifest.parse(Json.decode(text), "assets/dotwork/town.assets.json")
--           model.animated_sprite.hero.clips.walk_s.frames[1].duration   -- seconds
--           model.map.yard.layers[2].cells[1]        -- { x, y, key, tile = {atlas, col, row}, cx, cy, left, top, flags }
--           model.map.yard.centres[1]                -- { x, y, cx, cy }: every cell's centre in map pixels
--           model.map.yard.layers[5].cells           -- a stamps layer, expanded: one cell per tile of each stamp
--           Manifest.cell_centre("isometric", 1, 0, { 16, 8 })   -- 16, 8 (the spec's placing rule)
--           local p = Manifest.player(model.animated_sprite.hero.clips.walk_s); p:update(dt); p.index
--           model.background.hills.layers[2].velocity   model.particles.embers.emitter   model.image.logo.image
--           model.warnings   skipped kinds and fields (log them)    model.problems   broken references (fail on them)
--           model.files      every file the manifest names, with the size it must have (the loader checks them)
-- Notes   : Version rule: reads every 1.x.y manifest (spec 1.1.0; 1.0.0 packs still load), refuses another major
--           with a message naming both. Unknown kinds are skipped with one warning per kind, unknown layer kinds
--           with one warning per kind, unknown fields with one warning per kind and field. Paths come out resolved
--           from the game folder: join(dirname(manifest), base, path). A terrain cell's tile is picked among the
--           tiles of its terrain with the cell's key (the blob mask, the side bits, or the corner bits) by
--           probability with the spec's cell_roll (Jenkins hash, the same pick in every engine); every candidate is
--           kept in cell.variants. A cell with no tile for its key stays empty (one warning per layer; the
--           validator refuses such maps). Cells land as the spec's "Placing tiles" says: the tile's origin (its
--           `origin` field, else the atlas tile's centre) on the cell centre, isometric in Godot's diamond-down
--           layout, so an iso map's left column sits left of x = 0.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): corners4 keys, the
--           probability pick (hash32 / cell_roll), stamps layers, cell centres and placed positions, the extra
--           kinds loaded as data instead of skipped.
-- ---------------------------------------------------------------------------
--
-- Pseudocode
--   parse(doc, path): check format and major version -> base dir = normalize(dirname(path) / doc.base)
--     for each kind in dependency order (sprite, animated_sprite, icon, portrait, font, ui_kit, tileset, map,
--     then the extra kinds): convert every asset (required fields checked, unknown fields warned, paths resolved)
--     unknown kinds: one warning each, their image paths still listed in model.files
--   tileset: tiles filed by terrain and key (mask, or the sum of the corner bits holding the tile's own terrain)
--   map terrain layer: painted = its cells; key = cell_mask(painted, x, y, mode); candidates = tiles of the
--     layer's terrain with that key, in atlas order; tile = pick(candidates, cell_roll(x, y, layer_index))
--   map stamps layer: each [x, y, stamp] -> the stamp's tiles, tile j at (x + j % w, y + floor(j / w))
--   every placed cell: centre = cell_centre(shape, x, y, map tile_size); left, top = centre - tile origin
--   player(clip): time advances by dt; the frame is the one whose cumulative duration window holds the time;
--     a loop wraps, a one-shot holds its last frame and sets done
local bit = require("bit")                 -- LuaJIT's bit operations (Lua 5.1 has none)
local Json = require("src.core.json")

local Manifest = {}

-- ---- Tunables (the spec's constants) -------------------------------------------
Manifest.FORMAT = "dotwork-assets"
Manifest.MAJOR = 1                        -- the spec major this importer reads (spec 1.1.0; 1.0.0 loads too)
Manifest.SUFFIX = ".assets.json"
Manifest.CORE_KINDS = { "animated_sprite", "sprite", "icon", "portrait", "tileset", "map", "font", "ui_kit" }
Manifest.EXTRA_KINDS = { "background", "particles", "transition", "normal_map", "image" }
Manifest.KINDS = {}                       -- every kind this importer loads (core first, then the extra kinds)
for _, k in ipairs(Manifest.CORE_KINDS) do Manifest.KINDS[#Manifest.KINDS + 1] = k end
for _, k in ipairs(Manifest.EXTRA_KINDS) do Manifest.KINDS[#Manifest.KINDS + 1] = k end
-- parse order: a portrait names an animated_sprite, a map names a tileset and sprite objects
local PARSE_ORDER = { "sprite", "animated_sprite", "icon", "portrait", "font", "ui_kit", "tileset", "map",
                      "background", "particles", "transition", "normal_map", "image" }
-- N NE E SE S SW W NW, y down: bit b is NB8[b + 1]
Manifest.NB8 = { { 0, -1 }, { 1, -1 }, { 1, 0 }, { 1, 1 }, { 0, 1 }, { -1, 1 }, { -1, 0 }, { -1, -1 } }
Manifest.SIDES_ONLY = 1 + 4 + 16 + 64     -- N, E, S, W
Manifest.CORNERS_ONLY = 2 + 8 + 32 + 128  -- NE, SE, SW, NW
-- a corners4 tile's corner names per shape and the mask bit of the cell across that corner (spec "Autotiling"):
-- a diamond's top corner touches the cell up the screen, which is NW in map coordinates
Manifest.CORNER_BITS = {
  square = { top_left = 128, top_right = 2, bottom_right = 8, bottom_left = 32 },
  isometric = { top = 128, right = 2, bottom = 8, left = 32 },
}
Manifest.FLIP_H, Manifest.FLIP_V, Manifest.TRANSPOSE = 1, 2, 4
local M32 = 4294967296                    -- 2^32: hash32 keeps every step below it (the bit library is int32)

-- Fields each kind may carry (spec 1.1.0). Others are warned about once and ignored.
local KNOWN = {
  background = { "kind", "name", "role", "layers", "godot" },
  bg_layer = { "name", "image", "size", "velocity", "repeat", "wobble_px", "scale" },
  particles = { "kind", "name", "texture", "emitter", "godot" },
  transition = { "kind", "name", "image", "size", "transition", "godot" },
  normal_map = { "kind", "name", "image", "size", "target", "convention", "godot" },
  image = { "kind", "name", "role", "image", "size", "pivot", "godot" },
  animated_sprite = { "kind", "name", "role", "blend", "clips", "directions", "godot" },
  sprite = { "kind", "name", "role", "image", "size", "pivot", "content_rect", "collision", "shadow", "godot" },
  icon = { "kind", "name", "sizes" },
  portrait = { "kind", "name", "size", "expressions", "animation" },
  tileset = { "kind", "name", "tile_size", "shape", "terrain_sets", "atlases", "stamps", "custom_data", "godot" },
  map = { "kind", "name", "tileset", "size", "tile_size", "layers", "objects", "godot" },
  font = { "kind", "name", "file", "pages", "line_height", "base", "scale", "tint", "chars", "kerning", "license" },
  ui_kit = { "kind", "name", "role", "parts", "godot" },
  clip = { "name", "fps", "loop", "holds", "frame_size", "pivot", "sheet", "frames", "length" },
  tile = { "col", "row", "terrain_set", "terrain", "mask", "corners", "probability", "surface", "collision", "anim",
           "origin" },
}
for kind, list in pairs(KNOWN) do
  local set = {}
  for _, f in ipairs(list) do set[f] = true end
  KNOWN[kind] = set
end

local LOADED = {}
for _, k in ipairs(Manifest.KINDS) do LOADED[k] = true end

-- ---- Autotiling (the spec's rules, ported) -----------------------------------------
-- A corner bit only counts when both sides next to it are set: 256 raw masks fold into the 47 blob masks.
function Manifest.canon(m)
  for _, c in ipairs({ 1, 3, 5, 7 }) do   -- NE, SE, SW, NW
    local left, right = (c + 7) % 8, (c + 1) % 8
    if not (bit.band(bit.rshift(m, left), 1) == 1 and bit.band(bit.rshift(m, right), 1) == 1) then
      m = bit.band(m, bit.bnot(bit.lshift(1, c)))
    end
  end
  return m
end

local function key2(x, y) return x .. "," .. y end

-- The key a painted cell needs. painted: a set built by Manifest.painted_set(cells). mode: "blob47" (default,
-- the canon mask), "sides4" (N E S W bits) or "corners4" (the corner bits of the canon mask: a corner is the
-- terrain only when all four cells meeting there are painted).
function Manifest.cell_mask(painted, x, y, mode)
  local m = 0
  for b, d in ipairs(Manifest.NB8) do
    if painted[key2(x + d[1], y + d[2])] then m = m + bit.lshift(1, b - 1) end
  end
  if mode == "sides4" then return bit.band(m, Manifest.SIDES_ONLY) end
  if mode == "corners4" then return bit.band(Manifest.canon(m), Manifest.CORNERS_ONLY) end
  return Manifest.canon(m)
end

function Manifest.painted_set(cells)
  local set = {}
  for _, c in ipairs(cells) do set[key2(c[1], c[2])] = true end
  return set
end

-- A corners4 tile's corners as a list in sorted corner-name order (the spec's comparable form).
function Manifest.corner_list(corners)
  local names = {}
  for name in pairs(corners) do names[#names + 1] = name end
  table.sort(names)
  local out = {}
  for i, name in ipairs(names) do out[i] = corners[name] end
  return out
end

-- The key a tileset tile answers to: its mask (blob47, sides4), or the sum of the corner bits whose corner holds
-- the tile's own terrain (corners4, corner names by shape). nil when it has neither, or the corner names are not
-- the shape's. (Manifest.tile_key is the "atlas,col,row" lookup string, below.)
function Manifest.terrain_key(tile, mode, shape)
  if mode ~= "corners4" then return tile.mask end
  local corners = tile.corners
  if type(corners) ~= "table" then return nil end
  local names = Manifest.CORNER_BITS[shape] or Manifest.CORNER_BITS.square
  local key, n = 0, 0
  for name, b in pairs(names) do
    if corners[name] == nil then return nil end
    n = n + 1
    if corners[name] == tile.terrain then key = key + b end
  end
  for name in pairs(corners) do if not names[name] then return nil end end
  return key
end

-- The key a tile is filed under for comparison (tests): the mask number, or the corner list joined.
function Manifest.mask_key(tile)
  if tile.mask ~= nil then return tostring(tile.mask) end
  if tile.corners then return table.concat(Manifest.corner_list(tile.corners), ",") end
  return nil
end

-- ---- The variant pick (spec "Variants: the probability pick") ----------------------------
-- Bob Jenkins' 32-bit integer hash: only shifts, adds and xors. LuaJIT's bit functions return signed int32, so
-- every result is brought back to [0, 2^32) with % M32; a << 12 of a 32-bit value is below 2^44, exact in a double.
local function u32(v) return v % M32 end

function Manifest.hash32(k)
  k = u32(k)
  k = u32(k + 0x7ED55D16 + u32(bit.lshift(k, 12)))
  k = u32(bit.bxor(k, 0xC761C23C, u32(bit.rshift(k, 19))))
  k = u32(k + 0x165667B1 + u32(bit.lshift(k, 5)))
  k = u32(bit.bxor(u32(k + 0xD3A2646C), u32(bit.lshift(k, 9))))
  k = u32(k + 0xFD7046C5 + u32(bit.lshift(k, 3)))
  return u32(bit.bxor(k, 0xB55A4F09, u32(bit.rshift(k, 16))))
end

-- The roll in [0, 1) that picks cell (x, y)'s variant on the layer at layer_index (0-based, the layer's position in
-- the map's layers list); coordinates wrap at 16 bits, so negative cells roll too.
function Manifest.cell_roll(x, y, layer_index)
  local key = u32(bit.bor(bit.lshift(bit.band(x, 0xFFFF), 16), bit.band(y, 0xFFFF)))
  return Manifest.hash32(Manifest.hash32(key) + layer_index) / M32
end

-- candidates: { { weight, value }, ... } in atlas order. The value whose weight span holds roll * total; the first
-- when every weight is 0 (weight 0 is never picked otherwise).
function Manifest.pick_variant(candidates, roll)
  local total = 0
  for _, c in ipairs(candidates) do total = total + c[1] end
  if total <= 0 then return candidates[1][2] end
  local u = roll * total
  for _, c in ipairs(candidates) do
    u = u - c[1]
    if u < 0 then return c[2] end
  end
  return candidates[#candidates][2]
end

-- ---- Placing tiles (spec "Placing tiles") ------------------------------------------------
-- The centre of cell (x, y) in map pixels, y down: squares in rows; isometric diamonds in Godot's diamond-down
-- layout (x runs down-right, y down-left; cell (0, 0) at (w/2, h/2), so cell (0, 1) is at x = 0 and the left
-- column sits left of it). tile_size is the map's cell: the diamond [w, h] on an isometric set.
function Manifest.cell_centre(shape, x, y, tile_size)
  local w, h = tile_size[1], tile_size[2]
  if shape == "isometric" then return (x - y + 1) * w / 2, (x + y + 1) * h / 2 end
  return (x + 0.5) * w, (y + 0.5) * h
end

-- The image point drawn on the cell centre: the tile's own origin, else the atlas tile's centre (the atlas's tile
-- size, which can be taller than the map cell: iso blocks).
function Manifest.tile_origin(tile, atlas)
  if tile.origin then return tile.origin[1], tile.origin[2] end
  return atlas.tile_size[1] / 2, atlas.tile_size[2] / 2
end

-- ---- Tile flags -----------------------------------------------------------------
-- Map cell flags (1 flip h, 2 flip v, 4 transpose; transpose first, then flip) as the rotation and scale for
-- love.graphics.draw about the tile's centre: x + R(r) * S(sx, sy) * (p - origin). Derivation: transpose is
-- (x, y) -> (y, x) = rotate +90 degrees (y down) of scale (1, -1); a flip afterwards negates one output axis.
function Manifest.tile_transform(flags)
  flags = flags or 0
  local fh = bit.band(flags, Manifest.FLIP_H) ~= 0
  local fv = bit.band(flags, Manifest.FLIP_V) ~= 0
  if bit.band(flags, Manifest.TRANSPOSE) ~= 0 then
    return math.pi / 2, fv and -1 or 1, fh and 1 or -1
  end
  return 0, fh and -1 or 1, fv and -1 or 1
end

-- ---- Paths ----------------------------------------------------------------------
-- "a/b/../c" -> "a/c". Errors when ".." climbs above the game folder.
function Manifest.normalize(path)
  local out = {}
  for part in path:gsub("\\", "/"):gmatch("[^/]+") do
    if part == ".." then
      if #out == 0 then error("path " .. path .. " leaves the game folder", 0) end
      out[#out] = nil
    elseif part ~= "." then
      out[#out + 1] = part
    end
  end
  return table.concat(out, "/")
end

function Manifest.dirname(path)
  return path:match("^(.*)/[^/]*$") or "."
end

-- A manifest path must be relative, forward slashes, no "..", no drive (spec "Where it lives").
local function safe_rel(p)
  return type(p) == "string" and p ~= "" and not p:find("\\", 1, true) and p:sub(1, 1) ~= "/"
     and not p:find("^%a:") and not ("/" .. p .. "/"):find("/%.%./")
end

-- ---- Timing ---------------------------------------------------------------------
-- The frame index (1-based) showing at time t (seconds) of a clip, from the frames' own durations.
function Manifest.frame_at(clip, t)
  for i, start in ipairs(clip.starts) do
    if t < start + clip.frames[i].duration then return i end
  end
  return #clip.frames
end

local Player = {}
Player.__index = Player

-- A clip player: p:update(dt) moves p.index; p.done once a one-shot clip has shown its last frame for its duration.
function Manifest.player(clip)
  local p = setmetatable({}, Player)
  p:play(clip)
  return p
end

-- keep_if_playing: the clip already playing goes on (a walk that keeps its direction does not restart)
function Player:play(clip, keep_if_playing)
  if clip == self.clip and keep_if_playing then return end
  self.clip, self.t, self.index, self.done = clip, 0, 1, false
end

function Player:update(dt)
  local clip = self.clip
  if not clip or #clip.frames == 0 then return end
  self.t = self.t + dt
  if clip.loop then
    if clip.length > 0 then self.t = self.t % clip.length end
  elseif self.t >= clip.length then
    self.t, self.done = clip.length, true
  end
  self.index = Manifest.frame_at(clip, self.t)
end

function Player:frame() return self.clip and self.clip.frames[self.index] end

-- ---- Text layout (the BMFont fallback) --------------------------------------------
local function codepoints(text)
  local out = {}
  for ch in text:gmatch("[%z\1-\127\194-\244][\128-\191]*") do
    local b, n = ch:byte(1), #ch
    local cp = n == 1 and b or n == 2 and b % 32 or n == 3 and b % 16 or b % 8
    for i = 2, n do cp = cp * 64 + ch:byte(i) % 64 end
    out[#out + 1] = cp
  end
  return out
end

-- Glyph placements for text in a parsed font, at scale 1: { {char = row, x, y}, ... }, width, height. Kerning
-- applies between neighbours; a code point the font lacks is skipped (LÖVE's own BMFont does the same).
function Manifest.layout_text(font, text)
  local glyphs, pen, y, width, prev = {}, 0, 0, 0, nil
  for _, cp in ipairs(codepoints(text)) do
    if cp == 10 then
      pen, y, prev = 0, y + font.line_height, nil
    else
      local c = font.chars[cp]
      if c then
        if prev and font.kerning[prev] and font.kerning[prev][cp] then pen = pen + font.kerning[prev][cp] end
        if c.w > 0 and c.h > 0 then glyphs[#glyphs + 1] = { char = c, x = pen + c.xoffset, y = y + c.yoffset } end
        pen = pen + c.xadvance
        if pen > width then width = pen end
        prev = cp
      end
    end
  end
  return glyphs, width, y + font.line_height
end

-- ---- Parsing helpers --------------------------------------------------------------
local Ctx = {}
Ctx.__index = Ctx

local function is_num(v) return type(v) == "number" end

function Ctx:fail(where, msg) error(self.path .. ": " .. where .. ": " .. msg, 0) end
function Ctx:warn(msg) self.model.warnings[#self.model.warnings + 1] = msg end
function Ctx:problem(msg) self.model.problems[#self.model.problems + 1] = self.path .. ": " .. msg end

function Ctx:need(t, field, kind, where)
  local v = t[field]
  local ok
  if kind == "number" then ok = is_num(v)
  elseif kind == "string" then ok = type(v) == "string"
  elseif kind == "boolean" then ok = type(v) == "boolean"
  elseif kind == "list" then ok = type(v) == "table"
  elseif kind == "pair" then ok = type(v) == "table" and is_num(v[1]) and is_num(v[2])
  elseif kind == "rect" then ok = type(v) == "table" and is_num(v[1]) and is_num(v[2]) and is_num(v[3]) and is_num(v[4])
  end
  if not ok then self:fail(where, "field '" .. field .. "' is missing or not a " .. kind) end
  return v
end

-- JSON null and absent both mean "not given"
local function opt(v)
  if v == Json.null then return nil end
  return v
end

function Ctx:unknown_fields(t, set, label)
  for field in pairs(t) do
    if not set[field] then
      local key = label .. "." .. tostring(field)
      if not self.warned[key] then
        self.warned[key] = true
        self:warn(self.path .. ": " .. label .. " field '" .. tostring(field) .. "' is not in spec " ..
                  Manifest.MAJOR .. ".x: ignored")
      end
    end
  end
end

-- A manifest path -> a game-folder path, and the file listed for the loader to check.
function Ctx:file(rel, where, want_size, rects)
  if not safe_rel(rel) then self:fail(where, "path " .. tostring(rel) .. " is not a plain relative path") end
  local full = Manifest.normalize(self.base .. "/" .. rel)
  local f = self.files_by_path[full]
  if not f then
    f = { path = full, rel = rel, where = where, rects = {} }
    self.files_by_path[full] = f
    self.model.files[#self.model.files + 1] = f
  end
  if want_size and not f.size then f.size = { want_size[1], want_size[2] } end
  for _, r in ipairs(rects or {}) do f.rects[#f.rects + 1] = { r[1], r[2], r[3], r[4], where = where } end
  return full
end

local function copy_pair(p) return { p[1], p[2] } end
local function copy_rect(r) return { r[1], r[2], r[3], r[4] } end

local function collision_list(ctx, list, where)
  local out = {}
  for i, s in ipairs(opt(list) or {}) do
    local r = ctx:need(s, "rect", "rect", where .. " collision " .. i)
    out[i] = { r[1], r[2], r[3], r[4], one_way = s.one_way == true }
  end
  return out
end

-- ---- Kinds --------------------------------------------------------------------------
local convert = {}

function convert.sprite(ctx, a, where)
  local size = copy_pair(ctx:need(a, "size", "pair", where))
  local s = { kind = "sprite", name = a.name, role = a.role, size = size,
              pivot = copy_pair(ctx:need(a, "pivot", "pair", where)),
              content_rect = opt(a.content_rect) and copy_rect(a.content_rect) or nil,
              collision = collision_list(ctx, a.collision, where) }
  s.image = ctx:file(ctx:need(a, "image", "string", where), where, size)
  local sh = opt(a.shadow)
  if sh then
    s.shadow = { image = ctx:file(ctx:need(sh, "image", "string", where .. " shadow"), where .. " shadow"),
                 offset = copy_pair(ctx:need(sh, "offset", "pair", where .. " shadow")) }
  end
  return s
end

function convert.animated_sprite(ctx, a, where)
  local s = { kind = "animated_sprite", name = a.name, role = a.role, blend = opt(a.blend) or "normal",
              clips = {}, clip_order = {}, directions = {} }
  for ci, c in ipairs(ctx:need(a, "clips", "list", where)) do
    local cw = where .. " clip " .. tostring(c.name or ci)
    ctx:unknown_fields(c, KNOWN.clip, "clip")
    local fs = copy_pair(ctx:need(c, "frame_size", "pair", cw))
    local clip = { name = ctx:need(c, "name", "string", cw), fps = ctx:need(c, "fps", "number", cw),
                   loop = ctx:need(c, "loop", "boolean", cw), frame_size = fs,
                   pivot = copy_pair(ctx:need(c, "pivot", "pair", cw)), frames = {}, starts = {}, length = 0 }
    if opt(c.sheet) then clip.sheet = ctx:file(c.sheet, cw .. " sheet") end
    for fi, f in ipairs(ctx:need(c, "frames", "list", cw)) do
      local fw = cw .. " frame " .. fi
      local rect = copy_rect(ctx:need(f, "rect", "rect", fw))
      local duration = ctx:need(f, "duration", "number", fw)
      local file = ctx:file(ctx:need(f, "file", "string", fw), fw, fs, not clip.sheet and { rect } or nil)
      if clip.sheet then ctx:file(c.sheet, cw .. " sheet", nil, { rect }) end
      clip.starts[fi] = clip.length
      clip.frames[fi] = { file = file, rect = rect, duration = duration }
      clip.length = clip.length + duration
    end
    if s.clips[clip.name] then ctx:fail(cw, "two clips are named " .. clip.name) end
    s.clips[clip.name] = clip
    s.clip_order[#s.clip_order + 1] = clip.name
  end
  for action, dirs in pairs(opt(a.directions) or {}) do
    s.directions[action] = {}
    for dir, clip_name in pairs(dirs) do
      if not s.clips[clip_name] then ctx:problem(where .. ": direction " .. action .. "/" .. dir .. " names clip " ..
                                                 tostring(clip_name) .. ", which it does not have") end
      s.directions[action][dir] = clip_name
    end
  end
  return s
end

function convert.icon(ctx, a, where)
  local s = { kind = "icon", name = a.name, sizes = {}, by_size = {} }
  for i, e in ipairs(ctx:need(a, "sizes", "list", where)) do
    local n = ctx:need(e, "size", "number", where .. " size " .. i)
    local img = ctx:file(ctx:need(e, "image", "string", where .. " size " .. i), where .. " size " .. n, { n, n })
    s.sizes[#s.sizes + 1] = { size = n, image = img }
    s.by_size[n] = img
  end
  table.sort(s.sizes, function(x, y) return x.size < y.size end)
  return s
end

function convert.portrait(ctx, a, where, model)
  local size = copy_pair(ctx:need(a, "size", "pair", where))
  local s = { kind = "portrait", name = a.name, size = size, expressions = {}, by_name = {},
              animation = opt(a.animation) }
  for i, e in ipairs(ctx:need(a, "expressions", "list", where)) do
    local name = ctx:need(e, "name", "string", where .. " expression " .. i)
    local img = ctx:file(ctx:need(e, "image", "string", where .. " " .. name), where .. " " .. name, size)
    s.expressions[i] = { name = name, image = img }
    s.by_name[name] = img
  end
  if s.animation and not model.animated_sprite[s.animation] then
    ctx:problem(where .. ": animation " .. s.animation .. " is not an animated_sprite in this manifest")
  end
  return s
end

function convert.font(ctx, a, where)
  local s = { kind = "font", name = a.name, line_height = ctx:need(a, "line_height", "number", where),
              base = ctx:need(a, "base", "number", where), scale = ctx:need(a, "scale", "number", where),
              tint = ctx:need(a, "tint", "boolean", where), chars = {}, char_list = {}, kerning = {}, pages = {},
              license = opt(a.license) }
  s.file = ctx:file(ctx:need(a, "file", "string", where), where .. " .fnt")
  local per_page = {}
  for i, c in ipairs(ctx:need(a, "chars", "list", where)) do
    if type(c) ~= "table" or #c < 9 then ctx:fail(where, "char " .. i .. " is not [id, x, y, w, h, xoffset, " ..
                                                         "yoffset, xadvance, page]") end
    local row = { id = c[1], x = c[2], y = c[3], w = c[4], h = c[5], xoffset = c[6], yoffset = c[7],
                  xadvance = c[8], page = c[9], raw = { unpack(c, 1, 9) } }
    s.chars[row.id] = row
    s.char_list[i] = row
    per_page[row.page] = per_page[row.page] or {}
    if row.w > 0 and row.h > 0 then table.insert(per_page[row.page], { row.x, row.y, row.w, row.h }) end
  end
  for i, p in ipairs(ctx:need(a, "pages", "list", where)) do
    s.pages[i] = ctx:file(p, where .. " page " .. (i - 1), nil, per_page[i - 1])
  end
  for _, k in ipairs(opt(a.kerning) or {}) do
    s.kerning[k[1]] = s.kerning[k[1]] or {}
    s.kerning[k[1]][k[2]] = k[3]
  end
  return s
end

function convert.ui_kit(ctx, a, where)
  local s = { kind = "ui_kit", name = a.name, role = a.role, parts = {}, part_order = {} }
  for i, p in ipairs(ctx:need(a, "parts", "list", where)) do
    local pw = where .. " part " .. tostring(p.name or i)
    local size = copy_pair(ctx:need(p, "size", "pair", pw))
    local part = { name = ctx:need(p, "name", "string", pw), role = p.role, size = size, scale = opt(p.scale) or 1,
                   state = opt(p.state), control = opt(p.control), glyph = opt(p.glyph),
                   margins = opt(p.margins) and copy_rect(p.margins) or nil,
                   stretch_margin = opt(p.stretch_margin), hotspot = opt(p.hotspot) and copy_pair(p.hotspot) or nil }
    part.image = ctx:file(ctx:need(p, "image", "string", pw), pw, size)
    s.parts[part.name] = part
    s.part_order[#s.part_order + 1] = part.name
  end
  return s
end

local function tile_key(atlas, col, row) return atlas .. "," .. col .. "," .. row end
Manifest.tile_key = tile_key

function convert.tileset(ctx, a, where)
  local s = { kind = "tileset", name = a.name, tile_size = copy_pair(ctx:need(a, "tile_size", "pair", where)),
              shape = ctx:need(a, "shape", "string", where), terrain_sets = {}, atlases = {}, atlas_by_id = {},
              tiles = {}, tile_list = {}, by_key = {}, stamps = {}, stamp_list = {},
              custom_data = opt(a.custom_data) }
  for _, ts in ipairs(ctx:need(a, "terrain_sets", "list", where)) do
    local set = { id = ts.id, mode = ts.mode, terrains = {} }
    for _, t in ipairs(ts.terrains or {}) do set.terrains[t.id] = { id = t.id, name = t.name, color = t.color } end
    s.terrain_sets[ts.id] = set
  end
  for ai, at in ipairs(ctx:need(a, "atlases", "list", where)) do
    local aw = where .. " atlas " .. tostring(at.name or ai)
    local ts = copy_pair(ctx:need(at, "tile_size", "pair", aw))
    local atlas = { id = ctx:need(at, "id", "number", aw), name = at.name, role = at.role, tile_size = ts,
                    columns = ctx:need(at, "columns", "number", aw), rows = ctx:need(at, "rows", "number", aw) }
    atlas.image = ctx:file(ctx:need(at, "image", "string", aw), aw, nil,
                           { { 0, 0, atlas.columns * ts[1], atlas.rows * ts[2] } })
    s.atlases[ai] = atlas
    s.atlas_by_id[atlas.id] = atlas
    for _, t in ipairs(ctx:need(at, "tiles", "list", aw)) do
      ctx:unknown_fields(t, KNOWN.tile, "tile")
      local tile = { atlas = atlas.id, col = t.col, row = t.row, terrain_set = opt(t.terrain_set) or 0,
                     terrain = opt(t.terrain), mask = opt(t.mask), corners = opt(t.corners),
                     probability = opt(t.probability) or 1, surface = opt(t.surface),
                     collision = collision_list(ctx, t.collision, aw .. " tile " .. t.col .. "," .. t.row),
                     anim = opt(t.anim), origin = opt(t.origin) and copy_pair(t.origin) or nil }
      local last_col = t.col + (tile.anim and (tile.anim.frames - 1) or 0)
      if last_col >= atlas.columns or t.row >= atlas.rows then
        ctx:problem(aw .. ": tile " .. t.col .. "," .. t.row .. " is outside the " .. atlas.columns .. "x" ..
                    atlas.rows .. " atlas")
      end
      s.tiles[tile_key(atlas.id, t.col, t.row)] = tile
      s.tile_list[#s.tile_list + 1] = tile
    end
  end
  -- terrain tiles filed by "set/terrain" and key as { weight, tile } candidates in atlas order: atlases by id,
  -- tiles in list order (the spec's pick walks them in exactly this order)
  local ids = {}
  for id in pairs(s.atlas_by_id) do ids[#ids + 1] = id end
  table.sort(ids)
  for _, id in ipairs(ids) do
    for _, tile in ipairs(s.tile_list) do
      if tile.atlas == id and tile.terrain ~= nil then
        local set = s.terrain_sets[tile.terrain_set]
        local key = Manifest.terrain_key(tile, set and set.mode or "blob47", s.shape)
        if key ~= nil then
          local tk = tile.terrain_set .. "/" .. tile.terrain
          s.by_key[tk] = s.by_key[tk] or {}
          s.by_key[tk][key] = s.by_key[tk][key] or {}
          table.insert(s.by_key[tk][key], { tile.probability, tile })
        end
      end
    end
  end
  for i, st in ipairs(opt(a.stamps) or {}) do
    local sw = where .. " stamp " .. tostring(st.name or (i - 1))
    local stamp = { index = i - 1, name = ctx:need(st, "name", "string", sw), size = copy_pair(ctx:need(st, "size", "pair", sw)),
                    solid = st.solid == true, tiles = {} }
    for j, t in ipairs(ctx:need(st, "tiles", "list", sw)) do
      stamp.tiles[j] = { t[1], t[2], t[3] }
      if not s.tiles[tile_key(t[1], t[2], t[3])] then
        ctx:problem(sw .. " names tile " .. tile_key(t[1], t[2], t[3]) .. ", which the tileset does not have")
      end
    end
    s.stamps[stamp.name] = stamp
    s.stamp_list[i] = stamp                  -- a map's stamps layer names a stamp by its 0-based index: [index + 1]
  end
  return s
end

-- The { weight, tile } candidates of a terrain for a key, in atlas order (nil when no tile answers to it).
function Manifest.candidates(tileset, terrain_set, terrain, key)
  local by_terrain = tileset.by_key[(terrain_set or 0) .. "/" .. terrain]
  return by_terrain and by_terrain[key] or nil
end

-- Each painted cell of a terrain layer -> { x, y, key, tile = {atlas, col, row} | nil, variants }, sorted by y
-- then x. key is cell_mask's (the blob mask, the side bits or the corner bits); the tile is picked among the
-- candidates with that key by probability with cell_roll(x, y, layer_index) (0-based: the layer's position in
-- the map's layers list), so every engine picks the same variant; nil when no tile has the key.
function Manifest.resolve_terrain(tileset, layer, layer_index)
  local sid, tid = layer.terrain_set or 0, layer.terrain
  local set = tileset.terrain_sets[sid]
  local mode = set and set.mode or "blob47"
  local painted = Manifest.painted_set(layer.cells)
  local cells = {}
  for _, c in ipairs(layer.cells) do cells[#cells + 1] = { c[1], c[2] } end
  table.sort(cells, function(p, q) if p[2] ~= q[2] then return p[2] < q[2] end return p[1] < q[1] end)
  local out = {}
  for _, c in ipairs(cells) do
    local x, y = c[1], c[2]
    if not (out[#out] and out[#out].x == x and out[#out].y == y) then       -- a cell listed twice paints once
      local key = Manifest.cell_mask(painted, x, y, mode)
      local list = Manifest.candidates(tileset, sid, tid, key)
      local tile = list and Manifest.pick_variant(list, Manifest.cell_roll(x, y, layer_index or 0))
      out[#out + 1] = { x = x, y = y, key = key, tile = tile and { tile.atlas, tile.col, tile.row } or nil,
                        variants = list }
    end
  end
  return out
end

-- Each [x, y, stamp] of a stamps layer -> the stamp's tiles as cells { x, y, tile, stamp }, tile j at
-- (x + j % w, y + floor(j / w)), in the order of the layer's cells. A bad stamp index is a problem line.
function Manifest.expand_stamps(tileset, cells, ctx, where)
  local out = {}
  for _, c in ipairs(cells) do
    local stamp = tileset.stamp_list[(c[3] or -1) + 1]
    if not stamp then
      if ctx then ctx:problem(where .. ": cell " .. c[1] .. "," .. c[2] .. " names stamp " .. tostring(c[3]) ..
                              ", which the tileset does not have (" .. #tileset.stamp_list .. " stamps)") end
    else
      local sw = stamp.size[1]
      for j, t in ipairs(stamp.tiles) do
        local k = j - 1
        out[#out + 1] = { x = c[1] + k % sw, y = c[2] + math.floor(k / sw), tile = { t[1], t[2], t[3] },
                          stamp = stamp.index, flags = 0 }
      end
    end
  end
  return out
end

-- Where a placed cell's image lands: left, top in map pixels = the cell centre less the tile's origin.
local function place_cell(cell, map, ts)
  local tile = ts.tiles[tile_key(cell.tile[1], cell.tile[2], cell.tile[3])]
  local atlas = tile and ts.atlas_by_id[tile.atlas]
  if not atlas then return end
  local cx, cy = Manifest.cell_centre(map.shape, cell.x, cell.y, map.tile_size)
  local ox, oy = Manifest.tile_origin(tile, atlas)
  cell.cx, cell.cy, cell.left, cell.top = cx, cy, cx - ox, cy - oy
end

function convert.map(ctx, a, where, model)
  local s = { kind = "map", name = a.name, tileset_name = ctx:need(a, "tileset", "string", where),
              size = copy_pair(ctx:need(a, "size", "pair", where)),
              tile_size = copy_pair(ctx:need(a, "tile_size", "pair", where)), layers = {}, objects = {},
              centres = {} }
  local ts = model.tileset[s.tileset_name]
  s.tileset = ts
  s.shape = ts and ts.shape or "square"
  if not ts then ctx:problem(where .. ": tileset " .. s.tileset_name .. " is not in this manifest") end
  local mw, mh = s.size[1], s.size[2]
  for y = 0, mh - 1 do
    for x = 0, mw - 1 do
      local cx, cy = Manifest.cell_centre(s.shape, x, y, s.tile_size)
      s.centres[#s.centres + 1] = { x = x, y = y, cx = cx, cy = cy }
    end
  end
  for li, L in ipairs(ctx:need(a, "layers", "list", where)) do
    local lw = where .. " layer " .. tostring(L.name or li)
    local layer = { name = ctx:need(L, "name", "string", lw), kind = ctx:need(L, "kind", "string", lw),
                    index = li - 1, opacity = opt(L.opacity) or 1, cells = {}, count = 0 }
    ctx:need(L, "cells", "list", lw)
    local bad = false
    for _, c in ipairs(L.cells) do
      if not bad and not (c[1] >= 0 and c[1] < mw and c[2] >= 0 and c[2] < mh) then
        ctx:problem(lw .. ": cell " .. c[1] .. "," .. c[2] .. " is outside the " .. mw .. "x" .. mh .. " map")
        bad = true
      end
    end
    if layer.kind == "tiles" then
      for _, c in ipairs(L.cells) do
        local cell = { x = c[1], y = c[2], tile = { c[3], c[4], c[5] }, flags = c[6] or 0 }
        if ts and not bad and not ts.tiles[tile_key(c[3], c[4], c[5])] then
          ctx:problem(lw .. ": cell " .. c[1] .. "," .. c[2] .. " names tile " .. tile_key(c[3], c[4], c[5]) ..
                      ", which the tileset does not have")
          bad = true
        end
        layer.cells[#layer.cells + 1] = cell
      end
    elseif layer.kind == "terrain" then
      layer.terrain_set, layer.terrain = opt(L.terrain_set) or 0, ctx:need(L, "terrain", "number", lw)
      if ts then
        local set = ts.terrain_sets[layer.terrain_set]
        if not (set and set.terrains[layer.terrain]) then
          ctx:problem(lw .. ": terrain " .. layer.terrain .. " is not in tileset " .. ts.name)
        else
          layer.cells = Manifest.resolve_terrain(ts, { terrain_set = layer.terrain_set, terrain = layer.terrain,
                                                       cells = L.cells }, layer.index)
          local missing = 0
          for _, c in ipairs(layer.cells) do if not c.tile then missing = missing + 1 end end
          if missing > 0 then                       -- the validator refuses such a map; the cells stay empty
            ctx:warn(ctx.path .. ": " .. lw .. ": " .. missing .. " cell(s) need a key (" .. set.mode ..
                     ") the terrain has no tile for: left empty")
          end
        end
      end
    elseif layer.kind == "stamps" then
      if ts then layer.cells = Manifest.expand_stamps(ts, L.cells, ctx, lw) end
    else
      local k = "layer." .. layer.kind
      if not ctx.warned[k] then
        ctx.warned[k] = true
        ctx:warn(ctx.path .. ": " .. lw .. ": layer kind '" .. layer.kind .. "' is not in spec " .. Manifest.MAJOR ..
                 ".x: skipped")
      end
    end
    if ts then
      for _, cell in ipairs(layer.cells) do
        if cell.tile then
          place_cell(cell, s, ts)
          layer.count = layer.count + 1
        end
      end
    else
      layer.count = #L.cells
    end
    s.layers[li] = layer
  end
  for i, o in ipairs(opt(a.objects) or {}) do
    local ow = where .. " object " .. i
    local obj = { asset = ctx:need(o, "asset", "string", ow), x = ctx:need(o, "x", "number", ow),
                  y = ctx:need(o, "y", "number", ow) }
    obj.sprite = model.sprite[obj.asset]                -- props are sprites (the spec's mapbuild places them)
    if not obj.sprite then ctx:problem(ow .. ": " .. obj.asset .. " is not a sprite in this manifest") end
    s.objects[i] = obj
  end
  return s
end

-- ---- The extra kinds (loaded as data; the game object that uses them is the game's) ----------------
-- background: layers drawn first to last; `repeat` is none, x, y or xy (the view wraps the Image on those axes).
function convert.background(ctx, a, where)
  local s = { kind = "background", name = a.name, role = a.role, layers = {} }
  for i, L in ipairs(ctx:need(a, "layers", "list", where)) do
    local lw = where .. " layer " .. tostring(L.name or i)
    ctx:unknown_fields(L, KNOWN.bg_layer, "background layer")
    local size = copy_pair(ctx:need(L, "size", "pair", lw))
    local rep = opt(L["repeat"]) or "none"
    s.layers[i] = { name = opt(L.name), size = size, velocity = copy_pair(ctx:need(L, "velocity", "pair", lw)),
                    ["repeat"] = rep, repeat_x = rep == "x" or rep == "xy", repeat_y = rep == "y" or rep == "xy",
                    wobble_px = opt(L.wobble_px) or 0, scale = opt(L.scale) or 1 }
    s.layers[i].image = ctx:file(ctx:need(L, "image", "string", lw), lw, size)
  end
  return s
end

-- particles: the white mask texture and the emitter JSON as Dotwork writes it (amount, lifetime, one_shot,
-- colour steps ...), kept whole: the view builds a love ParticleSystem from the fields it knows.
function convert.particles(ctx, a, where)
  local s = { kind = "particles", name = a.name, emitter = ctx:need(a, "emitter", "list", where) }
  s.texture = ctx:file(ctx:need(a, "texture", "string", where), where .. " texture")
  return s
end

-- transition: a greyscale image; a pixel is covered once the progress passes its grey / 255.
function convert.transition(ctx, a, where)
  local size = copy_pair(ctx:need(a, "size", "pair", where))
  local s = { kind = "transition", name = a.name, size = size, transition = ctx:need(a, "transition", "string", where) }
  s.image = ctx:file(ctx:need(a, "image", "string", where), where, size)
  return s
end

-- normal_map: the map and the image it lights (both files must ship); green up (opengl) unless said otherwise.
function convert.normal_map(ctx, a, where)
  local size = copy_pair(ctx:need(a, "size", "pair", where))
  local s = { kind = "normal_map", name = a.name, size = size, convention = opt(a.convention) or "opengl" }
  s.image = ctx:file(ctx:need(a, "image", "string", where), where, size)
  s.target = ctx:file(ctx:need(a, "target", "string", where), where .. " target")
  return s
end

-- image: a loose PNG with what made it (role) and an optional pivot.
function convert.image(ctx, a, where)
  local size = copy_pair(ctx:need(a, "size", "pair", where))
  local s = { kind = "image", name = a.name, role = opt(a.role), size = size,
              pivot = opt(a.pivot) and copy_pair(a.pivot) or nil }
  s.image = ctx:file(ctx:need(a, "image", "string", where), where, size)
  return s
end

-- The file paths of a skipped (unknown) kind, so the loader still checks they ship.
local function extra_files(ctx, a, where)
  for _, field in ipairs({ "image", "texture", "target" }) do
    if type(a[field]) == "string" then ctx:file(a[field], where .. " " .. field) end
  end
  for i, L in ipairs(type(a.layers) == "table" and a.layers or {}) do
    if type(L) == "table" and type(L.image) == "string" then ctx:file(L.image, where .. " layer " .. i) end
  end
end

-- ---- The document ---------------------------------------------------------------------
-- Checks format and version; returns the major version number. Errors with a message naming both majors.
function Manifest.check_header(doc, path)
  if type(doc) ~= "table" or doc.format ~= Manifest.FORMAT then
    error(path .. ": not a Dotwork asset manifest (format is " .. tostring(type(doc) == "table" and doc.format) ..
          ", expected " .. Manifest.FORMAT .. ")", 0)
  end
  local major = tonumber(tostring(doc.version):match("^(%d+)%.%d+%.%d+$"))
  if not major then error(path .. ": version " .. tostring(doc.version) .. " is not MAJOR.MINOR.PATCH", 0) end
  if major ~= Manifest.MAJOR then
    error(path .. ": manifest version " .. doc.version .. " is major " .. major .. "; this importer reads major " ..
          Manifest.MAJOR .. " (" .. Manifest.MAJOR .. ".x.y): update the importer or rebuild the pack", 0)
  end
  return major
end

-- doc: the decoded JSON; path: the manifest's path in the game folder (love.filesystem style, forward slashes).
function Manifest.parse(doc, path)
  Manifest.check_header(doc, path)
  local model = { path = path, pack = doc.pack, version = doc.version, warnings = {}, problems = {}, files = {},
                  order = {} }
  for _, k in ipairs(Manifest.KINDS) do model[k] = {} end
  local ctx = setmetatable({ model = model, path = path, warned = {}, files_by_path = {} }, Ctx)
  ctx.base = Manifest.normalize(Manifest.dirname(path) .. "/" .. tostring(opt(doc.base) or "."))
  model.base = ctx.base
  if type(doc.assets) ~= "table" then ctx:fail("document", "field 'assets' is missing") end
  local by_kind, skipped = {}, {}
  for i, a in ipairs(doc.assets) do
    if type(a) ~= "table" or type(a.kind) ~= "string" or type(a.name) ~= "string" then
      ctx:fail("asset " .. i, "has no kind or name")
    end
    if LOADED[a.kind] then
      by_kind[a.kind] = by_kind[a.kind] or {}
      table.insert(by_kind[a.kind], a)
    else
      if not skipped[a.kind] then
        skipped[a.kind] = true
        ctx:warn(path .. ": kind '" .. a.kind .. "' is not in spec " .. Manifest.MAJOR .. ".x: skipped")
      end
      model.skipped = model.skipped or {}
      table.insert(model.skipped, { kind = a.kind, name = a.name })
      extra_files(ctx, a, a.kind .. " " .. a.name)
    end
  end
  for _, kind in ipairs(PARSE_ORDER) do
    for _, a in ipairs(by_kind[kind] or {}) do
      local where = kind .. " " .. a.name
      ctx:unknown_fields(a, KNOWN[kind], kind)
      if model[kind][a.name] then ctx:fail(where, "two " .. kind .. " assets are named " .. a.name) end
      local obj = convert[kind](ctx, a, where, model)
      model[kind][a.name] = obj
      model.order[#model.order + 1] = obj
    end
  end
  model.skipped = model.skipped or {}
  return model
end

return Manifest

-- {{FOOTER}}
