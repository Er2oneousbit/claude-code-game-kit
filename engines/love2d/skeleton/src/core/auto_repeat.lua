-- ---------------------------------------------------------------------------
-- auto_repeat.lua
-- Purpose : "Hold to mash" (access.auto_repeat, #166): a held button repeats its press, so a player who cannot tap
--           fast (one hand, a switch, tremor) can still mash.
-- Usage   : local rep = AutoRepeat.new()
--           if settings.access.auto_repeat and rep:update(dt, input:is_down("attack")) then attack() end
-- Notes   : No love.* calls. The first repeat comes after DELAY_S, then one every INTERVAL_S while held; releasing
--           resets it. The times are the kit's starting point (a tip: tune them per game), not from a source.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local AutoRepeat = {}
AutoRepeat.__index = AutoRepeat

AutoRepeat.DELAY_S = 0.35                -- held this long before the first repeat
AutoRepeat.INTERVAL_S = 0.15             -- then one repeat this often

function AutoRepeat.new()
  return setmetatable({ held = 0, next = AutoRepeat.DELAY_S }, AutoRepeat)
end

-- call every frame with whether the button is held; true on a frame that repeats the press
function AutoRepeat:update(dt, held)
  if not held then
    self.held, self.next = 0, AutoRepeat.DELAY_S
    return false
  end
  self.held = self.held + dt
  if self.held >= self.next then
    self.next = self.next + AutoRepeat.INTERVAL_S
    return true
  end
  return false
end

return AutoRepeat

-- {{FOOTER}}
