// ---------------------------------------------------------------------------
// Footprint.cs
// Purpose : How much ground each prop covers, without loading a mesh: the generator and LevelCheck use
//           it to keep props apart and to find where the keeper can walk.
// Usage   : Box b = Footprint.Of(prop);  b.Distance(point); b.Overlaps(other, margin)
// Notes   : Sizes were measured from the Kenney meshes at Level.WorldScale (renderer bounds, yaw 0) on
//           2026-10-22; FootprintTests compares them with the real meshes, so new art fails a test instead
//           of quietly breaking the checks. A rotated prop gets the box around its rotated footprint,
//           which is what LevelBuilder's blocker gets too: Renderer.bounds of a turned mesh is the box around
//           its turned box, so a pine at 45 degrees blocks 3.6 m, not 2.7 m. Edges snap outward to 1/16 m:
//           exact floats, so generated yards come out the same in the editor (Mono) and the player (IL2CPP).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fix (Claude Opus 5.5): cover is height-based. A ghost's sight runs from its eye
//           (1.3 m) to the keeper's chest (ChestHeight, 1.1 m), so a prop lower than the chest never blocks it:
//           crypt-a, crypt-b, gravestone-bevel, gravestone-broken and rocks were counted as cover and hid nobody.
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;

namespace graveyard_shift.Core
{
    // A world-aligned rectangle on the ground plane
    public struct Box
    {
        public float MinX, MaxX, MinZ, MaxZ;

        public Box(V2 center, float halfX, float halfZ)
        {
            MinX = center.X - halfX;
            MaxX = center.X + halfX;
            MinZ = center.Z - halfZ;
            MaxZ = center.Z + halfZ;
        }

        // 0 inside, else the distance to the nearest edge
        public float Distance(V2 p)
        {
            float dx = Math.Max(0f, Math.Max(MinX - p.X, p.X - MaxX));
            float dz = Math.Max(0f, Math.Max(MinZ - p.Z, p.Z - MaxZ));
            return (float)Math.Sqrt(dx * dx + dz * dz);
        }

        // Do the boxes overlap, or come closer than margin?
        public bool Overlaps(Box o, float margin) =>
            MinX < o.MaxX + margin && o.MinX < MaxX + margin && MinZ < o.MaxZ + margin && o.MinZ < MaxZ + margin;

        public override string ToString() => $"[{MinX:0.0}..{MaxX:0.0}, {MinZ:0.0}..{MaxZ:0.0}]";
    }

    public static class Footprint
    {
        // model -> bounds center offset (x, z) and size (x, z) in meters at WorldScale, yaw 0
        private static readonly Dictionary<string, float[]> Sizes = new Dictionary<string, float[]>
        {
            { "crypt", new[] { 0f, 0f, 1.44f, 2.23f } },
            { "crypt-a", new[] { 0f, 0f, 1.24f, 2.24f } },
            { "crypt-b", new[] { 0f, 0f, 1.24f, 2.24f } },
            // Buildings: the crypt with its roof and door (Parts), measured together
            { "crypt-large", new[] { 0f, -0.05f, 3.96f, 4.98f } },
            { "crypt-small", new[] { 0f, -0.045f, 3.00f, 2.97f } },
            { "gravestone-bevel", new[] { 0f, 0f, 0.90f, 0.50f } },
            { "gravestone-broken", new[] { -0.06f, 0.14f, 1.02f, 0.78f } },
            { "gravestone-cross", new[] { 0f, 0f, 0.90f, 0.66f } },
            { "gravestone-round", new[] { 0f, 0f, 0.90f, 0.50f } },
            { "gravestone-wide", new[] { 0f, 0f, 1.70f, 0.60f } },
            { "lightpost-single", new[] { 0f, 0.26f, 0.42f, 0.93f } },
            { "pine", new[] { 0f, 0f, 2.36f, 2.67f } },
            { "pine-crooked", new[] { -0.04f, 0f, 2.36f, 2.67f } },
            { "rocks", new[] { -0.21f, 0.10f, 2.15f, 1.93f } },
            { "rocks-tall", new[] { -0.01f, -0.11f, 2.07f, 2.04f } },
            { "stone-wall", new[] { 0f, -0.80f, 2.00f, 0.40f } },
        };

        // model -> top of its mesh in meters at WorldScale (renderer bounds, measured 2026-10-26; the same at any yaw).
        // HeightsTests compares them with the real meshes.
        private static readonly Dictionary<string, float> Heights = new Dictionary<string, float>
        {
            { "crypt", 1.46f }, { "crypt-a", 1.04f }, { "crypt-b", 1.04f }, { "crypt-large", 3.52f }, { "crypt-small", 3.48f },
            { "gravestone-bevel", 1.06f }, { "gravestone-broken", 0.68f }, { "gravestone-cross", 1.83f },
            { "gravestone-round", 1.15f }, { "gravestone-wide", 1.14f }, { "lightpost-single", 2.53f },
            { "pine", 4.40f }, { "pine-crooked", 4.02f }, { "rocks", 0.75f }, { "rocks-tall", 1.18f }, { "stone-wall", 1.45f },
        };

        // The keeper's chest above the ground: the low end of every ghost's line of sight (KeeperController.Chest)
        public const float ChestHeight = 1.1f;

        public static bool Known(string model) => Sizes.ContainsKey(model);

        public static float Height(string model) => Heights.TryGetValue(model, out float h) ? h : 0f;

        public static IEnumerable<string> Models => Sizes.Keys;

        // The measured size (x, z) at yaw 0 and the center offset, for FootprintTests
        public static float[] Measured(string model) => Sizes[model];

        // Cover hides a keeper pressed against it: it must reach the chest, where the sight line is lowest. Stones of
        // 1.14 to 1.18 m do (only up close: farther off the line passes over them); walls and posts do not count,
        // because nobody hides behind a lamp and a wall is the edge, not a hiding place.
        public static bool IsCover(string model) =>
            model != "stone-wall" && model != "lightpost-single" && Height(model) >= ChestHeight;

        // Pieces LevelBuilder adds to a prop (model, height, offset toward the front at yaw 0), so the two big crypts
        // read as buildings: a roof on the walls and a closed door in the front (-z) arch. Measured 2026-10-23.
        private static readonly Dictionary<string, (string Model, float Y, float Z)[]> Pieces = new Dictionary<string, (string, float, float)[]>
        {
            { "crypt-large", new[] { ("crypt-large-roof", 2f, 0f), ("crypt-large-door", 0f, -2.4f) } },
            { "crypt-small", new[] { ("crypt-small-roof", 2f, 0f), ("crypt-door", 0f, -1.4f) } },
        };

        private static readonly (string, float, float)[] NoPieces = new (string, float, float)[0];

        public static (string Model, float Y, float Z)[] Parts(string model) =>
            Pieces.TryGetValue(model, out var parts) ? parts : NoPieces;

        // Boxes snap outward to this lattice (1/16 m), so every edge is exact in a float on every runtime
        public const int Lattice = 16;

        public static Box Of(Prop p)
        {
            float[] s = Sizes.TryGetValue(p.Model, out var found) ? found : new[] { 0f, 0f, 1f, 1f };
            // In double (the same on every runtime), then outward to the lattice.
            // Unity's yaw turns +z toward +x: (x, z) -> (x cos + z sin, -x sin + z cos)
            double a = p.Yaw * Math.PI / 180.0;
            // Rounded to 12 places: a last-bit difference between two runtimes' Cos and Sin cannot reach the snap below
            double c = Math.Round(Math.Cos(a), 12), n = Math.Round(Math.Sin(a), 12);
            double cx = p.Position.X + s[0] * c + s[1] * n, cz = p.Position.Z - s[0] * n + s[1] * c;
            double ac = Math.Abs(c), an = Math.Abs(n);
            double hx = 0.5 * (s[2] * ac + s[3] * an), hz = 0.5 * (s[2] * an + s[3] * ac);
            return new Box
            {
                MinX = Down(cx - hx), MaxX = Up(cx + hx),
                MinZ = Down(cz - hz), MaxZ = Up(cz + hz),
            };
        }

        // 1e-9 keeps an edge that is already on the lattice where it is
        private static float Down(double v) => (float)(Math.Floor(v * Lattice + 1e-9) / Lattice);
        private static float Up(double v) => (float)(Math.Ceiling(v * Lattice - 1e-9) / Lattice);
    }
}
