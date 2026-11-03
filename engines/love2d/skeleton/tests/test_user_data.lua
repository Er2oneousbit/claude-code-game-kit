-- ---------------------------------------------------------------------------
-- test_user_data.lua
-- Purpose : The user-data files beyond the golden vectors: save slots through a store (backup fallback, the
--           newer-save guard with and without a load, recovery from a stranded .tmp), settings files (round trip,
--           .bak fallback, .tmp recovery), the rotating game log and its tail, consent-gated telemetry, and crash
--           reports.
-- Usage   : python tools/dev.py test     (or --filter user_data)
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local Json = require("src.core.json")
local TextStore = require("src.core.text_store")
local SaveStore = require("src.core.save_store")
local AtomicFile = require("src.core.atomic_file")
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

function T.test_a_newer_save_is_refused_without_a_load()
  local store = TextStore.memory()
  local v99 = Json.encode({ format = "save", version = 99, data = { x = 1 } })
  store:write("save_1.json", v99)
  A.raises(function() SaveStore.new(store):save(1, { x = 2 }) end, "save() reads the disk itself")
  A.eq(store:read("save_1.json"), v99, "the v99 save is untouched")
  A.falsy(store:exists("save_1.json.bak"), "no .bak made")
  A.falsy(store:exists("save_1.json.tmp"), "nothing staged")
end

function T.test_a_newer_backup_behind_a_torn_save_is_refused()
  local store = TextStore.memory()
  store:write("save_1.json", '{"format": "save", "vers')                         -- torn
  store:write("save_1.json.bak", Json.encode({ format = "save", version = 99, data = {} }))
  A.truthy(SaveStore.holds_newer(store:read("save_1.json"), store:read("save_1.json.bak")))
  A.raises(function() SaveStore.new(store):save(1, { x = 2 }) end, "the next save would back up over the v99 .bak")
  A.falsy(SaveStore.holds_newer(Json.encode({ format = "save", version = 1, data = {} }),
                                store:read("save_1.json.bak")), "a good primary wins, like load()")
end

function T.test_a_missing_save_is_recovered_from_a_complete_tmp()
  local store = TextStore.memory()
  local saves = SaveStore.new(store)
  saves:save(1, { level = 1 })
  AtomicFile.stage(store, "save_1.json", Json.encode({ format = "save", version = SaveStore.SAVE_VERSION,
                                                       data = { level = 2 } }))
  store:remove("save_1.json")                             -- a crash between the remove and the rename (Windows)
  local r = saves:load(1)
  A.truthy(r.recovered)
  A.eq(r.source, "primary")
  A.eq(r.envelope.data.level, 2, "the finished write, not the .bak")
  A.eq(r.problems[1], "primary: recovered from save_1.json.tmp")
  A.falsy(store:exists("save_1.json.tmp"))
end

function T.test_a_torn_tmp_is_not_recovered()
  local store = TextStore.memory()
  local saves = SaveStore.new(store)
  saves:save(1, { level = 1 })
  saves:save(1, { level = 2 })                            -- .bak = level 1
  store:write("save_1.json.tmp", '{"format": "save", "ver')
  store:remove("save_1.json")
  local r = saves:load(1)
  A.falsy(r.recovered)
  A.eq(r.source, "backup")
  A.eq(r.envelope.data.level, 1)
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

function T.test_settings_recovered_from_a_complete_tmp()
  local store = TextStore.memory()
  local s = Settings.defaults()
  s.audio.music = 0.3
  Settings.save_to(store, s)
  s.audio.music = 0.7
  AtomicFile.stage(store, Settings.FILE, Settings.encode(s))
  store:remove(Settings.FILE)                             -- a crash between the remove and the rename (Windows)
  local loaded, problems, source = Settings.load_from(store)
  A.eq(source, "file")
  A.eq(loaded.audio.music, 0.7)
  A.eq(problems[1], "settings.json: recovered from the .tmp")
  A.falsy(store:exists(Settings.FILE .. ".tmp"))
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

function T.test_log_tail_after_1000_lines()
  local log = LogFile.open(TextStore.memory(), { name = "G", version = "1" })
  for i = 1, 1000 do log:write("line " .. i) end
  A.eq(log:tail(3), "line 998\nline 999\nline 1000")
  local _, lines = log:tail():gsub("\n", "")
  A.eq(lines + 1, LogFile.TAIL_LINES, "the full tail keeps TAIL_LINES lines")
end

function T.test_telemetry_needs_consent()
  local store = TextStore.memory()
  local allowed = false
  local tele = Telemetry.new(store, function() return allowed end, "0a1b2c3d", function() return 0 end)
  A.falsy(tele:event("screen", "title"))
  A.falsy(store:exists(Telemetry.FILE), "nothing written before consent")
  allowed = true
  A.truthy(tele:event("note", 'has "quotes", commas'))
  local text = store:read(Telemetry.FILE)
  A.truthy(text:find("^" .. Telemetry.HEADER .. "\n"))
  A.truthy(text:find('1970-01-01T00:00:00Z,0a1b2c3d,note,"has ""quotes"", commas"', 1, true), text)
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
