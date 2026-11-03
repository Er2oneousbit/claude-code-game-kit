-- ---------------------------------------------------------------------------
-- main.lua
-- Purpose : The boot file. Hands play to the runtime shell (src/shell/app.lua: title, menus, settings, pause,
--           loading, then src/game/game.lua) and adds the kit's run modes around it: the smoke run (count frames,
--           print BOOT_OK, quit; or a --drive scenario that ends itself), the windowed capture (screenshot and
--           frame burst through a canvas), and the test run (tests/runner.lua). conf.lua parsed the command line
--           into the global KIT.
-- Usage   : love .  |  python tools/dev.py smoke [--drive menus] | test | run
-- Notes   : Keep game code out of this file: put it in src/game/ (and engine-free logic in src/core/) so the tests
--           can load it without a window. Captures render each frame into a canvas and save the canvas, because
--           reading back a window that is off-screen or covered gives undefined pixels on some drivers.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
--
-- Pseudocode
--   test mode  -> tests/runner.lua runs every tests/test_*.lua, prints the count, quits with 0/1/2
--   otherwise  -> app:load(); love.update/draw call the shell; smoke ends after KIT.frames (no --drive) or when
--                 the drive asks (app.finish_request); capture draws into a canvas and saves the last frame
--                 (--shot) or every N ms (--record)

local Log = require("src.core.log")
local TextStore = require("src.core.text_store")

local BOOT_MARKER = "BOOT_OK"

if KIT.mode == "test" then
  function love.load()
    local runner = require("tests.runner")
    love.event.quit(runner.run())
  end
  return
end

local App = require("src.shell.app")
local Version = require("src.version")
local app = App.new(KIT)
local frame, canvas, record_t, record_n = 0, nil, 0, 0

-- Writes a PNG to an absolute path (love.filesystem may only write inside the save folder). TextStore.file, not
-- io.open: io.open cannot open a path with "Í" or a curly quote on Windows.
local function save_png(image_data, path)
  local ok, err = TextStore.file.write(path, image_data:encode("png"):getString(), "wb")
  if not ok then error("cannot write " .. path .. ": " .. tostring(err), 0) end
end

-- Ends an automated run: the screenshot of the last drawn frame, the end marker, the exit code.
local function finish(marker, code)
  if canvas and KIT.shot then
    save_png(canvas:newImageData(), KIT.shot)
    print("CAPTURE_SHOT " .. KIT.shot)
  end
  print(marker)
  io.stdout:flush()
  love.event.quit(code or 0)
end

function love.load()
  io.stdout:setvbuf("line")
  Log.init({ debug = KIT.debug })
  if not KIT.headless then love.graphics.setDefaultFilter("nearest", "nearest") end   -- pixel art stays crisp
  app:load()
  if KIT.shot or KIT.record then
    canvas = love.graphics.newCanvas(love.graphics.getDimensions())
  end
  Log.info("core", BOOT_MARKER .. " " .. Version.name)
end

function love.update(dt)
  if app.finished then return end
  app:update(dt)
  frame = frame + 1
  if app.finish_request then
    app.finished = true
    finish(app.finish_request.marker, app.finish_request.code)
    return
  end
  if KIT.mode == "smoke" and not KIT.drive and frame >= KIT.frames then
    app.finished = true
    finish("SMOKE_DONE " .. frame, 0)
    return
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
    app:draw()
    love.graphics.setCanvas()
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.draw(canvas)
  else
    app:draw()
  end
end

function love.keypressed(key, scancode, isrepeat) app:keypressed(key, scancode, isrepeat) end
function love.gamepadpressed(joystick, button) app:gamepadpressed(joystick, button) end
function love.gamepadaxis(joystick, axis, value) app:gamepadaxis(joystick, axis, value) end
function love.mousemoved() app:mousemoved() end
function love.focus(focused) app:focus(focused) end

function love.resize(w, h)
  if canvas then canvas = love.graphics.newCanvas(w, h) end
end

-- {{FOOTER}}
