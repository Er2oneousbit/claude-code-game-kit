-- ---------------------------------------------------------------------------
-- app.lua
-- Purpose : The runtime shell around the game: the screen stack (boot, title, main menu, settings, credits,
--           loading, play, pause, juice demo), input routing to the top screen, the player's settings applied at
--           runtime, the user-data folder (settings, saves, logs, crashes, telemetry, bug reports), localization,
--           subtitles, and the scripted smoke scenarios (drive.lua).
-- Usage   : main.lua: local App = require("src.shell.app"); local app = App.new(KIT); app:load()
--           then app:update(dt), app:draw() and the input callbacks; app.finish_request tells main.lua to end a
--           smoke run ({ marker = "DRIVE_DONE menus", code = 0 }).
--           screens: app:push("settings"), app:pop(), app:replace("play"), app:reset("title")
--           text: app:t("menu.play"), app:tp("apples", 3)   say a line: app:say("guide.welcome")
--           a game HUD: app:hud_font(12) (12 px at scale 1, following text size and UI scale), app:hud_font_size(12),
--           app:on_look_changed(function() ... end) to rebuild cached text when those settings change (#309)
--           sound: app:play_sound("hit", "sfx"), app:bus_volume("ambience")   music: app:play_music("combat")
-- Notes   : Only the top screen updates and gets input; screens marked transparent (pause) draw over the one
--           below. Actions go to the top screen in sorted order until one is used, so Esc (ui_cancel and pause)
--           backs out of a menu but pauses the game. Automated runs (smoke, test) never change the window mode,
--           never pause on focus loss, and play no sound. A debug build is a run from the source folder (not a
--           fused exe or a .love): it adds the Juice demo to the menu, the pseudo language, and F8 bug reports.
--           Volumes: the master slider is LÖVE's listener volume. A game with data/audio_events.json gets each bus's
--           volume from src/core/audio_access.lua along the bus and its parents (a slider never twice down one
--           branch: ambience under sfx follows sfx once); without that file a source gets settings.audio[bus], as
--           before. data/music.json (if present) plays through src/shell/music_player.lua on the music bus; neither
--           file ships with the skeleton, and automated runs never open the music output.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): a smoke run's drive is the only input; the real
--           keyboard, mouse and pads go through input:real_* and are ignored there (#276)
-- Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): hud_font_size, hud_font and on_look_changed, so a game
--           HUD follows access.text_scale and display.ui_scale like the menus (#309)
-- ---------------------------------------------------------------------------
local Json = require("src.core.json")
local Log = require("src.core.log")
local Settings = require("src.core.settings")
local TextStore = require("src.core.text_store")
local LogFile = require("src.core.log_file")
local Crash = require("src.core.crash")
local Telemetry = require("src.core.telemetry")
local SaveStore = require("src.core.save_store")
local I18n = require("src.core.i18n")
local Dialogue = require("src.core.dialogue")
local Narrator = require("src.shell.narrator")
local InputMap = require("src.core.input_map")
local Bindings = require("src.core.bindings")
local Version = require("src.version")
local Style = require("src.shell.style")
local UI = require("src.shell.ui")
local Input = require("src.shell.input")
local AudioAccess = require("src.core.audio_access")
local Subtitles = require("src.shell.subtitles")
local MusicPlayer = require("src.shell.music_player")
local Drive = require("src.shell.drive")
local BugReport = require("src.shell.bug_report")

local App = {}
App.__index = App

-- ---- Tunables ----------------------------------------------------------------
local I18N_DIR = "data/i18n/"
local DIALOGUE_FILE = "data/dialogue/sample.built.json"
local TOAST_S = 2.5
local BUG_KEY = "key:f8"
local SOUND_RATE = 22050
local EVENTS_FILE = "data/audio_events.json"   -- its "buses" decide the slider routing when it exists
local MUSIC_FILE = "data/music.json"           -- adaptive music (src/shell/music_player.lua) when it exists
local MUSIC_ROOT = "assets/audio/"             -- music.json's stem and stinger paths are relative to this
local MASTER_SLIDER = "master"                 -- applied as love.audio.setVolume, so left out of the bus chains

function App.is_debug_build()
  if love.filesystem.isFused() then return false end
  local source = love.filesystem.getSource() or ""
  return not source:lower():match("%.love$")
end

App.MAX_HISTORY = 50                    -- lines the dialogue history keeps (#167)

function App.new(kit)
  return setmetatable({ kit = kit, stack = {}, toasts = {}, sounds = {}, debug_build = App.is_debug_build(),
                        finish_request = nil, plant = false, time = 0, asked_consent = false,
                        next_frame = 0, look_listeners = {}, look = nil }, App)
end

local function seed_from(rest)
  for i, a in ipairs(rest or {}) do
    if a == "--seed" then return tonumber(rest[i + 1]) or rest[i + 1] end
  end
  return nil
end

local function load_tables()
  local tables = {}
  for _, file in ipairs(love.filesystem.getDirectoryItems(I18N_DIR)) do
    local loc = file:match("^(.+)%.json$")
    if loc then
      local ok, data = Json.try_decode(love.filesystem.read(I18N_DIR .. file) or "")
      if ok and Json.is_object(data) then
        tables[loc] = data
      else
        Log.error("i18n", I18N_DIR .. file .. " is not a JSON object: " .. tostring(data))
      end
    end
  end
  return tables
end

local function load_dialogue()
  local text = love.filesystem.read(DIALOGUE_FILE)
  if not text then return Dialogue.parse({ lines = {} }) end
  local ok, db = pcall(function() return Dialogue.parse(Json.decode(text)) end)
  if ok then return db end
  Log.warn("dialogue", DIALOGUE_FILE .. ": " .. tostring(db))
  return Dialogue.parse({ lines = {} })
end

-- The bus tree of data/audio_events.json, or nil when the game has no such file (or it has no buses).
local function load_buses()
  if not love.filesystem.getInfo(EVENTS_FILE) then return nil end
  local ok, data = Json.try_decode(love.filesystem.read(EVENTS_FILE) or "")
  if not ok or not Json.is_object(data) then
    Log.warn("audio", EVENTS_FILE .. " is not a JSON object: " .. tostring(data) .. " (sliders map by name)")
    return nil
  end
  if not Json.is_object(data.buses) or next(data.buses) == nil then return nil end
  return data.buses
end

-- The music player for data/music.json, or nil (no file, an automated run, no audio, or a broken setup: logged).
local function load_music(kit)
  if kit.automated or kit.headless or not love.audio or not love.filesystem.getInfo(MUSIC_FILE) then return nil end
  local ok, player = pcall(MusicPlayer.from_file, MUSIC_FILE, { root = MUSIC_ROOT })
  if ok then return player end
  Log.warn("music", "no music: " .. tostring(player))
  return nil
end

-- a short sine blip as a sound (no audio files needed)
local function make_sound(freq, seconds, noise)
  local n = math.floor(SOUND_RATE * seconds)
  local data = love.sound.newSoundData(n, SOUND_RATE, 16, 1)
  for i = 0, n - 1 do
    local t = i / SOUND_RATE
    local env = 1 - i / n
    local s = math.sin(2 * math.pi * freq * t)
    if noise then s = s * 0.6 + (love.math.random() * 2 - 1) * 0.4 end
    data:setSample(i, s * env * 0.5)
  end
  return love.audio.newSource(data, "static")
end

function App:load()
  local kit = self.kit
  self.store = TextStore.for_run(kit.data_dir)
  -- the log file first, so everything after lands in it
  local major, minor, rev = love.getVersion()
  self.log_file = LogFile.open(self.store, { name = Version.name, version = Version.version,
    extra = string.format("(LÖVE %d.%d.%d, %s)", major, minor, rev, love.system.getOS()) }, function(msg)
      print("[WARN] log: " .. msg) end)
  Log.on_line = function(line) self.log_file:write(line) end
  self.seed = seed_from(kit.rest)
  Crash.configure({ store = self.store, name = Version.name, version = Version.version, seed = self.seed,
                    tail = function(n) return self.log_file:tail(n) end })
  local problems, source
  self.settings, problems, source = Settings.load_from(self.store)
  self.settings_existed = source ~= "none"
  for _, p in ipairs(problems) do Log.warn("settings", "fixed: " .. p) end
  self.i18n = I18n.new(load_tables(), "en")
  self.saves = SaveStore.new(self.store)
  self.telemetry = Telemetry.new(self.store, function() return Settings.telemetry_allowed(self.settings) end,
                                 Telemetry.new_session(love.math.random))
  self.dialogue = load_dialogue()
  self.track = Dialogue.track(self.dialogue)
  self.objective, self.history = "", {}                  -- cognitive access (#167)
  self.narrator, self.last_narration = Narrator.new(self), ""   -- menu narration (#165)
  self.ui = UI.new(self)
  self.input = Input.new(self)
  self.subtitles = Subtitles.new(self)
  self.buses = load_buses()
  self.music = load_music(kit)
  if love.keyboard then love.keyboard.setKeyRepeat(true) end
  if love.audio and not kit.headless then
    local ok, err = pcall(function()
      self.sounds.move = make_sound(660, 0.03)
      self.sounds.accept = make_sound(880, 0.06)
      self.sounds.hit = make_sound(110, 0.14, true)
    end)
    if not ok then Log.warn("audio", "no sounds: " .. tostring(err)) end
  end
  self:apply_settings()
  if self.settings_existed then self:apply_display() end
  Log.info("shell", string.format("data folder %s (%s), locale %s, %s build", self.store:path(""), self.store.kind,
           self.i18n.locale, self.debug_build and "debug" or "release"))
  self.telemetry:event("session_start", Version.version)
  if kit.mode == "smoke" and kit.drive and self.store.kind == "love" then
    -- a scripted run changes settings and saves them: never in the player's own save folder (a hand-run
    -- `lovec . --smoke 120 --drive menus`); dev.py smoke always passes --data-dir
    Log.error("drive", "DRIVE_IGNORED " .. kit.drive .. ": a drive needs its own --data-dir (python tools/dev.py " ..
              "smoke --drive " .. kit.drive .. " uses build/smoke-data)")
    self:finish("DRIVE_IGNORED " .. kit.drive, 1)
  elseif kit.mode == "smoke" then
    self.drive = Drive.new(self, kit.drive)
    self.input.scripted = true   -- only the drive presses: no real keyboard, mouse or pad (#276)
  end
  self:push("boot")
end

-- ---- Settings ------------------------------------------------------------------------------------------------
function App:apply_settings()
  local s = self.settings
  self.ui:set_scale(s.access.text_scale * s.display.ui_scale, s.access.readable_font, s.access.line_spacing)
  local look = table.concat({ tostring(s.access.text_scale), tostring(s.display.ui_scale),
                              tostring(s.access.readable_font), tostring(s.access.line_spacing) }, "|")
  if self.look ~= nil and look ~= self.look then
    for _, fn in ipairs(self.look_listeners) do fn() end
  end
  self.look = look
  self.i18n:set_locale(self.kit.locale or s.language)
  if love.audio then love.audio.setVolume(self.kit.automated and 0 or s.audio.master) end
  self.bus_gains = self.buses and AudioAccess.user_bus_gains(self.buses, s.audio) or nil
  if self.music then self.music:set_volume(self:bus_volume("music")) end
end

-- The volume a source on `bus` gets from the sliders, master left out (it is the listener volume).
-- With data/audio_events.json: the bus chain (audio_access.lua); without it, or for a bus the file does not
-- name: settings.audio[bus], 1 when there is no such slider.
function App:bus_volume(bus)
  if self.bus_gains and self.buses[bus] ~= nil then
    return AudioAccess.chain_gain(self.buses, self.bus_gains, bus, MASTER_SLIDER)
  end
  return self.settings.audio[bus] or 1
end

-- Window mode, size and vsync. Never in automated runs (the smoke window must stay small and off-screen).
function App:apply_display()
  if self.kit.automated or not love.window or not love.window.isOpen() then return end
  local d = self.settings.display
  local ok, err = pcall(function()
    if d.mode == "windowed" then
      if love.window.getFullscreen() then love.window.setFullscreen(false) end
      local dw, dh = love.window.getDesktopDimensions()
      local w, h = d.resolution[1], d.resolution[2]
      local cw, ch = love.graphics.getDimensions()
      if w <= dw and h <= dh and (w ~= cw or h ~= ch) then love.window.updateMode(w, h) end
    else
      love.window.setFullscreen(true, d.mode == "fullscreen" and "exclusive" or "desktop")
    end
    love.window.setVSync(d.vsync and 1 or 0)
  end)
  if not ok then Log.warn("display", tostring(err)) end
end

-- Writes settings.json (atomic, keeps settings.json.bak); returns the path.
function App:save_settings()
  local ok, path = pcall(Settings.save_to, self.store, self.settings)
  if not ok then
    Log.error("settings", "not saved: " .. tostring(path))
    self:toast(self:t("toast.settings_failed"))
    return nil
  end
  Log.info("settings", "saved " .. path)
  self.telemetry:event("settings_saved", "")
  return path
end

function App:set_consent(value)
  self.settings.telemetry.consent = value
  if value ~= "unset" then self:save_settings() end
  Log.info("telemetry", "consent " .. value)
end

-- ---- Game HUD text (#309) ------------------------------------------------------------------------------------
-- The pixel size for HUD text that is `base` px at scale 1: the player's text size times UI scale.
function App:hud_font_size(base)
  local s = self.settings
  return Style.hud_font_size(base or Style.FONT_PX, s.access.text_scale, s.display.ui_scale)
end

-- A font at that size (the readable font and line spacing when the player chose them). Draw-time only.
function App:hud_font(base) return self.ui:font(self:hud_font_size(base), true) end

-- fn() runs after text size, UI scale, readable font or line spacing changed (rebuild cached text or layout)
function App:on_look_changed(fn) self.look_listeners[#self.look_listeners + 1] = fn end

-- ---- Text ------------------------------------------------------------------------------------------------------
function App:t(key, args) return self.i18n:t(key, args) end
function App:tp(key, n, args) return self.i18n:tp(key, n, args) end
-- a value the game made up (a number, a name) shown through a "{name}" template, so the pseudo check sees it
function App:tv(value) return self.i18n:t("value.raw", { v = value }) end

-- The label of a binding for the current glyph set: the glyph's own string if the table has one, else the
-- binding's name ("Space", "A", "Cross").
function App:binding_label(gname)
  if self.i18n:has("glyph." .. gname) then return self:t("glyph." .. gname) end
  local name = gname:match("^[^_]+_(.+)$") or gname
  name = name:gsub("_", " ")
  return self:tv(name:sub(1, 1):upper() .. name:sub(2))
end

function App:glyph_set()
  return Bindings.glyph_set(self.settings.input.glyphs, self.input.last_device)
end

-- The prompt for an action right now: glyph name and text label.
function App:prompt(action)
  local gset = self:glyph_set()
  local binding = Bindings.prompt_binding(self.settings.input.bindings, action, gset)
  if binding == "" then return "unknown", self:t("controls.unbound") end
  local gname = Bindings.glyph_name(gset, binding)
  return gname, self:binding_label(gname)
end

-- ---- Screens -------------------------------------------------------------------------------------------------
function App:top() return self.stack[#self.stack] end

function App:push(name, params)
  local module = require("src.shell.screens." .. name)
  local screen = setmetatable({ app = self, name = name }, { __index = module })
  self.stack[#self.stack + 1] = screen
  if screen.enter then screen:enter(params or {}) end
  Log.info("shell", "screen " .. name)
  self.telemetry:event("screen", name)
  return screen
end

function App:pop()
  local screen = table.remove(self.stack)
  if screen and screen.leave then screen:leave() end
  local top = self:top()
  if top and top.resume then top:resume() end
  return screen
end

function App:replace(name, params)
  local screen = table.remove(self.stack)
  if screen and screen.leave then screen:leave() end
  return self:push(name, params)
end

function App:reset(name, params)
  while #self.stack > 0 do
    local screen = table.remove(self.stack)
    if screen.leave then screen:leave() end
  end
  return self:push(name, params)
end

function App:find(name)
  for i = #self.stack, 1, -1 do
    if self.stack[i].name == name then return self.stack[i] end
  end
  return nil
end

-- ---- Input ---------------------------------------------------------------------------------------------------
function App:dispatch(action)
  -- accept first dismisses a subtitle line waiting for the player (access.subtitle_hold, #167)
  if action == "ui_accept" and self.track:holding() then self.track:dismiss() return true end
  local top = self:top()
  if top and top.action then return top:action(action) == true end
  return false
end

function App:binding_pressed(binding, isrepeat)
  if binding == BUG_KEY and self.debug_build then
    if not isrepeat then BugReport.capture(self) end
    return
  end
  local top = self:top()
  if not isrepeat and top and top.raw and top:raw(binding) then return end
  local actions = InputMap.actions_for(self.settings.input.bindings, binding)
  -- a held subtitle line (#167) takes the accept first: on a gamepad, south is accept and jump, and the line must go
  -- before the game jumps (found by the access sweep's gamepad run)
  for _, action in ipairs(actions) do
    if action == "ui_accept" and self.track:holding() then self.track:dismiss() return end
  end
  for _, action in ipairs(actions) do
    if not isrepeat or action:sub(1, 3) == "ui_" then
      if self:dispatch(action) then return end
    end
  end
end

-- drives and tests: as if a bound key was pressed
function App:inject(action) return self:dispatch(action) end

-- the real devices (main.lua's callbacks): ignored while a drive runs (#276)
function App:keypressed(key, _, isrepeat) self.input:real_key(key, isrepeat) end
function App:gamepadpressed(joystick, button) self.input:real_button(joystick, button) end
function App:gamepadaxis(joystick, axis, value) self.input:real_axis(joystick, axis, value) end
function App:mousemoved() self.input:real_mouse() end

function App:focus(focused)
  if focused or self.kit.automated then return end
  local top = self:top()
  if top and top.pausable then
    Log.info("shell", "focus lost: paused")
    self:push("pause")
  end
end

-- ---- Feedback ------------------------------------------------------------------------------------------------
function App:play_sound(name, bus)
  local source = self.sounds[name]
  if not source or self.kit.automated then return end
  source:stop()
  source:setVolume(self:bus_volume(bus or "sfx"))
  source:play()
end

function App:toast(text)
  self.toasts[#self.toasts + 1] = { text = text, t = TOAST_S }
end

-- Changes the music to a track of data/music.json on its planned beat, bar or phrase; the plan, or nil (no
-- music file, the first track, or already playing).
function App:play_music(track)
  if not self.music then return nil end
  local ok, plan = pcall(self.music.request, self.music, track)
  if ok then return plan end
  Log.warn("music", tostring(plan))
  return nil
end

-- Shows a dialogue line as a subtitle (respects subtitles / barks settings, priority and cooldown).
function App:say(id)
  local ok = self.track:play(id, self.settings)
  if ok then                                             -- the history for "What now?" and the history page (#167)
    local line = self.track:current().line
    self.history[#self.history + 1] = { name = line.name or "", text = self.subtitles:text_of(line) }
    if #self.history > App.MAX_HISTORY then table.remove(self.history, 1) end
  end
  return ok
end

-- the goal "What now?" shows on the pause menu (#167); "" clears it. Pass translated text (app:t()).
function App:set_objective(text) self.objective = text or "" end

function App:game_speed() return self.settings.access.game_speed end

-- ---- Leaving ---------------------------------------------------------------------------------------------------
function App:finish(marker, code)
  self.finish_request = { marker = marker, code = code or 0 }
end

function App:quit()
  Log.info("shell", "quit")
  self.telemetry:event("quit", "")
  if self.kit.automated and self.kit.drive then
    self:finish("DRIVE_DONE " .. self.kit.drive, self.drive and self.drive.exit_code or 0)
  else
    love.event.quit(0)
  end
end

-- ---- Frame -------------------------------------------------------------------------------------------------------
function App:update(dt)
  self.time = self.time + dt
  local cap = self.settings.display.frame_cap
  if cap and cap > 0 and not self.kit.automated then
    local now = love.timer.getTime()
    if self.next_frame > now then love.timer.sleep(self.next_frame - now) end
    self.next_frame = math.max(now, self.next_frame) + 1 / cap
  end
  if self.drive then self.drive:update(dt) end
  local top = self:top()
  if top and top.update then top:update(dt) end
  self.track:update(dt, self.settings.access.subtitle_hold)
  self.narrator:update()
  self.subtitles:update(dt)
  if self.music then self.music:update() end
  for i = #self.toasts, 1, -1 do
    self.toasts[i].t = self.toasts[i].t - dt
    if self.toasts[i].t <= 0 then table.remove(self.toasts, i) end
  end
end

-- the whole-number scale and offset that fit the 640x360 base into the window
function App:transform()
  local w, h = love.graphics.getDimensions()
  local s = math.max(1, math.floor(math.min(w / Style.BASE_W, h / Style.BASE_H)))
  return s, math.floor((w - Style.BASE_W * s) / 2), math.floor((h - Style.BASE_H * s) / 2)
end

function App:draw()
  local s, ox, oy = self:transform()
  self.view = { s = s, ox = ox, oy = oy }
  love.graphics.clear(0, 0, 0, 1)
  self.ui:begin_frame()
  love.graphics.push()
  love.graphics.translate(ox, oy)
  love.graphics.scale(s)
  love.graphics.setScissor(ox, oy, Style.BASE_W * s, Style.BASE_H * s)
  love.graphics.setColor(Style.color.bg)
  love.graphics.rectangle("fill", 0, 0, Style.BASE_W, Style.BASE_H)
  local first = #self.stack
  while first > 1 and self.stack[first].transparent do first = first - 1 end
  for i = first, #self.stack do
    local screen = self.stack[i]
    if screen.draw then screen:draw(self.ui) end
  end
  self.subtitles:draw(self.ui)
  local top = self:top()
  if self.plant and top and top.name == "main_menu" then   -- --drive pseudo-plant: one label too small for its text
    self.ui:label("plant.too_small", self:t("menu.settings"), 8, 8, 30, 18)
  end
  local ty = 8
  for i, toast in ipairs(self.toasts) do
    local font = self.ui:font()
    local w = math.min(Style.BASE_W - 32, font:getWidth(toast.text) + 24)
    local rh = self.ui:row_h(font)
    self.ui:panel((Style.BASE_W - w) / 2, ty, w, rh)
    self.ui:label("toast." .. i, toast.text, (Style.BASE_W - w) / 2, ty, w, rh, { align = "center" })
    ty = ty + rh + 4
  end
  love.graphics.setScissor()
  love.graphics.pop()
  self.ui:end_frame()
  love.graphics.setColor(1, 1, 1, 1)
end

return App

-- {{FOOTER}}
