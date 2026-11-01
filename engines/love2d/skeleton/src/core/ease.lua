-- ---------------------------------------------------------------------------
-- ease.lua
-- Purpose : The standard easing curves (easings.net names), so tweens, UI pops and camera moves feel the same in
--           every engine of the kit. Matches data/golden/juice.json "ease".
-- Usage   : local Ease = require("src.core.ease")
--           local k = Ease.ease("out_back", elapsed / duration)    -- t is clamped to 0..1
--           x = from + (to - from) * k
-- Notes   : No love.* calls. An unknown name raises an error (a typo must not silently become linear).
--           Ease.NAMES lists every curve in sorted order.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Ease = {}

-- ---- Tunables ----------------------------------------------------------------
local C1 = 1.70158                       -- the "back" overshoot
local C3 = C1 + 1.0
local C4 = 2.0 * math.pi / 3.0           -- the elastic period
local BOUNCE_N1, BOUNCE_D1 = 7.5625, 2.75

local function bounce(t)
  if t < 1.0 / BOUNCE_D1 then return BOUNCE_N1 * t * t end
  if t < 2.0 / BOUNCE_D1 then
    t = t - 1.5 / BOUNCE_D1
    return BOUNCE_N1 * t * t + 0.75
  end
  if t < 2.5 / BOUNCE_D1 then
    t = t - 2.25 / BOUNCE_D1
    return BOUNCE_N1 * t * t + 0.9375
  end
  t = t - 2.625 / BOUNCE_D1
  return BOUNCE_N1 * t * t + 0.984375
end

Ease.CURVES = {
  linear = function(t) return t end,
  in_quad = function(t) return t * t end,
  out_quad = function(t) return 1.0 - (1.0 - t) * (1.0 - t) end,
  in_out_quad = function(t)
    if t < 0.5 then return 2.0 * t * t end
    return 1.0 - (-2.0 * t + 2.0) ^ 2 / 2.0
  end,
  in_cubic = function(t) return t * t * t end,
  out_cubic = function(t) return 1.0 - (1.0 - t) ^ 3 end,
  in_out_cubic = function(t)
    if t < 0.5 then return 4.0 * t * t * t end
    return 1.0 - (-2.0 * t + 2.0) ^ 3 / 2.0
  end,
  in_sine = function(t) return 1.0 - math.cos(t * math.pi / 2.0) end,
  out_sine = function(t) return math.sin(t * math.pi / 2.0) end,
  in_out_sine = function(t) return -(math.cos(math.pi * t) - 1.0) / 2.0 end,
  in_back = function(t) return C3 * t * t * t - C1 * t * t end,
  out_back = function(t) return 1.0 + C3 * (t - 1.0) ^ 3 + C1 * (t - 1.0) ^ 2 end,
  out_elastic = function(t)
    if t <= 0.0 then return 0.0 end
    if t >= 1.0 then return 1.0 end
    return 2.0 ^ (-10.0 * t) * math.sin((t * 10.0 - 0.75) * C4) + 1.0
  end,
  out_bounce = bounce,
}

Ease.NAMES = {}
for name in pairs(Ease.CURVES) do Ease.NAMES[#Ease.NAMES + 1] = name end
table.sort(Ease.NAMES)

function Ease.ease(name, t)
  local curve = Ease.CURVES[name]
  if not curve then error("unknown easing curve '" .. tostring(name) .. "'", 2) end
  return curve(math.min(math.max(t, 0.0), 1.0))
end

return Ease

-- {{FOOTER}}
