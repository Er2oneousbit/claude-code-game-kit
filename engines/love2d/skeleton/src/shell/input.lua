-- ---------------------------------------------------------------------------
-- input.lua
-- Purpose : The shell's input: turns LÖVE's key, gamepad and stick events into bindings ("key:space",
--           "pad:south"), remembers the last device (for the prompt glyphs), answers "is this action held?",
--           captures the next press for "press a key" rebinding, and lets a drive script hold actions.
-- Usage   : local Input = require("src.shell.input"); local input = Input.new(app)
--           main.lua events -> app -> input:key(key, isrepeat) / input:button(joystick, button) / input:axis(...)
--           input:is_down("move_left")   input.last_device ("keyboard", "mouse", "pad_xbox", ...)
--           input:capture("key", function(binding) ... end)   -- nil binding = cancelled (Esc, or Back on a pad)
-- Notes   : The left stick also counts as the d-pad (menus and the demo), past the player's deadzone, and
--           input.invert_y flips its vertical axis for gameplay. Triggers are axes in LÖVE: past TRIGGER_ON they
--           press pad:l2 / pad:r2. Key repeat only repeats ui_* actions (holding Down scrolls a menu; holding
--           Space does not jump twice).
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local InputMap = require("src.core.input_map")

local Input = {}
Input.__index = Input

-- ---- Tunables ----------------------------------------------------------------
local STICK_ON, STICK_OFF = 0.5, 0.3     -- stick-as-dpad press and release thresholds (hysteresis)
local TRIGGER_ON, TRIGGER_OFF = 0.5, 0.3

function Input.new(app)
  return setmetatable({ app = app, last_device = "keyboard", capturing = nil, forced = {},
                        stick = { x = 0, y = 0 }, held_dirs = {}, triggers = {} }, Input)
end

function Input:bindings() return self.app.settings.input.bindings end

function Input:capture(kind, callback)
  self.capturing = { kind = kind, callback = callback }
end

function Input:is_capturing() return self.capturing ~= nil end

local function finish_capture(self, binding)
  local c = self.capturing
  self.capturing = nil
  c.callback(binding)
end

function Input:key(key, isrepeat)
  self.last_device = "keyboard"
  if self.capturing then
    if isrepeat then return end
    if key == "escape" then finish_capture(self, nil) return end
    if self.capturing.kind == "key" then finish_capture(self, InputMap.from_key(key)) end
    return
  end
  self.app:binding_pressed(InputMap.from_key(key), isrepeat)
end

function Input:button(joystick, button)
  self.last_device = InputMap.device_of_pad(joystick and joystick:getName())
  local binding = InputMap.from_button(button)
  if self.capturing then
    if button == "back" then finish_capture(self, nil) return end
    if self.capturing.kind == "pad" then finish_capture(self, binding) end
    return
  end
  self.app:binding_pressed(binding, false)
end

function Input:mouse()
  self.last_device = "mouse"
end

local function dir_edge(self, name, active)
  local was = self.held_dirs[name]
  if active and not was then
    self.held_dirs[name] = true
    if not self.capturing then self.app:binding_pressed("pad:" .. name, false) end
  elseif not active and was then
    self.held_dirs[name] = nil
  end
end

function Input:axis(joystick, axis, value)
  local dz = math.max(self.app.settings.input.deadzone or 0.2, 0.05)
  if axis == "triggerleft" or axis == "triggerright" then
    local name = axis == "triggerleft" and "l2" or "r2"
    local on = self.triggers[name]
    if value > TRIGGER_ON and not on then
      self.triggers[name] = true
      self.last_device = InputMap.device_of_pad(joystick and joystick:getName())
      if self.capturing and self.capturing.kind == "pad" then finish_capture(self, "pad:" .. name)
      elseif not self.capturing then self.app:binding_pressed("pad:" .. name, false) end
    elseif value < TRIGGER_OFF then
      self.triggers[name] = nil
    end
    return
  end
  if axis ~= "leftx" and axis ~= "lefty" then return end
  if math.abs(value) < dz then value = 0 end
  if axis == "leftx" then self.stick.x = value else self.stick.y = value end
  if value ~= 0 then self.last_device = InputMap.device_of_pad(joystick and joystick:getName()) end
  local on = math.max(STICK_ON, dz)
  if axis == "leftx" then
    dir_edge(self, "dpad_left", value < -on or (self.held_dirs.dpad_left and value < -STICK_OFF))
    dir_edge(self, "dpad_right", value > on or (self.held_dirs.dpad_right and value > STICK_OFF))
  else
    dir_edge(self, "dpad_up", value < -on or (self.held_dirs.dpad_up and value < -STICK_OFF))
    dir_edge(self, "dpad_down", value > on or (self.held_dirs.dpad_down and value > STICK_OFF))
  end
end

local function binding_down(self, binding)
  local keys = InputMap.love_keys(binding)
  if keys then
    return love.keyboard and love.keyboard.isDown(unpack(keys)) or false
  end
  local dir = binding:match("^pad:(dpad_%a+)$")
  if dir and self.held_dirs[dir] then return true end
  local trig = binding:match("^pad:([lr]2)$")
  if trig then return self.triggers[trig] == true end
  local button = InputMap.love_button(binding)
  if button and love.joystick then
    for _, j in ipairs(love.joystick.getJoysticks()) do
      if j:isGamepad() and j:isGamepadDown(button) then return true end
    end
  end
  return false
end

-- Held right now (keyboard, pad, stick, or held by a drive script)?
function Input:is_down(action)
  if self.forced[action] then return true end
  local list = self:bindings()[action]
  if type(list) ~= "table" then return false end
  for _, b in ipairs(list) do
    if b ~= "" and binding_down(self, b) then return true end
  end
  return false
end

-- The left stick for gameplay (-1..1 each, deadzone applied, invert_y honoured).
function Input:move_vector()
  local y = self.stick.y
  if self.app.settings.input.invert_y then y = -y end
  return self.stick.x, y
end

return Input

-- {{FOOTER}}
