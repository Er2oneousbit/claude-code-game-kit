-- ---------------------------------------------------------------------------
-- input.lua
-- Purpose : The shell's input: turns LÖVE's key, gamepad and stick events into bindings ("key:space",
--           "pad:south"), remembers the last device (for the prompt glyphs), answers "is this action held?",
--           captures the next press for "press a key" rebinding, lets a drive script hold actions, and gives the
--           game the pad's analog values (#274).
-- Usage   : local Input = require("src.shell.input"); local input = Input.new(app)
--           main.lua events -> app -> input:real_key(key, isrepeat) / real_button(joystick, button) / real_axis(...)
--           (drives and tests: input:key / button / axis, which a scripted run still takes)
--           input:is_down("move_left")   input.last_device ("keyboard", "mouse", "pad_xbox", ...)
--           input:capture("key", function(binding) ... end)   -- nil binding = cancelled (Esc, or Back on a pad)
--           analog: input:move_vector() -> x, y ; input:triggers() -> left, right ; input:held_actions()
-- Notes   : The left stick also counts as the d-pad (menus and the demo) past STICK_ON, and holds move_left/right/
--           up/down past the player's deadzone (is_down, held_actions), whatever the bindings say. move_vector() is
--           the stick with the Bevy shell's rules (src/core/analog.lua): a radial, rescaled deadzone from
--           input.deadzone and input.invert_y, up is -y. Triggers are axes in LÖVE: triggers() reads them 0 to 1,
--           and past TRIGGER_ON they also press pad:l2 / pad:r2. Key repeat only repeats ui_* actions (holding
--           Down scrolls a menu; holding Space does not jump twice). With scripted set (a drive runs), the real_*
--           events and the keyboard and pad polls in is_down are ignored: only the drive presses (#276).
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): real devices are not read while a drive runs (#276)
-- ---------------------------------------------------------------------------
local Analog = require("src.core.analog")
local InputMap = require("src.core.input_map")

local Input = {}
Input.__index = Input

-- ---- Tunables ----------------------------------------------------------------
local STICK_ON, STICK_OFF = 0.5, 0.3     -- stick-as-dpad press and release thresholds (hysteresis)
local TRIGGER_ON, TRIGGER_OFF = 0.5, 0.3

function Input.new(app)
  -- raw: the pad's analog values as LÖVE reports them (left stick -1..1, triggers 0..1); tests may set them
  -- scripted: a drive runs, so the real devices are not read (#276; app sets it)
  return setmetatable({ app = app, last_device = "keyboard", capturing = nil, forced = {}, scripted = false,
                        raw = { x = 0, y = 0, l2 = 0, r2 = 0 }, held_dirs = {}, trigger_on = {} }, Input)
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

-- ---- The real devices (#276) -----------------------------------------------------------------------------------
-- main.lua's callbacks come in here (through app); drives and tests call key / button / axis themselves. While a
-- drive runs (scripted: every smoke run has one) the real keyboard, mouse and pads reach nothing, so a stray key or
-- a virtual pad on a shared machine cannot open screens the tour does not expect.
function Input:real_key(key, isrepeat)
  if not self.scripted then self:key(key, isrepeat) end
end

function Input:real_button(joystick, button)
  if not self.scripted then self:button(joystick, button) end
end

function Input:real_axis(joystick, axis, value)
  if not self.scripted then self:axis(joystick, axis, value) end
end

function Input:real_mouse()
  if not self.scripted then self:mouse() end
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
    self.raw[name] = value
    local on = self.trigger_on[name]
    if value > TRIGGER_ON and not on then
      self.trigger_on[name] = true
      self.last_device = InputMap.device_of_pad(joystick and joystick:getName())
      if self.capturing and self.capturing.kind == "pad" then finish_capture(self, "pad:" .. name)
      elseif not self.capturing then self.app:binding_pressed("pad:" .. name, false) end
    elseif value < TRIGGER_OFF then
      self.trigger_on[name] = nil
    end
    return
  end
  if axis ~= "leftx" and axis ~= "lefty" then return end
  if axis == "leftx" then self.raw.x = value else self.raw.y = value end
  if math.abs(value) < dz then value = 0 end
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
  if keys then   -- a drive's run never asks the real keyboard (#276)
    return not self.scripted and love.keyboard and love.keyboard.isDown(unpack(keys)) or false
  end
  local dir = binding:match("^pad:(dpad_%a+)$")
  if dir and self.held_dirs[dir] then return true end
  local trig = binding:match("^pad:([lr]2)$")
  if trig then return self.trigger_on[trig] == true end
  local button = InputMap.love_button(binding)
  if button and love.joystick and not self.scripted then
    for _, j in ipairs(love.joystick.getJoysticks()) do
      if j:isGamepad() and j:isGamepadDown(button) then return true end
    end
  end
  return false
end

local function stick_holds(self, action)
  local input = self.app.settings.input
  for _, a in ipairs(Analog.stick_actions(self.raw.x, self.raw.y, input.deadzone or 0.2, input.invert_y)) do
    if a == action then return true end
  end
  return false
end

-- Held right now (keyboard, pad, stick, or held by a drive script)? The stick also holds move_* (Analog.stick_actions).
function Input:is_down(action)
  if self.forced[action] then return true end
  if stick_holds(self, action) then return true end
  local list = self:bindings()[action]
  if type(list) ~= "table" then return false end
  for _, b in ipairs(list) do
    if b ~= "" and binding_down(self, b) then return true end
  end
  return false
end

-- The game actions (no ui_*) held right now, sorted: a drift button, a charge, "hold to sprint".
function Input:held_actions()
  local out = {}
  for action in pairs(self:bindings()) do
    if action:sub(1, 3) ~= "ui_" and self:is_down(action) then out[#out + 1] = action end
  end
  table.sort(out)
  return out
end

-- The left stick for gameplay: each axis -1..1, the length 0..1, input.deadzone (radial, rescaled) and
-- input.invert_y applied, up is -y.
function Input:move_vector()
  local input = self.app.settings.input
  return Analog.stick(self.raw.x, self.raw.y, input.deadzone or 0.2, input.invert_y)
end

-- The analog triggers, 0 at rest to 1 fully in (Analog.TRIGGER_DEADZONE applied): left, right.
function Input:triggers()
  return Analog.trigger(self.raw.l2), Analog.trigger(self.raw.r2)
end

return Input

-- {{FOOTER}}
