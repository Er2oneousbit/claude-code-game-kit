-- ---------------------------------------------------------------------------
-- test_audio_golden.lua
-- Purpose : The audio director (src/core/audio_director.lua) against data/golden/audio.json, one test per case:
--           variant picks, pitch and volume draws, voice caps, cooldowns and ducking envelopes. The expected values
--           come from the file at test time, never from this code.
-- Usage   : python tools/dev.py test     (or --filter audio)
-- Notes   : The director returns stolen = false (AudioDirector.NO_VOICE) where the vectors hold null; the test maps
--           it to Json.null before comparing. The kit's comparer counts null as missing, so this test also checks
--           the key sets exactly (a result that dropped "stolen" fails here).
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Json = require("src.core.json")
local Golden = require("tests.helpers.golden")
local AudioDirector = require("src.core.audio_director")

local FILE = "audio.json"

local function unknown_call(where, step)
  error(where .. ": unknown call '" .. tostring(step.call) .. "' (update the port and this test)", 0)
end

-- The director's result in the vectors' terms: the no-voice sentinel becomes JSON null.
local function as_vector(result)
  local out = Json.object({})
  for k, v in pairs(result) do
    if k == "stolen" and v == AudioDirector.NO_VOICE then v = Json.null end
    out[k] = v
  end
  return out
end

-- Exact key sets (a key holding null must exist too). Returns the number of keys checked.
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

function handlers.audio_director(case, tol, where)
  local director = AudioDirector.new(case.params)
  local n = 0
  for i, step in ipairs(case.steps) do
    local got
    if step.call == "play" then
      got = director:play(step.event, step.t_ms)
    elseif step.call == "duck" then
      got = director:duck(step.t_ms)
    else
      unknown_call(where, step)
    end
    local actual = as_vector(got)
    local at = where .. " step " .. i .. " (" .. step.call .. " t=" .. tostring(step.t_ms) .. ")"
    n = n + expect_keys(actual, step.expect, at)
    Golden.expect(actual, step.expect, tol, at)
  end
  return n
end

return Golden.suite(Golden.load(FILE), handlers, FILE)

-- {{FOOTER}}
