// ---------------------------------------------------------------------------
// Level.cs
// Purpose : The graveyard as data: its outline (a main body plus wings), the stone wall around it, crypts,
//           gravestone rows, trees, the souls, the gate, the keeper's start and the ghost patrol routes. The
//           game builds the scene from this at runtime (LevelBuilder.cs); EditMode tests check it.
// Usage   : Level level = Level.Graveyard();  level.Props, level.Souls, level.GhostRoutes, level.Inside(p)
//           Generated nights: LevelGenerator.Generate(seed) (seed 0 is this hand-made yard).
// Notes   : Meters on the ground plane (Unity x, z), +z away from the camera. The outline is a union of
//           rectangles on a 2 m grid (Area), so a yard can be an L, a T or have wings jutting out; the wall is
//           one 2 m segment on every edge between inside and outside, centered on that edge, so corners close.
//           Model names are Kenney Graveyard Kit files (Assets/Art/Graveyard), drawn at WorldScale. Every prop
//           blocks movement and sight (the game gives it a box collider from its mesh).
//
// Pseudocode (Walled):
//   tiles = every 2 m square inside some area
//   for each tile, each side whose neighbour is outside: a wall segment centered on that side
//   leave GateWidth open in the main body's south wall, at x = 0; the gate itself is built by LevelBuilder
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fix (Claude Opus 5.5): Area.Contains is half-open (min edge in, max edge out), so a
//           seam between two areas belongs to one of them instead of to none.
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;

namespace graveyard_shift.Core
{
    public struct Prop
    {
        public string Model;
        public V2 Position;
        public float Yaw;       // degrees around +y
    }

    // One rectangle of the yard, edges on the 2 m wall grid (even meters)
    public struct Area
    {
        public float MinX, MaxX, MinZ, MaxZ;

        public Area(float minX, float maxX, float minZ, float maxZ)
        {
            MinX = minX;
            MaxX = maxX;
            MinZ = minZ;
            MaxZ = maxZ;
        }

        public float Size => (MaxX - MinX) * (MaxZ - MinZ);
        // Half-open, so areas that share an edge tile the plane: a point on the seam is in exactly one of them
        public bool Contains(V2 p) => p.X >= MinX && p.X < MaxX && p.Z >= MinZ && p.Z < MaxZ;
        public override string ToString() => $"[{MinX}..{MaxX}, {MinZ}..{MaxZ}]";
    }

    public sealed class Level
    {
        public const float WorldScale = 2f;    // the Kenney kit is mini scale: a 0.9 m keeper becomes 1.8 m
        public const float Tile = 2f;          // the wall grid: one stone-wall segment per tile edge
        public const float GateWidth = 4f;     // the opening in the south wall the gate closes
        private const float WallPivot = 0.8f;  // the stone-wall model's box sits this far behind its pivot

        public readonly List<Area> Areas = new List<Area>();   // Areas[0] is the main body (the gate is in its south wall)
        public readonly List<Prop> Props = new List<Prop>();
        public readonly List<V2> Souls = new List<V2>();
        public readonly List<List<V2>> GhostRoutes = new List<List<V2>>();
        public V2 Gate;
        public V2 KeeperStart;
        public int Seed;            // the night it was made for (0: this hand-made yard)
        public int FixedProps;      // Props[0..FixedProps) are the walls and gate posts
        public int Attempts;        // layouts the generator tried before this one passed (0: not generated)
        public bool Fallback;       // the generator gave up and fell back to the hand-made yard

        public bool HandMade => Attempts == 0 || Fallback;

        public bool Inside(V2 p)
        {
            foreach (var a in Areas) if (a.Contains(p)) return true;
            return false;
        }

        // Inside, and at least margin from every wall
        public bool Inside(V2 p, float margin) =>
            Inside(p) && Inside(new V2(p.X - margin, p.Z)) && Inside(new V2(p.X + margin, p.Z)) &&
            Inside(new V2(p.X, p.Z - margin)) && Inside(new V2(p.X, p.Z + margin)) &&
            Inside(new V2(p.X - margin, p.Z - margin)) && Inside(new V2(p.X + margin, p.Z + margin)) &&
            Inside(new V2(p.X - margin, p.Z + margin)) && Inside(new V2(p.X + margin, p.Z - margin));

        public float AreaSize
        {
            get
            {
                // Tiles counted once, so overlapping areas are not counted twice
                float n = 0f;
                var b = Bounds;
                for (float x = b.MinX + Tile * 0.5f; x < b.MaxX; x += Tile)
                for (float z = b.MinZ + Tile * 0.5f; z < b.MaxZ; z += Tile)
                    if (Inside(new V2(x, z))) n += Tile * Tile;
                return n;
            }
        }

        // The box around the whole outline
        public Area Bounds
        {
            get
            {
                var b = Areas[0];
                foreach (var a in Areas)
                {
                    b.MinX = Math.Min(b.MinX, a.MinX);
                    b.MaxX = Math.Max(b.MaxX, a.MaxX);
                    b.MinZ = Math.Min(b.MinZ, a.MinZ);
                    b.MaxZ = Math.Max(b.MaxZ, a.MaxZ);
                }
                return b;
            }
        }

        // Distance from an inside point to the nearest wall along x or z, up to limit (the bots avoid dead ends)
        public float EdgeDistance(V2 p, float limit)
        {
            const float step = 0.25f;
            for (float d = step; d <= limit; d += step)
            {
                if (!Inside(new V2(p.X + d, p.Z)) || !Inside(new V2(p.X - d, p.Z)) ||
                    !Inside(new V2(p.X, p.Z + d)) || !Inside(new V2(p.X, p.Z - d))) return d;
            }
            return limit;
        }

        // The hand-made yard: a main body with wings to the north-west, east and west (about 4,400 square meters)
        public static Level Graveyard()
        {
            var l = Walled(new[]
            {
                new Area(-32, 32, -30, 18),     // main body, the gate in its south wall
                new Area(-32, 6, 18, 34),       // north-west wing
                new Area(32, 46, -20, 10),      // east wing
                new Area(-46, -32, -10, 14),    // west wing
            });

            // Crypts with roofs and doors (LevelBuilder adds those) and low tombs: the big cover
            l.Add("crypt-large", 0f, 12f, 180);
            l.Add("crypt-large", -20f, 26f, 180);
            l.Add("crypt-large", 24f, -2f, 270);
            l.Add("crypt-small", -24f, -18f, 0);
            l.Add("crypt-small", 24f, -20f, 0);
            l.Add("crypt-small", -8f, -8f, 0);
            l.Add("crypt-small", 8f, 4f, 0);
            l.Add("crypt-small", 40f, -12f, 270);
            l.Add("crypt-small", -40f, 6f, 90);
            l.Add("crypt-small", -6f, 29f, 180);
            l.Add("crypt", -24f, 4f, 90);
            l.Add("crypt-a", 12f, 14f, 0);
            l.Add("crypt-b", -14f, 12f, 0);

            // Trees and rocks: corner and wing cover
            l.Add("pine", -29f, -27f, 0);
            l.Add("pine", 29f, -27f, 30);
            l.Add("pine", 43f, 7f, 0);
            l.Add("pine-crooked", -43f, -7f, 0);
            l.Add("pine", -29f, 31f, 0);
            l.Add("pine", 3f, 31f, 60);
            l.Add("pine", 29f, 15f, 0);
            l.Add("pine-crooked", -43f, 11f, 45);
            l.Add("rocks-tall", -12f, -20f, 0);
            l.Add("rocks-tall", 14f, -12f, 45);
            l.Add("rocks-tall", 38f, 2f, 0);

            // Gravestone rows: the central path (|x| < 3) and the corridors at x = +-16 stay open
            string[] stones = { "gravestone-round", "gravestone-cross", "gravestone-wide", "gravestone-bevel", "gravestone-broken" };
            int n = 0;
            int bigCover = l.Props.Count;
            foreach (float z in new[] { -22f, -14f, -6f, 2f, 8f, 22f, 28f })
            {
                for (float x = -44.2f; x <= 44.2f; x += 2.6f)
                {
                    float ax = Math.Abs(x);
                    if (ax < 3f || Math.Abs(ax - 16f) < 1.6f) continue;
                    var prop = new Prop { Model = stones[n % stones.Length], Position = new V2(x, z) };
                    var box = Footprint.Of(prop);
                    if (!l.Inside(prop.Position, 1.6f) || l.ClutterNear(box, bigCover, 1.2f)) continue;
                    if (ax < 6f && z < -20f) continue;                 // room in front of the gate
                    l.Props.Add(prop);
                    n++;
                }
            }

            // Twelve souls, each near cover, spread over the body and every wing
            l.Souls.AddRange(new[]
            {
                new V2(-27f, -23.5f), new V2(27f, -24f), new V2(43f, -16f), new V2(-43f, 2f),
                new V2(0f, 16.5f), new V2(-27f, 31f), new V2(0f, 31f), new V2(-20f, 21.5f),
                new V2(-8f, -12.5f), new V2(12f, 10.5f), new V2(28f, 4f), new V2(-24f, 9f),
            });

            // Eight ghost loops: the main body in a 3 x 2 grid without the gate square, then one per wing
            l.GhostRoutes.Add(new List<V2> { new V2(-26f, -24f), new V2(-13f, -24f), new V2(-13f, -10f), new V2(-30f, -10f) });
            l.GhostRoutes.Add(new List<V2> { new V2(13f, -24f), new V2(26f, -24f), new V2(30f, -10f), new V2(13f, -10f) });
            l.GhostRoutes.Add(new List<V2> { new V2(-30f, -4f), new V2(-13f, -4f), new V2(-13f, 15f), new V2(-30f, 15f) });
            l.GhostRoutes.Add(new List<V2> { new V2(-5f, -2f), new V2(5f, -2f), new V2(5f, 5f), new V2(-5f, 5f) });
            l.GhostRoutes.Add(new List<V2> { new V2(13f, -4f), new V2(30f, -4f), new V2(26f, 13f), new V2(13f, 15f) });
            l.GhostRoutes.Add(new List<V2> { new V2(-30f, 20f), new V2(-10f, 20f), new V2(-10f, 32f), new V2(-25.5f, 32f) });
            l.GhostRoutes.Add(new List<V2> { new V2(35f, -17f), new V2(44f, -17f), new V2(44f, 4f), new V2(35f, 7f) });
            l.GhostRoutes.Add(new List<V2> { new V2(-40f, -7f), new V2(-35f, -7f), new V2(-35f, 11f), new V2(-40f, 11f) });
            return l;
        }

        // The part every yard of this outline shares: the wall, the gate opening, the keeper's start, the gate lamps
        public static Level Walled(IEnumerable<Area> areas)
        {
            var l = new Level();
            l.Areas.AddRange(areas);
            var main = l.Areas[0];
            float gateZ = main.MinZ;
            l.Gate = new V2(0f, gateZ + 1f);
            l.KeeperStart = new V2(0f, gateZ + 3f);

            var b = l.Bounds;
            for (float x = b.MinX + Tile * 0.5f; x < b.MaxX; x += Tile)
            for (float z = b.MinZ + Tile * 0.5f; z < b.MaxZ; z += Tile)
            {
                if (!l.Inside(new V2(x, z))) continue;
                // A wall on each side of this tile that faces outside, centered on the tile's edge
                if (!l.Inside(new V2(x, z + Tile)))
                    l.Add("stone-wall", x, z + Tile * 0.5f + WallPivot, 0);
                if (!l.Inside(new V2(x, z - Tile)) && !(Math.Abs(z - Tile * 0.5f - gateZ) < 0.01f && Math.Abs(x) < GateWidth * 0.5f))
                    l.Add("stone-wall", x, z - Tile * 0.5f + WallPivot, 0);
                if (!l.Inside(new V2(x + Tile, z)))
                    l.Add("stone-wall", x + Tile * 0.5f + WallPivot, z, 90);
                if (!l.Inside(new V2(x - Tile, z)))
                    l.Add("stone-wall", x - Tile * 0.5f + WallPivot, z, 90);
            }
            l.Add("lightpost-single", -GateWidth * 0.5f - 1f, gateZ + 0.8f, 0);
            l.Add("lightpost-single", GateWidth * 0.5f + 1f, gateZ + 0.8f, 0);
            l.FixedProps = l.Props.Count;
            return l;
        }

        public void Add(string model, float x, float z, float yaw)
        {
            Props.Add(new Prop { Model = model, Position = new V2(x, z), Yaw = yaw });
        }

        // Does the box come within gap of any prop from index `from` on (the big cover placed before the rows)?
        private bool ClutterNear(Box box, int from, float gap)
        {
            for (int i = FixedProps; i < from && i < Props.Count; i++)
                if (box.Overlaps(Footprint.Of(Props[i]), gap)) return true;
            return false;
        }
    }
}
