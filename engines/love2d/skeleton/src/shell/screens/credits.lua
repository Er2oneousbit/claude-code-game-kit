-- ---------------------------------------------------------------------------
-- credits.lua
-- Purpose : The credits: scrolls CREDITS.md from the game folder (headings and list markers stripped), or a
--           placeholder until the game has one. Up/down scroll by hand; accept or cancel goes back.
-- Usage   : app:push("credits")
-- Notes   : CREDITS.md is content, not UI copy, so its lines are exempt from the pseudo-locale "went through tr"
--           check (they are still checked for clipping). With reduce motion the text does not scroll on its own.
--           dev.py build packs CREDITS.md into the .love. Build the file from docs/ASSET_LOG.md before a release.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Style = require("src.shell.style")

local Credits = {}

-- ---- Tunables ----------------------------------------------------------------
local FILE = "CREDITS.md"
local SCROLL_PX_S = 18                   -- auto scroll speed
local STEP_PX = 24                       -- one up/down press
local AREA_X, AREA_Y, AREA_W, AREA_H = 60, 56, 520, 260

local function read_lines()
  local text = love.filesystem.read(FILE)
  if not text then return nil end
  local lines = {}
  for line in (text .. "\n"):gmatch("(.-)\r?\n") do
    line = line:gsub("^%s*#+%s*", ""):gsub("^%s*[-*]%s+", ""):gsub("%*%*", "")
    lines[#lines + 1] = line
  end
  return lines
end

function Credits:enter()
  self.lines = read_lines()
  self.offset = 0
end

function Credits:update(dt)
  if not self.app.settings.access.reduce_motion then self.offset = self.offset + SCROLL_PX_S * dt end
end

function Credits:action(name)
  if name == "ui_cancel" or name == "ui_accept" then self.app:pop() return true end
  if name == "ui_down" then self.offset = self.offset + STEP_PX return true end
  if name == "ui_up" then self.offset = math.max(0, self.offset - STEP_PX) return true end
  return false
end

function Credits:draw(ui)
  local app = self.app
  ui:label("credits.title", app:t("credits.title"), 0, 14, Style.BASE_W, 32,
           { align = "center", font = ui:font(Style.TITLE_PX * 0.75), color = Style.color.accent })
  local font = ui:font()
  local lh = font:getHeight() + 2
  if not self.lines then                   -- no CREDITS.md yet: a placeholder, no scrolling
    ui:label("credits.placeholder", app:t("credits.placeholder"), AREA_X, AREA_Y + 30, AREA_W, AREA_H - 90,
             { wrap = true, align = "center" })
    ui:label("credits.engine", app:t("credits.engine"), AREA_X, AREA_Y + AREA_H - 40, AREA_W, lh, { align = "center" })
    ui:label("credits.hint", app:t("credits.hint"), 0, Style.BASE_H - 30, Style.BASE_W, 22,
             { align = "center", font = ui:font(Style.SMALL_PX), color = Style.color.dim })
    return
  end
  local rows = {}
  for _, line in ipairs(self.lines) do
    local _, wrapped = font:getWrap(line, AREA_W)
    if #wrapped == 0 then wrapped = { "" } end
    for _, w in ipairs(wrapped) do rows[#rows + 1] = { text = w, raw = true } end
  end
  rows[#rows + 1] = { text = "" }
  rows[#rows + 1] = { text = app:t("credits.engine") }
  local total = #rows * lh
  if total > AREA_H then
    self.offset = self.offset % (total + AREA_H)          -- loop: start again from below
  else
    self.offset = 0
  end
  local start = (total > AREA_H) and (AREA_H - self.offset) or 0
  ui:clip(AREA_X, AREA_Y, AREA_W, AREA_H)
  for i, row in ipairs(rows) do
    local y = AREA_Y + start + (i - 1) * lh
    if row.text ~= "" and y + lh > AREA_Y and y < AREA_Y + AREA_H then
      if y >= AREA_Y and y + lh <= AREA_Y + AREA_H then
        ui:label("credits.line" .. i, row.text, AREA_X, y, AREA_W, lh, { align = "center", raw = row.raw })
      else                                   -- half scrolled out: drawn, not a layout problem
        love.graphics.setFont(font)
        love.graphics.setColor(Style.color.text)
        love.graphics.printf(row.text, AREA_X, math.floor(y + 1), AREA_W, "center")
      end
    end
  end
  ui:unclip()
  ui:label("credits.hint", app:t("credits.hint"), 0, Style.BASE_H - 30, Style.BASE_W, 22,
           { align = "center", font = ui:font(Style.SMALL_PX), color = Style.color.dim })
end

return Credits

-- {{FOOTER}}
