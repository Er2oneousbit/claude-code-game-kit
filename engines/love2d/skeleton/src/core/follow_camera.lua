-- ---------------------------------------------------------------------------
-- follow_camera.lua
-- Purpose : A camera that follows a target: a deadzone box the target can move in without moving the camera,
--           look-ahead along the target's velocity, and smoothing that is the same at 30, 60 or 144 fps.
--           Matches data/golden/juice.json "follow".
-- Usage   : local FollowCamera = require("src.core.follow_camera")
--           local cam = FollowCamera.new({ deadzone_w = 64, deadzone_h = 48, lookahead = 0.25, smoothing = 8 })
--           each frame: local cx, cy = cam:update(dt, player.x, player.y, player.vx, player.vy)
--           draw: love.graphics.translate(screen_w / 2 - cx, screen_h / 2 - cy)
-- Notes   : No love.* calls. smoothing is a rate per second (0 = snap). The exponential form 1 - exp(-k*dt) is
--           what keeps it frame-rate independent; a plain lerp by a constant is not.
--
-- Pseudocode:
--   per axis: target outside cam +- half deadzone -> desired = target -+ half, else desired = cam
--   desired += velocity * lookahead
--   k = 1 - exp(-smoothing * dt) (1 when smoothing is 0); cam += (desired - cam) * k
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local FollowCamera = {}
FollowCamera.__index = FollowCamera

-- ---- Tunables ----------------------------------------------------------------
FollowCamera.DEFAULTS = {
  deadzone_w = 64.0,                     -- px the target may move left/right before the camera follows
  deadzone_h = 48.0,
  lookahead = 0.25,                      -- seconds of velocity to lead by
  smoothing = 8.0,                       -- per second; 0 snaps
  x = 0.0, y = 0.0,                      -- start position
}

function FollowCamera.new(params)
  local self = setmetatable({}, FollowCamera)
  for k, v in pairs(FollowCamera.DEFAULTS) do
    if params and params[k] ~= nil then self[k] = params[k] else self[k] = v end
  end
  return self
end

local function axis(cam, target, half)
  if target > cam + half then return target - half end
  if target < cam - half then return target + half end
  return cam
end

function FollowCamera:update(dt, tx, ty, vx, vy)
  local dx = axis(self.x, tx, self.deadzone_w / 2.0) + (vx or 0.0) * self.lookahead
  local dy = axis(self.y, ty, self.deadzone_h / 2.0) + (vy or 0.0) * self.lookahead
  local k = 1.0
  if self.smoothing > 0.0 then k = 1.0 - math.exp(-self.smoothing * dt) end
  self.x = self.x + (dx - self.x) * k
  self.y = self.y + (dy - self.y) * k
  return self.x, self.y
end

return FollowCamera

-- {{FOOTER}}
