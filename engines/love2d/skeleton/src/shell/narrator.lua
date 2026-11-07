-- ---------------------------------------------------------------------------
-- narrator.lua
-- Purpose : Menu narration (#165): every focus change, value change and screen says a short line ("Music volume,
--           slider, 70 percent"), so a blind or low-vision player can use the title, settings and pause screens.
-- Usage   : app.narrator = Narrator.new(app); app.narrator:update() once a frame (app.lua does both)
--           Narrator.describe(app, row) is the line for one menu row (the access drive reports it for every row)
-- Notes   : The line is always worked out (app.last_narration); it is spoken only with access.narration on. LÖVE has
--           no speech of its own, so the operating system's is used from a background thread (the game never
--           waits): Windows' speech synthesizer through PowerShell, macOS `say`, Linux `spd-say` (speech-dispatcher).
--           Only Windows was tried (verify on macOS and Linux); a line still being spoken is not cut off.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Bindings = require("src.core.bindings")

local Narrator = {}
Narrator.__index = Narrator

-- the words a screen's title comes from, per screen name (a screen not listed says its name)
local SCREEN_TITLES = { settings = "settings.title", credits = "credits.title", pause = "pause.title",
                        help = "help.title", history = "history.title", juice_demo = "juice.title" }
local ROLES = { button = "narrate.button", binding = "narrate.button", toggle = "narrate.toggle",
                slider = "narrate.slider", choice = "narrate.choice" }

-- the speech thread: one line at a time from the channel, through the system's speech command
local THREAD = [[
local channel = love.thread.getChannel("narrator")
while true do
  local cmd = channel:demand()
  if cmd == "quit" then break end
  os.execute(cmd)
end
]]

local function speech_command(text)
  local os_name = love.system and love.system.getOS() or ""
  if os_name == "Windows" then
    local quoted = text:gsub("'", "''")                  -- PowerShell single quotes
    return 'powershell -NoProfile -Command "Add-Type -AssemblyName System.Speech; '
           .. "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('" .. quoted:gsub('"', "") .. "')\""
  end
  local quoted = "'" .. text:gsub("'", "'\\''") .. "'"   -- POSIX single quotes
  if os_name == "OS X" then return "say " .. quoted end
  return "spd-say " .. quoted
end

function Narrator.new(app)
  return setmetatable({ app = app, last_top = nil, last_line = nil, thread = nil }, Narrator)
end

-- the line one menu row says: its label, its role, its value
function Narrator.describe(app, row)
  if not row then return "" end
  local label = type(row.text) == "function" and row.text() or tostring(row.text or "")
  local value = row.value and row.value() or ""
  return Bindings.narration_line(label, ROLES[row.kind] and app:t(ROLES[row.kind]) or "", value)
end

local function focused_row(top)
  local list = top and (top.list or (top.lists and top.lists[top.tab]))
  return list and list:focused() or nil
end

function Narrator:say(line)
  self.last_line = line
  self.app.last_narration = line
  if not (self.app.settings.access.narration and love.thread) then return end
  if not self.thread then
    self.thread = love.thread.newThread(THREAD)
    self.thread:start()
  end
  love.thread.getChannel("narrator"):push(speech_command(line))
end

function Narrator:update()
  local app, top = self.app, self.app:top()
  if top ~= self.last_top then
    self.last_top = top
    if top then
      local key = SCREEN_TITLES[top.name]
      self:say(Bindings.narration_line(key and app:t(key) or top.name, app:t("narrate.screen")))
      return
    end
  end
  local line = Narrator.describe(app, focused_row(top))
  if line ~= "" and line ~= self.last_line then self:say(line) end
end

return Narrator

-- {{FOOTER}}
