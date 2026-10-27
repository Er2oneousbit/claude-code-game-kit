# ---------------------------------------------------------------------------
# tuning.gd
# Purpose : Every gameplay number in one place, so tuning never means hunting
#           for literals. Tests read these too (tests/test_level_reachable.gd).
# Usage   : Tuning.RUN_SPEED, Tuning.GRAVITY, ...
# Notes   : Units are world pixels and seconds. One tile is 18 px (Kenney Pixel
#           Platformer) and the camera zooms 2x, so the screen shows 320x180 of world.
#           Change a jump number and the reachability test tells you if a gap became impossible.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name Tuning
extends RefCounted

const TILE: int = 18                     # px per tile in tilemap_packed.png
const CAMERA_ZOOM: float = 2.0
const RUN_SPEED: float = 120.0           # px/s at full input
const ACCEL: float = 900.0               # px/s^2 toward target speed on the ground
const AIR_ACCEL: float = 600.0           # px/s^2 in the air (less control, still forgiving)
const GRAVITY: float = 900.0             # px/s^2
const MAX_FALL_SPEED: float = 420.0      # px/s
const JUMP_VELOCITY: float = 340.0       # px/s upward; apex about 67 px (3.7 tiles) at 60 ticks/s, see JumpMath
const JUMP_CUT: float = 0.45             # releasing jump early keeps this share of upward speed
const COYOTE_TIME: float = 0.10          # s of grace after walking off a ledge
const JUMP_BUFFER_TIME: float = 0.12     # s a jump press is remembered before landing
const PLAYER_SIZE: Vector2 = Vector2(12, 18)   # collision box; the fox (about 20x22 px) overhangs it a little
const FALL_LIMIT_Y: float = 260.0        # below this the player respawns (screen bottom is 180)
const SAFETY_MARGIN: float = 0.85        # reachability test: a jump may use at most 85% of the ideal arc
const MUSIC_DB: float = -3.0          # the created theme is about 5 dB quieter than the old track
const SFX_DB: float = -4.0
