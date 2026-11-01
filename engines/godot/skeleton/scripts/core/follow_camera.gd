# ---------------------------------------------------------------------------
# follow_camera.gd
# Purpose : Camera follow logic (engine-free): a deadzone box around the camera, look-ahead along the target's
#           velocity, and frame-rate independent exponential smoothing.
# Usage   : var follow := FollowCamera.new(64.0, 48.0, 0.25, 8.0)   # deadzone w/h px, look-ahead s, smoothing
#           each tick: follow.update(dt, player.x, player.y, velocity.x, velocity.y)
#                      camera.position = follow.position()
# Notes   : smoothing 0 snaps (no lag). The target can move inside the deadzone without moving the camera, which
#           keeps small hops from jiggling the screen. x and y stay 64-bit floats; position() packs them.
#           Tested against data/golden/juice.json.
#
# Pseudocode:
#   per axis: target past the deadzone edge -> desired = target pulled back by half the deadzone, else camera
#   desired += velocity * lookahead
#   k = 1 - exp(-smoothing * dt) (1 when smoothing is 0); camera += (desired - camera) * k
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name FollowCamera
extends RefCounted

var deadzone_w: float
var deadzone_h: float
var lookahead: float # seconds of velocity to lead the target by
var smoothing: float # higher = tighter; 0 = snap
var x: float
var y: float


func _init(p_deadzone_w: float = 64.0, p_deadzone_h: float = 48.0, p_lookahead: float = 0.25,
		p_smoothing: float = 8.0, p_x: float = 0.0, p_y: float = 0.0) -> void:
	deadzone_w = p_deadzone_w
	deadzone_h = p_deadzone_h
	lookahead = p_lookahead
	smoothing = p_smoothing
	x = p_x
	y = p_y


static func _axis(cam: float, target: float, half: float) -> float:
	if target > cam + half:
		return target - half
	if target < cam - half:
		return target + half
	return cam


func update(dt: float, tx: float, ty: float, vx: float = 0.0, vy: float = 0.0) -> void:
	var dx: float = _axis(x, tx, deadzone_w / 2.0) + vx * lookahead
	var dy: float = _axis(y, ty, deadzone_h / 2.0) + vy * lookahead
	var k: float = 1.0 - exp(-smoothing * dt) if smoothing > 0.0 else 1.0
	x += (dx - x) * k
	y += (dy - y) * k


func position() -> Vector2:
	return Vector2(x, y)

# {{FOOTER}}
