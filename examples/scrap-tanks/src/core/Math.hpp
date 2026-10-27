// ---------------------------------------------------------------------------
// Math.hpp
// Purpose : 2D vector math and angle helpers for the ground plane (meters).
// Usage   : core::Vec2 v{1, 2}; double a = core::angle_of(v); core::turn_toward(a, b, max_step)
// Notes   : World axes: x to the right, y toward the camera (down the screen). An angle a points
//           along (cos a, sin a), so a positive turn is clockwise on screen.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <algorithm>
#include <cmath>

namespace core {

constexpr double kPi = 3.14159265358979323846;

struct Vec2 {
    double x = 0.0;
    double y = 0.0;
};

inline Vec2 operator+(Vec2 a, Vec2 b) { return {a.x + b.x, a.y + b.y}; }
inline Vec2 operator-(Vec2 a, Vec2 b) { return {a.x - b.x, a.y - b.y}; }
inline Vec2 operator*(Vec2 a, double s) { return {a.x * s, a.y * s}; }
inline Vec2& operator+=(Vec2& a, Vec2 b) { a.x += b.x; a.y += b.y; return a; }

inline double dot(Vec2 a, Vec2 b) { return a.x * b.x + a.y * b.y; }
inline double length(Vec2 a) { return std::hypot(a.x, a.y); }
inline double distance(Vec2 a, Vec2 b) { return length(a - b); }

inline Vec2 normalized(Vec2 a) {
    const double l = length(a);
    return l < 1e-12 ? Vec2{0.0, 0.0} : Vec2{a.x / l, a.y / l};
}

inline Vec2 from_angle(double a) { return {std::cos(a), std::sin(a)}; }
inline double angle_of(Vec2 v) { return std::atan2(v.y, v.x); }

// Angle in (-pi, pi].
inline double wrap_angle(double a) {
    a = std::fmod(a + kPi, 2.0 * kPi);
    if (a <= 0.0) a += 2.0 * kPi;
    return a - kPi;
}

// Turn `from` toward `to` by at most max_step radians, the short way round.
inline double turn_toward(double from, double to, double max_step) {
    const double diff = wrap_angle(to - from);
    if (std::abs(diff) <= max_step) return to;
    return wrap_angle(from + (diff > 0.0 ? max_step : -max_step));
}

inline double clamp(double v, double lo, double hi) { return std::max(lo, std::min(hi, v)); }

}  // namespace core
