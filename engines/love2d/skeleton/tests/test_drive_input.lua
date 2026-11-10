-- ---------------------------------------------------------------------------
-- test_drive_input.lua
-- Purpose : #276: while a smoke drive runs, a real key, pad button, stick or mouse move (a stray key, a virtual pad
--           on a shared machine) must not reach the shell, and the keyboard and pads are not polled for held
--           actions; the drive's own presses still count; normal play reads all of it.
-- Usage   : python tools/dev.py test     (or --filter drive_input)
-- Notes   : The shell input runs on a stand-in app (settings and a binding_pressed that records), as in
--           test_analog_input.lua. Real events come in the way main.lua's callbacks send them (input:real_*); the
--           real keyboard and pads are stand-ins for love.keyboard.isDown and love.joystick.getJoysticks, put
--           back after each test.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local Bindings = require("src.core.bindings")
local Input = require("src.shell.input")
local T = {}

local function app()
  local a = { settings = { input = { bindings = Bindings.defaults(), deadzone = 0.2, invert_y = false } },
              pressed = {} }
  function a:binding_pressed(binding) self.pressed[#self.pressed + 1] = binding end
  return a
end

-- Runs f with the real keyboard holding `key` and one pad holding `button` (stand-ins for LÖVE's devices).
local function with_devices(key, button, f)
  local keyboard, joystick = love.keyboard, love.joystick
  love.keyboard = { isDown = function(...)
    for _, k in ipairs({ ... }) do if k == key then return true end end
    return false
  end }
  local pad = { isGamepad = function() return true end, isGamepadDown = function(_, b) return b == button end,
                getName = function() return "Xbox Wireless Controller" end }
  love.joystick = { getJoysticks = function() return { pad } end }
  local ok, err = pcall(f, pad)
  love.keyboard, love.joystick = keyboard, joystick
  if not ok then error(err, 0) end
end

local function events(input, pad)
  input:real_key("d", false)                             -- move_right's key
  input:real_button(pad, "a")                            -- south: ui_accept
  input:real_axis(pad, "leftx", 0.9)                     -- the stick, past the d-pad threshold
  input:real_mouse()
end

function T.test_normal_play_reads_the_real_devices()
  with_devices("d", "a", function(pad)
    local a = app()
    local input = Input.new(a)
    events(input, pad)
    A.same(a.pressed, { "key:d", "pad:south", "pad:dpad_right" })
    A.eq(input.last_device, "mouse", "the device the prompts follow")
    A.truthy(input:is_down("move_right"), "the held D key")
    A.truthy(input:is_down("ui_accept"), "the held pad button")
    A.truthy(input:move_vector() > 0.5, "the stick steers")
  end)
end

function T.test_a_drive_ignores_the_real_devices()
  with_devices("d", "a", function(pad)
    local a = app()
    local input = Input.new(a)
    input.scripted = true                                -- what app does when a drive runs
    input.last_device = "pad_other"
    events(input, pad)
    A.same(a.pressed, {}, "no real press reached the shell")
    A.eq(input.last_device, "pad_other", "the prompts stay where the drive put them")
    A.falsy(input:is_down("move_right"), "the held D key holds nothing")
    A.falsy(input:is_down("ui_accept"), "nor does the held pad button")
    A.eq((input:move_vector()), 0, "nor does the stick")
    A.same(input:held_actions(), {})
  end)
end

function T.test_the_drives_own_presses_still_count()
  with_devices(nil, nil, function()
    local a = app()
    local input = Input.new(a)
    input.scripted = true
    input:button(nil, "a")                               -- the access drive's pad press (drive.lua)
    input:key("escape", false)                           -- its Escape and F8
    A.same(a.pressed, { "pad:south", "key:escape" })
    input.forced.attack = true                           -- a drive holding an action
    A.truthy(input:is_down("attack"))
  end)
end

return T

-- {{FOOTER}}
