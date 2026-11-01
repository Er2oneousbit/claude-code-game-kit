-- ---------------------------------------------------------------------------
-- test_juice_golden.lua
-- Purpose : The juice modules (shake, hitstop, ease, follow camera, input buffer, coyote timer, spring, squash,
--           flash limiter) against data/golden/juice.json, one test per case. The expected values come from the
--           file at test time, never from this code.
-- Usage   : python tools/dev.py test     (or --filter juice)
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Golden = require("tests.helpers.golden")
local Shake = require("src.core.shake")
local Hitstop = require("src.core.hitstop")
local Ease = require("src.core.ease")
local FollowCamera = require("src.core.follow_camera")
local InputBuffer = require("src.core.input_buffer")
local CoyoteTimer = require("src.core.coyote_timer")
local Spring = require("src.core.spring")
local FlashLimiter = require("src.core.flash_limiter")

local FILE = "juice.json"

local function unknown_call(where, step)
  error(where .. ": unknown call '" .. tostring(step.call) .. "' (update the port and this test)", 0)
end

local handlers = {}

function handlers.noise(case, tol, where)
  for i, p in ipairs(case.points) do
    Golden.expect(Shake.noise(p[1], p[2], p[3]), p[4], tol, where .. " point " .. i)
  end
  return #case.points
end

function handlers.shake(case, tol, where)
  local s = Shake.new(case.params)
  local n = 0
  for i, step in ipairs(case.steps) do
    if step.call == "add_trauma" then
      s:add_trauma(step.a)
    elseif step.call == "update" then
      local x, y, angle = s:update(step.dt, step.intensity)
      Golden.expect({ x = x, y = y, angle = angle, trauma = s.trauma }, step.expect, tol, where .. " step " .. i)
      n = n + 4
    else
      unknown_call(where, step)
    end
  end
  return n
end

function handlers.hitstop(case, tol, where)
  local h = Hitstop.new(case.params.max_s)
  local n = 0
  for i, step in ipairs(case.steps) do
    if step.call == "hit" then
      h:hit(step.duration)
    elseif step.call == "scaled_dt" then
      local dt = h:scaled_dt(step.dt)
      Golden.expect({ dt = dt, remaining = h.remaining }, step.expect, tol, where .. " step " .. i)
      n = n + 2
    else
      unknown_call(where, step)
    end
  end
  return n
end

function handlers.ease(case, tol, where)
  for i, p in ipairs(case.points) do
    Golden.expect(Ease.ease(p[1], p[2]), p[3], tol, where .. " " .. p[1] .. " t=" .. p[2] .. " (point " .. i .. ")")
  end
  return #case.points
end

function handlers.follow(case, tol, where)
  local cam = FollowCamera.new(case.params)
  for i, step in ipairs(case.steps) do
    if step.call ~= "update" then unknown_call(where, step) end
    local x, y = cam:update(step.dt, step.tx, step.ty, step.vx, step.vy)
    Golden.expect({ x = x, y = y }, step.expect, tol, where .. " step " .. i)
  end
  return #case.steps * 2
end

function handlers.input_buffer(case, tol, where)
  local b = InputBuffer.new(case.params.window_s)
  local n = 0
  for i, step in ipairs(case.steps) do
    if step.call == "press" then
      b:press(step.action)
    elseif step.call == "update" then
      b:update(step.dt)
    elseif step.call == "consume" then
      Golden.expect({ result = b:consume(step.action) }, step.expect, tol, where .. " step " .. i)
      n = n + 1
    else
      unknown_call(where, step)
    end
  end
  return n
end

function handlers.coyote(case, tol, where)
  local c = CoyoteTimer.new(case.params.window_s)
  local n = 0
  for i, step in ipairs(case.steps) do
    if step.call == "update" then
      c:update(step.dt, step.on_floor)
    elseif step.call == "consume" then
      c:consume()
    elseif step.call == "can_jump" then
      Golden.expect({ result = c:can_jump() }, step.expect, tol, where .. " step " .. i)
      n = n + 1
    else
      unknown_call(where, step)
    end
  end
  return n
end

function handlers.spring(case, tol, where)
  local s = Spring.new(case.params.frequency, case.params.damping)
  s.x, s.v, s.target = case.params.x, case.params.v, case.params.target
  for i, step in ipairs(case.steps) do
    if step.call ~= "update" then unknown_call(where, step) end
    local x = s:update(step.dt)
    Golden.expect({ x = x, v = s.v }, step.expect, tol, where .. " step " .. i)
  end
  return #case.steps * 2
end

function handlers.squash(case, tol, where)
  for i, p in ipairs(case.points) do
    local sx, sy = Spring.squash(p[1])
    Golden.expect({ sx, sy }, { p[2], p[3] }, tol, where .. " point " .. i)
  end
  return #case.points * 2
end

function handlers.flash_limiter(case, tol, where)
  local f = FlashLimiter.new(case.params.max_flashes, case.params.window_s)
  for i, step in ipairs(case.steps) do
    if step.call ~= "request" then unknown_call(where, step) end
    Golden.expect({ result = f:request(step.now) }, step.expect, tol, where .. " step " .. i)
  end
  return #case.steps
end

return Golden.suite(Golden.load(FILE), handlers, FILE)

-- {{FOOTER}}
