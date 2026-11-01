-- ---------------------------------------------------------------------------
-- atomic_file.lua
-- Purpose : Crash-safe writes for settings and saves: the old file stays readable until the new one is complete,
--           and the previous good version is kept as <file>.bak.
-- Usage   : local AtomicFile = require("src.core.atomic_file")
--           AtomicFile.write(store, "save_1.json", text)                            -- keeps save_1.json.bak
--           AtomicFile.write(store, "save_1.json", text, { is_good = function(old) ... end })
--           AtomicFile.recover(store, "save_1.json", is_complete)   -- before a load: puts a stranded .tmp back
--           (store: src/core/text_store.lua, the user-data folder)
-- Notes   : No love.* calls; the store does the file work. Two kinds of store:
--           - a real folder (--data-dir, io.open): write <file>.tmp, close it, read it back, copy the old file to
--             <file>.bak, rename <file>.tmp over <file>. On POSIX that rename replaces <file> atomically. On
--             Windows a rename does not replace an existing file, so the store removes <file> first
--             (text_store.lua Dir:rename). A crash before the rename leaves the old file intact; a crash between
--             that remove and the rename (Windows only) leaves no <file> but a complete <file>.tmp and the .bak.
--           - love.filesystem (the save folder) has NO rename: write <file>.tmp and check it reads back complete,
--             then write <file>.bak and <file> directly, then remove the .tmp. A crash during the final write can
--             leave a short <file>, so the loaders fall back to the .bak (and the verified .tmp is still there).
--           Recovery: recover() runs before every load of a save slot or settings.json. When <file> is missing and
--           <file>.tmp passes is_complete (it parses), the .tmp is the newest finished write: it is renamed to
--           <file> and the load reports it ("recovered from <file>.tmp"). A .tmp that does not parse is left
--           alone and the loaders fall back to the .bak. A .tmp next to an existing <file> is a write that never
--           reached its commit: the old <file> wins and the next write overwrites the .tmp.
--           stage() and commit() are the two halves, so a test can stop between them (a simulated crash).
--
-- Pseudocode:
--   stage:   write <file>.tmp ; read back == text, else raise (nothing was replaced)
--   commit:  old = read <file>; if old and is_good(old) then write <file>.bak = old
--            store can rename -> rename tmp over file ; else write <file> = text, check, remove tmp
--   recover: no <file> and is_complete(read <file>.tmp) -> rename tmp -> file (a failed rename: leave it)
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local AtomicFile = {}

-- ---- Tunables ----------------------------------------------------------------
AtomicFile.TMP_SUFFIX = ".tmp"
AtomicFile.BAK_SUFFIX = ".bak"

function AtomicFile.stage(store, name, text)
  local tmp = name .. AtomicFile.TMP_SUFFIX
  store:write(tmp, text)
  if store:read(tmp) ~= text then
    error("atomic write: " .. store:path(tmp) .. " did not read back complete (disk full?)", 0)
  end
end

-- options.backup (default true): keep the replaced file as .bak; options.is_good(old_text): back up only a file
-- that passes (a corrupt file must never replace a good .bak).
function AtomicFile.commit(store, name, options)
  options = options or {}
  local tmp = name .. AtomicFile.TMP_SUFFIX
  local text = store:read(tmp)
  if text == nil then error("atomic write: nothing staged in " .. store:path(tmp), 0) end
  if options.backup ~= false then
    local old = store:read(name)
    if old ~= nil and (not options.is_good or options.is_good(old)) then
      store:write(name .. AtomicFile.BAK_SUFFIX, old)
    end
  end
  if store.can_rename then
    store:rename(tmp, name)                  -- replaces name (the Windows folder store removes it first)
  else
    store:write(name, text)
    if store:read(name) ~= text then
      error("atomic write: " .. store:path(name) .. " did not read back complete; " .. tmp .. " has the data", 0)
    end
    store:remove(tmp)
  end
end

function AtomicFile.write(store, name, text, options)
  AtomicFile.stage(store, name, text)
  AtomicFile.commit(store, name, options)
end

-- A crash between removing <file> and renaming the .tmp over it leaves no <file> but a complete .tmp: put it back.
-- is_complete(text) says whether the .tmp is a whole file (it parses). Returns true when it recovered.
function AtomicFile.recover(store, name, is_complete)
  if store:exists(name) then return false end
  local tmp = name .. AtomicFile.TMP_SUFFIX
  local text = store:read(tmp)
  if text == nil or not is_complete(text) then return false end
  return (pcall(store.rename, store, tmp, name))     -- a failed rename leaves both as they were: use the .bak
end

return AtomicFile

-- {{FOOTER}}
