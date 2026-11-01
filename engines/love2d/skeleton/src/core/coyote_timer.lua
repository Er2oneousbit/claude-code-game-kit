-- ---------------------------------------------------------------------------
-- coyote_timer.lua
-- Purpose : Example of ENGINE-FREE logic that is unit testable. Grants a short grace window to still jump after
--           leaving a ledge ("coyote time"). Same rules as the kit's Godot and web CoyoteTimer and the golden
--           vectors in data/golden/juice.json (type "coyote").
-- Usage   : local CoyoteTimer = require("src.core.coyote_timer")
--           local t = CoyoteTimer.new(0.1)
--           each tick: t:update(dt, on_floor)   on jump pressed: if t:can_jump() then ... t:consume() end
-- Notes   : No love.* calls, so tests/ runs it without a window. A window of 0 means "no coyote time", not "no
--           jumping". This file is a TEMPLATE example: delete it if the game has no jump.
--
-- Pseudocode:
--   on floor  -> grounded, time_left = window; a landing re-arms a consumed jump
--   off floor -> not grounded, time_left = max(0, time_left - dt)
--   can_jump  -> not consumed and (grounded or time_left > 0)
--   consume   -> consumed until the next landing
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local CoyoteTimer = {}
CoyoteTimer.__index = CoyoteTimer

function CoyoteTimer.new(window_seconds)
  -- guard against negative windows from bad tuning data
  return setmetatable({ window = math.max(window_seconds or 0.1, 0), time_left = 0, grounded = false,
                        consumed = false }, CoyoteTimer)
end

function CoyoteTimer:update(dt, on_floor)
  if on_floor then
    if not self.grounded then self.consumed = false end   -- landed: the next jump is available again
    self.grounded = true
    self.time_left = self.window
  else
    self.grounded = false
    self.time_left = math.max(self.time_left - dt, 0)
  end
end

function CoyoteTimer:can_jump()
  return (not self.consumed) and (self.grounded or self.time_left > 0)
end

function CoyoteTimer:consume()
  self.consumed = true
  self.time_left = 0
end

return CoyoteTimer

-- {{FOOTER}}
