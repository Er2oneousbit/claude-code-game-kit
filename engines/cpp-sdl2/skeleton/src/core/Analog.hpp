// ---------------------------------------------------------------------------
// Analog.hpp
// Purpose : Analog input shaping (#274): the left stick and the triggers as the game reads them, after the player's
//           deadzone and invert_y, so a racer steers by how far the stick leans and brakes by how far a trigger is
//           in; the move direction that adds the held move_* actions to the stick; and the hysteresis that turns a
//           stick axis into d-pad presses for the menus. The same rules as the Bevy shell's logic/analog.rs.
// Usage   : const core::analog::Vec2 s = core::analog::stick(raw_x, raw_y, deadzone, invert_y);
//           const double gas = core::analog::trigger(raw_r2);
//           const core::analog::Vec2 dir = core::analog::move_vector(held_dir, s);   // length 0..1
//           on = core::analog::hysteresis(lean, on, std::max(kStickOn, deadzone), kStickOff);
// Notes   : Header-only, no SDL. The stick deadzone is radial (the length of the vector, not each axis), and what is
//           left is rescaled to 0..1, so a stick just past the deadzone gives a small value instead of jumping to the
//           deadzone's size; the direction never changes. Axes follow SDL: x grows right, y grows DOWN (the game's
//           screen space), so a stick pushed up gives a negative y; invert_y flips y. Triggers have their own small
//           fixed deadzone: input.deadzone is the "Stick deadzone" setting, and a trigger resting at 0.1 would
//           otherwise lose a fifth of its travel. NaN and infinities (a broken driver) count as 0.
//           Everything here lives in core::analog, not core: games keep their own code in core:: too, and a game's
//           own core::Vec2 (a math header) must not collide with the kit's. Convert at the edge if the game has one:
//           const core::analog::Vec2 s = shell.stick(); core::Vec2 v{s.x, s.y};
//
// Pseudocode:
//   stick(x, y, dz, inv): y = -y if inv -> len = |(x, y)| -> len <= dz: (0, 0)
//     -> scale = min((len - dz) / (1 - dz), 1) / len -> (x * scale, y * scale)
//   trigger(v, dz): v = clamp(v, 0, 1) -> v <= dz: 0 -> (v - dz) / (1 - dz)
//   move_vector(held, stick): held + stick, cut to length 1
//   hysteresis(lean, was, on, off): was ? lean > off : lean > on
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): moved into core::analog (stick, trigger and
//           hysteresis without the old prefixes, as the Bevy shell's analog::stick / analog::trigger), so a game's
//           own core::Vec2 still compiles
// ---------------------------------------------------------------------------
#pragma once

#include <algorithm>
#include <cmath>

namespace core::analog {

// ---- Tunables ----
constexpr double kTriggerDeadzone = 0.05;  // trigger travel ignored at rest (0 to 1)
constexpr double kMaxDeadzone = 0.95;      // the largest deadzone accepted (settings clamp to 0.9); keeps the rescale finite
constexpr double kStickHoldMin = 0.2;      // a raw lean that holds a move_* action, never below the player's deadzone
constexpr double kAxisMax = 32767.0;       // SDL's axis range: -32768..32767 (sticks), 0..32767 (triggers)

struct Vec2 {
    double x = 0.0;
    double y = 0.0;
    double length() const { return std::sqrt(x * x + y * y); }
};

inline double finite_or_zero(double v) {
    return std::isfinite(v) ? v : 0.0;
}

// An SDL axis value as -1..1 (sticks) or 0..1 (triggers).
inline double axis_from_raw(int raw) {
    return std::clamp(static_cast<double>(raw) / kAxisMax, -1.0, 1.0);
}

// The stick after the radial deadzone and invert_y: each axis -1..1, the vector's length 0..1.
inline Vec2 stick(double x, double y, double deadzone, bool invert_y) {
    x = finite_or_zero(x);
    y = finite_or_zero(y);
    if (invert_y) {
        y = -y;
    }
    const double dz = std::clamp(finite_or_zero(deadzone), 0.0, kMaxDeadzone);
    const double len = std::sqrt(x * x + y * y);
    if (len <= dz || len == 0.0) {
        return {};
    }
    const double scale = std::min((len - dz) / (1.0 - dz), 1.0) / len;
    return {x * scale, y * scale};
}

// A trigger (0 at rest, 1 fully in) after its deadzone, rescaled to 0..1.
inline double trigger(double value, double deadzone = kTriggerDeadzone) {
    const double v = std::clamp(finite_or_zero(value), 0.0, 1.0);
    const double dz = std::clamp(finite_or_zero(deadzone), 0.0, kMaxDeadzone);
    return v <= dz ? 0.0 : (v - dz) / (1.0 - dz);
}

// The direction the player asks for: the held move_* actions (a unit or zero vector) plus the shaped stick, cut to
// length 1, so a keyboard gives full speed and a half-leaned stick half speed.
inline Vec2 move_vector(Vec2 held, Vec2 stick) {
    Vec2 v{held.x + stick.x, held.y + stick.y};
    const double len = v.length();
    if (len > 1.0) {
        v.x /= len;
        v.y /= len;
    }
    return v;
}

// One stick direction as a d-pad button with hysteresis: it goes on past `on` and off again only below `off`, so a
// stick resting near the threshold does not flicker. lean is the axis value towards that direction (>= 0 = towards).
inline bool hysteresis(double lean, bool was_on, double on, double off) {
    lean = finite_or_zero(lean);
    return was_on ? lean > off : lean > on;
}

}  // namespace core::analog

// {{FOOTER}}
