-- ---------------------------------------------------------------------------
-- tools/lovecheck/main.lua
-- Purpose : Compile-check Lua files with LÖVE's own LuaJIT (the exact compiler the game runs on), without running
--           them: `lovec tools/lovecheck <file.lua> ...` (absolute paths). dev.py check calls it.
-- Notes   : Reads files by absolute path, because love.filesystem only sees this checker's own folder. LÖVE hands
--           the arguments over as UTF-8, and io.open takes the system code page on Windows (a project folder with
--           "Í" or a curly quote would be unreadable), so on Windows the file is opened with _wfopen through the
--           FFI (the same calls as src/core/text_store.lua's TextStore.file; this checker cannot require the game's
--           code). Prints "CHECK_FAIL <path> <message>" per broken file and "CHECK_DONE <files> <failed>" at the end.
--           Exit 0 all compiled, 1 a file failed, 2 a file could not be read.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------

-- ---- Tunables ----------------------------------------------------------------
local WIN_UTF8 = 65001                     -- CP_UTF8 for MultiByteToWideChar
local WIN_INVALID_CHARS = 8                -- MB_ERR_INVALID_CHARS: a path that is not UTF-8 falls back to io.open
local READ_CHUNK = 65536                   -- bytes per fread

local ok_ffi, ffi = pcall(require, "ffi")
local WIDE = ok_ffi and ffi.os == "Windows"
if WIDE then
  for _, decl in ipairs({
    "int MultiByteToWideChar(unsigned int cp, unsigned long flags, const char *src, int srclen, uint16_t *dst, "
      .. "int dstlen);",
    "void *_wfopen(const uint16_t *name, const uint16_t *mode);",
    "size_t fread(void *buf, size_t size, size_t n, void *f);",
    "int fclose(void *f);",
  }) do pcall(ffi.cdef, decl) end
end

-- The UTF-16 copy of a UTF-8 string, or nil when it is not valid UTF-8
local function wide(s)
  local n = ffi.C.MultiByteToWideChar(WIN_UTF8, WIN_INVALID_CHARS, s, -1, nil, 0)
  if n == 0 then return nil end
  local buf = ffi.new("uint16_t[?]", n)
  if ffi.C.MultiByteToWideChar(WIN_UTF8, WIN_INVALID_CHARS, s, -1, buf, n) == 0 then return nil end
  return buf
end

-- The file's text, or nil when it cannot be opened
local function read_file(path)
  local wpath = WIDE and wide(path)
  if not wpath then
    local f = io.open(path, "rb")
    if not f then return nil end
    local src = f:read("*a")
    f:close()
    return src
  end
  local f = ffi.C._wfopen(wpath, wide("rb"))
  if f == nil then return nil end
  local buf, parts = ffi.new("char[?]", READ_CHUNK), {}
  while true do
    local got = tonumber(ffi.C.fread(buf, 1, READ_CHUNK, f))
    if got > 0 then parts[#parts + 1] = ffi.string(buf, got) end
    if got < READ_CHUNK then break end
  end
  ffi.C.fclose(f)
  return table.concat(parts)
end

function love.load(args)
  local failed, unreadable = 0, 0
  for _, path in ipairs(args or {}) do
    local src = read_file(path)
    if not src then
      unreadable = unreadable + 1
      print("CHECK_FAIL " .. path .. " cannot read the file")
    else
      local _, err = loadstring(src, "@" .. path)
      if err then
        failed = failed + 1
        print("CHECK_FAIL " .. path .. " " .. err)
      end
    end
  end
  print(string.format("CHECK_DONE %d %d", #(args or {}), failed + unreadable))
  io.stdout:flush()
  os.exit(unreadable > 0 and 2 or (failed > 0 and 1 or 0))
end
