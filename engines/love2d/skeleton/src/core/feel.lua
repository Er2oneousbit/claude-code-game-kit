-- ---------------------------------------------------------------------------
-- feel.lua
-- Purpose : The small helpers SOP-18's recipe table builds on (#170, #164): impact (a hit confirm scaled by damage),
--           float_text (a damage number's rise, pop and fade) and the tracer's point history by distance
--           (trail_push, trail_shrink, trail_length). Matches data/golden/juice.json "impact", "float_text", "trail".
-- Usage   : local Feel = require("src.core.feel")
--           local hit = Feel.impact(damage, enemy.max_hp)
--           hitstop:hit(hit.hitstop); shake:add_trauma(hit.trauma)
--           if hit.flash and limiter:request(love.timer.getTime()) then flash() end
--           local f = Feel.float_text(label.age)         -- f.dy, f.scale, f.alpha, f.done
--           tracer = Feel.trail_push(tracer, bx, by, spacing, length)   -- every frame; after the hit:
--           tracer = Feel.trail_shrink(tracer, speed * dt)              -- until fewer than two points
-- Notes   : No love.* calls. Pure functions: no settings, no clock, no random numbers. Points are {x, y} pairs,
--           tail first, head last; each trail function returns a new list. The defaults are SOP-18's starting points.
--
-- Pseudocode:
--   impact: f = clamp(damage / full, 0, 1) (full <= 0: 1); nothing for damage <= 0; lerp hitstop, trauma; flash f >= at
--   float_text: u = t / life; dy = -rise * out_cubic(u); scale = out_back(t / pop); alpha = 1 - in_cubic(u)
--   trail_push: < 2 points: append; head spacing past the point before it: append; else move the head; cut to length
--   trail_shrink: cut the trail to (length - amount) from the tail
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): impact is the same with blood on or off; what a
--           hit leaves is the game's: blood, or (blood_enabled off) a neutral spark or dust (SOP-18 step 4, #171)
-- ---------------------------------------------------------------------------
local Ease = require("src.core.ease")

local Feel = {}

-- ---- Tunables (SOP-18 step 4 starting points) --------------------------------
Feel.HITSTOP_MIN, Feel.HITSTOP_MAX = 0.03, 0.1    -- s: the smallest hit, a full one (under Hitstop's 0.25 s cap)
Feel.TRAUMA_MIN, Feel.TRAUMA_MAX = 0.15, 0.6
Feel.FLASH_AT = 0.5                               -- a hit of at least half of `full` asks for a flash
Feel.FLOAT_LIFE, Feel.FLOAT_RISE, Feel.FLOAT_POP = 0.8, 24.0, 0.12   -- s, px, s
Feel.TRAIL_SPACING, Feel.TRAIL_LENGTH = 6.0, 48.0 -- px between kept points, px of the longest trail
local EPS = 1e-12                                 -- a cut this close to a point removes the point

function Feel.impact(damage, full, hitstop_min, hitstop_max, trauma_min, trauma_max, flash_at)
  hitstop_min, hitstop_max = hitstop_min or Feel.HITSTOP_MIN, hitstop_max or Feel.HITSTOP_MAX
  trauma_min, trauma_max = trauma_min or Feel.TRAUMA_MIN, trauma_max or Feel.TRAUMA_MAX
  flash_at = flash_at or Feel.FLASH_AT
  if damage <= 0 then return { hitstop = 0.0, trauma = 0.0, flash = false } end
  local f = 1.0
  if full > 0 then f = math.min(math.max(damage / full, 0.0), 1.0) end
  return { hitstop = hitstop_min + (hitstop_max - hitstop_min) * f,
           trauma = trauma_min + (trauma_max - trauma_min) * f, flash = f >= flash_at }
end

function Feel.float_text(t, life, rise, pop_s)
  life, rise, pop_s = life or Feel.FLOAT_LIFE, rise or Feel.FLOAT_RISE, pop_s or Feel.FLOAT_POP
  local u = 1.0
  if life > 0 then u = math.min(math.max(t / life, 0.0), 1.0) end
  local scale = 1.0
  if pop_s > 0 then scale = Ease.ease("out_back", t / pop_s) end
  return { dy = -rise * Ease.ease("out_cubic", u), scale = scale, alpha = 1.0 - Ease.ease("in_cubic", u),
           done = t >= life }
end

local function seg(a, b)
  local dx, dy = b[1] - a[1], b[2] - a[2]
  return math.sqrt(dx * dx + dy * dy)
end

function Feel.trail_length(points)
  local total = 0.0
  for i = 1, #points - 1 do total = total + seg(points[i], points[i + 1]) end
  return total
end

local function copy(points)
  local out = {}
  for i, p in ipairs(points) do out[i] = { p[1], p[2] } end
  return out
end

local function trim_to(points, keep)
  local pts = copy(points)
  local excess = Feel.trail_length(pts) - math.max(keep, 0.0)
  while excess > EPS and #pts > 1 do
    local s = seg(pts[1], pts[2])
    if s <= excess + EPS then
      table.remove(pts, 1)
      excess = excess - s
    else
      local k = excess / s
      pts[1] = { pts[1][1] + (pts[2][1] - pts[1][1]) * k, pts[1][2] + (pts[2][2] - pts[1][2]) * k }
      excess = 0.0
    end
  end
  return pts
end

function Feel.trail_push(points, x, y, spacing, max_len)
  spacing, max_len = spacing or Feel.TRAIL_SPACING, max_len or Feel.TRAIL_LENGTH
  local pts = copy(points)
  if #pts < 2 or seg(pts[#pts - 1], pts[#pts]) >= spacing then
    pts[#pts + 1] = { x, y }
  else
    pts[#pts] = { x, y }
  end
  return trim_to(pts, max_len)
end

function Feel.trail_shrink(points, amount)
  return trim_to(points, Feel.trail_length(points) - amount)
end

return Feel

-- {{FOOTER}}
