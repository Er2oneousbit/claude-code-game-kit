-- ---------------------------------------------------------------------------
-- pause.lua
-- Purpose : The pause menu over the frozen game: Resume, Settings, Quit to title. Opens on the pause action and
--           when the window loses focus; pause or cancel resumes.
-- Usage   : app:push("pause") (play and the juice demo do it)
-- Notes   : transparent = true: the game below keeps drawing (frozen: only the top screen updates).
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Style = require("src.shell.style")
local Widgets = require("src.shell.widgets")

local Pause = { transparent = true }

-- ---- Tunables ----------------------------------------------------------------
local PANEL_W, PANEL_H = 280, 180

function Pause:enter()
  local app = self.app
  self.list = Widgets.list({
    Widgets.button("resume", function() return app:t("pause.resume") end, function() app:pop() end),
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
  local x, y = (Style.BASE_W - PANEL_W) / 2, (Style.BASE_H - PANEL_H) / 2
  ui:panel(x, y, PANEL_W, PANEL_H)
  ui:label("pause.title", app:t("pause.title"), x, y + 10, PANEL_W, 28,
           { align = "center", font = ui:font(Style.TITLE_PX * 0.75), color = Style.color.accent })
  self.list:draw(ui, x + 40, y + 52, PANEL_W - 80, { prefix = "pause", center = true })
end

return Pause

-- {{FOOTER}}
