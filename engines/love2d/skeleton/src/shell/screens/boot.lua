-- ---------------------------------------------------------------------------
-- boot.lua
-- Purpose : The first screen: the game's name for a moment while the shell settles, then the title screen.
--           Put a studio logo or an epilepsy warning here if the game needs one.
-- Usage   : app:push("boot") (app.lua does it at load)
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Style = require("src.shell.style")
local Version = require("src.version")

local Boot = {}

-- ---- Tunables ----------------------------------------------------------------
local BOOT_S = 0.5                       -- seconds on screen in play
local BOOT_FRAMES_AUTOMATED = 2          -- frames in a smoke run

function Boot:enter()
  self.t, self.frames = 0, 0
end

function Boot:update(dt)
  self.t, self.frames = self.t + dt, self.frames + 1
  local done = self.app.kit.automated and self.frames >= BOOT_FRAMES_AUTOMATED or self.t >= BOOT_S
  if done then self.app:replace("title") end
end

function Boot:draw(ui)
  ui:label("boot.name", self.app:t("title.name", { name = Version.name }), 0, 0, Style.BASE_W, Style.BASE_H,
           { align = "center", font = ui:font(Style.TITLE_PX), color = Style.color.dim })
end

-- any key skips the boot screen
function Boot:raw()
  self.t = BOOT_S
  return true
end

return Boot

-- {{FOOTER}}
