// ---------------------------------------------------------------------------
// LevelGenerator.cs
// Purpose : A new graveyard every night: an outline (a main body plus wings), crypts, gravestone rows, trees,
//           twelve souls and a ghost loop for every 550 square meters, from one seed. Every layout must pass
//           LevelCheck or it is thrown away.
// Usage   : Level l = LevelGenerator.Generate(seed);        // seed 0 = the hand-made yard (Level.Graveyard)
//           int seed = LevelGenerator.SeedForNight(nightsPlayed);
// Notes   : Engine-free, so EditMode tests run hundreds of seeds (SOP-17). Same seed, same yard: all randomness
//           comes from SeededRandom, never UnityEngine.Random or System.Random. The big pieces go first (the
//           outline, the paths, crypts, then rows around them, then trees), like Spelunky's path and Gungeon's
//           pre-made rooms: fill in around what matters most. Numbers are in the constants block.
//           Every coordinate is a multiple of 1/16 m (Footprint.Lattice) and so is every constant that gets added
//           to one: float sums are then exact, and the editor (Mono) and a .NET 8 build make the same yard.
//
// Pseudocode:
//   seed 0 -> the hand-made yard
//   for attempt 1..MaxAttempts (each with its own rng from seed and attempt):
//       outline: a main body with the gate in its south wall, plus 1 to 3 wings (area within AreaMin..AreaMax)
//       skeleton: the central path and corridors that cross every row
//       crypts (buildings and tombs) and trees off the corridors, then gravestone rows that leave the paths open
//       walk grid from the keeper's start; pick twelve reachable soul spots with cover, spread apart
//       ghost loops: split the outline into cells, one loop in each of a random choice of them
//       LevelCheck.Problems empty -> return it
//   every attempt failed -> the hand-made yard, marked Fallback (a test fails if that ever happens)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review follow-up (Claude Opus 5.5): a ghost loop corner needs open ground all round it
//           (CornerOpen): a corner in a sliver between props had no NavMesh within the ghost's arrive radius.
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;

namespace graveyard_shift.Core
{
    public static class LevelGenerator
    {
        public const int MaxAttempts = 25;
        public const int MaxSeed = 99999;            // seeds from SeedForNight are 1..MaxSeed, short enough to type

        // The outline (meters, even numbers: the wall grid). The gate is always in the south wall at z = GateZ.
        private const float GateZ = -30f;
        private const int MainHalfWidthMin = 15, MainHalfWidthMax = 20;   // in wall tiles: 60 to 80 m wide
        private const int MainDepthMin = 22, MainDepthMax = 28;           // in wall tiles: 44 to 56 m deep
        private const int OutlineTries = 60;                               // outlines drawn until one has the right area
        private const int WingsMin = 1, WingsMax = 3;
        private const int WingLengthMin = 6, WingLengthMax = 14;          // tiles along the side it juts from
        private const int WingDepthMin = 5, WingDepthMax = 9;             // tiles out from that side
        private const float AreaMin = 4000f, AreaMax = 5200f;             // square meters: about four times the old yard
        private const float SquareMetersPerGhost = 550f;

        // The space kept open in front of the gate
        private const float StartZoneHalfX = 4.5f, StartZoneDepth = 7f;

        // Pieces and the gaps between them (meters)
        private const float CryptGap = 1.625f;       // around a crypt: room to walk round it
        private const float CryptWallGap = 1.625f;   // between a crypt and the wall: room to walk behind it
        private const float TreeWallGap = 0.25f;     // trees may stand against the wall (corner cover)
        private const float StoneGap = 0.875f;       // a gravestone and a crypt or tree
        private const float StoneWallGap = 1.625f;
        private const float TreeGap = 1.25f;
        private const float RowSpacingMin = 3.375f, RowSpacingMax = 5.625f;
        private const float StoneStepMin = 2.5f, StoneStepMax = 3.0f;
        private const float MissingStone = 0.12f;    // chance a stone in a row is gone
        private const float CenterPathMin = 2.25f, CenterPathMax = 3.375f;   // half width of the path up from the gate
        private const float SidePathHalf = 1.375f;   // half width of a gap in a row (the corridors and the extra gaps)
        private const int ExtraGapsMax = 2;
        private const int LargeCryptsMin = 2, LargeCryptsMax = 4, SmallCryptsMin = 3, SmallCryptsMax = 6;
        private const int TombsMin = 4, TombsMax = 8;
        private const int TreesMin = 10, TreesMax = 20;
        private const float WallTree = 0.5f;         // chance a tree goes against a wall (they hide the wall souls)
        private const float WallTreeReach = 3.5f;    // "against a wall": this close to one
        private const int TreeYawSteps = 24;         // trees turn in 15 degree steps
        private const float TreeYawStep = 15f;

        // The skeleton: corridors (half width CorridorHalf) cross every row, the inner pair always, the outer pair
        // when the yard is wide enough. Crypts and trees stay out of them.
        private const float InnerCorridorMin = 12f, InnerCorridorMax = 16f;
        private const float OuterCorridorMin = 26f, OuterCorridorMax = 30f;
        private const float CorridorHalf = 1.375f;

        // Ghost loops: the yard's bounds split into cells about this big; a loop is a rectangle inside a cell
        private const float LoopCell = 20f;
        private const float LoopMinSide = 10f;
        private const float LoopCellMargin = 1.5f;
        private const float SnapRadius = 1.5f;       // a loop corner moves at most this far to reach open ground
        private const float CornerSafeMargin = 0.5f; // a loop corner keeps LevelCheck.GhostStartSafe plus this from the start
        // A loop corner needs open ground this far all round it: Smoke_E found one in a sliver between three props that the
        // walk grid kept and the NavMesh bake closed, 0.85 m from any NavMesh (night 3, seed 55875, 2026-10-26)
        public const float CornerOpen = 0.25f;

        private const int Lattice = Footprint.Lattice;
        private const int PieceTries = 40;
        private const float Half = 0.5f;             // coin flips: stone facing, loop direction

        private static readonly string[] Stones = { "gravestone-round", "gravestone-cross", "gravestone-wide", "gravestone-bevel", "gravestone-broken" };
        private static readonly string[] Tombs = { "crypt", "crypt-a", "crypt-b" };
        // Not the low "rocks" (0.75 m): the NavMesh agent can step onto it, the keeper cannot, so bot paths ran into it
        private static readonly string[] Trees = { "pine", "pine", "pine-crooked", "rocks-tall" };

        // Night n's seed: night 0 is the hand-made yard, every later night a new one, the same for every player.
        // A hash into 1..MaxSeed, so two nights can share a seed (the first 250 do not; a repeat becomes likely after
        // a few hundred nights). Changing this changes every player's night order, so it stays as it is.
        public static int SeedForNight(int nightsPlayed)
        {
            if (nightsPlayed <= 0) return 0;
            uint h = (uint)SeededRandom.Combine(nightsPlayed, 0x5EED);
            return 1 + (int)(h % MaxSeed);
        }

        public static Level Generate(int seed) => Generate(seed, null);

        // tuning: the night's numbers (pickup and gate radius); null uses the defaults.
        // rejects (optional): why each thrown-away attempt failed, its first problem or "room: ..." (for tests and tuning)
        public static Level Generate(int seed, GameTuning tuning, List<string> rejects = null)
        {
            if (seed == 0) return Level.Graveyard();
            var t = tuning ?? new GameTuning();
            for (int attempt = 1; attempt <= MaxAttempts; attempt++)
            {
                var rng = new SeededRandom(SeededRandom.Combine(seed, attempt));
                string noRoom = null;
                Level l = TryLayout(rng, ref noRoom);
                if (l == null)
                {
                    rejects?.Add("room: " + noRoom);
                    continue;
                }
                var problems = LevelCheck.Problems(l, t);
                if (problems.Count > 0)
                {
                    rejects?.Add(problems[0]);
                    continue;
                }
                l.Seed = seed;
                l.Attempts = attempt;
                return l;
            }
            var fallback = Level.Graveyard();
            fallback.Seed = seed;
            fallback.Attempts = MaxAttempts;
            fallback.Fallback = true;
            return fallback;
        }

        // One layout, or null when a piece found no room (noRoom says which)
        private static Level TryLayout(SeededRandom rng, ref string noRoom)
        {
            // 1. The outline: a main body, then wings jutting out of its west, east or north side, redrawn until the
            //    area is right (cheap: no props yet)
            Level l = null;
            float size = 0f;
            for (int i = 0; i < OutlineTries && l == null; i++)
            {
                var main = MainBody(rng);
                var areas = new List<Area> { main };
                int wings = rng.Range(WingsMin, WingsMax + 1);
                for (int w = 0; w < wings; w++) areas.Add(Wing(rng, main));
                var candidate = Level.Walled(areas);
                size = candidate.AreaSize;
                if (size >= AreaMin && size <= AreaMax) l = candidate;
            }
            if (l == null)
            {
                noRoom = "outline";
                return null;
            }
            var bounds = l.Bounds;

            // 2. The skeleton: the path up from the gate and the corridors
            float center = rng.Step(CenterPathMin, CenterPathMax, Lattice);
            var corridors = new List<float>();
            float inner = rng.Step(InnerCorridorMin, InnerCorridorMax, Lattice), outer = rng.Step(OuterCorridorMin, OuterCorridorMax, Lattice);
            corridors.Add(-inner);
            corridors.Add(inner);
            if (bounds.MinX < -outer - 4f) corridors.Add(-outer);
            if (bounds.MaxX > outer + 4f) corridors.Add(outer);
            var boxes = new List<Box>();     // crypts and trees placed so far

            // 3. Crypts: buildings (they get roofs and doors) and tombs, the big pieces that break sight lines (the low
            //    tombs, crypt-a and crypt-b, only block walking: Footprint.IsCover)
            var crypts = new List<string>();
            int large = rng.Range(LargeCryptsMin, LargeCryptsMax + 1), small = rng.Range(SmallCryptsMin, SmallCryptsMax + 1);
            int tombs = rng.Range(TombsMin, TombsMax + 1);
            for (int i = 0; i < large; i++) crypts.Add("crypt-large");
            for (int i = 0; i < small; i++) crypts.Add("crypt-small");
            for (int i = 0; i < tombs; i++) crypts.Add(rng.Pick(Tombs));
            foreach (var model in crypts)
            {
                float yaw = rng.Range(0, 4) * 90f;
                if (!Place(l, boxes, corridors, rng, model, yaw, CryptWallGap, CryptGap, bounds, false))
                {
                    noRoom = model;
                    return null;
                }
            }

            // 4. Trees and rocks: half against a wall (cover for the souls out there), the rest anywhere there is room
            int trees = rng.Range(TreesMin, TreesMax + 1);
            for (int i = 0; i < trees; i++)
            {
                string model = rng.Pick(Trees);
                float yaw = rng.Range(0, TreeYawSteps) * TreeYawStep;
                // No room for this one: skip it (souls still need cover nearby, which LevelCheck checks)
                Place(l, boxes, corridors, rng, model, yaw, TreeWallGap, TreeGap, bounds, rng.Chance(WallTree));
            }

            // 5. Gravestone rows, south to north, leaving the central path, the corridors and a gap or two open
            float z = GateZ + StartZoneDepth + rng.Step(0f, 1.5f, Lattice);
            int stone = rng.Range(0, Stones.Length);
            while (z <= bounds.MaxZ - StoneWallGap)
            {
                int extra = rng.Range(0, ExtraGapsMax + 1);
                var gaps = new List<float>(corridors);
                for (int i = 0; i < extra; i++) gaps.Add(rng.Step(bounds.MinX + 4f, bounds.MaxX - 4f, Lattice));
                float step = rng.Step(StoneStepMin, StoneStepMax, Lattice);
                for (float x = bounds.MinX + StoneWallGap + rng.Step(0f, step, Lattice); x <= bounds.MaxX - StoneWallGap; x += step)
                {
                    if (Math.Abs(x) < center || rng.Chance(MissingStone)) continue;
                    bool onPath = false;
                    foreach (float g in gaps) if (Math.Abs(x - g) < SidePathHalf) onPath = true;
                    if (onPath) continue;
                    var prop = new Prop { Model = Stones[stone % Stones.Length], Position = new V2(x, z), Yaw = rng.Chance(Half) ? 0f : 180f };
                    var b = Footprint.Of(prop);
                    if (!BoxInside(l, b, StoneWallGap) || InStartZone(b) || Near(b, boxes, StoneGap)) continue;
                    l.Props.Add(prop);
                    stone++;
                }
                z += rng.Step(RowSpacingMin, RowSpacingMax, Lattice);
            }

            // 6. Souls: reachable, clear, near cover, spread apart (greedy over a shuffled list of good spots)
            var grid = new WalkGrid(l);
            var allBoxes = LevelCheck.Boxes(l, false);
            var coverBoxes = LevelCheck.Boxes(l, true);
            var spots = new List<V2>();
            foreach (var p in grid.ReachableCells(4))   // every 0.5 m
            {
                if (!l.Inside(p, LevelCheck.WallMargin + 0.375f)) continue;
                if (V2.Distance(p, l.KeeperStart) < LevelCheck.GeneratedFromStart) continue;
                if (LevelCheck.Nearest(allBoxes, p) < LevelCheck.SpotClearance + 0.125f) continue;
                if (LevelCheck.Nearest(coverBoxes, p) > LevelCheck.CoverReach - 1f) continue;
                spots.Add(p);
            }
            Shuffle(spots, rng);
            foreach (var p in spots)
            {
                bool far = true;
                foreach (var s in l.Souls) if (V2.Distance(p, s) < LevelCheck.SoulSpacing) far = false;
                if (far) l.Souls.Add(p);
                if (l.Souls.Count == LevelCheck.SoulCount) break;
            }
            if (l.Souls.Count < LevelCheck.SoulCount)
            {
                noRoom = $"souls ({l.Souls.Count} spots)";
                return null;
            }

            // 7. Ghost loops: the bounds split into cells, a loop in each of a random choice of usable cells
            int want = Math.Max(LevelCheck.MinRoutes, Math.Min(LevelCheck.MaxRoutes, (int)Math.Round(size / SquareMetersPerGhost)));
            var cells = Cells(bounds);
            Shuffle(cells, rng);
            foreach (var cell in cells)
            {
                if (l.GhostRoutes.Count == want) break;
                List<V2> route = null;
                for (int i = 0; i < PieceTries && route == null; i++) route = Loop(rng, grid, l, cell);
                if (route != null) l.GhostRoutes.Add(route);
            }
            if (l.GhostRoutes.Count < want)
            {
                noRoom = $"ghost loops ({l.GhostRoutes.Count} of {want})";
                return null;
            }
            return l;
        }

        // The main body: centered on x = 0, its south wall at GateZ
        private static Area MainBody(SeededRandom rng)
        {
            float half = Level.Tile * rng.Range(MainHalfWidthMin, MainHalfWidthMax + 1);
            float depth = Level.Tile * rng.Range(MainDepthMin, MainDepthMax + 1);
            return new Area(-half, half, GateZ, GateZ + depth);
        }

        // A wing on the main body's west, east or north side, somewhere along it
        private static Area Wing(SeededRandom rng, Area main)
        {
            float length = Level.Tile * rng.Range(WingLengthMin, WingLengthMax + 1);
            float depth = Level.Tile * rng.Range(WingDepthMin, WingDepthMax + 1);
            int side = rng.Range(0, 3);
            if (side == 2)
            {
                // north: anywhere along the north wall
                int slots = Math.Max(1, (int)((main.MaxX - main.MinX - length) / Level.Tile) + 1);
                float x0 = main.MinX + Level.Tile * rng.Range(0, slots);
                return new Area(x0, x0 + length, main.MaxZ, main.MaxZ + depth);
            }
            // west or east: along the side, never level with the gate's wall
            int zSlots = Math.Max(1, (int)((main.MaxZ - main.MinZ - Level.Tile * 2f - length) / Level.Tile) + 1);
            float z0 = main.MinZ + Level.Tile * 2f + Level.Tile * rng.Range(0, zSlots);
            return side == 0 ? new Area(main.MinX - depth, main.MinX, z0, z0 + length)
                             : new Area(main.MaxX, main.MaxX + depth, z0, z0 + length);
        }

        // Cells about LoopCell big over the bounds (the loops' homes). Widths in whole lattice steps, so every
        // edge is exact: `MinX + i * (width / n)` rounded differently in Unity's Mono and .NET 8 and moved a loop
        private static List<Area> Cells(Area b)
        {
            var cells = new List<Area>();
            int nx = Math.Max(1, (int)Math.Round((b.MaxX - b.MinX) / LoopCell));
            int nz = Math.Max(1, (int)Math.Round((b.MaxZ - b.MinZ) / LoopCell));
            int w = (int)((b.MaxX - b.MinX) * Lattice) / nx, d = (int)((b.MaxZ - b.MinZ) * Lattice) / nz;   // lattice steps
            for (int i = 0; i < nx; i++)
            for (int j = 0; j < nz; j++)
                cells.Add(new Area(b.MinX + i * w / (float)Lattice, b.MinX + (i + 1) * w / (float)Lattice,
                                   b.MinZ + j * d / (float)Lattice, b.MinZ + (j + 1) * d / (float)Lattice));
            return cells;
        }

        // A rectangle loop inside the cell, its corners snapped to reachable ground, or null
        private static List<V2> Loop(SeededRandom rng, WalkGrid grid, Level l, Area cell)
        {
            float minX = cell.MinX + LoopCellMargin, maxX = cell.MaxX - LoopCellMargin;
            float minZ = cell.MinZ + LoopCellMargin, maxZ = cell.MaxZ - LoopCellMargin;
            if (maxX - minX < LoopMinSide || maxZ - minZ < LoopMinSide) return null;
            float x0 = rng.Step(minX, maxX - LoopMinSide, Lattice);
            float x1 = rng.Step(x0 + LoopMinSide, maxX, Lattice);
            float z0 = rng.Step(minZ, maxZ - LoopMinSide, Lattice);
            float z1 = rng.Step(z0 + LoopMinSide, maxZ, Lattice);
            var corners = new[] { new V2(x0, z0), new V2(x1, z0), new V2(x1, z1), new V2(x0, z1) };
            var route = new List<V2>();
            foreach (var c in corners)
            {
                if (!grid.NearestReachable(c, SnapRadius, out V2 p, CornerOpen) ||
                    V2.Distance(p, l.KeeperStart) < LevelCheck.GhostStartSafe + CornerSafeMargin) return null;
                route.Add(p);
            }
            if (rng.Chance(Half)) route.Reverse();
            return route;
        }

        // Try PieceTries spots in the bounds; add the prop where it is inside the outline by wallGap, keeps `gap`
        // from every placed box, stays off the corridors and the start, and (byWall) stands close to a wall
        private static bool Place(Level l, List<Box> boxes, List<float> corridors, SeededRandom rng, string model, float yaw,
                                  float wallGap, float gap, Area bounds, bool byWall)
        {
            for (int i = 0; i < PieceTries; i++)
            {
                var pos = new V2(rng.Step(bounds.MinX, bounds.MaxX, Lattice), rng.Step(bounds.MinZ, bounds.MaxZ, Lattice));
                var prop = new Prop { Model = model, Position = pos, Yaw = yaw };
                var b = Footprint.Of(prop);
                if (!BoxInside(l, b, wallGap) || InStartZone(b) || Near(b, boxes, gap) || InCorridor(b, corridors)) continue;
                if (byWall && l.EdgeDistance(pos, WallTreeReach) >= WallTreeReach) continue;
                if (StoneNear(l, b, StoneGap)) continue;
                l.Props.Add(prop);
                boxes.Add(b);
                return true;
            }
            return false;
        }

        // The box's corners and edge middles are all inside the outline, by margin
        private static bool BoxInside(Level l, Box b, float margin)
        {
            float mx = (b.MinX + b.MaxX) * 0.5f, mz = (b.MinZ + b.MaxZ) * 0.5f;
            return l.Inside(new V2(b.MinX, b.MinZ), margin) && l.Inside(new V2(b.MaxX, b.MinZ), margin) &&
                   l.Inside(new V2(b.MinX, b.MaxZ), margin) && l.Inside(new V2(b.MaxX, b.MaxZ), margin) &&
                   l.Inside(new V2(mx, b.MinZ), margin) && l.Inside(new V2(mx, b.MaxZ), margin) &&
                   l.Inside(new V2(b.MinX, mz), margin) && l.Inside(new V2(b.MaxX, mz), margin);
        }

        private static bool InCorridor(Box b, List<float> corridors)
        {
            foreach (float c in corridors) if (b.MaxX > c - CorridorHalf && b.MinX < c + CorridorHalf) return true;
            return false;
        }

        private static bool InStartZone(Box b) => b.MinX < StartZoneHalfX && b.MaxX > -StartZoneHalfX && b.MinZ < GateZ + StartZoneDepth;

        private static bool Near(Box b, List<Box> boxes, float gap)
        {
            foreach (var o in boxes) if (b.Overlaps(o, gap)) return true;
            return false;
        }

        private static bool StoneNear(Level l, Box b, float gap)
        {
            for (int i = l.FixedProps; i < l.Props.Count; i++)
                if (l.Props[i].Model.StartsWith("gravestone") && b.Overlaps(Footprint.Of(l.Props[i]), gap)) return true;
            return false;
        }

        private static void Shuffle<T>(List<T> items, SeededRandom rng)
        {
            for (int i = items.Count - 1; i > 0; i--)
            {
                int j = rng.Range(0, i + 1);
                (items[i], items[j]) = (items[j], items[i]);
            }
        }
    }
}
