-- ---------------------------------------------------------------------------
-- test_access_behaviour.lua
-- Purpose : The motor and cognitive settings do what they say (#166, #167): auto_repeat repeats a held press on its
--           schedule, subtitle_hold keeps a finished line until it is dismissed.
-- Usage   : python tools/dev.py test     (or --filter access_behaviour)
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local AutoRepeat = require("src.core.auto_repeat")
local Dialogue = require("src.core.dialogue")
local Json = require("src.core.json")
local T = {}

function T.test_a_held_press_repeats_after_the_delay_then_on_the_interval()
  local rep, fired, t = AutoRepeat.new(), {}, 0
  for _ = 1, 70 do                                        -- 0.7 s held at 100 frames a second
    t = t + 0.01
    if rep:update(0.01, true) then fired[#fired + 1] = t end
  end
  A.eq(#fired, 3, "0.35 s, then every 0.15 s")
  A.near(fired[1], AutoRepeat.DELAY_S, 0.011)
  A.near(fired[2] - fired[1], AutoRepeat.INTERVAL_S, 0.011)
  A.falsy(rep:update(0.01, false), "releasing stops it")
  A.falsy(rep:update(0.2, true), "and the delay starts again")
end

local function sample_track()
  local db = Dialogue.parse(Json.decode(love.filesystem.read("data/dialogue/sample.built.json")))
  local track = Dialogue.track(db)
  return track
end

function T.test_a_held_line_waits_until_it_is_dismissed()
  local settings = { access = { subtitles = true, subtitle_barks = true, speaker_names = true } }
  local track = sample_track()
  A.truthy(track:play("guide.welcome", settings), "a sample line plays")
  track:update(30, true)
  A.truthy(track:current() ~= nil and track:holding(), "still on screen with subtitle_hold")
  track:dismiss()
  A.eq(track:current(), nil, "gone once dismissed")
  A.truthy(track:play("guide.welcome", settings))
  track:update(30, false)
  A.eq(track:current(), nil, "without the setting a line ends on its own")
end

return T

-- {{FOOTER}}
