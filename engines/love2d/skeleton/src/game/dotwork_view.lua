-- ---------------------------------------------------------------------------
-- dotwork_view.lua
-- Purpose : Draws what a Dotwork manifest describes (src/core/dotwork_manifest.lua): images with nearest filtering
--           and no mipmaps, one Quad per rect, animated sprites timed by each frame's duration, a SpriteBatch per
--           atlas and layer for maps (animated tiles included), BMFont fonts, 9-slice UI parts, icons, portraits.
-- Usage   : local View = require("src.game.dotwork_view")
--           local view = View.new()                          -- in love.draw or after the window exists
--           local hero = view:animated(model.animated_sprite.hero); hero:play_direction("walk", "e")
--           hero:update(dt); hero:draw(x, y, 2)              -- (x, y) is where the pivot (the feet) lands
--           view:draw_sprite(model.sprite.crate, x, y, 2)    -- contact shadow first, when it has one
--           local map = view:map(model.map.yard); map:update(dt); map:draw(x, y, 2)
--           view:print(model.font.tiny, "AB", x, y, 2)       -- the .fnt through love.graphics.newFont
--           view:draw_part(model.ui_kit.windows.parts.ui_window_plain, x, y, 2, w, h)   -- 9-slice when w, h given
-- Notes   : Needs a window: every love.graphics.new* call errors without one (docs/ENGINE.md gotcha 2), so build
--           the view lazily in draw. Pivots go straight into love.graphics.draw's origin arguments (y down, the
--           manifest's own axes: no conversion). Scale by whole numbers. Fonts: love.graphics.newFont(fntPath)
--           reads AngelCode BMFont text files and finds the pages beside the .fnt (checked on LÖVE 11.5); if that
--           fails, the font is drawn from the manifest's `chars` with one Quad per glyph. Isometric map cells use
--           Godot's diamond-down layout (x right-down, y left-down) (verify against a Dotwork iso map).
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
--
-- Pseudocode
--   image(path): cached newImage(path, no mipmaps), nearest filter, clamp
--   quad(image, rect): cached newQuad over the image's size
--   animated: a Manifest.player per instance; draw = frame's image + quad at (x, y) with origin = clip pivot
--   map: for each layer, cells grouped by atlas -> one SpriteBatch; a cell = tile quad at the cell centre with
--        the tile's origin (flags rotate and flip about it); animated tiles re-set their quad when the frame changes;
--        objects (props) drawn after the layers, sorted by y
--   font: newFont(.fnt) in a pcall -> else glyph quads from chars (Manifest.layout_text)
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
function View:image(path, wrap)
  local img = self.images[path]
  if not img then
    img = love.graphics.newImage(path, { mipmaps = false })
    img:setFilter(FILTER, FILTER)
    img:setWrap(wrap or "clamp", wrap or "clamp")
    self.images[path] = img
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

-- The centre of cell (cx, cy) in map pixels (square grid, or Godot's diamond-down iso layout).
local function cell_centre(map, cx, cy)
  local tw, th = map.tile_size[1], map.tile_size[2]
  if map.tileset and map.tileset.shape == "isometric" then
    return (cx - cy) * tw / 2 + map.size[2] * tw / 2, (cx + cy) * th / 2 + th / 2
  end
  return cx * tw + tw / 2, cy * th + th / 2
end
View.cell_centre = cell_centre

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

return View

-- {{FOOTER}}
