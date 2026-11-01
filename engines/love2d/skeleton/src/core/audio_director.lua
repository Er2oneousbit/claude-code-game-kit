-- ---------------------------------------------------------------------------
-- audio_director.lua
-- Purpose : Decides how each game sound plays: which file of the event (no back-to-back repeats), its pitch and
--           volume within the event's ranges, voice limits (steal the oldest or refuse), cooldowns, and how far
--           dialogue ducks the music and ambience buses. Data comes from data/audio_events.json. Matches
--           data/golden/audio.json "audio_director".
-- Usage   : local AudioDirector = require("src.core.audio_director")
--           local director = AudioDirector.new(events_json)          -- { seed?, events, ducking? }
--           local d = director:play("step_stone", now_ms)            -- d.result: "played" | "cooldown" | "capped"
--           if d.result == "played" then
--             if d.stolen then stop_voice(d.stolen) end              -- false when nothing was stolen
--             start(event.files[d.variant + 1], d.pitch_ratio, d.gain_db, d.voice)   -- variant is 0-based
--           end
--           each frame: for bus, db in pairs(director:duck(now_ms)) do set_bus_duck(bus, db) end
-- Notes   : No love.* calls: this file only decides (the tests run it without a window or audio device), the
--           game's player plays. The spec is tools/audio/wavesmith/audio_events.py; every step of data/golden/audio.json
--           must come out the same. Park-Miller stays exact in doubles (products below 2^53, no bit operations),
--           event ids are ASCII, and randomness is drawn in a fixed order (variant, pitch, volume) and never by a
--           rejected play. Calls must come in time order. variant is 0-based (as in the vectors and the other
--           engines); add 1 to index event.files. stolen is the stopped voice id, or false (AudioDirector.NO_VOICE)
--           where the vectors hold null, so the key is always present. lengths_ms per file: from the loaded
--           sources (Source:getDuration() * 1000).
--           Seeds: every remainder goes through mod() (math.fmod, exact by definition, as in shake.lua) rather
--           than Lua's %, which is a - floor(a / m) * m and leans on a rounded division. Any seed below 2^53 is
--           exact as a double (JSON numbers above that are not), and (seed mod M) * 7919 < 2^44.
--           History holds only voices on a ducking trigger bus, and duck(t) drops those that ended at or before
--           t, so a long session stays cheap (results unchanged). JSON null in an event field: the reference
--           validator rejects it (leave the field out for its default); this file does not check, and Json.null
--           is a truthy table here, so an unvalidated null would not fall back to the default.
--
-- Pseudocode:
--   play(e, t) -> drop finished voices -> cooldown? "cooldown" -> at max_voices: steal oldest or "capped"
--              -> variant by pick rule -> pitch -> volume -> new voice (ends at t + length / pitch ratio)
--   duck(t)    -> per ducking rule: walk the trigger bus's voice edges since the last call, ramp in dB
--              -> drop history voices that ended at or before t
--   ramp       -> active: towards depth_db at depth/attack per ms ; idle: back to 0 at depth/release per ms
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local AudioDirector = {}
AudioDirector.__index = AudioDirector

-- ---- Tunables ----------------------------------------------------------------
AudioDirector.DEFAULT_MAX_VOICES = 8     -- an event with no max_voices plays at most this many at once
AudioDirector.DEFAULT_PICK = "random_no_repeat"
AudioDirector.DEFAULT_STEAL = "oldest"
AudioDirector.NO_VOICE = false           -- result.stolen when nothing was stolen (null in the vectors)
local PM_M = 2147483647                  -- Park-Miller modulus (2^31 - 1)
local PM_A = 16807
local SEED_MUL = 7919                    -- mixes the global seed into each event's seed

-- floor modulo for negative values too; math.fmod is exact for doubles
local function mod(a, m)
  local r = math.fmod(a, m)
  if r < 0 then r = r + m end
  return r
end

-- ---- Random source -------------------------------------------------------------
-- Park-Miller minimal standard generator: s * 16807 < 2^53, so doubles are exact and every language agrees.
local Rng = {}
Rng.__index = Rng

function Rng.new(seed)
  local s = mod(seed, PM_M)
  if s == 0 then s = 1 end
  return setmetatable({ s = s }, Rng)
end

-- A float in [0, 1).
function Rng:next()
  self.s = mod(self.s * PM_A, PM_M)
  return (self.s - 1) / (PM_M - 1)
end

AudioDirector.Rng = Rng

-- The seed of one event's random source: a hash of its ASCII id mixed with the global seed (0 becomes 1).
function AudioDirector.event_seed(event_id, global_seed)
  local h = 0
  for i = 1, #event_id do
    h = mod(h * 31 + event_id:byte(i), PM_M)   -- ids are ASCII (validated), so byte = code point
  end
  local s = mod(h + mod(global_seed, PM_M) * SEED_MUL, PM_M)
  if s == 0 then s = 1 end
  return s
end

-- ---- Director ------------------------------------------------------------------
function AudioDirector.new(params)
  if type(params) ~= "table" or type(params.events) ~= "table" then
    error("AudioDirector.new: params.events is required (the events table of audio_events.json)", 2)
  end
  local self = setmetatable({}, AudioDirector)
  self.events = params.events
  self.ducking = params.ducking or {}
  self.seed = params.seed or 1
  self.rng = {}                          -- event id -> Rng (one stream per event: events never disturb each other)
  for name in pairs(self.events) do
    self.rng[name] = Rng.new(AudioDirector.event_seed(name, self.seed))
  end
  self.voices = {}                       -- playing voices: { id, event, bus, start, ["end"] }
  self.history = {}                      -- trigger-bus voices the ducking envelopes may still need
  self.triggers = {}                     -- set of bus names that some ducking rule listens to
  for _, rule in ipairs(self.ducking) do self.triggers[rule.trigger] = true end
  self.next_id = 1
  self.last_play = {}                    -- event id -> t of its last accepted play (cooldown)
  self.last_variant = {}                 -- event id -> 0-based index of its last file (no-repeat rules)
  self.bags = {}                         -- event id -> remaining 0-based indices of the shuffle round
  self.duck_state = {}
  for i = 1, #self.ducking do self.duck_state[i] = { gain = 0.0, t = 0.0 } end
  self.now = 0.0
  return self
end

function AudioDirector:_clock(t)
  if t < self.now then
    error(string.format("AudioDirector: calls must come in time order (%s ms after %s ms)", tostring(t),
                        tostring(self.now)), 3)
  end
  self.now = t
end

-- min(floor(r * n), n - 1): the clamp guards r * n rounding up to n (it cannot for r < 1, but every port keeps it)
local function draw_index(rng, n)
  return math.min(math.floor(rng:next() * n), n - 1)
end

-- The 0-based file index for this play, by the event's pick rule. Draws from rng only where the spec does.
function AudioDirector:_pick(name, ev, rng)
  local n = #ev.files
  local last = self.last_variant[name] or -1
  local pick = ev.pick or AudioDirector.DEFAULT_PICK
  if n == 1 then return 0 end
  if pick == "sequence" then return (last + 1) % n end
  if pick == "random" then return draw_index(rng, n) end
  if pick == "random_no_repeat" then
    if last < 0 then return draw_index(rng, n) end
    local k = math.min(math.floor(rng:next() * (n - 1)), n - 2)    -- one of the n - 1 other files
    if k >= last then return k + 1 end
    return k
  end
  -- shuffle (as in the spec, any other pick lands here; validate rejects unknown picks before a game runs):
  -- bag[1..] holds 0-based indices; an empty bag refills with Fisher-Yates
  local bag = self.bags[name] or {}
  if #bag == 0 then
    bag = {}
    for i = 1, n do bag[i] = i - 1 end
    for i = n - 1, 1, -1 do                          -- i and j are 0-based positions, as in the spec
      local j = math.min(math.floor(rng:next() * (i + 1)), i)
      bag[i + 1], bag[j + 1] = bag[j + 1], bag[i + 1]
    end
    if bag[1] == last then bag[1], bag[2] = bag[2], bag[1] end   -- never the same file twice across a refill
  end
  local idx = table.remove(bag, 1)
  self.bags[name] = bag
  return idx
end

-- One play request at t_ms. Returns { result = "cooldown" } | { result = "capped" } | the played voice (see Usage).
function AudioDirector:play(name, t)
  self:_clock(t)
  local ev = self.events[name]
  if not ev then error("AudioDirector: unknown audio event " .. tostring(name), 2) end

  -- expire voices that ended by now
  local alive = {}
  for _, v in ipairs(self.voices) do
    if v["end"] > t then alive[#alive + 1] = v end
  end
  self.voices = alive

  -- cooldown: a rejected play draws nothing
  local cooldown = ev.cooldown_ms or 0
  if cooldown ~= 0 and self.last_play[name] ~= nil and t - self.last_play[name] < cooldown then
    return { result = "cooldown" }
  end

  -- voice cap: steal the oldest (smallest start, then smallest id) or refuse
  local victim, count = nil, 0
  for _, v in ipairs(self.voices) do
    if v.event == name then
      count = count + 1
      if not victim or v.start < victim.start or (v.start == victim.start and v.id < victim.id) then victim = v end
    end
  end
  local stolen = AudioDirector.NO_VOICE
  if count >= (ev.max_voices or AudioDirector.DEFAULT_MAX_VOICES) then
    if (ev.steal or AudioDirector.DEFAULT_STEAL) == "none" then return { result = "capped" } end
    victim["end"] = t                                -- it stops now (the ducking envelope sees that)
    for i, v in ipairs(self.voices) do
      if v == victim then table.remove(self.voices, i); break end
    end
    stolen = victim.id
  end

  -- fixed draw order: variant, pitch, volume (a fixed range draws nothing)
  local rng = self.rng[name]
  local idx = self:_pick(name, ev, rng)
  local pitch = ev.pitch_semitones or { 0.0, 0.0 }
  local lo, hi = pitch[1], pitch[2]
  local semis = lo
  if lo ~= hi then semis = lo + (hi - lo) * rng:next() end
  local volume = ev.volume_db or { 0.0, 0.0 }
  local vlo, vhi = volume[1], volume[2]
  local gain = vlo
  if vlo ~= vhi then gain = vlo + (vhi - vlo) * rng:next() end
  local ratio = 2.0 ^ (semis / 12.0)

  local voice = { id = self.next_id, event = name, bus = ev.bus, start = t,
                  ["end"] = t + ev.lengths_ms[idx + 1] / ratio }   -- lengths_ms is a Lua list: 1-based
  self.next_id = self.next_id + 1
  self.voices[#self.voices + 1] = voice
  if self.triggers[voice.bus] then self.history[#self.history + 1] = voice end
  self.last_play[name] = t
  self.last_variant[name] = idx
  return { result = "played", variant = idx, pitch_semitones = semis, pitch_ratio = ratio, gain_db = gain,
           voice = voice.id, stolen = stolen, ends_ms = voice["end"] }
end

-- The duck gain after dt ms of one segment (active: the trigger bus has a voice playing at its start).
local function ramp(gain, active, rule, dt)
  local depth = rule.depth_db
  if active then
    local attack = rule.attack_ms or 0
    if attack <= 0 then return depth end
    return math.max(depth, gain + depth / attack * dt)
  end
  local release = rule.release_ms or 0
  if release <= 0 then return 0.0 end
  return math.min(0.0, gain - depth / release * dt)
end

-- { target bus = duck gain in dB } at t_ms, every rule advanced from its last call to t across the trigger bus's
-- voice edges. A bus named by several rules takes the deepest gain. No rules: an empty table.
function AudioDirector:duck(t)
  self:_clock(t)
  local out = {}
  for i, rule in ipairs(self.ducking) do
    local st = self.duck_state[i]
    local mine, seen, edges = {}, {}, {}
    for _, v in ipairs(self.history) do
      if v.bus == rule.trigger then
        mine[#mine + 1] = v
        for _, e in ipairs({ v.start, v["end"] }) do
          if st.t < e and e < t and not seen[e] then seen[e] = true; edges[#edges + 1] = e end
        end
      end
    end
    table.sort(edges)
    edges[#edges + 1] = t
    local gain, at = st.gain, st.t
    for _, edge in ipairs(edges) do
      local active = false
      for _, v in ipairs(mine) do
        if v.start <= at and at < v["end"] then active = true; break end
      end
      gain = ramp(gain, active, rule, edge - at)
      at = edge
    end
    st.gain, st.t = gain, t
    for _, bus in ipairs(rule.targets) do
      out[bus] = math.min(out[bus] or 0.0, gain)
    end
  end
  -- every rule now stands at t: a voice that ended at or before t adds no later edge and is never active again
  local keep = {}
  for _, v in ipairs(self.history) do
    if v["end"] > t then keep[#keep + 1] = v end
  end
  self.history = keep
  return out
end

return AudioDirector

-- {{FOOTER}}
