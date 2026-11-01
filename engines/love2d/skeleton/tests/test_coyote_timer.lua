-- ---------------------------------------------------------------------------
-- test_coyote_timer.lua
-- Purpose : Unit tests for CoyoteTimer. Doubles as the example of how to write engine-free tests in this project.
-- Usage   : python tools/dev.py test     (or --filter coyote)
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local CoyoteTimer = require("src.core.coyote_timer")
local T = {}

function T.test_can_jump_on_floor()
  local t = CoyoteTimer.new(0.1)
  t:update(0.016, true)
  A.truthy(t:can_jump(), "grounded")
end

function T.test_grace_window_after_leaving_floor()
  local t = CoyoteTimer.new(0.1)
  t:update(0.016, true)
  t:update(0.05, false)
  A.truthy(t:can_jump(), "still open at 50 ms")
  t:update(0.2, false)
  A.falsy(t:can_jump(), "closed after the window")
end

function T.test_consumed_jump_waits_for_landing()
  local t = CoyoteTimer.new(0.1)
  t:update(0.016, true)
  t:consume()
  t:update(0.016, true)
  A.falsy(t:can_jump(), "no second jump while still grounded")
  t:update(0.016, false)
  t:update(0.016, true)
  A.truthy(t:can_jump(), "a new landing re-arms it")
end

function T.test_zero_window_still_allows_grounded_jumps()
  local t = CoyoteTimer.new(0)
  t:update(0.016, true)
  A.truthy(t:can_jump())
end

return T

-- {{FOOTER}}
