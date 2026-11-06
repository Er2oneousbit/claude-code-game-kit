-- ---------------------------------------------------------------------------
-- history.lua
-- Purpose : "Dialogue history" from the pause menu (#167, cognitive access): every line said so far, newest last, so
--           a player who missed or forgot a line can read it again at their own pace.
-- Usage   : app:push("history") (the pause menu does it)
-- Notes   : Reads app.history (app:say records each line that plays, up to App.MAX_HISTORY); it opens at the
--           newest line, and up/down scroll.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local TextPage = require("src.shell.screens.text_page")

local History = {}

function History:enter() self.offset = math.huge end   -- the page clamps it: open at the newest line

function History:action(name) return TextPage.action(self, name) end

function History:draw(ui)
  local app = self.app
  local lines = {}
  for _, entry in ipairs(app.history) do
    lines[#lines + 1] = app:t("help.last_line", { name = entry.name, text = entry.text })
  end
  if #lines == 0 then lines[1] = app:t("history.empty") end
  TextPage.draw(self, ui, app:t("history.title"), lines, "history")
end

return History

-- {{FOOTER}}
