-- ---------------------------------------------------------------------------
-- main_menu.lua
-- Purpose : The main menu: Play, Settings, Credits, Quit, plus "Juice demo" in a debug build (a run from the
--           source folder). Cancel goes back to the title.
-- Usage   : app:push("main_menu") (the title screen does it)
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Style = require("src.shell.style")
local Widgets = require("src.shell.widgets")
local Version = require("src.version")

local MainMenu = {}

-- ---- Tunables ----------------------------------------------------------------
local MENU_W = 240

function MainMenu:enter()
  local app = self.app
  local function t(key) return function() return app:t(key) end end
  local rows = {
    Widgets.button("play", t("menu.play"), function() app:push("loading", { next = "play" }) end),
    Widgets.button("settings", t("menu.settings"), function() app:push("settings") end),
    Widgets.button("credits", t("menu.credits"), function() app:push("credits") end),
  }
  if app.debug_build then
    rows[#rows + 1] = Widgets.button("juice", t("menu.juice"), function() app:push("loading", { next = "juice_demo" }) end)
  end
  rows[#rows + 1] = Widgets.button("quit", t("menu.quit"), function() app:quit() end)
  self.list = Widgets.list(rows, { on_move = function() app:play_sound("move", "ui") end })
end

function MainMenu:focus_id() return self.list:focused_id() end

function MainMenu:action(name)
  if name == "ui_cancel" then self.app:pop() return true end
  if name == "ui_accept" then self.app:play_sound("accept", "ui") end
  return self.list:action(name)
end

function MainMenu:draw(ui)
  local app = self.app
  ui:label("menu.title", app:t("title.name", { name = Version.name }), 0, 40, Style.BASE_W, 40,
           { align = "center", font = ui:font(Style.TITLE_PX), color = Style.color.accent })
  self.list:draw(ui, (Style.BASE_W - MENU_W) / 2, 110, MENU_W, { prefix = "menu", center = true })
  local gname, label = app:prompt("ui_accept")
  local hint = app:t("hint.select")
  local font = ui:font(Style.SMALL_PX)
  local y = Style.BASE_H - 30
  local w = ui:glyph_cell("menu.hint.glyph", gname, label, 16, y, 20)
  ui:label("menu.hint", hint, 22 + w, y, font:getWidth(hint) + 2, 20, { font = font, color = Style.color.dim })
end

return MainMenu

-- {{FOOTER}}
