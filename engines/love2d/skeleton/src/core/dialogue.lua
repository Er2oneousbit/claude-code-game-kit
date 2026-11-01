-- ---------------------------------------------------------------------------
-- dialogue.lua
-- Purpose : Reads dialogue.built.json (the audio pipeline's runtime file, schema v0) and plays lines as
--           subtitles: which line is showing, which cue of it, how many characters a typewriter has revealed,
--           priorities and interrupts, bark cooldowns, and the player's subtitle settings.
-- Usage   : local Dialogue = require("src.core.dialogue")
--           local db = Dialogue.parse(Json.decode(love.filesystem.read("data/dialogue/sample.built.json")))
--           local track = Dialogue.track(db)
--           track:play("guide.welcome", settings)   -- false when it must not show (barks off, cooldown, priority)
--           each frame: track:update(dt); local cur = track:current()  -- { id, line, t } or nil
--           Dialogue.cue_at(cur.line, cur.t) -> the cue's lines; Dialogue.revealed(cur.line, cur.t) -> characters
-- Notes   : No love.* calls. Unknown fields are ignored (the schema only ever adds optional fields). Lines of kind
--           "bark" show only with access.subtitle_barks; nothing shows with access.subtitles off. Interrupts:
--           "never" waits its turn (dropped here: barks are not queued), "lower" may cut a lower-priority line,
--           "always" cuts anything. A line with no reveal list reveals at DEFAULT_CPS.
--
-- Pseudocode (play):
--   line missing or not allowed by the settings -> false; on cooldown -> false
--   nothing playing -> start ; playing: interrupt rule against the current line's priority -> start or false
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Dialogue = {}

-- ---- Tunables ----------------------------------------------------------------
Dialogue.SCHEMA_VERSION = 1
Dialogue.DEFAULT_CPS = 30                -- characters per second for a line without a reveal list
Dialogue.HOLD_S = 0.6                    -- a text-only line stays this long after its last character
Dialogue.DEFAULT_PRIORITY = 50

-- db = { lines = { id -> line }, captions = { id -> caption }, style = {...}, locale }
function Dialogue.parse(data)
  if type(data) ~= "table" or type(data.lines) ~= "table" then error("dialogue: no lines table", 0) end
  local db = { lines = {}, captions = {}, style = data.style or {}, locale = data.locale or "en",
               version = data.version }
  for id, line in pairs(data.lines) do
    if type(line) == "table" and type(line.text) == "string" then
      db.lines[id] = line
      line.id = id
    end
  end
  if type(data.captions) == "table" then
    for id, c in pairs(data.captions) do
      if type(c) == "table" and type(c.text) == "string" then db.captions[id] = c end
    end
  end
  return db
end

local function char_count(text)
  local _, n = text:gsub("[^\128-\191]", "")
  return n
end

-- seconds the line is on screen
function Dialogue.duration(line)
  if type(line.duration_s) == "number" then return line.duration_s end
  return char_count(line.text) / Dialogue.DEFAULT_CPS + Dialogue.HOLD_S
end

-- the cue showing at t (a list of text lines), or nil
function Dialogue.cue_at(line, t)
  if type(line.cues) == "table" then
    for _, cue in ipairs(line.cues) do
      if type(cue) == "table" and t >= (cue.start or 0) and t < (cue["end"] or math.huge) then return cue.lines end
    end
    return nil
  end
  if t < Dialogue.duration(line) then return { line.text } end
  return nil
end

-- characters of line.text revealed at t (a typewriter); the reveal list's i is 0-based
function Dialogue.revealed(line, t)
  local total = char_count(line.text)
  if type(line.reveal) == "table" and #line.reveal > 0 then
    local n = 0
    for _, r in ipairs(line.reveal) do
      if type(r) == "table" and type(r.t) == "number" and r.t <= t then n = math.max(n, (r.i or 0) + 1) end
    end
    return math.min(n, total)
  end
  return math.min(total, math.floor(t * Dialogue.DEFAULT_CPS))
end

function Dialogue.allowed(line, settings)
  local access = settings and settings.access or {}
  if access.subtitles == false then return false end
  if line.kind == "bark" and not access.subtitle_barks then return false end
  return true
end

-- ---- A track: one line at a time -----------------------------------------------------------------------
local Track = {}
Track.__index = Track

function Dialogue.track(db)
  return setmetatable({ db = db, playing = nil, t = 0, clock = 0, last_played = {} }, Track)
end

function Track:play(id, settings)
  local line = self.db.lines[id]
  if not line or not Dialogue.allowed(line, settings) then return false end
  local cooldown = type(line.cooldown_s) == "number" and line.cooldown_s or 0
  local last = self.last_played[id]
  if last and cooldown > 0 and self.clock - last < cooldown then return false end
  if self.playing then
    local cur = self.playing
    local mode = line.interrupt or "lower"
    local mine, theirs = line.priority or Dialogue.DEFAULT_PRIORITY, cur.priority or Dialogue.DEFAULT_PRIORITY
    if mode == "never" or (mode == "lower" and mine <= theirs) then return false end
  end
  self.playing, self.t = line, 0
  self.last_played[id] = self.clock
  return true
end

function Track:update(dt)
  self.clock = self.clock + dt
  if not self.playing then return end
  self.t = self.t + dt
  if self.t >= Dialogue.duration(self.playing) then self.playing = nil end
end

function Track:current()
  if not self.playing then return nil end
  return { id = self.playing.id, line = self.playing, t = self.t }
end

function Track:stop() self.playing = nil end

return Dialogue

-- {{FOOTER}}
