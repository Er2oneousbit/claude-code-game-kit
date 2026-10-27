// ---------------------------------------------------------------------------
// LevelCheck.cs
// Purpose : The invariants every graveyard must satisfy, hand-made or generated (SOP-17 step 1), and the
//           walk grid that answers "can the keeper get there on foot". The generator rejects any layout
//           with a problem; the EditMode property tests run the same checks over hundreds of seeds.
// Usage   : List<string> problems = LevelCheck.Problems(level, tuning);   // empty = a fair yard
//           var grid = new WalkGrid(level);  grid.Reachable(point)
// Notes   : Each problem starts with its invariant's name ("reach: soul 3 ..."), so tests can count them.
//           The walk grid blocks every cell within KeeperRadius (the NavMesh agent's radius) plus BakeMargin of
//           a prop's footprint, so a gap the grid calls open is one the NavMesh bake keeps open too. The PlayMode
//           test Smoke_E checks that claim against the real NavMesh. Ties and sums stay exact on the 1/16 m
//           lattice (LevelGenerator), so a check gives the same answer on every runtime.
//
// Pseudocode:
//   grid  = cells of CellSize over the yard; blocked if within KeeperRadius + BakeMargin of a prop box
//   reach = flood fill from the keeper's start
//   check : twelve souls, inside the outline, clear of props, reachable, spread apart, near cover;
//           gate reachable; three ghost loops whose every waypoint a ghost can arrive at, none near the
//           start; no prop on top of another; every model has a measured footprint
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fixes (Claude Opus 5.5): "cover" is Footprint.IsCover, now only props that reach the
//           keeper's chest (low tombs, bevelled and broken stones and low rocks never hid anyone);
//           WalkGrid.ReachableAround for the generator's ghost corners.
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;

namespace graveyard_shift.Core
{
    public static class LevelCheck
    {
        // The invariants' numbers (meters). Changing one changes which yards are fair: rerun the property tests.
        public const int SoulCount = 12;
        public const int MinRoutes = 6, MaxRoutes = 12;   // ghost loops: about one per 550 square meters
        public const float SpotClearance = 0.6f;   // souls, the start and the gate approach stand this far from any prop
        public const float SoulSpacing = 10f;      // souls at least this far apart: the night is a tour, not a pile
        public const float SoulFromStart = 7f;     // no soul right at the gate (the hand-made yard's nearest is 7.8 m)
        public const float GeneratedFromStart = 15f;   // generated souls start farther out: a dark keeper pays for distance
        public const float CoverReach = 4f;        // cover (chest high, not a wall or a post) this close to every soul: dark sneaking works
        public const float GhostStartSafe = 8f;    // no ghost route point this close to the keeper's start (ghosts may start at any)
        public const float MinLoop = 24f;          // a patrol loop at least this long, so it is a patrol and not a post
        public const float WallMargin = 1f;        // souls, the start and the gate approach stand this far inside the wall
        public const float OverlapTolerance = 1f / 8f;    // the lattice snap grows each box up to 1/16 m per edge: two boxes, 1/8
        public static readonly V2 GateApproach = new V2(0f, 1.5f);   // the old level test's spot inside the gate

        public static List<string> Problems(Level l, GameTuning t)
        {
            var problems = new List<string>();
            var grid = new WalkGrid(l);
            var boxes = Boxes(l, false);
            var cover = Boxes(l, true);

            foreach (var p in l.Props)
                if (!Footprint.Known(p.Model)) problems.Add($"models: '{p.Model}' has no measured footprint");

            if (l.Souls.Count != SoulCount) problems.Add($"souls: {l.Souls.Count}, not {SoulCount}");
            if (!grid.Walkable(l.KeeperStart)) problems.Add($"reach: the keeper's start {l.KeeperStart} is blocked");

            // Souls, the start and the gate approach: inside the walls and clear of every prop
            var spots = new List<V2>(l.Souls) { l.KeeperStart, l.Gate + GateApproach };
            for (int i = 0; i < spots.Count; i++)
            {
                var p = spots[i];
                string name = i < l.Souls.Count ? $"soul {i}" : i == l.Souls.Count ? "start" : "gate";
                if (!l.Inside(p, WallMargin))
                    problems.Add($"inside: {name} {p} is outside the walls");
                float clear = Nearest(boxes, p);
                if (clear < SpotClearance) problems.Add($"clear: {name} {p} is {clear:0.00} m from a prop");
            }

            // Souls: reachable on foot, spread out, each with cover near it
            for (int i = 0; i < l.Souls.Count; i++)
            {
                var s = l.Souls[i];
                // The game's pickup rule, less a voxel
                if (!grid.ReachableNear(s, (float)(t.SoulPickupRadius - WalkGrid.BakeMargin)))
                    problems.Add($"reach: soul {i} {s} cannot be reached on foot");
                // Generated yards keep souls farther out than the hand-made one does
                float fromStart = l.HandMade ? SoulFromStart : GeneratedFromStart;
                if (V2.Distance(s, l.KeeperStart) < fromStart) problems.Add($"spread: soul {i} {s} is under {fromStart} m from the start");
                for (int j = i + 1; j < l.Souls.Count; j++)
                    if (V2.Distance(s, l.Souls[j]) < SoulSpacing) problems.Add($"spread: souls {i} and {j} are {V2.Distance(s, l.Souls[j]):0.0} m apart");
                if (Nearest(cover, s) > CoverReach) problems.Add($"cover: soul {i} {s} has no cover within {CoverReach} m");
            }
            if (!grid.ReachableNear(l.Gate, (float)(t.GateRadius - WalkGrid.BakeMargin))) problems.Add("reach: the gate cannot be reached on foot");

            // Ghost routes: closed loops a ghost can walk, none starting on top of the keeper
            if (l.GhostRoutes.Count < MinRoutes || l.GhostRoutes.Count > MaxRoutes)
                problems.Add($"routes: {l.GhostRoutes.Count}, not {MinRoutes} to {MaxRoutes}");
            for (int r = 0; r < l.GhostRoutes.Count; r++)
            {
                var route = l.GhostRoutes[r];
                if (route.Count < 3)
                {
                    problems.Add($"routes: route {r} has {route.Count} points, not a loop");
                    continue;
                }
                float loop = 0f;
                for (int i = 0; i < route.Count; i++)
                {
                    var p = route[i];
                    loop = (float)(loop + V2.Distance(p, route[(i + 1) % route.Count]));
                    // A ghost moves on to the next point only within GhostBrain.Arrive of this one: it must get there
                    if (!grid.ReachableNear(p, GhostBrain.Arrive - 0.05f)) problems.Add($"routes: route {r} point {p} cannot be reached");
                    if (V2.Distance(p, l.KeeperStart) < GhostStartSafe) problems.Add($"routes: route {r} point {p} is next to the start");
                }
                if (loop < MinLoop) problems.Add($"routes: route {r} loop is {loop:0.0} m, under {MinLoop}");
            }

            // No prop on top of another (the shared walls and posts only checked against the rest)
            for (int i = l.FixedProps; i < boxes.Count; i++)
            {
                for (int j = 0; j < i; j++)
                {
                    if (boxes[i].Overlaps(boxes[j], -OverlapTolerance))
                        problems.Add($"overlap: {l.Props[i].Model} {l.Props[i].Position} overlaps {l.Props[j].Model} {l.Props[j].Position}");
                }
            }
            return problems;
        }

        // Distance from a point to the nearest prop footprint
        public static float Clearance(Level l, V2 p) => Nearest(Boxes(l, false), p);

        // Distance from a point to the nearest prop that hides you (not a wall or a post)
        public static float CoverDistance(Level l, V2 p) => Nearest(Boxes(l, true), p);

        // Every prop's footprint (coverOnly: only the ones that hide you), worked out once per check: a yard has
        // hundreds of props and the generator asks about thousands of spots
        public static List<Box> Boxes(Level l, bool coverOnly)
        {
            var boxes = new List<Box>(l.Props.Count);
            foreach (var prop in l.Props)
                if (!coverOnly || Footprint.IsCover(prop.Model)) boxes.Add(Footprint.Of(prop));
            return boxes;
        }

        public static float Nearest(List<Box> boxes, V2 p)
        {
            float best = float.MaxValue;
            foreach (var b in boxes) best = Math.Min(best, b.Distance(p));
            return best;
        }
    }

    // Where the keeper can walk: a grid over the yard, flood-filled from the start
    public sealed class WalkGrid
    {
        public const float CellSize = 0.125f;   // fine enough that rounding stays under a ghost's arrive margin
        public const float KeeperRadius = 0.5f;     // the NavMesh agent radius (AI Navigation's Humanoid default)
        public const float BakeMargin = 0.125f;     // the bake works in voxels of radius/3 (0.17 m): a gap only a
                                                    // hair wider than the agent closes, so ask for this much more
        private const float Blocked = KeeperRadius + BakeMargin;
        private readonly float MinX, MinZ;          // the yard's bounds: the grid covers them

        private readonly int _nx, _nz;
        private readonly bool[] _blocked;
        private readonly bool[] _reach;

        public WalkGrid(Level l)
        {
            var b = l.Bounds;
            MinX = b.MinX;
            MinZ = b.MinZ;
            _nx = (int)((b.MaxX - b.MinX) / CellSize);
            _nz = (int)((b.MaxZ - b.MinZ) / CellSize);
            _blocked = new bool[_nx * _nz];
            _reach = new bool[_nx * _nz];
            // Outside the outline is not yard, whatever the walls do
            for (int z = 0; z < _nz; z++)
            for (int x = 0; x < _nx; x++)
                if (!l.Inside(Center(x, z))) _blocked[z * _nx + x] = true;
            foreach (var p in l.Props) Block(Footprint.Of(p));
            Flood(l.KeeperStart);
        }

        public bool Walkable(V2 p) => Cell(p, out int i) && !_blocked[i];

        public bool Reachable(V2 p) => Cell(p, out int i) && _reach[i];

        // Is any reachable cell within radius of p?
        public bool ReachableNear(V2 p, float radius)
        {
            int r = (int)Math.Ceiling(radius / CellSize);
            int cx = (int)Math.Floor((p.X - MinX) / CellSize), cz = (int)Math.Floor((p.Z - MinZ) / CellSize);
            for (int z = cz - r; z <= cz + r; z++)
            for (int x = cx - r; x <= cx + r; x++)
            {
                if (x < 0 || z < 0 || x >= _nx || z >= _nz || !_reach[z * _nx + x]) continue;
                if (V2.Distance(Center(x, z), p) <= radius) return true;
            }
            return false;
        }

        // The reachable cell center nearest to p within radius, ties broken by scan order: exact, so every
        // runtime picks the same cell (the generator snaps ghost loop corners with it). open > 0: only cells with
        // open ground that far all round (ReachableAround)
        public bool NearestReachable(V2 p, float radius, out V2 found, float open = 0f)
        {
            found = p;
            int r = (int)Math.Ceiling(radius / CellSize);
            int cx = (int)Math.Floor((p.X - MinX) / CellSize), cz = (int)Math.Floor((p.Z - MinZ) / CellSize);
            float best = radius * radius;
            bool any = false;
            for (int z = cz - r; z <= cz + r; z++)
            for (int x = cx - r; x <= cx + r; x++)
            {
                if (x < 0 || z < 0 || x >= _nx || z >= _nz || !_reach[z * _nx + x]) continue;
                V2 d = Center(x, z) - p;
                float d2 = d.X * d.X + d.Z * d.Z;
                if (d2 > best || (any && d2 == best)) continue;
                if (open > 0f && !ReachableAround(Center(x, z), open)) continue;
                best = d2;
                found = Center(x, z);
                any = true;
            }
            return any;
        }

        // Is every cell whose center is within radius of p reachable? Open ground all round, not a sliver between props
        // (the NavMesh bake erodes those away; the generator puts ghost corners only where this holds)
        public bool ReachableAround(V2 p, float radius)
        {
            int r = (int)Math.Ceiling(radius / CellSize);
            int cx = (int)Math.Floor((p.X - MinX) / CellSize), cz = (int)Math.Floor((p.Z - MinZ) / CellSize);
            for (int z = cz - r; z <= cz + r; z++)
            for (int x = cx - r; x <= cx + r; x++)
            {
                if (V2.Distance(Center(x, z), p) > radius) continue;
                if (x < 0 || z < 0 || x >= _nx || z >= _nz || !_reach[z * _nx + x]) return false;
            }
            return true;
        }

        // Every reachable cell center (the generator picks soul spots from these)
        public IEnumerable<V2> ReachableCells(int step)
        {
            for (int z = 0; z < _nz; z += step)
            for (int x = 0; x < _nx; x += step)
                if (_reach[z * _nx + x]) yield return Center(x, z);
        }

        private V2 Center(int x, int z) => new V2(MinX + (x + 0.5f) * CellSize, MinZ + (z + 0.5f) * CellSize);

        private bool Cell(V2 p, out int index)
        {
            int x = (int)Math.Floor((p.X - MinX) / CellSize), z = (int)Math.Floor((p.Z - MinZ) / CellSize);
            index = z * _nx + x;
            return x >= 0 && z >= 0 && x < _nx && z < _nz;
        }

        // Block every cell whose center is within KeeperRadius + BakeMargin of the box
        private void Block(Box b)
        {
            int x0 = Math.Max(0, (int)Math.Floor((b.MinX - Blocked - MinX) / CellSize));
            int x1 = Math.Min(_nx - 1, (int)Math.Floor((b.MaxX + Blocked - MinX) / CellSize));
            int z0 = Math.Max(0, (int)Math.Floor((b.MinZ - Blocked - MinZ) / CellSize));
            int z1 = Math.Min(_nz - 1, (int)Math.Floor((b.MaxZ + Blocked - MinZ) / CellSize));
            for (int z = z0; z <= z1; z++)
            for (int x = x0; x <= x1; x++)
                if (b.Distance(Center(x, z)) <= Blocked) _blocked[z * _nx + x] = true;
        }

        // 4-neighbour flood fill from the start
        private void Flood(V2 start)
        {
            if (!Cell(start, out int s) || _blocked[s]) return;
            var queue = new Queue<int>();
            _reach[s] = true;
            queue.Enqueue(s);
            while (queue.Count > 0)
            {
                int i = queue.Dequeue();
                int x = i % _nx, z = i / _nx;
                if (x > 0) Visit(i - 1, queue);
                if (x < _nx - 1) Visit(i + 1, queue);
                if (z > 0) Visit(i - _nx, queue);
                if (z < _nz - 1) Visit(i + _nx, queue);
            }
        }

        private void Visit(int i, Queue<int> queue)
        {
            if (_blocked[i] || _reach[i]) return;
            _reach[i] = true;
            queue.Enqueue(i);
        }
    }
}
