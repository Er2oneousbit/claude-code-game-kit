// ---------------------------------------------------------------------------
// DotworkTile.cs
// Purpose : One cell of a Dotwork tileset atlas as a Unity tile: its sprite, its animation frames (Dotwork's
//           water and the like), its collider, and the manifest data it came from (atlas, col, row, terrain and
//           mask, probability, surface). The Dotwork importer (Assets/Editor/Dotwork/) writes one per tile.
// Usage   : tilemap.SetTile(cell, tile);  tile.surface ("stone", "water") for footsteps and the like
// Notes   : Unity's plain Tile cannot animate, so this is a TileBase. Collision: the tile's sprite carries the
//           manifest's collision rects as its custom physics shape (set at import), and solid tiles report
//           ColliderType.Sprite, so a TilemapCollider2D on the tilemap uses exactly those rects. Animation speed
//           is frames per second at the tilemap's animationFrameRate of 1 (Unity's default). The transform is not
//           locked, so a map's flipped cells (Tilemap.SetTransformMatrix) keep their flip.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using UnityEngine;
using UnityEngine.Tilemaps;

namespace {{GAME_SLUG}}.Dotwork
{
    public sealed class DotworkTile : TileBase
    {
        public Sprite sprite;
        public Sprite[] frames = new Sprite[0];   // the animation, frames[0] == sprite; empty when still
        public float fps;
        public bool solid;                        // has collision rects (the sprite's physics shape)
        public Rect[] collision = new Rect[0];    // the manifest's rects, tile pixels, y down (for game code)

        // Where it came from in the manifest: [atlas, col, row], and its terrain data (-1 when none)
        public int atlas, col, row;
        public int terrainSet = -1, terrain = -1, mask = -1;
        public int[] corners = new int[0];        // corners4: terrain per corner, corner names sorted
        public float probability = 1f;
        public string surface = "";

        public bool Animated => frames != null && frames.Length > 1 && fps > 0f;

        public override void GetTileData(Vector3Int position, ITilemap tilemap, ref TileData tileData)
        {
            tileData.sprite = sprite;
            tileData.color = Color.white;
            tileData.transform = Matrix4x4.identity;
            tileData.flags = TileFlags.LockColor;
            tileData.colliderType = solid ? Tile.ColliderType.Sprite : Tile.ColliderType.None;
        }

        public override bool GetTileAnimationData(Vector3Int position, ITilemap tilemap, ref TileAnimationData tileAnimationData)
        {
            if (!Animated)
            {
                return false;
            }
            tileAnimationData.animatedSprites = frames;
            tileAnimationData.animationSpeed = fps;
            tileAnimationData.animationStartTime = 0f;
            return true;
        }
    }
}

// {{FOOTER}}
