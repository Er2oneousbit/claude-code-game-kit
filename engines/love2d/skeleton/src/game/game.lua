-- ---------------------------------------------------------------------------
-- game.lua
-- Purpose : The starter game: a box that runs and jumps (with coyote time) on a floor. Replace it with your game;
--           keep the five functions main.lua calls (load, update, draw, keypressed, gamepadpressed).
-- Usage   : main.lua calls Game.load(KIT), Game.update(dt), Game.draw() and the input callbacks.
-- Notes   : Creates graphics only in draw (and never in a headless run), so `dev.py smoke --headless` still boots.
--           Tunables live in the constants block. This file is a TEMPLATE: replace it.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local CoyoteTimer = require("src.core.coyote_timer")

local SPEED = 140                         -- px/s
local GRAVITY = 900                       -- px/s^2
local JUMP_SPEED = 330                    -- px/s
local FLOOR_Y = 300                       -- top of the floor, in the 640x360 base
local BOX = 20                            -- box size, px
local COYOTE_S = 0.1

local Game = {}
local box = { x = 100, y = FLOOR_Y - BOX, vy = 0, dir = 1 }
local coyote = CoyoteTimer.new(COYOTE_S)

function Game.load(kit)
  Game.kit = kit
end

function Game.update(dt)
  -- walk back and forth on its own, so a smoke run exercises movement and jumping
  box.x = box.x + box.dir * SPEED * dt
  if box.x < 20 or box.x > 620 - BOX then box.dir = -box.dir end
  box.vy = box.vy + GRAVITY * dt
  box.y = box.y + box.vy * dt
  local on_floor = box.y >= FLOOR_Y - BOX
  if on_floor then box.y, box.vy = FLOOR_Y - BOX, 0 end
  coyote:update(dt, on_floor)
end

function Game.jump()
  if coyote:can_jump() then
    box.vy = -JUMP_SPEED
    coyote:consume()
  end
end

function Game.draw()
  love.graphics.clear(0.08, 0.09, 0.12)
  love.graphics.setColor(0.25, 0.27, 0.32)
  love.graphics.rectangle("fill", 0, FLOOR_Y, 640, 360 - FLOOR_Y)
  love.graphics.setColor(0.95, 0.75, 0.3)
  love.graphics.rectangle("fill", box.x, box.y, BOX, BOX)
  love.graphics.setColor(1, 1, 1)
end

function Game.keypressed(key)
  if key == "space" then Game.jump() end
  if key == "escape" and not Game.kit.automated then love.event.quit() end
end

function Game.gamepadpressed(_, button)
  if button == "a" then Game.jump() end
end

return Game

-- {{FOOTER}}
