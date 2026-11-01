# ---------------------------------------------------------------------------
# shake.gd
# Purpose : Trauma-based screen shake (engine-free). Hits add trauma (0..1), trauma decays linearly, and the
#           camera offset and angle are trauma squared times smooth noise, so small hits barely move the screen
#           and big ones kick hard.
# Usage   : var shake := Shake.new()                      # max_offset 8 px, max_angle 0.05 rad, decay 1.5/s
#           on a hit:    shake.add_trauma(0.5)
#           each frame:  shake.update(game_dt, Shell.effective_shake())   # game time: after hitstop and game speed
#                        camera.offset = shake.offset(); camera.rotation = shake.angle
# Notes   : Matches the kit's reference (tools/golden_vectors.py) and is tested against data/golden/juice.json.
#           intensity is the player's shake setting: 0 with reduce motion, so the camera never moves.
#           Results are kept as 64-bit floats (offset_x, offset_y, angle); offset() packs them into a Vector2.
#           Noise uses Park-Miller integer arithmetic, so every language gets the same numbers.
#
# Pseudocode:
#   lattice(seed, i, ch) -> a fixed pseudo-random value in (-1, 1] per integer point
#   noise(seed, t, ch)   -> blend the two lattice values around t with smoothstep
#   update(dt)           -> time += dt; trauma -= decay * dt (not below 0); s = trauma^2 * intensity
#                           offset = max_offset * s * noise(channel 0 / 1), angle = max_angle * s * noise(channel 2)
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name Shake
extends RefCounted

const PM_M: int = 2147483647 # Park-Miller modulus (2^31 - 1)
const PM_A: int = 16807 # Park-Miller multiplier
const SEED_MUL: int = 7919 # lattice hash: primes per input, products stay below 2^53
const INDEX_MUL: int = 104729
const CHANNEL_MUL: int = 15485863

var max_offset: float # pixels at full trauma
var max_angle: float # radians at full trauma
var decay: float # trauma lost per second
var frequency: float # noise lattice points per second (higher = faster jitter)
var noise_seed: int
var trauma: float = 0.0
var time: float = 0.0
var offset_x: float = 0.0 # results of the last update()
var offset_y: float = 0.0
var angle: float = 0.0


func _init(p_max_offset: float = 8.0, p_max_angle: float = 0.05, p_decay: float = 1.5,
		p_frequency: float = 15.0, p_seed: int = 1) -> void:
	max_offset = p_max_offset
	max_angle = p_max_angle
	decay = p_decay
	frequency = p_frequency
	noise_seed = p_seed


static func lattice(seed_value: int, i: int, ch: int) -> float:
	var s: int = posmod(seed_value * SEED_MUL + i * INDEX_MUL + ch * CHANNEL_MUL, PM_M)
	if s == 0:
		s = 1
	s = (s * PM_A) % PM_M
	s = (s * PM_A) % PM_M
	return float(s) / float(PM_M - 1) * 2.0 - 1.0


static func noise(seed_value: int, t: float, ch: int) -> float:
	# Smooth 1D value noise for t >= 0
	var i: int = floori(t)
	var f: float = t - float(i)
	var a: float = lattice(seed_value, i, ch)
	var b: float = lattice(seed_value, i + 1, ch)
	var u: float = f * f * (3.0 - 2.0 * f)
	return a + (b - a) * u


func add_trauma(amount: float) -> void:
	trauma = minf(maxf(trauma + amount, 0.0), 1.0)


func update(dt: float, intensity: float = 1.0) -> void:
	time += dt
	trauma = maxf(trauma - decay * dt, 0.0)
	var s: float = trauma * trauma * intensity
	var t: float = time * frequency
	offset_x = max_offset * s * noise(noise_seed, t, 0)
	offset_y = max_offset * s * noise(noise_seed, t, 1)
	angle = max_angle * s * noise(noise_seed, t, 2)


func offset() -> Vector2:
	return Vector2(offset_x, offset_y)

# {{FOOTER}}
