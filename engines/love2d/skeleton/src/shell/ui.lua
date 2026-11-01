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

local UI = {}
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
                        check_result = nil, scale = 1 }, UI)
end

-- The UI font at size px * the player's text scale (whole pixels); unscaled = true skips the text scale
-- (subtitles have their own size setting).
function UI:font(px, unscaled)
  local k = unscaled and 1 or self.scale
  px = math.max(6, math.floor((px or Style.FONT_PX) * k + 0.5))
  if not self.fonts[px] then
    self.fonts[px] = love.graphics.newFont(px)
    self.fonts[px]:setFilter("nearest", "nearest")
  end
  return self.fonts[px]
end

function UI:set_scale(scale)
  self.scale = scale
end

function UI:row_h(font) return (font or self:font()):getHeight() + Style.ROW_PAD * 2 end

function UI:begin_frame()
  self.labels = {}
end

-- Draws text inside the box (x, y, w, h), vertically centred; opts: align, font, color, raw, wrap, id_screen.
function UI:label(id, text, x, y, w, h, opts)
  opts = opts or {}
  local font = opts.font or self:font()
  text = tostring(text or "")
  love.graphics.setFont(font)
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
  self.labels[#self.labels + 1] = { id = id, text = text, x = x, y = y, w = w, h = h, font = font,
                                    raw = opts.raw, wrap = opts.wrap }
end

function UI:panel(x, y, w, h, color)
  love.graphics.setColor(color or Style.color.panel)
  love.graphics.rectangle("fill", x, y, w, h, 4, 4)
  love.graphics.setColor(Style.color.panel_edge)
  love.graphics.setLineWidth(1)
  love.graphics.rectangle("line", x + 0.5, y + 0.5, w - 1, h - 1, 4, 4)
end

-- The focused item: a lighter fill, a white outline and a ">" marker (never colour alone).
function UI:focus_box(x, y, w, h)
  love.graphics.setColor(Style.color.row_focus)
  love.graphics.rectangle("fill", x, y, w, h, 3, 3)
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
             color = (opts and opts.warn) and Style.color.warn or Style.color.text })
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

-- Asks for a check of the labels of the next frame; the result lands in self.check_result.
function UI:request_check(screen)
  self.pending_check = screen
  self.check_result = nil
end

function UI:end_frame()
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
