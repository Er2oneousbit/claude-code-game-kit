// ---------------------------------------------------------------------------
// Spring.cs
// Purpose : A damped spring for squash-and-stretch recovery, UI pops and wobble, plus the volume-keeping
//           squash scale. Checked against data/golden/juice.json ("spring" and "squash").
// Usage   : var spring = new Spring();             // frequency in Hz, damping 0 (wobbles forever) .. 1 (no overshoot)
//           on landing: spring.X = 0.4;           // kick it (or set Target for a new rest point)
//           each frame: var s = Squash.Scale(spring.Update(Time.deltaTime));
//                       sprite scale = (s.ScaleX, s.ScaleY)
// Notes   : No UnityEngine types (EditMode tests run it). Semi-implicit Euler: stable at game frame rates;
//           for a stiff spring (high frequency) on a long frame, step it in smaller pieces. Squash keeps the
//           area: x * y = 1, and the amount is clamped above -0.9 so a stretch never flips the sprite.
//
// Pseudocode:
//   w = 2*pi*frequency ; a = -w^2 (x - target) - 2*damping*w*v ; v += a*dt ; x += v*dt
//   squash(amount): a = max(amount, -0.9) ; scale = (1 + a, 1 / (1 + a))
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;

namespace graveyard_shift.Core
{
    public sealed class Spring
    {
        // ---- Tunables ------------------------------------------------------------
        public const double DEFAULT_FREQUENCY = 4.0;   // oscillations per second
        public const double DEFAULT_DAMPING = 0.5;     // damping ratio: 0 wobbles forever, 1 settles without overshoot

        public double Frequency;
        public double Damping;
        public double X;                               // position
        public double V;                               // velocity
        public double Target;                          // rest position

        public Spring(double frequency = DEFAULT_FREQUENCY, double damping = DEFAULT_DAMPING)
        {
            Frequency = frequency;
            Damping = damping;
        }

        /// <summary>Advances the spring by dt seconds and returns the new position.</summary>
        public double Update(double dt)
        {
            double w = 2.0 * Math.PI * Frequency;
            double a = -w * w * (X - Target) - 2.0 * Damping * w * V;
            V += a * dt;
            X += V * dt;
            return X;
        }
    }

    public static class Squash
    {
        // ---- Tunables ------------------------------------------------------------
        public const double MIN_AMOUNT = -0.9;         // the strongest stretch (keeps both scales positive)

        /// <summary>Scale for a squash amount: &gt; 0 widens and flattens, &lt; 0 stretches; area stays 1.</summary>
        public static (double ScaleX, double ScaleY) Scale(double amount)
        {
            double a = Math.Max(amount, MIN_AMOUNT);
            return (1.0 + a, 1.0 / (1.0 + a));
        }
    }
}
