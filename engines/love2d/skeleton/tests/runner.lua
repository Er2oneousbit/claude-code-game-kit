-- ---------------------------------------------------------------------------
-- runner.lua
-- Purpose : The project's own unit-test runner (no LuaRocks, no busted): runs inside LÖVE, so tests use the same
--           LuaJIT and love.* modules as the game. `python tools/dev.py test` runs it with `lovec . --test`.
-- Usage   : a test file tests/test_<thing>.lua returns a table of functions named test_*:
--             local A = require("tests.assert")
--             local T = {}
--             function T.test_adds() A.eq(1 + 1, 2) end
--             return T
--           filter: lovec . --test --filter coyote   (only files whose name contains "coyote")
-- Notes   : Prints one line per failure and a summary "TESTS <run> passed <p> failed <f> files <n>", which dev.py
--           parses. Exit 0 all passed, 1 a test failed or a file did not load, 2 nothing ran.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
--
-- Pseudocode
--   files = tests/test_*.lua (sorted, filtered) -> load each (a load error counts as a failure)
--   for each test_* function in name order: pcall it, count pass / fail, print the failure with its message
--   print the summary; return the exit code
local Runner = {}

local function filter_arg()
  for i, a in ipairs(KIT and KIT.rest or {}) do
    if a == "--filter" then return KIT.rest[i + 1] end
  end
  return nil
end

function Runner.run()
  local filter = filter_arg()
  local files = {}
  for _, name in ipairs(love.filesystem.getDirectoryItems("tests")) do
    if name:match("^test_.*%.lua$") and (not filter or name:find(filter, 1, true)) then
      files[#files + 1] = name
    end
  end
  table.sort(files)
  local run, passed, failed = 0, 0, 0
  for _, file in ipairs(files) do
    local module = "tests." .. file:gsub("%.lua$", "")
    local ok, suite = pcall(require, module)
    if not ok or type(suite) ~= "table" then
      failed = failed + 1
      print("FAIL " .. file .. ": did not load: " .. tostring(suite))
    else
      local names = {}
      for name, fn in pairs(suite) do
        if type(fn) == "function" and name:match("^test_") then names[#names + 1] = name end
      end
      table.sort(names)
      for _, name in ipairs(names) do
        run = run + 1
        local good, err = xpcall(suite[name], debug.traceback)
        if good then
          passed = passed + 1
        else
          failed = failed + 1
          print("FAIL " .. file .. " " .. name .. ": " .. tostring(err))
        end
      end
    end
  end
  print(string.format("TESTS %d passed %d failed %d files %d", run, passed, failed, #files))
  if failed > 0 then return 1 end
  if run == 0 then return 2 end
  return 0
end

return Runner

-- {{FOOTER}}
