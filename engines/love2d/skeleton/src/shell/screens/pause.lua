-- ---------------------------------------------------------------------------
-- pause.lua
-- Purpose : The pause menu over the frozen game: Resume, What now?, Dialogue history, Settings, Quit to title. Opens on the pause action and
--           when the window loses focus; pause or cancel resumes.
-- Usage   : app:push("pause") (play and the juice demo do it)
-- Notes   : transparent = true: the game below keeps drawing (frozen: only the top screen updates).
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Style = require("src.shell.style")
local Widgets = require("src.shell.widgets")

local Pause = { transparent = true }

-- ---- Tunables ----------------------------------------------------------------
local PANEL_W, PANEL_H = 280, 180          -- the smallest panel; it grows with its rows and labels
local LIST_PAD = 40                        -- the list's inset from the panel's sides
local ROW_INSET = 24                       -- room the list row takes around its text (the focus marker)

function Pause:enter()
  local app = self.app
  self.list = Widgets.list({
    Widgets.button("resume", function() return app:t("pause.resume") end, function() app:pop() end),
    Widgets.button("help", function() return app:t("pause.help") end, function() app:push("help") end),       -- #167
    Widgets.button("history", function() return app:t("pause.history") end, function() app:push("history") end),
    Widgets.button("settings", function() return app:t("menu.settings") end, function() app:push("settings") end),
    Widgets.button("quit", function() return app:t("pause.quit") end, function() app:reset("title") end),
  }, { on_move = function() app:play_sound("move", "ui") end })
end

function Pause:focus_id() return self.list:focused_id() end

function Pause:action(name)
  if name == "pause" or name == "ui_cancel" then self.app:pop() return true end
  if name == "ui_accept" then self.app:play_sound("accept", "ui") end
  return self.list:action(name)
end

function Pause:draw(ui)
  local app = self.app
  love.graphics.setColor(Style.color.overlay)
  love.graphics.rectangle("fill", 0, 0, Style.BASE_W, Style.BASE_H)
  -- the panel's height follows its rows and the text size (five buttons since #167)
  local title_font = ui:font(Style.TITLE_PX * 0.75)
  local list_y = 10 + title_font:getHeight() + 10
  local h = math.max(PANEL_H, list_y + #self.list.rows * (ui:row_h() + 2) + 12)
  -- and its width follows the longest button, so "Dialogue history" fits at 200 % text (the access sweep, #91)
  local widest = 0
  for _, row in ipairs(self.list.rows) do widest = math.max(widest, ui:font():getWidth(row.text())) end
  local w = math.min(Style.BASE_W - 16, math.max(PANEL_W, widest + LIST_PAD * 2 + ROW_INSET))
  local x, y = (Style.BASE_W - w) / 2, math.max(4, (Style.BASE_H - h) / 2)
  ui:panel(x, y, w, h)
  ui:label("pause.title", app:t("pause.title"), x, y + 10, w, title_font:getHeight(),
           { align = "center", font = title_font, color = Style.color.accent })
  self.list:draw(ui, x + LIST_PAD, y + list_y, w - LIST_PAD * 2, { prefix = "pause", center = true })
end

return Pause

-- {{FOOTER}}
