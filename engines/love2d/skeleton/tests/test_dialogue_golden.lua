-- ---------------------------------------------------------------------------
-- test_dialogue_golden.lua
-- Purpose : The subtitle typewriter (Dialogue.revealed in src/core/dialogue.lua) against data/golden/dialogue.json:
--           a reveal list that fits the text is followed, one that does not is ignored and the line types at 30
--           characters a second or fast enough to finish within its duration, code points counted.
-- Usage   : python tools/dev.py test     (or --filter dialogue)
-- Notes   : Expected values come from the file at test time (tools/audio/wavesmith/dialogue.py vectors --write);
--           tolerance 0 (whole characters).
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Golden = require("tests.helpers.golden")
local Dialogue = require("src.core.dialogue")

local FILE = "dialogue.json"

local handlers = {}

function handlers.reveal_count(case, tol, where)
  local n = 0
  for i, step in ipairs(case.steps) do
    local at = where .. " step " .. i .. " (" .. tostring(step.about) .. ", t=" .. tostring(step.t) .. ")"
    Golden.expect(Dialogue.revealed(step.line, step.t), step.expect, tol, at)
    n = n + 1
  end
  return n
end

return Golden.suite(Golden.load(FILE), handlers, FILE)

-- {{FOOTER}}
