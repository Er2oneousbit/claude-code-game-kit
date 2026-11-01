# ---------------------------------------------------------------------------
# easing.gd
# Purpose : Named easing curves (engine-free), the same set and formulas in every engine of the kit.
# Usage   : var k := Easing.apply("out_back", t)        # t is clamped to 0..1
#           position = start.lerp(end, Easing.apply("out_cubic", elapsed / duration))
# Notes   : Names: linear, in_quad, out_quad, in_out_quad, in_cubic, out_cubic, in_out_cubic, in_sine, out_sine,
#           in_out_sine, in_back, out_back, out_elastic, out_bounce. An unknown name is an error (push_error, NAN).
#           Not called ease(): that is a built-in GDScript function. Tested against data/golden/juice.json.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name Easing
extends RefCounted

const NAMES: PackedStringArray = ["linear", "in_quad", "out_quad", "in_out_quad", "in_cubic", "out_cubic",
		"in_out_cubic", "in_sine", "out_sine", "in_out_sine", "in_back", "out_back", "out_elastic", "out_bounce"]
const C1: float = 1.70158 # back overshoot
const C3: float = C1 + 1.0
const C4: float = 2.0 * PI / 3.0 # elastic period
const BOUNCE_N1: float = 7.5625
const BOUNCE_D1: float = 2.75


static func has(curve: String) -> bool:
	return NAMES.has(curve)


static func apply(curve: String, t: float) -> float:
	t = minf(maxf(t, 0.0), 1.0)
	match curve:
		"linear":
			return t
		"in_quad":
			return t * t
		"out_quad":
			return 1.0 - (1.0 - t) * (1.0 - t)
		"in_out_quad":
			return 2.0 * t * t if t < 0.5 else 1.0 - pow(-2.0 * t + 2.0, 2.0) / 2.0
		"in_cubic":
			return t * t * t
		"out_cubic":
			return 1.0 - pow(1.0 - t, 3.0)
		"in_out_cubic":
			return 4.0 * t * t * t if t < 0.5 else 1.0 - pow(-2.0 * t + 2.0, 3.0) / 2.0
		"in_sine":
			return 1.0 - cos(t * PI / 2.0)
		"out_sine":
			return sin(t * PI / 2.0)
		"in_out_sine":
			return -(cos(PI * t) - 1.0) / 2.0
		"in_back":
			return C3 * t * t * t - C1 * t * t
		"out_back":
			return 1.0 + C3 * pow(t - 1.0, 3.0) + C1 * pow(t - 1.0, 2.0)
		"out_elastic":
			if t <= 0.0:
				return 0.0
			if t >= 1.0:
				return 1.0
			return pow(2.0, -10.0 * t) * sin((t * 10.0 - 0.75) * C4) + 1.0
		"out_bounce":
			return _bounce(t)
	push_error("Easing: unknown curve '%s'" % curve)
	return NAN


static func _bounce(t: float) -> float:
	if t < 1.0 / BOUNCE_D1:
		return BOUNCE_N1 * t * t
	if t < 2.0 / BOUNCE_D1:
		t -= 1.5 / BOUNCE_D1
		return BOUNCE_N1 * t * t + 0.75
	if t < 2.5 / BOUNCE_D1:
		t -= 2.25 / BOUNCE_D1
		return BOUNCE_N1 * t * t + 0.9375
	t -= 2.625 / BOUNCE_D1
	return BOUNCE_N1 * t * t + 0.984375

# {{FOOTER}}
