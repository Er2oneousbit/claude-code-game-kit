// ---------------------------------------------------------------------------
// Autotile.cs
// Purpose : The terrain rules of Dotwork's asset manifest (core/tools/art/dotwork/ASSET_MANIFEST.md "Autotiling and
//           maps"), ported from assetspec.py: a painted cell's key from its 8 neighbours (blob47, sides4, corners4),
//           a corners4 tile's key from its corner terrains, and the variant pick (hash32, cell_roll, pick). The
//           Dotwork importer (Assets/Editor/Dotwork/), its terrain tile (Assets/Scripts/Dotwork/) and the tests use
//           it; a game can call it for its own autotiling too.
// Usage   : int key = Autotile.CellMask((x, y) => painted.Contains((x, y)), cx, cy, Autotile.CORNERS4);
//           int tileKey = Autotile.CornerKey(cornersByName, terrainId, "isometric");   // -1 when names do not fit
//           double roll = Autotile.CellRoll(x, y, layerIndex);  int i = Autotile.Pick(weights, roll);
// Notes   : Map coordinates, y DOWN (row 0 at the top), the manifest's own space: N is (0, -1). The bits are
//           N=1, NE=2, E=4, SE=8, S=16, SW=32, W=64, NW=128. blob47 keeps a corner bit only when both sides next to
//           it are set; sides4 keeps N, E, S, W only; corners4 keeps the four corner bits of the folded mask (a
//           corner is the terrain only when all four cells meeting there are painted). Corner names map to bits by
//           shape: square top_left NW, top_right NE, bottom_right SE, bottom_left SW; isometric top NW, right NE,
//           bottom SE, left SW. hash32 is Bob Jenkins' 6-shift integer hash in uint arithmetic (unchecked: every
//           step wraps at 32 bits, as the spec's Python masks it). No UnityEngine types (EditMode tests run it
//           instantly).
//
// Pseudocode:
//   raw = sum of 1 << b for every neighbour b (N, NE, E, SE, S, SW, W, NW) that is painted
//   sides4: raw & (N | E | S | W)   blob47: canon(raw)   corners4: canon(raw) & (NE | SE | SW | NW)
//   roll(x, y, layer) = hash32(hash32((x & 0xFFFF) << 16 | (y & 0xFFFF)) + layer) / 2^32
//   pick: u = roll * sum(weights); walk the weights subtracting; the first that drives u below 0 (last otherwise)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): the corners4 mode, corner keys, hash32,
//           cell_roll and the pick of asset manifest 1.1.0 (#285)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;

namespace {{GAME_SLUG}}.Core
{
    public static class Autotile
    {
        // ---- Tunables ------------------------------------------------------------
        public const int N = 1, NE = 2, E = 4, SE = 8, S = 16, SW = 32, W = 64, NW = 128;
        public const int SIDES_ONLY = N | E | S | W;
        public const int CORNERS_ONLY = NE | SE | SW | NW;
        public const string BLOB47 = "blob47", SIDES4 = "sides4", CORNERS4 = "corners4";
        public const string SQUARE = "square", ISOMETRIC = "isometric";

        // Neighbour offsets in bit order (N NE E SE S SW W NW), y down
        public static readonly int[] DX = { 0, 1, 1, 1, 0, -1, -1, -1 };
        public static readonly int[] DY = { -1, -1, 0, 1, 1, 1, 0, -1 };

        // A corners4 tile's corner names per shape, each with the mask bit of the cell across that corner
        private static readonly (string name, int bit)[] SQUARE_CORNERS =
            { ("top_left", NW), ("top_right", NE), ("bottom_right", SE), ("bottom_left", SW) };
        private static readonly (string name, int bit)[] ISO_CORNERS =
            { ("top", NW), ("right", NE), ("bottom", SE), ("left", SW) };

        /// <summary>A corner bit only counts when both sides next to it are set: 256 raw masks fold into 47.</summary>
        public static int Canon(int m)
        {
            for (int c = 1; c < 8; c += 2)             // NE, SE, SW, NW
            {
                bool before = ((m >> ((c + 7) % 8)) & 1) != 0;
                bool after = ((m >> ((c + 1) % 8)) & 1) != 0;
                if (!(before && after))
                {
                    m &= ~(1 << c);
                }
            }
            return m;
        }

        /// <summary>The key the painted cell (x, y) needs. painted(x, y) says whether a cell holds this terrain.</summary>
        public static int CellMask(Func<int, int, bool> painted, int x, int y, string mode = BLOB47)
        {
            if (painted == null)
            {
                throw new ArgumentNullException(nameof(painted));
            }
            int m = 0;
            for (int b = 0; b < 8; b++)
            {
                if (painted(x + DX[b], y + DY[b]))
                {
                    m |= 1 << b;
                }
            }
            if (mode == SIDES4)
            {
                return m & SIDES_ONLY;
            }
            return mode == CORNERS4 ? Canon(m) & CORNERS_ONLY : Canon(m);
        }

        /// <summary>The corner names of a shape (square unless isometric), each with its mask bit, in the spec's order.</summary>
        public static IReadOnlyList<(string name, int bit)> CornerBits(string shape)
        {
            return shape == ISOMETRIC ? ISO_CORNERS : SQUARE_CORNERS;
        }

        /// <summary>A corners4 tile's key: the sum of the bits of the corners holding the tile's own terrain; -1 when
        /// the corner names are not the shape's four.</summary>
        public static int CornerKey(IReadOnlyDictionary<string, int> corners, int terrain, string shape)
        {
            IReadOnlyList<(string name, int bit)> names = CornerBits(shape);
            if (corners == null || corners.Count != names.Count)
            {
                return -1;
            }
            int key = 0;
            foreach ((string name, int bit) in names)
            {
                if (!corners.TryGetValue(name, out int t))
                {
                    return -1;
                }
                if (t == terrain)
                {
                    key |= bit;
                }
            }
            return key;
        }

        /// <summary>Bob Jenkins' 32-bit integer hash: six shifts, adds and xors, every step kept to 32 bits.</summary>
        public static uint Hash32(uint k)
        {
            unchecked
            {
                k = k + 0x7ED55D16u + (k << 12);
                k = k ^ 0xC761C23Cu ^ (k >> 19);
                k = k + 0x165667B1u + (k << 5);
                k = (k + 0xD3A2646Cu) ^ (k << 9);
                k = k + 0xFD7046C5u + (k << 3);
                k = k ^ 0xB55A4F09u ^ (k >> 16);
                return k;
            }
        }

        /// <summary>The roll in [0, 1) that picks a terrain cell's variant, from the cell and the index of its layer in
        /// the map's layers list (0-based, every layer counted). Coordinates wrap at 16 bits.</summary>
        public static double CellRoll(int x, int y, int layer)
        {
            unchecked
            {
                uint cell = ((uint)(x & 0xFFFF) << 16) | (uint)(y & 0xFFFF);
                return Hash32(Hash32(cell) + (uint)layer) / 4294967296.0;
            }
        }

        /// <summary>The index of the candidate a roll picks: walk the weights (in atlas order) subtracting from
        /// roll * total; the first candidate that drives it below 0, the last otherwise, the first when every
        /// weight is 0 or less.</summary>
        public static int Pick(IReadOnlyList<double> weights, double roll)
        {
            if (weights == null || weights.Count == 0)
            {
                throw new ArgumentException("no candidates", nameof(weights));
            }
            double total = 0;
            foreach (double w in weights)
            {
                total += w;
            }
            if (total <= 0)
            {
                return 0;
            }
            double u = roll * total;
            for (int i = 0; i < weights.Count; i++)
            {
                u -= weights[i];
                if (u < 0)
                {
                    return i;
                }
            }
            return weights.Count - 1;
        }

        /// <summary>The 47 blob masks, ascending (255 = surrounded on all sides).</summary>
        public static IReadOnlyList<int> BlobMasks()
        {
            var set = new SortedSet<int>();
            for (int m = 0; m < 256; m++)
            {
                set.Add(Canon(m));
            }
            return new List<int>(set);
        }
    }
}

// {{FOOTER}}
