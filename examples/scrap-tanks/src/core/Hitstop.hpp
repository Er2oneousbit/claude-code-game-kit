// ---------------------------------------------------------------------------
// Hitstop.hpp
// Purpose : Freezes game time for a moment on impact (hit pause). Pure logic, no SDL, no clock.
// Usage   : core::Hitstop hitstop;               // or Hitstop(max_seconds)
//           on a heavy hit: hitstop.hit(0.06);
//           each tick:      const double game_dt = hitstop.scaled_dt(dt);   // 0 while frozen
//                           world.update(game_dt);  ui.update(dt);           // menus and audio keep real time
// Notes   : Overlapping hits keep the longest freeze, never longer than max_seconds. A frame that ends the
//           freeze returns only the unfrozen rest of its dt. Matches tools/golden_vectors.py (Hitstop),
//           checked against data/golden/juice.json.
//
// Pseudocode:
//   hit(d)         : remaining = min(max(remaining, d), max_seconds)
//   scaled_dt(dt)  : nothing frozen -> dt; else used = min(remaining, dt); remaining -= used; return dt - used
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <algorithm>

namespace core {

// ---- Tunables ----
constexpr double kHitstopMaxSeconds = 0.25;  // the longest freeze any stack of hits can cause

class Hitstop {
public:
    explicit Hitstop(double max_seconds = kHitstopMaxSeconds) : max_(max_seconds) {}

    // Starts (or extends) a freeze of duration seconds.
    void hit(double duration) { remaining_ = std::min(std::max(remaining_, duration), max_); }

    // The game's delta for this frame: the frozen part of real_dt is removed.
    double scaled_dt(double real_dt) {
        if (remaining_ <= 0.0) {
            return real_dt;
        }
        const double used = std::min(remaining_, real_dt);
        remaining_ -= used;
        return real_dt - used;
    }

    double remaining() const { return remaining_; }
    bool frozen() const { return remaining_ > 0.0; }

private:
    double max_;
    double remaining_ = 0.0;
};

}  // namespace core
