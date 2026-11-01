// ---------------------------------------------------------------------------
// FlashLimiter.cs
// Purpose : Photosensitivity guard: at most MaxFlashes full-screen flashes in any window (three per second
//           by default). Checked against data/golden/juice.json ("flash_limiter").
// Usage   : var flashes = new FlashLimiter();
//           before a full-screen flash: if (!settingFlashLimit || flashes.Request(Time.unscaledTimeAsDouble)) Flash();
// Notes   : No UnityEngine types (EditMode tests run it). A refused flash is skipped, not queued. The access
//           setting "flash_limit" (GameSettings) is on by default; keep it on unless the player turns it off.
//           now is any clock in seconds that only goes forward (unscaled, so hitstop cannot bunch flashes).
//
// Pseudocode:
//   request(now): drop the times at or before now - window ; fewer than max left -> remember now, true ; else false
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections.Generic;

namespace {{GAME_SLUG}}.Core
{
    public sealed class FlashLimiter
    {
        // ---- Tunables ------------------------------------------------------------
        public const int DEFAULT_MAX_FLASHES = 3;      // the common guideline: no more than three flashes per second
        public const double DEFAULT_WINDOW_S = 1.0;

        private readonly List<double> _times = new List<double>();

        public int MaxFlashes;
        public double Window;

        public FlashLimiter(int maxFlashes = DEFAULT_MAX_FLASHES, double windowSeconds = DEFAULT_WINDOW_S)
        {
            MaxFlashes = maxFlashes;
            Window = windowSeconds;
        }

        /// <summary>True when a flash at time now is allowed (and counts it), false when it must be skipped.</summary>
        public bool Request(double now)
        {
            double since = now - Window;
            _times.RemoveAll(t => !(t > since));
            if (_times.Count < MaxFlashes)
            {
                _times.Add(now);
                return true;
            }
            return false;
        }
    }
}

// {{FOOTER}}
