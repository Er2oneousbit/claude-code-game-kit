-- ---------------------------------------------------------------------------
-- test_telemetry_golden.lua
-- Purpose : The telemetry file format (src/core/telemetry.lua) against data/golden/telemetry.json, one test per
--           case: the header, the session id and every row (time format, CSV quoting), so every engine's
--           telemetry.csv has the same columns.
-- Usage   : python tools/dev.py test     (or --filter telemetry)
-- Notes   : The expected values come from the file at test time (tools/golden_vectors.py writes it).
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Golden = require("tests.helpers.golden")
local Telemetry = require("src.core.telemetry")

local FILE = "telemetry.json"
local data = Golden.load(FILE)

local handlers = {}

function handlers.telemetry_format(case, _, where)
  if Telemetry.HEADER ~= case.header then
    error(where .. ": header expected " .. case.header .. ", got " .. Telemetry.HEADER, 0)
  end
  if Telemetry.SESSION_LENGTH ~= case.session_length then
    error(where .. ": session length expected " .. case.session_length .. ", got " .. Telemetry.SESSION_LENGTH, 0)
  end
  local n = 2
  -- the lowest and highest ids a random source can give, and some in between
  local picks = { function() return 0 end, function() return 65535 end, math.random }
  for _, rand in ipairs(picks) do
    local sid = Telemetry.new_session(rand)
    if #sid ~= case.session_length then error(where .. ": session id " .. sid .. " has the wrong length", 0) end
    for ch in sid:gmatch(".") do
      if not case.session_chars:find(ch, 1, true) then error(where .. ": session id " .. sid .. " holds " .. ch, 0) end
    end
    n = n + 1
  end
  return n
end

function handlers.telemetry_row(case, _, where)
  for i, p in ipairs(case.points) do
    local got = Telemetry.row(p[1], p[2], p[3], p[4])
    if got ~= p[5] then
      error(where .. " point " .. i .. ": expected " .. string.format("%q", p[5]) .. ", got " ..
            string.format("%q", got), 0)
    end
  end
  return #case.points
end

return Golden.suite(data, handlers, FILE)

-- {{FOOTER}}
