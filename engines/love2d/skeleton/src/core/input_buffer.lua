-- ---------------------------------------------------------------------------
-- input_buffer.lua
-- Purpose : Input buffering: remembers a press for a short window, so a jump pressed a few frames before landing
--           still happens on landing. Matches data/golden/juice.json "input_buffer".
-- Usage   : local InputBuffer = require("src.core.input_buffer")
--           local buffer = InputBuffer.new(0.12)
--           on press: buffer:press("jump")
--           each frame: buffer:update(dt); if can_jump and buffer:consume("jump") then jump() end
-- Notes   : No love.* calls. One pending entry per action; pressing again restarts its window. Pair it with the
--           coyote timer (src/core/coyote_timer.lua): buffering covers early presses, coyote time late ones.
--
-- Pseudocode:
--   press(a)   -> pending[a] = window
--   update(dt) -> every pending entry -= dt; entries at or below zero are dropped
--   consume(a) -> pending[a] > 0: drop it and return true; else false
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local InputBuffer = {}
InputBuffer.__index = InputBuffer

-- ---- Tunables ----------------------------------------------------------------
InputBuffer.WINDOW_S = 0.12              -- how long a press is remembered
local EXPIRED = 1e-12                    -- float dust: 0.12 - 0.1 - 0.02 is not exactly 0

function InputBuffer.new(window_s)
  return setmetatable({ window = window_s or InputBuffer.WINDOW_S, pending = {} }, InputBuffer)
end

function InputBuffer:press(action)
  self.pending[action] = self.window
end

function InputBuffer:update(dt)
  local names = {}
  for a in pairs(self.pending) do names[#names + 1] = a end
  table.sort(names)
  for _, a in ipairs(names) do
    self.pending[a] = self.pending[a] - dt
    if self.pending[a] <= EXPIRED then self.pending[a] = nil end
  end
end

function InputBuffer:consume(action)
  if (self.pending[action] or 0.0) > 0.0 then
    self.pending[action] = nil
    return true
  end
  return false
end

function InputBuffer:clear() self.pending = {} end

return InputBuffer

-- {{FOOTER}}
