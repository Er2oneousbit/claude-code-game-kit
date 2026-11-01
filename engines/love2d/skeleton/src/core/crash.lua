-- ---------------------------------------------------------------------------
-- crash.lua
-- Purpose : Writes a crash report when the game hits an unhandled error: crashes/crash_<timestamp>.txt in the
--           user-data folder with the version, the seed (if any), the error, the traceback and the log tail.
--           conf.lua's love.errorhandler calls Crash.write(msg, trace) and prints CRASH_WRITTEN <path> in
--           automated runs (dev.py smoke echoes it).
-- Usage   : local Crash = require("src.core.crash")
--           Crash.configure({ store = store, name = "My Game", version = "0.1.0", seed = 7,
--                             tail = function() return log_file:tail(50) end })   -- the shell does this at boot
--           local path = Crash.write("boom", debug.traceback())                   -- returns the file's path
-- Notes   : No love.graphics (an error can come from anywhere, the renderer included). Before configure() runs
--           (an error during boot) it still writes: to --data-dir when given, else the save folder. Never raises:
--           a crash report must not hide the crash.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Crash = {}

-- ---- Tunables ----------------------------------------------------------------
Crash.DIR = "crashes/"
local TAIL_LINES = 60
local MAX_SAME_SECOND = 50               -- crash_<ts>_2.txt ... when several crashes share a second

local config = {}

function Crash.configure(options)
  for k, v in pairs(options) do config[k] = v end
end

local function default_store()
  local TextStore = require("src.core.text_store")
  return TextStore.for_run(KIT and KIT.data_dir)
end

local function version_info()
  if config.version then return config.name or "game", config.version end
  local ok, v = pcall(require, "src.version")
  if ok and type(v) == "table" then return v.name or "game", v.version or "0.0.0" end
  return "game", "unknown"
end

-- The report's text (separate, so tests can check it without a file).
function Crash.report(msg, trace)
  local name, version = version_info()
  local lines = {
    name .. " crash report",
    "version: " .. tostring(version),
    "time: " .. os.date("!%Y-%m-%dT%H:%M:%SZ"),
    "seed: " .. (config.seed ~= nil and tostring(config.seed) or "none"),
  }
  if love and love.getVersion then
    local ok, major, minor, rev = pcall(love.getVersion)
    if ok then lines[#lines + 1] = string.format("love: %s.%s.%s", major, minor, rev) end
  end
  if love and love.system and love.system.getOS then
    local ok, os_name = pcall(love.system.getOS)
    if ok then lines[#lines + 1] = "os: " .. tostring(os_name) end
  end
  lines[#lines + 1] = ""
  lines[#lines + 1] = "error: " .. tostring(msg)
  lines[#lines + 1] = ""
  lines[#lines + 1] = "traceback:" .. tostring(trace or "")
  lines[#lines + 1] = ""
  lines[#lines + 1] = "log tail:"
  local tail = ""
  if config.tail then
    local ok, text = pcall(config.tail, TAIL_LINES)
    if ok and text then tail = text end
  end
  lines[#lines + 1] = tail ~= "" and tail or "(no log lines)"
  return table.concat(lines, "\n") .. "\n"
end

-- Writes the report; returns its path, or nil and the reason.
function Crash.write(msg, trace)
  local ok, result = pcall(function()
    local store = config.store or default_store()
    local stamp = os.date("%Y%m%d_%H%M%S")
    local name = Crash.DIR .. "crash_" .. stamp .. ".txt"
    local n = 1
    while store:exists(name) and n < MAX_SAME_SECOND do
      n = n + 1
      name = Crash.DIR .. "crash_" .. stamp .. "_" .. n .. ".txt"
    end
    store:write(name, Crash.report(msg, trace))
    return store:path(name)
  end)
  if ok then return result end
  return nil, result
end

return Crash

-- {{FOOTER}}
