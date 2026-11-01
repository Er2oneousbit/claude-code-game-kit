-- ---------------------------------------------------------------------------
-- conf.lua
-- Purpose : LÖVE configuration, read before main.lua. Also decides the run mode (play, smoke, headless smoke,
--           capture, test) from the command line and installs the error handler, because only code here runs
--           early enough to catch a syntax error in main.lua.
-- Usage   : love .                         play
--           lovec . --smoke 120            what `python tools/dev.py smoke` runs (a small window off-screen)
--           lovec . --smoke 120 --headless no window at all (logic only; see docs/ENGINE.md gotchas)
--           lovec . --test                 the unit tests in tests/ (`python tools/dev.py test`)
-- Notes   : LÖVE's own error screen waits for a key press, even with no window, so a smoke or test run that hit an
--           error would hang forever. In those modes the handler below prints "[error] ..." and exits 1 instead.
--           In play mode it writes a crash file (src/core/crash.lua, when present) and then shows LÖVE's screen.
--           Window size: 640x360 is the kit's pixel-art base (it divides 720p, 1080p, 1440p and 4K evenly).
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
--
-- Pseudocode
--   KIT = parsed command line (mode, frames, capture paths, data dir, locale, drive scenario)
--   love.errorhandler: crash file (best effort) -> smoke/test: print + exit 1 ; play: LÖVE's default screen
--   love.conf: title, identity, size; headless/test: no window; smoke/capture: small, borderless, off-screen

local GAME_TITLE = "{{GAME_NAME}}"
local IDENTITY = "{{GAME_SLUG}}"         -- the save folder name (love.filesystem.getSaveDirectory())
local BASE_W, BASE_H = 640, 360          -- pixel-art base resolution
local WINDOW_SCALE = 2                   -- play window = base x 2
local OFFSCREEN = -20000                 -- smoke window position: renders, but nobody sees it flash
-- The OLDEST LÖVE the game runs on (dev.py MIN_LOVE). A LÖVE that does not list this version as compatible shows a
-- modal "Compatibility Warning" box, which hangs automated runs: 11.5 accepts "11.4", 11.4 does not accept "11.5".
local LOVE_VERSION = "11.4"

-- The command line, parsed once for conf.lua, main.lua and the shell. Unknown options are left for the game.
local function parse(args)
  local k = { mode = "play", frames = 120, headless = false, shot = nil, record = nil, every_ms = 66,
              data_dir = nil, locale = nil, drive = nil, debug = false, rest = {} }
  local i = 1
  while args and i <= #args do
    local a = args[i]
    local function value() i = i + 1; return args[i] end
    if a == "--smoke" then k.mode = "smoke"; k.frames = tonumber(args[i + 1]) or k.frames
      if tonumber(args[i + 1]) then i = i + 1 end
    elseif a == "--test" then k.mode = "test"
    elseif a == "--headless" then k.headless = true
    elseif a == "--shot" then k.shot = value()
    elseif a == "--record" then k.record = value()
    elseif a == "--every-ms" then k.every_ms = tonumber(value()) or k.every_ms
    elseif a == "--data-dir" then k.data_dir = value()
    elseif a == "--locale" then k.locale = value()
    elseif a == "--drive" then k.drive = value()
    elseif a == "--debug" then k.debug = true
    else k.rest[#k.rest + 1] = a end
    i = i + 1
  end
  k.automated = k.mode ~= "play"
  return k
end

KIT = parse(arg)

local default_handler = love.errorhandler or love.errhand

love.errorhandler = function(msg)
  msg = tostring(msg)
  local trace = debug.traceback("", 2)
  local ok, crash = pcall(require, "src.core.crash")    -- absent in a bare project: then no crash file
  if ok and type(crash) == "table" and crash.write then
    local wrote, path = pcall(crash.write, msg, trace)
    if wrote and path and KIT.automated then
      io.stdout:write("CRASH_WRITTEN " .. tostring(path) .. "\n")
    end
  end
  if KIT.automated then
    io.stderr:write("[error] " .. msg .. "\n" .. trace .. "\n")
    io.stderr:flush()
    io.stdout:flush()
    os.exit(1)
  end
  return default_handler(msg)
end

function love.conf(t)
  t.identity = IDENTITY
  t.version = LOVE_VERSION
  t.console = false
  t.window.title = GAME_TITLE
  t.window.width = BASE_W * WINDOW_SCALE
  t.window.height = BASE_H * WINDOW_SCALE
  t.window.resizable = true
  t.window.vsync = 1
  if KIT.mode == "test" or KIT.headless then
    t.window = false                     -- no window: logic only (love.graphics cannot create anything)
    t.modules.audio = false
    t.modules.sound = false
  elseif KIT.mode == "smoke" then
    t.window.width, t.window.height = BASE_W, BASE_H
    t.window.borderless = true
    t.window.resizable = false
    -- a plain smoke runs as fast as it can (it counts frames, not seconds); a capture runs at real speed, so a
    -- recorded burst plays back like the game
    t.window.vsync = (KIT.shot or KIT.record) and 1 or 0
    t.window.x, t.window.y = OFFSCREEN, OFFSCREEN
  end
end

-- {{FOOTER}}
