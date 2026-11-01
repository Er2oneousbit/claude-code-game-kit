-- ---------------------------------------------------------------------------
-- log.lua
-- Purpose : One logging channel for the whole game: Log.info("physics", "msg"), Log.warn, Log.error, and
--           Log.debug (only with --debug). Never bare print in committed game code.
-- Usage   : local Log = require("src.core.log"); Log.init({ debug = KIT.debug }); Log.info("core", "hello")
-- Notes   : Lines go to stdout (the console build lovec.exe shows them; dev.py reads them). Log.on_line lets the
--           shell copy every line into logs/game.log. "[ERROR]" lines make `dev.py smoke` fail.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Log = { debug_enabled = false, on_line = nil }

local function emit(level, channel, msg)
  local line = string.format("[%s] %s: %s", level, channel, tostring(msg))
  print(line)
  if Log.on_line then Log.on_line(line) end
end

function Log.init(options)
  Log.debug_enabled = options and options.debug or false
end

function Log.info(channel, msg) emit("INFO", channel, msg) end
function Log.warn(channel, msg) emit("WARN", channel, msg) end
function Log.error(channel, msg) emit("ERROR", channel, msg) end
function Log.debug(channel, msg)
  if Log.debug_enabled then emit("DEBUG", channel, msg) end
end

return Log

-- {{FOOTER}}
