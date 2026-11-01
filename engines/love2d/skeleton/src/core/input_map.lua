-- ---------------------------------------------------------------------------
-- input_map.lua
-- Purpose : Translates LÖVE's input names into the kit's binding strings and back (key:enter for LÖVE's
--           "return", pad:south for the gamepad's "a", ...), and finds the actions a binding triggers.
-- Usage   : local InputMap = require("src.core.input_map")
--           InputMap.from_key("return") -> "key:enter"      InputMap.from_button("a") -> "pad:south"
--           InputMap.love_keys("key:shift") -> { "lshift", "rshift" }
--           InputMap.actions_for(bindings, "key:escape") -> { "pause", "ui_cancel" } (sorted)
--           InputMap.device_of_pad("Xbox Controller") -> "pad_xbox"
-- Notes   : No love.* calls; src/shell/input.lua uses it with the real events. Pad names are positional (south =
--           the bottom face button on every controller), see src/core/bindings.lua. The pad brand comes from the
--           joystick's name, a heuristic (verify with your controllers).
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Json = require("src.core.json")

local InputMap = {}

-- ---- Tunables ----------------------------------------------------------------
local KEY_ALIASES = { ["return"] = "enter", kpenter = "enter", lshift = "shift", rshift = "shift", lctrl = "ctrl",
                      rctrl = "ctrl", lalt = "alt", ralt = "alt", lgui = "gui", rgui = "gui" }
local KEY_REVERSE = { enter = { "return", "kpenter" }, shift = { "lshift", "rshift" }, ctrl = { "lctrl", "rctrl" },
                      alt = { "lalt", "ralt" }, gui = { "lgui", "rgui" } }
local BUTTONS = { a = "south", b = "east", x = "west", y = "north", back = "select", start = "start", guide = "home",
                  leftshoulder = "l1", rightshoulder = "r1", leftstick = "l3", rightstick = "r3",
                  dpup = "dpad_up", dpdown = "dpad_down", dpleft = "dpad_left", dpright = "dpad_right" }
local BUTTONS_REVERSE = {}
for love_name, kit in pairs(BUTTONS) do BUTTONS_REVERSE[kit] = love_name end
local PLAYSTATION_HINTS = { "playstation", "dualshock", "dualsense", "ps3", "ps4", "ps5", "wireless controller" }
local XBOX_HINTS = { "xbox", "xinput", "x-box" }

function InputMap.from_key(key) return "key:" .. (KEY_ALIASES[key] or key) end
function InputMap.from_button(button) return "pad:" .. (BUTTONS[button] or button) end
function InputMap.from_mouse(button)
  local names = { [1] = "left", [2] = "right", [3] = "middle" }
  return "mouse:" .. (names[button] or tostring(button))
end

-- LÖVE key constants for a "key:" binding (nil for other kinds)
function InputMap.love_keys(binding)
  local name = binding:match("^key:(.+)$")
  if not name then return nil end
  return KEY_REVERSE[name] or { name }
end

-- LÖVE gamepad button for a "pad:" binding (nil for other kinds, and for l2/r2, which are axes in LÖVE)
function InputMap.love_button(binding)
  local name = binding:match("^pad:(.+)$")
  return name and BUTTONS_REVERSE[name] or nil
end

function InputMap.actions_for(bindings, binding)
  local out = {}
  for _, action in ipairs(Json.sorted_keys(bindings)) do
    local list = bindings[action]
    if type(list) == "table" then
      for _, b in ipairs(list) do
        if b == binding then out[#out + 1] = action; break end
      end
    end
  end
  return out
end

-- "pad_xbox" | "pad_playstation" | "pad_other" from a joystick's name
function InputMap.device_of_pad(name)
  name = (name or ""):lower()
  for _, hint in ipairs(PLAYSTATION_HINTS) do
    if name:find(hint, 1, true) then return "pad_playstation" end
  end
  for _, hint in ipairs(XBOX_HINTS) do
    if name:find(hint, 1, true) then return "pad_xbox" end
  end
  return "pad_other"
end

return InputMap

-- {{FOOTER}}
