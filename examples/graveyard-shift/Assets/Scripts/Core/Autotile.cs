// ---------------------------------------------------------------------------
// Autotile.cs
// Purpose : The terrain rule of Dotwork's asset manifest (core/tools/art/dotwork/ASSET_MANIFEST.md "Autotiling and
//           maps"), ported from assetspec.cell_mask: which of a cell's 8 neighbours hold the same terrain, as the
//           8-bit mask a tile carries. The Dotwork importer's terrain tiles (Assets/Scripts/Dotwork/) and its tests
//           use it; a game can call it for its own autotiling too.
// Usage   : int m = Autotile.CellMask((x, y) => painted.Contains((x, y)), cx, cy, "blob47");
//           Autotile.Canon(raw) folds a raw mask to one of the 47 blob masks.
// Notes   : Map coordinates, y DOWN (row 0 at the top), the manifest's own space: N is (0, -1). The bits are
//           N=1, NE=2, E=4, SE=8, S=16, SW=32, W=64, NW=128. blob47 keeps a corner bit only when both sides next to
//           it are set; sides4 keeps N, E, S, W only. Any other mode (corners4) folds like blob47, as the reference
//           loader does. No UnityEngine types (EditMode tests run it instantly).
//
// Pseudocode:
//   raw = sum of 1 << b for every neighbour b (N, NE, E, SE, S, SW, W, NW) that is painted
//   sides4: raw & (N | E | S | W)      otherwise: for each corner, clear it unless both of its sides are set
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;

namespace graveyard_shift.Core
{
    public static class Autotile
    {
        // ---- Tunables ------------------------------------------------------------
        public const int N = 1, NE = 2, E = 4, SE = 8, S = 16, SW = 32, W = 64, NW = 128;
        public const int SIDES_ONLY = N | E | S | W;
        public const string BLOB47 = "blob47", SIDES4 = "sides4", CORNERS4 = "corners4";

        // Neighbour offsets in bit order (N NE E SE S SW W NW), y down
        public static readonly int[] DX = { 0, 1, 1, 1, 0, -1, -1, -1 };
        public static readonly int[] DY = { -1, -1, 0, 1, 1, 1, 0, -1 };

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

        /// <summary>The mask the painted cell (x, y) needs. painted(x, y) says whether a cell holds this terrain.</summary>
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
            return mode == SIDES4 ? m & SIDES_ONLY : Canon(m);
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
