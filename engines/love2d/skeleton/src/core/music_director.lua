-- ---------------------------------------------------------------------------
-- music_director.lua
-- Purpose : The adaptive-music rules of data/music.json with no love.* in them (the tests run them against
--           data/golden/music.json): the beat grid in samples, loop points, where playback is, the next beat / bar /
--           phrase / loop end, which transition rule applies, and the plan for a change (when, fade, stinger, entry).
-- Usage   : local MusicDirector = require("src.core.music_director")
--           local p = MusicDirector.plan(music_json, "explore", since, entry, "combat", now)   -- all in samples
--           p.switch_at, p.from_stop_at, p.fade, p.to_start_at, p.to_offset
--           p.stinger, p.stinger_at                -- false (MusicDirector.NONE) when the rule has no stinger
--           MusicDirector.loop_points(track, rate) -- loop start, loop end (the loop plays [start, end))
-- Notes   : A port of tools/audio/wavesmith/music.py (the reference): every value is a whole number of samples and
--           must match the golden file exactly (tolerance 0). Beat k starts at floor(k * 60 * rate / bpm + 0.5); no
--           round() anywhere, halves round up as in every other engine. Lua numbers are doubles: k * 60 * rate stays
--           an exact integer below 2^53 for any sane track (k = 10^6 beats at 192 kHz is about 1.2e13), and the one
--           division after it is the same IEEE division Python makes. Remainders go through mod() (math.fmod, exact)
--           as in audio_director.lua. stinger and stinger_at are false (MusicDirector.NONE) where the vectors hold
--           null, so the keys always exist; the golden test maps false to Json.null. A JSON null inside a rule
--           (Json.null, a truthy table here) counts as "not set", as None does in the reference.
--
-- Pseudocode:
--   beat_sample(k) = floor(k * 60 * rate / bpm + 0.5); bar b starts at beat_sample(b * beats_per_bar)
--   position(track, since, now, entry): p = now - since + entry; past the loop end -> wrap into the loop
--   plan(from, to, now): rule (exact pair, from *, to *, default) -> next boundary of its quantize at or after p
--                        -> switch_at = now + (boundary - p); stinger? the target enters after the stinger's bars
--                        -> else the target enters at offset 0, or at the same place in the bar with "sync"
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Json = require("src.core.json")

local MusicDirector = {}

-- ---- Tunables ----------------------------------------------------------------
MusicDirector.NONE = false               -- plan.stinger / plan.stinger_at without a stinger (null in the vectors)
MusicDirector.QUANTIZE = { immediate = true, beat = true, bar = true, phrase = true, loop_end = true }
local DEFAULT_RULE = { quantize = "bar", fade_ms = 0, sync = false }
local DEFAULT_BEATS_PER_BAR = 4
local DEFAULT_PHRASE_BARS = 4

-- floor modulo for negative values too; math.fmod is exact for doubles (Lua's % divides first)
local function mod(a, m)
  local r = math.fmod(a, m)
  if r < 0 then r = r + m end
  return r
end

-- JSON null -> nil, so a field that holds null behaves like a missing one
local function opt(v)
  if v == Json.null then return nil end
  return v
end

-- Python's truth test for a scalar rule field (0 and "" are false there, true in Lua)
local function truthy(v)
  return v ~= nil and v ~= false and v ~= 0 and v ~= ""
end

local function bpb_of(track)
  return opt(track.beats_per_bar) or DEFAULT_BEATS_PER_BAR
end

-- ---- The grid ------------------------------------------------------------------
-- First sample of beat k (k may be any whole number, negative too).
function MusicDirector.beat_sample(k, bpm, rate)
  return math.floor(k * 60 * rate / bpm + 0.5)
end

function MusicDirector.bar_sample(b, track, rate)
  return MusicDirector.beat_sample(b * bpb_of(track), track.bpm, rate)
end

-- The bar that contains `sample`: a float estimate, then corrected on the rounded grid so it is exact.
function MusicDirector.bar_index_at(sample, track, rate)
  local b = math.floor(sample * track.bpm / (60 * rate * bpb_of(track)))
  while MusicDirector.bar_sample(b + 1, track, rate) <= sample do b = b + 1 end
  while b > 0 and MusicDirector.bar_sample(b, track, rate) > sample do b = b - 1 end
  return b
end

-- Loop start and loop end in samples: the loop plays [start, end) forever; bars before loop_start_bar are an
-- intro that plays once.
function MusicDirector.loop_points(track, rate)
  return MusicDirector.bar_sample(opt(track.loop_start_bar) or 0, track, rate),
         MusicDirector.bar_sample(track.bars, track, rate)
end

-- Where in the track (samples from its start) playback is at `now`, when it started at `since` from `entry`.
function MusicDirector.position(track, rate, since, now, entry)
  local p = now - since + (entry or 0)
  local start, stop = MusicDirector.loop_points(track, rate)
  if p >= stop then p = start + mod(p - start, stop - start) end
  return p
end

-- The first boundary of the given kind at or after track position p (never past the loop end).
function MusicDirector.next_boundary(track, rate, p, quantize, phrase_bars)
  if quantize == "immediate" then return p end
  local _, stop = MusicDirector.loop_points(track, rate)
  if quantize == "loop_end" then return stop end
  local bpb = bpb_of(track)
  local step
  if quantize == "beat" then step = 1
  elseif quantize == "bar" then step = bpb
  elseif quantize == "phrase" then step = bpb * (phrase_bars or DEFAULT_PHRASE_BARS)
  else error("music: unknown quantize '" .. tostring(quantize) .. "'", 0) end
  -- the beat at or after p, then up to the next multiple of step (counted from the track's first beat)
  local k = math.floor(p * track.bpm / (60 * rate))
  while MusicDirector.beat_sample(k, track.bpm, rate) < p do k = k + 1 end
  while mod(k, step) ~= 0 do k = k + 1 end
  return math.min(MusicDirector.beat_sample(k, track.bpm, rate), stop)
end

-- Built-in default, then the file's default_transition, then the rule itself (later wins; a null clears a field).
local function merged(...)
  local out = {}
  for i = 1, select("#", ...) do
    local layer = select(i, ...)
    if type(layer) == "table" and layer ~= Json.null then
      for k, v in pairs(layer) do out[k] = opt(v) end
    end
  end
  return out
end

-- The transition rule: exact pair, then from "*", then to "*", then the file's default, then the built-in one.
function MusicDirector.rule_for(data, from, to)
  local rules = opt(data.transitions) or {}
  local default = opt(data.default_transition)
  for _, want in ipairs({ { from, to }, { "*", to }, { from, "*" } }) do
    for _, r in ipairs(rules) do
      if r.from == want[1] and r.to == want[2] then return merged(DEFAULT_RULE, default, r) end
    end
  end
  return merged(DEFAULT_RULE, default)
end

-- When and how to change from track `from` (playing since sample `since` from offset `entry`) to `to`, asked at
-- sample `now`. Returns { switch_at, from_stop_at, fade, to_start_at, to_offset, stinger, stinger_at }.
function MusicDirector.plan(data, from, since, entry, to, now)
  local rate = data.sample_rate
  local a, b = data.tracks[from], data.tracks[to]
  if not a then error("music: unknown track '" .. tostring(from) .. "'", 0) end
  if not b then error("music: unknown track '" .. tostring(to) .. "'", 0) end
  local rule = MusicDirector.rule_for(data, from, to)
  local p = MusicDirector.position(a, rate, since, now, entry)
  local boundary = MusicDirector.next_boundary(a, rate, p, rule.quantize or "bar", rule.phrase_bars)
  local switch_at = now + (boundary - p)
  local fade = math.floor((rule.fade_ms or 0) * rate / 1000 + 0.5)
  local out = { switch_at = switch_at, from_stop_at = switch_at + fade, fade = fade, to_offset = 0,
                to_start_at = switch_at, stinger = MusicDirector.NONE, stinger_at = MusicDirector.NONE }
  if rule.stinger ~= nil then out.stinger = rule.stinger end
  if truthy(rule.stinger) then
    local st = (opt(data.stingers) or {})[rule.stinger]
    if not st then error("music: unknown stinger '" .. tostring(rule.stinger) .. "'", 0) end
    out.stinger_at = switch_at
    out.to_start_at = switch_at + MusicDirector.beat_sample(st.bars * bpb_of(b), b.bpm, rate)
  elseif truthy(rule.sync) and a.bpm == b.bpm and bpb_of(a) == bpb_of(b) then
    -- keep the beat: enter the target at the same place in its bar (bar boundaries are where the grids line up)
    out.to_offset = boundary - MusicDirector.bar_sample(MusicDirector.bar_index_at(boundary, a, rate), a, rate)
  end
  return out
end

return MusicDirector

-- {{FOOTER}}
