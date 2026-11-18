// ---------------------------------------------------------------------------
// Feel.cs
// Purpose : The small helpers SOP-18's recipe table builds on (#170, #164): Impact (a hit confirm scaled by damage),
//           FloatText (a damage number's rise, pop and fade) and the tracer's point history by distance
//           (TrailPush, TrailShrink, TrailLength). Checked against data/golden/juice.json ("impact", "float_text",
//           "trail").
// Usage   : var hit = Feel.Impact(damage, enemy.MaxHp);
//           hitstop.Hit(hit.Hitstop); shake.AddTrauma(hit.Trauma);
//           if (hit.Flash && limiter.Request(Time.realtimeSinceStartupAsDouble)) Flash();
//           var f = Feel.FloatText(label.Age);                 // f.Dy, f.Scale, f.Alpha, f.Done
//           points = Feel.TrailPush(points, pos.x, pos.y, spacing, length);   // every frame (a LineRenderer draws
//           them); after the hit: points = Feel.TrailShrink(points, speed * dt) until fewer than two are left
// Notes   : No UnityEngine types (EditMode tests run it): no settings, no clock, no random numbers. Points are
//           double[2] {x, y}, tail first, head last; each trail function returns a new list. The defaults are
//           SOP-18's starting points.
//
// Pseudocode:
//   impact: f = clamp(damage / full, 0, 1) (full <= 0: 1); nothing for damage <= 0; lerp hitstop, trauma; flash f >= at
//   float_text: u = t / life; dy = -rise * out_cubic(u); scale = out_back(t / pop); alpha = 1 - in_cubic(u)
//   trail_push: < 2 points: append; head spacing past the point before it: append; else move the head; cut to length
//   trail_shrink: cut the trail to (length - amount) from the tail
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;

namespace {{GAME_SLUG}}.Core
{
    public static class Feel
    {
        // ---- Tunables (SOP-18 step 4 starting points) -----------------------------
        public const double HITSTOP_MIN = 0.03;     // s, the smallest hit
        public const double HITSTOP_MAX = 0.1;      // s, a full hit (under Hitstop's 0.25 s cap)
        public const double TRAUMA_MIN = 0.15;
        public const double TRAUMA_MAX = 0.6;
        public const double FLASH_AT = 0.5;         // a hit of at least half of `full` asks for a flash
        public const double FLOAT_LIFE = 0.8;       // s
        public const double FLOAT_RISE = 24.0;      // px
        public const double FLOAT_POP = 0.12;       // s
        public const double TRAIL_SPACING = 6.0;    // px between kept points
        public const double TRAIL_LENGTH = 48.0;    // px, the longest trail
        private const double EPS = 1e-12;           // a cut this close to a point removes the point

        public readonly struct ImpactResult
        {
            public readonly double Hitstop;
            public readonly double Trauma;
            public readonly bool Flash;

            public ImpactResult(double hitstop, double trauma, bool flash)
            {
                Hitstop = hitstop;
                Trauma = trauma;
                Flash = flash;
            }
        }

        public readonly struct FloatTextResult
        {
            public readonly double Dy;
            public readonly double Scale;
            public readonly double Alpha;
            public readonly bool Done;

            public FloatTextResult(double dy, double scale, double alpha, bool done)
            {
                Dy = dy;
                Scale = scale;
                Alpha = alpha;
                Done = done;
            }
        }

        public static ImpactResult Impact(double damage, double full, double hitstopMin = HITSTOP_MIN,
                                          double hitstopMax = HITSTOP_MAX, double traumaMin = TRAUMA_MIN,
                                          double traumaMax = TRAUMA_MAX, double flashAt = FLASH_AT)
        {
            if (damage <= 0.0)
            {
                return new ImpactResult(0.0, 0.0, false);
            }
            double f = full <= 0.0 ? 1.0 : Math.Min(Math.Max(damage / full, 0.0), 1.0);
            return new ImpactResult(hitstopMin + (hitstopMax - hitstopMin) * f, traumaMin + (traumaMax - traumaMin) * f,
                                    f >= flashAt);
        }

        public static FloatTextResult FloatText(double t, double life = FLOAT_LIFE, double rise = FLOAT_RISE,
                                                double popS = FLOAT_POP)
        {
            double u = life > 0.0 ? Math.Min(Math.Max(t / life, 0.0), 1.0) : 1.0;
            double scale = popS > 0.0 ? Ease.Apply("out_back", t / popS) : 1.0;
            return new FloatTextResult(-rise * Ease.Apply("out_cubic", u), scale, 1.0 - Ease.Apply("in_cubic", u),
                                       t >= life);
        }

        private static double Seg(double[] a, double[] b)
        {
            double dx = b[0] - a[0];
            double dy = b[1] - a[1];
            return Math.Sqrt(dx * dx + dy * dy);
        }

        /// <summary>Total length, tail to head (summed in order, as the reference does).</summary>
        public static double TrailLength(IReadOnlyList<double[]> points)
        {
            double total = 0.0;
            for (int i = 0; i + 1 < points.Count; i++)
            {
                total += Seg(points[i], points[i + 1]);
            }
            return total;
        }

        private static List<double[]> Copy(IReadOnlyList<double[]> points)
        {
            var pts = new List<double[]>(points.Count + 1);
            foreach (double[] p in points)
            {
                pts.Add(new[] { p[0], p[1] });
            }
            return pts;
        }

        private static List<double[]> TrimTo(List<double[]> pts, double keep)
        {
            double excess = TrailLength(pts) - Math.Max(keep, 0.0);
            while (excess > EPS && pts.Count > 1)
            {
                double s = Seg(pts[0], pts[1]);
                if (s <= excess + EPS)
                {
                    pts.RemoveAt(0);
                    excess -= s;
                }
                else
                {
                    double k = excess / s;
                    pts[0] = new[] { pts[0][0] + (pts[1][0] - pts[0][0]) * k, pts[0][1] + (pts[1][1] - pts[0][1]) * k };
                    excess = 0.0;
                }
            }
            return pts;
        }

        /// <summary>A tracer's path: the head follows (x, y); a new point is kept once the head is `spacing` past the
        /// point before it (by distance, not frame); longer than maxLen, the tail is cut.</summary>
        public static List<double[]> TrailPush(IReadOnlyList<double[]> points, double x, double y,
                                               double spacing = TRAIL_SPACING, double maxLen = TRAIL_LENGTH)
        {
            List<double[]> pts = Copy(points);
            int n = pts.Count;
            if (n < 2 || Seg(pts[n - 2], pts[n - 1]) >= spacing)
            {
                pts.Add(new[] { x, y });
            }
            else
            {
                pts[n - 1] = new[] { x, y };
            }
            return TrimTo(pts, maxLen);
        }

        /// <summary>The tail catching up after the shot dies: remove `amount` px from the tail (fewer than two
        /// points: draw nothing).</summary>
        public static List<double[]> TrailShrink(IReadOnlyList<double[]> points, double amount)
        {
            return TrimTo(Copy(points), TrailLength(points) - amount);
        }
    }
}

// {{FOOTER}}
