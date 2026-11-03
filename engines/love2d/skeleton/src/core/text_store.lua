-- ---------------------------------------------------------------------------
-- text_store.lua
-- Purpose : The game's user-data folder as one small interface, so settings, saves, logs, crash files and
--           telemetry never care where they live: the save folder (love.filesystem), an absolute folder given
--           with --data-dir (real files, so tests can inspect them), or memory (unit tests).
-- Usage   : local TextStore = require("src.core.text_store")
--           local store = TextStore.for_run(KIT.data_dir)  -- --data-dir if given, else the save folder
--           store:read("settings.json") -> text or nil      store:write("logs/game.log", text)
--           store:append(name, text)  store:remove(name)  store:rename(from, to)  store:exists(name)
--           store:path(name) -> the absolute path, for messages and the proof lines dev.py prints
--           TextStore.file.read(path) / .write(path, text, "wb"|"ab") / .exists / .remove / .rename: the same file
--           calls by absolute UTF-8 path, for code outside a store (main.lua's captures)
-- Notes   : Names are folder-style paths relative to the folder ("crashes/crash_1.txt"); parent folders are
--           created on write. Binary data (PNG) is fine: every backend writes bytes as they are.
--           Folder store: TextStore.file plus a small mkdir through LuaJIT's FFI (Lua has none). Its rename is real
--           (can_rename = true) and replaces the target: on POSIX os.rename does that atomically; on Windows it
--           cannot, so Dir:rename removes the target first there only (RENAME_REPLACES; atomic_file.lua documents
--           the crash window that leaves and how a load recovers it). io.open, os.remove and os.rename take the
--           path in the system code page on Windows, so a folder named with "Í" or a curly quote cannot be opened
--           through them: on Windows TextStore.file converts the UTF-8 path to UTF-16 and calls the C runtime's
--           wide functions (_wfopen, _wremove, _wrename) through the FFI. Elsewhere it is io.open and os.*.
--           Save-folder store: love.filesystem has no rename (can_rename = false; atomic_file.lua writes and
--           verifies instead), and read() ignores files that live in the game's own folder, not the save folder.
--           love.filesystem works without a window, so tests use it too.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local TextStore = {}

-- ---- Tunables ----------------------------------------------------------------
local POSIX_DIR_MODE = 493                 -- 0755
local WIN_UTF8 = 65001                     -- CP_UTF8 for MultiByteToWideChar
local WIN_INVALID_CHARS = 8                -- MB_ERR_INVALID_CHARS: a path that is not UTF-8 falls back to io.open
local READ_CHUNK = 65536                   -- bytes per fread
-- os.rename replaces an existing target on POSIX (atomically) but not on Windows ("\" is the Windows separator)
TextStore.RENAME_REPLACES = package.config:sub(1, 1) ~= "\\"

local function parent_of(path)
  return path:match("^(.*)[/\\][^/\\]+$")
end

-- ---- Files by UTF-8 path (wide C runtime calls on Windows, io.open and os.* elsewhere) -------------------
local ok_ffi, ffi = pcall(require, "ffi")
local WIDE = ok_ffi and ffi.os == "Windows"
if WIDE then
  -- one declaration per call, so a module that already declared one of them cannot stop the rest
  for _, decl in ipairs({
    "int MultiByteToWideChar(unsigned int cp, unsigned long flags, const char *src, int srclen, uint16_t *dst, "
      .. "int dstlen);",
    "int CreateDirectoryW(const uint16_t *path, void *security);",
    "void *_wfopen(const uint16_t *name, const uint16_t *mode);",
    "size_t fread(void *buf, size_t size, size_t n, void *f);",
    "size_t fwrite(const void *buf, size_t size, size_t n, void *f);",
    "int fflush(void *f);",
    "int fclose(void *f);",
    "int _wremove(const uint16_t *name);",
    "int _wrename(const uint16_t *from, const uint16_t *to);",
    "char *strerror(int errnum);",
  }) do pcall(ffi.cdef, decl) end
end

-- The UTF-16 copy of a UTF-8 string for the wide calls, or nil when it is not valid UTF-8
local function wide(s)
  local n = ffi.C.MultiByteToWideChar(WIN_UTF8, WIN_INVALID_CHARS, s, -1, nil, 0)
  if n == 0 then return nil end
  local buf = ffi.new("uint16_t[?]", n)
  if ffi.C.MultiByteToWideChar(WIN_UTF8, WIN_INVALID_CHARS, s, -1, buf, n) == 0 then return nil end
  return buf
end

local function c_error(path)
  return path .. ": " .. ffi.string(ffi.C.strerror(ffi.errno()))
end

local File = {}
TextStore.file = File

-- The whole file as a string, or nil and a message
function File.read(path)
  local wpath = WIDE and wide(path)
  if not wpath then
    local f, err = io.open(path, "rb")
    if not f then return nil, err end
    local text = f:read("*a")
    f:close()
    return text
  end
  local f = ffi.C._wfopen(wpath, wide("rb"))
  if f == nil then return nil, c_error(path) end
  local buf, parts = ffi.new("char[?]", READ_CHUNK), {}
  while true do
    local got = tonumber(ffi.C.fread(buf, 1, READ_CHUNK, f))
    if got > 0 then parts[#parts + 1] = ffi.string(buf, got) end
    if got < READ_CHUNK then break end
  end
  ffi.C.fclose(f)
  return table.concat(parts)
end

-- Writes (mode "wb") or appends ("ab") text: true, or nil and a message. The parent folder must exist.
function File.write(path, text, mode)
  local wpath = WIDE and wide(path)
  if not wpath then
    local f, err = io.open(path, mode)
    if not f then return nil, err end
    local ok
    ok, err = f:write(text)
    if ok then ok, err = f:flush() end
    f:close()
    if not ok then return nil, err end
    return true
  end
  local f = ffi.C._wfopen(wpath, wide(mode))
  if f == nil then return nil, c_error(path) end
  local ok = tonumber(ffi.C.fwrite(text, 1, #text, f)) == #text and ffi.C.fflush(f) == 0
  local err = (not ok) and c_error(path) or nil
  if ffi.C.fclose(f) ~= 0 and ok then ok, err = false, c_error(path) end
  if not ok then return nil, err end
  return true
end

function File.exists(path)
  local wpath = WIDE and wide(path)
  if not wpath then
    local f = io.open(path, "rb")
    if f then f:close() return true end
    return false
  end
  local f = ffi.C._wfopen(wpath, wide("rb"))
  if f == nil then return false end
  ffi.C.fclose(f)
  return true
end

-- true, or nil and a message (like os.remove)
function File.remove(path)
  local wpath = WIDE and wide(path)
  if not wpath then return os.remove(path) end
  if ffi.C._wremove(wpath) ~= 0 then return nil, c_error(path) end
  return true
end

-- Like os.rename: on Windows it fails when `to` exists (Dir:rename removes it first there)
function File.rename(from, to)
  local wfrom, wto = WIDE and wide(from), WIDE and wide(to)
  if not (wfrom and wto) then return os.rename(from, to) end
  if ffi.C._wrename(wfrom, wto) ~= 0 then return nil, c_error(from) end
  return true
end

-- ---- mkdir through the FFI (falls back to os.execute when the FFI is missing) -----------------------
local mkdir_one
do
  if WIDE then
    mkdir_one = function(path)
      local wpath = wide(path)
      return wpath ~= nil and ffi.C.CreateDirectoryW(wpath, nil) ~= 0
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

-- ---- A real folder (TextStore.file) ---------------------------------------------------------------------
local Dir = {}
Dir.__index = Dir

function TextStore.dir(root)
  root = (root:gsub("\\", "/")):gsub("/+$", "")
  return setmetatable({ root = root, can_rename = true, kind = "dir" }, Dir)
end

function Dir:path(name) return self.root .. "/" .. name end

function Dir:read(name)
  return (File.read(self:path(name)))
end

local function write_mode(self, name, text, mode)
  local path = self:path(name)
  if File.write(path, text, mode) then return end
  local parent = parent_of(path)
  if parent then TextStore.mkdir_p(parent) end
  local ok, err = File.write(path, text, mode)
  if not ok then error("cannot write " .. path .. ": " .. tostring(err), 0) end
end

function Dir:write(name, text) write_mode(self, name, text, "wb") end
function Dir:append(name, text) write_mode(self, name, text, "ab") end

function Dir:exists(name) return File.exists(self:path(name)) end

function Dir:remove(name) File.remove(self:path(name)) end

-- Replaces `to`. POSIX rename does that atomically; a Windows rename fails when `to` exists, so remove it first there.
function Dir:rename(from, to)
  if not TextStore.RENAME_REPLACES then File.remove(self:path(to)) end
  local ok, err = File.rename(self:path(from), self:path(to))
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
