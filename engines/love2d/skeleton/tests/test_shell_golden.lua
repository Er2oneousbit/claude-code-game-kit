-- ---------------------------------------------------------------------------
-- test_shell_golden.lua
-- Purpose : The shell logic (settings defaults and loading, rebinding, glyphs, prompts, save loading and
--           migration, translation, plurals, pseudo-locale) against data/golden/shell.json, one test per case.
-- Usage   : python tools/dev.py test     (or --filter shell)
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): the display_staging cases (the Display tab's Apply
--           and its keep-or-revert confirm, #308), every step's result and state
-- ---------------------------------------------------------------------------
local Golden = require("tests.helpers.golden")
local Settings = require("src.core.settings")
local Bindings = require("src.core.bindings")
local SaveStore = require("src.core.save_store")
local I18n = require("src.core.i18n")
local DisplayStaging = require("src.core.display_staging")
local Json = require("src.core.json")

local FILE = "shell.json"
local data = Golden.load(FILE)

local handlers = {}

function handlers.defaults(case, tol, where)
  Golden.expect(Settings.defaults(), case.expect, tol, where)
  return 1
end

function handlers.settings_load(case, tol, where)
  local s, problems = Settings.load(Golden.opt(case.input))
  Golden.expect(s, case.expect, tol, where .. " settings")
  Golden.expect(#problems, case.problems, tol, where .. " problem count (" .. table.concat(problems, ", ") .. ")")
  Golden.expect(Settings.effective_shake(s), case.effective_shake, tol, where .. " effective_shake")
  Golden.expect(Settings.telemetry_allowed(s), case.telemetry_allowed, tol, where .. " telemetry_allowed")
  return 4
end

function handlers.rebind(case, tol, where)
  local out, conflicts = Bindings.rebind(case.bindings, case.action, case.slot, case.binding)
  Golden.expect({ bindings = out, conflicts = conflicts }, case.expect, tol, where)
  return 2
end

function handlers.glyph_set(case, tol, where)
  for i, p in ipairs(case.points) do
    Golden.expect(Bindings.glyph_set(p[1], p[2]), p[3], tol, where .. " " .. p[1] .. "/" .. p[2] .. " (" .. i .. ")")
  end
  return #case.points
end

function handlers.glyph_name(case, tol, where)
  for i, p in ipairs(case.points) do
    Golden.expect(Bindings.glyph_name(p[1], p[2]), p[3], tol, where .. " " .. p[1] .. "/" .. p[2] .. " (" .. i .. ")")
  end
  return #case.points
end

function handlers.prompt_binding(case, tol, where)
  for i, p in ipairs(case.points) do
    Golden.expect(Bindings.prompt_binding(case.bindings, p[1], p[2]), p[3], tol,
                  where .. " " .. p[1] .. "/" .. p[2] .. " (" .. i .. ")")
  end
  return #case.points
end

function handlers.save_load(case, tol, where)
  Golden.expect(SaveStore.SAVE_VERSION, case.current_version, tol, where .. " SAVE_VERSION")
  local env, source, problems = SaveStore.load_texts(Golden.opt(case.primary), Golden.opt(case.backup))
  Golden.expect({ envelope = env, source = source, problems = #problems }, case.expect, tol,
                where .. " (" .. table.concat(problems, ", ") .. ")")
  return 3
end

function handlers.tr(case, tol, where)
  for i, p in ipairs(case.points) do
    Golden.expect(I18n.tr(case.tables, p[1], p[2], p[3]), p[4], tol, where .. " " .. p[1] .. "/" .. p[2] .. " (" .. i .. ")")
  end
  return #case.points
end

function handlers.plural(case, tol, where)
  for i, p in ipairs(case.points) do
    Golden.expect(I18n.plural(p[1], p[2]), p[3], tol, where .. " plural " .. p[1] .. " " .. p[2] .. " (" .. i .. ")")
    Golden.expect(I18n.tr_plural(case.tables, p[1], "apples", p[2]), p[4], tol,
                  where .. " text " .. p[1] .. " " .. p[2] .. " (" .. i .. ")")
  end
  return #case.points * 2
end

function handlers.narration(case, tol, where)
  for i, p in ipairs(case.points) do
    Golden.expect(Bindings.narration_line(p[1], p[2], p[3]), p[4], tol, where .. " (" .. i .. ")")
  end
end

function handlers.pseudo(case, tol, where)
  for i, p in ipairs(case.points) do
    Golden.expect(I18n.pseudo(p[1]), p[2], tol, where .. " " .. string.format("%q", p[1]) .. " (" .. i .. ")")
  end
  return #case.points
end

-- A script of steps ({op, args...}); after each one: its result (out), the set-value calls, pending, the value
-- every control shows, the applied values and the countdown's whole seconds.
function handlers.display_staging(case, tol, where)
  Golden.expect(DisplayStaging.CONFIRM_S, case.confirm_s, tol, where .. " CONFIRM_S")
  local st = DisplayStaging.new(case.applied)
  local n = 1
  for i, step in ipairs(case.steps) do
    local op = step.op
    local out, calls = Json.null, {}
    if op[1] == "stage" then out = st:stage(op[2], op[3])
    elseif op[1] == "apply" then calls = st:apply()
    elseif op[1] == "tick" then calls = st:tick(op[2])
    elseif op[1] == "keep" then st:keep()
    elseif op[1] == "revert" then calls = st:revert()
    elseif op[1] == "back" then out, calls = st:back()
    else error(where .. ": unknown op " .. tostring(op[1]), 0) end
    local shown = {}
    for _, f in ipairs(DisplayStaging.APPLY_ORDER) do shown[f] = st:value(f) end
    local w = string.format("%s step %d (%s)", where, i, tostring(op[1]))
    Golden.expect({ out = out, calls = calls, pending = st.pending, shown = shown, applied = st.applied,
                    seconds = st:seconds() },
                  { out = step.out, calls = step.calls, pending = step.pending, shown = step.shown,
                    applied = step.applied, seconds = step.seconds }, tol, w)
    n = n + 6
  end
  return n
end

local suite = Golden.suite(data, handlers, FILE)

-- The vectors' save_version must match the port's (a stale copy of shell.json would otherwise pass old cases).
function suite.test_save_version_matches()
  Golden.expect(SaveStore.SAVE_VERSION, data.save_version, 0, "shell.json save_version")
end

return suite

-- {{FOOTER}}
