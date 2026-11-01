-- ---------------------------------------------------------------------------
-- flash_limiter.lua
-- Purpose : Photosensitivity guard: allows at most max_flashes full-screen flashes in any window_s seconds (three
--           per second, the common guideline). Ask it before every flash. Matches data/golden/juice.json
--           "flash_limiter".
-- Usage   : local FlashLimiter = require("src.core.flash_limiter")
--           local limiter = FlashLimiter.new()                     -- 3 per 1.0 s
--           if limiter:request(real_time) then flash(settings.access.flash_limit and 0.3 or 1.0) end
-- Notes   : No love.* calls; pass the time in: REAL time (love.timer), never game time, so hitstop or a slower
--           game speed cannot squeeze more flashes into a real second. The limiter is ALWAYS on, whatever the
--           settings say; access.flash_limit is an extra-gentle mode on top (flashes drawn at about 30 %
--           opacity). A refused flash should be replaced by something calmer (a colour tint, a border pulse),
--           never just dropped when it carries information.
--
-- Pseudocode:
--   request(now): keep only times > now - window; fewer than max -> record now, true; else false
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local FlashLimiter = {}
FlashLimiter.__index = FlashLimiter

-- ---- Tunables ----------------------------------------------------------------
FlashLimiter.MAX_FLASHES = 3
FlashLimiter.WINDOW_S = 1.0

function FlashLimiter.new(max_flashes, window_s)
  return setmetatable({ max = max_flashes or FlashLimiter.MAX_FLASHES, window = window_s or FlashLimiter.WINDOW_S,
                        times = {} }, FlashLimiter)
end

function FlashLimiter:request(now)
  local kept = {}
  for _, t in ipairs(self.times) do
    if t > now - self.window then kept[#kept + 1] = t end
  end
  self.times = kept
  if #kept < self.max then
    kept[#kept + 1] = now
    return true
  end
  return false
end

return FlashLimiter

-- {{FOOTER}}
