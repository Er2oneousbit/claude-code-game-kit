-- ---------------------------------------------------------------------------
-- game.lua
-- Purpose : The starter game: a box that runs and jumps (with coyote time) on a floor. Replace it with your game;
--           keep the functions the shell's play screen calls (src/shell/screens/play.lua).
-- Usage   : Game.load(kit, { app = app, save = data_or_nil })   once per play session
--           Game.update(dt)   dt is game time (the player's game_speed applied)
--           Game.draw()       in the 640x360 base (the shell scales it)
--           Game.action(name) a pressed action ("jump", "attack", ...); return true when used
--           Game.save_data()  a table the shell saves to slot 1 when the player leaves (optional)
-- Notes   : Creates graphics only in draw (and draw never runs headless), so `dev.py smoke --headless` still boots.
--           Input comes as actions from the player's bindings, not raw keys: rebinding works without changes
--           here. Held actions: ctx.app.input:is_down("move_left"). This file is a TEMPLATE: replace it.
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
local box, coyote, runs

function Game.load(kit, ctx)
  Game.kit = kit
  box = { x = 100, y = FLOOR_Y - BOX, vy = 0, dir = 1 }
  coyote = CoyoteTimer.new(COYOTE_S)
  local save = ctx and ctx.save or {}
  runs = (tonumber(save.runs) or 0) + 1
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

function Game.action(name)
  if name == "jump" then Game.jump() return true end
  return false
end

function Game.save_data()
  return { runs = runs, level = 1, health = 3 }
end

function Game.draw()
  love.graphics.clear(0.08, 0.09, 0.12)
  love.graphics.setColor(0.25, 0.27, 0.32)
  love.graphics.rectangle("fill", 0, FLOOR_Y, 640, 360 - FLOOR_Y)
  love.graphics.setColor(0.95, 0.75, 0.3)
  love.graphics.rectangle("fill", box.x, box.y, BOX, BOX)
  love.graphics.setColor(1, 1, 1)
end

return Game

-- {{FOOTER}}
