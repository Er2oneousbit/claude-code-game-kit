-- ---------------------------------------------------------------------------
-- test_platform_golden.lua
-- Purpose : The platform layer (src/core/platform.lua) against every case of data/golden/platform.json, then the
--           service the shell owns: the cached state file, the save hook, nothing written without
--           data/achievements.json.
-- Usage   : python tools/dev.py test     (or --filter platform)
-- Notes   : A step's calls are what the rules sent to their backend during that step; "fail_store" is the null
--           backend's hook (its next store_stats fails). Expected values come from the file at test time.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Golden = require("tests.helpers.golden")
local A = require("tests.assert")
local Json = require("src.core.json")
local Platform = require("src.core.platform")
local TextStore = require("src.core.text_store")
local SaveStore = require("src.core.save_store")
local PlatformSteam = require("src.core.platform_steam")

local FILE = "platform.json"
local SAMPLE = '{"stats": [{"id": "kills", "max": 100, "increment_only": true}], "achievements": [{"id": "first", '
  .. '"name": "First"}, {"id": "kills_10", "name": "Ten", "stat": "kills", "threshold": 10}]}'

local handlers = {}

function handlers.platform_format(case, tol, where)
  local mine = { state_format = Platform.FORMAT, state_file = Platform.STATE_FILE, state_version = Platform.STATE_VERSION,
    id_max = Platform.ID_MAX, stat_types = Platform.STAT_TYPES, presence_max_keys = Platform.PRESENCE_MAX_KEYS,
    presence_max_value_bytes = Platform.PRESENCE_MAX_VALUE_BYTES, cloud_modes = Platform.CLOUD_MODES,
    cloud_local_names = Platform.CLOUD_LOCAL_NAMES, cloud_local_suffixes = Platform.CLOUD_LOCAL_SUFFIXES,
    cloud_local_dirs = Platform.CLOUD_LOCAL_DIRS, overlay_pause_screens = Platform.OVERLAY_PAUSE_SCREENS,
    type = case.type, name = case.name }
  Golden.expect(mine, case, tol, where)
  return 12
end

function handlers.achievements_load(case, tol, where)
  for i, p in ipairs(case.points) do
    local text = p[2] ~= Json.null and p[2] or nil
    local defs, problems = Platform.achievements_load(text)
    Golden.expect(defs, p[3], tol, where .. " " .. p[1] .. ": defs")
    Golden.expect(problems, p[4], tol, where .. " " .. p[1] .. ": problems")
  end
  return #case.points * 2
end

function handlers.cloud_partition(case, tol, where)
  for _, p in ipairs(case.points) do Golden.expect(Platform.cloud_partition(p[1]), p[2], tol, where .. " '" .. p[1] .. "'") end
  return #case.points
end

function handlers.overlay(case, tol, where)
  for i, p in ipairs(case.points) do Golden.expect(Platform.overlay_action(p[1], p[2]), p[3], tol, where .. " " .. i) end
  return #case.points
end

local function step(p, nb, op)
  local kind = op[1]
  if kind == "fail_store" then
    nb.fail_stores = nb.fail_stores + 1
    return Json.null, {}
  elseif kind == "overlay" then return Platform.overlay_action(op[2], op[3]), {}
  elseif kind == "unlock" then return p:unlock(op[2])
  elseif kind == "set_stat" then return p:set_stat(op[2], op[3])
  elseif kind == "add_stat" then return p:add_stat(op[2], op[3])
  elseif kind == "flush" then return p:flush()
  elseif kind == "set_presence" then return p:set_presence(op[2], op[3])
  elseif kind == "clear_presence" then return p:clear_presence()
  elseif kind == "saved" then return p:saved(op[2])
  elseif kind == "connect" then return p:connect(op[2])
  elseif kind == "disconnect" then return p:disconnect()
  elseif kind == "reset_all" then return p:reset_all()
  end
  error("unknown step " .. tostring(kind), 0)
end

function handlers.platform_script(case, tol, where)
  local nb = Platform.null_backend()
  local p = Platform.rules(case.defs, nb, case.online, case.cloud)
  for i, s in ipairs(case.steps) do
    local out, calls = step(p, nb, s.op)
    local w = where .. " step " .. i .. " " .. tostring(s.op[1])
    Golden.expect(out, s.out, tol, w .. ": out")
    Golden.expect(calls, s.calls, tol, w .. ": calls")
    Golden.expect(p:state(), s.state, tol, w .. ": state")
    Golden.expect(p:presence_list(), s.presence, tol, w .. ": presence")
    Golden.expect(p.online, s.online, tol, w .. ": online")
  end
  return #case.steps * 5
end

function handlers.platform_state_load(case, tol, where)
  for _, p in ipairs(case.points) do
    local text = p[2] ~= Json.null and p[2] or nil
    local state, problems = Platform.state_load(case.defs, text)
    Golden.expect(state, p[3], tol, where .. " " .. p[1] .. ": state")
    Golden.expect(problems, p[4], tol, where .. " " .. p[1] .. ": problems")
  end
  return #case.points * 2
end

function handlers.null_backend(case, tol, where)
  local nb = Platform.null_backend()
  for i, s in ipairs(case.sends) do
    local call, got = s[1], Json.null
    if #call == 1 and call[1] == "fail_next_store" then nb.fail_stores = nb.fail_stores + 1 else got = nb:send(call) end
    local w = where .. " send " .. i
    Golden.expect(got, s[2], tol, w .. ": ok")
    Golden.expect(nb:remote(), s[3], tol, w .. ": remote")
    Golden.expect(nb:presence_list(), s[4], tol, w .. ": presence")
    Golden.expect(nb.cloud, s[5], tol, w .. ": cloud")
  end
  Golden.expect(nb.calls, case.calls, tol, where .. " calls")
  return #case.sends * 5
end

local suite = Golden.suite(Golden.load(FILE), handlers, FILE)

function suite.test_service_without_achievements_writes_nothing()
  local store = TextStore.memory()
  local ps = Platform.service(store, nil)
  A.falsy(ps.active)
  A.eq(ps:unlock("first"), "unknown")
  A.eq(ps:flush(), "nothing")
  A.eq(ps:saved("save_1.json"), "cloud")
  A.eq(next(store.files), nil, "no file without data/achievements.json")
end

function suite.test_service_caches_the_state_file()
  local store = TextStore.memory()
  local ps = Platform.service(store, SAMPLE)
  A.eq(ps:add_stat("kills", 12), "ok")
  A.eq(ps:unlock("first"), "unlocked")
  local again = Platform.service(store, SAMPLE)
  A.same(again.rules.unlocked, { "kills_10", "first" }, 0, "reloaded unlocks")
  A.eq(again:unlock("first"), "already")
  A.eq(store:read(Platform.STATE_FILE .. ".tmp"), nil, "no .tmp left behind")
end

function suite.test_the_save_store_calls_saved()
  local store = TextStore.memory()
  local ps = Platform.service(store, SAMPLE, nil, "api")
  local seen = {}
  local saves = SaveStore.new(store, function(name) seen[#seen + 1] = name ps:saved(name) end)
  saves:save(1, { level = 1 })
  A.same(seen, { "save_1.json" }, 0, "saved names")
  A.same(ps.backend.cloud, { "save_1.json" }, 0, "cloud writes")
end

function suite.test_the_overlay_pauses_only_over_play()
  local ps = Platform.service(TextStore.memory(), nil)
  A.eq(ps:overlay(true, "play"), "pause")
  A.eq(ps:overlay(true, "juice_demo"), "none")
  A.eq(ps:overlay(false, "pause"), "none")
end

-- ---- the luasteam adapter against a fake binding (no luasteam, no Steam) -------------------------------------

local function fake_steam(init_ok)
  local log = {}
  local fake = { log = log, store_ok = true }
  fake.Init = function() return init_ok end
  fake.RunCallbacks = function() log[#log + 1] = "RunCallbacks" end
  fake.UserStats = {
    SetAchievement = function(id) log[#log + 1] = "SetAchievement " .. id end,
    SetStatInt32 = function(id, v) log[#log + 1] = "SetStatInt32 " .. id .. " " .. v end,
    SetStatFloat = function(id, v) log[#log + 1] = "SetStatFloat " .. id .. " " .. v end,
    StoreStats = function() log[#log + 1] = "StoreStats" return fake.store_ok end,
    GetAchievement = function(id) return true, id == "first" end,
    GetStatInt32 = function() return true, 4 end,
    GetStatFloat = function() return true, 0.5 end,
  }
  fake.Friends = { SetRichPresence = function(k, v) log[#log + 1] = "SetRichPresence " .. k .. " " .. v end }
  return fake
end

function suite.test_the_steam_adapter_maps_calls_and_a_refused_store()
  local defs = Platform.achievements_load(SAMPLE)
  local fake = fake_steam(true)
  local steam = PlatformSteam.make(defs, TextStore.memory(), fake)
  A.truthy(steam, "a binding whose Init succeeds gives a backend")
  local remote = steam:remote()
  A.same(remote.unlocked, { "first" }, 0, "remote unlocks")
  A.eq(remote.stats.kills, 4)
  local rules = Platform.rules(defs, steam, true)
  A.eq((rules:add_stat("kills", 12)), "ok")
  A.same(fake.log, { "SetStatInt32 kills 12", "SetAchievement kills_10", "StoreStats" }, 0, "the unlock flushed")
  for i = #fake.log, 1, -1 do fake.log[i] = nil end
  fake.store_ok = false
  A.eq((rules:unlock("first")), "unlocked")
  A.falsy(rules.online, "a refused StoreStats takes the layer offline")
  A.eq((rules:set_presence("status", "Menu")), "ok")
  A.same(fake.log, { "SetAchievement first", "StoreStats" }, 0, "offline: presence waits")
  fake.Friends.OnGameOverlayActivated({ m_bActive = 1 })
  A.eq(steam:update(), true, "the overlay opening reaches update() once")
  A.eq(steam:update(), nil)
end

function suite.test_steam_starts_without_achievements()
  -- docs/PLATFORM.md section 6: an enabled adapter starts Steam whether or not data/achievements.json exists
  local fake = fake_steam(true)
  local steam = PlatformSteam.make(Platform.achievements_load(nil), TextStore.memory(), fake)
  A.truthy(steam, "no achievements file: Steam still starts")
  local ps = Platform.service(TextStore.memory(), nil, steam)
  A.eq(ps:set_presence("status", "Menu"), "ok")
  A.same(fake.log, { "SetRichPresence status Menu" }, 0, "presence reaches Steam without achievements")
end

function suite.test_a_late_user_stats_stored_failure_requeues_the_store()
  local fake = fake_steam(true)
  local store = TextStore.memory()
  local steam = PlatformSteam.make(Platform.achievements_load(SAMPLE), store, fake)
  local ps = Platform.service(store, SAMPLE, steam)
  A.eq(ps:add_stat("kills", 12), "ok")       -- the store had 4: 16, kills_10 unlocks and flushes
  A.truthy(ps.rules.online)
  fake.UserStats.OnUserStatsStored({ m_eResult = 2 })   -- k_EResultFail
  ps:update()
  A.falsy(ps.rules.online, "a late failure takes the layer offline")
  local pending = ps.rules:state().pending
  A.same(pending.stats, { "kills" }, 0, "the stat is queued again")
  A.same(pending.unlocks, { "kills_10" }, 0, "the unlock is queued again")
  for i = #fake.log, 1, -1 do fake.log[i] = nil end
  ps.rules:connect({})
  A.same(fake.log, { "SetStatInt32 kills 16", "SetAchievement kills_10", "StoreStats" }, 0, "connect sends it again")
  fake.UserStats.OnUserStatsStored({ m_eResult = 1 })
  ps:update()
  A.truthy(ps.rules.online, "a stored batch changes nothing")
end

function suite.test_the_steam_adapter_is_off_without_steam()
  A.eq(PlatformSteam.make(Platform.achievements_load(SAMPLE), TextStore.memory(), fake_steam(false)), nil,
       "Init false: the null backend")
  local ok = pcall(require, "luasteam")
  if not ok then A.eq(PlatformSteam.make(Platform.achievements_load(SAMPLE), TextStore.memory()), nil, "no luasteam") end
end

return suite

-- {{FOOTER}}
