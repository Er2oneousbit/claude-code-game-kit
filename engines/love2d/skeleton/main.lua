-- ---------------------------------------------------------------------------
-- main.lua
-- Purpose : The boot file. Hands play to src/game/game.lua and adds the kit's run modes around it: the smoke run
--           (count frames, print BOOT_OK, quit), the windowed capture (screenshot and frame burst through a canvas),
--           and the test run (tests/runner.lua). conf.lua parsed the command line into the global KIT.
-- Usage   : love .  |  python tools/dev.py smoke | test | run
-- Notes   : Keep game code out of this file: put it in src/game/ (and engine-free logic in src/core/) so the tests
--           can load it without a window. Captures render each frame into a canvas and save the canvas, because
--           reading back a window that is off-screen or covered gives undefined pixels on some drivers.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
--
-- Pseudocode
--   test mode  -> tests/runner.lua runs every tests/test_*.lua, prints the count, quits with 0/1/2
--   otherwise  -> Game.load(); love.update/draw call the game; smoke counts frames and quits after KIT.frames;
--                 capture draws into a canvas, saves the last frame (--shot) or every N ms (--record) to disk

local Log = require("src.core.log")

local BOOT_MARKER = "BOOT_OK"

if KIT.mode == "test" then
  function love.load()
    local runner = require("tests.runner")
    love.event.quit(runner.run())
  end
  return
end

local Game = require("src.game.game")
local frame, canvas, record_t, record_n = 0, nil, 0, 0

-- Writes a PNG to an absolute path (love.filesystem may only write inside the save folder).
local function save_png(image_data, path)
  local file = assert(io.open(path, "wb"), "cannot write " .. path)
  file:write(image_data:encode("png"):getString())
  file:close()
end

function love.load(args)
  io.stdout:setvbuf("line")
  Log.init({ debug = KIT.debug })
  Game.load(KIT)
  if KIT.shot or KIT.record then
    canvas = love.graphics.newCanvas(love.graphics.getDimensions())
  end
  Log.info("core", BOOT_MARKER .. " {{GAME_NAME}}")
end

function love.update(dt)
  Game.update(dt)
  frame = frame + 1
  if KIT.mode == "smoke" and frame >= KIT.frames then
    if canvas and KIT.shot then
      save_png(canvas:newImageData(), KIT.shot)
      print("CAPTURE_SHOT " .. KIT.shot)
    end
    print("SMOKE_DONE " .. frame)
    love.event.quit(0)
  end
  if canvas and KIT.record then
    record_t = record_t + dt
    if record_t * 1000 >= KIT.every_ms then
      record_t = 0
      record_n = record_n + 1
      save_png(canvas:newImageData(), string.format("%s/f%05d.png", KIT.record, record_n))
    end
  end
end

function love.draw()
  if canvas then
    love.graphics.setCanvas(canvas)
    love.graphics.clear()
    Game.draw()
    love.graphics.setCanvas()
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.draw(canvas)
  else
    Game.draw()
  end
end

function love.keypressed(key, scancode, isrepeat)
  if Game.keypressed then Game.keypressed(key, scancode, isrepeat) end
end

function love.gamepadpressed(joystick, button)
  if Game.gamepadpressed then Game.gamepadpressed(joystick, button) end
end

function love.focus(focused)
  if Game.focus then Game.focus(focused) end
end

function love.resize(w, h)
  if canvas then canvas = love.graphics.newCanvas(w, h) end
  if Game.resize then Game.resize(w, h) end
end

-- {{FOOTER}}
