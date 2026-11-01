-- ---------------------------------------------------------------------------
-- test_user_data.lua
-- Purpose : The user-data files beyond the golden vectors: save slots through a store (backup fallback, the
--           newer-save guard), settings files (round trip, .bak fallback), the rotating game log, consent-gated
--           telemetry, and crash reports.
-- Usage   : python tools/dev.py test     (or --filter user_data)
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local Json = require("src.core.json")
local TextStore = require("src.core.text_store")
local SaveStore = require("src.core.save_store")
local Settings = require("src.core.settings")
local LogFile = require("src.core.log_file")
local Telemetry = require("src.core.telemetry")
local Crash = require("src.core.crash")
local T = {}

function T.test_save_and_load_a_slot()
  local saves = SaveStore.new(TextStore.memory())
  saves:save(2, { level = 4, health = 6 })
  local r = saves:load(2)
  A.eq(r.source, "primary")
  A.eq(r.envelope.version, SaveStore.SAVE_VERSION)
  A.eq(r.envelope.data.level, 4)
end

function T.test_corrupt_slot_falls_back_to_the_backup()
  local store = TextStore.memory()
  local saves = SaveStore.new(store)
  saves:save(1, { level = 1 })
  saves:save(1, { level = 2 })                            -- .bak = level 1
  store:write("save_1.json", '{"format": "save", "vers')   -- torn write
  local r = saves:load(1)
  A.eq(r.source, "backup")
  A.eq(r.envelope.data.level, 1)
  A.eq(#r.problems, 1)
end

function T.test_a_newer_save_is_never_overwritten()
  local store = TextStore.memory()
  store:write("save_1.json", Json.encode({ format = "save", version = SaveStore.SAVE_VERSION + 1, data = { x = 1 } }))
  local saves = SaveStore.new(store)
  local r = saves:load(1)
  A.truthy(r.newer)
  A.raises(function() saves:save(1, { x = 2 }) end, "refuses to overwrite")
  A.truthy(store:read("save_1.json"):find('"version":' .. (SaveStore.SAVE_VERSION + 1), 1, true))
end

function T.test_settings_round_trip_has_no_problems()
  local store = TextStore.memory()
  local s = Settings.defaults()
  s.audio.master = 0.5
  s.input.bindings.jump = Json.array({})                  -- an empty list stays a list
  Settings.save_to(store, s)
  local loaded, problems = Settings.load_from(store)
  A.eq(#problems, 0, table.concat(problems, ", "))
  A.eq(loaded.audio.master, 0.5)
  A.eq(Json.kind(loaded.input.bindings.jump), "array")
end

function T.test_settings_fall_back_to_the_bak()
  local store = TextStore.memory()
  local s = Settings.defaults()
  s.audio.music = 0.3
  Settings.save_to(store, s)
  Settings.save_to(store, s)                              -- .bak holds a good copy
  store:write("settings.json", "{broken")
  local loaded, problems, source = Settings.load_from(store)
  A.eq(source, "backup")
  A.eq(loaded.audio.music, 0.3)
  A.truthy(#problems >= 1)
end

function T.test_log_rotation_keeps_five()
  local store = TextStore.memory()
  for run = 1, 8 do
    local log = LogFile.open(store, { name = "G", version = "1.2.3" })
    log:write("run " .. run)
  end
  A.truthy(store:read("logs/game.log"):match("^G 1%.2%.3 started %d%d%d%d%-"), "version and time on line 1")
  A.truthy(store:read("logs/game.log"):find("run 8", 1, true))
  A.truthy(store:read("logs/game.1.log"):find("run 7", 1, true))
  A.truthy(store:read("logs/game.5.log"):find("run 3", 1, true))
  A.falsy(store:exists("logs/game.6.log"))
end

function T.test_log_tail()
  local log = LogFile.open(TextStore.memory(), { name = "G", version = "1" })
  for i = 1, LogFile.TAIL_LINES + 20 do log:write("line " .. i) end
  local tail = log:tail(3)
  A.eq(tail, "line " .. (LogFile.TAIL_LINES + 18) .. "\nline " .. (LogFile.TAIL_LINES + 19) .. "\nline "
       .. (LogFile.TAIL_LINES + 20))
end

function T.test_telemetry_needs_consent()
  local store = TextStore.memory()
  local allowed = false
  local tele = Telemetry.new(store, function() return allowed end, function() return 1.5 end)
  A.falsy(tele:event("screen", "title"))
  A.falsy(store:exists(Telemetry.FILE), "nothing written before consent")
  allowed = true
  A.truthy(tele:event("note", 'has "quotes", commas'))
  local text = store:read(Telemetry.FILE)
  A.truthy(text:find("^" .. Telemetry.HEADER .. "\n"))
  A.truthy(text:find(',1.50,note,"has ""quotes"", commas"', 1, true), text)
end

function T.test_crash_report_contents()
  local store = TextStore.memory()
  Crash.configure({ store = store, name = "G", version = "9.9.9", seed = 42,
                    tail = function() return "[INFO] last line" end })
  local path = Crash.write("boom", "stack here")
  A.truthy(path and path:find("crashes/crash_", 1, true), tostring(path))
  local name = path:match("memory:/(.+)$")
  local text = store:read(name)
  for _, want in ipairs({ "version: 9.9.9", "seed: 42", "error: boom", "stack here", "[INFO] last line" }) do
    A.truthy(text:find(want, 1, true), "crash file has " .. want)
  end
  local second = Crash.write("boom again", "")
  A.truthy(second ~= path, "two crashes in one second get two files")
end

return T

-- {{FOOTER}}
