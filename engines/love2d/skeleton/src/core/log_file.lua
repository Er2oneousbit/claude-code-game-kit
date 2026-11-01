-- ---------------------------------------------------------------------------
-- log_file.lua
-- Purpose : The game's log on disk: logs/game.log in the user-data folder, the version and a timestamp on the
--           first line, the previous LOG_KEEP runs kept as logs/game.1.log (newest) .. game.5.log, and the last
--           lines in memory for crash files and bug reports.
-- Usage   : local LogFile = require("src.core.log_file")
--           local log_file = LogFile.open(store, { name = "My Game", version = "0.1.0" })
--           Log.on_line = function(line) log_file:write(line) end      -- src/core/log.lua copies every line
--           log_file:tail(50) -> the last 50 lines as one string
-- Notes   : No love.* calls (the store does the file work, src/core/text_store.lua). Every line is appended at
--           once, so a crash loses nothing that was logged. A failing disk never stops the game: write errors
--           turn the file off and are reported once through on_error.
--
-- Pseudocode:
--   open: game.(KEEP-1).log -> game.KEEP.log ... game.log -> game.1.log; new game.log with the header line
--   write(line): append line to the file and to a ring of TAIL_LINES
--   ring: ring[first..last] are the kept lines; first and last are counted, never #ring (the length operator is
--   undefined on a table whose low indices were set to nil; LuaJIT gave 0 there after a few hundred lines)
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local LogFile = {}
LogFile.__index = LogFile

-- ---- Tunables ----------------------------------------------------------------
LogFile.FILE = "logs/game.log"
LogFile.KEEP = 5                         -- older logs kept: logs/game.1.log (newest) .. logs/game.5.log
LogFile.TAIL_LINES = 200                 -- lines kept in memory for crash files and bug reports

local function rotated(i) return "logs/game." .. i .. ".log" end

function LogFile.rotate(store)
  store:remove(rotated(LogFile.KEEP))
  for i = LogFile.KEEP - 1, 1, -1 do
    if store:exists(rotated(i)) then store:rename(rotated(i), rotated(i + 1)) end
  end
  if store:exists(LogFile.FILE) then store:rename(LogFile.FILE, rotated(1)) end
end

-- info: { name, version, extra } -> the first line "<name> <version> started <ISO time> <extra>"
function LogFile.open(store, info, on_error)
  local self = setmetatable({ store = store, ring = {}, first = 1, last = 0, enabled = true,
                              on_error = on_error }, LogFile)
  info = info or {}
  self.header = string.format("%s %s started %s%s", info.name or "game", info.version or "0.0.0",
                              os.date("!%Y-%m-%dT%H:%M:%SZ"), info.extra and (" " .. info.extra) or "")
  local ok, err = pcall(function()
    LogFile.rotate(store)
    store:write(LogFile.FILE, self.header .. "\n")
  end)
  if not ok then self:fail(err) end
  self:remember(self.header)
  return self
end

function LogFile:fail(err)
  self.enabled = false
  if self.on_error then self.on_error("log file off: " .. tostring(err)) end
end

function LogFile:remember(line)
  self.last = self.last + 1
  self.ring[self.last] = line
  if self.last - self.first + 1 > LogFile.TAIL_LINES then
    self.ring[self.first] = nil
    self.first = self.first + 1
  end
end

function LogFile:write(line)
  self:remember(line)
  if not self.enabled then return end
  local ok, err = pcall(self.store.append, self.store, LogFile.FILE, line .. "\n")
  if not ok then self:fail(err) end
end

function LogFile:tail(n)
  local out = {}
  local from = math.max(self.first, self.last - (n or LogFile.TAIL_LINES) + 1)
  for i = from, self.last do out[#out + 1] = self.ring[i] end
  return table.concat(out, "\n")
end

function LogFile:path() return self.store:path(LogFile.FILE) end

return LogFile

-- {{FOOTER}}
