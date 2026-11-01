-- ---------------------------------------------------------------------------
-- play.lua
-- Purpose : The play screen: runs the game (src/game/game.lua) inside the shell. Game time is scaled by the
--           player's game_speed; the pause action and focus loss open the pause menu; leaving saves slot 1.
-- Usage   : app:push("loading", { next = "play" }) -> this screen
--           the game gets: Game.load(kit, { app = app, save = data_or_nil }), Game.update(dt), Game.draw(),
--           Game.action(name) for pressed actions (optional), Game.save_data() -> a table to save (optional)
-- Notes   : The save goes through src/core/save_store.lua (atomic, .bak, migrations, never over a newer save).
--           Held actions: app.input:is_down("move_left").
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Log = require("src.core.log")
local Style = require("src.shell.style")

local Play = { pausable = true }

-- ---- Tunables ----------------------------------------------------------------
local SAVE_SLOT = 1

function Play:enter()
  local app = self.app
  self.game = require("src.game.game")
  local r = app.saves:load(SAVE_SLOT)
  for _, p in ipairs(r.problems) do
    if not p:find(": missing$") then Log.warn("save", "slot " .. SAVE_SLOT .. " " .. p) end
  end
  if r.newer then app:toast(app:t("toast.save_newer")) end
  self.game.load(app.kit, { app = app, save = r.envelope and r.envelope.data or nil })
end

function Play:leave()
  local app = self.app
  if type(self.game.save_data) ~= "function" then return end
  local ok, path = pcall(app.saves.save, app.saves, SAVE_SLOT, self.game.save_data())
  if ok then Log.info("save", "saved " .. path) else Log.warn("save", tostring(path)) end
end

function Play:update(dt)
  self.game.update(dt * self.app:game_speed())
end

function Play:action(name)
  if name == "pause" then self.app:push("pause") return true end
  if self.game.action then return self.game.action(name) == true end
  return false
end

function Play:draw(ui)
  self.game.draw()
  local app = self.app
  local gname, label = app:prompt("pause")
  local font = ui:font(Style.SMALL_PX)
  local hint = app:t("hint.pause")
  local w = ui:glyph_cell("play.hint.glyph", gname, label, 12, 8, 20)
  ui:label("play.hint", hint, 18 + w, 8, font:getWidth(hint) + 2, 20, { font = font, color = Style.color.dim })
end

return Play

-- {{FOOTER}}
