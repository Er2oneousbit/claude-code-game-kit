-- ---------------------------------------------------------------------------
-- text_store.lua
-- Purpose : The game's user-data folder as one small interface, so settings, saves, logs, crash files and
--           telemetry never care where they live: the save folder (love.filesystem), an absolute folder given
--           with --data-dir (io.open, so tests can inspect the files), or memory (unit tests).
-- Usage   : local TextStore = require("src.core.text_store")
--           local store = TextStore.for_run(KIT.data_dir)  -- --data-dir if given, else the save folder
--           store:read("settings.json") -> text or nil      store:write("logs/game.log", text)
--           store:append(name, text)  store:remove(name)  store:rename(from, to)  store:exists(name)
--           store:path(name) -> the absolute path, for messages and the proof lines dev.py prints
-- Notes   : Names are folder-style paths relative to the folder ("crashes/crash_1.txt"); parent folders are
--           created on write. Binary data (PNG) is fine: every backend writes bytes as they are.
--           Folder store: io.open plus a small mkdir through LuaJIT's FFI (Lua has none). Its rename is real
--           (can_rename = true); on Windows it does not replace an existing target, so remove the target first
--           (atomic_file.lua does). io.open takes the path in the system code page on Windows, so keep
--           --data-dir paths ASCII there (verify for other paths).
--           Save-folder store: love.filesystem has no rename (can_rename = false; atomic_file.lua writes and
--           verifies instead), and read() ignores files that live in the game's own folder, not the save folder.
--           love.filesystem works without a window, so tests use it too.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local TextStore = {}

-- ---- Tunables ----------------------------------------------------------------
local POSIX_DIR_MODE = 493                 -- 0755
local WIN_UTF8 = 65001                     -- CP_UTF8 for MultiByteToWideChar
local WIN_PATH_MAX = 32768

local function parent_of(path)
  return path:match("^(.*)[/\\][^/\\]+$")
end

-- ---- mkdir through the FFI (falls back to os.execute when the FFI is missing) -----------------------
local mkdir_one
do
  local ok_ffi, ffi = pcall(require, "ffi")
  if ok_ffi and ffi.os == "Windows" then
    pcall(ffi.cdef, [[
      int MultiByteToWideChar(unsigned int cp, unsigned long flags, const char *src, int srclen,
                              uint16_t *dst, int dstlen);
      int CreateDirectoryW(const uint16_t *path, void *security);
    ]])
    mkdir_one = function(path)
      local buf = ffi.new("uint16_t[?]", WIN_PATH_MAX)
      if ffi.C.MultiByteToWideChar(WIN_UTF8, 0, path, -1, buf, WIN_PATH_MAX) == 0 then return false end
      return ffi.C.CreateDirectoryW(buf, nil) ~= 0
    end
  elseif ok_ffi then
    pcall(ffi.cdef, "int mkdir(const char *path, unsigned int mode);")
    mkdir_one = function(path) return ffi.C.mkdir(path, POSIX_DIR_MODE) == 0 end
  else
    mkdir_one = function(path)
      local sep = package.config:sub(1, 1)
      if sep == "\\" then return os.execute('mkdir "' .. path:gsub("/", "\\") .. '" 2>nul') == 0 end
      return os.execute("mkdir -p '" .. path .. "' 2>/dev/null") == 0
    end
  end
end

-- Creates path and every missing parent. Existing folders are fine; returns nothing (a write reports failure).
function TextStore.mkdir_p(path)
  local prefix, rest = path:match("^(%a:[/\\])(.*)$")       -- C:/...
  if not prefix then prefix, rest = path:match("^([/\\][/\\][^/\\]+[/\\][^/\\]+[/\\]?)(.*)$") end   -- //server/share
  if not prefix then prefix, rest = path:match("^([/\\]?)(.*)$") end
  local current = prefix
  for part in rest:gmatch("[^/\\]+") do
    if current ~= "" and not current:match("[/\\]$") then current = current .. "/" end
    current = current .. part
    pcall(mkdir_one, current)
  end
end

-- ---- A real folder (io.open) -------------------------------------------------------------------------
local Dir = {}
Dir.__index = Dir

function TextStore.dir(root)
  root = (root:gsub("\\", "/")):gsub("/+$", "")
  return setmetatable({ root = root, can_rename = true, kind = "dir" }, Dir)
end

function Dir:path(name) return self.root .. "/" .. name end

function Dir:read(name)
  local f = io.open(self:path(name), "rb")
  if not f then return nil end
  local text = f:read("*a")
  f:close()
  return text
end

local function write_mode(self, name, text, mode)
  local path = self:path(name)
  local f = io.open(path, mode)
  if not f then
    local parent = parent_of(path)
    if parent then TextStore.mkdir_p(parent) end
    local err
    f, err = io.open(path, mode)
    if not f then error("cannot write " .. path .. ": " .. tostring(err), 0) end
  end
  local ok, err = f:write(text)
  if ok then ok, err = f:flush() end
  f:close()
  if not ok then error("cannot write " .. path .. ": " .. tostring(err), 0) end
end

function Dir:write(name, text) write_mode(self, name, text, "wb") end
function Dir:append(name, text) write_mode(self, name, text, "ab") end

function Dir:exists(name)
  local f = io.open(self:path(name), "rb")
  if f then f:close() return true end
  return false
end

function Dir:remove(name) os.remove(self:path(name)) end

function Dir:rename(from, to)
  local ok, err = os.rename(self:path(from), self:path(to))
  if not ok then error("cannot rename " .. self:path(from) .. " to " .. self:path(to) .. ": " .. tostring(err), 0) end
end

-- ---- The save folder (love.filesystem) -----------------------------------------------------------------
local Save = {}
Save.__index = Save

function TextStore.love(subdir)
  return setmetatable({ sub = subdir and (subdir:gsub("/+$", "") .. "/") or "", can_rename = false,
                        kind = "love" }, Save)
end

function Save:rel(name) return self.sub .. name end
function Save:path(name) return love.filesystem.getSaveDirectory() .. "/" .. self:rel(name) end

local function in_save_folder(rel)
  local info = love.filesystem.getInfo(rel, "file")
  if not info then return false end
  return love.filesystem.getRealDirectory(rel) == love.filesystem.getSaveDirectory()
end

function Save:read(name)
  local rel = self:rel(name)
  if not in_save_folder(rel) then return nil end
  local text = love.filesystem.read(rel)
  return text
end

local function ensure_parent(rel)
  local parent = parent_of(rel)
  if parent and not love.filesystem.getInfo(parent, "directory") then love.filesystem.createDirectory(parent) end
end

function Save:write(name, text)
  local rel = self:rel(name)
  ensure_parent(rel)
  local ok, err = love.filesystem.write(rel, text)
  if not ok then error("cannot write " .. self:path(name) .. ": " .. tostring(err), 0) end
end

function Save:append(name, text)
  local rel = self:rel(name)
  ensure_parent(rel)
  local ok, err = love.filesystem.append(rel, text)
  if not ok then error("cannot append to " .. self:path(name) .. ": " .. tostring(err), 0) end
end

function Save:exists(name) return in_save_folder(self:rel(name)) end
function Save:remove(name) love.filesystem.remove(self:rel(name)) end

-- Not atomic (love.filesystem has no rename): copy, then remove.
function Save:rename(from, to)
  local text = self:read(from)
  if text == nil then error("cannot rename " .. self:path(from) .. ": it does not exist", 0) end
  self:write(to, text)
  self:remove(from)
end

-- ---- Memory (tests) --------------------------------------------------------------------------------------
local Memory = {}
Memory.__index = Memory

function TextStore.memory()
  return setmetatable({ files = {}, can_rename = true, kind = "memory" }, Memory)
end

function Memory:path(name) return "memory:/" .. name end
function Memory:read(name) return self.files[name] end
function Memory:write(name, text) self.files[name] = text end
function Memory:append(name, text) self.files[name] = (self.files[name] or "") .. text end
function Memory:exists(name) return self.files[name] ~= nil end
function Memory:remove(name) self.files[name] = nil end
function Memory:rename(from, to)
  if self.files[from] == nil then error("cannot rename " .. from .. ": it does not exist", 0) end
  self.files[to] = self.files[from]
  self.files[from] = nil
end

-- The store for this run: --data-dir (an absolute folder) wins, else the save folder.
function TextStore.for_run(data_dir)
  if data_dir and data_dir ~= "" then return TextStore.dir(data_dir) end
  return TextStore.love()
end

return TextStore

-- {{FOOTER}}
