-- ---------------------------------------------------------------------------
-- telemetry.lua
-- Purpose : Local, consent-gated play statistics: events are appended to telemetry.csv in the user-data folder
--           only when the player said yes (settings telemetry.consent == "yes"). Nothing is sent anywhere.
-- Usage   : local Telemetry = require("src.core.telemetry")
--           local tele = Telemetry.new(store, function() return Settings.telemetry_allowed(settings) end)
--           tele:event("screen", "title")        -- a no-op until consent
-- Notes   : No love.* calls. The consent check runs on every event, so a "no" in the settings stops the very
--           next event. Columns: time (UTC, ISO 8601), session seconds, event, detail. To send the file
--           somewhere a game needs an endpoint, a privacy policy that names what is collected and why, and a way
--           to withdraw consent (docs/sop/SOP-19); the kit ships none of that on purpose.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Telemetry = {}
Telemetry.__index = Telemetry

-- ---- Tunables ----------------------------------------------------------------
Telemetry.FILE = "telemetry.csv"
Telemetry.HEADER = "time,session_s,event,detail"

local function csv(field)
  field = tostring(field or "")
  if field:find('[,"\r\n]') then field = '"' .. field:gsub('"', '""') .. '"' end
  return field
end

-- clock: optional function returning seconds since the session started (os.clock when left out)
function Telemetry.new(store, allowed, clock)
  return setmetatable({ store = store, allowed = allowed, clock = clock or os.clock, written = 0 }, Telemetry)
end

-- Returns true when the event was written.
function Telemetry:event(name, detail)
  if not (self.allowed and self.allowed()) then return false end
  local ok = pcall(function()
    if not self.store:exists(Telemetry.FILE) then self.store:write(Telemetry.FILE, Telemetry.HEADER .. "\n") end
    self.store:append(Telemetry.FILE, table.concat({ csv(os.date("!%Y-%m-%dT%H:%M:%SZ")),
      csv(string.format("%.2f", self.clock())), csv(name), csv(detail) }, ",") .. "\n")
  end)
  if ok then self.written = self.written + 1 end
  return ok
end

return Telemetry

-- {{FOOTER}}
