// ---------------------------------------------------------------------------
// GhostPlan.cs
// Purpose : Where each ghost of a night starts and which way it walks: one ghost per patrol loop, then the
//           difficulty's extra ghosts on the longest loops, each on the corner opposite its loop's first ghost,
//           walking the other way round.
// Usage   : foreach (var s in GhostPlan.For(level, seed, extraGhosts)) ghost.Init(..., s.Route(level), ..., s.Start)
// Notes   : Engine-free, so a test checks every difficulty and seed without a scene. The seed picks each base ghost's
//           corner ((loop + seed) % corners, unchanged from before) and the direction of all of them (seed / 4).
//           Kimi audit (2026-10-23): extras used to start at index ghost + seed + 2 of their reversed loop, which put
//           one exactly on a base ghost's corner at Normal and up on the hand-made yard.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fix (Claude Opus 5.5): loops are ranked by an exact key (length in whole 1/16 m, then
//           index), not a float sum, so two loops of nearly equal length cannot swap places between runtimes.
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using System.Linq;

namespace graveyard_shift.Core
{
    public readonly struct GhostSpawn
    {
        public readonly int Loop;        // index into Level.GhostRoutes
        public readonly bool Reversed;   // walks the loop backwards
        public readonly int Start;       // starting corner, as an index into Route() (already reversed if Reversed)
        public readonly bool Extra;      // one of the difficulty's extra ghosts

        public GhostSpawn(int loop, bool reversed, int start, bool extra)
        {
            Loop = loop;
            Reversed = reversed;
            Start = start;
            Extra = extra;
        }

        public List<V2> Route(Level level)
        {
            var route = new List<V2>(level.GhostRoutes[Loop]);
            if (Reversed) route.Reverse();
            return route;
        }

        public V2 StartPoint(Level level) => Route(level)[Start];
    }

    public static class GhostPlan
    {
        public static List<GhostSpawn> For(Level level, int seed, int extraGhosts)
        {
            var plan = new List<GhostSpawn>();
            int loops = level.GhostRoutes.Count;
            bool reverseBase = (seed / 4) % 2 == 1;
            var corner = new int[loops];   // each base ghost's corner, as an index into the loop's own (unreversed) order
            for (int i = 0; i < loops; i++)
            {
                int n = level.GhostRoutes[i].Count;
                int start = (int)(((long)i + seed) % n);
                corner[i] = reverseBase ? n - 1 - start : start;
                plan.Add(new GhostSpawn(i, reverseBase, start, false));
            }
            // Longest loops first, ties by index: an integer key, so the order never depends on rounding or a sort's stability
            var longest = Enumerable.Range(0, loops).OrderByDescending(i => LengthKey(level.GhostRoutes[i])).ThenBy(i => i).ToList();
            for (int e = 0; e < extraGhosts && loops > 0; e++)
            {
                int loop = longest[e % loops];
                int n = level.GhostRoutes[loop].Count;
                int opposite = (corner[loop] + n / 2) % n;
                bool reversed = !reverseBase;
                plan.Add(new GhostSpawn(loop, reversed, reversed ? n - 1 - opposite : opposite, true));
            }
            return plan;
        }

        // The loop's length in whole lattice steps (1/16 m), summed in double: corners sit on the lattice, so this is the
        // same integer on every runtime unless a length lands within a hair of a step's midpoint
        public static long LengthKey(List<V2> route)
        {
            double length = 0.0;
            for (int i = 0; i < route.Count; i++)
            {
                double dx = (double)route[(i + 1) % route.Count].X - route[i].X, dz = (double)route[(i + 1) % route.Count].Z - route[i].Z;
                length += System.Math.Sqrt(dx * dx + dz * dz);
            }
            return (long)System.Math.Round(length * Footprint.Lattice);
        }

        public static float Length(List<V2> route)
        {
            float length = 0f;
            for (int i = 0; i < route.Count; i++) length += V2.Distance(route[i], route[(i + 1) % route.Count]);
            return length;
        }
    }
}
