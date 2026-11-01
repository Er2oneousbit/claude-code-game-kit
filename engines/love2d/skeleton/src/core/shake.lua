-- ---------------------------------------------------------------------------
-- shake.lua
-- Purpose : Trauma-based screen shake: hits add trauma (0..1), trauma decays linearly, and the camera offset is
--           trauma squared times smooth noise, so small hits barely move it and big hits really do. Also the value
--           noise itself (Shake.noise), the same in every engine of the kit (data/golden/juice.json "noise",
--           "shake").
-- Usage   : local Shake = require("src.core.shake")
--           local shake = Shake.new({ max_offset = 8, decay = 1.5 })   -- any field left out takes the default
--           on a hit: shake:add_trauma(0.5)
--           each frame: local x, y, angle = shake:update(dt, Settings.effective_shake(settings))
--           then love.graphics.translate(x, y) and rotate(angle) around the screen centre
-- Notes   : No love.* calls. intensity is the player's shake setting (0 with reduce motion), so the camera never
--           moves for a player who asked it not to. The noise is integer arithmetic that stays exact in doubles
--           (Park-Miller), so LuaJIT, Python and JavaScript give the same numbers; no bit operations.
--
-- Pseudocode:
--   lattice(seed, i, ch) -> a pseudo-random value in (-1, 1] for an integer point i of channel ch
--   noise(seed, t, ch)   -> blend the lattice values at floor(t) and floor(t)+1 with smoothstep
--   update: time += dt; trauma -= decay*dt (not below 0); s = trauma^2 * intensity
--           x, y, angle = max_offset*s*noise(ch 0), max_offset*s*noise(ch 1), max_angle*s*noise(ch 2)
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Shake = {}
Shake.__index = Shake

-- ---- Tunables ----------------------------------------------------------------
Shake.DEFAULTS = {
  max_offset = 8.0,                      -- px at full trauma
  max_angle = 0.05,                      -- radians at full trauma
  decay = 1.5,                           -- trauma lost per second
  frequency = 15.0,                      -- noise samples per second (higher = more jittery)
  seed = 1,
}
local PM_M = 2147483647                  -- Park-Miller modulus (2^31 - 1)
local PM_A = 16807
local SEED_MUL, I_MUL, CH_MUL = 7919, 104729, 15485863

-- floor modulo for negative values too; math.fmod is exact for doubles
local function mod(a, m)
  local r = math.fmod(a, m)
  if r < 0 then r = r + m end
  return r
end

function Shake.lattice(seed, i, ch)
  local s = mod(seed * SEED_MUL + i * I_MUL + ch * CH_MUL, PM_M)
  if s == 0 then s = 1 end
  s = mod(s * PM_A, PM_M)
  s = mod(s * PM_A, PM_M)
  return s / (PM_M - 1) * 2.0 - 1.0
end

-- Smooth 1D value noise in about -1..1; t >= 0.
function Shake.noise(seed, t, ch)
  local i = math.floor(t)
  local f = t - i
  local a, b = Shake.lattice(seed, i, ch), Shake.lattice(seed, i + 1, ch)
  local u = f * f * (3.0 - 2.0 * f)
  return a + (b - a) * u
end

function Shake.new(params)
  local self = setmetatable({ trauma = 0.0, time = 0.0 }, Shake)
  for k, v in pairs(Shake.DEFAULTS) do
    if params and params[k] ~= nil then self[k] = params[k] else self[k] = v end
  end
  return self
end

function Shake:add_trauma(amount)
  self.trauma = math.min(math.max(self.trauma + amount, 0.0), 1.0)
end

-- Returns x, y, angle for this frame. intensity: 0..1, the player's setting (default 1).
function Shake:update(dt, intensity)
  intensity = intensity or 1.0
  self.time = self.time + dt
  self.trauma = math.max(self.trauma - self.decay * dt, 0.0)
  local s = self.trauma * self.trauma * intensity
  local t = self.time * self.frequency
  return self.max_offset * s * Shake.noise(self.seed, t, 0),
         self.max_offset * s * Shake.noise(self.seed, t, 1),
         self.max_angle * s * Shake.noise(self.seed, t, 2)
end

return Shake

-- {{FOOTER}}
