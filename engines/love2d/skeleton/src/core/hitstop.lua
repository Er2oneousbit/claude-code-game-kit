-- ---------------------------------------------------------------------------
-- hitstop.lua
-- Purpose : Hitstop (hit pause): freezes game time for a few frames on impact so a hit feels heavy. Overlapping
--           hits keep the longest freeze, capped at max_s. Matches data/golden/juice.json "hitstop".
-- Usage   : local Hitstop = require("src.core.hitstop")
--           local hitstop = Hitstop.new(0.25)
--           on a hit: hitstop:hit(0.08)
--           each frame: local game_dt = hitstop:scaled_dt(dt)   -- 0 while frozen; pass game_dt to gameplay
-- Notes   : No love.* calls. Keep UI, audio and the hitstop itself on the real dt; only gameplay uses game_dt. A
--           frame that ends the freeze returns the unfrozen remainder, so no time is lost or doubled.
--
-- Pseudocode:
--   hit(d)        -> remaining = min(max(remaining, d), max_s)
--   scaled_dt(dt) -> remaining <= 0: dt ; else used = min(remaining, dt); remaining -= used; return dt - used
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Hitstop = {}
Hitstop.__index = Hitstop

-- ---- Tunables ----------------------------------------------------------------
Hitstop.MAX_S = 0.25                     -- the longest freeze one hit (or a flurry) can cause

function Hitstop.new(max_s)
  return setmetatable({ max_s = max_s or Hitstop.MAX_S, remaining = 0.0 }, Hitstop)
end

function Hitstop:hit(duration)
  self.remaining = math.min(math.max(self.remaining, duration), self.max_s)
end

function Hitstop:scaled_dt(real_dt)
  if self.remaining <= 0.0 then return real_dt end
  local used = math.min(self.remaining, real_dt)
  self.remaining = self.remaining - used
  return real_dt - used
end

function Hitstop:active() return self.remaining > 0.0 end

return Hitstop

-- {{FOOTER}}
