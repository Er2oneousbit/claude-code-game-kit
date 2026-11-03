-- ---------------------------------------------------------------------------
-- drive.lua
-- Purpose : Scripted smoke scenarios (`python tools/dev.py smoke --drive <name>`): they press the same actions a
--           player would, frame by frame, and print proof lines dev.py echoes (SETTINGS_WRITTEN, PSEUDO_*,
--           DRIVE_*). Without --drive, a smoke run walks title -> menu -> play and lets the game run.
-- Usage   : menus          title -> settings: master volume 0.5 (left or right from whatever the data folder
--                          held), reduce motion on -> back (saves) -> quit;
--                          prints SETTINGS_WRITTEN <path> once the file holds the new values
--           crash          raises an error in a frame (conf.lua's handler writes the crash file, exit 1)
--           pseudo         (with --locale pseudo) visits every screen and checks every visible label
--           pseudo-plant   the same plus one label too small for its text: must fail and name it
--           show:<screen>  title | settings | pause | subtitle | juice: opens it, then ends (--screenshot)
--           bug            presses F8 on the menu and checks the bug_<timestamp>/ folder
-- Notes   : A scenario is a coroutine: d:press() injects an action and waits a couple of frames, d:wait_screen()
--           yields until the screen is on top. Each wait has a frame limit, so a broken menu fails instead of
--           hanging. Add a scenario: a function in SCENARIOS, then document it in docs/ENGINE_FLOW.md.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Json = require("src.core.json")
local Log = require("src.core.log")
local Settings = require("src.core.settings")

local Drive = {}
Drive.__index = Drive

-- ---- Tunables ----------------------------------------------------------------
local PRESS_GAP = 2                      -- frames after each injected press
local WAIT_LIMIT = 900                   -- frames a wait may take before the scenario fails
local FOCUS_LIMIT = 40                   -- presses to reach a menu item
local DRIVE_LIMIT = 6000                 -- frames for a whole scenario
Drive.TARGET_MASTER = 0.5                -- menus drives the master volume here
Drive.MAX_SLIDER_STEPS = 40              -- presses a slider gets to reach its target (0..1 is 20 steps of 0.05)
local SLIDER_EPS = 1e-9                  -- a slider value this close to its target is there

-- The press that moves a slider from now towards target ("" once it is there)
function Drive.slide_action(now, target)
  if math.abs(now - target) <= SLIDER_EPS then return "" end
  return now > target and "ui_left" or "ui_right"
end

-- ---- Helpers (inside the coroutine) ------------------------------------------------------------------------
function Drive:frames(n)
  for _ = 1, n or 1 do coroutine.yield() end
end

function Drive:wait_for(pred, what, limit)
  for _ = 1, limit or WAIT_LIMIT do
    if pred() then return end
    coroutine.yield()
  end
  error("timed out waiting for " .. what, 0)
end

function Drive:top() return self.app:top() end

function Drive:wait_screen(name)
  self:wait_for(function() local t = self:top(); return t and t.name == name end, "screen " .. name)
end

function Drive:press(action)
  self.app:inject(action)
  self:frames(PRESS_GAP)
end

function Drive:focus_id()
  local t = self:top()
  return t and t.focus_id and t:focus_id() or nil
end

-- presses `step` (ui_down) until the focused item is id
function Drive:focus(id, step)
  for _ = 1, FOCUS_LIMIT do
    if self:focus_id() == id then return end
    self:press(step or "ui_down")
  end
  error("could not focus " .. id .. " (focused: " .. tostring(self:focus_id()) .. ")", 0)
end

function Drive:open(item, screen)
  self:focus(item)
  self:press("ui_accept")
  self:wait_screen(screen)
end

-- title (answers the consent question with Later) -> main menu
function Drive:to_menu()
  self:wait_screen("title")
  if self:top().consent then self:press("ui_cancel") end
  self:press("ui_accept")
  self:wait_screen("main_menu")
end

-- settings: from the rows back up to the tab bar, then to a tab
function Drive:to_tab(tab)
  for _ = 1, FOCUS_LIMIT do
    local id = self:focus_id() or ""
    if id:sub(1, 5) == "tabs." then break end
    if self:top().lists[self:top().tab].index == 1 then self:press("ui_up") else self:press("ui_down") end
  end
  self:focus("tabs." .. tab, "ui_right")
end

-- Presses left or right on the focused slider until read() equals target, from any start value
function Drive:slide_to(what, read, target)
  for _ = 1, Drive.MAX_SLIDER_STEPS do
    local action = Drive.slide_action(read(), target)
    if action == "" then return end
    self:press(action)
  end
  if Drive.slide_action(read(), target) ~= "" then
    error(what .. " did not reach " .. target .. " (is " .. tostring(read()) .. ")", 0)
  end
end

-- the layout check of the next drawn frame
function Drive:check(name)
  self.app.ui:request_check(name)
  self:wait_for(function() return self.app.ui.check_result ~= nil end, "a drawn frame (does the run have a window?)")
  local r = self.app.ui.check_result
  self.app.ui.check_result = nil
  self.checked = self.checked + 1
  self.labels = self.labels + r.labels
  print(string.format("PSEUDO_SCREEN %s labels %d problems %d", name, r.labels, #r.problems))
  for _, p in ipairs(r.problems) do
    self.problems = self.problems + 1
    print(string.format("PSEUDO_FAIL %s label %s: %s (%q)", name, p.id, p.why, p.text))
  end
end

function Drive:done(code)
  self.exit_code = code or 0
  self.app:finish("DRIVE_DONE " .. self.name, self.exit_code)
  while true do coroutine.yield() end
end

-- ---- Scenarios ----------------------------------------------------------------------------------------------
local SCENARIOS = {}

-- no --drive: walk into the game and stay there (main.lua ends the run after --smoke N frames)
function SCENARIOS.default(d)
  d:to_menu()
  d:open("play", "play")
  while true do coroutine.yield() end
end

function SCENARIOS.menus(d)
  local app = d.app
  d:to_menu()
  d:open("settings", "settings")
  d:to_tab("audio")
  d:press("ui_down")
  d:focus("audio.master")
  d:slide_to("audio.master", function() return app.settings.audio.master end, Drive.TARGET_MASTER)
  d:to_tab("access")
  d:press("ui_down")
  d:focus("access.reduce_motion")
  if not app.settings.access.reduce_motion then d:press("ui_accept") end
  d:press("ui_cancel")                                   -- back: saves settings.json
  d:wait_screen("main_menu")
  local path = app.store:path(Settings.FILE)
  local ok, saved = Json.try_decode(app.store:read(Settings.FILE) or "")
  if not ok or Drive.slide_action(saved.audio.master, Drive.TARGET_MASTER) ~= ""
      or saved.access.reduce_motion ~= true then
    Log.error("drive", "settings.json does not hold master " .. Drive.TARGET_MASTER .. " and reduce_motion true: "
      .. path)
    d:done(1)
  end
  print("SETTINGS_WRITTEN " .. path)
  d:focus("quit")
  d:press("ui_accept")                                   -- app:quit() ends the run with DRIVE_DONE
  d:frames(10)
  error("quit did not end the run", 0)
end

function SCENARIOS.crash(d)
  d:to_menu()
  d:frames(2)
  error("drive crash: a planted error to prove the crash report (expected)")
end

local function pseudo_tour(d)
  local app = d.app
  if not app.i18n:is_pseudo() then
    app.kit.locale = "pseudo"
    app:apply_settings()
    print("DRIVE_NOTE the pseudo drive switched the locale to pseudo (pass --locale pseudo next time)")
  end
  d:wait_screen("title")
  if d:top().consent then d:check("consent"); d:press("ui_cancel") end
  d:check("title")
  d:press("ui_accept")
  d:wait_screen("main_menu")
  d:check("main_menu")
  d:open("settings", "settings")
  for _, tab in ipairs({ "display", "audio", "controls", "access", "language" }) do
    d:to_tab(tab)
    d:check("settings." .. tab)
    d:press("ui_down")
    d:focus(tab .. ".back")                              -- scrolled to the end: the rows below the fold
    d:check("settings." .. tab .. ".end")
    if tab == "controls" then
      d:focus("controls.bind_jump")
      d:press("ui_accept")                               -- the "press a key" prompt
      d:check("settings.capture")
      app.input:key("escape", false)
      d:frames(PRESS_GAP)
    end
  end
  d:press("ui_cancel")
  d:wait_screen("main_menu")
  d:open("credits", "credits")
  d:check("credits")
  d:press("ui_cancel")
  d:wait_screen("main_menu")
  if app.debug_build then
    app.settings.access.subtitle_barks, app.settings.access.captions_sfx = true, true   -- show the bark + caption
    d:focus("juice")
    d:press("ui_accept")
    d:wait_screen("loading")
    d:check("loading")
    d:wait_screen("juice_demo")
    d:frames(20)
    d:check("juice_demo")
    d:press("attack")
    d:frames(3)
    d:check("juice_demo.hit")
    d:press("pause")
    d:wait_screen("pause")
    d:check("pause")
    d:open("quit", "title")
    d:press("ui_accept")
    d:wait_screen("main_menu")
  end
  d:open("play", "loading")
  d:wait_screen("play")
  d:frames(5)
  d:check("play")
  d:press("pause")
  d:wait_screen("pause")
  d:check("pause.play")
  d:open("quit", "title")
  if d.problems == 0 then
    print(string.format("PSEUDO_PASS %d screens, %d labels, nothing truncated or untranslated", d.checked, d.labels))
    d:done(0)
  end
  print(string.format("PSEUDO_FAILED %d problem(s) on %d screens", d.problems, d.checked))
  Log.error("pseudo", d.problems .. " label problem(s); see the PSEUDO_FAIL lines")
  d:done(1)
end

SCENARIOS.pseudo = pseudo_tour
SCENARIOS["pseudo-plant"] = function(d)
  d.app.plant = true                                     -- app.lua draws one label too small for its text
  pseudo_tour(d)
end

SCENARIOS.bug = function(d)
  local app = d.app
  d:to_menu()
  app.input:key("f8", false)
  d:wait_for(function() return app.last_bug_report ~= nil end, "the bug report")
  local dir = app.last_bug_report:match("[^/]+$")
  for _, f in ipairs({ "info.txt", "log_tail.txt", "settings.json", "screenshot.png" }) do
    if not app.store:exists(dir .. "/" .. f) then Log.error("drive", "bug report lacks " .. f) d:done(1) end
  end
  print("DRIVE_BUG " .. app.last_bug_report)
  d:done(0)
end

-- show:<screen>: open it, let it settle, end (main.lua saves --screenshot)
local SHOW = {}
function SHOW.title(d)
  d:wait_screen("title")
  if d:top().consent then d:press("ui_cancel") end
  d:frames(10)
  d:wait_for(function() local t = d:top().t % 1.2; return t > 0.1 and t < 0.5 end, "the blinking prompt")
end
function SHOW.settings(d)
  d:to_menu()
  d:open("settings", "settings")
  d:to_tab("audio")
  d:press("ui_down")
  d:focus("audio.master")
  d:press("ui_left")
  d:frames(5)
end
function SHOW.pause(d)
  d:to_menu()
  d:open("play", "loading")
  d:wait_screen("play")
  d:frames(30)
  d:press("pause")
  d:wait_screen("pause")
  d:frames(5)
end
local function to_juice(d)
  d:to_menu()
  if not d.app.debug_build then error("the juice demo is in debug builds only", 0) end
  d:open("juice", "loading")
  d:wait_screen("juice_demo")
end
function SHOW.subtitle(d)
  d.app.settings.access.speaker_names = true
  to_juice(d)
  d:wait_for(function() local c = d.app.track:current(); return c and c.t > 1.6 end, "the subtitle line")
end
function SHOW.juice(d)
  to_juice(d)
  d:frames(90)                                           -- the intro line is over by now
  d:press("attack")
  d:frames(1)
end

-- ---- The driver ----------------------------------------------------------------------------------------------
function Drive.new(app, name)
  local self = setmetatable({ app = app, name = name or "default", frame = 0, exit_code = 0, checked = 0,
                              labels = 0, problems = 0 }, Drive)
  local fn = SCENARIOS[self.name]
  local show = self.name:match("^show:(.+)$")
  if show then
    if not SHOW[show] then error("unknown --drive show:" .. show .. " (title, settings, pause, subtitle, juice)", 0) end
    fn = function(d) SHOW[show](d); d:done(0) end
  end
  if not fn then
    local names = {}
    for k in pairs(SCENARIOS) do if k ~= "default" then names[#names + 1] = k end end
    table.sort(names)
    error("unknown --drive " .. self.name .. " (" .. table.concat(names, ", ") .. ", show:<screen>)", 0)
  end
  self.co = coroutine.create(function() fn(self) end)
  if self.name ~= "default" then Log.info("drive", "scenario " .. self.name) end
  return self
end

function Drive:update()
  self.frame = self.frame + 1
  if coroutine.status(self.co) == "dead" then return end
  if self.frame > DRIVE_LIMIT then error("drive " .. self.name .. " did not finish in " .. DRIVE_LIMIT .. " frames", 0) end
  local ok, err = coroutine.resume(self.co)
  if not ok then
    error("drive " .. self.name .. ": " .. tostring(err) .. "\n" .. debug.traceback(self.co), 0)
  end
end

return Drive

-- {{FOOTER}}
