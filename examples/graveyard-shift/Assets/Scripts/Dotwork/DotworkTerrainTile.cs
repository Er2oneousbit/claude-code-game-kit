// ---------------------------------------------------------------------------
// DotworkTerrainTile.cs
// Purpose : A terrain of a Dotwork tileset (grass, path, water, a platform, a corners4 pond) as one paintable
//           tile for the Tile Palette: each cell it is painted on shows the atlas tile whose key matches its
//           neighbours (Core/Autotile.CellMask, the manifest's blob47, sides4 or corners4 rule), the variant
//           picked by the cell's roll (Autotile.CellRoll with this tile's layerIndex) among the tiles sharing
//           that key, by probability, as the spec's loaded result names it.
// Usage   : tilemap.SetTile(cell, terrainTile);  terrainTile.Resolve(tilemap.GetTile, cell, out key)
// Notes   : The importer resolves a map's terrain layers into plain DotworkTiles at import (the Tilemap then holds
//           the spec's tiles themselves); this tile is for painting by hand, and resolves the same way. Unity
//           cells are y UP: on a square map a map row y sits at cell y = -1 - y (the importer's layout, top-left
//           corner at the origin), on an isometric map cell (u, v) = (-1 - y, -1 - x) (DotworkImporter.Cell), so
//           `shape` says how a neighbour offset maps to a cell offset. A neighbour counts when it holds this same
//           tile asset on the same tilemap (each terrain layer is painted on its own, as the spec says).
//           Changing a cell refreshes its 8 neighbours.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): corners4, the isometric cell mapping and the
//           probability pick of asset manifest 1.1.0 (#285); the map importer no longer paints with it
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Tilemaps;
using graveyard_shift.Core;

namespace graveyard_shift.Dotwork
{
    public sealed class DotworkTerrainTile : TileBase
    {
        public string mode = Autotile.BLOB47;     // blob47, sides4 or corners4
        public string shape = Autotile.SQUARE;    // the tileset's shape: how cells map to map coordinates
        public int terrainSet, terrain;
        public string terrainName = "";
        public int layerIndex;                    // the roll's layer (the layer's index in a map's layers list)
        // Candidates in atlas order, flat (Unity serializes no nested lists): a key per entry, its tile, its weight
        public int[] keys = new int[0];
        public DotworkTile[] tiles = new DotworkTile[0];
        public double[] weights = new double[0];

        /// <summary>Map cell (x, y) (y down) of a Unity cell, for this tile's shape.</summary>
        public Vector2Int MapCell(Vector3Int cell)
        {
            return shape == Autotile.ISOMETRIC ? new Vector2Int(-1 - cell.y, -1 - cell.x) : new Vector2Int(cell.x, -1 - cell.y);
        }

        /// <summary>The Unity cell of a map cell (x, y), for this tile's shape (DotworkImporter.Cell's rule).</summary>
        public Vector3Int UnityCell(int x, int y, int z = 0)
        {
            return shape == Autotile.ISOMETRIC ? new Vector3Int(-1 - y, -1 - x, z) : new Vector3Int(x, -1 - y, z);
        }

        /// <summary>The key the cell needs, from whatever get(cell) returns for its neighbours (ITilemap.GetTile or
        /// Tilemap.GetTile).</summary>
        public int KeyAt(Func<Vector3Int, TileBase> get, Vector3Int cell)
        {
            Vector2Int m = MapCell(cell);
            return Autotile.CellMask((x, y) => get(UnityCell(x, y, cell.z)) == this, m.x, m.y, mode);
        }

        /// <summary>The tile for a key and a roll (the pick among the tiles sharing the key), or null when the
        /// tileset has none for it.</summary>
        public DotworkTile TileFor(int key, double roll = 0)
        {
            var cands = new List<int>();
            var w = new List<double>();
            for (int i = 0; i < keys.Length && i < tiles.Length; i++)
            {
                if (keys[i] == key)
                {
                    cands.Add(i);
                    w.Add(i < weights.Length ? weights[i] : 1);
                }
            }
            return cands.Count == 0 ? null : tiles[cands[Autotile.Pick(w, roll)]];
        }

        /// <summary>What a painted cell shows: its key and the picked tile (null when the tileset has none).</summary>
        public DotworkTile Resolve(Func<Vector3Int, TileBase> get, Vector3Int cell, out int key)
        {
            key = KeyAt(get, cell);
            Vector2Int m = MapCell(cell);
            return TileFor(key, Autotile.CellRoll(m.x, m.y, layerIndex));
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
            DotworkTile t = Resolve(tilemap.GetTile, position, out _);
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
            DotworkTile t = Resolve(tilemap.GetTile, position, out _);
            return t != null && t.GetTileAnimationData(position, tilemap, ref tileAnimationData);
        }
    }
}
