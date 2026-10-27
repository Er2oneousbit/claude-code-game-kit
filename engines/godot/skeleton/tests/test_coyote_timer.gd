# ---------------------------------------------------------------------------
# test_coyote_timer.gd
# Purpose : GUT unit tests for CoyoteTimer. Doubles as the example of how to
#           write engine-free tests in this project.
# Usage   : python tools/dev.py test      (needs the GUT addon in addons/gut/)
# Notes   : Test names describe behavior. No scene tree needed.
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# ---------------------------------------------------------------------------
extends GutTest


func test_can_jump_when_on_floor() -> void:
	var t := CoyoteTimer.new(0.1)
	t.update(0.016, true)
	assert_true(t.can_jump(), "should be able to jump while grounded")


func test_can_jump_shortly_after_leaving_floor() -> void:
	var t := CoyoteTimer.new(0.1)
	t.update(0.016, true)
	t.update(0.05, false)
	assert_true(t.can_jump(), "grace window should still be open at 50 ms")


func test_cannot_jump_after_window_expires() -> void:
	var t := CoyoteTimer.new(0.1)
	t.update(0.016, true)
	t.update(0.2, false)
	assert_false(t.can_jump(), "grace window should be closed at 200 ms")


func test_consume_closes_window() -> void:
	var t := CoyoteTimer.new(0.1)
	t.update(0.016, true)
	t.consume()
	assert_false(t.can_jump(), "consumed jump must not be reusable")


func test_consumed_jump_stays_used_while_still_grounded() -> void:
	var t := CoyoteTimer.new(0.1)
	t.update(0.016, true)
	t.consume()
	t.update(0.016, true) # physics has not lifted the body yet
	assert_false(t.can_jump(), "no second jump on the same ground contact")


func test_landing_rearms_jump() -> void:
	var t := CoyoteTimer.new(0.1)
	t.update(0.016, true)
	t.consume()
	t.update(0.3, false)
	t.update(0.016, true)
	assert_true(t.can_jump(), "landing should make the jump available again")


func test_zero_window_still_allows_grounded_jump() -> void:
	var t := CoyoteTimer.new(0.0)
	t.update(0.016, true)
	assert_true(t.can_jump(), "zero window means no coyote time, not no jumping")
	t.update(0.016, false)
	assert_false(t.can_jump(), "zero window gives no grace after leaving the floor")


func test_negative_window_is_clamped() -> void:
	var t := CoyoteTimer.new(-1.0)
	assert_eq(t.window, 0.0, "negative tuning value should clamp to a zero window")

# {{FOOTER}}
