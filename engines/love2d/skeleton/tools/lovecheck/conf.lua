-- ---------------------------------------------------------------------------
-- tools/lovecheck/conf.lua
-- Purpose : Configuration of the syntax checker that `python tools/dev.py check` runs (a separate tiny LÖVE
--           program, so a broken conf.lua or main.lua in the game cannot stop it). No window, no audio.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
love.errorhandler = function(msg)
  io.stderr:write("[error] checker: " .. tostring(msg) .. "\n")
  io.stderr:flush()
  os.exit(2)
end

function love.conf(t)
  t.identity = "lovecheck"
  t.window = false
  t.modules.audio = false
  t.modules.sound = false
  t.modules.graphics = false
end
