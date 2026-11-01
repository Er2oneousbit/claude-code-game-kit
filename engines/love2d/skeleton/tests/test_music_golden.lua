-- ---------------------------------------------------------------------------
-- test_music_golden.lua
-- Purpose : The music director (src/core/music_director.lua) against data/golden/music.json, one test per case:
--           the beat grid in samples and every scripted transition plan (quantize, loop wrap, fades, stingers,
--           synced entries), exactly (tolerance 0). The expected values come from the file at test time.
-- Usage   : python tools/dev.py test     (or --filter music)
-- Notes   : The director returns stinger / stinger_at = false (MusicDirector.NONE) where the vectors hold null; the
--           test maps false to Json.null before comparing. The kit's comparer counts null as missing, so this test
--           also checks the key sets exactly (a plan that dropped "stinger_at" fails here) and that every null in
--           the file meets the sentinel, not a number or a name.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Json = require("src.core.json")
local Golden = require("tests.helpers.golden")
local MusicDirector = require("src.core.music_director")

local FILE = "music.json"

-- A plan in the vectors' terms: the no-stinger sentinel becomes JSON null.
local function as_vector(plan)
  local out = Json.object({})
  for k, v in pairs(plan) do
    if v == MusicDirector.NONE then v = Json.null end
    out[k] = v
  end
  return out
end

-- Exact key sets (a key holding null must exist too), and null only where the file has null.
-- Returns the number of keys checked.
local function expect_keys(actual, expected, where)
  for _, k in ipairs(Json.sorted_keys(expected)) do
    if actual[k] == nil then error(where .. ": $." .. tostring(k) .. ": missing", 0) end
    if (actual[k] == Json.null) ~= (expected[k] == Json.null) then
      error(where .. ": $." .. tostring(k) .. ": expected " .. tostring(expected[k]) .. ", got " ..
            tostring(actual[k]), 0)
    end
  end
  for _, k in ipairs(Json.sorted_keys(actual)) do
    if expected[k] == nil then error(where .. ": $." .. tostring(k) .. ": unexpected key", 0) end
  end
  return #Json.sorted_keys(expected)
end

local handlers = {}

function handlers.music_grid(case, tol, where)
  local n = 0
  for i, step in ipairs(case.steps) do
    local at = where .. " step " .. i .. " (k=" .. tostring(step.k) .. " bpm=" .. tostring(step.bpm) .. ")"
    Golden.expect(MusicDirector.beat_sample(step.k, step.bpm, step.rate), step.sample, tol, at)
    n = n + 1
  end
  return n
end

function handlers.music_plan(case, tol, where)
  local n = 0
  for i, step in ipairs(case.steps) do
    local got = MusicDirector.plan(case.params, step.from, step.since, step.entry, step.to, step.now)
    local actual = as_vector(got)
    local at = where .. " step " .. i .. " (" .. step.from .. " -> " .. step.to .. " now=" .. tostring(step.now) .. ")"
    n = n + expect_keys(actual, step.expect, at)
    Golden.expect(actual, step.expect, tol, at)
  end
  return n
end

return Golden.suite(Golden.load(FILE), handlers, FILE)

-- {{FOOTER}}
