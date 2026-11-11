-- ---------------------------------------------------------------------------
-- test_frame_times.lua
-- Purpose : Unit tests for FrameTimes, the FRAME_TIMES line `dev.py smoke` reads (#90).
-- Usage   : python tools/dev.py test     (or --filter frame)
-- Notes   : Nearest-rank percentiles, the same rule as every engine's FRAME_TIMES line.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local FrameTimes = require("src.core.frame_times")
local T = {}

function T.test_summary_of_1_to_100_ms_in_any_order()
  local list = {}
  for i = 100, 1, -1 do list[#list + 1] = i end
  local s = FrameTimes.summary(list)
  A.eq(s.frames, 100)
  A.near(s.mean, 50.5, 1e-9)
  A.eq(s.p95, 95)
  A.eq(s.p99, 99)
  A.eq(s.worst, 100)
end

function T.test_one_frame_is_every_percentile()
  local s = FrameTimes.summary({ 7.5 })
  A.eq(s.p95, 7.5)
  A.eq(s.p99, 7.5)
  A.eq(s.worst, 7.5)
end

function T.test_the_line_dev_py_reads()
  local ft = FrameTimes.new()
  ft:add(16)
  ft:add(17)
  ft:add(40)
  A.eq(ft:line("render"), "FRAME_TIMES frames=3 mean=24.33 p95=40.00 p99=40.00 worst=40.00 mode=render")
end

function T.test_no_frames_no_line()
  A.eq(FrameTimes.new():line("logic"), "")
end

return T

-- {{FOOTER}}
