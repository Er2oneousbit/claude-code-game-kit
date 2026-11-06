-- ---------------------------------------------------------------------------
-- ui.lua
-- Purpose : Drawing helpers for the shell's screens: fonts at the player's text scale, labels that remember
--           where they were drawn (for the pseudo-locale layout check), the focus outline, panels, bars, button
--           glyphs (assets/ui/glyphs/<name>.png, or a text key-cap when the file is missing), and the check.
-- Usage   : local UI = require("src.shell.ui"); local ui = UI.new(app)
--           ui:label("menu.play", app:t("menu.play"), x, y, w, h, { align = "center", font = ui:font() })
--           ui:focus_box(x, y, w, h)      ui:glyph_cell(gname, label, x, y, h)
--           ui:begin_frame() ... draw ... ui:end_frame() -> runs a pending check: ui.check_result
-- Notes   : Coordinates are in the 640x360 base; the app scales the whole frame by a whole number. Fonts and images
--           are created on first use only, never in a headless run (no window: love.graphics cannot create them).
--           The check flags a label whose text is wider than its box, a box past the screen edge or shorter than
--           a line, and (pseudo-locale) text that did not go through tr(), i.e. does not start with "[".
--           opts.raw = true exempts text that is not UI copy (the CREDITS.md file).
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Style = require("src.shell.style")

local Json = require("src.core.json")

local UI = {}

local OUTLINE_STEPS = { { -1, 0 }, { 1, 0 }, { 0, -1 }, { 0, 1 }, { -1, -1 }, { 1, 1 }, { -1, 1 }, { 1, -1 } }
UI.__index = UI

-- ---- Tunables ----------------------------------------------------------------
local GLYPH_DIR = "assets/ui/glyphs/"
local KEYCAP_PAD = 4                     -- px around a text key-cap
local SLACK_PX = 0.5                     -- measuring slack before a label counts as overflowing

function UI.utf8_len(s)
  local _, n = s:gsub("[^\128-\191]", "")
  return n
end

-- the first n characters (code points) of s
function UI.utf8_prefix(s, n)
  if n <= 0 then return "" end
  local count, i = 0, 1
  while i <= #s do
    local b = s:byte(i)
    if b < 0x80 or b >= 0xC0 then
      count = count + 1
      if count > n then return s:sub(1, i - 1) end
    end
    i = i + 1
  end
  return s
end

function UI.new(app)
  return setmetatable({ app = app, fonts = {}, glyphs = {}, labels = {}, pending_check = nil,
                        check_result = nil, scale = 1, font_px = {}, fills = {}, order = 0, recording = false,
                        in_ui = false, pending_access = nil, access_result = nil }, UI)
end

-- The UI font at size px * the player's text scale (whole pixels); unscaled = true skips the text scale
-- (subtitles have their own size setting).
function UI:font(px, unscaled)
  local k = unscaled and 1 or self.scale
  px = math.max(6, math.floor((px or Style.FONT_PX) * k + 0.5))
  if not self.fonts[px] then
    self.fonts[px] = love.graphics.newFont(px)
    self.fonts[px]:setFilter("nearest", "nearest")
    self.font_px[self.fonts[px]] = px
  end
  return self.fonts[px]
end

function UI:set_scale(scale)
  self.scale = scale
end

function UI:row_h(font) return (font or self:font()):getHeight() + Style.ROW_PAD * 2 end

function UI:begin_frame()
  self.labels = {}
  self.fills, self.order = {}, 0
  self.recording = self.pending_access ~= nil
end

-- a box in window pixels, through the current transform (the frame's scale and offset, a list's scroll)
local function window_box(x, y, w, h)
  local x1, y1 = love.graphics.transformPoint(x, y)
  local x2, y2 = love.graphics.transformPoint(x + w, y + h)
  return { x1, y1, x2 - x1, y2 - y1 }
end

-- the access drive's hook on love.graphics.rectangle: every fill of a recorded frame, in drawing order
function UI:note_fill(x, y, w, h)
  if not self.recording then return end
  self.order = self.order + 1
  local r, g, b, a = love.graphics.getColor()
  self.fills[#self.fills + 1] = { box = window_box(x, y, w, h), color = { r, g, b, a }, order = self.order,
                                  ui = self.in_ui }
end

-- Draws text inside the box (x, y, w, h), vertically centred; opts: align, font, color, raw, wrap, id_screen,
-- outline (a colour: the text drawn under itself one pixel each way, so it reads over any game, #91).
function UI:label(id, text, x, y, w, h, opts)
  opts = opts or {}
  local font = opts.font or self:font()
  text = tostring(text or "")
  love.graphics.setFont(font)
  if opts.outline then
    local plain = {}
    for k, v in pairs(opts) do plain[k] = v end
    plain.outline, plain.color, plain.no_record = nil, opts.outline, true
    for _, d in ipairs(OUTLINE_STEPS) do self:label(id, text, x + d[1], y + d[2], w, h, plain) end
  end
  love.graphics.setColor(opts.color or Style.color.text)
  if opts.wrap then
    -- opts.shown: draw only this much (a typewriter), but lay out and check the whole text
    if opts.shown then
      local _, lines = font:getWrap(text, w)
      local left = opts.shown
      for i, line in ipairs(lines) do
        if left <= 0 then break end
        local part = UI.utf8_prefix(line, left)
        love.graphics.print(part, math.floor(x), math.floor(y + (i - 1) * font:getHeight()))
        left = left - UI.utf8_len(line)
        -- getWrap drops the space a line broke at: count it, so the reveal stays in step with the text
        if i < #lines then left = left - 1 end
      end
    else
      love.graphics.printf(text, math.floor(x), math.floor(y), w, opts.align or "left")
    end
  else
    local tw = font:getWidth(text)
    local tx = x
    if opts.align == "center" then tx = x + (w - tw) / 2 elseif opts.align == "right" then tx = x + w - tw end
    local ty = y + (h - font:getHeight()) / 2
    love.graphics.print(text, math.floor(tx), math.floor(ty))
  end
  if opts.no_record then return end                     -- an outline pass: the label itself is recorded once
  local colour = opts.color or Style.color.text
  self.order = self.order + 1
  local ink = nil
  if self.recording then                                 -- where the glyphs land (the access sweep's overlap check)
    if opts.wrap then
      local widest, lines = font:getWrap(text, w)
      ink = window_box(x, y, math.min(widest, w), #lines * font:getHeight())
    else
      local tw = font:getWidth(text)
      local tx = opts.align == "center" and x + (w - tw) / 2 or opts.align == "right" and x + w - tw or x
      ink = window_box(tx, y + (h - font:getHeight()) / 2, tw, font:getHeight())
    end
  end
  self.labels[#self.labels + 1] = { id = id, text = text, x = x, y = y, w = w, h = h, font = font,
                                    raw = opts.raw, wrap = opts.wrap, color = { colour[1], colour[2], colour[3] },
                                    box = self.recording and window_box(x, y, w, h) or nil, order = self.order,
                                    ink = ink, outline = opts.outline }
end

function UI:panel(x, y, w, h, color)
  love.graphics.setColor(color or Style.color.panel)
  self.in_ui = true                                   -- the access report tells UI panels from the game world
  love.graphics.rectangle("fill", x, y, w, h, 4, 4)
  self.in_ui = false
  love.graphics.setColor(Style.color.panel_edge)
  love.graphics.setLineWidth(1)
  love.graphics.rectangle("line", x + 0.5, y + 0.5, w - 1, h - 1, 4, 4)
end

-- The focused item: a lighter fill, a white outline and a ">" marker (never colour alone).
function UI:focus_box(x, y, w, h)
  love.graphics.setColor(Style.color.row_focus)
  self.in_ui = true
  love.graphics.rectangle("fill", x, y, w, h, 3, 3)
  self.in_ui = false
  love.graphics.setColor(Style.color.focus)
  love.graphics.setLineWidth(Style.FOCUS_LINE)
  love.graphics.rectangle("line", x + 1, y + 1, w - 2, h - 2, 3, 3)
  local font = self:font()
  love.graphics.setFont(font)
  love.graphics.print(">", math.floor(x - font:getWidth(">") - 4), math.floor(y + (h - font:getHeight()) / 2))
end

-- Limits drawing to a box in base coordinates (scissors work in window pixels, so the frame's scale applies).
function UI:clip(x, y, w, h)
  local v = self.app.view or { s = 1, ox = 0, oy = 0 }
  love.graphics.setScissor(v.ox + x * v.s, v.oy + y * v.s, w * v.s, h * v.s)
end

function UI:unclip()
  local v = self.app.view or { s = 1, ox = 0, oy = 0 }
  love.graphics.setScissor(v.ox, v.oy, Style.BASE_W * v.s, Style.BASE_H * v.s)
end

function UI:bar(x, y, w, h, fraction, color)
  love.graphics.setColor(Style.color.row)
  love.graphics.rectangle("fill", x, y, w, h, 2, 2)
  love.graphics.setColor(color or Style.color.bar)
  love.graphics.rectangle("fill", x, y, w * math.max(0, math.min(1, fraction)), h, 2, 2)
  love.graphics.setColor(Style.color.panel_edge)
  love.graphics.setLineWidth(1)
  love.graphics.rectangle("line", x + 0.5, y + 0.5, w - 1, h - 1, 2, 2)
end

-- The image for a glyph name, or false when assets/ui/glyphs/<name>.png is missing.
function UI:glyph(name)
  if self.glyphs[name] == nil then
    local path = GLYPH_DIR .. name .. ".png"
    if love.filesystem.getInfo(path, "file") then
      local ok, img = pcall(love.graphics.newImage, path)
      self.glyphs[name] = ok and img or false
      if ok then img:setFilter("nearest", "nearest") end
    else
      self.glyphs[name] = false
    end
  end
  return self.glyphs[name]
end

-- A button prompt at (x, y) in a row of height h: the glyph image at 1x (whole-number scaled with the frame), or
-- a key-cap with the text label. Returns the width used.
function UI:glyph_cell(id, gname, label, x, y, h, opts)
  local img = self:glyph(gname)
  if img then
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.draw(img, math.floor(x), math.floor(y + (h - img:getHeight()) / 2))
    return img:getWidth()
  end
  local font = (opts and opts.font) or self:font(Style.SMALL_PX)
  local w = font:getWidth(label) + KEYCAP_PAD * 2
  local ch = font:getHeight() + KEYCAP_PAD
  local cy = y + (h - ch) / 2
  love.graphics.setColor((opts and opts.warn) and Style.color.warn or Style.color.panel_edge)
  love.graphics.setLineWidth(1)
  love.graphics.rectangle("line", math.floor(x) + 0.5, math.floor(cy) + 0.5, w, ch, 3, 3)
  self:label(id, label, x + KEYCAP_PAD, cy, w - KEYCAP_PAD * 2 + 1, ch, { font = font,
             color = (opts and opts.warn) and Style.color.warn or Style.color.text, outline = opts and opts.outline })
  return w
end

-- ---- The layout check (pseudo-locale) -------------------------------------------------------------------
local function problems_of(self, label)
  local out = {}
  local pseudo = self.app.i18n:is_pseudo()
  if label.text == "" then return out end
  if pseudo and not label.raw and label.text:sub(1, 1) ~= "[" then out[#out + 1] = "not passed through tr" end
  local font, lh = label.font, label.font:getHeight()
  if label.wrap then
    local _, lines = font:getWrap(label.text, label.w)
    if #lines * lh > label.h + SLACK_PX then
      out[#out + 1] = string.format("wraps to %d lines, the box holds %d", #lines, math.floor(label.h / lh))
    end
  else
    local tw = font:getWidth(label.text)
    if tw > label.w + SLACK_PX then
      out[#out + 1] = string.format("text %d px is wider than its box %d px (truncated)", tw, math.floor(label.w))
    end
    if lh > label.h + SLACK_PX then out[#out + 1] = "box is shorter than one line (clipped)" end
  end
  if label.x < -SLACK_PX or label.y < -SLACK_PX or label.x + label.w > Style.BASE_W + SLACK_PX
     or label.y + label.h > Style.BASE_H + SLACK_PX then
    out[#out + 1] = "box runs past the screen edge (clipped)"
  end
  return out
end

-- ---- The access report (tools/access/sweep.py, #91) -----------------------------------------------------------
local function hex(c) return string.format("#%02x%02x%02x", math.floor(c[1] * 255 + 0.5),
                                           math.floor(c[2] * 255 + 0.5), math.floor(c[3] * 255 + 0.5)) end

-- The colour under a label: every earlier fill covering its centre, blended in drawing order over the cleared black.
-- world = a screen drawn over the game: only UI panels count, and text with no opaque panel is "over the game".
local function background(self, label, world)
  local cx, cy = label.box[1] + label.box[3] / 2, label.box[2] + label.box[4] / 2
  local c, layers, opaque = { 0, 0, 0 }, {}, false
  for _, f in ipairs(self.fills) do
    local b = f.box
    if f.order < label.order and cx >= b[1] and cx <= b[1] + b[3] and cy >= b[2] and cy <= b[2] + b[4] then
      local a = f.color[4]
      c = { c[1] + (f.color[1] - c[1]) * a, c[2] + (f.color[2] - c[2]) * a, c[3] + (f.color[3] - c[3]) * a }
      if f.ui then
        table.insert(layers, 1, { hex(f.color), math.floor(a * 1000 + 0.5) / 1000 })
        if a >= 0.999 then layers, opaque = {}, true end
      end
    end
  end
  if world and not opaque then
    local over = {}
    for i, l in ipairs(layers) do over[i] = Json.array(l) end
    return nil, Json.array(over)
  end
  return hex(c), nil
end

-- Asks for the access report of the next drawn frame; world = a screen over the game. Result: self.access_result.
function UI:request_access(screen, world)
  self.pending_access = { screen = screen, world = world }
  self.access_result = nil
end

-- true when an opaque UI panel drawn after the label covers its middle (a dialog over a screen): not visible
local COVER_ALPHA = 0.9                           -- a panel this opaque hides what is under it
local function covered(self, label)
  local cx, cy = label.box[1] + label.box[3] / 2, label.box[2] + label.box[4] / 2
  for _, f in ipairs(self.fills) do
    local b = f.box
    if f.ui and f.order > label.order and f.color[4] >= COVER_ALPHA and cx >= b[1] and cx <= b[1] + b[3]
       and cy >= b[2] and cy <= b[2] + b[4] then
      return true
    end
  end
  return false
end

-- the panel the label sits on: the last opaque UI fill drawn before it under its middle ({} on the bare screen)
local function card(self, label)
  local cx, cy = label.box[1] + label.box[3] / 2, label.box[2] + label.box[4] / 2
  local best = nil
  for _, f in ipairs(self.fills) do
    local b = f.box
    if f.ui and f.order < label.order and f.color[4] >= COVER_ALPHA and cx >= b[1] and cx <= b[1] + b[3]
       and cy >= b[2] and cy <= b[2] + b[4] then
      best = f
    end
  end
  if not best then return Json.object({}) end
  return { order = best.order, rect = Json.array({ best.box[1], best.box[2], best.box[3], best.box[4] }) }
end

local function access_report(self)
  local req = self.pending_access
  local texts = {}
  for _, label in ipairs(self.labels) do
    if label.text ~= "" and label.box then
      local bg, over = background(self, label, req.world)
      local problems = {}
      for _, why in ipairs(problems_of(self, label)) do
        -- a single line taller than its box is drawn centred on it: harmless unless it hits other text, which
        -- the sweep checks from the ink boxes
        if why ~= "box is shorter than one line (clipped)" then problems[#problems + 1] = why end
      end
      texts[#texts + 1] = { node = label.id, text = label.text:sub(1, 60), state = "",
                            outline = label.outline and hex(label.outline) or nil,
                            ink = Json.array({ label.ink[1], label.ink[2], label.ink[3], label.ink[4] }),
                            px = self.font_px[label.font] or Style.FONT_PX, fg = hex(label.color), bg = bg,
                            over_game = over, fits = #problems == 0, covered = covered(self, label),
                            card = card(self, label),
                            why = #problems > 0 and problems[1] or nil }
    end
  end
  self.access_result = { screen = req.screen, design = Json.array({ Style.BASE_W, Style.BASE_H }),
                         scaling = "integer", texts = Json.array(texts) }
  self.pending_access, self.recording = nil, false
end

-- Asks for a check of the labels of the next frame; the result lands in self.check_result.
function UI:request_check(screen)
  self.pending_check = screen
  self.check_result = nil
end

function UI:end_frame()
  if self.pending_access and self.recording then access_report(self) end
  if not self.pending_check then return end
  local result = { screen = self.pending_check, labels = #self.labels, problems = {} }
  for _, label in ipairs(self.labels) do
    for _, why in ipairs(problems_of(self, label)) do
      result.problems[#result.problems + 1] = { id = label.id, text = label.text, why = why }
    end
  end
  self.check_result = result
  self.pending_check = nil
end

return UI

-- {{FOOTER}}
