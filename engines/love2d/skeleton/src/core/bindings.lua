-- ---------------------------------------------------------------------------
-- bindings.lua
-- Purpose : Input bindings as data, rebinding with swap, and which button prompt (glyph) to show. A binding is a
--           string "<kind>:<name>": key:space, mouse:left, pad:south (the face button at the bottom), pad:start,
--           pad_axis:leftx-. Matches data/golden/shell.json "rebind", "glyph_set", "glyph_name",
--           "prompt_binding".
-- Usage   : local Bindings = require("src.core.bindings")
--           local b = Bindings.defaults()                        -- action -> { slot 0 (keyboard), slot 1 (pad) }
--           local b2, conflicts = Bindings.rebind(b, "jump", 0, "key:k")
--           local gset = Bindings.glyph_set(settings.input.glyphs, last_device)       -- "xbox", "keyboard", ...
--           local art = Bindings.glyph_name(gset, Bindings.prompt_binding(b, "jump", gset))  -- "xbox_a"
--           -> assets/ui/glyphs/xbox_a.png, or a text label when that file is missing
-- Notes   : No love.* calls. SLOTS ARE 0-BASED here, as in the vectors and every other engine of the kit (slot 0
--           keyboard, slot 1 pad, more slots allowed); the Lua list index is slot + 1. Actions named ui_* form
--           one group, all others the game group: a binding may be shared across groups (Enter is ui_accept and
--           Space is jump) but not inside one, so rebinding swaps the old binding onto the action that had it.
--           Physical names are positional (south/east/west/north), so one table works for every controller;
--           glyph_name turns them into the right art (xbox_a, ps_cross).
--
-- Pseudocode (rebind):
--   old = the slot's current binding ("" when the slot is new); conflicts = every other (action, slot) of the
--   same group holding the new binding; put the binding in; every conflict gets old (a swap, or unbound "")
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Json = require("src.core.json")

local Bindings = {}

-- ---- Tunables ----------------------------------------------------------------
Bindings.GLYPH_SETS = { "auto", "keyboard", "xbox", "playstation", "generic" }
Bindings.SLOT_KEYBOARD, Bindings.SLOT_PAD = 0, 1
-- the game actions a Controls screen lists, in order (ui_* actions are not rebindable in the menus: a player who
-- rebinds ui_accept away can no longer use the menu that would undo it)
Bindings.GAME_ACTIONS = { "move_left", "move_right", "move_up", "move_down", "jump", "attack", "interact", "pause" }

local DEFAULTS = {
  ui_up = { "key:up", "pad:dpad_up" }, ui_down = { "key:down", "pad:dpad_down" },
  ui_left = { "key:left", "pad:dpad_left" }, ui_right = { "key:right", "pad:dpad_right" },
  ui_accept = { "key:enter", "pad:south" }, ui_cancel = { "key:escape", "pad:east" },
  move_left = { "key:a", "pad:dpad_left" }, move_right = { "key:d", "pad:dpad_right" },
  move_up = { "key:w", "pad:dpad_up" }, move_down = { "key:s", "pad:dpad_down" },
  jump = { "key:space", "pad:south" }, attack = { "key:j", "pad:west" },
  interact = { "key:e", "pad:north" }, pause = { "key:escape", "pad:start" },
}

local DEVICE_SETS = { keyboard = "keyboard", mouse = "keyboard", pad_xbox = "xbox", pad_playstation = "playstation" }
local XBOX = { south = "a", east = "b", west = "x", north = "y", l1 = "lb", r1 = "rb", l2 = "lt", r2 = "rt",
               start = "menu", select = "view" }
local PLAYSTATION = { south = "cross", east = "circle", west = "square", north = "triangle", start = "options",
                      select = "share" }

-- A fresh copy of the default bindings (lists marked as JSON arrays, the whole as an object).
function Bindings.defaults()
  local out = Json.object({})
  for action, list in pairs(DEFAULTS) do
    out[action] = Json.array({ list[1], list[2] })
  end
  return out
end

function Bindings.group_of(action)
  if action:sub(1, 3) == "ui_" then return "ui" end
  return "game"
end

-- Returns new bindings and the conflicts as a sorted list of { action, slot } (slot 0-based). Raises when slot is
-- past the end of the action's list (slot == #list appends a new slot).
function Bindings.rebind(bindings, action, slot, binding)
  local b = Json.copy(bindings)
  if b[action] == nil then b[action] = Json.array({}) end
  local list = b[action]
  if slot > #list then error("rebind: slot " .. slot .. " is past the end of " .. action, 2) end
  local old = ""
  if slot < #list then old = list[slot + 1] end
  local conflicts = Json.array({})
  local group = Bindings.group_of(action)
  for _, other in ipairs(Json.sorted_keys(b)) do
    if Bindings.group_of(other) == group and type(b[other]) == "table" then
      for i, name in ipairs(b[other]) do
        local s = i - 1
        if not (other == action and s == slot) and name == binding and binding ~= "" then
          conflicts[#conflicts + 1] = Json.array({ other, s })
        end
      end
    end
  end
  list[slot + 1] = binding
  for _, c in ipairs(conflicts) do b[c[1]][c[2] + 1] = old end
  return b, conflicts
end

-- Every binding shared by two actions of the same group (a hand-edited file can have them): a list of
-- { binding, action_a, slot_a, action_b, slot_b }, sorted. The Controls screen marks them.
function Bindings.find_conflicts(bindings)
  local seen, out = {}, {}
  for _, action in ipairs(Json.sorted_keys(bindings)) do
    for i, name in ipairs(bindings[action]) do
      if name ~= "" then
        local key = Bindings.group_of(action) .. "|" .. name
        if seen[key] then
          out[#out + 1] = { name, seen[key][1], seen[key][2], action, i - 1 }
        else
          seen[key] = { action, i - 1 }
        end
      end
    end
  end
  return out
end

-- Which prompt art to show: the player's choice, or (auto) the last device used: keyboard, mouse, pad_xbox,
-- pad_playstation, or anything else (a pad of unknown make) -> generic.
function Bindings.glyph_set(setting, last_device)
  if setting ~= "auto" then return setting end
  return DEVICE_SETS[last_device] or "generic"
end

-- The prompt art name for one binding: key_space, mouse_left, xbox_a, ps_cross, pad_south, xbox_lstick, unknown.
function Bindings.glyph_name(gset, binding)
  local colon = binding:find(":", 1, true)
  local kind, name = binding, ""
  if colon then kind, name = binding:sub(1, colon - 1), binding:sub(colon + 1) end
  if kind == "key" then return "key_" .. name end
  if kind == "mouse" then return "mouse_" .. name end
  if kind == "pad_axis" then
    if name:sub(1, 4) == "left" then name = "lstick" else name = "rstick" end
  elseif kind ~= "pad" then
    return "unknown"
  end
  if gset == "xbox" then return "xbox_" .. (XBOX[name] or name) end
  if gset == "playstation" then return "ps_" .. (PLAYSTATION[name] or name) end
  return "pad_" .. name
end

-- The binding to show for an action: slot 0 (keyboard) for the keyboard set, slot 1 (pad) otherwise; "" if none.
function Bindings.prompt_binding(bindings, action, gset)
  local list = bindings[action] or {}
  local slot = (gset == "keyboard") and 0 or 1
  return list[slot + 1] or ""
end

local function one_line(text) return (tostring(text or ""):gsub("%s+", " "):match("^%s*(.-)%s*$")) end

-- What the narration says for one control (#165): "Music volume, slider, 70 percent"; no label says "unlabelled".
function Bindings.narration_line(label, role, value)
  local parts = { one_line(label) ~= "" and one_line(label) or "unlabelled" }
  if one_line(role) ~= "" then parts[#parts + 1] = one_line(role) end
  if one_line(value) ~= "" then parts[#parts + 1] = one_line(value) end
  return table.concat(parts, ", ")
end

return Bindings

-- {{FOOTER}}
