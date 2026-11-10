// ---------------------------------------------------------------------------
// InputBuffer.hpp
// Purpose : Remembers a button press for a short window, so a jump pressed just before landing (or an
//           attack pressed during the last one) still happens. Pure logic, no SDL.
// Usage   : core::InputBuffer buffer;                 // or InputBuffer(window_seconds)
//           on the key/pad event:  buffer.press("jump");
//           each tick:             buffer.update(dt);
//                                  if (on_floor && buffer.consume("jump")) start_jump();
// Notes   : Actions are the names from the bindings (Bindings.hpp). A press that ages past the window is
//           dropped; consume() takes it so it fires once. Matches tools/golden_vectors.py (InputBuffer),
//           checked against data/golden/juice.json. set_window() changes the window for the next press (the
//           player's access.timing_scale, core/MotorAccess.hpp); a press already buffered keeps what it has left.
//
// Pseudocode:
//   press(a)   : pending[a] = window
//   update(dt) : every pending press loses dt; at (about) 0 it is dropped
//   consume(a) : pending and still alive -> drop it, true; else false
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): set_window for access.timing_scale (#269)
// ---------------------------------------------------------------------------
#pragma once

#include <map>
#include <string>

namespace core {

// ---- Tunables ----
constexpr double kInputBufferWindow = 0.12;    // seconds a press stays usable
constexpr double kInputBufferEpsilon = 1e-12;  // what is left of a window after float rounding counts as expired

class InputBuffer {
public:
    explicit InputBuffer(double window_seconds = kInputBufferWindow) : window_(window_seconds) {}

    void press(const std::string& action) { pending_[action] = window_; }

    // A new window for the presses from now on (seconds); negative counts as 0.
    void set_window(double window_seconds) { window_ = window_seconds > 0.0 ? window_seconds : 0.0; }
    double window() const { return window_; }

    void update(double dt) {
        for (auto it = pending_.begin(); it != pending_.end();) {
            it->second -= dt;
            if (it->second <= kInputBufferEpsilon) {
                it = pending_.erase(it);
            } else {
                ++it;
            }
        }
    }

    // True once per buffered press of action.
    bool consume(const std::string& action) {
        const auto it = pending_.find(action);
        if (it != pending_.end() && it->second > 0.0) {
            pending_.erase(it);
            return true;
        }
        return false;
    }

    bool pending(const std::string& action) const { return pending_.count(action) != 0; }
    void clear() { pending_.clear(); }

private:
    double window_;
    std::map<std::string, double> pending_;  // action -> seconds left
};

}  // namespace core

// {{FOOTER}}
