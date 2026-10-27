# ---------------------------------------------------------------------------
# jump_math.gd
# Purpose : Closed-form jump arc math, so level design can be checked against
#           the tuning numbers without running physics.
# Usage   : JumpMath.apex_height(v, g, dt); JumpMath.horizontal_reach(v, g, speed, rise, dt)
#           dt = physics step (1.0 / Engine.physics_ticks_per_second); 0.0 = the ideal continuous arc
# Notes   : Ignores acceleration ramps and the jump cut: it is the best case at
#           full speed with jump held. Tests apply Tuning.SAFETY_MARGIN on top.
#           Why dt: player.gd steps semi-implicit Euler (gravity is added to the velocity, then the
#           body moves by velocity * dt), so after n ticks the height is
#           v (n dt) - g dt^2 n (n - 1) / 2 = (v + g dt / 2) t - g t^2 / 2 at t = n dt. That is the
#           continuous parabola with v + g dt / 2, so passing dt makes both functions match the
#           ticks: at v 340, g 900, 60 ticks/s the apex is 67.09 px (measured 67.16, the 0.08 px
#           floor safe margin), not the 64.22 px of v^2 / 2g. The body lands on the first tick at
#           or past the computed time, so horizontal_reach stays a little short of the real travel
#           (flat ground at 120 px/s: 92.67 px here, 90.67 px without dt, 96 px measured in game):
#           it errs on the safe side for level checks. Long drops also hit MAX_FALL_SPEED, which
#           only lengthens the real reach.
#
# Pseudocode:
#   v' = v + g dt / 2                          (dt = 0 gives the textbook formulas)
#   apex = v'^2 / 2g
#   time to come back down to height `rise` (descending root of v' t - g t^2 / 2 = rise)
#     t = (v' + sqrt(v'^2 - 2 g rise)) / g     (no solution when rise > apex)
#   reach = speed * t
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): optional dt term for the
#           semi-implicit Euler step the physics really takes
# ---------------------------------------------------------------------------
class_name JumpMath
extends RefCounted


static func apex_height(jump_velocity: float, gravity: float, dt: float = 0.0) -> float:
	var v: float = _effective_velocity(jump_velocity, gravity, dt)
	return v * v / (2.0 * gravity)


# Horizontal distance covered before the arc falls back to `rise` px above the
# take-off point (negative rise = landing lower). Returns -1.0 if never that high.
static func horizontal_reach(jump_velocity: float, gravity: float, speed: float, rise: float, dt: float = 0.0) -> float:
	var v: float = _effective_velocity(jump_velocity, gravity, dt)
	var disc: float = v * v - 2.0 * gravity * rise
	if disc < 0.0:
		return -1.0
	return speed * (v + sqrt(disc)) / gravity


# The take-off velocity of the continuous parabola that passes through every physics tick's position.
static func _effective_velocity(jump_velocity: float, gravity: float, dt: float) -> float:
	return jump_velocity + gravity * maxf(dt, 0.0) / 2.0
