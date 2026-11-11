// ---------------------------------------------------------------------------
// FrameTimes.cs
// Purpose : Frame-time sampling for `dev.py smoke` (#90): a Smoke test adds each frame's time and logs one line at
//           the end, which dev.py reads from the Unity log, reports and checks against --frame-budget:
//             FRAME_TIMES frames=N mean=MS p95=MS p99=MS worst=MS mode=logic|render
// Usage   : var ft = new FrameTimes(); ft.Add(ms); ... Debug.Log(ft.Line("logic"));
//           FrameTimes.Summarize(list) is a plain function (Assets/Tests/EditMode/FrameTimesTests.cs).
// Notes   : No UnityEngine types (EditMode tests run instantly). dev.py smoke runs Unity in batch mode with
//           -nographics unless a capture needs a renderer, so the mode is "logic" there (a logic budget, not a
//           render budget). Numbers use the invariant culture: a comma decimal separator would break dev.py's
//           parsing. Percentiles are nearest-rank, the same rule as every engine's FRAME_TIMES line.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.Globalization;

namespace {{GAME_SLUG}}.Core
{
    public sealed class FrameTimes
    {
        public struct Summary
        {
            public int Frames;
            public double Mean, P95, P99, Worst;
        }

        private readonly List<double> _samples = new List<double>();

        public int Count => _samples.Count;

        /// <summary>Records one frame's time in milliseconds.</summary>
        public void Add(double ms) => _samples.Add(ms);

        /// <summary>Mean, nearest-rank p95 and p99, and worst of these times (all 0 when there are none).</summary>
        public static Summary Summarize(IReadOnlyList<double> ms)
        {
            var s = new Summary { Frames = ms.Count };
            if (ms.Count == 0)
            {
                return s;
            }
            var sorted = new List<double>(ms);
            sorted.Sort();
            double total = 0;
            foreach (double v in sorted)
            {
                total += v;
            }
            s.Mean = total / sorted.Count;
            s.P95 = Rank(sorted, 0.95);
            s.P99 = Rank(sorted, 0.99);
            s.Worst = sorted[sorted.Count - 1];
            return s;
        }

        /// <summary>The FRAME_TIMES line ("" when no frame was added).</summary>
        public string Line(string mode)
        {
            if (_samples.Count == 0)
            {
                return "";
            }
            Summary s = Summarize(_samples);
            return string.Format(CultureInfo.InvariantCulture,
                "FRAME_TIMES frames={0} mean={1:F2} p95={2:F2} p99={3:F2} worst={4:F2} mode={5}",
                s.Frames, s.Mean, s.P95, s.P99, s.Worst, mode);
        }

        // Nearest rank: the smallest value with at least q of the samples at or below it.
        private static double Rank(List<double> sorted, double q)
        {
            int i = Math.Max(0, (int)Math.Ceiling(q * sorted.Count) - 1);
            return sorted[Math.Min(i, sorted.Count - 1)];
        }
    }
}

// {{FOOTER}}
