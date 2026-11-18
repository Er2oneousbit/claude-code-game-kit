-- ---------------------------------------------------------------------------
-- platform.lua
-- Purpose : The engine-free platform layer (#84, docs/PLATFORM.md): achievements, stats, rich presence, the
--           overlay's pause hook and cloud saves, kept here and sent to a backend. Every game runs the null
--           backend (it records every call); the luasteam adapter (src/core/platform_steam.lua) replaces it when
--           luasteam is installed. Checked against data/golden/platform.json (every case).
-- Usage   : local Platform = require("src.core.platform")
--           app.platform:unlock("first_win") ; app.platform:add_stat("enemies_defeated", 1)
--           app.platform:flush()                      -- at checkpoints (the shell flushes on pause and quit)
--           app.platform:set_presence("status", "In the crypt")
--           pure parts: Platform.achievements_load(text), cloud_partition(path), overlay_action(active, screen),
--           Platform.rules(defs, backend, online, cloud), Platform.null_backend(), Platform.state_load(defs, text)
-- Notes   : No love.* calls (the tests run it without a window). A backend is a table with available(),
--           remote(), send(call) (false only for a store_stats the store refused) and update(). JSON null is
--           Json.null: Python's dict.get(k, default) is get(t, k, default) here (a key holding null is null, not
--           the default). With no data/achievements.json every call is "unknown" and nothing is written, so a game
--           without achievements runs exactly as before. The state file is a cache, written only when it changed.
--
-- Pseudocode
--   rules op -> update local state -> online: send calls to the backend one at a time, in order
--   flush: set_stat per pending stat (definition order), set_achievement per pending unlock, store_stats;
--          a false store_stats keeps everything and goes offline; then cloud_write per pending cloud file
--   service: defs <- data/achievements.json ; state <- platform_state.json ; backend available ->
--          connect(backend.remote()) ; after every op: write the state file when it changed
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): Rules:store_failed and Service:update take a store
--           that failed after it was accepted (Steam's UserStatsStored) back onto the queue
-- ---------------------------------------------------------------------------
local Json = require("src.core.json")
local AtomicFile = require("src.core.atomic_file")
local Log = require("src.core.log")

local Platform = {}

-- ---- Tunables (the same in every engine: data/golden/platform.json "names and limits") ------
Platform.FORMAT = "platform_state"
Platform.STATE_VERSION = 1
Platform.STATE_FILE = "platform_state.json"
Platform.ACHIEVEMENTS_FILE = "data/achievements.json"
Platform.ID_MAX = 64
Platform.STAT_TYPES = { "int", "float" }
Platform.PRESENCE_MAX_KEYS = 30               -- Steam's rich presence limits (verify)
Platform.PRESENCE_MAX_VALUE_BYTES = 255
Platform.CLOUD_MODES = { "auto", "api" }
Platform.CLOUD_LOCAL_NAMES = { "settings.json", Platform.STATE_FILE, "telemetry.csv", "log_tail.txt" }
Platform.CLOUD_LOCAL_SUFFIXES = { ".tmp", ".log" }
Platform.CLOUD_LOCAL_DIRS = { "logs", "crashes", "captures" }
Platform.OVERLAY_PAUSE_SCREENS = { "play" }
Platform.CLOUD_MODE = "auto"                  -- "auto" (Steam Auto-Cloud, preferred) or "api"

-- ---- small helpers ----------------------------------------------------------------
local function is_null(v) return v == nil or v == Json.null end
local function get(t, k, default)
  local v = t[k]
  if v == nil then return default end
  return v
end
local function has(list, v)
  for _, x in ipairs(list) do if x == v then return true end end
  return false
end
local function remove(list, v)
  for i, x in ipairs(list) do if x == v then table.remove(list, i) return true end end
  return false
end
local function copy_list(list)
  local out = Json.array({})
  for i, x in ipairs(list) do out[i] = x end
  return out
end
local function count(t)
  local n = 0
  for _ in pairs(t) do n = n + 1 end
  return n
end

-- An achievement, stat or presence key name: 1 to 64 ASCII characters, a letter first.
function Platform.id_ok(v)
  return type(v) == "string" and #v > 0 and #v <= Platform.ID_MAX and v:match("^[A-Za-z][A-Za-z0-9_]*$") ~= nil
end

-- A finite number (true is never 1 here).
local function num_ok(v) return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge end
-- Whole by value, never by type.
local function whole(v) return num_ok(v) and math.floor(v) == v end
local function ok_for(kind, v) if kind == "int" then return whole(v) end return num_ok(v) end

local function clamp_stat(s, v)
  v = math.max(v, s.min)
  if not is_null(s.max) then v = math.min(v, s.max) end
  return v
end
function Platform.stat_initial(s) return clamp_stat(s, 0) end

local function empty_defs()
  return { version = Platform.STATE_VERSION, stats = Json.array({}), achievements = Json.array({}) }
end

-- data/achievements.json text (nil or "" = no file) -> defs, problems.
function Platform.achievements_load(text)
  if type(text) ~= "string" or text == "" then return empty_defs(), 0 end
  local ok, raw = Json.try_decode(text)
  if not ok or not Json.is_object(raw) then return empty_defs(), 1 end
  local problems = 0
  local stats, achievements, by_id = Json.array({}), Json.array({}), {}
  local raw_stats = get(raw, "stats", Json.array({}))
  if not Json.is_array(raw_stats) then
    raw_stats, problems = {}, problems + 1
  end
  for _, s in ipairs(raw_stats) do
    local good = Json.is_object(s) and Platform.id_ok(s.id) and by_id[s.id] == nil
    local kind, lo, hi, inc
    if good then
      kind, lo, hi, inc = get(s, "type", "int"), get(s, "min", 0), get(s, "max", Json.null), get(s, "increment_only", false)
      good = (kind == "int" or kind == "float") and ok_for(kind, lo)
          and (hi == Json.null or (ok_for(kind, hi) and hi >= lo)) and type(inc) == "boolean"
    end
    if good then
      local sdef = { id = s.id, type = kind, min = lo, max = hi, increment_only = inc }
      stats[#stats + 1] = sdef
      by_id[s.id] = sdef
    else
      problems = problems + 1
    end
  end
  local raw_ach = get(raw, "achievements", Json.array({}))
  if not Json.is_array(raw_ach) then raw_ach, problems = {}, problems + 1 end
  local seen = {}
  for _, a in ipairs(raw_ach) do
    local good = Json.is_object(a) and Platform.id_ok(a.id) and not seen[a.id] and type(a.name) == "string"
        and a.name ~= "" and type(get(a, "description", "")) == "string"
    local stat, threshold, every, sdef = Json.null, Json.null, Json.null, nil
    if good then
      stat, threshold, every = get(a, "stat", Json.null), get(a, "threshold", Json.null), get(a, "progress_every", Json.null)
      if not is_null(stat) then
        sdef = type(stat) == "string" and by_id[stat] or nil
        local kind = sdef and sdef.type or "float"
        good = sdef ~= nil and ok_for(kind, threshold) and threshold > Platform.stat_initial(sdef)
            and (is_null(sdef.max) or threshold <= sdef.max)
            and (is_null(every) or (ok_for(kind, every) and every > 0 and every < threshold))
      else
        good = is_null(threshold) and is_null(every)          -- a threshold without a stat is a mistake
      end
    end
    if good then
      seen[a.id] = true
      achievements[#achievements + 1] = { id = a.id, name = a.name, description = get(a, "description", ""),
        stat = stat, threshold = is_null(stat) and Json.null or threshold,
        progress_every = is_null(every) and Json.null or every }
    else
      problems = problems + 1
    end
  end
  return { version = Platform.STATE_VERSION, stats = stats, achievements = achievements }, problems
end

-- Which user-data file syncs: "cloud" or "local". ASCII-only folding (never a locale's lowercase).
function Platform.cloud_partition(path)
  local folded = path:gsub("[A-Z]", function(c) return string.char(c:byte() + 32) end):gsub("\\", "/")
  local parts = {}
  for p in folded:gmatch("[^/]+") do
    if p ~= "." then parts[#parts + 1] = p end
  end
  if #parts == 0 then return "local" end
  local name = parts[#parts]
  if (#parts > 1 and has(Platform.CLOUD_LOCAL_DIRS, parts[1])) or has(Platform.CLOUD_LOCAL_NAMES, name) then
    return "local"
  end
  for _, s in ipairs(Platform.CLOUD_LOCAL_SUFFIXES) do
    if #name >= #s and name:sub(-#s) == s then return "local" end
  end
  return "cloud"
end

-- The store overlay opened (active) or closed over `screen`: "pause" opens the pause menu; closing never resumes.
function Platform.overlay_action(active, screen)
  if active and has(Platform.OVERLAY_PAUSE_SCREENS, screen) then return "pause" end
  return "none"
end

local function sorted_pairs(t)
  local out = Json.array({})
  for _, k in ipairs(Json.sorted_keys(t)) do out[#out + 1] = Json.array({ k, t[k] }) end
  return out
end

-- ---- the null backend -----------------------------------------------------------
local NullBackend = {}
NullBackend.__index = NullBackend

-- The backend every game runs by default: records every call and keeps what a store would hold.
-- fail_stores is the test hook: the next N store_stats fail (a failed store lands nothing).
function Platform.null_backend()
  return setmetatable({ name = "null", calls = Json.array({}), unlocked = Json.array({}), stats = Json.object({}),
    presence = {}, cloud = Json.array({}), fail_stores = 0, staged_unlocks = {}, staged_stats = {} }, NullBackend)
end

function NullBackend:available() return true end
function NullBackend:update() end
function NullBackend:remote()
  local stats = Json.object({})
  for k, v in pairs(self.stats) do stats[k] = v end
  return { unlocked = copy_list(self.unlocked), stats = stats }
end

function NullBackend:send(call)
  self.calls[#self.calls + 1] = copy_list(call)
  local name, a, b = call[1], call[2], call[3]
  if name == "set_achievement" then
    if not has(self.staged_unlocks, a) then self.staged_unlocks[#self.staged_unlocks + 1] = a end
  elseif name == "set_stat" then
    self.staged_stats[a] = b
  elseif name == "store_stats" then
    if self.fail_stores > 0 then
      self.fail_stores = self.fail_stores - 1
      return false
    end
    for _, u in ipairs(self.staged_unlocks) do
      if not has(self.unlocked, u) then self.unlocked[#self.unlocked + 1] = u end
    end
    for k, v in pairs(self.staged_stats) do self.stats[k] = v end
    self.staged_unlocks, self.staged_stats = {}, {}
  elseif name == "reset_all_stats" then
    self.unlocked, self.stats, self.staged_unlocks, self.staged_stats = Json.array({}), Json.object({}), {}, {}
  elseif name == "set_presence" then
    if b == "" then self.presence[a] = nil else self.presence[a] = b end
  elseif name == "clear_presence" then
    self.presence = {}
  elseif name == "cloud_write" and not has(self.cloud, a) then
    self.cloud[#self.cloud + 1] = a
  end
  return true
end

function NullBackend:presence_list() return sorted_pairs(self.presence) end

-- ---- the rules ------------------------------------------------------------------
local Rules = {}
Rules.__index = Rules

-- PLATFORM.md section 3. Every operation returns out, calls (the calls it sent, in order).
function Platform.rules(defs, backend, online, cloud)
  local self = setmetatable({ defs = defs, backend = backend or Platform.null_backend(), online = online == true,
    cloud = cloud or "auto", stat_defs = {}, ach_defs = {}, presence = {}, sent = Json.array({}) }, Rules)
  for _, s in ipairs(defs.stats) do self.stat_defs[s.id] = s end
  for _, a in ipairs(defs.achievements) do self.ach_defs[a.id] = a end
  self:reset_local()
  return self
end

function Rules:reset_local()
  self.unlocked = {}
  self.stats = {}
  for _, s in ipairs(self.defs.stats) do self.stats[s.id] = Platform.stat_initial(s) end
  self.pending_stats, self.pending_unlocks, self.pending_cloud = {}, {}, {}
end

-- What the state file holds (and what the golden steps compare).
function Rules:state()
  local ps = Json.array({})
  for _, s in ipairs(self.defs.stats) do
    if has(self.pending_stats, s.id) then ps[#ps + 1] = s.id end
  end
  local stats = Json.object({})
  for k, v in pairs(self.stats) do stats[k] = v end
  return Json.object({ format = Platform.FORMAT, version = Platform.STATE_VERSION, unlocked = copy_list(self.unlocked),
    stats = stats, pending = Json.object({ stats = ps, unlocks = copy_list(self.pending_unlocks),
                                           cloud = copy_list(self.pending_cloud) }) })
end

-- Takes over a loaded state (state_load's), e.g. at start.
function Rules:restore(st)
  self.unlocked = copy_list(st.unlocked)
  self.stats = {}
  for k, v in pairs(st.stats) do self.stats[k] = v end
  self.pending_stats = copy_list(st.pending.stats)
  self.pending_unlocks = copy_list(st.pending.unlocks)
  self.pending_cloud = copy_list(st.pending.cloud)
end

function Rules:presence_list() return sorted_pairs(self.presence) end

function Rules:send(call)
  self.sent[#self.sent + 1] = Json.array(call)
  return self.backend:send(call)
end

function Rules:done(out)
  local calls = self.sent
  self.sent = Json.array({})
  return out, calls
end

function Rules:unlock_local(id)
  self.unlocked[#self.unlocked + 1] = id
  self.pending_unlocks[#self.pending_unlocks + 1] = id
end

function Rules:unlock(id)
  if self.ach_defs[id] == nil then return self:done("unknown") end
  if has(self.unlocked, id) then return self:done("already") end
  self:unlock_local(id)
  if self.online then self:flush_inner() end
  return self:done("unlocked")
end

function Rules:check(sid, old, now, notify)
  local did = false
  for _, a in ipairs(self.defs.achievements) do
    if a.stat == sid and not has(self.unlocked, a.id) then
      if now >= a.threshold then
        self:unlock_local(a.id)
        did = true
      elseif notify and self.online and not is_null(a.progress_every)
          and math.floor(now / a.progress_every) > math.floor(old / a.progress_every) then
        self:send({ "indicate_progress", a.id, now, a.threshold })
      end
    end
  end
  return did
end

-- v may be anything a caller (or a JSON file) passes: a non-number is refused, never coerced.
function Rules:set_stat(id, v)
  local s = self.stat_defs[id]
  if s == nil then return self:done("unknown") end
  if not ok_for(s.type, v) then return self:done("refused") end
  local c = clamp_stat(s, v)
  local old = self.stats[id]
  if s.increment_only and c < old then return self:done("refused") end
  if c == old then return self:done("same") end
  self.stats[id] = c
  if not has(self.pending_stats, id) then self.pending_stats[#self.pending_stats + 1] = id end
  if self:check(id, old, c, true) and self.online then self:flush_inner() end
  return self:done(c ~= v and "clamped" or "ok")
end

function Rules:add_stat(id, d)
  local s = self.stat_defs[id]
  if s == nil then return self:done("unknown") end
  if not ok_for(s.type, d) then return self:done("refused") end
  return self:set_stat(id, self.stats[id] + d)
end

function Rules:flush_inner()
  if not self.online then return "offline" end
  if #self.pending_stats == 0 and #self.pending_unlocks == 0 and #self.pending_cloud == 0 then return "nothing" end
  if #self.pending_stats > 0 or #self.pending_unlocks > 0 then
    for _, s in ipairs(self.defs.stats) do
      if has(self.pending_stats, s.id) then self:send({ "set_stat", s.id, self.stats[s.id] }) end
    end
    for _, id in ipairs(self.pending_unlocks) do self:send({ "set_achievement", id }) end
    if not self:send({ "store_stats" }) then
      self.online = false                     -- the store said no: keep everything, wait for connect()
      return "failed"
    end
    self.pending_stats, self.pending_unlocks = {}, {}
  end
  for _, p in ipairs(self.pending_cloud) do self:send({ "cloud_write", p }) end
  self.pending_cloud = {}
  return "sent"
end

function Rules:flush() return self:done(self:flush_inner()) end

function Rules:set_presence(key, value)
  if not Platform.id_ok(key) or type(value) ~= "string" or #value > Platform.PRESENCE_MAX_VALUE_BYTES then
    return self:done("refused")
  end
  if value == "" then
    if self.presence[key] == nil then return self:done("same") end
    self.presence[key] = nil
  else
    if self.presence[key] == value then return self:done("same") end
    if self.presence[key] == nil and count(self.presence) >= Platform.PRESENCE_MAX_KEYS then
      return self:done("refused")
    end
    self.presence[key] = value
  end
  if self.online then self:send({ "set_presence", key, value }) end
  return self:done("ok")
end

function Rules:clear_presence()
  if next(self.presence) == nil then return self:done("same") end
  self.presence = {}
  if self.online then self:send({ "clear_presence" }) end
  return self:done("ok")
end

-- The save code calls this after its atomic write succeeded; path is relative to the user-data folder.
function Rules:saved(path)
  local part = Platform.cloud_partition(path)
  if part == "cloud" and self.cloud == "api" then
    if self.online then
      self:send({ "cloud_write", path })
    elseif not has(self.pending_cloud, path) then
      self.pending_cloud[#self.pending_cloud + 1] = path
    end
  end
  return self:done(part)
end

function Rules:connect(remote)
  self.online = true
  local ru = get(remote, "unlocked", {})
  if type(ru) == "table" and ru ~= Json.null then
    for _, id in ipairs(ru) do
      if type(id) == "string" then
        if self.ach_defs[id] ~= nil and not has(self.unlocked, id) then self.unlocked[#self.unlocked + 1] = id end
        remove(self.pending_unlocks, id)
      end
    end
  end
  local rs = get(remote, "stats", {})
  if not Json.is_object(rs) then rs = {} end
  for _, s in ipairs(self.defs.stats) do
    local r = rs[s.id]
    if ok_for(s.type, r) then
      r = clamp_stat(s, r)
      local old = self.stats[s.id]
      local now
      if s.increment_only then
        if r >= old then remove(self.pending_stats, s.id) end
        now = math.max(old, r)
      else
        now = has(self.pending_stats, s.id) and old or r
      end
      self.stats[s.id] = now
      self:check(s.id, old, now, false)
    end
  end
  self:flush_inner()
  if self.online then
    for _, pair in ipairs(self:presence_list()) do self:send({ "set_presence", pair[1], pair[2] }) end
  end
  return self:done(self.online and "online" or "failed")
end

function Rules:disconnect()
  self.online = false
  return self:done("offline")
end

-- A store the backend accepted failed later (Steam's UserStatsStored): the same as a refused store_stats. The
-- batch's stats and unlocks (its set_stat / set_achievement calls) are pending again; offline until connect().
function Rules:store_failed(batch)
  self.online = false
  for _, call in ipairs(batch) do
    local name, id = call[1], call[2]
    if name == "set_stat" and self.stat_defs[id] ~= nil and not has(self.pending_stats, id) then
      self.pending_stats[#self.pending_stats + 1] = id
    elseif name == "set_achievement" and has(self.unlocked, id) and not has(self.pending_unlocks, id) then
      self.pending_unlocks[#self.pending_unlocks + 1] = id
    end
  end
  return self:done("failed")
end

-- Testing only: refused offline (a reset is never queued).
function Rules:reset_all()
  if not self.online then return self:done("offline") end
  self:reset_local()
  self:send({ "reset_all_stats", true })
  return self:done("reset")
end

-- platform_state.json text (nil or "" = no file) -> state, problems.
function Platform.state_load(defs, text)
  local p = Platform.rules(defs)
  if type(text) ~= "string" or text == "" then return p:state(), 0 end
  local ok, raw = Json.try_decode(text)
  if not ok or not Json.is_object(raw) or raw.format ~= Platform.FORMAT or raw.version ~= Platform.STATE_VERSION then
    return p:state(), 1
  end
  local problems = 0
  local function items(v, kind)
    if Json.kind(v) == kind then return v end
    if not is_null(v) then problems = problems + 1 end
    return {}
  end
  for _, id in ipairs(items(raw.unlocked, "array")) do
    if type(id) == "string" and p.ach_defs[id] ~= nil and not has(p.unlocked, id) then
      p.unlocked[#p.unlocked + 1] = id
    else
      problems = problems + 1
    end
  end
  local st = items(raw.stats, "object")
  for _, sid in ipairs(Json.sorted_keys(st)) do
    local s, v = p.stat_defs[sid], st[sid]
    if s == nil or not ok_for(s.type, v) then
      problems = problems + 1
    else
      p.stats[sid] = clamp_stat(s, v)
    end
  end
  local pending = items(raw.pending, "object")
  for _, sid in ipairs(items(pending.stats, "array")) do
    if type(sid) == "string" and p.stat_defs[sid] ~= nil and not has(p.pending_stats, sid) then
      p.pending_stats[#p.pending_stats + 1] = sid
    else
      problems = problems + 1
    end
  end
  for _, id in ipairs(items(pending.unlocks, "array")) do
    if type(id) == "string" and has(p.unlocked, id) and not has(p.pending_unlocks, id) then
      p.pending_unlocks[#p.pending_unlocks + 1] = id
    else
      problems = problems + 1
    end
  end
  for _, path in ipairs(items(pending.cloud, "array")) do
    if type(path) == "string" and Platform.cloud_partition(path) == "cloud" and not has(p.pending_cloud, path) then
      p.pending_cloud[#p.pending_cloud + 1] = path
    else
      problems = problems + 1
    end
  end
  return p:state(), problems
end

-- ---- the service the shell owns ---------------------------------------------------
local Service = {}
Service.__index = Service

-- The rules, the backend and the cached local state file (store: src/core/text_store.lua).
-- active is false without data/achievements.json (or with an empty one): nothing is ever written.
function Platform.service(store, achievements_text, backend, cloud)
  local defs, problems = Platform.achievements_load(achievements_text)
  if problems > 0 then
    Log.warn("platform", "data/achievements.json: " .. problems .. " problem(s), those entries were dropped")
  end
  local self = setmetatable({ store = store, backend = backend or Platform.null_backend(), last = "" }, Service)
  self.active = #defs.stats > 0 or #defs.achievements > 0
  self.rules = Platform.rules(defs, self.backend, false, cloud or Platform.CLOUD_MODE)
  if self.active then
    local text = store:read(Platform.STATE_FILE)
    local st, n = Platform.state_load(defs, text)
    if n > 0 then Log.warn("platform", Platform.STATE_FILE .. ": " .. n .. " problem(s), the store's copy wins") end
    self.rules:restore(st)
    self.last = text or ""
  end
  if self.backend:available() then self.rules:connect(self.backend:remote()) end
  self:persist()
  return self
end

function Service:persist()
  if not self.active then return end
  local text = Json.encode(self.rules:state(), { indent = 2 }) .. "\n"
  if text == self.last then return end
  local ok, err = pcall(AtomicFile.write, self.store, Platform.STATE_FILE, text, { backup = false })
  if ok then self.last = text else Log.warn("platform", Platform.STATE_FILE .. " not written: " .. tostring(err)) end
end

local function after(self, out)
  self:persist()
  return out
end

function Service:unlock(id) return after(self, (self.rules:unlock(id))) end
function Service:set_stat(id, v) return after(self, (self.rules:set_stat(id, v))) end
function Service:add_stat(id, d) return after(self, (self.rules:add_stat(id, d))) end
function Service:flush() return after(self, (self.rules:flush())) end           -- at checkpoints: level end, pause, quit
function Service:set_presence(k, v) return after(self, (self.rules:set_presence(k, v))) end
function Service:clear_presence() return after(self, (self.rules:clear_presence())) end
-- After an atomic save: its cloud partition (and, in api mode, the cloud write or its queue).
function Service:saved(path) return after(self, (self.rules:saved(path))) end
-- The store overlay opened or closed over `screen`: "pause" means open the pause menu.
function Service:overlay(active, screen) return Platform.overlay_action(active, screen) end
-- Each frame: the backend's callbacks; true / false when the store overlay opened / closed, else nil. A store that
-- failed late (a backend with take_store_failure: Steam's UserStatsStored) goes back on the queue, offline.
function Service:update()
  local overlay = self.backend:update()
  if self.backend.take_store_failure then
    local batch = self.backend:take_store_failure()
    while batch do
      Log.warn("platform", "a store the backend accepted failed later: kept for the next connect")
      after(self, (self.rules:store_failed(batch)))
      batch = self.backend:take_store_failure()
    end
  end
  return overlay
end

return Platform

-- {{FOOTER}}
