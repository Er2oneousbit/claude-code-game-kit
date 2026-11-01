// ---------------------------------------------------------------------------
// Shake.cs
// Purpose : Trauma-based screen shake (and the smooth value noise it is built on). Hits add trauma 0..1,
//           trauma decays linearly, and the camera offset is trauma squared times noise, so small hits
//           barely move the camera and big ones really do. Checked against data/golden/juice.json
//           ("noise" and "shake").
// Usage   : var shake = new Shake();                 // tunables below, or pass your own
//           on a hit:   shake.AddTrauma(0.4);
//           each frame: var s = shake.Update(Time.deltaTime, GameSettings.EffectiveShake(settings));
//                       camera offset = (s.X, s.Y) in pixels or units, rotation = s.Angle in radians
// Notes   : No UnityEngine types, so EditMode tests run it instantly; the MonoBehaviour applying the offset is
//           thin glue in Assets/Scripts/Game. intensity is the player's shake setting: 0 with reduce motion
//           (GameSettings.EffectiveShake), so the setting really turns it off. Noise uses Park-Miller integer
//           arithmetic that is exact in 64-bit, so every engine port of the kit computes the same numbers.
//
// Pseudocode:
//   lattice(seed, i, ch) = Park-Miller of (seed*7919 + i*104729 + ch*15485863) mod M, twice, mapped to (-1, 1]
//   noise(seed, t, ch)   = lattice at floor(t) and floor(t)+1, blended with smoothstep of the fraction
//   update: time += dt ; trauma = max(trauma - decay*dt, 0) ; s = trauma^2 * intensity
//           x, y, angle = max_offset*s*noise(t*frequency, channel 0 / 1), max_angle*s*noise(channel 2)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;

namespace graveyard_shift.Core
{
    /// <summary>Smooth 1D value noise in (-1, 1], identical in every engine port of the kit.</summary>
    public static class Noise
    {
        public const long PM_M = 2147483647;           // Park-Miller modulus (2^31 - 1)
        public const long PM_A = 16807;

        /// <summary>The value at integer lattice point i of channel ch. Products stay below 2^53.</summary>
        public static double Lattice(long seed, long i, int ch)
        {
            long s = Mod(seed * 7919 + i * 104729 + ch * 15485863L, PM_M);
            if (s == 0)
            {
                s = 1;
            }
            s = (s * PM_A) % PM_M;
            s = (s * PM_A) % PM_M;
            return (double)s / (PM_M - 1) * 2.0 - 1.0;
        }

        /// <summary>Noise at time t (t &gt;= 0) of channel ch: lattice values blended with smoothstep.</summary>
        public static double Value(long seed, double t, int ch)
        {
            double floor = Math.Floor(t);
            long i = (long)floor;
            double f = t - floor;
            double a = Lattice(seed, i, ch);
            double b = Lattice(seed, i + 1, ch);
            double u = f * f * (3.0 - 2.0 * f);
            return a + (b - a) * u;
        }

        // Python's % (never negative), so a negative seed lands on the same lattice as the reference
        private static long Mod(long x, long m)
        {
            long r = x % m;
            return r < 0 ? r + m : r;
        }
    }

    public sealed class Shake
    {
        // ---- Tunables ------------------------------------------------------------
        public const double DEFAULT_MAX_OFFSET = 8.0;  // pixels (or units) at full trauma
        public const double DEFAULT_MAX_ANGLE = 0.05;  // radians at full trauma
        public const double DEFAULT_DECAY = 1.5;       // trauma lost per second
        public const double DEFAULT_FREQUENCY = 15.0;  // noise samples per second (higher = more jittery)
        public const long DEFAULT_SEED = 1;

        public double MaxOffset;
        public double MaxAngle;
        public double Decay;
        public double Frequency;
        public long Seed;

        public double Trauma { get; private set; }
        public double Time { get; private set; }

        public Shake(double maxOffset = DEFAULT_MAX_OFFSET, double maxAngle = DEFAULT_MAX_ANGLE,
                     double decay = DEFAULT_DECAY, double frequency = DEFAULT_FREQUENCY, long seed = DEFAULT_SEED)
        {
            MaxOffset = maxOffset;
            MaxAngle = maxAngle;
            Decay = decay;
            Frequency = frequency;
            Seed = seed;
        }

        /// <summary>Adds (or with a negative amount removes) trauma, kept within 0..1.</summary>
        public void AddTrauma(double amount)
        {
            Trauma = Math.Min(Math.Max(Trauma + amount, 0.0), 1.0);
        }

        /// <summary>Advances the shake. intensity is the player's shake setting (0 with reduce motion).</summary>
        public (double X, double Y, double Angle) Update(double dt, double intensity = 1.0)
        {
            Time += dt;
            Trauma = Math.Max(Trauma - Decay * dt, 0.0);
            double s = Trauma * Trauma * intensity;
            double t = Time * Frequency;
            return (MaxOffset * s * Noise.Value(Seed, t, 0),
                    MaxOffset * s * Noise.Value(Seed, t, 1),
                    MaxAngle * s * Noise.Value(Seed, t, 2));
        }
    }
}
