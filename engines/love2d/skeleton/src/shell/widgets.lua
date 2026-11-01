-- ---------------------------------------------------------------------------
-- widgets.lua
-- Purpose : The one menu widget the shell needs: a vertical list of rows (button, toggle, choice, slider,
--           binding) with keyboard / gamepad focus, left/right to change a value, accept to activate, and
--           scrolling when the rows do not fit.
-- Usage   : local Widgets = require("src.shell.widgets")
--           local list = Widgets.list({
--             { id = "play", kind = "button", text = function() return app:t("menu.play") end, accept = start },
--             Widgets.slider("master", label_fn, get, set, 0, 1, 0.1, format_fn),
--             Widgets.toggle("vsync", label_fn, get, set, on_text_fn),
--             Widgets.choice("mode", label_fn, options, get, set, option_text_fn) })
--           screen:action(a) -> list:action(a) ; draw: list:draw(ui, x, y, w, { label_w = 220, max_h = 240 })
-- Notes   : Rows are tables; a row may define left(), right(), accept(), draw_value(ui, x, y, w, h, focused) and
--           enabled() (false = skipped by focus). Every visible text goes through the label function you pass,
--           which should call app:t(), so the pseudo-locale check sees it.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Style = require("src.shell.style")

local Widgets = {}

-- ---- Tunables ----------------------------------------------------------------
local LABEL_PAD = 8                      -- px between the row edge and its text
local ARROW_W = 12                       -- px for the < > arrows of a choice
local SLIDER_TEXT_W = 72                 -- px for a slider's value text (room for the pseudo-locale's "[100%~]")
local SLIDER_H = 6

local List = {}
List.__index = List

function Widgets.list(rows, opts)
  local self = setmetatable({ rows = rows, index = 1, top = 1, opts = opts or {} }, List)
  self:fix_focus(1)
  return self
end

local function enabled(row) return not row.enabled or row.enabled() end

function List:fix_focus(dir)
  local n = #self.rows
  if n == 0 then return end
  for _ = 1, n do
    if enabled(self.rows[self.index]) then return end
    self.index = (self.index - 1 + dir) % n + 1
  end
end

function List:focused() return self.rows[self.index] end
function List:focused_id() local r = self:focused(); return r and r.id end

function List:focus(id)
  for i, row in ipairs(self.rows) do
    if row.id == id then self.index = i; return true end
  end
  return false
end

function List:move(delta)
  local n = #self.rows
  if n == 0 then return end
  local start = self.index
  repeat
    self.index = (self.index - 1 + delta) % n + 1
  until enabled(self.rows[self.index]) or self.index == start
  if self.opts.on_move then self.opts.on_move() end
end

-- Returns true when the action was used.
function List:action(name)
  local row = self:focused()
  if name == "ui_up" then self:move(-1) return true end
  if name == "ui_down" then self:move(1) return true end
  if not row then return false end
  if name == "ui_left" and row.left then row.left() return true end
  if name == "ui_right" and row.right then row.right() return true end
  if name == "ui_accept" and row.accept then row.accept() return true end
  return false
end

-- opts: label_w (two columns when set), max_h (scroll), prefix (label ids), center (single-column, centred)
function List:draw(ui, x, y, w, opts)
  opts = opts or {}
  local font = ui:font()
  local rh = ui:row_h(font)
  local gap = 2
  local visible = #self.rows
  if opts.max_h then visible = math.max(1, math.floor((opts.max_h + gap) / (rh + gap))) end
  if self.index < self.top then self.top = self.index end
  if self.index >= self.top + visible then self.top = self.index - visible + 1 end
  self.top = math.max(1, math.min(self.top, math.max(1, #self.rows - visible + 1)))
  local prefix = opts.prefix or "list"
  local ry = y
  for i = self.top, math.min(#self.rows, self.top + visible - 1) do
    local row = self.rows[i]
    local focused = (i == self.index)
    if focused then
      ui:focus_box(x, ry, w, rh)
    else
      love.graphics.setColor(Style.color.row)
      love.graphics.rectangle("fill", x, ry, w, rh, 3, 3)
    end
    local color = enabled(row) and Style.color.text or Style.color.dim
    local text = row.text and row.text() or ""
    if opts.label_w and row.kind ~= "button" then
      ui:label(prefix .. "." .. row.id, text, x + LABEL_PAD, ry, opts.label_w - LABEL_PAD, rh,
               { font = font, color = color })
      if row.draw_value then
        row.draw_value(ui, x + opts.label_w, ry, w - opts.label_w - LABEL_PAD, rh, focused, prefix .. "." .. row.id)
      end
    else
      ui:label(prefix .. "." .. row.id, text, x + LABEL_PAD, ry, w - LABEL_PAD * 2, rh,
               { font = font, color = color, align = opts.center and "center" or "left" })
    end
    ry = ry + rh + gap
  end
  -- scroll hints: more rows above / below
  love.graphics.setColor(Style.color.dim)
  if self.top > 1 then love.graphics.polygon("fill", x + w - 14, y - 3, x + w - 8, y - 9, x + w - 2, y - 3) end
  if self.top + visible - 1 < #self.rows then
    love.graphics.polygon("fill", x + w - 14, ry + 1, x + w - 8, ry + 7, x + w - 2, ry + 1)
  end
  return ry
end

-- ---- Row builders ------------------------------------------------------------------------------------------
local function value_text(ui, id, text, x, y, w, h)
  ui:label(id .. ".value", text, x + ARROW_W, y, w - ARROW_W * 2, h, { align = "center" })
end

local function arrows(ui, x, y, w, h, focused)
  if not focused then return end
  local font = ui:font()
  love.graphics.setFont(font)
  love.graphics.setColor(Style.color.accent)
  local ty = math.floor(y + (h - font:getHeight()) / 2)
  love.graphics.print("<", math.floor(x), ty)
  love.graphics.print(">", math.floor(x + w - font:getWidth(">")), ty)
end

-- format(value) -> the text to show (through app:t, e.g. "50%")
function Widgets.slider(id, text, get, set, lo, hi, step, format)
  local function nudge(d)
    local v = get() + d * step
    v = math.floor(v / step + 0.5) * step
    v = tonumber(string.format("%.6f", v))              -- no float dust in settings.json: 0.15, not 0.15000000000000002
    set(math.min(hi, math.max(lo, v)))
  end
  return {
    id = id, kind = "slider", text = text,
    left = function() nudge(-1) end, right = function() nudge(1) end,
    draw_value = function(ui, x, y, w, h, focused, lid)
      local tw = SLIDER_TEXT_W * ui.scale                -- the value text grows with the text size
      local bw = w - tw
      ui:bar(x, y + (h - SLIDER_H) / 2, bw - 8, SLIDER_H, (get() - lo) / (hi - lo))
      ui:label(lid .. ".value", format(get()), x + bw, y, tw, h, { align = "right" })
    end,
  }
end

-- on_off(value) -> the text to show
function Widgets.toggle(id, text, get, set, on_off)
  local function flip() set(not get()) end
  return {
    id = id, kind = "toggle", text = text, accept = flip, left = flip, right = flip,
    draw_value = function(ui, x, y, w, h, focused, lid)
      arrows(ui, x, y, w, h, focused)
      value_text(ui, lid, on_off(get()), x, y, w, h)
    end,
  }
end

-- options: a list of values; show(value) -> the text to show
function Widgets.choice(id, text, options, get, set, show)
  local function step(d)
    local cur, idx = get(), 1
    for i, o in ipairs(options()) do if o == cur then idx = i end end
    local list = options()
    set(list[(idx - 1 + d) % #list + 1])
  end
  return {
    id = id, kind = "choice", text = text,
    left = function() step(-1) end, right = function() step(1) end, accept = function() step(1) end,
    draw_value = function(ui, x, y, w, h, focused, lid)
      arrows(ui, x, y, w, h, focused)
      value_text(ui, lid, show(get()), x, y, w, h)
    end,
  }
end

function Widgets.button(id, text, accept)
  return { id = id, kind = "button", text = text, accept = accept }
end

return Widgets

-- {{FOOTER}}
