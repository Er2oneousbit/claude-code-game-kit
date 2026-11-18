# ---------------------------------------------------------------------------
# feel.gd
# Purpose : The small helpers SOP-18's recipe table builds on (#170, #164): impact (a hit confirm scaled by damage),
#           float_text (a damage number's rise, pop and fade) and the tracer's point history by distance
#           (trail_push, trail_shrink, trail_length). Engine-free; matches data/golden/juice.json "impact",
#           "float_text" and "trail".
# Usage   : var hit: Dictionary = Feel.impact(damage, enemy.max_hp)
#           hitstop.hit(hit["hitstop"]); shake.add_trauma(hit["trauma"])
#           if hit["flash"] and limiter.request(Time.get_ticks_msec() / 1000.0): flash()
#           var f: Dictionary = Feel.float_text(label_age)          # dy, scale, alpha, done
#           tracer_points = Feel.trail_push(tracer_points, bullet.global_position.x, bullet.global_position.y,
#                   spacing, length)                                 # every frame, then
#           line.points = Feel.to_packed(tracer_points)              # a top_level Line2D (Dotwork's tracer Trail)
#           after the hit: tracer_points = Feel.trail_shrink(tracer_points, speed * dt)   # until < 2 points
# Notes   : Pure static functions: no settings, no clock, no random numbers. Points are an Array of [x, y] Arrays
#           (64-bit floats, as every port; a Vector2 is 32-bit), tail first, head last; each trail function returns
#           a new Array. The defaults are SOP-18's starting points.
#
# Pseudocode:
#   impact: f = clamp(damage / full, 0, 1) (full <= 0: 1); nothing for damage <= 0; lerp hitstop, trauma; flash f >= at
#   float_text: u = t / life; dy = -rise * out_cubic(u); scale = out_back(t / pop); alpha = 1 - in_cubic(u)
#   trail_push: < 2 points: append; head spacing past the point before it: append; else move the head; cut to length
#   trail_shrink: cut the trail to (length - amount) from the tail
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): impact is the same with blood on or off; what a
#           hit leaves is the game's: blood, or (blood_enabled off) a neutral spark or dust (SOP-18 step 4, #171)
# ---------------------------------------------------------------------------
class_name Feel
extends RefCounted

# ---- Tunables (SOP-18 step 4 starting points) --------------------------------
const HITSTOP_MIN: float = 0.03 # s, the smallest hit
const HITSTOP_MAX: float = 0.1 # s, a full hit (under Hitstop's 0.25 s cap)
const TRAUMA_MIN: float = 0.15
const TRAUMA_MAX: float = 0.6
const FLASH_AT: float = 0.5 # a hit of at least half of `full` asks for a flash
const FLOAT_LIFE: float = 0.8 # s
const FLOAT_RISE: float = 24.0 # px
const FLOAT_POP: float = 0.12 # s
const TRAIL_SPACING: float = 6.0 # px between kept points
const TRAIL_LENGTH: float = 48.0 # px, the longest trail
const EPS: float = 1e-12 # a cut this close to a point removes the point


static func impact(damage: float, full: float, hitstop_min: float = HITSTOP_MIN, hitstop_max: float = HITSTOP_MAX,
		trauma_min: float = TRAUMA_MIN, trauma_max: float = TRAUMA_MAX, flash_at: float = FLASH_AT) -> Dictionary:
	if damage <= 0.0:
		return {"hitstop": 0.0, "trauma": 0.0, "flash": false}
	var f: float = 1.0 if full <= 0.0 else clampf(damage / full, 0.0, 1.0)
	return {"hitstop": hitstop_min + (hitstop_max - hitstop_min) * f,
			"trauma": trauma_min + (trauma_max - trauma_min) * f, "flash": f >= flash_at}


static func float_text(t: float, life: float = FLOAT_LIFE, rise: float = FLOAT_RISE,
		pop_s: float = FLOAT_POP) -> Dictionary:
	var u: float = clampf(t / life, 0.0, 1.0) if life > 0.0 else 1.0
	var scale: float = Easing.apply("out_back", t / pop_s) if pop_s > 0.0 else 1.0
	return {"dy": -rise * Easing.apply("out_cubic", u), "scale": scale,
			"alpha": 1.0 - Easing.apply("in_cubic", u), "done": t >= life}


static func _seg(a: Array, b: Array) -> float:
	var dx: float = float(b[0]) - float(a[0])
	var dy: float = float(b[1]) - float(a[1])
	return sqrt(dx * dx + dy * dy)


static func trail_length(points: Array) -> float:
	var total: float = 0.0
	for i: int in points.size() - 1:
		total += _seg(points[i], points[i + 1])
	return total


static func _copy(points: Array) -> Array:
	var out: Array = []
	for p: Array in points:
		out.append([float(p[0]), float(p[1])])
	return out


static func _trim_to(points: Array, keep: float) -> Array:
	var pts: Array = _copy(points)
	var excess: float = trail_length(pts) - maxf(keep, 0.0)
	while excess > EPS and pts.size() > 1:
		var s: float = _seg(pts[0], pts[1])
		if s <= excess + EPS:
			pts.pop_front()
			excess -= s
		else:
			var k: float = excess / s
			pts[0] = [pts[0][0] + (pts[1][0] - pts[0][0]) * k, pts[0][1] + (pts[1][1] - pts[0][1]) * k]
			excess = 0.0
	return pts


static func trail_push(points: Array, x: float, y: float, spacing: float = TRAIL_SPACING,
		max_len: float = TRAIL_LENGTH) -> Array:
	var pts: Array = _copy(points)
	if pts.size() < 2 or _seg(pts[pts.size() - 2], pts[pts.size() - 1]) >= spacing:
		pts.append([x, y])
	else:
		pts[pts.size() - 1] = [x, y]
	return _trim_to(pts, max_len)


static func trail_shrink(points: Array, amount: float) -> Array:
	return _trim_to(points, trail_length(points) - amount)


## The points as a PackedVector2Array for a Line2D (drawing only: the history itself stays 64-bit).
static func to_packed(points: Array) -> PackedVector2Array:
	var out: PackedVector2Array = PackedVector2Array()
	for p: Array in points:
		out.append(Vector2(p[0], p[1]))
	return out
