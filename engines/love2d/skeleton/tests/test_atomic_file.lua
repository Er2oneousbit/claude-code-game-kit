-- ---------------------------------------------------------------------------
-- test_atomic_file.lua
-- Purpose : Crash-safe writes against the REAL filesystem: both kinds of store (an absolute folder through
--           io.open, like --data-dir, and the save folder through love.filesystem) in a temp folder, including a
--           simulated crash between writing the .tmp and replacing the file, and the recovery after a crash
--           between removing the file and the rename (Windows).
-- Usage   : python tools/dev.py test     (or --filter atomic)
-- Notes   : The temp folders live in the game's save folder (love.filesystem may only create folders there) and
--           are removed afterwards.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local TextStore = require("src.core.text_store")
local AtomicFile = require("src.core.atomic_file")
local T = {}

local NAME = "save_1.json"

local function temp_stores()
  local base = "test_tmp_" .. os.time() .. "_" .. math.random(100000)
  love.filesystem.createDirectory(base .. "/dir")
  local abs = love.filesystem.getSaveDirectory() .. "/" .. base .. "/dir"
  return { TextStore.dir(abs), TextStore.love(base .. "/love") }, base
end

local function cleanup(base)
  local function rm(path)
    if love.filesystem.getInfo(path, "directory") then
      for _, item in ipairs(love.filesystem.getDirectoryItems(path)) do rm(path .. "/" .. item) end
    end
    love.filesystem.remove(path)
  end
  rm(base)
end

local function each_store(fn)
  local stores, base = temp_stores()
  local ok, err = pcall(function()
    for _, store in ipairs(stores) do fn(store, store.kind) end
  end)
  cleanup(base)
  if not ok then error(err, 0) end
end

function T.test_first_write_has_no_backup()
  each_store(function(store, kind)
    AtomicFile.write(store, NAME, "one")
    A.eq(store:read(NAME), "one", kind)
    A.falsy(store:exists(NAME .. ".bak"), kind .. ": no .bak without an old file")
    A.falsy(store:exists(NAME .. ".tmp"), kind .. ": no .tmp left")
  end)
end

function T.test_second_write_keeps_the_old_file_as_bak()
  each_store(function(store, kind)
    AtomicFile.write(store, NAME, "one")
    AtomicFile.write(store, NAME, "two")
    A.eq(store:read(NAME), "two", kind)
    A.eq(store:read(NAME .. ".bak"), "one", kind)
  end)
end

function T.test_crash_before_the_rename_leaves_the_old_file()
  each_store(function(store, kind)
    AtomicFile.write(store, NAME, "good")
    AtomicFile.stage(store, NAME, "new but never committed")      -- the game dies here
    A.eq(store:read(NAME), "good", kind .. ": old file intact")
    A.eq(store:read(NAME .. ".tmp"), "new but never committed", kind)
    AtomicFile.write(store, NAME, "next")                         -- the next save just overwrites the stale .tmp
    A.eq(store:read(NAME), "next", kind)
    A.eq(store:read(NAME .. ".bak"), "good", kind)
    A.falsy(store:exists(NAME .. ".tmp"), kind)
  end)
end

function T.test_crash_between_the_remove_and_the_rename_is_recovered()
  each_store(function(store, kind)
    AtomicFile.write(store, NAME, "good")
    AtomicFile.stage(store, NAME, "new")
    store:remove(NAME)                                            -- Windows: the target is gone, the rename never ran
    local complete = function(text) return text == "new" end
    A.truthy(AtomicFile.recover(store, NAME, complete), kind .. ": recovered")
    A.eq(store:read(NAME), "new", kind)
    A.falsy(store:exists(NAME .. ".tmp"), kind)
    A.falsy(AtomicFile.recover(store, NAME, complete), kind .. ": nothing to do when the file is there")
    store:write(NAME .. ".tmp", "ne")                             -- a torn .tmp
    store:remove(NAME)
    A.falsy(AtomicFile.recover(store, NAME, complete), kind .. ": a .tmp that does not parse stays put")
    A.falsy(store:exists(NAME), kind)
  end)
end

function T.test_rename_replaces_an_existing_target()
  if love.system.getOS() == "Windows" then A.falsy(TextStore.RENAME_REPLACES, "Windows removes the target first") end
  each_store(function(store, kind)
    store:write("a.txt", "from a")
    store:write("b.txt", "old b")
    store:rename("a.txt", "b.txt")
    A.eq(store:read("b.txt"), "from a", kind)
    A.falsy(store:exists("a.txt"), kind)
  end)
end

function T.test_a_bad_old_file_does_not_replace_a_good_backup()
  each_store(function(store, kind)
    AtomicFile.write(store, NAME, "good 1")
    AtomicFile.write(store, NAME, "good 2")              -- .bak = good 1
    store:write(NAME, "garbage")                         -- corrupted on disk
    AtomicFile.write(store, NAME, "good 3", { is_good = function(old) return old:sub(1, 4) == "good" end })
    A.eq(store:read(NAME .. ".bak"), "good 1", kind .. ": the corrupt file was not backed up")
    A.eq(store:read(NAME), "good 3", kind)
  end)
end

function T.test_binary_and_nested_paths()
  each_store(function(store, kind)
    local bytes = "\137PNG\r\n\26\n\0\1\2\255"
    store:write("bug_x/shot.png", bytes)
    A.eq(store:read("bug_x/shot.png"), bytes, kind)
    store:append("logs/game.log", "a\n")
    store:append("logs/game.log", "b\n")
    A.eq(store:read("logs/game.log"), "a\nb\n", kind)
  end)
end

-- io.open takes the Windows code page, so a folder named with "Í" or a right double quote (bytes cp1252 cannot
-- decode) was unreadable through the folder store (#98). love.filesystem (UTF-8) checks the files landed by name.
function T.test_folder_store_with_a_name_outside_the_code_page()
  local base = "test_tmp_" .. os.time() .. "_" .. math.random(100000)
  local folder = base .. "/l\195\141ve \226\128\157q"            -- "lÍve ”q"
  love.filesystem.createDirectory(folder)
  local ok, err = pcall(function()
    local store = TextStore.dir(love.filesystem.getSaveDirectory() .. "/" .. folder)
    local big = string.rep("0123456789abcdef", 10000)             -- several read chunks
    AtomicFile.write(store, NAME, big)
    A.eq(store:read(NAME), big, "read back")
    A.eq(love.filesystem.read(folder .. "/" .. NAME), big, "the file has the right name on disk")
    store:append("logs/game.log", "a\n")
    store:append("logs/game.log", "b\n")
    A.eq(love.filesystem.read(folder .. "/logs/game.log"), "a\nb\n", "append in a new subfolder")
    AtomicFile.write(store, NAME, "two")                          -- rename over the old file
    A.eq(store:read(NAME .. ".bak"), big, ".bak")
    A.truthy(store:exists(NAME), "exists")
    store:remove(NAME)
    A.falsy(store:exists(NAME), "removed")
    local shot = love.filesystem.getSaveDirectory() .. "/" .. folder .. "/shot.png"
    A.truthy(TextStore.file.write(shot, "\137PNG", "wb"), "TextStore.file.write (main.lua captures)")
    A.eq(love.filesystem.read(folder .. "/shot.png"), "\137PNG", "capture bytes")
  end)
  cleanup(base)
  if not ok then error(err, 0) end
end

function T.test_memory_store_contract()
  local store = TextStore.memory()
  AtomicFile.write(store, NAME, "x")
  AtomicFile.write(store, NAME, "y")
  A.eq(store:read(NAME .. ".bak"), "x")
  A.raises(function() store:rename("missing", "other") end)
end

return T

-- {{FOOTER}}
