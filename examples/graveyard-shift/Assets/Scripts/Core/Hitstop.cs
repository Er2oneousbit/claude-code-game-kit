// ---------------------------------------------------------------------------
// Hitstop.cs
// Purpose : Freezes game time for a moment on impact (hit pause), the cheapest way to make a hit land.
//           Checked against data/golden/juice.json ("hitstop").
// Usage   : var hitstop = new Hitstop();
//           on a hit:   hitstop.Hit(0.06);
//           each frame: double gameDt = hitstop.ScaledDt(Time.unscaledDeltaTime);   // feed gameDt to gameplay
// Notes   : No UnityEngine types (EditMode tests run it). Overlapping hits keep the longest freeze, capped at
//           MaxSeconds, so a flurry of hits never locks the game. UI and audio keep the real delta.
//
// Pseudocode:
//   hit(d):        remaining = min(max(remaining, d), max_s)
//   scaled_dt(dt): nothing frozen -> dt ; else used = min(remaining, dt), remaining -= used, return dt - used
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;

namespace graveyard_shift.Core
{
    public sealed class Hitstop
    {
        // ---- Tunables ------------------------------------------------------------
        public const double DEFAULT_MAX_SECONDS = 0.25;    // the longest freeze any pile of hits can cause

        public double MaxSeconds;
        public double Remaining { get; private set; }

        public Hitstop(double maxSeconds = DEFAULT_MAX_SECONDS)
        {
            MaxSeconds = maxSeconds;
        }

        /// <summary>Starts (or extends) a freeze of duration seconds; the longest overlapping hit wins.</summary>
        public void Hit(double duration)
        {
            Remaining = Math.Min(Math.Max(Remaining, duration), MaxSeconds);
        }

        /// <summary>The game's delta for this frame: the frozen part of realDt is removed.</summary>
        public double ScaledDt(double realDt)
        {
            if (Remaining <= 0.0)
            {
                return realDt;
            }
            double used = Math.Min(Remaining, realDt);
            Remaining -= used;
            return realDt - used;
        }
    }
}
