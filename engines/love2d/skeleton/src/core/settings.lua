-- ---------------------------------------------------------------------------
-- settings.lua
-- Purpose : The player's settings: the built-in defaults, a schema per field, and a loader that never fails (a
--           missing or broken file gives defaults, a bad field is fixed and counted, unknown keys are kept so a
--           newer build's file survives an older one). Matches data/golden/shell.json "defaults" and
--           "settings_load".
-- Usage   : local Settings = require("src.core.settings")
--           local s, problems = Settings.load(text)         -- text may be nil (no file yet)
--           Settings.effective_shake(s)   -> 0 with reduce motion, else access.shake_scale
--           Settings.telemetry_allowed(s) -> only after an explicit yes
--           local text = Settings.encode(s)                 -- write it with src/core/atomic_file.lua
--           Settings.load_from(store) / Settings.save_to(store, s)   -- settings.json in the user-data folder
-- Notes   : No love.* calls. The schema below is the contract every engine of the kit shares (SOP-19): add a
--           field to DEFAULTS and SCHEMA together, and to the settings screen. Kinds: num (clamped to lo..hi),
--           bool, enum (one of a list), res (two whole numbers >= 1), and the language code (2..12 characters).
--
-- Pseudocode (load):
--   no text -> {} ; not JSON -> defaults + "unreadable" ; not an object -> defaults + "not an object"
--   copy every key; version = 1; language valid or "en"
--   per schema section: not an object -> problem, {}; per field: missing -> default, bad -> fixed + problem
--   input.bindings: per action a list of strings (non-strings dropped, a non-list keeps the default) + problems
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Json = require("src.core.json")
local Bindings = require("src.core.bindings")
local AtomicFile = require("src.core.atomic_file")

local Settings = {}

-- ---- Tunables ----------------------------------------------------------------
Settings.FILE = "settings.json"
Settings.VERSION = 1
Settings.DIFFICULTIES = { "story", "easy", "normal", "hard" }
Settings.COLORBLIND = { "none", "protanopia", "deuteranopia", "tritanopia" }
Settings.SUB_SIZES = { "small", "medium", "large", "xl" }
Settings.DISPLAY_MODES = { "windowed", "fullscreen", "borderless" }
Settings.FRAME_CAPS = { 0, 30, 60, 120, 144, 240 }
Settings.CONSENT = { "unset", "yes", "no" }
local LANG_MIN, LANG_MAX = 2, 12           -- "en" .. "zh-Hant-TW" and friends

local function defaults_table()
  return Json.object({
    version = Settings.VERSION,
    display = Json.object({ mode = "windowed", vsync = true, frame_cap = 0, resolution = Json.array({ 1920, 1080 }),
                            ui_scale = 1.0 }),
    audio = Json.object({ master = 1.0, music = 0.8, sfx = 1.0, ui = 1.0, voice = 1.0, mono = false }),
    language = "en",
    access = Json.object({ text_scale = 1.0, subtitles = true, subtitle_size = "medium", subtitle_background = 0.6,
                           speaker_names = true, subtitle_barks = false, captions_sfx = false, colorblind = "none",
                           reduce_motion = false, shake_scale = 1.0, flash_limit = true, hold_to_toggle = false,
                           difficulty = "normal", game_speed = 1.0, readable_font = false, line_spacing = 1.0,
                           subtitle_hold = false, timing_scale = 1.0, auto_repeat = false, narration = false }),
    input = Json.object({ bindings = Bindings.defaults(), deadzone = 0.2, invert_y = false, glyphs = "auto" }),
    telemetry = Json.object({ consent = "unset" }),
  })
end

-- section -> field -> rule; the order of SECTIONS is only for readable problem lists
Settings.SECTIONS = { "display", "audio", "access", "input", "telemetry" }
Settings.SCHEMA = {
  display = { mode = { "enum", Settings.DISPLAY_MODES }, vsync = { "bool" }, frame_cap = { "enum", Settings.FRAME_CAPS },
              resolution = { "res" }, ui_scale = { "num", 0.75, 2.0 } },
  audio = { master = { "num", 0, 1 }, music = { "num", 0, 1 }, sfx = { "num", 0, 1 }, ui = { "num", 0, 1 },
            voice = { "num", 0, 1 }, mono = { "bool" } },
  access = { text_scale = { "num", 0.75, 2.0 }, subtitles = { "bool" }, subtitle_size = { "enum", Settings.SUB_SIZES },
             subtitle_background = { "num", 0, 1 }, speaker_names = { "bool" }, subtitle_barks = { "bool" },
             captions_sfx = { "bool" }, colorblind = { "enum", Settings.COLORBLIND }, reduce_motion = { "bool" },
             shake_scale = { "num", 0, 1 }, flash_limit = { "bool" }, hold_to_toggle = { "bool" },
             difficulty = { "enum", Settings.DIFFICULTIES }, game_speed = { "num", 0.5, 1.0 },
             readable_font = { "bool" }, line_spacing = { "num", 1.0, 2.0 }, subtitle_hold = { "bool" },
             timing_scale = { "num", 1.0, 3.0 }, auto_repeat = { "bool" }, narration = { "bool" } },
  input = { deadzone = { "num", 0, 0.9 }, invert_y = { "bool" }, glyphs = { "enum", Bindings.GLYPH_SETS } },
  telemetry = { consent = { "enum", Settings.CONSENT } },
}

function Settings.defaults() return defaults_table() end

local function is_num(v) return type(v) == "number" and v == v end    -- NaN is not a number here

-- (value, problem?) for one field
local function fix(rule, value, default)
  local kind = rule[1]
  if kind == "bool" then
    if type(value) == "boolean" then return value, false end
    return default, true
  elseif kind == "num" then
    if not is_num(value) then return default, true end
    local clamped = math.min(math.max(value, rule[2]), rule[3])
    return clamped, clamped ~= value
  elseif kind == "enum" then
    for _, allowed in ipairs(rule[2]) do
      if type(allowed) == type(value) and value == allowed then return allowed, false end
    end
    return default, true
  elseif kind == "res" then
    if Json.is_array(value) and #value == 2 then
      local ok = true
      for i = 1, 2 do
        local n = value[i]
        if not (is_num(n) and n >= 1 and n == math.floor(n)) then ok = false end
      end
      if ok then return Json.array({ value[1], value[2] }), false end
    end
    return Json.copy(default), true
  end
  error("settings: unknown rule " .. tostring(kind))
end

local function fix_bindings(value, problems)
  local out = Bindings.defaults()
  if not Json.is_object(value) then
    problems[#problems + 1] = "input.bindings"
    return out
  end
  for _, action in ipairs(Json.sorted_keys(value)) do
    local list = value[action]
    if not Json.is_array(list) then
      problems[#problems + 1] = "input.bindings." .. action
    else
      local clean = Json.array({})
      for _, b in ipairs(list) do
        if type(b) == "string" then clean[#clean + 1] = b end
      end
      if #clean ~= #list then problems[#problems + 1] = "input.bindings." .. action end
      out[action] = clean
    end
  end
  return out
end

local function utf8_len(s)
  local ok, utf8 = pcall(require, "utf8")
  if ok and utf8 and utf8.len then return utf8.len(s) end
  local _, n = s:gsub("[^\128-\191]", "")                 -- count lead bytes
  return n
end

-- Settings from the file's text: settings, problems (a list of "section.field" strings).
function Settings.load(text)
  local problems = {}
  local raw = Json.object({})
  if text ~= nil then
    local ok, value = Json.try_decode(text)
    if not ok then return defaults_table(), { "unreadable" } end
    raw = value
  end
  if not Json.is_object(raw) then return defaults_table(), { "not an object" } end
  local defaults = defaults_table()
  local out = Json.copy(raw)
  out.version = Settings.VERSION
  local lang = raw.language
  if lang == nil then lang = "en" end
  local lang_len = type(lang) == "string" and utf8_len(lang) or nil
  if lang_len and lang_len >= LANG_MIN and lang_len <= LANG_MAX then
    out.language = lang
  else
    out.language = "en"
    if raw.language ~= nil then problems[#problems + 1] = "language" end
  end
  for _, section in ipairs(Settings.SECTIONS) do
    local fields = Settings.SCHEMA[section]
    local src = raw[section]
    if src == nil then src = Json.object({}) end
    if not Json.is_object(src) then
      problems[#problems + 1] = section
      src = Json.object({})
    end
    local sec = Json.copy(src)
    setmetatable(sec, getmetatable(Json.object({})))
    for _, name in ipairs(Json.sorted_keys(fields)) do
      local default = defaults[section][name]
      if src[name] ~= nil then
        local value, bad = fix(fields[name], src[name], default)
        if bad then problems[#problems + 1] = section .. "." .. name end
        sec[name] = value
      else
        sec[name] = Json.copy(default)
      end
    end
    if section == "input" then
      if src.bindings ~= nil then
        sec.bindings = fix_bindings(src.bindings, problems)
      else
        sec.bindings = Bindings.defaults()
      end
    end
    out[section] = sec
  end
  return out, problems
end

function Settings.effective_shake(s)
  if s.access.reduce_motion then return 0.0 end
  return s.access.shake_scale
end

function Settings.telemetry_allowed(s)
  return s.telemetry.consent == "yes"
end

function Settings.encode(s)
  return Json.encode(s, { indent = 2 }) .. "\n"
end

-- From the user-data folder (src/core/text_store.lua): settings, problems, source ("file", "backup", "none").
-- An unreadable settings.json falls back to settings.json.bak before it falls back to the defaults. A missing
-- settings.json with a complete settings.json.tmp (a crash in the middle of a save) is put back first.
local function is_object_text(text) local ok, v = Json.try_decode(text); return ok and Json.is_object(v) end

function Settings.load_from(store)
  local recovered = AtomicFile.recover(store, Settings.FILE, is_object_text)
  local text = store:read(Settings.FILE)
  if text ~= nil then
    local s, problems = Settings.load(text)
    if problems[1] ~= "unreadable" and problems[1] ~= "not an object" then
      if recovered then table.insert(problems, 1, Settings.FILE .. ": recovered from the " .. AtomicFile.TMP_SUFFIX) end
      return s, problems, "file"
    end
    local bak = store:read(Settings.FILE .. AtomicFile.BAK_SUFFIX)
    if bak ~= nil then
      local s2, problems2 = Settings.load(bak)
      if problems2[1] ~= "unreadable" and problems2[1] ~= "not an object" then
        table.insert(problems2, 1, "settings.json: " .. problems[1] .. ", used the .bak")
        return s2, problems2, "backup"
      end
    end
    return s, problems, "none"
  end
  -- no settings.json (and no complete .tmp) but a .bak: a crash between removing the old file and the rename
  local bak = store:read(Settings.FILE .. AtomicFile.BAK_SUFFIX)
  if bak ~= nil then
    local s, problems = Settings.load(bak)
    if problems[1] ~= "unreadable" and problems[1] ~= "not an object" then return s, problems, "backup" end
  end
  local s, problems = Settings.load(nil)
  return s, problems, "none"
end

-- Writes settings.json atomically (keeps settings.json.bak); returns the file's path for messages.
function Settings.save_to(store, s)
  AtomicFile.write(store, Settings.FILE, Settings.encode(s), { is_good = is_object_text })
  return store:path(Settings.FILE)
end

return Settings

-- {{FOOTER}}
