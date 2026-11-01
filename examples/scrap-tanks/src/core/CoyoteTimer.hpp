// ---------------------------------------------------------------------------
// CoyoteTimer.hpp
// Purpose : Grace window to still jump after walking off a ledge ("coyote time"). Pure logic, no SDL.
// Usage   : core::CoyoteTimer coyote;          // or CoyoteTimer(window_seconds)
//           each tick:       coyote.update(dt, on_floor);
//           on jump pressed: if (coyote.can_jump()) { start_jump(); coyote.consume(); }
// Notes   : A window of 0 means "no coyote time", not "no jumping": grounded jumps always work. A landing
//           re-arms a consumed jump. Same rules as the Godot and web CoyoteTimer; matches
//           tools/golden_vectors.py (Coyote), checked against data/golden/juice.json.
//           Pairs with InputBuffer: buffer the press, then consume it when can_jump() turns true.
//
// Pseudocode:
//   on floor  -> (just landed: consumed = false) grounded, time_left = window
//   off floor -> not grounded, time_left = max(time_left - dt, 0)
//   can_jump  -> not consumed and (grounded or time_left > 0)
//   consume   -> consumed until the next landing, time_left = 0
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <algorithm>

namespace core {

// ---- Tunables ----
constexpr double kCoyoteWindow = 0.1;  // seconds after leaving the floor that a jump still works

class CoyoteTimer {
public:
    // A negative window (bad tuning data) counts as 0.
    explicit CoyoteTimer(double window_seconds = kCoyoteWindow) : window_(std::max(window_seconds, 0.0)) {}

    void update(double dt, bool on_floor) {
        if (on_floor) {
            if (!grounded_) {
                consumed_ = false;  // landed: the next jump is available again
            }
            grounded_ = true;
            time_left_ = window_;
        } else {
            grounded_ = false;
            time_left_ = std::max(time_left_ - dt, 0.0);
        }
    }

    bool can_jump() const { return !consumed_ && (grounded_ || time_left_ > 0.0); }

    void consume() {
        consumed_ = true;
        time_left_ = 0.0;
    }

    double time_left() const { return time_left_; }

private:
    double window_;
    double time_left_ = 0.0;
    bool grounded_ = false;
    bool consumed_ = false;
};

}  // namespace core
