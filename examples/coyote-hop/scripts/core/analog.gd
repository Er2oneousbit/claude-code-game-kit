# ---------------------------------------------------------------------------
# analog.gd
# Purpose : Analog input shaping (#274): the left stick and the triggers as the game reads them, after the player's
#           deadzone and invert_y, so a racer steers by how far the stick leans and brakes by how far a trigger is in.
#           The same rules as the Bevy shell's Intent (#265).
# Usage   : var v: Vector2 = Analog.stick(raw, Shell.settings.input.deadzone, Shell.settings.input.invert_y)
#           var gas: float = Analog.trigger(raw_r2)               # 0 at rest to 1 fully in
#           (the Shell does both for the game: Shell.stick(), Shell.triggers())
# Notes   : Engine-free (no Input calls), so GUT tests it alone. The stick deadzone is radial (the length of the
#           vector, not each axis), and what is left is rescaled to 0..1, so a stick just past the deadzone gives a
#           small value instead of jumping to the deadzone's size; the direction never changes. This is also what
#           Input.get_vector() does with the same deadzone. Up is -y, as Godot's joypad axes and screen coordinates
#           have it; invert_y flips it. Triggers have their own small fixed deadzone: input.deadzone is the "Stick
#           dead zone" setting, and a trigger that rests at 0.1 would otherwise lose a fifth of its travel. NaN and
#           infinities (a broken driver) count as 0.
#
# Pseudocode:
#   stick(v, dz, inv): v.y = -v.y if inv -> len = |v| -> len <= dz: (0, 0)
#   -> scale = min((len - dz) / (1 - dz), 1) / len -> v * scale
#   trigger(t, dz): t = clamp(t, 0, 1) -> t <= dz: 0 -> (t - dz) / (1 - dz)
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name Analog
extends RefCounted

const TRIGGER_DEADZONE: float = 0.05 # trigger travel ignored at rest (0 to 1)
const MAX_DEADZONE: float = 0.95 # the largest deadzone accepted (settings clamp input.deadzone to 0.9 too)
const STICK_HOLD_MIN: float = 0.2 # raw stick lean that also holds a move_* action; never below the player's deadzone


## The stick after the radial deadzone and invert_y: each axis -1..1, the vector's length 0..1, up is -y.
static func stick(raw: Vector2, deadzone: float, invert_y: bool) -> Vector2:
	var v: Vector2 = Vector2(_finite(raw.x), _finite(raw.y))
	if invert_y:
		v.y = -v.y
	var dz: float = clampf(_finite(deadzone), 0.0, MAX_DEADZONE)
	var length: float = v.length()
	if length <= dz or length == 0.0:
		return Vector2.ZERO
	return v * (minf((length - dz) / (1.0 - dz), 1.0) / length)


## A trigger (0 at rest, 1 fully in) after its deadzone, rescaled to 0..1.
static func trigger(value: float, deadzone: float = TRIGGER_DEADZONE) -> float:
	var v: float = clampf(_finite(value), 0.0, 1.0)
	var dz: float = clampf(_finite(deadzone), 0.0, MAX_DEADZONE)
	return 0.0 if v <= dz else (v - dz) / (1.0 - dz)


## The action deadzone that makes a leaning stick hold a move_* action: the player's, never below STICK_HOLD_MIN.
static func hold_deadzone(deadzone: float) -> float:
	return maxf(_finite(deadzone), STICK_HOLD_MIN)


static func _finite(v: float) -> float:
	return v if is_finite(v) else 0.0
