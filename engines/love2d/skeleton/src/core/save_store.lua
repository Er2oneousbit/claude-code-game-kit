-- ---------------------------------------------------------------------------
-- save_store.lua
-- Purpose : Save slots that survive crashes, corruption and game updates: a versioned envelope, a migration chain
--           from every old version, a fallback to the .bak copy, and a refusal to load (or overwrite) a save made
--           by a newer build. Matches data/golden/shell.json "save_load".
-- Usage   : local SaveStore = require("src.core.save_store")
--           local saves = SaveStore.new(store)                 -- store: src/core/text_store.lua
--           local r = saves:load(1)      -- r.envelope (nil or { format, version, data }), r.source, r.problems
--           saves:save(1, { level = 3, health = 9 })           -- atomic, keeps save_1.json.bak
--           pure parts: SaveStore.load_texts(primary_text, backup_text), SaveStore.migrate(envelope)
-- Notes   : No love.* calls. The file is {"format": "save", "version": N, "data": {...}}. MIGRATIONS is the
--           TEMPLATE chain the kit's vectors test (v2 renamed hp to health, v3 added difficulty): when your save
--           data changes shape, bump SAVE_VERSION and add one function (SOP-19). Never edit an old migration; old
--           saves in the wild still need it. After a load found a "newer" save, save() refuses that slot, so an
--           old build never destroys a newer build's progress.
--
-- Pseudocode (load_texts):
--   for primary, then backup: parse -> missing | unreadable | not a save | bad version | newer -> next
--   the first good one is migrated step by step up to SAVE_VERSION and returned with its source
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Json = require("src.core.json")
local AtomicFile = require("src.core.atomic_file")

local SaveStore = {}
SaveStore.__index = SaveStore

-- ---- Tunables ----------------------------------------------------------------
SaveStore.SAVE_VERSION = 3
SaveStore.FORMAT = "save"

-- MIGRATIONS[n] turns version-n data into version n+1 data (it may change the table in place).
SaveStore.MIGRATIONS = {
  [1] = function(data)
    if data.hp ~= nil then                 -- v2 renamed hp to health
      data.health = data.hp
      data.hp = nil
    end
    return data
  end,
  [2] = function(data)
    if data.difficulty == nil then data.difficulty = "normal" end   -- v3 added the difficulty of the run
    return data
  end,
}

function SaveStore.file_name(slot) return "save_" .. tostring(slot) .. ".json" end

-- envelope or nil, problem ("" when fine)
function SaveStore.parse(text)
  if text == nil then return nil, "missing" end
  local ok, env = Json.try_decode(text)
  if not ok then return nil, "unreadable" end
  if not Json.is_object(env) or env.format ~= SaveStore.FORMAT or not Json.is_object(env.data) then
    return nil, "not a save"
  end
  local v = env.version
  if type(v) ~= "number" or v ~= v or v ~= math.floor(v) or v < 1 then return nil, "bad version" end
  if v > SaveStore.SAVE_VERSION then return nil, "newer" end
  return env, ""
end

function SaveStore.migrate(env)
  env = Json.copy(env)
  while env.version < SaveStore.SAVE_VERSION do
    local step = SaveStore.MIGRATIONS[env.version]
    if not step then error("save: no migration from version " .. env.version, 0) end
    env.data = step(env.data)
    env.version = env.version + 1
  end
  return env
end

-- envelope at SAVE_VERSION or nil, source "primary" | "backup" | "none", problems (list of "<source>: <why>")
function SaveStore.load_texts(primary, backup)
  local problems = {}
  local sources = { { "primary", primary }, { "backup", backup } }
  for _, pair in ipairs(sources) do
    local env, problem = SaveStore.parse(pair[2])
    if env then return SaveStore.migrate(env), pair[1], problems end
    problems[#problems + 1] = pair[1] .. ": " .. problem
  end
  return nil, "none", problems
end

function SaveStore.new(store)
  return setmetatable({ store = store, refused = {} }, SaveStore)
end

-- { envelope, source, problems, newer } for a slot; newer = true when a newer build's save is on disk
function SaveStore:load(slot)
  local name = SaveStore.file_name(slot)
  local env, source, problems = SaveStore.load_texts(self.store:read(name),
                                                     self.store:read(name .. AtomicFile.BAK_SUFFIX))
  local newer = false
  for _, p in ipairs(problems) do
    if p:find(": newer$") then newer = true end
  end
  self.refused[tostring(slot)] = newer or nil
  return { envelope = env, source = source, problems = problems, newer = newer }
end

-- Writes data as the current version; raises when this slot holds a newer build's save. Returns the path.
function SaveStore:save(slot, data)
  if self.refused[tostring(slot)] then
    error("save: slot " .. tostring(slot) .. " holds a save from a newer version of the game; not overwriting it", 0)
  end
  local env = Json.object({ format = SaveStore.FORMAT, version = SaveStore.SAVE_VERSION,
                            data = Json.is_object(data) and data or Json.object(data or {}) })
  local name = SaveStore.file_name(slot)
  AtomicFile.write(self.store, name, Json.encode(env, { indent = 2 }) .. "\n", {
    is_good = function(old) return SaveStore.parse(old) ~= nil end })
  return self.store:path(name)
end

return SaveStore

-- {{FOOTER}}
