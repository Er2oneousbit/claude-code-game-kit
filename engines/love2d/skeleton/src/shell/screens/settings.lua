-- ---------------------------------------------------------------------------
-- settings.lua
-- Purpose : The settings screen: tabs Display, Audio, Controls, Accessibility, Language, one row per field of
--           the settings schema (src/core/settings.lua), applied as you change it. Controls lists the game
--           actions with their prompt glyphs, rebinds with "press a key" (the swap comes from Bindings.rebind),
--           marks conflicts and resets to defaults. Back (or cancel) saves settings.json.
-- Usage   : app:push("settings")  |  app:push("settings", { tab = "audio", focus = "master" })
-- Notes   : Focus starts on the tab bar: left/right switch tabs, down enters the rows; up from the first row goes
--           back to the tabs. Display changes apply at once in play (never in automated runs). Audio "mono" is
--           stored but LÖVE has no downmix for stereo sources: a game that needs it plays mono sources (verify).
--           ui_* actions are not rebindable here (see src/core/bindings.lua).
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Style = require("src.shell.style")
local Widgets = require("src.shell.widgets")
local Settings = require("src.core.settings")
local Json = require("src.core.json")
local Bindings = require("src.core.bindings")

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

local function percent(app) return function(v) return app:t("value.percent", { n = math.floor(v * 100 + 0.5) }) end end
local function times(app) return function(v) return app:t("value.times", { n = v }) end end

function SettingsScreen:enter(params)
  self.tab = params.tab or "display"
  self.on_tabs = params.focus == nil
  self.message, self.message_t = nil, 0
  self.capturing = nil
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

function SettingsScreen:display_rows()
  local app = self.app
  local d = app.settings.display
  local res_options = {}
  for _, r in ipairs(RESOLUTIONS) do res_options[#res_options + 1] = r[1] .. "x" .. r[2] end
  local res = Widgets.choice("resolution", function() return app:t("settings.display.resolution") end,
    function() return res_options end,
    function() return d.resolution[1] .. "x" .. d.resolution[2] end,
    function(v)
      local w, h = v:match("^(%d+)x(%d+)$")
      d.resolution[1], d.resolution[2] = tonumber(w), tonumber(h)
      self:changed("display")
    end,
    function(v)
      local w, h = v:match("^(%d+)x(%d+)$")
      if not w then return app:tv(v) end
      return app:t("value.resolution", { w = w, h = h })
    end)
  local cap = Widgets.choice("frame_cap", function() return app:t("settings.display.frame_cap") end,
    function() return Settings.FRAME_CAPS end, function() return d.frame_cap end,
    function(v) d.frame_cap = v; self:changed("display") end,
    function(v) if v == 0 then return app:t("opt.frame_cap.0") end return app:t("value.fps", { n = v }) end)
  return {
    self:field("display", "mode", "choice", Settings.DISPLAY_MODES),
    self:field("display", "vsync", "toggle"),
    cap, res,
    self:field("display", "ui_scale", "slider", 0.75, 2.0, 0.25),
    self:back_row(),
  }
end

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
  self.app:save_settings()
  self.app:pop()
end

function SettingsScreen:switch_tab(delta)
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
  self.lists[self.tab]:draw(ui, CONTENT_X, LIST_Y, CONTENT_W, { label_w = LABEL_W, max_h = LIST_BOTTOM - LIST_Y,
                                                                 prefix = "settings." .. self.tab })
  local hint = self.message or app:t("settings.hint")
  ui:label("settings.hint", hint, 16, H - 30, W - 32, 22,
           { align = "center", font = ui:font(Style.SMALL_PX), color = self.message and Style.color.accent
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
