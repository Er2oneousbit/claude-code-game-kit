-- ---------------------------------------------------------------------------
-- atomic_file.lua
-- Purpose : Crash-safe writes for settings and saves: the old file stays readable until the new one is complete,
--           and the previous good version is kept as <file>.bak.
-- Usage   : local AtomicFile = require("src.core.atomic_file")
--           AtomicFile.write(store, "save_1.json", text)                            -- keeps save_1.json.bak
--           AtomicFile.write(store, "save_1.json", text, { is_good = function(old) ... end })
--           (store: src/core/text_store.lua, the user-data folder)
-- Notes   : No love.* calls; the store does the file work. Two kinds of store:
--           - a real folder (--data-dir, io.open): write <file>.tmp, close it, read it back, copy the old file to
--             <file>.bak, remove <file>, rename <file>.tmp to <file>. The remove comes first because a rename
--             on Windows does not replace an existing file. A crash before the rename leaves the old file intact;
--             a crash between the remove and the rename leaves <file>.bak and <file>.tmp, and the loaders fall
--             back to the .bak.
--           - love.filesystem (the save folder) has NO rename: write <file>.tmp and check it reads back complete,
--             then write <file>.bak and <file> directly, then remove the .tmp. A crash during the final write can
--             leave a short <file>, so the loaders fall back to the .bak (and the verified .tmp is still there).
--           stage() and commit() are the two halves, so a test can stop between them (a simulated crash).
--
-- Pseudocode:
--   stage:  write <file>.tmp ; read back == text, else raise (nothing was replaced)
--   commit: old = read <file>; if old and is_good(old) then write <file>.bak = old
--           store can rename -> remove <file>, rename tmp -> file ; else write <file> = text, check, remove tmp
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
    store:remove(name)
    store:rename(tmp, name)
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

return AtomicFile

-- {{FOOTER}}
