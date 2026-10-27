// ---------------------------------------------------------------------------
// FixedTimestep.hpp
// Purpose : Accumulator for a fixed-step simulation loop. Pure logic, no SDL,
//           no clock. Time is injected, so tests are deterministic.
// Usage   : core::FixedTimestep step(1.0 / 60.0);
//           each frame: int n = step.advance(frame_seconds);
//                       for (int i = 0; i < n; ++i) game.update(step.step());
//                       alpha = step.alpha();   // for render interpolation later
// Notes   : Frame time is clamped (max_frame_) to avoid the "spiral of death"
//           after a debugger pause or window drag. Steps per frame are capped
//           too (max_steps_), leftover time is dropped with a warning flag.
//
// Pseudocode:
//   frame_dt = min(frame_dt, max_frame), and 0 for negative or NaN input
//   accumulator += frame_dt
//   steps = 0
//   while accumulator >= step and steps < max_steps: accumulator -= step; steps++
//   if steps hit the cap: accumulator = 0 and remember we dropped time
//   return steps
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// Updated : 2026-10-21 with Claude (Opus 5.5, claude-opus-5-5): NaN/negative frame time and non-positive
//           max_frame guarded (a negative max_frame was UB in std::clamp; NaN froze the accumulator)
// ---------------------------------------------------------------------------
#pragma once

#include <algorithm>

namespace core {

class FixedTimestep {
public:
    explicit FixedTimestep(double step_seconds, double max_frame_seconds = 0.25, int max_steps = 8)
        : step_(step_seconds > 0.0 ? step_seconds : 1.0 / 60.0),
          max_frame_(max_frame_seconds > 0.0 ? max_frame_seconds : 0.25),  // NaN > 0 is false, so NaN falls back too
          max_steps_(std::max(1, max_steps)) {}

    // Feed the real elapsed frame time. Returns how many fixed updates to run.
    int advance(double frame_seconds) {
        dropped_ = false;
        // `> 0.0` is false for NaN, so a NaN frame time counts as zero instead of poisoning the accumulator
        const double dt = frame_seconds > 0.0 ? std::min(frame_seconds, max_frame_) : 0.0;
        accumulator_ += dt;
        int steps = 0;
        while (accumulator_ >= step_ && steps < max_steps_) {
            accumulator_ -= step_;
            ++steps;
        }
        if (steps == max_steps_ && accumulator_ >= step_) {
            // We cannot keep up. Drop the backlog rather than spiral.
            accumulator_ = 0.0;
            dropped_ = true;
        }
        return steps;
    }

    double step() const { return step_; }
    // Fraction of a step left over, 0..1, for render interpolation.
    double alpha() const { return accumulator_ / step_; }
    // True if the last advance() had to drop time. Useful for a debug HUD.
    bool dropped_time() const { return dropped_; }

private:
    double step_;
    double max_frame_;
    int max_steps_;
    double accumulator_ = 0.0;
    bool dropped_ = false;
};

}  // namespace core
