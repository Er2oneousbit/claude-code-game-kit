-- ---------------------------------------------------------------------------
-- test_analog_input.lua
-- Purpose : Analog input (#274): src/core/analog.lua's radial, rescaled stick deadzone, invert_y, trigger deadzone
--           and the move_* actions a leaning stick holds; and the shell input giving them to the game through
--           move_vector(), triggers(), is_down() and held_actions().
-- Usage   : python tools/dev.py test     (or --filter analog)
-- Notes   : The same cases as the Bevy shell's logic/analog.rs tests, with up as -y (LÖVE's convention). The shell
--           input runs on a stand-in app (settings and a binding_pressed that records), fed through input:axis().
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local Analog = require("src.core.analog")
local Bindings = require("src.core.bindings")
local Input = require("src.shell.input")
local T = {}

local function app(deadzone, invert_y)
  local a = { settings = { input = { bindings = Bindings.defaults(), deadzone = deadzone or 0.2,
                                     invert_y = invert_y or false } }, pressed = {} }
  function a:binding_pressed(binding) self.pressed[#self.pressed + 1] = binding end
  return a
end

function T.test_the_stick_is_still_inside_the_deadzone_and_rescales_from_zero_past_it()
  local x, y = Analog.stick(0.15, 0.1, 0.2, false)
  A.eq(x, 0) A.eq(y, 0)
  x = Analog.stick(0.21, 0, 0.2, false)                 -- just past the deadzone: a small push, never a jump to 0.2
  A.truthy(x > 0 and x < 0.02, tostring(x))
  A.near((Analog.stick(0.6, 0, 0.2, false)), 0.5, 1e-6)
  A.near((Analog.stick(1, 0, 0.2, false)), 1, 1e-6)
  x, y = Analog.stick(1, 1, 0.2, false)                 -- a diagonal past full deflection: length 1, direction kept
  A.near(math.sqrt(x * x + y * y), 1, 1e-6)
  A.near(x, y, 1e-9)
  x, y = Analog.stick(-0.3, 0.4, 0, false)              -- no deadzone: the raw value
  A.near(x, -0.3, 1e-9) A.near(y, 0.4, 1e-9)
end

function T.test_invert_y_flips_only_the_vertical_axis()
  local x, y = Analog.stick(0, -1, 0.2, true)
  A.near(x, 0, 1e-9) A.near(y, 1, 1e-6)
  x, y = Analog.stick(1, 0, 0.2, true)
  A.near(x, 1, 1e-6) A.near(y, 0, 1e-9)
end

function T.test_triggers_rescale_past_their_deadzone_and_ignore_bad_values()
  A.eq(Analog.trigger(0.04), 0)
  A.eq(Analog.trigger(1), 1)
  A.near(Analog.trigger(0.525, Analog.TRIGGER_DEADZONE), 0.5, 1e-6)
  A.eq(Analog.trigger(-0.5, 0), 0, "a trigger never goes negative")
  A.eq(Analog.trigger(0 / 0, 0), 0, "NaN")
  local x, y = Analog.stick(0 / 0, -1, 0, false)
  A.eq(x, 0) A.near(y, -1, 1e-9)
end

function T.test_stick_actions_need_more_than_drift()
  A.same(Analog.stick_actions(-0.5, 0, 0.2, false), { "move_left" })
  A.same(Analog.stick_actions(0.5, -0.5, 0.2, false), { "move_right", "move_up" })
  A.same(Analog.stick_actions(Analog.STICK_HOLD_MIN - 0.05, 0, 0, false), {}, "a drifting stick with deadzone 0")
  A.same(Analog.stick_actions(0.3, 0, 0.4, false), {}, "the player's bigger deadzone wins")
  A.same(Analog.stick_actions(0, -0.8, 0.2, true), { "move_down" }, "invert_y")
end

function T.test_the_shell_input_gives_the_shaped_stick_and_triggers()
  local input = Input.new(app(0.2, true))
  A.eq(select(2, input:move_vector()), 0, "zero without a pad")
  input:axis(nil, "leftx", 0.6)
  input:axis(nil, "lefty", 0)
  A.near((input:move_vector()), 0.5, 1e-6)
  input:axis(nil, "leftx", 0)
  input:axis(nil, "lefty", -1)                          -- stick up, invert_y on: down (+y)
  A.near(select(2, input:move_vector()), 1, 1e-6)
  input:axis(nil, "triggerleft", 0.525)
  input:axis(nil, "triggerright", 1)
  local l, r = input:triggers()
  A.near(l, 0.5, 1e-6) A.eq(r, 1)
  input:axis(nil, "triggerright", 0.02)
  A.eq(select(2, input:triggers()), 0, "a trigger at rest reads 0")
end

function T.test_a_leaning_stick_holds_move_actions_and_held_actions_skip_ui()
  local a = app(0.2, false)
  local input = Input.new(a)
  input:axis(nil, "leftx", -0.3)                        -- past the deadzone, short of the d-pad's STICK_ON
  A.truthy(input:is_down("move_left"), "the stick holds move_left without a stick binding")
  A.falsy(input:is_down("ui_left"), "menus follow the d-pad thresholds, not the analog hold")
  A.same(input:held_actions(), { "move_left" })
  input.forced.jump = true
  A.same(input:held_actions(), { "jump", "move_left" })
  input:axis(nil, "leftx", 0)
  input.forced.jump = nil
  A.same(input:held_actions(), {})
end

return T

-- {{FOOTER}}
