-- ---------------------------------------------------------------------------
-- music_player.lua
-- Purpose : Plays data/music.json: each track's stems loop together on the bar grid, and a change of track happens
--           on the sample the music director plans (next beat, bar, phrase or loop end), with an optional fade and
--           stinger. The player mixes the stems itself into fixed-size buffers and feeds a QueueableSource.
-- Usage   : local MusicPlayer = require("src.shell.music_player")
--           local music = MusicPlayer.from_file("data/music.json", { root = "assets/audio/" })  -- decodes the stems
--           music:start("explore")                  -- at the next sample of the music clock
--           local plan = music:request("combat")    -- the plan, in samples on the music clock (or nil)
--           music:set_stem_gain("explore", "drums", 0)   -- layers: a stem off or on (linear 0..1)
--           music:set_volume(app:bus_volume("music"))    -- the player's sliders (app.lua does it)
--           music:update()                          -- every frame: keeps the queue full
--           tests: MusicPlayer.new(data, readers) and music:mix(buffer, frames), no love.audio at all
-- Notes   : PRECISION. Sample-exact in its own mix: every switch, fade step, stinger start, stem gain change and loop
--           wrap lands on the exact sample the director planned, counted on the music clock (the number of
--           samples this player has mixed). tests/test_music_player.lua checks that sample by sample, without an
--           audio device. What you hear lags that clock by the queue (QUEUE_BUFFERS x BUFFER_FRAMES, 4 x 1024 =
--           about 93 ms at 44.1 kHz) plus OpenAL's own buffering: a request is planned at the mix cursor, so even an
--           "immediate" change is heard that much later; the musical timing stays exact. A frame hitch longer than
--           the queue runs it dry: a gap, then the music goes on from the same sample (the clock pauses, nothing is
--           skipped). The output through OpenAL (latency, gaps on a real device) was not measured.
--           Why not plain Sources: LÖVE has no scheduled start, so Source:play() per frame is only frame-accurate
--           (16 ms at 60 fps), and stems started one call apart can drift by a buffer.
--           Stems are decoded whole into SoundData (love.sound.newSoundData): about 10 MB per stereo minute at
--           16 bit. music.json's sample_rate must equal every file's rate (no resampling here; from_file refuses a
--           mismatch). Mono files play on both channels; the output is 16-bit stereo. The mix is clamped to -1..1
--           (SoundData:setSample does not clamp: 2.0 wraps around in 11.5). A fade is a straight line in gain from
--           1 at switch_at down to 0 at from_stop_at, where the old track stops; the new track enters at full gain.
--           Decisions live in src/core/music_director.lua.
--
-- Pseudocode:
--   start(track, at): a voice { stems, since = at, entry = 0 } on the music clock
--   request(to): a change still pending (its switch sample not mixed yet) is undone first, as Godot's player does
--                -> plan = MusicDirector.plan(current, cursor) -> old voice fades from switch_at, stops at from_stop_at
--                -> stinger voice at stinger_at -> new voice from to_start_at at to_offset
--   mix(buffer, n): for each voice: its active samples in [cursor, cursor + n) -> position (loop wrap) -> stem
--                   samples x stem gain x fade -> sum -> clamp -> buffer; cursor += n; drop finished voices
--   update(): while the source has a free buffer: mix BUFFER_FRAMES into the next SoundData of a ring, queue it
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Json = require("src.core.json")
local Log = require("src.core.log")
local MusicDirector = require("src.core.music_director")

local MusicPlayer = {}
MusicPlayer.__index = MusicPlayer

-- ---- Tunables ----------------------------------------------------------------
MusicPlayer.BUFFER_FRAMES = 1024         -- frames per queued buffer (smaller: less latency, more update calls)
MusicPlayer.QUEUE_BUFFERS = 4            -- buffers OpenAL holds; QUEUE_BUFFERS x BUFFER_FRAMES is the lag
MusicPlayer.DEFAULT_ROOT = "assets/audio/"
local BIT_DEPTH = 16
local OUT_CHANNELS = 2

-- ---- Construction ------------------------------------------------------------------------------------------------
-- data: the decoded music.json; readers: { [file] = SoundData or anything with getSample(i, ch),
-- getSampleCount(), getChannelCount() } for every stem and stinger file.
function MusicPlayer.new(data, readers)
  if type(data) ~= "table" or type(data.tracks) ~= "table" or type(data.sample_rate) ~= "number" then
    error("music: not a music.json (tracks and sample_rate are required)", 0)
  end
  return setmetatable({ data = data, readers = readers or {}, rate = data.sample_rate, cursor = 0, voices = {},
                        current = nil, volume = 1, source = nil, ring = nil, ring_i = 0,
                        mix_l = {}, mix_r = {} }, MusicPlayer)
end

-- Every file the music needs (stems and stingers), each once.
function MusicPlayer.files(data)
  local seen, out = {}, {}
  local function add(f)
    if type(f) == "string" and not seen[f] then seen[f] = true; out[#out + 1] = f end
  end
  for _, name in ipairs(Json.sorted_keys(data.tracks or {})) do
    local stems = data.tracks[name].stems or {}
    for _, stem in ipairs(Json.sorted_keys(stems)) do add(stems[stem]) end
  end
  local stingers = data.stingers ~= Json.null and data.stingers or {}
  for _, name in ipairs(Json.sorted_keys(stingers)) do add(stingers[name].file) end
  return out
end

-- Loads music.json and decodes every file under opts.root (default assets/audio/). Raises on a missing file or a
-- rate that is not the file's sample_rate, so a broken setup fails at load, not at the first transition.
function MusicPlayer.from_file(path, opts)
  opts = opts or {}
  local text = love.filesystem.read(path)
  if not text then error("music: cannot read " .. path, 0) end
  local data = Json.decode(text)
  local root = opts.root or MusicPlayer.DEFAULT_ROOT
  local readers = {}
  for _, f in ipairs(MusicPlayer.files(data)) do
    local sd = love.sound.newSoundData(root .. f)
    if sd:getSampleRate() ~= data.sample_rate then
      error(string.format("music: %s is %d Hz, music.json says %d Hz (resample it)", f, sd:getSampleRate(),
                          data.sample_rate), 0)
    end
    readers[f] = sd
  end
  return MusicPlayer.new(data, readers)
end

-- ---- Control (all times are samples on the music clock) -----------------------------------------------------------
function MusicPlayer:now() return self.cursor end
function MusicPlayer:track() return self.current and self.current.name or nil end

local function reader_of(self, file)
  local r = self.readers[file]
  if not r then error("music: file " .. tostring(file) .. " is not loaded", 0) end
  return r
end

-- A track voice: its stems in a fixed order (sorted names) so the mix is the same on every run.
local function track_voice(self, name, at, entry)
  local t = self.data.tracks[name]
  if not t then error("music: unknown track '" .. tostring(name) .. "'", 0) end
  local ls, le = MusicDirector.loop_points(t, self.rate)
  local stems = {}
  for _, stem in ipairs(Json.sorted_keys(t.stems or {})) do
    stems[#stems + 1] = { name = stem, reader = reader_of(self, t.stems[stem]), gain = 1, next_at = nil,
                          next_gain = nil }
  end
  return { kind = "track", name = name, track = t, since = at, entry = entry, loop_start = ls, loop_end = le,
           stems = stems, fade_at = nil, stop_at = nil }
end

-- Starts a track at `at` (default: the next sample to mix). Stops nothing: call it once, then use request.
function MusicPlayer:start(name, at)
  self.stopped, self.pending = false, nil
  local v = track_voice(self, name, at or self.cursor, 0)
  self.voices[#self.voices + 1] = v
  self.current = v
  return v
end

-- Undoes the last planned change when its switch sample has not been mixed yet (Godot's _cancel_pending): the new
-- track and a stinger that has not started are dropped, and the old track plays on with its old fade and stop, as
-- if the change had never been asked for. Too late (the switch is already mixed): nothing changes.
local function cancel_pending(self)
  local pend = self.pending
  self.pending = nil
  if not pend or pend.switch_at < self.cursor then return end
  local keep, has_old = {}, false
  for _, v in ipairs(self.voices) do
    if v == pend.old then has_old = true end
    if v ~= pend.new and not (v == pend.stinger and v.since >= self.cursor) then keep[#keep + 1] = v end
  end
  if not has_old then keep[#keep + 1] = pend.old end    -- dropped at a stop sample that is now undone
  self.voices = keep
  pend.old.fade_at, pend.old.stop_at = pend.fade_at, pend.stop_at
  self.current = pend.old
end

-- Plans and schedules a change to `to` at the mix cursor; returns the plan, or nil when nothing was planned
-- (no track yet: `to` starts now; `to` already current: nothing happens). A change asked for while the previous
-- one is still pending replaces it, so asking for the playing track again before the switch keeps it playing.
function MusicPlayer:request(to)
  if not self.current then
    self:start(to)
    return nil
  end
  cancel_pending(self)
  local cur = self.current
  if cur.name == to then return nil end
  -- a track that has not entered yet (a stinger's delayed entry) is planned from where it enters, not before
  local p = MusicDirector.plan(self.data, cur.name, cur.since, cur.entry, to, math.max(self.cursor, cur.since))
  local pend = { old = cur, fade_at = cur.fade_at, stop_at = cur.stop_at, switch_at = p.switch_at }
  -- the old track: full gain until switch_at, a straight line to 0 at from_stop_at, then silent and dropped
  if p.fade > 0 then cur.fade_at = p.switch_at end
  cur.stop_at = cur.stop_at and math.min(cur.stop_at, p.from_stop_at) or p.from_stop_at
  if p.stinger ~= MusicDirector.NONE then
    local st = self.data.stingers[p.stinger]
    local r = reader_of(self, st.file)
    pend.stinger = { kind = "stinger", name = p.stinger, since = p.stinger_at,
                     stems = { { name = "stinger", reader = r, gain = 1 } }, stop_at = p.stinger_at + r:getSampleCount() }
    self.voices[#self.voices + 1] = pend.stinger
  end
  local v = track_voice(self, to, p.to_start_at, p.to_offset)
  self.voices[#self.voices + 1] = v
  self.current, pend.new, self.pending = v, v, pend
  return p
end

-- A stem's level (linear 0..1) of the current track from sample `at` on (default: the next sample to mix).
function MusicPlayer:set_stem_gain(track, stem, value, at)
  local cur = self.current
  if not cur or cur.name ~= track then return false end
  for _, s in ipairs(cur.stems) do
    if s.name == stem then
      s.next_at, s.next_gain = at or self.cursor, math.min(1, math.max(0, value))
      return true
    end
  end
  error("music: track " .. tostring(track) .. " has no stem " .. tostring(stem), 0)
end

-- The output level (linear; the music bus from the sliders). Applies at once through the source, not on the grid.
function MusicPlayer:set_volume(v)
  self.volume = v
  if self.source then self.source:setVolume(v) end
end

-- ---- The mixer (pure Lua: no love.* below until the output section) ----------------------------------------------
-- Adds one voice's samples in [t0, t0 + n) into the accumulators.
local function mix_voice(self, v, t0, n, acc_l, acc_r)
  local first = math.max(t0, v.since)
  local last = t0 + n                                      -- exclusive
  if v.stop_at then last = math.min(last, v.stop_at) end
  if first >= last then return end
  -- the position at the first active sample: the director's rule (with the loop wrap), then one step per sample
  local p
  if v.kind == "track" then
    p = MusicDirector.position(v.track, self.rate, v.since, first, v.entry)
  else
    p = first - v.since
  end
  local fade_at, stop_at = v.fade_at, v.stop_at
  local fade_len = fade_at and (stop_at - fade_at) or 0
  for _, s in ipairs(v.stems) do
    local r = s.reader
    local frames, ch = r:getSampleCount(), r:getChannelCount()
    local q = p
    for t = first, last - 1 do
      if s.next_at and t >= s.next_at then s.gain, s.next_at, s.next_gain = s.next_gain, nil, nil end
      local g = s.gain
      if fade_at and t >= fade_at then g = g * (stop_at - t) / fade_len end
      if g ~= 0 and q < frames then                        -- a stem shorter than the loop is silent past its end
        local i = t - t0 + 1
        if ch == 1 then
          local x = r:getSample(q, 1) * g
          acc_l[i] = acc_l[i] + x
          acc_r[i] = acc_r[i] + x
        else
          acc_l[i] = acc_l[i] + r:getSample(q, 1) * g
          acc_r[i] = acc_r[i] + r:getSample(q, 2) * g
        end
      end
      q = q + 1
      if v.kind == "track" and q >= v.loop_end then q = v.loop_start end
    end
  end
end

-- Mixes the next n frames of the music clock into buffer (buffer:setSample(i, channel, value), i from 0, as a
-- stereo SoundData has it) and moves the clock on. Returns n.
function MusicPlayer:mix(buffer, n)
  local acc_l, acc_r = self.mix_l, self.mix_r
  for i = 1, n do acc_l[i], acc_r[i] = 0, 0 end
  local t0 = self.cursor
  for _, v in ipairs(self.voices) do mix_voice(self, v, t0, n, acc_l, acc_r) end
  for i = 1, n do
    buffer:setSample(i - 1, 1, math.min(1, math.max(-1, acc_l[i])))
    buffer:setSample(i - 1, 2, math.min(1, math.max(-1, acc_r[i])))
  end
  self.cursor = t0 + n
  -- a voice whose stop sample has been mixed is done (a stem gain change pending on it goes with it)
  local keep = {}
  for _, v in ipairs(self.voices) do
    if not v.stop_at or v.stop_at > self.cursor then keep[#keep + 1] = v end
  end
  self.voices = keep
  return n
end

-- ---- Output (LÖVE) -------------------------------------------------------------------------------------------------
-- Opens the QueueableSource; update() calls it on first use. False (and a log line) when there is no audio device.
function MusicPlayer:open()
  if self.source then return true end
  local ok, src = pcall(love.audio.newQueueableSource, self.rate, BIT_DEPTH, OUT_CHANNELS, MusicPlayer.QUEUE_BUFFERS)
  if not ok then
    Log.warn("music", "no output: " .. tostring(src))
    self.failed = true
    return false
  end
  self.source = src
  src:setVolume(self.volume)
  -- one more buffer than OpenAL holds: a SoundData is written again only after the queue let its turn go
  self.ring = {}
  for i = 1, MusicPlayer.QUEUE_BUFFERS + 1 do
    self.ring[i] = love.sound.newSoundData(MusicPlayer.BUFFER_FRAMES, self.rate, BIT_DEPTH, OUT_CHANNELS)
  end
  return true
end

-- Keeps the queue full; call once per frame.
function MusicPlayer:update()
  if self.stopped or self.failed or not self:open() then return end
  local src = self.source
  while src:getFreeBufferCount() > 0 do
    self.ring_i = self.ring_i % #self.ring + 1
    local sd = self.ring[self.ring_i]
    self:mix(sd, MusicPlayer.BUFFER_FRAMES)
    src:queue(sd)
  end
  if not src:isPlaying() then src:play() end   -- the first time, and after a stall ran the queue dry
end

-- Stops the output and forgets every voice until the next start (the clock keeps its count).
function MusicPlayer:stop()
  if self.source then self.source:stop() end
  self.voices, self.current, self.stopped, self.pending = {}, nil, true, nil
end

return MusicPlayer

-- {{FOOTER}}
