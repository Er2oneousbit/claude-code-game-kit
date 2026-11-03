-- ---------------------------------------------------------------------------
-- telemetry.lua
-- Purpose : Local, consent-gated play statistics: events are appended to telemetry.csv in the user-data folder
--           only when the player said yes (settings telemetry.consent == "yes"). Nothing is sent anywhere.
-- Usage   : local Telemetry = require("src.core.telemetry")
--           local tele = Telemetry.new(store, function() return Settings.telemetry_allowed(settings) end,
--                                      Telemetry.new_session(love.math.random))
--           tele:event("screen", "title")        -- a no-op until consent
-- Notes   : No love.* calls. The consent check runs on every event, so a "no" in the settings stops the very
--           next event. Columns, the same in every engine: time (UTC, ISO 8601, whole seconds), session (8 hex
--           digits, random per launch), event, detail; tested against data/golden/telemetry.json. To send the file
--           somewhere a game needs an endpoint, a privacy policy that names what is collected and why, and a way
--           to withdraw consent (docs/sop/SOP-19); the kit ships none of that on purpose.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Telemetry = {}
Telemetry.__index = Telemetry

-- ---- Tunables ----------------------------------------------------------------
Telemetry.FILE = "telemetry.csv"
Telemetry.HEADER = "time,session,event,detail"
Telemetry.SESSION_LENGTH = 8             -- hex digits in a session id

local function csv(field)
  field = tostring(field or "")
  if field:find('[,"\r\n]') then field = '"' .. field:gsub('"', '""') .. '"' end
  return field
end

-- A random id per launch, so rows of one run can be grouped. rand(lo, hi) gives an integer (math.random when left
-- out; the game passes love.math.random, which LÖVE seeds at start).
function Telemetry.new_session(rand)
  rand = rand or math.random
  return string.format("%04x%04x", rand(0, 65535), rand(0, 65535))
end

-- UTC, ISO 8601, whole seconds (a fraction is dropped, not rounded): 2026-11-02T14:05:03Z
function Telemetry.time_string(unix_s)
  return os.date("!%Y-%m-%dT%H:%M:%SZ", math.floor(unix_s))
end

-- One escaped CSV row (no line break)
function Telemetry.row(unix_s, session, name, detail)
  return table.concat({ csv(Telemetry.time_string(unix_s)), csv(session), csv(name), csv(detail) }, ",")
end

-- session: the launch's id (Telemetry.new_session()); now: optional function returning Unix seconds (os.time)
function Telemetry.new(store, allowed, session, now)
  return setmetatable({ store = store, allowed = allowed, session = session or Telemetry.new_session(),
                        now = now or os.time, written = 0 }, Telemetry)
end

-- Returns true when the event was written.
function Telemetry:event(name, detail)
  if not (self.allowed and self.allowed()) then return false end
  local ok = pcall(function()
    if not self.store:exists(Telemetry.FILE) then self.store:write(Telemetry.FILE, Telemetry.HEADER .. "\n") end
    self.store:append(Telemetry.FILE, Telemetry.row(self.now(), self.session, name, detail) .. "\n")
  end)
  if ok then self.written = self.written + 1 end
  return ok
end

return Telemetry

-- {{FOOTER}}
