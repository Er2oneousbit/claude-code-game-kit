-- ---------------------------------------------------------------------------
-- platform_steam.lua
-- Purpose : The Steam backend for the platform layer (#84, docs/PLATFORM.md) through luasteam (MIT, the
--           uspgamedev binding; v6 names), used only when luasteam loads and Steam answers. Without it,
--           PlatformSteam.make() returns nil and the game runs the null backend exactly as before.
-- Usage   : local backend = PlatformSteam.make(defs, store)       -- nil: no luasteam or no Steam
--           app.platform = Platform.service(store, text, backend)
--           tests: PlatformSteam.make(defs, store, fake_binding)  -- a table shaped like luasteam's
-- Notes   : Gated at run time: pcall(require, "luasteam"), so a game without the native module (luasteam.dll /
--           .so next to the executable, which the kit does not ship) starts as before. Names follow luasteam
--           v6's docs: Steam.Init, Steam.RunCallbacks, Steam.UserStats.SetAchievement / SetStatInt32 /
--           SetStatFloat / StoreStats / GetAchievement / GetStatInt32 / GetStatFloat / IndicateAchievementProgress /
--           ResetAllStats, Steam.Friends.SetRichPresence / ClearRichPresence / OnGameOverlayActivated,
--           Steam.RemoteStorage.FileWrite (verify against the installed luasteam). Only StoreStats returning false
--           counts as a failed store (a later UserStatsStored failure is not seen, verify). No love.* calls.
--
-- Pseudocode
--   make: no binding (require fails) -> nil ; Init() false -> nil ; else a backend over Steam.UserStats etc.
--   send(call): the matching luasteam call; store_stats returns what StoreStats returned
--   remote: GetAchievement / GetStatInt32 / GetStatFloat for every defined id
--   update: RunCallbacks() ; OnGameOverlayActivated sets the overlay state update() returns once
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Log = require("src.core.log")

local PlatformSteam = {}
PlatformSteam.__index = PlatformSteam

-- ---- Tunables ----------------------------------------------------------------
PlatformSteam.MODULE = "luasteam"

-- The Steam backend, or nil. binding: a luasteam-shaped table (tests); nil loads the real module.
function PlatformSteam.make(defs, store, binding)
  local steam = binding
  if steam == nil then
    local ok, lib = pcall(require, PlatformSteam.MODULE)
    if not ok then return nil end              -- no luasteam: the null backend (the usual case)
    steam = lib
  end
  if not steam.Init() then
    Log.warn("platform", "luasteam is installed but Steam did not start (the null backend runs)")
    return nil
  end
  local self = setmetatable({ name = "steam", steam = steam, defs = defs, store = store, overlay = nil }, PlatformSteam)
  if steam.Friends then
    steam.Friends.OnGameOverlayActivated = function(data)
      self.overlay = data.m_bActive == 1 or data.m_bActive == true
    end
  end
  return self
end

function PlatformSteam:available() return true end

local function stat_type(defs, id)
  for _, s in ipairs(defs.stats) do
    if s.id == id then return s.type end
  end
  return "float"
end

function PlatformSteam:remote()
  local us = self.steam.UserStats
  local unlocked, stats = {}, {}
  for _, a in ipairs(self.defs.achievements) do
    local ok, achieved = us.GetAchievement(a.id)
    if ok and achieved then unlocked[#unlocked + 1] = a.id end
  end
  for _, s in ipairs(self.defs.stats) do
    local ok, v
    if s.type == "int" then ok, v = us.GetStatInt32(s.id) else ok, v = us.GetStatFloat(s.id) end
    if ok then stats[s.id] = v end
  end
  return { unlocked = unlocked, stats = stats }
end

function PlatformSteam:send(call)
  local s, name, a, b = self.steam, call[1], call[2], call[3]
  if name == "set_achievement" then
    s.UserStats.SetAchievement(a)
  elseif name == "set_stat" then
    if stat_type(self.defs, a) == "int" then s.UserStats.SetStatInt32(a, math.floor(b)) else s.UserStats.SetStatFloat(a, b) end
  elseif name == "store_stats" then
    return s.UserStats.StoreStats() and true or false
  elseif name == "indicate_progress" then
    s.UserStats.IndicateAchievementProgress(a, math.floor(b), math.floor(call[4]))
  elseif name == "reset_all_stats" then
    s.UserStats.ResetAllStats(a)
  elseif name == "set_presence" then
    s.Friends.SetRichPresence(a, b)
  elseif name == "clear_presence" then
    s.Friends.ClearRichPresence()
  elseif name == "cloud_write" then
    local text = self.store:read(a)
    if text and s.RemoteStorage then s.RemoteStorage.FileWrite(a, text, #text) end
  end
  return true
end

-- Each frame: runs Steam's callbacks; returns true / false once when the overlay opened / closed, else nil.
function PlatformSteam:update()
  self.steam.RunCallbacks()
  local changed = self.overlay
  self.overlay = nil
  return changed
end

return PlatformSteam

-- {{FOOTER}}
