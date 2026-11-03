-- ---------------------------------------------------------------------------
-- test_dialogue_input.lua
-- Purpose : The subtitle data (data/dialogue/sample.built.json through src/core/dialogue.lua) and the input
--           name mapping (src/core/input_map.lua).
-- Usage   : python tools/dev.py test     (or --filter dialogue)
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local Json = require("src.core.json")
local Dialogue = require("src.core.dialogue")
local InputMap = require("src.core.input_map")
local Bindings = require("src.core.bindings")
local Settings = require("src.core.settings")
local T = {}

local function db()
  return Dialogue.parse(Json.decode(love.filesystem.read("data/dialogue/sample.built.json")))
end

function T.test_sample_follows_the_schema()
  local d = db()
  local line = d.lines["guide.welcome"]
  A.truthy(line, "guide.welcome")
  local _, chars = line.text:gsub("[^\128-\191]", "")
  A.eq(#line.reveal, chars, "one reveal entry per character")
  for i = 2, #line.reveal do A.truthy(line.reveal[i].t >= line.reveal[i - 1].t, "reveal times never decrease") end
  A.truthy(d.captions.box_hit, "a caption")
end

function T.test_typewriter_and_cues()
  local line = db().lines["guide.welcome"]
  A.eq(Dialogue.revealed(line, 0), 1)
  A.eq(Dialogue.revealed(line, 100), #line.text)
  A.eq(Dialogue.cue_at(line, 0.5)[1], line.cues[1].lines[1])
  A.eq(Dialogue.cue_at(line, 2.0)[1], line.cues[2].lines[1])
  A.eq(Dialogue.cue_at(line, 99), nil)
end

-- a line with no reveal list and a short duration_s is fully typed before it ends, not cut at 30 cps (#162)
function T.test_typewriter_without_reveal_fits_the_duration()
  local line = { text = string.rep("x", 140), duration_s = 2 }  -- 140 characters at 30 cps would need 4.67 s
  A.eq(Dialogue.revealed(line, 1), 70)
  A.eq(Dialogue.revealed(line, line.duration_s), 140)
  A.eq(Dialogue.revealed({ text = line.text, duration_s = 10 }, 1), Dialogue.DEFAULT_CPS, "never slower than 30 cps")
  A.eq(Dialogue.revealed({ text = line.text }, 1), Dialogue.DEFAULT_CPS, "no duration_s: 30 cps")
end

function T.test_barks_need_the_setting()
  local s = Settings.defaults()
  local track = Dialogue.track(db())
  A.falsy(track:play("box.ouch", s), "barks off by default")
  s.access.subtitle_barks = true
  A.truthy(track:play("box.ouch", s))
  track:update(0.1)
  A.falsy(track:play("box.ouch", s), "cooldown")
  s.access.subtitles = false
  A.falsy(Dialogue.allowed(db().lines["guide.welcome"], s), "subtitles off hides lines too")
end

function T.test_priority_and_interrupts()
  local s = Settings.defaults()
  s.access.subtitle_barks = true
  local track = Dialogue.track(db())
  A.truthy(track:play("guide.welcome", s))
  A.falsy(track:play("box.ouch", s), "a never-interrupt bark waits (dropped)")
  track:update(10)
  A.eq(track:current(), nil, "the line ended")
end

function T.test_input_names()
  A.eq(InputMap.from_key("return"), "key:enter")
  A.eq(InputMap.from_key("space"), "key:space")
  A.eq(InputMap.from_button("a"), "pad:south")
  A.eq(InputMap.from_button("start"), "pad:start")
  A.same(InputMap.love_keys("key:enter"), { "return", "kpenter" })
  A.eq(InputMap.love_button("pad:dpad_up"), "dpup")
  A.same(InputMap.actions_for(Bindings.defaults(), "key:escape"), { "pause", "ui_cancel" })
  A.eq(InputMap.device_of_pad("PS5 Controller"), "pad_playstation")
  A.eq(InputMap.device_of_pad("Xbox Series X Controller"), "pad_xbox")
  A.eq(InputMap.device_of_pad("8BitDo"), "pad_other")
end

return T

-- {{FOOTER}}
