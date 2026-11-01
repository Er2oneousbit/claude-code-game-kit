-- ---------------------------------------------------------------------------
-- bug_report.lua
-- Purpose : The bug-report key (F8 in debug builds): bundles a screenshot, the log tail, the settings and a short
--           info file into bug_<timestamp>/ in the user-data folder, so a tester attaches one folder.
-- Usage   : BugReport.capture(app)     -- app.lua calls it on F8; the files land a frame later
-- Notes   : The screenshot comes from love.graphics.captureScreenshot, which delivers the frame after it is drawn;
--           a headless run has no screenshot (the other files are still written). Nothing leaves the machine.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Log = require("src.core.log")
local Settings = require("src.core.settings")
local Version = require("src.version")

local BugReport = {}

-- ---- Tunables ----------------------------------------------------------------
local TAIL_LINES = 200

local function write_files(app, dir, png)
  local store = app.store
  local top = app:top()
  store:write(dir .. "/info.txt", table.concat({
    Version.name .. " " .. Version.version,
    "time: " .. os.date("!%Y-%m-%dT%H:%M:%SZ"),
    "screen: " .. (top and top.name or "none"),
    "seed: " .. tostring(app.seed or "none"),
    "locale: " .. app.i18n.locale,
    "os: " .. love.system.getOS(),
  }, "\n") .. "\n")
  store:write(dir .. "/log_tail.txt", app.log_file:tail(TAIL_LINES) .. "\n")
  store:write(dir .. "/settings.json", Settings.encode(app.settings))
  if png then store:write(dir .. "/screenshot.png", png) end
end

-- Returns the folder's path (the screenshot follows a frame later).
function BugReport.capture(app)
  local dir = "bug_" .. os.date("%Y%m%d_%H%M%S")
  local path = app.store:path(dir)
  local function done(png)
    local ok, err = pcall(write_files, app, dir, png)
    if ok then
      Log.info("bug", "report saved to " .. path)
      app:toast(app:t("toast.bug_saved"))
      app.last_bug_report = path
    else
      Log.error("bug", "report not saved: " .. tostring(err))
    end
  end
  if love.graphics and love.window and love.window.isOpen() then
    love.graphics.captureScreenshot(function(image_data)
      local ok, data = pcall(function() return image_data:encode("png"):getString() end)
      done(ok and data or nil)
    end)
  else
    done(nil)
  end
  return path
end

return BugReport

-- {{FOOTER}}
