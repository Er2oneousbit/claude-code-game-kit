// ---------------------------------------------------------------------------
// MotorAccess.hpp
// Purpose : The two motor-access settings as pure logic (SOP-20, #166): access.timing_scale lengthens every timing
//           window (input buffer, coyote time, parry windows), access.hold_to_toggle turns a held action (guard,
//           sprint, aim) into press-once-on, press-again-off. No SDL.
// Usage   : buffer.set_window(core::scaled_window(core::kInputBufferWindow, shell.timing_scale()));
//           coyote.set_window(core::scaled_window(core::kCoyoteWindow, shell.timing_scale()));
//           core::HeldAction guard;
//           each tick: guarding = guard.update(shell.is_down("interact"), shell.access_flag("hold_to_toggle"));
// Notes   : The setting only ever lengthens a window: a scale under 1 (or not a number) counts as 1. HeldAction
//           reads the button's state every tick and finds the press itself, so it needs no event hook; a press
//           shorter than one fixed step can be missed, as with any polled input. Turning hold_to_toggle off while
//           toggled on hands the action back to the button (released: off).
//
// Pseudocode:
//   scaled_window(base, k) : base * (k >= 1 ? k : 1)
//   HeldAction.update(held, toggle):
//     toggle -> on a press (held now, not held last tick) flip active
//     hold   -> active = held
//     remember held; return active
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

namespace core {

// base seconds times the player's access.timing_scale (1 to 3 in the settings schema)
inline double scaled_window(double base_seconds, double timing_scale) {
    return base_seconds * (timing_scale >= 1.0 ? timing_scale : 1.0);   // NaN fails the test too
}

// A held action that honours access.hold_to_toggle.
class HeldAction {
public:
    // Call once per tick: held = a bound key or button is down now; toggle = access.hold_to_toggle.
    bool update(bool held, bool toggle) {
        if (toggle) {
            if (held && !was_held_) {
                active_ = !active_;
            }
        } else {
            active_ = held;
        }
        was_held_ = held;
        return active_;
    }

    bool active() const { return active_; }
    void reset() {
        active_ = false;
        was_held_ = false;
    }

private:
    bool active_ = false;
    bool was_held_ = false;
};

}  // namespace core

// {{FOOTER}}
