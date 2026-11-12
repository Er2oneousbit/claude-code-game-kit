-- ---------------------------------------------------------------------------
-- dotwork_view.lua
-- Purpose : Draws what a Dotwork manifest describes (src/core/dotwork_manifest.lua): images with nearest filtering
--           and no mipmaps, one Quad per rect, animated sprites timed by each frame's duration, a SpriteBatch per
--           atlas and layer for maps (terrain, tiles and stamps layers, animated tiles, both shapes), BMFont fonts,
--           9-slice UI parts, icons, portraits, and the extra kinds: backgrounds (Images wrapped on their repeat
--           axes), particles (texture + a ParticleSystem from the emitter), transitions, normal maps, images.
-- Usage   : local View = require("src.game.dotwork_view")
--           local view = View.new()                          -- in love.draw or after the window exists
--           local hero = view:animated(model.animated_sprite.hero); hero:play_direction("walk", "e")
--           hero:update(dt); hero:draw(x, y, 2)              -- (x, y) is where the pivot (the feet) lands
--           view:draw_sprite(model.sprite.crate, x, y, 2)    -- contact shadow first, when it has one
--           local map = view:map(model.map.yard); map:update(dt); map:draw(x, y, 2)
--           view:print(model.font.tiny, "AB", x, y, 2)       -- the .fnt through love.graphics.newFont
--           view:draw_part(model.ui_kit.windows.parts.ui_window_plain, x, y, 2, w, h)   -- 9-slice when w, h given
--           local bg = view:background(model.background.hills); bg:update(dt); bg:draw(0, 0, 2, 640, 360)
--           local ps = view:particles(model.particles.embers)   -- { image, system = love ParticleSystem, emitter }
--           view:transition(model.transition.wipe).image     view:normal_map(model.normal_map.crate_n).image
--           view:draw_image(model.image.logo, x, y, 2)       -- its pivot (else the top-left) at (x, y)
-- Notes   : Needs a window: every love.graphics.new* call errors without one (docs/ENGINE.md gotcha 2), so build
--           the view lazily in draw. Pivots go straight into love.graphics.draw's origin arguments (y down, the
--           manifest's own axes: no conversion). Scale by whole numbers. Fonts: love.graphics.newFont(fntPath)
--           reads AngelCode BMFont text files and finds the pages beside the .fnt (checked on LÖVE 11.5); if that
--           fails, the font is drawn from the manifest's `chars` with one Quad per glyph. Map cells sit where the
--           spec's "Placing tiles" puts them (Manifest.cell_centre: squares in rows, isometric diamonds in Godot's
--           diamond-down layout, cell (0, 0) of a 16x8 set centred on (8, 4)) with each tile's origin on the centre,
--           so an iso map's left column reaches left of the map's x: leave room, or draw it from the map's centres.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): the spec's cell centres
--           (the old iso formula was Godot's layout from memory), stamps layers, per-axis wrap, the extra kinds.
-- ---------------------------------------------------------------------------
--
-- Pseudocode
--   image(path, wrap_x, wrap_y): cached newImage(path, no mipmaps), nearest filter, clamp unless asked to repeat
--   quad(image, rect): cached newQuad over the image's size
--   animated: a Manifest.player per instance; draw = frame's image + quad at (x, y) with origin = clip pivot
--   map: for each layer, cells grouped by atlas -> one SpriteBatch; a cell = tile quad at the cell's centre
--        (Manifest.cell_centre) with the tile's origin (flags rotate and flip about it); animated tiles re-set
--        their quad when the frame changes; objects (props) drawn after the layers, sorted by y
--   font: newFont(.fnt) in a pcall -> else glyph quads from chars (Manifest.layout_text)
--   background: a layer = Image wrapped on its repeat axes + a scroll offset moved by velocity (whole pixels),
--        drawn through a Quad the size of the view so the repeat shows
--   particles: newParticleSystem(texture, amount); lifetime, emission rate (amount / lifetime, or emit(amount)
--        for a one-shot), colour steps as setColors; the rest of the emitter JSON stays the game's to apply
local Log = require("src.core.log")
local Manifest = require("src.core.dotwork_manifest")

local View = {}
View.__index = View

-- ---- Tunables ----------------------------------------------------------------
local FILTER = "nearest"                  -- pixel art: nearest both ways
local LOG = "dotwork"

function View.new()
  return setmetatable({ images = {}, quads = {}, fonts = {} }, View)
end

-- ---- Textures ------------------------------------------------------------------
-- wrap_x, wrap_y: "clamp" (default) or "repeat" (background layers on their repeat axes). An image asked for
-- with another wrap than its cached one gets its own entry.
function View:image(path, wrap_x, wrap_y)
  wrap_x, wrap_y = wrap_x or "clamp", wrap_y or wrap_x or "clamp"
  local key = (wrap_x == "clamp" and wrap_y == "clamp") and path or (path .. "|" .. wrap_x .. "," .. wrap_y)
  local img = self.images[key]
  if not img then
    img = love.graphics.newImage(path, { mipmaps = false })
    img:setFilter(FILTER, FILTER)
    img:setWrap(wrap_x, wrap_y)
    self.images[key] = img
  end
  return img
end

function View:quad(path, x, y, w, h)
  local key = path .. "|" .. x .. "," .. y .. "," .. w .. "," .. h
  local q = self.quads[key]
  if not q then
    local iw, ih = self:image(path):getDimensions()
    q = love.graphics.newQuad(x, y, w, h, iw, ih)
    self.quads[key] = q
  end
  return q
end

-- ---- Sprites ---------------------------------------------------------------------
-- A sprite with its pivot at (x, y); its contact shadow first, centred `offset` from the pivot.
function View:draw_sprite(sprite, x, y, scale)
  scale = scale or 1
  if sprite.shadow then
    local img = self:image(sprite.shadow.image)
    local w, h = img:getDimensions()
    love.graphics.draw(img, x + sprite.shadow.offset[1] * scale, y + sprite.shadow.offset[2] * scale, 0, scale,
                       scale, w / 2, h / 2)
  end
  love.graphics.draw(self:image(sprite.image), x, y, 0, scale, scale, sprite.pivot[1], sprite.pivot[2])
end

local Animated = {}
Animated.__index = Animated

-- An animated sprite instance with its own clock, or drawing the frame of a Manifest.player the game already
-- updates (timing that also runs headless).
function View:animated(asset, clip_name, player)
  local a = setmetatable({ view = self, asset = asset }, Animated)
  a.player = player or Manifest.player(asset.clips[clip_name or asset.clip_order[1]])
  return a
end

function Animated:play(clip_name, keep_if_playing)
  local clip = self.asset.clips[clip_name]
  if not clip then Log.warn(LOG, self.asset.name .. " has no clip " .. tostring(clip_name)) return false end
  self.player:play(clip, keep_if_playing)
  return true
end

-- play the clip of an action facing a direction ("walk", "e"), from the manifest's directions table
function Animated:play_direction(action, dir)
  local dirs = self.asset.directions[action]
  local name = dirs and dirs[dir] or (action .. "_" .. dir)
  return self:play(name, true)
end

function Animated:update(dt) self.player:update(dt) end

function Animated:draw(x, y, scale)
  local clip, f = self.player.clip, self.player:frame()
  if not f then return end
  scale = scale or 1
  local path = clip.sheet or f.file
  local r = f.rect
  local blend = self.asset.blend == "add"
  if blend then love.graphics.setBlendMode("add") end
  love.graphics.draw(self.view:image(path), self.view:quad(path, r[1], r[2], r[3], r[4]), x, y, 0, scale, scale,
                     clip.pivot[1], clip.pivot[2])
  if blend then love.graphics.setBlendMode("alpha") end
end

-- ---- Icons, portraits, UI ------------------------------------------------------------
function View:draw_icon(icon, size, x, y, scale)
  local path = icon.by_size[size] or icon.sizes[#icon.sizes].image
  love.graphics.draw(self:image(path), x, y, 0, scale or 1, scale or 1)
end

function View:draw_portrait(portrait, expression, x, y, scale)
  local path = portrait.by_name[expression or "neutral"] or portrait.expressions[1].image
  love.graphics.draw(self:image(path), x, y, 0, scale or 1, scale or 1)
end

-- A UI part at (x, y): a cursor is offset by its hotspot; with w and h (in screen pixels) a part with margins is
-- drawn as a 9-slice (corners kept, edges and centre stretched).
function View:draw_part(part, x, y, scale, w, h)
  scale = (scale or 1) * (part.scale or 1)
  local path = part.image
  local img = self:image(path)
  if part.hotspot then x, y = x - part.hotspot[1] * scale, y - part.hotspot[2] * scale end
  if not (w and h and part.margins) then
    love.graphics.draw(img, x, y, 0, scale, scale)
    return
  end
  local iw, ih = part.size[1], part.size[2]
  local l, t, r, b = part.margins[1], part.margins[2], part.margins[3], part.margins[4]
  local cols = { { 0, l, x, l * scale }, { l, iw - l - r, x + l * scale, w - (l + r) * scale },
                 { iw - r, r, x + w - r * scale, r * scale } }
  local rows = { { 0, t, y, t * scale }, { t, ih - t - b, y + t * scale, h - (t + b) * scale },
                 { ih - b, b, y + h - b * scale, b * scale } }
  for _, row in ipairs(rows) do
    for _, col in ipairs(cols) do
      if col[2] > 0 and row[2] > 0 and col[4] > 0 and row[4] > 0 then
        love.graphics.draw(img, self:quad(path, col[1], row[1], col[2], row[2]), col[3], row[3], 0,
                           col[4] / col[2], row[4] / row[2])
      end
    end
  end
end

-- ---- Fonts ----------------------------------------------------------------------------
local GlyphFont = {}
GlyphFont.__index = GlyphFont

-- The font as LÖVE's own BMFont (font.love) or, when LÖVE cannot read the .fnt, glyph quads from chars.
function View:font(font)
  local f = self.fonts[font]
  if f then return f end
  f = { asset = font }
  local ok, lf = pcall(love.graphics.newFont, font.file)
  if ok then
    lf:setFilter(FILTER, FILTER)
    f.love = lf
  else
    Log.warn(LOG, font.file .. ": love.graphics.newFont could not read it (" .. tostring(lf) ..
                  "): drawing glyphs from the manifest's chars")
  end
  self.fonts[font] = f
  return f
end

-- Text in a manifest font with its top-left at (x, y); scale multiplies the font's own `scale`. A tinted font
-- (white ink) takes the current colour; a coloured one is drawn as is.
function View:print(font, text, x, y, scale)
  local f = self:font(font)
  local s = (scale or 1) * (font.scale or 1)
  local r, g, b, a = love.graphics.getColor()
  if not font.tint then love.graphics.setColor(1, 1, 1, a) end
  if f.love then
    love.graphics.print(text, f.love, x, y, 0, s, s)
  else
    for _, gl in ipairs((Manifest.layout_text(font, text))) do
      local c = gl.char
      local page = font.pages[c.page + 1]
      love.graphics.draw(self:image(page), self:quad(page, c.x, c.y, c.w, c.h), x + gl.x * s, y + gl.y * s, 0, s, s)
    end
  end
  love.graphics.setColor(r, g, b, a)
end

function View:text_width(font, text, scale)
  local f = self:font(font)
  local s = (scale or 1) * (font.scale or 1)
  if f.love then return f.love:getWidth(text) * s end
  local _, w = Manifest.layout_text(font, text)
  return w * s
end

-- ---- Maps -------------------------------------------------------------------------------
local MapView = {}
MapView.__index = MapView

-- The centre of cell (cx, cy) in map pixels: the spec's rule (Manifest.cell_centre), squares in rows, isometric
-- diamonds in Godot's diamond-down layout with cell (0, 0) centred on (w/2, h/2).
local function cell_centre(map, cx, cy)
  return Manifest.cell_centre(map.shape or (map.tileset and map.tileset.shape) or "square", cx, cy, map.tile_size)
end
View.cell_centre = cell_centre

-- The map's pixel bounds around its cell centres: left, top, right, bottom (an iso map's left column sits left
-- of x = 0, so draw it at x - left to keep it on screen).
function View.map_bounds(map)
  local l, t, r, b = math.huge, math.huge, -math.huge, -math.huge
  local hw, hh = map.tile_size[1] / 2, map.tile_size[2] / 2
  for _, c in ipairs(map.centres) do
    l, t, r, b = math.min(l, c.cx - hw), math.min(t, c.cy - hh), math.max(r, c.cx + hw), math.max(b, c.cy + hh)
  end
  if #map.centres == 0 then return 0, 0, 0, 0 end
  return l, t, r, b
end

local function anim_quad(view, atlas, col, row)
  local tw, th = atlas.tile_size[1], atlas.tile_size[2]
  return view:quad(atlas.image, col * tw, row * th, tw, th)
end

function View:map(map)
  local mv = setmetatable({ view = self, map = map, layers = {}, animated = {}, t = 0 }, MapView)
  local ts = map.tileset
  if not ts then Log.warn(LOG, "map " .. map.name .. " has no tileset: nothing to draw") return mv end
  local usage = "static"                  -- a hint: animated tiles re-set their quads, so those batches are dynamic
  for _, tile in ipairs(ts.tile_list) do if tile.anim then usage = "dynamic" break end end
  for _, layer in ipairs(map.layers) do
    local batches, order = {}, {}
    for _, cell in ipairs(layer.cells) do
      local ref = cell.tile
      local tile = ref and ts.tiles[Manifest.tile_key(ref[1], ref[2], ref[3])]
      local atlas = tile and ts.atlas_by_id[tile.atlas]
      if atlas then
        local b = batches[atlas.id]
        if not b then
          b = love.graphics.newSpriteBatch(self:image(atlas.image), #layer.cells, usage)
          batches[atlas.id] = b
          order[#order + 1] = atlas.id
        end
        local x, y = cell_centre(map, cell.x, cell.y)
        local ox = tile.origin and tile.origin[1] or atlas.tile_size[1] / 2
        local oy = tile.origin and tile.origin[2] or atlas.tile_size[2] / 2
        local r, sx, sy = Manifest.tile_transform(cell.flags)
        local id = b:add(anim_quad(self, atlas, tile.col, tile.row), x, y, r, sx, sy, ox, oy)
        if tile.anim and tile.anim.frames > 1 then
          mv.animated[#mv.animated + 1] = { batch = b, id = id, atlas = atlas, tile = tile, x = x, y = y, r = r,
                                            sx = sx, sy = sy, ox = ox, oy = oy, frame = 0 }
        end
      end
    end
    local list = {}
    for _, id in ipairs(order) do list[#list + 1] = batches[id] end
    mv.layers[#mv.layers + 1] = { name = layer.name, opacity = layer.opacity, batches = list }
  end
  return mv
end

-- Animated tiles: frame = floor(t * fps) mod frames, the frames sit in the next cells to the right.
function MapView:update(dt)
  self.t = self.t + dt
  for _, a in ipairs(self.animated) do
    local f = math.floor(self.t * a.tile.anim.fps) % a.tile.anim.frames
    if f ~= a.frame then
      a.frame = f
      a.batch:set(a.id, anim_quad(self.view, a.atlas, a.tile.col + f, a.tile.row), a.x, a.y, a.r, a.sx, a.sy,
                  a.ox, a.oy)
    end
  end
end

-- The map with its top-left at (x, y); objects (props) after the layers, sorted by y (feet).
function MapView:draw(x, y, scale)
  scale = scale or 1
  local r, g, b, a = love.graphics.getColor()
  for _, layer in ipairs(self.layers) do
    love.graphics.setColor(r, g, b, a * layer.opacity)
    for _, batch in ipairs(layer.batches) do love.graphics.draw(batch, x, y, 0, scale, scale) end
  end
  love.graphics.setColor(r, g, b, a)
  local objects = {}
  for i, o in ipairs(self.map.objects) do objects[i] = o end
  table.sort(objects, function(p, q) return p.y < q.y end)
  for _, o in ipairs(objects) do
    if o.sprite then self.view:draw_sprite(o.sprite, x + o.x * scale, y + o.y * scale, scale) end
  end
end

-- ---- Backgrounds -----------------------------------------------------------------------------
local Background = {}
Background.__index = Background

-- A background's layers as Images wrapped on their repeat axes, each with a scroll offset its velocity moves.
function View:background(asset)
  local bg = setmetatable({ view = self, asset = asset, layers = {} }, Background)
  for i, L in ipairs(asset.layers) do
    bg.layers[i] = { data = L, image = self:image(L.image, L.repeat_x and "repeat" or "clamp",
                                                  L.repeat_y and "repeat" or "clamp"), ox = 0, oy = 0 }
  end
  return bg
end

-- Scroll by velocity (px/s of the art); the offset wraps within the image on a repeating axis.
function Background:update(dt)
  for _, L in ipairs(self.layers) do
    local d, w, h = L.data, L.data.size[1], L.data.size[2]
    L.ox, L.oy = L.ox + d.velocity[1] * dt, L.oy + d.velocity[2] * dt
    if d.repeat_x and w > 0 then L.ox = L.ox % w end
    if d.repeat_y and h > 0 then L.oy = L.oy % h end
  end
end

-- The layers with their top-left at (x, y), the art at `scale` times each layer's own scale, over a view of
-- w x h screen pixels: a repeating axis is drawn through a Quad that size (the wrap shows it tiled), a fixed axis
-- as the image is. Offsets move in whole art pixels.
function Background:draw(x, y, scale, w, h)
  scale = scale or 1
  for _, L in ipairs(self.layers) do
    local d = L.data
    local s = scale * (d.scale or 1)
    local iw, ih = d.size[1], d.size[2]
    local ox, oy = math.floor(L.ox), math.floor(L.oy)
    local qw = d.repeat_x and w and (w / s) or iw
    local qh = d.repeat_y and h and (h / s) or ih
    local qx = d.repeat_x and -ox or 0
    local qy = d.repeat_y and -oy or 0
    L.quad = L.quad or love.graphics.newQuad(0, 0, iw, ih, iw, ih)
    L.quad:setViewport(qx, qy, qw, qh)      -- outside the image on a repeating axis: the wrap tiles it
    local dx = d.repeat_x and 0 or ox
    local dy = d.repeat_y and 0 or oy
    love.graphics.draw(L.image, L.quad, x + dx * s, y + dy * s, 0, s, s)
  end
end

-- ---- Particles, transitions, normal maps, images ---------------------------------------------------
-- "#rrggbb" or "#rrggbbaa" -> r, g, b, a in 0..1
local function hex_colour(s)
  local r, g, b, a = s:match("^#?(%x%x)(%x%x)(%x%x)(%x?%x?)$")
  if not r then return 1, 1, 1, 1 end
  return tonumber(r, 16) / 255, tonumber(g, 16) / 255, tonumber(b, 16) / 255, a ~= "" and tonumber(a, 16) / 255 or 1
end

-- The emitter's colour steps as setColors arguments: Dotwork's `colour_steps` ({rgba = {r, g, b, a}}, 0..255
-- with a 0..1 alpha) or a plain `colors` list of hex strings; empty when it has neither.
local function emitter_colours(e)
  local out = {}
  for _, step in ipairs(type(e.colour_steps) == "table" and e.colour_steps or {}) do
    local c = step.rgba or {}
    out[#out + 1] = (c[1] or 255) / 255; out[#out + 1] = (c[2] or 255) / 255; out[#out + 1] = (c[3] or 255) / 255
    out[#out + 1] = c[4] or 1
  end
  if #out == 0 then
    for _, hex in ipairs(type(e.colors) == "table" and e.colors or {}) do
      local r, g, b, a = hex_colour(tostring(hex))
      out[#out + 1] = r; out[#out + 1] = g; out[#out + 1] = b; out[#out + 1] = a
    end
  end
  return out
end

-- The particle texture (nearest, white mask) and a ParticleSystem from the emitter's amount, lifetime, one_shot and
-- colour steps (a one-shot is started with ps.system:emit(ps.amount); a loop emits amount / lifetime per second).
-- Everything else in the emitter JSON (emission shape, speed, gravity, damping, blend) is the game's to apply from
-- ps.emitter: LÖVE's ParticleSystem has matching setters for most of it.
function View:particles(asset)
  local e = asset.emitter or {}
  local amount = math.max(1, math.floor(tonumber(e.amount) or 8))
  local lifetime = tonumber(e.lifetime) or 1
  local ps = { asset = asset, emitter = e, image = self:image(asset.texture), amount = amount, lifetime = lifetime,
               one_shot = e.one_shot == true }
  local sys = love.graphics.newParticleSystem(ps.image, amount)
  sys:setParticleLifetime(lifetime)
  if not ps.one_shot then sys:setEmissionRate(amount / math.max(lifetime, 1e-6)) end
  local colours = emitter_colours(e)
  if #colours >= 4 then sys:setColors(unpack(colours)) end
  if e.blend == "add" then ps.blend = "add" end
  ps.system = sys
  return ps
end

-- A transition's greyscale image (the threshold shader recipe reads it: covered once progress > grey / 255).
function View:transition(asset)
  return { asset = asset, image = self:image(asset.image), kind = asset.transition, size = asset.size }
end

-- A normal map and the image it lights, both as Images (the sprite_light shader recipe takes the map as kit_aux).
function View:normal_map(asset)
  return { asset = asset, image = self:image(asset.image), target = self:image(asset.target),
           convention = asset.convention }
end

-- A loose image with its pivot (else its top-left) at (x, y).
function View:draw_image(asset, x, y, scale)
  scale = scale or 1
  local px, py = 0, 0
  if asset.pivot then px, py = asset.pivot[1], asset.pivot[2] end
  love.graphics.draw(self:image(asset.image), x, y, 0, scale, scale, px, py)
end

return View

-- {{FOOTER}}
