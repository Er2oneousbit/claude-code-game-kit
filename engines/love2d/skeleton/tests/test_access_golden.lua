-- ---------------------------------------------------------------------------
-- test_access_golden.lua
-- Purpose : The audio accessibility rules (src/core/audio_access.lua) against data/golden/access.json, one test
--           per case: the slider gain every bus gets (nested trees, cycles, bad values) and the direction and arrow
--           every caption point gets. The expected values come from the file at test time.
-- Usage   : python tools/dev.py test     (or --filter access)
-- Notes   : The golden sliders hold a string ("loud") and a null (Json.null here): both must count as 1, so they
--           go into user_bus_gains exactly as decoded. The gain key sets are checked exactly (the comparer alone
--           would let a missing bus pass as null). The file's "arrows" list must equal AudioAccess.ARROWS, byte
--           for byte (UTF-8).
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Json = require("src.core.json")
local Golden = require("tests.helpers.golden")
local AudioAccess = require("src.core.audio_access")

local FILE = "access.json"
local data = Golden.load(FILE)

-- Exact key sets. Returns the number of keys checked.
local function expect_keys(actual, expected, where)
  for _, k in ipairs(Json.sorted_keys(expected)) do
    if actual[k] == nil then error(where .. ": $." .. tostring(k) .. ": missing", 0) end
  end
  for _, k in ipairs(Json.sorted_keys(actual)) do
    if expected[k] == nil then error(where .. ": $." .. tostring(k) .. ": unexpected key", 0) end
  end
  return #Json.sorted_keys(expected)
end

local handlers = {}

function handlers.access_gains(case, tol, where)
  local n = 0
  for i, step in ipairs(case.steps) do
    local at = where .. " step " .. i
    local actual = Json.object(AudioAccess.user_bus_gains(step.buses, step.sliders))
    n = n + expect_keys(actual, step.expect, at)
    Golden.expect(actual, step.expect, tol, at)
  end
  return n
end

function handlers.access_arrow(case, tol, where)
  local n = 0
  for i, step in ipairs(case.steps) do
    local at = where .. " step " .. i .. " (dx=" .. tostring(step.dx) .. " dy=" .. tostring(step.dy) .. ")"
    local dir = AudioAccess.caption_direction(step.dx, step.dy, step.half_w, step.half_h)
    if dir ~= step.dir then error(at .. ": dir expected " .. tostring(step.dir) .. ", got " .. tostring(dir), 0) end
    local arrow = AudioAccess.caption_arrow(step.dx, step.dy, step.half_w, step.half_h)
    if arrow ~= step.arrow then
      error(at .. ": arrow expected " .. string.format("%q", step.arrow) .. ", got " .. string.format("%q", arrow), 0)
    end
    n = n + 2
  end
  return n
end

local suite = Golden.suite(data, handlers, FILE)

-- the arrow table itself, so a typo in a direction the points do not reach still fails
function suite.test_arrows_table()
  if not Json.is_array(data.arrows) then error(FILE .. ": no arrows list", 0) end
  if #data.arrows ~= #AudioAccess.ARROWS then
    error("arrows: expected " .. #data.arrows .. ", got " .. #AudioAccess.ARROWS, 0)
  end
  for i, want in ipairs(data.arrows) do
    if AudioAccess.ARROWS[i] ~= want then
      error("arrows[" .. (i - 1) .. "]: expected " .. string.format("%q", want) .. ", got " ..
            string.format("%q", tostring(AudioAccess.ARROWS[i])), 0)
    end
  end
end

return suite

-- {{FOOTER}}
