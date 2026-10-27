// ---------------------------------------------------------------------------
// View.hpp
// Purpose : The camera math between the ground plane (meters) and the screen (logical pixels), and
//           which row of a rotation sprite sheet faces a given direction. No SDL: unit tested.
// Usage   : auto s = view::to_screen(pos, height);  int row = view::sheet_row(angle, 32, 0.0);
// Notes   : Matches tools/make_sprites.py: 55 degree camera, hull sheets 3.6 m per 112 px cell.
//           A sheet's row r was rendered with the camera turned r * 360/N degrees counter-clockwise, so
//           the model's front points up the screen in row 0 and to the right in row N/4. yaw_offset
//           is pi for models whose front faces the other way (the Tower Defense Kit turrets).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <cmath>

#include "core/Math.hpp"

namespace view {

constexpr double kPixelsPerMeter = 112.0 / 3.6;  // hull sheets: --size 112 --world-size 3.6
constexpr double kElevation = 55.0 * core::kPi / 180.0;
inline const double kDepth = std::sin(kElevation);   // ground y is squashed by this on screen
inline const double kHeight = std::cos(kElevation);  // a meter of height rises this many meters on screen
constexpr double kOriginX = 49.0;                     // screen position of world (0, 0)
constexpr double kOriginY = 86.0;

struct Point {
    double x = 0.0;
    double y = 0.0;
};

inline Point to_screen(core::Vec2 p, double height = 0.0) {
    return {kOriginX + p.x * kPixelsPerMeter, kOriginY + (p.y * kDepth - height * kHeight) * kPixelsPerMeter};
}

// Screen point (on the ground) back to the world: where the mouse aims.
inline core::Vec2 to_world(double sx, double sy) {
    return {(sx - kOriginX) / kPixelsPerMeter, (sy - kOriginY) / (kPixelsPerMeter * kDepth)};
}

// Row of an N-direction sheet that shows a model facing world angle `angle` (radians, x right, y down).
inline int sheet_row(double angle, int directions, double yaw_offset = 0.0) {
    // The front of row r points along world (sin a, -cos a) with a = r * 2pi/N, so a = atan2(cos, -sin).
    const double a = std::atan2(std::cos(angle), -std::sin(angle)) + yaw_offset;
    const double step = 2.0 * core::kPi / directions;
    const int r = static_cast<int>(std::lround(a / step)) % directions;
    return r < 0 ? r + directions : r;
}

}  // namespace view
