# ---------------------------------------------------------------------------
# spring.gd
# Purpose : A damped spring (engine-free) for squash and stretch recovery, UI pops and wobble, plus the
#           volume-keeping squash scale.
# Usage   : var spring := Spring.new(4.0, 0.5)              # frequency Hz, damping ratio (1 = no overshoot)
#           on a hit:   spring.x = 0.4                      # kick it away from target (0)
#           each tick:  spring.update(dt); sprite.scale = Spring.squash(spring.x)
# Notes   : Semi-implicit Euler, so it stays stable at normal frame rates. squash(a): a > 0 widens and flattens,
#           a < 0 stretches; amount is clamped above -0.9 so the scale never reaches 0. squash() returns a Vector2
#           (32-bit floats); that is well inside the golden tolerance. Tested against data/golden/juice.json.
#
# Pseudocode:
#   w = 2 pi frequency; a = -w^2 (x - target) - 2 damping w v; v += a dt; x += v dt
#   squash(a) = (1 + a, 1 / (1 + a)) with a >= -0.9
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name Spring
extends RefCounted

const MIN_SQUASH: float = -0.9

var frequency: float
var damping: float
var x: float = 0.0 # current value
var v: float = 0.0 # velocity
var target: float = 0.0


func _init(p_frequency: float = 4.0, p_damping: float = 0.5) -> void:
	frequency = p_frequency
	damping = p_damping


func update(dt: float) -> float:
	var w: float = 2.0 * PI * frequency
	var a: float = -w * w * (x - target) - 2.0 * damping * w * v
	v += a * dt
	x += v * dt
	return x


static func squash(amount: float) -> Vector2:
	var a: float = maxf(amount, MIN_SQUASH)
	return Vector2(1.0 + a, 1.0 / (1.0 + a))
