-- ---------------------------------------------------------------------------
-- tools/lovecheck/main.lua
-- Purpose : Compile-check Lua files with LÖVE's own LuaJIT (the exact compiler the game runs on), without running
--           them: `lovec tools/lovecheck <file.lua> ...` (absolute paths). dev.py check calls it.
-- Notes   : Reads files with io.open, because love.filesystem only sees this checker's own folder. Prints
--           "CHECK_FAIL <path> <message>" per broken file and "CHECK_DONE <files> <failed>" at the end.
--           Exit 0 all compiled, 1 a file failed, 2 a file could not be read.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
function love.load(args)
  local failed, unreadable = 0, 0
  for _, path in ipairs(args or {}) do
    local f = io.open(path, "rb")
    if not f then
      unreadable = unreadable + 1
      print("CHECK_FAIL " .. path .. " cannot read the file")
    else
      local src = f:read("*a")
      f:close()
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
