-- ---------------------------------------------------------------------------
-- test_display_apply.lua
-- Purpose : The Display tab's Apply on the settings screen (#308) and the game HUD's text size (#309): the confirm
--           counts real time from the clock (not the frame dt), Back warns once then discards, and the HUD size
--           follows text size and UI scale.
-- Usage   : python tools/dev.py test     (or --filter display_apply)
-- Notes   : The settings screen runs on a stand-in app (no window): rows, actions and update() need no graphics.
--           The golden steps of src/core/display_staging.lua are in test_shell_golden.lua.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- Updated : 2026-11-14 with Claude (Opus 5.5, claude-opus-5-5): App.window_size under Windows display scaling (#308);
--           the first run takes the window's size as the setting
--           2026-11-14 with Claude (Opus 5.5, claude-opus-5-5): on_look_changed's stop function
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local Settings = require("src.core.settings")
local DisplayStaging = require("src.core.display_staging")
local SettingsScreen = require("src.shell.screens.settings")
local Style = require("src.shell.style")
local App = require("src.shell.app")
local T = {}

local function noop() end

-- a settings screen over a stand-in app; now() is the clock the screen reads
local function screen_with_clock()
  local clock = { t = 100 }
  local app = { settings = Settings.defaults(), saves = 0, popped = false }
  function app.t(_, key) return key end
  function app.tv(_, v) return tostring(v) end
  app.play_sound, app.apply_settings, app.apply_display = noop, noop, noop
  function app.save_settings(self) self.saves = self.saves + 1 end
  function app.pop(self) self.popped = true end
  local screen = setmetatable({ app = app, name = "settings" }, { __index = SettingsScreen })
  local saved_clock = SettingsScreen.clock
  SettingsScreen.clock = function() return clock.t end
  screen:enter({})
  return screen, app, clock, function() SettingsScreen.clock = saved_clock end
end

-- from the tab bar: into the rows, one step right on the mode row (a staged mode change)
local function stage_mode(screen)
  screen:action("ui_down")
  A.eq(screen:focus_id(), "display.mode")
  screen:action("ui_right")
end

local function press_apply(screen)
  for _ = 1, 10 do
    if screen:focus_id() == "display.apply" then break end
    screen:action("ui_down")
  end
  A.eq(screen:focus_id(), "display.apply")
  screen:action("ui_accept")
end

function T.test_mode_waits_for_apply_and_the_confirm_counts_real_time()
  local screen, app, clock, restore = screen_with_clock()
  local ok, err = pcall(function()
    stage_mode(screen)
    A.eq(app.settings.display.mode, "windowed", "nothing applied before Apply")
    press_apply(screen)
    A.eq(app.settings.display.mode, "fullscreen", "Apply set the mode")
    A.eq(screen:focus_id(), "confirm.keep", "the confirm opens with focus on Keep")
    A.eq(app.saves, 0, "a mode change is not saved until the confirm closes")
    screen:update(0)                                     -- the first reading starts the count
    screen:update(1000)                                  -- a huge game dt with the clock standing still: nothing
    A.eq(screen.staging:seconds(), 15)
    clock.t = clock.t + 14.2
    screen:update(0.016)
    A.eq(screen.staging:seconds(), 1, "14.2 real seconds later")
    A.eq(app.settings.display.mode, "fullscreen")
    clock.t = clock.t + 1.0
    screen:update(0.016)
    A.falsy(screen.staging:confirming(), "15 real seconds: reverted")
    A.eq(app.settings.display.mode, "windowed", "the mode that Apply replaced is back")
    A.eq(app.saves, 1, "saved once, after the revert")
    A.eq(screen:focus_id(), "display.mode")
  end)
  restore()
  if not ok then error(err, 0) end
end

function T.test_back_warns_once_then_discards()
  local screen, app, _, restore = screen_with_clock()
  local ok, err = pcall(function()
    stage_mode(screen)
    screen:action("ui_cancel")
    A.truthy(screen.staging.warned, "first Back warns")
    A.falsy(app.popped, "and stays")
    screen:action("ui_cancel")
    A.truthy(app.popped, "second Back leaves")
    A.eq(app.settings.display.mode, "windowed", "the staged mode was discarded")
  end)
  restore()
  if not ok then error(err, 0) end
end

function T.test_back_during_the_confirm_reverts_and_vsync_saves_at_once()
  local screen, app, _, restore = screen_with_clock()
  local ok, err = pcall(function()
    stage_mode(screen)
    press_apply(screen)
    screen:action("ui_cancel")
    A.falsy(screen.staging:confirming(), "Back closed the confirm")
    A.eq(app.settings.display.mode, "windowed", "and reverted")
    A.falsy(app.popped, "without leaving")
    screen:action("ui_down")                             -- mode -> vsync
    A.eq(screen:focus_id(), "display.vsync")
    screen:action("ui_accept")
    local saves = app.saves
    press_apply(screen)
    A.eq(app.settings.display.vsync, false)
    A.falsy(screen.staging:confirming(), "vsync needs no confirm")
    A.eq(app.saves, saves + 1, "Apply without a confirm saves at once")
  end)
  restore()
  if not ok then error(err, 0) end
end

function T.test_tick_at_ignores_frame_time()
  local st = DisplayStaging.new(Settings.defaults().display)
  st:stage("resolution", { 1280, 720 })
  A.eq(#st:apply(), 1)
  A.eq(#st:tick_at(50), 0)
  A.eq(st:seconds(), 15, "the first reading only starts the count")
  A.eq(#st:tick_at(64.5), 0)
  A.eq(st:seconds(), 1)
  local calls = st:tick_at(65.0)
  A.eq(calls[1][1], "resolution")
  A.eq(calls[1][2][1], 1920, "the replaced size is back")
end

function T.test_staging_an_equal_table_drops_the_change()
  local st = DisplayStaging.new(Settings.defaults().display)
  st:stage("resolution", { 1280, 720 })
  st:stage("resolution", { 1920.0, 1080 })               -- equal by value to the applied size
  A.falsy(st:has_pending())
end

function T.test_hud_font_size_follows_both_scales()
  A.eq(Style.hud_font_size(10, 1, 1), 10)
  A.eq(Style.hud_font_size(10, 1.5, 2), 30)
  A.eq(Style.hud_font_size(12, 0.75, 0.75), 7)
  A.eq(Style.hud_font_size(6, 0.75, 1), Style.MIN_FONT_PX, "never under the minimum")
end

function T.test_app_hud_size_and_look_listeners()
  local app = setmetatable({ settings = Settings.defaults(), look_listeners = {}, kit = { automated = true },
                             ui = { set_scale = noop }, i18n = { set_locale = noop } }, App)
  local heard = 0
  app:on_look_changed(function() heard = heard + 1 end)
  app:apply_settings()
  A.eq(heard, 0, "the first apply is no change")
  A.eq(app:hud_font_size(10), 10)
  app.settings.access.text_scale, app.settings.display.ui_scale = 1.5, 1.25
  app:apply_settings()
  A.eq(heard, 1, "text size and UI scale changed")
  A.eq(app:hud_font_size(10), 19)
  app.settings.audio.master = 0.3
  app:apply_settings()
  A.eq(heard, 1, "a volume change is not a look change")
  -- a screen that listens on each visit stops when it leaves: without that every visit adds a listener
  local other = 0
  local stop = app:on_look_changed(function() other = other + 1 end)
  A.eq(type(stop), "function", "on_look_changed returns its stop function")
  stop()
  app.settings.access.text_scale = 2.0
  app:apply_settings()
  A.eq(other, 0, "a stopped listener hears nothing")
  A.eq(heard, 2, "the others still hear")
  A.eq(#app.look_listeners, 1, "and it is gone from the list")
end

-- the windowed size in window units (#308, seen on a real window): Windows at 125 % scales a LÖVE window, so a
-- 1920x1080 setting once became a 2400x1350 window on a 1920x1200 screen
function T.test_window_size_follows_display_scaling()
  local w, h = App.window_size({ 1920, 1080 }, { 1920, 1200 }, { 1536, 960 })
  A.eq(w, 1536, "125 %: 1920 real pixels are 1536 window units")
  A.eq(h, 864)
  w, h = App.window_size({ 1920, 1080 }, { 1920, 1200 }, nil)
  A.eq(w, 1920, "no scaling known: the setting as it is")
  A.eq(h, 1080)
  A.eq(App.window_size({ 2560, 1440 }, { 1920, 1200 }, { 1536, 960 }), nil, "larger than the screen: left alone")
  A.eq(App.window_size({ 2560, 1440 }, { 1920, 1200 }, nil), nil)
  w, h = App.window_size({ 1920, 1200 }, { 1920, 1200 }, { 1280, 800 })
  A.eq(w, 1280, "150 %: the whole screen still fits")
  A.eq(h, 800)
end

-- a first run takes the window's size as the setting, in real pixels (#308: the setting said 1920x1080 while a
-- 1280x720 window was on screen, so a revert grew the window instead of restoring it)
function T.test_first_run_takes_the_window_size()
  local w, h = App.real_size({ 1280, 720 }, { 1920, 1200 }, { 1536, 960 })
  A.eq(w, 1600, "125 %: 1280 window units are 1600 real pixels")
  A.eq(h, 900)
  w, h = App.real_size({ 1280, 720 }, { 1920, 1200 }, nil)
  A.eq(w, 1280)
  A.eq(h, 720)
  local back_w, back_h = App.window_size({ App.real_size({ 1280, 720 }, { 1920, 1200 }, { 1536, 960 }) }, { 1920, 1200 },
                                         { 1536, 960 })
  A.eq(back_w, 1280, "window_size undoes real_size")
  A.eq(back_h, 720)
  local app = setmetatable({ kit = { automated = false }, settings = Settings.defaults() }, App)
  local saved_window, saved_graphics, saved_system = love.window, love.graphics, love.system
  love.system = { getOS = function() return "Linux" end }             -- no display scaling to look up
  love.window = { isOpen = function() return true end, getFullscreen = function() return false end,
                  getDesktopDimensions = function() return 1280, 800 end }
  love.graphics = setmetatable({ getDimensions = function() return 1024, 600 end }, { __index = saved_graphics })
  local ok, err = pcall(App.adopt_window_size, app)
  love.window, love.graphics, love.system = saved_window, saved_graphics, saved_system
  A.truthy(ok, tostring(err))
  A.eq(app.settings.display.resolution[1], 1024, "the setting is the window's size, not the 1920x1080 default")
  A.eq(app.settings.display.resolution[2], 600)
end

return T

-- {{FOOTER}}
