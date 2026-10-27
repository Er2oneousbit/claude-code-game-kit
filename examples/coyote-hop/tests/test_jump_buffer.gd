# ---------------------------------------------------------------------------
# test_jump_buffer.gd
# Purpose : GUT unit tests for JumpBuffer (early jump presses are remembered).
# Usage   : python tools/dev.py test      (needs the GUT addon in addons/gut/)
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends GutTest


func test_nothing_pending_before_a_press() -> void:
	var b := JumpBuffer.new(0.12)
	assert_false(b.is_pending())


func test_press_is_remembered_inside_window() -> void:
	var b := JumpBuffer.new(0.12)
	b.press()
	b.update(0.08)
	assert_true(b.is_pending(), "an 80 ms early press should still count")


func test_press_expires_after_window() -> void:
	var b := JumpBuffer.new(0.12)
	b.press()
	b.update(0.2)
	assert_false(b.is_pending(), "a 200 ms early press should be forgotten")


func test_clear_uses_up_the_press() -> void:
	var b := JumpBuffer.new(0.12)
	b.press()
	b.clear()
	assert_false(b.is_pending(), "one press, one jump")


func test_negative_window_is_clamped() -> void:
	var b := JumpBuffer.new(-1.0)
	b.press()
	assert_false(b.is_pending(), "bad tuning data must not create a permanent buffer")
