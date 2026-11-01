// ---------------------------------------------------------------------------
// Ease.cs
// Purpose : Easing curves by name (linear, quad, cubic, sine, back, elastic, bounce) for tweens, UI pops and
//           camera moves. Checked against data/golden/juice.json ("ease").
// Usage   : double k = Ease.Apply("out_back", elapsed / duration);   // t is clamped to 0..1
//           value = from + (to - from) * k
// Notes   : No UnityEngine types (EditMode tests run it). Names match every engine port of the kit, so a tuning
//           file can say "out_back" on any engine. An unknown name throws ArgumentException (a typo should
//           fail loudly, not ease linearly). The formulas are the common easings.net set.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;

namespace graveyard_shift.Core
{
    public static class Ease
    {
        // ---- Tunables ------------------------------------------------------------
        private const double C1 = 1.70158;             // back overshoot
        private const double C3 = C1 + 1.0;
        private const double C4 = 2.0 * Math.PI / 3.0; // elastic period
        private const double N1 = 7.5625;              // bounce
        private const double D1 = 2.75;

        private static readonly Dictionary<string, Func<double, double>> CURVES = new Dictionary<string, Func<double, double>>
        {
            { "linear", t => t },
            { "in_quad", t => t * t },
            { "out_quad", t => 1.0 - (1.0 - t) * (1.0 - t) },
            { "in_out_quad", t => t < 0.5 ? 2.0 * t * t : 1.0 - Math.Pow(-2.0 * t + 2.0, 2) / 2.0 },
            { "in_cubic", t => t * t * t },
            { "out_cubic", t => 1.0 - Math.Pow(1.0 - t, 3) },
            { "in_out_cubic", t => t < 0.5 ? 4.0 * t * t * t : 1.0 - Math.Pow(-2.0 * t + 2.0, 3) / 2.0 },
            { "in_sine", t => 1.0 - Math.Cos(t * Math.PI / 2.0) },
            { "out_sine", t => Math.Sin(t * Math.PI / 2.0) },
            { "in_out_sine", t => -(Math.Cos(Math.PI * t) - 1.0) / 2.0 },
            { "in_back", t => C3 * t * t * t - C1 * t * t },
            { "out_back", t => 1.0 + C3 * Math.Pow(t - 1.0, 3) + C1 * Math.Pow(t - 1.0, 2) },
            { "out_elastic", t => t <= 0.0 ? 0.0 : t >= 1.0 ? 1.0
                                  : Math.Pow(2.0, -10.0 * t) * Math.Sin((t * 10.0 - 0.75) * C4) + 1.0 },
            { "out_bounce", Bounce },
        };

        /// <summary>Every curve name, for a tuning UI or a validation pass over data files.</summary>
        public static IEnumerable<string> Names => CURVES.Keys;

        public static bool Has(string name)
        {
            return name != null && CURVES.ContainsKey(name);
        }

        /// <summary>The eased value of t (clamped to 0..1). Throws ArgumentException for an unknown name.</summary>
        public static double Apply(string name, double t)
        {
            if (name == null || !CURVES.TryGetValue(name, out Func<double, double> curve))
            {
                throw new ArgumentException($"unknown easing '{name}' (see Ease.Names)", nameof(name));
            }
            return curve(Math.Min(Math.Max(t, 0.0), 1.0));
        }

        private static double Bounce(double t)
        {
            if (t < 1.0 / D1)
            {
                return N1 * t * t;
            }
            if (t < 2.0 / D1)
            {
                t -= 1.5 / D1;
                return N1 * t * t + 0.75;
            }
            if (t < 2.5 / D1)
            {
                t -= 2.25 / D1;
                return N1 * t * t + 0.9375;
            }
            t -= 2.625 / D1;
            return N1 * t * t + 0.984375;
        }
    }
}
