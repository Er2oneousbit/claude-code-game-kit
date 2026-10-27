// ---------------------------------------------------------------------------
// FixedTimestep.cs
// Purpose : Engine-free fixed-step accumulator (example of testable Core logic).
// Usage   : var ts = new FixedTimestep(1.0 / 60.0); int n = ts.Advance(frameSeconds);
// Notes   : No UnityEngine types, so EditMode tests run instantly. Frame time is clamped,
//           steps per frame are capped, backlog is dropped instead of spiraling.
//
// Pseudocode (same as the C++ twin in the C++/SDL2 overlay):
//   frame_dt = min(frame_dt, max_frame), and 0 for negative or NaN input
//   accumulator += frame_dt
//   steps = 0
//   while accumulator >= step and steps < max_steps: accumulator -= step; steps++
//   if steps hit the cap: accumulator = 0 and remember we dropped time
//   return steps
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// ---------------------------------------------------------------------------
using System;

namespace graveyard_shift.Core
{
    public sealed class FixedTimestep
    {
        private readonly double _step;
        private readonly double _maxFrame;
        private readonly int _maxSteps;
        private double _accumulator;

        public bool DroppedTime { get; private set; }
        public double Step => _step;
        public double Alpha => _accumulator / _step;

        public FixedTimestep(double stepSeconds, double maxFrameSeconds = 0.25, int maxSteps = 8)
        {
            _step = stepSeconds > 0.0 ? stepSeconds : 1.0 / 60.0;
            _maxFrame = maxFrameSeconds > 0.0 ? maxFrameSeconds : 0.25;   // NaN > 0 is false, so NaN falls back too
            _maxSteps = Math.Max(1, maxSteps);
        }

        public int Advance(double frameSeconds)
        {
            DroppedTime = false;
            // `> 0.0` is false for NaN, so a NaN frame time counts as zero instead of poisoning the accumulator
            _accumulator += frameSeconds > 0.0 ? Math.Min(frameSeconds, _maxFrame) : 0.0;
            int steps = 0;
            while (_accumulator >= _step && steps < _maxSteps)
            {
                _accumulator -= _step;
                steps++;
            }
            if (steps == _maxSteps && _accumulator >= _step)
            {
                _accumulator = 0.0;
                DroppedTime = true;
            }
            return steps;
        }
    }
}
