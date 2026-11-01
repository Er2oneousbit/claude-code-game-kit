-- ---------------------------------------------------------------------------
-- save_store.lua
-- Purpose : Save slots that survive crashes, corruption and game updates: a versioned envelope, a migration chain
--           from every old version, a fallback to the .bak copy, and a refusal to load (or overwrite) a save made
--           by a newer build. Matches data/golden/shell.json "save_load".
-- Usage   : local SaveStore = require("src.core.save_store")
--           local saves = SaveStore.new(store)                 -- store: src/core/text_store.lua
--           local r = saves:load(1)      -- r.envelope (nil or { format, version, data }), r.source, r.problems,
--                                        -- r.newer (a newer build's save is there), r.recovered (from the .tmp)
--           saves:save(1, { level = 3, health = 9 })           -- atomic, keeps save_1.json.bak
--           pure parts: SaveStore.load_texts(primary_text, backup_text), SaveStore.migrate(envelope)
-- Notes   : No love.* calls. The file is {"format": "save", "version": N, "data": {...}}. MIGRATIONS is the
--           TEMPLATE chain the kit's vectors test (v2 renamed hp to health, v3 added difficulty): when your save
--           data changes shape, bump SAVE_VERSION and add one function (SOP-19). Never edit an old migration; old
--           saves in the wild still need it. save() reads the slot on disk itself and refuses it when it holds a
--           newer build's save (holds_newer: the primary is newer, or the primary is not a good save and the .bak
--           is newer), with or without an earlier load(), so an old build never destroys a newer build's progress.
--           A missing save_N.json with a complete save_N.json.tmp next to it (a crash between removing the old file
--           and the rename, Windows --data-dir) is put back in place first (AtomicFile.recover).
--
-- Pseudocode (load_texts):
--   for primary, then backup: parse -> missing | unreadable | not a save | bad version | newer -> next
--   the first good one is migrated step by step up to SAVE_VERSION and returned with its source
-- Pseudocode (save): recover a stranded .tmp -> read primary and .bak -> holds_newer? raise -> atomic write
--   (the old primary becomes the .bak only when it parses as a save, so a corrupt one never replaces a good .bak)
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

-- true when the slot holds a newer build's save that this build must not overwrite: the primary is newer, or
-- the primary is not a good save (missing, torn) and the .bak is newer. Same rule as load()'s "newer".
function SaveStore.holds_newer(primary, backup)
  local _, problem = SaveStore.parse(primary)
  if problem == "newer" then return true end
  if problem == "" then return false end
  local _, bak_problem = SaveStore.parse(backup)
  return bak_problem == "newer"
end

-- a .tmp worth recovering: a whole save envelope, of this version or a newer one
local function complete_save(text)
  local _, problem = SaveStore.parse(text)
  return problem == "" or problem == "newer"
end

function SaveStore.new(store)
  return setmetatable({ store = store }, SaveStore)
end

-- primary text, backup text, recovered (true when a stranded .tmp was put back as the primary)
function SaveStore:read_slot(slot)
  local name = SaveStore.file_name(slot)
  local recovered = AtomicFile.recover(self.store, name, complete_save)
  return self.store:read(name), self.store:read(name .. AtomicFile.BAK_SUFFIX), recovered
end

-- { envelope, source, problems, newer, recovered } for a slot; newer = true when a newer build's save is on disk
function SaveStore:load(slot)
  local primary, backup, recovered = self:read_slot(slot)
  local env, source, problems = SaveStore.load_texts(primary, backup)
  if recovered then
    table.insert(problems, 1, "primary: recovered from " .. SaveStore.file_name(slot) .. AtomicFile.TMP_SUFFIX)
  end
  return { envelope = env, source = source, problems = problems, newer = SaveStore.holds_newer(primary, backup),
           recovered = recovered }
end

-- Writes data as the current version; raises when this slot holds a newer build's save (read from disk now, not
-- remembered from a load). Returns the path.
function SaveStore:save(slot, data)
  local primary, backup = self:read_slot(slot)
  if SaveStore.holds_newer(primary, backup) then
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
