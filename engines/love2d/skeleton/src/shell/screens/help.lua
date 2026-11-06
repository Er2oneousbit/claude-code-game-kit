-- ---------------------------------------------------------------------------
-- help.lua
-- Purpose : "What now?" from the pause menu (#167, cognitive access): the current goal, the last line someone said,
--           and the controls for play, so a player who lost track can pick up again without guessing.
-- Usage   : app:push("help") (the pause menu does it); the game sets the goal: app:set_objective(app:t("..."))
-- Notes   : The goal is whatever the game last set; the last line comes from app.history (app:say records each
--           line that plays). Controls follow the device in use.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local TextPage = require("src.shell.screens.text_page")

local Help = {}

local CONTROL_ACTIONS = { "move_left", "move_right", "jump", "attack", "interact", "pause" }

function Help:enter() self.offset = 0 end

function Help:action(name) return TextPage.action(self, name) end

function Help:draw(ui)
  local app = self.app
  local lines = { app.objective ~= "" and app:t("help.objective", { text = app.objective }) or app:t("help.no_objective") }
  local last = app.history[#app.history]
  if last then lines[#lines + 1] = app:t("help.last_line", { name = last.name, text = last.text }) end
  lines[#lines + 1] = app:t("help.controls")
  for _, action in ipairs(CONTROL_ACTIONS) do
    local _, label = app:prompt(action)
    lines[#lines + 1] = app:t("action." .. action) .. ": " .. label
  end
  TextPage.draw(self, ui, app:t("help.title"), lines, "help")
end

return Help

-- {{FOOTER}}
