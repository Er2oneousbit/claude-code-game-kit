// ---------------------------------------------------------------------------
// DotworkTerrainTile.cs
// Purpose : A terrain of a Dotwork tileset (grass, path, water, a platform) as one paintable tile: each cell it is
//           painted on shows the atlas tile whose mask matches its neighbours (Core/Autotile.CellMask, the
//           manifest's blob47 or sides4 rule). Paint it by hand in the Tile Palette or let the importer paint a
//           map's terrain layers with it: both resolve the same way.
// Usage   : tilemap.SetTile(cell, terrainTile);  terrainTile.MaskAt(tilemap.GetTile, cell)  (what a cell resolves to)
// Notes   : Unity cells are y UP: a map row y sits at cell y = -1 - y (the importer's layout, top-left corner at the
//           origin), so the manifest's north neighbour (0, -1) is cell (0, +1). A neighbour counts when it holds
//           this same tile asset on the same tilemap (each terrain layer is painted on its own, as the spec says).
//           Several tiles can share a mask (variants): the first in atlas order is used, as the manifest's loaded
//           result names it (Godot picks one at random by probability, so the shapes match, not always the variant).
//           Changing a cell refreshes its 8 neighbours.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using UnityEngine;
using UnityEngine.Tilemaps;
using graveyard_shift.Core;

namespace graveyard_shift.Dotwork
{
    public sealed class DotworkTerrainTile : TileBase
    {
        public string mode = Autotile.BLOB47;     // blob47 or sides4
        public int terrainSet, terrain;
        public string terrainName = "";
        public int[] masks = new int[0];          // parallel to tiles: the first tile per mask, atlas order
        public DotworkTile[] tiles = new DotworkTile[0];

        /// <summary>The mask the cell needs, from whatever get(cell) returns for its neighbours (ITilemap.GetTile or
        /// Tilemap.GetTile).</summary>
        public int MaskAt(Func<Vector3Int, TileBase> get, Vector3Int cell)
        {
            return Autotile.CellMask((dx, dy) => get(new Vector3Int(cell.x + dx, cell.y - dy, cell.z)) == this, 0, 0, mode);
        }

        /// <summary>The tile for a mask, or null when the tileset has none for it.</summary>
        public DotworkTile TileFor(int mask)
        {
            int i = Array.IndexOf(masks, mask);
            return i >= 0 && i < tiles.Length ? tiles[i] : null;
        }

        public override void RefreshTile(Vector3Int position, ITilemap tilemap)
        {
            for (int dy = -1; dy <= 1; dy++)
            {
                for (int dx = -1; dx <= 1; dx++)
                {
                    tilemap.RefreshTile(new Vector3Int(position.x + dx, position.y + dy, position.z));
                }
            }
        }

        public override void GetTileData(Vector3Int position, ITilemap tilemap, ref TileData tileData)
        {
            DotworkTile t = TileFor(MaskAt(tilemap.GetTile, position));
            if (t != null)
            {
                t.GetTileData(position, tilemap, ref tileData);
                return;
            }
            tileData.sprite = null;
            tileData.colliderType = Tile.ColliderType.None;
        }

        public override bool GetTileAnimationData(Vector3Int position, ITilemap tilemap, ref TileAnimationData tileAnimationData)
        {
            DotworkTile t = TileFor(MaskAt(tilemap.GetTile, position));
            return t != null && t.GetTileAnimationData(position, tilemap, ref tileAnimationData);
        }
    }
}
