-- ---------------------------------------------------------------------------
-- frame_times.lua
-- Purpose : Frame-time sampling for `dev.py smoke` (#90): main.lua adds each smoke frame's time and prints one line
--           at the end of the run, which dev.py reports and checks against --frame-budget:
--             FRAME_TIMES frames=N mean=MS p95=MS p99=MS worst=MS mode=render|logic
-- Usage   : local FrameTimes = require("src.core.frame_times")
--           local ft = FrameTimes.new(); ft:add(dt * 1000); print(ft:line("render"))
--           FrameTimes.summary(list) is a plain function (tests/test_frame_times.lua).
-- Notes   : Engine-free. A plain smoke runs without vsync in a small off-screen window, so the numbers are what a
--           frame costs to update and draw ("render"); --headless draws nothing ("logic": a logic budget, not a
--           render budget). Percentiles are nearest-rank, the same rule as every engine's FRAME_TIMES line.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local FrameTimes = {}
FrameTimes.__index = FrameTimes

function FrameTimes.new()
  return setmetatable({ samples = {} }, FrameTimes)
end

-- Records one frame's time in milliseconds.
function FrameTimes:add(ms)
  self.samples[#self.samples + 1] = ms
end

-- Nearest rank: the smallest value with at least q of the samples at or below it (sorted must not be empty).
local function rank(sorted, q)
  local i = math.max(1, math.ceil(q * #sorted))
  return sorted[math.min(i, #sorted)]
end

-- { frames, mean, p95, p99, worst } in ms (frames 0, the rest 0, when there are none).
function FrameTimes.summary(list)
  local out = { frames = #list, mean = 0, p95 = 0, p99 = 0, worst = 0 }
  if #list == 0 then return out end
  local sorted, total = {}, 0
  for i, v in ipairs(list) do
    sorted[i] = v
    total = total + v
  end
  table.sort(sorted)
  out.mean = total / #sorted
  out.p95 = rank(sorted, 0.95)
  out.p99 = rank(sorted, 0.99)
  out.worst = sorted[#sorted]
  return out
end

-- The FRAME_TIMES line ("" when no frame was added).
function FrameTimes:line(mode)
  if #self.samples == 0 then return "" end
  local s = FrameTimes.summary(self.samples)
  return string.format("FRAME_TIMES frames=%d mean=%.2f p95=%.2f p99=%.2f worst=%.2f mode=%s",
    s.frames, s.mean, s.p95, s.p99, s.worst, mode)
end

return FrameTimes

-- {{FOOTER}}
