-- ---------------------------------------------------------------------------
-- spring.lua
-- Purpose : A damped spring for squash and stretch recovery, UI pops and wobble, plus squash(), the scale pair
--           that keeps a sprite's area while it squashes. Matches data/golden/juice.json "spring" and "squash".
-- Usage   : local Spring = require("src.core.spring")
--           local s = Spring.new(4.0, 0.5)          -- frequency in Hz, damping ratio (1 = no overshoot)
--           on landing: s.x = 0.4                   -- displace it (or set s.target)
--           each frame: local amount = s:update(dt); local sx, sy = Spring.squash(amount)
-- Notes   : No love.* calls. Semi-implicit Euler (velocity first, then position): stable at game frame rates.
--           squash(amount): amount > 0 widens and flattens, < 0 stretches; clamped above -0.9.
--
-- Pseudocode:
--   w = 2*pi*frequency ; a = -w^2 * (x - target) - 2*damping*w*v ; v += a*dt ; x += v*dt
--   squash(a) -> 1 + a, 1 / (1 + a)
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Spring = {}
Spring.__index = Spring

-- ---- Tunables ----------------------------------------------------------------
Spring.FREQUENCY = 4.0                   -- Hz
Spring.DAMPING = 0.5                     -- ratio: below 1 overshoots (bouncy), 1 settles fastest without overshoot
local SQUASH_MIN = -0.9                  -- a stretch past this would flip the sprite

function Spring.new(frequency, damping)
  return setmetatable({ frequency = frequency or Spring.FREQUENCY, damping = damping or Spring.DAMPING,
                        x = 0.0, v = 0.0, target = 0.0 }, Spring)
end

function Spring:update(dt)
  local w = 2.0 * math.pi * self.frequency
  local a = -w * w * (self.x - self.target) - 2.0 * self.damping * w * self.v
  self.v = self.v + a * dt
  self.x = self.x + self.v * dt
  return self.x
end

function Spring.squash(amount)
  local a = math.max(amount, SQUASH_MIN)
  return 1.0 + a, 1.0 / (1.0 + a)
end

return Spring

-- {{FOOTER}}
