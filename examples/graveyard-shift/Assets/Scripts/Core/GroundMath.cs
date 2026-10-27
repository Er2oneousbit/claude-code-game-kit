// ---------------------------------------------------------------------------
// GroundMath.cs
// Purpose : A tiny 2D vector for the ground plane (x, z in Unity) and the angle helpers the rules need,
//           so Core stays free of UnityEngine and its tests run without a scene.
// Usage   : var d = V2.Distance(a, b); float a = V2.AngleBetween(forward, toTarget);
// Notes   : Game code converts with new V2(pos.x, pos.z) and new Vector3(v.X, y, v.Z).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;

namespace graveyard_shift.Core
{
    [Serializable]
    public struct V2
    {
        public float X;
        public float Z;

        public V2(float x, float z)
        {
            X = x;
            Z = z;
        }

        public static V2 operator +(V2 a, V2 b) => new V2(a.X + b.X, a.Z + b.Z);
        public static V2 operator -(V2 a, V2 b) => new V2(a.X - b.X, a.Z - b.Z);
        public static V2 operator *(V2 a, float s) => new V2(a.X * s, a.Z * s);

        public float Length => (float)Math.Sqrt(X * X + Z * Z);
        public V2 Normalized => Length < 1e-6f ? new V2(0, 0) : this * (1f / Length);

        public static float Distance(V2 a, V2 b) => (a - b).Length;
        public static float Dot(V2 a, V2 b) => a.X * b.X + a.Z * b.Z;

        // Unsigned angle in degrees between two directions (0 when either is zero length).
        public static float AngleBetween(V2 a, V2 b)
        {
            float la = a.Length;
            float lb = b.Length;
            if (la < 1e-6f || lb < 1e-6f) return 0f;
            float c = Dot(a, b) / (la * lb);
            c = Math.Max(-1f, Math.Min(1f, c));
            return (float)(Math.Acos(c) * 180.0 / Math.PI);
        }

        public override string ToString() => $"({X:0.0}, {Z:0.0})";
    }
}
