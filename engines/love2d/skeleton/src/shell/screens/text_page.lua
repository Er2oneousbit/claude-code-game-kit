-- ---------------------------------------------------------------------------
-- text_page.lua
-- Purpose : The page the "What now?" and "Dialogue history" screens share (#167): a title, wrapped lines that
--           scroll with up/down, and accept or cancel to go back.
-- Usage   : local TextPage = require("src.shell.screens.text_page")
--           function Help:draw(ui) TextPage.draw(self, ui, title, lines) end   -- lines: { "text", ... }
--           function Help:action(name) return TextPage.action(self, name) end
-- Notes   : Lines wrap to the page width and take the player's line spacing (ui:line_h). The page scrolls by
--           whole steps and never past its end.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Style = require("src.shell.style")

local TextPage = {}

-- ---- Tunables ----------------------------------------------------------------
local MARGIN = 32
local TITLE_Y = 14
local BOTTOM = 40                        -- room for the hint at the bottom
local STEP_PX = 24                       -- up/down scroll this far

function TextPage.action(screen, name)
  if name == "ui_cancel" or name == "ui_accept" then screen.app:pop() return true end
  if name == "ui_down" then screen.offset = (screen.offset or 0) + STEP_PX return true end
  if name == "ui_up" then screen.offset = math.max(0, (screen.offset or 0) - STEP_PX) return true end
  return false
end

function TextPage.draw(screen, ui, title, lines, id)
  local app = screen.app
  love.graphics.setColor(Style.color.bg)
  love.graphics.rectangle("fill", 0, 0, Style.BASE_W, Style.BASE_H)
  local title_font = ui:font(Style.TITLE_PX * 0.75)
  ui:label(id .. ".title", title, 0, TITLE_Y, Style.BASE_W, title_font:getHeight(),
           { align = "center", font = title_font, color = Style.color.accent })
  local TOP = TITLE_Y + title_font:getHeight() + 8      -- the text starts below the title, at any text size
  local font = ui:font()
  local w = Style.BASE_W - MARGIN * 2
  local area_h = Style.BASE_H - TOP - BOTTOM
  local rows = {}
  for i, text in ipairs(lines) do
    local _, wrapped = font:getWrap(text, w)
    rows[#rows + 1] = { i = i, text = text, h = math.max(1, #wrapped) * ui:line_h(font) + 4 }
  end
  local total = 0
  for _, r in ipairs(rows) do total = total + r.h end
  screen.offset = math.max(0, math.min(screen.offset or 0, total - area_h))
  ui:clip(0, TOP, Style.BASE_W, area_h)
  local y = TOP - screen.offset
  for _, r in ipairs(rows) do
    if y + r.h > TOP and y < TOP + area_h then
      ui:label(id .. ".line" .. r.i, r.text, MARGIN, y, w, r.h - 4, { wrap = true, font = font, raw = true })
    end
    y = y + r.h
  end
  ui:unclip()
  local small = ui:font(Style.SMALL_PX)
  ui:label(id .. ".hint", app:t("page.hint"), 0, Style.BASE_H - 30, Style.BASE_W, small:getHeight(),
           { align = "center", font = small, color = Style.color.dim })
end

return TextPage

-- {{FOOTER}}
