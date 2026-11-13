-- ---------------------------------------------------------------------------
-- settings.lua
-- Purpose : The settings screen: tabs Display, Audio, Controls, Accessibility, Language, one row per field of
--           the settings schema (src/core/settings.lua), applied as you change it. Controls lists the game
--           actions with their prompt glyphs, rebinds with "press a key" (the swap comes from Bindings.rebind),
--           marks conflicts and resets to defaults. Back (or cancel) saves settings.json. The Display tab waits for
--           Apply (#308): its rows show the staged value, Apply sends the changed fields, and a mode or resolution
--           change asks "Keep these display settings?" for 15 s of real time (src/core/display_staging.lua).
-- Usage   : app:push("settings")  |  app:push("settings", { tab = "audio", focus = "master" })
-- Notes   : Focus starts on the tab bar: left/right switch tabs, down enters the rows; up from the first row goes
--           back to the tabs. Display changes apply at once in play (never in automated runs). Audio "mono" is
--           stored but LÖVE has no downmix for stereo sources: a game that needs it plays mono sources (verify).
--           ui_* actions are not rebindable here (see src/core/bindings.lua).
--           Display tab rows: mode, vsync, frame cap, window size, UI scale, then Apply (dim until something is
--           staged) and Back; while the confirm runs, Keep and Revert replace Apply and Back and the rows are dim.
--           Back with staged changes warns once (the status line), a second Back discards them; Back or cancel
--           during the confirm reverts. Apply saves settings.json at once when no confirm opens; with a confirm,
--           the file is written when it closes (Keep, or after the revert), so a mode the screen cannot show is
--           never saved. The status line (bottom, its own row) shows the countdown, the warning and rebinding
--           messages.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): the Display tab waits for Apply, with a keep-or-revert
--           confirm for mode and resolution and a hint line (#308)
-- ---------------------------------------------------------------------------
local Style = require("src.shell.style")
local Widgets = require("src.shell.widgets")
local Settings = require("src.core.settings")
local Json = require("src.core.json")
local Bindings = require("src.core.bindings")
local DisplayStaging = require("src.core.display_staging")

local SettingsScreen = {}

-- ---- Tunables ----------------------------------------------------------------
local PRESETS_FILE = "data/input/presets.json"   -- the one-handed layouts (#166)
local PRESET_NAMES = { "one_hand_left", "one_hand_right" }
SettingsScreen.TABS = { "display", "audio", "controls", "access", "language" }
local RESOLUTIONS = { { 1280, 720 }, { 1600, 900 }, { 1920, 1080 }, { 2560, 1440 }, { 3840, 2160 } }
local CONTENT_X, CONTENT_W = 44, 552
local LABEL_W = 290
local TITLE_Y, LIST_BOTTOM = 10, 318        -- the tab bar and the rows follow the title's height
local MESSAGE_S = 3.0
local CELL_GAP = 8
local HINT_GAP = 4                          -- px between the Display tab's hint line and its rows
SettingsScreen.clock = function() return love.timer.getTime() end   -- the confirm's real-time clock (tests replace it)

local function percent(app) return function(v) return app:t("value.percent", { n = math.floor(v * 100 + 0.5) }) end end
local function times(app) return function(v) return app:t("value.times", { n = v }) end end

function SettingsScreen:enter(params)
  self.tab = params.tab or "display"
  self.on_tabs = params.focus == nil
  self.message, self.message_t = nil, 0
  self.capturing = nil
  self.staging = DisplayStaging.new(self.app.settings.display)   -- lives as long as the screen: tabs and language keep it
  self.last_apply, self.last_revert = nil, nil                    -- the latest calls, for the display drive
  self:build()
  if params.focus then self.lists[self.tab]:focus(params.focus) end
end

function SettingsScreen:changed(section)
  local app = self.app
  app:apply_settings()
  if section == "display" then app:apply_display() end
  self.dirty = true
end

function SettingsScreen:say(text)
  self.message, self.message_t = text, MESSAGE_S
end

-- ---- Row builders ------------------------------------------------------------------------------------------------
function SettingsScreen:field(section, name, kind, a, b, c)
  local app = self.app
  local s = app.settings
  local function get() return s[section][name] end
  local function set(v) s[section][name] = v; self:changed(section) end
  local label = function() return app:t("settings." .. section .. "." .. name) end
  if kind == "toggle" then
    return Widgets.toggle(name, label, get, set, function(v) return app:t(v and "value.on" or "value.off") end)
  elseif kind == "slider" then
    return Widgets.slider(name, label, get, set, a, b, c, (section == "display" or name == "text_scale")
                          and times(app) or percent(app))
  elseif kind == "choice" then
    return Widgets.choice(name, label, function() return a end, get, set,
                          function(v) return app:t("opt." .. name .. "." .. tostring(v)) end)
  end
  error("settings screen: unknown row kind " .. tostring(kind))
end

function SettingsScreen:back_row()
  return Widgets.button("back", function() return self.app:t("settings.back") end, function() self:close() end)
end

-- the Display rows read and write the staged values; the rows are dim while the confirm is open
function SettingsScreen:display_rows()
  local app = self.app
  local st = self.staging
  local function free() return not st:confirming() end
  local function staged(field, kind, a, b, c)
    local label = function() return app:t("settings.display." .. field) end
    local get = function() return st:value(field) end
    local set = function(v) st:stage(field, v) end
    local row
    if kind == "toggle" then
      row = Widgets.toggle(field, label, get, set, function(v) return app:t(v and "value.on" or "value.off") end)
    elseif kind == "slider" then
      row = Widgets.slider(field, label, get, set, a, b, c, times(app))
    else
      row = Widgets.choice(field, label, function() return a end, get, set,
                           function(v) return app:t("opt." .. field .. "." .. tostring(v)) end)
    end
    row.enabled = free
    return row
  end
  local res_options = {}
  for _, r in ipairs(RESOLUTIONS) do res_options[#res_options + 1] = r[1] .. "x" .. r[2] end
  local function res_text(r) return r[1] .. "x" .. r[2] end
  local res = Widgets.choice("resolution", function() return app:t("settings.display.resolution") end,
    function()
      local cur = res_text(st:value("resolution"))
      for _, o in ipairs(res_options) do if o == cur then return res_options end end
      local out = { cur }                                   -- a size from settings.json that is not in the list
      for _, o in ipairs(res_options) do out[#out + 1] = o end
      return out
    end,
    function() return res_text(st:value("resolution")) end,
    function(v)
      local w, h = v:match("^(%d+)x(%d+)$")
      st:stage("resolution", { tonumber(w), tonumber(h) })
    end,
    function(v)
      local w, h = v:match("^(%d+)x(%d+)$")
      if not w then return app:tv(v) end
      return app:t("value.resolution", { w = w, h = h })
    end)
  res.enabled = free
  local cap = Widgets.choice("frame_cap", function() return app:t("settings.display.frame_cap") end,
    function() return Settings.FRAME_CAPS end, function() return st:value("frame_cap") end,
    function(v) st:stage("frame_cap", v) end,
    function(v) if v == 0 then return app:t("opt.frame_cap.0") end return app:t("value.fps", { n = v }) end)
  cap.enabled = free
  local rows = {
    staged("mode", "choice", Settings.DISPLAY_MODES),
    staged("vsync", "toggle"),
    cap, res,
    staged("ui_scale", "slider", 0.75, 2.0, 0.25),
  }
  if st:confirming() then
    rows[#rows + 1] = Widgets.button("keep", function() return app:t("settings.keep") end, function() self:keep() end)
    rows[#rows + 1] = Widgets.button("revert", function() return app:t("settings.revert") end,
                                     function() self:revert() end)
  else
    local apply = Widgets.button("apply", function() return app:t("settings.apply") end, function() self:apply() end)
    apply.enabled = function() return st:has_pending() end
    rows[#rows + 1] = apply
    rows[#rows + 1] = self:back_row()
  end
  return rows
end

-- Rebuilds the Display list for the staging state (Apply and Back, or Keep and Revert), focus on `focus` when given
function SettingsScreen:refresh_display(focus)
  local old = self.lists and self.lists.display
  local keep_id = focus or (old and old:focused_id())
  self.lists.display = Widgets.list(self:display_rows(), { on_move = self.on_move })
  if keep_id then self.lists.display:focus(keep_id) end
  self.lists.display:fix_focus(1)
end

-- The set-value path for display fields: each call sets the setting, then the app applies display and scale.
function SettingsScreen:send(calls)
  if #calls == 0 then return end
  local d = self.app.settings.display
  for _, c in ipairs(calls) do
    local v = c[2]
    if type(v) == "table" then v = { v[1], v[2] } end
    d[c[1]] = v
  end
  self:changed("display")
end

function SettingsScreen:apply()
  if not self.staging:has_pending() or self.staging:confirming() then return end
  local calls = self.staging:apply()
  self.last_apply = calls
  self:send(calls)
  if self.staging:confirming() then
    self.on_tabs = false
    self:refresh_display("keep")                          -- focus on Keep
  else
    self.app:save_settings()
    self:refresh_display("apply")
  end
end

function SettingsScreen:keep()
  self.staging:keep()
  self.app:save_settings()
  self:refresh_display("mode")
end

-- after a revert (the Revert button, Back, or the countdown running out): set, save, redraw
function SettingsScreen:reverted(calls)
  self.last_revert = calls
  self:send(calls)
  self.app:save_settings()
  self:refresh_display("mode")
end

function SettingsScreen:revert() self:reverted(self.staging:revert()) end

function SettingsScreen:audio_rows()
  local rows = {}
  for _, bus in ipairs({ "master", "music", "sfx", "ui", "voice" }) do
    rows[#rows + 1] = self:field("audio", bus, "slider", 0, 1, 0.1)
  end
  rows[#rows + 1] = self:field("audio", "mono", "toggle")
  rows[#rows + 1] = self:back_row()
  return rows
end

function SettingsScreen:action_label(action) return self.app:t("action." .. action) end

-- the glyph set for the pad column (the keyboard set makes no sense there)
function SettingsScreen:pad_set()
  local gset = self.app:glyph_set()
  if gset == "keyboard" then return "generic" end
  return gset
end

function SettingsScreen:binding_row(action)
  local app = self.app
  local row = { id = "bind_" .. action, kind = "binding", cell = 0,
                text = function() return self:action_label(action) end }
  row.left = function() row.cell = 0 end
  row.right = function() row.cell = 1 end
  row.accept = function()
    local slot = row.cell
    self.capturing = { action = action, slot = slot }
    app.input:capture(slot == 0 and "key" or "pad", function(binding)
      self.capturing = nil
      if not binding then return end
      local new, conflicts = Bindings.rebind(app.settings.input.bindings, action, slot, binding)
      app.settings.input.bindings = new
      self.dirty = true
      if #conflicts > 0 then
        self:say(app:t("controls.swapped", { action = self:action_label(conflicts[1][1]) }))
      else
        self:say(app:t("controls.bound", { action = self:action_label(action) }))
      end
    end)
  end
  row.draw_value = function(ui, x, y, w, h, focused, lid)
    local list = app.settings.input.bindings[action] or {}
    local conflicts = {}
    for _, c in ipairs(Bindings.find_conflicts(app.settings.input.bindings)) do
      if c[2] == action then conflicts[c[3]] = true end
      if c[4] == action then conflicts[c[5]] = true end
    end
    local cw = (w - CELL_GAP) / 2
    for slot = 0, 1 do
      local cx = x + slot * (cw + CELL_GAP)
      local binding = list[slot + 1] or ""
      local gset = slot == 0 and "keyboard" or self:pad_set()
      local label, gname
      if binding == "" then
        gname, label = "unknown", app:t("controls.unbound")
      else
        gname = Bindings.glyph_name(gset, binding)
        label = app:binding_label(gname)
      end
      if focused and row.cell == slot then
        love.graphics.setColor(Style.color.focus)
        love.graphics.setLineWidth(1)
        love.graphics.rectangle("line", cx + 0.5, y + 3.5, cw - 1, h - 7, 3, 3)
      end
      local used = ui:glyph_cell(lid .. ".slot" .. slot, gname, label, cx + 6, y, h, { warn = conflicts[slot] })
      if conflicts[slot] then
        ui:label(lid .. ".slot" .. slot .. ".conflict", app:t("controls.conflict"), cx + 12 + used, y,
                 cw - used - 18, h, { color = Style.color.warn, font = ui:font(Style.SMALL_PX) })
      end
    end
  end
  return row
end

function SettingsScreen:controls_rows()
  local app = self.app
  local rows = {}
  for _, action in ipairs(Bindings.GAME_ACTIONS) do rows[#rows + 1] = self:binding_row(action) end
  rows[#rows + 1] = self:field("input", "glyphs", "choice", Bindings.GLYPH_SETS)
  rows[#rows + 1] = self:field("input", "deadzone", "slider", 0, 0.9, 0.05)
  rows[#rows + 1] = self:field("input", "invert_y", "toggle")
  rows[#rows + 1] = Widgets.button("reset", function() return app:t("controls.reset") end, function()
    app.settings.input.bindings = Bindings.defaults()
    self.dirty = true
    self:say(app:t("controls.reset_done"))
  end)
  -- one-handed layouts (#166, motor access), from data/input/presets.json
  for _, preset in ipairs(PRESET_NAMES) do
    rows[#rows + 1] = Widgets.button("preset_" .. preset, function() return app:t("controls.preset." .. preset) end,
      function()
        local ok, data = Json.try_decode(love.filesystem.read(PRESETS_FILE) or "")
        local chosen = ok and type(data) == "table" and data.presets and data.presets[preset]
        if not chosen then return end
        local bindings = Bindings.defaults()
        for action, pair in pairs(chosen.bindings) do bindings[action] = { pair[1], pair[2] } end
        app.settings.input.bindings = bindings
        self.dirty = true
        self:say(app:t("controls.preset_done"))
      end)
  end
  rows[#rows + 1] = self:back_row()
  return rows
end

function SettingsScreen:access_rows()
  local f = function(...) return self:field("access", ...) end
  return {
    f("text_scale", "slider", 0.75, 2.0, 0.25),
    f("subtitles", "toggle"),
    f("subtitle_size", "choice", Settings.SUB_SIZES),
    f("subtitle_background", "slider", 0, 1, 0.1),
    f("speaker_names", "toggle"),
    f("subtitle_barks", "toggle"),
    f("captions_sfx", "toggle"),
    f("colorblind", "choice", Settings.COLORBLIND),
    f("reduce_motion", "toggle"),
    f("shake_scale", "slider", 0, 1, 0.25),
    f("flash_limit", "toggle"),
    f("hold_to_toggle", "toggle"),
    f("difficulty", "choice", Settings.DIFFICULTIES),
    f("game_speed", "slider", 0.5, 1.0, 0.1),
    f("readable_font", "toggle"),                      -- #167: cognitive access
    f("line_spacing", "slider", 1.0, 2.0, 0.25),
    f("subtitle_hold", "toggle"),
    f("timing_scale", "slider", 1.0, 3.0, 0.5),        -- #166: motor access
    f("auto_repeat", "toggle"),
    f("narration", "toggle"),                          -- #165: menu narration
    self:back_row(),
  }
end

function SettingsScreen:language_rows()
  local app = self.app
  local function locales()
    local out = app.i18n:locales()
    if app.debug_build then out[#out + 1] = "pseudo" end
    return out
  end
  local lang = Widgets.choice("language", function() return app:t("settings.language.language") end, locales,
    function() return app.kit.locale or app.settings.language end,
    function(v)
      app.settings.language = v
      app.kit.locale = nil                       -- the player's choice beats --locale from here on
      self:changed("language")
    end,
    function(v)
      local t = app.i18n.tables[v]
      local name = t and t["language.name"] or (v == "pseudo" and "Pseudo" or v)
      return app:tv(name)
    end)
  return {
    lang,
    self:field("telemetry", "consent", "choice", Settings.CONSENT),
    self:back_row(),
  }
end

function SettingsScreen:build()
  local on_move = function() self.app:play_sound("move", "ui") end
  self.on_move = on_move
  self.lists = {
    display = Widgets.list(self:display_rows(), { on_move = on_move }),
    audio = Widgets.list(self:audio_rows(), { on_move = on_move }),
    controls = Widgets.list(self:controls_rows(), { on_move = on_move }),
    access = Widgets.list(self:access_rows(), { on_move = on_move }),
    language = Widgets.list(self:language_rows(), { on_move = on_move }),
  }
end

-- ---- Input ------------------------------------------------------------------------------------------------------
function SettingsScreen:close()
  local out, calls = self.staging:back()
  if out == "revert" then self:reverted(calls) return end  -- Back during the confirm puts the old display back
  if out == "warn" then return end                         -- the status line says so; Back again discards
  self:refresh_display()
  self.app:save_settings()
  self.app:pop()
end

function SettingsScreen:switch_tab(delta)
  if self.staging:confirming() then return end            -- the confirm keeps the Display tab up
  local idx = 1
  for i, name in ipairs(SettingsScreen.TABS) do if name == self.tab then idx = i end end
  self.tab = SettingsScreen.TABS[(idx - 1 + delta) % #SettingsScreen.TABS + 1]
  self.app:play_sound("move", "ui")
end

function SettingsScreen:focus_id()
  if self.on_tabs then return "tabs." .. self.tab end
  return self.tab .. "." .. tostring(self.lists[self.tab]:focused_id())
end

function SettingsScreen:action(name)
  if self.capturing then return true end
  if name == "ui_cancel" then self:close() return true end
  local list = self.lists[self.tab]
  if self.on_tabs then
    if name == "ui_left" then self:switch_tab(-1) return true end
    if name == "ui_right" then self:switch_tab(1) return true end
    if name == "ui_down" or name == "ui_accept" then
      self.on_tabs = false
      list.index = 1
      list:fix_focus(1)
      return true
    end
    return name == "ui_up"
  end
  if name == "ui_up" and list.index == 1 then self.on_tabs = true return true end
  if name == "ui_accept" then self.app:play_sound("accept", "ui") end
  return list:action(name)
end

function SettingsScreen:update(dt)
  -- the confirm counts real seconds (the clock), not dt: game speed, hitstop and fixed-step runs leave it alone
  if self.staging:confirming() and not self.hold_countdown then
    local calls = self.staging:tick_at(SettingsScreen.clock())
    if #calls > 0 then self:reverted(calls) end
  end
  if self.message_t > 0 then
    self.message_t = self.message_t - dt
    if self.message_t <= 0 then self.message = nil end
  end
end

-- ---- Draw -------------------------------------------------------------------------------------------------------
function SettingsScreen:draw(ui)
  local app = self.app
  local W, H = Style.BASE_W, Style.BASE_H
  local title_font = ui:font(Style.TITLE_PX * 0.75)
  ui:label("settings.title", app:t("settings.title"), 0, TITLE_Y, W, title_font:getHeight(),
           { align = "center", font = title_font, color = Style.color.accent })
  local TABS_Y = TITLE_Y + title_font:getHeight() + 4
  -- the tab bar: each tab as wide as its text
  local font = ui:font(Style.SMALL_PX)
  local widths, total = {}, 0
  for i, tab in ipairs(SettingsScreen.TABS) do
    widths[i] = font:getWidth(app:t("settings.tab." .. tab)) + 18
    total = total + widths[i] + 4
  end
  local tx = (W - total + 4) / 2
  local th = font:getHeight() + 10
  for i, tab in ipairs(SettingsScreen.TABS) do
    local selected = tab == self.tab
    if selected and self.on_tabs then
      ui:focus_box(tx, TABS_Y, widths[i], th)
    else
      love.graphics.setColor(selected and Style.color.row_focus or Style.color.row)
      love.graphics.rectangle("fill", tx, TABS_Y, widths[i], th, 3, 3)
    end
    if selected then                               -- the open tab is underlined, not just tinted
      love.graphics.setColor(Style.color.accent)
      love.graphics.rectangle("fill", tx + 4, TABS_Y + th - 3, widths[i] - 8, 2)
    end
    ui:label("settings.tab." .. tab, app:t("settings.tab." .. tab), tx, TABS_Y, widths[i], th,
             { align = "center", font = font, color = selected and Style.color.text or Style.color.dim })
    tx = tx + widths[i] + 4
  end
  local LIST_Y = TABS_Y + th + 10
  if self.tab == "display" then                            -- #308: say which changes wait for Apply
    local small = ui:font(Style.SMALL_PX)
    local text = app:t("settings.display_hint")
    local _, lines = small:getWrap(text, CONTENT_W)        -- wraps at a large text size or a long translation
    local hint_h = ui:line_h(small) * math.max(1, #lines)
    ui:label("settings.display_hint", text, CONTENT_X, LIST_Y - 4, CONTENT_W, hint_h,
             { align = "center", font = small, color = Style.color.dim, wrap = true })
    LIST_Y = LIST_Y - 4 + hint_h + HINT_GAP
  end
  self.lists[self.tab]:draw(ui, CONTENT_X, LIST_Y, CONTENT_W, { label_w = LABEL_W, max_h = LIST_BOTTOM - LIST_Y,
                                                                 prefix = "settings." .. self.tab })
  -- the status line: the confirm's countdown, the unapplied warning, a message, else the key hint
  local hint, id, loud = app:t("settings.hint"), "settings.hint", false
  if self.staging:confirming() then
    hint, id, loud = app:t("settings.confirm", { secs = self.staging:seconds() }), "settings.confirm", true
  elseif self.staging.warned then
    hint, id, loud = app:t("settings.unapplied"), "settings.unapplied", true
  elseif self.message then
    hint, loud = self.message, true
  end
  ui:label(id, hint, 16, H - 30, W - 32, 22,
           { align = "center", font = ui:font(Style.SMALL_PX), color = loud and Style.color.accent
             or Style.color.dim })
  if self.capturing then
    love.graphics.setColor(Style.color.overlay)
    love.graphics.rectangle("fill", 0, 0, W, H)
    local pw, ph = 380, 96
    local px, py = (W - pw) / 2, (H - ph) / 2
    ui:panel(px, py, pw, ph)
    local key = self.capturing.slot == 0 and "controls.press_key" or "controls.press_button"
    ui:label("settings.capture", app:t(key, { action = self:action_label(self.capturing.action) }), px, py + 18,
             pw, 26, { align = "center" })
    ui:label("settings.capture.hint", app:t("controls.capture_cancel"), px, py + 52, pw, 22,
             { align = "center", font = ui:font(Style.SMALL_PX), color = Style.color.dim })
  end
end

return SettingsScreen

-- {{FOOTER}}
