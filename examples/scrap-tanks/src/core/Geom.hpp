// ---------------------------------------------------------------------------
// Geom.hpp
// Purpose : Collision and sight on the ground plane: circles (tanks, crates, rocks, trees),
//           line of sight, swept shells, and move-and-slide.
// Usage   : core::line_of_sight(a, b, obstacles); core::move_circle(pos, delta, r, obstacles, bounds)
// Notes   : Everything that blocks is a circle seen from above. `pad` grows the circles, so a
//           sight line or a path can keep a margin (a shell's size, a tank's half width).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <vector>

#include "core/Math.hpp"

namespace core {

struct Circle {
    Vec2 c;
    double r = 0.0;
};

struct Rect {
    double min_x = 0.0;
    double min_y = 0.0;
    double max_x = 0.0;
    double max_y = 0.0;
};

// Fraction t in [0, 1] where segment a->b first touches the circle grown by pad, or -1 if it misses.
inline double segment_circle_t(Vec2 a, Vec2 b, const Circle& c, double pad = 0.0) {
    const Vec2 d = b - a;
    const Vec2 f = a - c.c;
    const double r = c.r + pad;
    const double A = dot(d, d);
    const double C = dot(f, f) - r * r;
    if (C <= 0.0) return 0.0;  // starts inside
    if (A < 1e-12) return -1.0;
    const double B = 2.0 * dot(f, d);
    const double disc = B * B - 4.0 * A * C;
    if (disc < 0.0) return -1.0;
    const double t = (-B - std::sqrt(disc)) / (2.0 * A);
    return (t >= 0.0 && t <= 1.0) ? t : -1.0;
}

inline bool line_of_sight(Vec2 a, Vec2 b, const std::vector<Circle>& blockers, double pad = 0.0) {
    for (const Circle& c : blockers) {
        if (segment_circle_t(a, b, c, pad) >= 0.0) return false;
    }
    return true;
}

inline bool inside(const Rect& r, Vec2 p, double margin = 0.0) {
    return p.x >= r.min_x + margin && p.x <= r.max_x - margin && p.y >= r.min_y + margin && p.y <= r.max_y - margin;
}

// Push a circle (center p, radius r) out of one blocker. Unchanged if not touching.
inline Vec2 push_out(Vec2 p, double r, const Circle& c) {
    const Vec2 d = p - c.c;
    const double dist = length(d);
    const double need = r + c.r;
    if (dist >= need) return p;
    const Vec2 dir = dist > 1e-9 ? d * (1.0 / dist) : Vec2{1.0, 0.0};
    return c.c + dir * need;
}

// Move by delta, slide along blockers, stay inside bounds.
inline Vec2 move_circle(Vec2 p, Vec2 delta, double r, const std::vector<Circle>& blockers, const Rect& bounds) {
    Vec2 q = p + delta;
    for (int pass = 0; pass < 2; ++pass) {
        for (const Circle& c : blockers) q = push_out(q, r, c);
    }
    q.x = clamp(q.x, bounds.min_x + r, bounds.max_x - r);
    q.y = clamp(q.y, bounds.min_y + r, bounds.max_y - r);
    return q;
}

}  // namespace core
