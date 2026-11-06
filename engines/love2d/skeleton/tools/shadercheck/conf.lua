-- ---------------------------------------------------------------------------
-- tools/shadercheck/conf.lua
-- Purpose : Configuration of the shader checker that `python tools/dev.py check` and `smoke --shaders` run (a
--           separate tiny LÖVE program, so a broken game cannot stop it). A small borderless window off-screen:
--           LÖVE compiles and draws shaders only with a window. No audio.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local OFFSCREEN = -20000                 -- renders, but nobody sees it flash (as the game's smoke window)

love.errorhandler = function(msg)
  io.stderr:write("[error] shader checker: " .. tostring(msg) .. "\n")
  io.stderr:flush()
  os.exit(2)
end

function love.conf(t)
  t.identity = "shadercheck"
  t.version = "11.4"
  t.modules.audio = false
  t.modules.sound = false
  t.modules.joystick = false
  t.window.title = "shadercheck"
  t.window.width, t.window.height = 64, 64
  t.window.borderless = true
  t.window.x, t.window.y = OFFSCREEN, OFFSCREEN
  t.window.vsync = 0
end
