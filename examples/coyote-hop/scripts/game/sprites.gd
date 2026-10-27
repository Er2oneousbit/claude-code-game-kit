# ---------------------------------------------------------------------------
# sprites.gd
# Purpose : Cuts sprites out of the Kenney Pixel Platformer sheets (A-0001 in
#           docs/ASSET_LOG.md), so the rest of the code asks for "tile 151"
#           instead of doing atlas math, and loads the player's frame files (A-0006).
# Usage   : Sprites.tile(151) -> Sprite2D; Sprites.frames(Sprites.TILES, [151, 152], 4.0) -> SpriteFrames
#           Sprites.animations("res://assets/art/sunny_land_fox/", {"run": [6, 12.0]}) -> SpriteFrames
# Notes   : The *_packed sheets have no spacing between tiles. Indices count
#           left to right, top to bottom, 20 per row.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name Sprites
extends RefCounted

const TILES: Texture2D = preload("res://assets/art/pixel_platformer/tilemap_packed.png")
const BACKGROUNDS: Texture2D = preload("res://assets/art/pixel_platformer/tilemap-backgrounds_packed.png")
const TILE_COLS: int = 20
const TILE_SIZE: int = 18


static func region(index: int) -> Rect2:
	return Rect2((index % TILE_COLS) * TILE_SIZE, int(index / float(TILE_COLS)) * TILE_SIZE, TILE_SIZE, TILE_SIZE)


# A static tile sprite, top-left anchored like a grid cell.
static func tile(index: int) -> Sprite2D:
	var s := Sprite2D.new()
	s.texture = TILES
	s.region_enabled = true
	s.region_rect = region(index)
	s.centered = false
	return s


# Animation frames from a sheet, looping, one animation called "default".
static func frames(sheet: Texture2D, indices: Array[int], fps: float) -> SpriteFrames:
	var sf := SpriteFrames.new()
	sf.set_animation_speed("default", fps)
	sf.set_animation_loop("default", true)
	for i: int in indices:
		var at := AtlasTexture.new()
		at.atlas = sheet
		at.region = region(i)
		sf.add_frame("default", at)
	return sf


# Named animations from one PNG per frame: <base><name>/player-<name>-<n>.png, n from 1.
# anims maps name -> [frame count, fps]; fps 0 means "no playback, the code picks the frame".
static func animations(base: String, anims: Dictionary) -> SpriteFrames:
	var sf := SpriteFrames.new()
	sf.remove_animation("default")
	for anim_name: String in anims:
		var spec: Array = anims[anim_name]
		sf.add_animation(anim_name)
		sf.set_animation_speed(anim_name, maxf(spec[1], 1.0))
		sf.set_animation_loop(anim_name, true)
		for n: int in range(1, int(spec[0]) + 1):
			sf.add_frame(anim_name, load("%s%s/player-%s-%d.png" % [base, anim_name, anim_name, n]))
	return sf
