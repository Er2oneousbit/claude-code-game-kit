-- ---------------------------------------------------------------------------
-- analog.lua
-- Purpose : Analog input shaping (#274): the left stick and the triggers as the game reads them, after the player's
--           deadzone and invert_y, so a racer steers by how far the stick leans and brakes by how far a trigger is
--           in. The same rules as the Bevy shell's Intent (#265).
-- Usage   : local Analog = require("src.core.analog")
--           local x, y = Analog.stick(raw_x, raw_y, settings.input.deadzone, settings.input.invert_y)
--           local gas = Analog.trigger(raw_r2)                      -- 0 at rest to 1 fully in
--           Analog.stick_actions(raw_x, raw_y, deadzone, invert_y)  -- { "move_left" } while the stick leans left
-- Notes   : No love.* calls (tests run it as plain Lua). The stick deadzone is radial (the length of the vector, not
--           each axis), and what is left is rescaled to 0..1, so a stick just past the deadzone gives a small value
--           instead of jumping to the deadzone's size; the direction never changes. Up is -y, as LÖVE's gamepad
--           axes and screen coordinates have it; invert_y flips it. Triggers have their own small fixed deadzone:
--           input.deadzone is the "Stick deadzone" setting, and a trigger that rests at 0.1 would otherwise lose a
--           fifth of its travel. NaN and infinities (a broken driver) count as 0.
--
-- Pseudocode:
--   stick(x, y, dz, inv): y = -y if inv -> len = |(x, y)| -> len <= dz: (0, 0)
--   -> scale = min((len - dz) / (1 - dz), 1) / len -> (x * scale, y * scale)
--   trigger(v, dz): v = clamp(v, 0, 1) -> v <= dz: 0 -> (v - dz) / (1 - dz)
--   stick_actions: raw lean past max(dz, STICK_HOLD_MIN) per direction (invert_y honoured) -> move_* names
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Analog = {}

-- ---- Tunables ----------------------------------------------------------------
Analog.TRIGGER_DEADZONE = 0.05   -- trigger travel ignored at rest (0 to 1)
Analog.MAX_DEADZONE = 0.95       -- the largest deadzone accepted (settings clamp input.deadzone to 0.9 too)
Analog.STICK_HOLD_MIN = 0.2      -- raw stick lean that also holds a move_* action; never below the player's deadzone

local function finite(v)
  if type(v) ~= "number" or v ~= v or v == math.huge or v == -math.huge then return 0 end
  return v
end

local function clamp(v, lo, hi) return math.min(math.max(v, lo), hi) end

-- The stick after the radial deadzone and invert_y: each axis -1..1, the vector's length 0..1, up is -y.
function Analog.stick(x, y, deadzone, invert_y)
  x, y = finite(x), finite(y)
  if invert_y then y = -y end
  local dz = clamp(finite(deadzone), 0, Analog.MAX_DEADZONE)
  local len = math.sqrt(x * x + y * y)
  if len <= dz or len == 0 then return 0, 0 end
  local scale = math.min((len - dz) / (1 - dz), 1) / len
  return x * scale, y * scale
end

-- A trigger (0 at rest, 1 fully in) after its deadzone, rescaled to 0..1.
function Analog.trigger(value, deadzone)
  local v = clamp(finite(value), 0, 1)
  local dz = clamp(finite(deadzone or Analog.TRIGGER_DEADZONE), 0, Analog.MAX_DEADZONE)
  if v <= dz then return 0 end
  return (v - dz) / (1 - dz)
end

-- The move_* actions a raw stick lean holds: past max(deadzone, STICK_HOLD_MIN), invert_y honoured, up is -y.
function Analog.stick_actions(x, y, deadzone, invert_y)
  local on = math.max(finite(deadzone), Analog.STICK_HOLD_MIN)
  x, y = finite(x), finite(y)
  if invert_y then y = -y end
  local out = {}
  if x < -on then out[#out + 1] = "move_left" end
  if x > on then out[#out + 1] = "move_right" end
  if y < -on then out[#out + 1] = "move_up" end
  if y > on then out[#out + 1] = "move_down" end
  return out
end

return Analog

-- {{FOOTER}}
