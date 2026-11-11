-- ---------------------------------------------------------------------------
-- dotwork_manifest.lua
-- Purpose : Reads a Dotwork asset manifest (<pack>.assets.json, spec in tools/art/dotwork/ASSET_MANIFEST.md) into
--           plain Lua tables the game draws from: sprites, animated sprites with per-frame durations, icons,
--           portraits, BMFont fonts, UI kits, tilesets and maps whose terrain layers are resolved with the spec's
--           blob rule. Engine-free: no love.* calls, so tests run it without a window.
-- Usage   : local Manifest = require("src.core.dotwork_manifest")
--           local model = Manifest.parse(Json.decode(text), "assets/dotwork/town.assets.json")
--           model.animated_sprite.hero.clips.walk_s.frames[1].duration   -- seconds
--           model.map.yard.layers[2].cells[1]                            -- { x, y, mask, tile = {atlas, col, row} }
--           local p = Manifest.player(model.animated_sprite.hero.clips.walk_s); p:update(dt); p.index
--           model.warnings   skipped kinds and fields (log them)    model.problems   broken references (fail on them)
--           model.files      every file the manifest names, with the size it must have (the loader checks them)
-- Notes   : Version rule: reads every 1.x.y manifest, refuses another major with a message naming both. Unknown
--           kinds and the extra kinds (background, particles, transition, normal_map, image) are skipped with one
--           warning per kind; unknown fields with one warning per kind and field. Paths come out resolved from the
--           game folder: join(dirname(manifest), base, path). Terrain layers take the FIRST tile (atlas order)
--           whose mask is the cell's, the variant the spec's loaded result names; every variant is kept in
--           tileset.by_mask for a game that wants to pick by probability. corners4 terrain layers keep the
--           reference loader's answer (a mask, no tile) and warn: the spec defines no corner rule for map layers yet.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
--
-- Pseudocode
--   parse(doc, path): check format and major version -> base dir = normalize(dirname(path) / doc.base)
--     for each kind in dependency order (sprite, animated_sprite, icon, portrait, font, ui_kit, tileset, map):
--       convert every asset of that kind (required fields checked, unknown fields warned, paths resolved)
--     unknown and extra kinds: one warning each, their image paths still listed in model.files
--   map terrain layer: painted = its cells; each cell's mask = canon(8 neighbour bits) (sides4: N E S W only);
--     tile = the first tile of that terrain and mask
--   player(clip): time advances by dt; the frame is the one whose cumulative duration window holds the time;
--     a loop wraps, a one-shot holds its last frame and sets done
local bit = require("bit")                 -- LuaJIT's bit operations (Lua 5.1 has none)
local Json = require("src.core.json")

local Manifest = {}

-- ---- Tunables (the spec's constants) -------------------------------------------
Manifest.FORMAT = "dotwork-assets"
Manifest.MAJOR = 1                        -- the spec major this importer reads (spec 1.0.0)
Manifest.SUFFIX = ".assets.json"
Manifest.CORE_KINDS = { "animated_sprite", "sprite", "icon", "portrait", "tileset", "map", "font", "ui_kit" }
Manifest.EXTRA_KINDS = { "background", "particles", "transition", "normal_map", "image" }
-- parse order: a portrait names an animated_sprite, a map names a tileset and sprite objects
local PARSE_ORDER = { "sprite", "animated_sprite", "icon", "portrait", "font", "ui_kit", "tileset", "map" }
-- N NE E SE S SW W NW, y down: bit b is NB8[b + 1]
Manifest.NB8 = { { 0, -1 }, { 1, -1 }, { 1, 0 }, { 1, 1 }, { 0, 1 }, { -1, 1 }, { -1, 0 }, { -1, -1 } }
Manifest.SIDES_ONLY = 1 + 4 + 16 + 64     -- N, E, S, W
Manifest.FLIP_H, Manifest.FLIP_V, Manifest.TRANSPOSE = 1, 2, 4

-- Fields each kind may carry (spec 1.0.0). Others are warned about once and ignored.
local KNOWN = {
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

local CORE, EXTRA = {}, {}
for _, k in ipairs(Manifest.CORE_KINDS) do CORE[k] = true end
for _, k in ipairs(Manifest.EXTRA_KINDS) do EXTRA[k] = true end

-- ---- Autotiling (the spec's blob rule, ported) ----------------------------------
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

-- painted: a set built by Manifest.painted_set(cells). mode: "blob47" (default) or "sides4".
function Manifest.cell_mask(painted, x, y, mode)
  local m = 0
  for b, d in ipairs(Manifest.NB8) do
    if painted[key2(x + d[1], y + d[2])] then m = m + bit.lshift(1, b - 1) end
  end
  if mode == "sides4" then return bit.band(m, Manifest.SIDES_ONLY) end
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

-- The key a tile is filed under in tileset.by_mask: the mask number, or the corner list joined.
function Manifest.mask_key(tile)
  if tile.mask ~= nil then return tostring(tile.mask) end
  if tile.corners then return table.concat(Manifest.corner_list(tile.corners), ",") end
  return nil
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
              tiles = {}, tile_list = {}, by_mask = {}, stamps = {}, custom_data = opt(a.custom_data) }
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
      if tile.terrain ~= nil then
        local mk = Manifest.mask_key(tile)
        if mk then
          local tk = tile.terrain_set .. "/" .. tile.terrain
          s.by_mask[tk] = s.by_mask[tk] or {}
          s.by_mask[tk][mk] = s.by_mask[tk][mk] or {}
          table.insert(s.by_mask[tk][mk], tile)       -- atlas order: [1] is the base variant
        end
      end
    end
  end
  for _, st in ipairs(opt(a.stamps) or {}) do
    s.stamps[st.name] = { name = st.name, size = copy_pair(st.size), solid = st.solid, tiles = st.tiles }
    for _, t in ipairs(st.tiles or {}) do
      if not s.tiles[tile_key(t[1], t[2], t[3])] then
        ctx:problem(where .. ": stamp " .. st.name .. " names tile " .. tile_key(t[1], t[2], t[3]) ..
                    ", which the tileset does not have")
      end
    end
  end
  return s
end

-- Each painted cell of a terrain layer -> { x, y, mask, tile = {atlas, col, row} | nil }, sorted by y then x.
function Manifest.resolve_terrain(tileset, layer)
  local sid, tid = layer.terrain_set or 0, layer.terrain
  local set = tileset.terrain_sets[sid]
  local mode = set and set.mode or "blob47"
  local variants = tileset.by_mask[sid .. "/" .. tid] or {}
  local painted = Manifest.painted_set(layer.cells)
  local cells = {}
  for _, c in ipairs(layer.cells) do cells[#cells + 1] = { c[1], c[2] } end
  table.sort(cells, function(p, q) if p[2] ~= q[2] then return p[2] < q[2] end return p[1] < q[1] end)
  local out = {}
  for _, c in ipairs(cells) do
    local x, y = c[1], c[2]
    if not (out[#out] and out[#out].x == x and out[#out].y == y) then       -- a cell listed twice paints once
      local m = Manifest.cell_mask(painted, x, y, mode)
      local list = mode ~= "corners4" and variants[tostring(m)] or nil
      local first = list and list[1]
      out[#out + 1] = { x = x, y = y, mask = m, tile = first and { first.atlas, first.col, first.row } or nil,
                        variants = list }
    end
  end
  return out
end

function convert.map(ctx, a, where, model)
  local s = { kind = "map", name = a.name, tileset_name = ctx:need(a, "tileset", "string", where),
              size = copy_pair(ctx:need(a, "size", "pair", where)),
              tile_size = copy_pair(ctx:need(a, "tile_size", "pair", where)), layers = {}, objects = {} }
  local ts = model.tileset[s.tileset_name]
  s.tileset = ts
  if not ts then ctx:problem(where .. ": tileset " .. s.tileset_name .. " is not in this manifest") end
  local mw, mh = s.size[1], s.size[2]
  for li, L in ipairs(ctx:need(a, "layers", "list", where)) do
    local lw = where .. " layer " .. tostring(L.name or li)
    local layer = { name = ctx:need(L, "name", "string", lw), kind = ctx:need(L, "kind", "string", lw),
                    opacity = opt(L.opacity) or 1, cells = {}, count = #ctx:need(L, "cells", "list", lw) }
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
          if set.mode == "corners4" then
            ctx:warn(ctx.path .. ": " .. lw .. ": corners4 terrain layers are not resolved to tiles yet (masks only)")
          end
          layer.cells = Manifest.resolve_terrain(ts, { terrain_set = layer.terrain_set, terrain = layer.terrain,
                                                       cells = L.cells })
          local missing = 0
          for _, c in ipairs(layer.cells) do if not c.tile then missing = missing + 1 end end
          if missing > 0 and set.mode ~= "corners4" then
            ctx:problem(lw .. ": " .. missing .. " cell(s) need a mask the tileset has no tile for")
          end
        end
      end
    else
      ctx:warn(ctx.path .. ": " .. lw .. ": layer kind '" .. layer.kind .. "' is not in spec 1.x: skipped")
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

-- The file paths of a skipped extra kind, so the loader still checks they ship.
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
  for _, k in ipairs(Manifest.CORE_KINDS) do model[k] = {} end
  local ctx = setmetatable({ model = model, path = path, warned = {}, files_by_path = {} }, Ctx)
  ctx.base = Manifest.normalize(Manifest.dirname(path) .. "/" .. tostring(opt(doc.base) or "."))
  model.base = ctx.base
  if type(doc.assets) ~= "table" then ctx:fail("document", "field 'assets' is missing") end
  local by_kind, skipped = {}, {}
  for i, a in ipairs(doc.assets) do
    if type(a) ~= "table" or type(a.kind) ~= "string" or type(a.name) ~= "string" then
      ctx:fail("asset " .. i, "has no kind or name")
    end
    if CORE[a.kind] then
      by_kind[a.kind] = by_kind[a.kind] or {}
      table.insert(by_kind[a.kind], a)
    else
      if not skipped[a.kind] then
        skipped[a.kind] = true
        ctx:warn(path .. ": kind '" .. a.kind .. "' " .. (EXTRA[a.kind] and "(an extra kind) is not imported yet"
                 or "is not in spec " .. Manifest.MAJOR .. ".x") .. ": skipped")
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
