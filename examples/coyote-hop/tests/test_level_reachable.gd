# ---------------------------------------------------------------------------
# test_level_reachable.gd
# Purpose : Design guard: every gap in LevelData can be jumped with the numbers
#           in Tuning, with a safety margin, and the level's pieces sit where they
#           should. Retune the jump or move a platform and this fails first.
# Usage   : python tools/dev.py test      (needs the GUT addon in addons/gut/)
# Notes   : Uses JumpMath's best-case arc (full speed, jump held) at the project's physics
#           step, scaled by Tuning.SAFETY_MARGIN. The two tick-by-tick tests prove that arc
#           never promises more than player.gd's integration delivers. The autoplay bot
#           (main.gd --autoplay) is the in-engine check of the same thing.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): arcs include the physics step;
#           tick-by-tick checks of JumpMath against the semi-implicit Euler step
# ---------------------------------------------------------------------------
extends GutTest


func _dt() -> float:
	return 1.0 / Engine.physics_ticks_per_second


# Steps a full held jump the way player.gd does (velocity first, then position) and returns
# [highest rise, horizontal travel when it first comes back down to `rise`], in px.
func _simulate_jump(rise: float) -> Array[float]:
	var dt: float = _dt()
	var vy: float = -Tuning.JUMP_VELOCITY
	var height: float = 0.0
	var top: float = 0.0
	var ticks: int = 0
	while ticks < 10000:
		if ticks > 0:
			vy = minf(vy + Tuning.GRAVITY * dt, Tuning.MAX_FALL_SPEED)
		height -= vy * dt
		ticks += 1
		top = maxf(top, height)
		if vy > 0.0 and height <= rise:
			break
	return [top, Tuning.RUN_SPEED * dt * ticks]


func test_apex_matches_formula() -> void:
	assert_almost_eq(JumpMath.apex_height(520.0, 1400.0), 96.57, 0.01)


func test_reach_on_flat_ground_is_speed_times_airtime() -> void:
	# Airtime on flat ground is 2v/g.
	assert_almost_eq(JumpMath.horizontal_reach(520.0, 1400.0, 200.0, 0.0), 200.0 * 2.0 * 520.0 / 1400.0, 0.01)


func test_too_high_is_unreachable() -> void:
	assert_eq(JumpMath.horizontal_reach(520.0, 1400.0, 200.0, 500.0), -1.0)


func test_apex_with_step_matches_the_ticks() -> void:
	# The closed form without dt said 64.22 px; the physics really climbs 67.1 px.
	var formula: float = JumpMath.apex_height(Tuning.JUMP_VELOCITY, Tuning.GRAVITY, _dt())
	var ticked: float = _simulate_jump(0.0)[0]
	assert_true(ticked <= formula + 0.001, "tick apex %.3f px must not exceed the formula %.3f px" % [ticked, formula])
	assert_almost_eq(ticked, formula, 0.05, "the dt term makes the formula match the ticks")
	assert_gt(ticked, JumpMath.apex_height(Tuning.JUMP_VELOCITY, Tuning.GRAVITY) + 2.0, "without dt the formula is too low")


func test_reach_with_step_is_never_more_than_the_ticks() -> void:
	# Conservative: the formula may come up short of the real travel, by at most one tick
	# while the fall stays under MAX_FALL_SPEED (the -36 px drop hits it, which only adds travel).
	for rise: float in [36.0, 18.0, 0.0, -36.0]:
		var formula: float = JumpMath.horizontal_reach(Tuning.JUMP_VELOCITY, Tuning.GRAVITY, Tuning.RUN_SPEED, rise, _dt())
		var ticked: float = _simulate_jump(rise)[1]
		assert_true(formula <= ticked, "rise %d: formula %.2f px <= ticks %.2f px" % [rise, formula, ticked])
		if rise >= 0.0:
			assert_lt(ticked - formula, Tuning.RUN_SPEED * _dt() + 0.001, "rise %d: within one tick" % rise)


func test_every_step_up_is_below_the_apex() -> void:
	var apex: float = JumpMath.apex_height(Tuning.JUMP_VELOCITY, Tuning.GRAVITY, _dt())
	var plats: Array[Rect2] = LevelData.platforms_px()
	for i in range(plats.size() - 1):
		var rise: float = plats[i].position.y - plats[i + 1].position.y
		assert_lt(rise, apex * Tuning.SAFETY_MARGIN, "platform %d -> %d rises %d px (apex %d)" % [i, i + 1, rise, apex])


func test_every_gap_is_within_reach() -> void:
	var plats: Array[Rect2] = LevelData.platforms_px()
	for i in range(plats.size() - 1):
		var gap: float = plats[i + 1].position.x - plats[i].end.x
		var rise: float = plats[i].position.y - plats[i + 1].position.y
		var reach: float = JumpMath.horizontal_reach(Tuning.JUMP_VELOCITY, Tuning.GRAVITY, Tuning.RUN_SPEED, rise, _dt())
		assert_lt(gap + Tuning.PLAYER_SIZE.x, reach * Tuning.SAFETY_MARGIN,
				"gap %d -> %d is %d px, reach with margin %d px" % [i, i + 1, gap, reach * Tuning.SAFETY_MARGIN])


func test_spawn_stands_on_the_first_platform() -> void:
	var first: Rect2 = LevelData.platforms_px()[0]
	var feet: Vector2 = LevelData.spawn_px() + Vector2(0, Tuning.PLAYER_SIZE.y / 2.0)
	assert_almost_eq(feet.y, first.position.y, 0.5)
	assert_between(feet.x, first.position.x, first.end.x)


func test_goal_stands_on_the_last_platform() -> void:
	var last: Rect2 = LevelData.platforms_px()[-1]
	var goal: Rect2 = LevelData.goal_px()
	assert_almost_eq(goal.end.y, last.position.y, 0.5)
	assert_between(goal.position.x, last.position.x, last.end.x - Tuning.TILE)


func test_coins_are_not_inside_platforms() -> void:
	for c: Vector2i in LevelData.COINS:
		for r: Rect2i in LevelData.PLATFORMS:
			assert_false(r.has_point(c), "coin at %s is inside platform %s" % [c, r])


func test_coins_are_within_jump_height() -> void:
	# The player's head at the top of a full jump from a nearby platform must reach
	# the bottom of the coin's pickup circle (main.gd uses radius 6, centered in the tile).
	var apex: float = JumpMath.apex_height(Tuning.JUMP_VELOCITY, Tuning.GRAVITY, _dt())
	for c: Vector2i in LevelData.COINS:
		var coin_bottom: float = c.y * Tuning.TILE + Tuning.TILE / 2.0 + 6.0
		var best_head: float = INF
		for r: Rect2i in LevelData.PLATFORMS:
			if c.x >= r.position.x - 4 and c.x < r.end.x + 4:
				best_head = minf(best_head, r.position.y * Tuning.TILE - Tuning.PLAYER_SIZE.y - apex)
		assert_lt(best_head, coin_bottom, "coin at %s: highest head %d px, coin bottom %d px" % [c, best_head, coin_bottom])
