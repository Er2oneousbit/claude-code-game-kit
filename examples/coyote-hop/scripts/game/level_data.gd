# ---------------------------------------------------------------------------
# level_data.gd
# Purpose : The level as data, in tiles: platforms, coins, decorations, spawn
#           and goal. main.gd builds nodes from it; tests check every gap is jumpable.
# Usage   : for rect in LevelData.platforms_px(): ...
# Notes   : Rect2i(x, y, width, height) in tiles, y grows downward, listed left to
#           right in the order the player visits them. Row 10 is the screen bottom.
#           Platforms 1 tile high are wooden bridges, taller ones grass and dirt.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name LevelData
extends RefCounted

const PLATFORMS: Array[Rect2i] = [
	Rect2i(0, 8, 12, 2),     # start
	Rect2i(15, 8, 6, 2),     # first gap, flat
	Rect2i(23, 6, 4, 1),     # bridge, two tiles up
	Rect2i(30, 5, 3, 1),     # higher bridge
	Rect2i(35, 7, 4, 1),     # drop down
	Rect2i(42, 6, 3, 1),     # one tile up across 3 tiles (54 px, tied widest with gaps 1 and 3)
	Rect2i(47, 8, 14, 2),    # finish
]
# Coins trace the arc of a full jump taken at each ledge (placed from the autoplay bot's path)
const COINS: Array[Vector2i] = [
	Vector2i(13, 3), Vector2i(14, 3), Vector2i(15, 3), Vector2i(22, 3), Vector2i(23, 3),
	Vector2i(29, 1), Vector2i(30, 1), Vector2i(34, 1), Vector2i(36, 1), Vector2i(41, 2), Vector2i(47, 1),
]
# Decorations stand on top of a platform tile: [tile column, tile index in tilemap_packed.png]
const DECOR: Array[Vector2i] = [
	Vector2i(3, 85), Vector2i(7, 124), Vector2i(10, 126), Vector2i(17, 128), Vector2i(19, 125),
	Vector2i(49, 127), Vector2i(52, 124), Vector2i(55, 126),
]
const SPAWN_TILE: Vector2i = Vector2i(1, 7)
const GOAL_TILE: Vector2i = Vector2i(58, 6)   # flag tile; the pole tile sits below it


static func tile_rect(r: Rect2i) -> Rect2:
	return Rect2(Rect2i(r.position * Tuning.TILE, r.size * Tuning.TILE))


static func platforms_px() -> Array[Rect2]:
	var out: Array[Rect2] = []
	for r: Rect2i in PLATFORMS:
		out.append(tile_rect(r))
	return out


static func spawn_px() -> Vector2:
	# Feet on the floor of the spawn tile
	return Vector2(SPAWN_TILE.x * Tuning.TILE + Tuning.TILE / 2.0, (SPAWN_TILE.y + 1) * Tuning.TILE - Tuning.PLAYER_SIZE.y / 2.0)


static func goal_px() -> Rect2:
	# Flag plus pole: one tile wide, two tiles tall
	return Rect2(Vector2(GOAL_TILE * Tuning.TILE), Vector2(Tuning.TILE, Tuning.TILE * 2))


static func level_width_px() -> int:
	var right: int = 0
	for r: Rect2i in PLATFORMS:
		right = maxi(right, r.end.x)
	return right * Tuning.TILE
