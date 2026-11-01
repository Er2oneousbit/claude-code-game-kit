-- ---------------------------------------------------------------------------
-- test_music_player.lua
-- Purpose : The music player's own mixer (src/shell/music_player.lua) sample by sample, as pure Lua: stems in sync,
--           the loop wrap on the bar grid, a switch with its fade on the planned samples, a stinger and the delayed
--           entry after it, a synced entry offset, a stem gain change on its sample, and the clamp.
-- Usage   : python tools/dev.py test     (or --filter music_player)
-- Notes   : No love.audio here: the stems are tables with SoundData's getSample / getSampleCount / getChannelCount,
--           and the output is a table with setSample, so nothing needs an audio device. The track is tiny on
--           purpose: 40 Hz at 60 BPM is a beat of 40 samples and a bar of 160, so every expected sample below can
--           be worked out by hand (the comments do). Chunks of odd sizes (7, 37, 64) prove the result does not
--           depend on where the buffer edges fall. This checks the mix, not what OpenAL plays.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local MusicPlayer = require("src.shell.music_player")
local T = {}

-- ---- Tunables ----------------------------------------------------------------
local TOL = 1e-12                        -- sums of a few doubles: exact up to rounding

-- A stand-in for SoundData: frames, channels and the sample at (frame, channel).
local function reader(frames, channels, fn)
  return {
    getSampleCount = function() return frames end,
    getChannelCount = function() return channels end,
    getSample = function(_, i, ch)
      assert(i >= 0 and i < frames, "read past the end: " .. i)
      return fn(i, ch)
    end,
  }
end

-- 40 Hz, 60 BPM, 4/4: beat = 40 samples, bar = 160.
-- a: 2 bars, loop from bar 1 -> intro [0, 160), loop [160, 320). b: 1 bar, loop [0, 160).
local function music(transitions)
  return {
    version = 1, sample_rate = 40,
    tracks = {
      a = { bpm = 60, beats_per_bar = 4, bars = 2, loop_start_bar = 1, stems = { x = "a_x", y = "a_y" } },
      b = { bpm = 60, beats_per_bar = 4, bars = 1, stems = { z = "b_z" } },
      c = { bpm = 60, beats_per_bar = 4, bars = 1, stems = { p = "c_p", q = "c_p" } },
    },
    stingers = { s = { file = "s", bars = 0.5 } },     -- half a bar = 2 beats = 80 samples before the next track
    transitions = transitions or {
      { from = "a", to = "b", quantize = "bar", fade_ms = 100 },     -- fade = floor(100 * 40 / 1000 + 0.5) = 4
      { from = "b", to = "a", quantize = "beat", stinger = "s" },
    },
    default_transition = { quantize = "bar", fade_ms = 0 },
  }
end

local function readers()
  return {
    a_x = reader(320, 1, function(i) return i / 1000 end),                        -- mono ramp: tells the position
    a_y = reader(320, 2, function(_, ch) return ch == 1 and 0.25 or -0.25 end),   -- stereo: L +0.25, R -0.25
    b_z = reader(160, 1, function(i) return 0.5 + i / 10000 end),
    c_p = reader(160, 2, function(_, ch) return ch == 1 and 0.75 or -0.75 end),
    s = reader(50, 1, function() return 0.125 end),                               -- 50 samples long
  }
end

-- Mixes until the clock reaches `upto`, in chunks of `chunk`, into out.l[t] / out.r[t] (t = clock sample).
local function render(player, upto, chunk, out)
  out = out or { l = {}, r = {} }
  while player:now() < upto do
    local n = math.min(chunk, upto - player:now())
    local base = player:now()
    local sink = { setSample = function(_, i, ch, v)
      if ch == 1 then out.l[base + i] = v else out.r[base + i] = v end
    end }
    player:mix(sink, n)
  end
  return out
end

local function expect_range(out, from, to, fn, what)
  for t = from, to - 1 do
    local l, r = fn(t)
    A.near(out.l[t], l, TOL, what .. " L at sample " .. t)
    A.near(out.r[t], r, TOL, what .. " R at sample " .. t)
  end
end

function T.test_stems_in_sync_and_loop_wrap()
  local m = MusicPlayer.new(music(), readers())
  m:start("a")
  local out = render(m, 400, 64)
  -- position: the intro once, then [160, 320) again and again
  expect_range(out, 0, 400, function(t)
    local p = t < 320 and t or 160 + (t - 160) % 160
    return p / 1000 + 0.25, p / 1000 - 0.25
  end, "a")
  -- by hand: sample 320 is the loop start again (position 160): 0.16 + 0.25 and 0.16 - 0.25
  A.near(out.l[320], 0.41, TOL, "wrap L")
  A.near(out.r[320], -0.09, TOL, "wrap R")
  A.near(out.l[319], 0.569, TOL, "last loop sample L")
end

function T.test_switch_and_fade_on_the_planned_samples()
  local m = MusicPlayer.new(music(), readers())
  m:start("a")
  local out = render(m, 100, 64)
  local p = m:request("b")
  -- asked at 100: the next bar is 160; the fade is 4 samples
  A.eq(p.switch_at, 160, "switch_at")
  A.eq(p.from_stop_at, 164, "from_stop_at")
  A.eq(p.to_start_at, 160, "to_start_at")
  A.eq(p.to_offset, 0, "to_offset")
  A.eq(p.stinger, false, "no stinger")
  render(m, 200, 7, out)
  expect_range(out, 0, 160, function(t) return t / 1000 + 0.25, t / 1000 - 0.25 end, "a before the switch")
  expect_range(out, 160, 164, function(t)
    local g = (164 - t) / 4                                     -- 1 at switch_at, down to 0 at from_stop_at
    local b = 0.5 + (t - 160) / 10000
    return (t / 1000 + 0.25) * g + b, (t / 1000 - 0.25) * g + b
  end, "the fade")
  expect_range(out, 164, 200, function(t) local b = 0.5 + (t - 160) / 10000; return b, b end, "b alone")
  -- by hand: sample 161 = a at 3/4 (0.411 * 0.75 = 0.30825, -0.089 * 0.75 = -0.06675) + b's 0.5001
  A.near(out.l[161], 0.80835, TOL, "161 L")
  A.near(out.r[161], 0.43335, TOL, "161 R")
  A.eq(#m.voices, 1, "the old track is dropped after from_stop_at")
  A.eq(m:track(), "b", "current track")
end

function T.test_stinger_then_the_next_track()
  local m = MusicPlayer.new(music(), readers())
  m:start("b")
  local out = render(m, 90, 37)
  local p = m:request("a")
  -- asked at 90: the next beat is 120 (beats at 80, 120); no fade; the stinger is 80 samples of grid
  A.eq(p.switch_at, 120, "switch_at")
  A.eq(p.from_stop_at, 120, "from_stop_at")
  A.eq(p.stinger, "s", "stinger")
  A.eq(p.stinger_at, 120, "stinger_at")
  A.eq(p.to_start_at, 200, "to_start_at")
  render(m, 260, 37, out)
  expect_range(out, 0, 120, function(t) local b = 0.5 + t / 10000; return b, b end, "b")
  expect_range(out, 120, 170, function() return 0.125, 0.125 end, "the stinger (50 samples)")
  expect_range(out, 170, 200, function() return 0, 0 end, "silence until the next track enters")
  expect_range(out, 200, 260, function(t)
    local q = t - 200
    return q / 1000 + 0.25, q / 1000 - 0.25
  end, "a from its start")
end

function T.test_synced_entry_offset()
  local m = MusicPlayer.new(music({ { from = "a", to = "b", quantize = "beat", sync = true } }), readers())
  m:start("a")
  local out = render(m, 50, 64)
  local p = m:request("b")
  -- asked at 50: the next beat is 80, which is 80 samples into bar 0, so b enters at its own sample 80
  A.eq(p.switch_at, 80, "switch_at")
  A.eq(p.to_offset, 80, "to_offset")
  render(m, 120, 7, out)
  expect_range(out, 50, 80, function(t) return t / 1000 + 0.25, t / 1000 - 0.25 end, "a")
  expect_range(out, 80, 120, function(t) local b = 0.5 + t / 10000; return b, b end, "b in step with the bar")
  A.near(out.l[80], 0.508, TOL, "80 L")
end

function T.test_stem_gain_on_its_sample()
  local m = MusicPlayer.new(music(), readers())
  m:start("a")
  m:set_stem_gain("a", "y", 0, 50)
  local out = render(m, 100, 32)                                -- 50 falls inside the second chunk
  expect_range(out, 0, 50, function(t) return t / 1000 + 0.25, t / 1000 - 0.25 end, "both stems")
  expect_range(out, 50, 100, function(t) return t / 1000, t / 1000 end, "stem y off from 50")
  A.raises(function() m:set_stem_gain("a", "nope", 1) end)
end

function T.test_mix_clamps()
  local m = MusicPlayer.new(music(), readers())
  m:start("c")                                                  -- two stems of 0.75 / -0.75: sums of 1.5
  local out = render(m, 10, 64)
  expect_range(out, 0, 10, function() return 1, -1 end, "clamped")
end

function T.test_files_and_bad_input()
  local files = MusicPlayer.files(music())
  A.eq(table.concat(files, ","), "a_x,a_y,b_z,c_p,s", "every file once, sorted by track and stem")
  A.raises(function() MusicPlayer.new({ tracks = {} }) end)
  local m = MusicPlayer.new(music(), readers())
  A.raises(function() m:start("nope") end)
  A.eq(m:request("a"), nil, "the first request starts the track")
  A.eq(m:request("a"), nil, "the same track again: nothing")
end

return T

-- {{FOOTER}}
