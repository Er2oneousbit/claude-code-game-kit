// ---------------------------------------------------------------------------
// Feel.hpp
// Purpose : The small helpers SOP-18's recipe table builds on (#170, #164): impact (a hit confirm scaled by damage),
//           float_text (a damage number's rise, pop and fade) and the tracer's point history by distance
//           (trail_push, trail_shrink, trail_length). Pure logic, no SDL.
// Usage   : const core::Impact hit = core::impact(damage, enemy.max_hp);
//           hitstop.hit(hit.hitstop); shake.add_trauma(hit.trauma);
//           if (hit.flash && limiter.request(real_now)) flash();
//           const core::FloatText f = core::float_text(label.age);       // f.dy, f.scale, f.alpha, f.done
//           tracer = core::trail_push(tracer, bullet.x, bullet.y, spacing, length);   // every frame; after the hit:
//           tracer = core::trail_shrink(tracer, speed * dt);                          // until fewer than 2 points
// Notes   : No settings, no clock, no random numbers. Points are {x, y}, tail first, head last; each trail function
//           returns a new list. The defaults are SOP-18's starting points. Matches tools/golden_vectors.py,
//           checked against data/golden/juice.json ("impact", "float_text", "trail").
//
// Pseudocode:
//   impact: f = clamp(damage / full, 0, 1) (full <= 0: 1); nothing for damage <= 0; lerp hitstop, trauma; flash f >= at
//   float_text: u = t / life; dy = -rise * out_cubic(u); scale = out_back(t / pop); alpha = 1 - in_cubic(u)
//   trail_push: < 2 points: append; head spacing past the point before it: append; else move the head; cut to length
//   trail_shrink: cut the trail to (length - amount) from the tail
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): impact is the same with blood on or off; what a
//           hit leaves is the game's: blood, or (blood_enabled off) a neutral spark or dust (SOP-18 step 4, #171)
// ---------------------------------------------------------------------------
#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <utility>
#include <vector>

#include "core/Ease.hpp"

namespace core {

// ---- Tunables (SOP-18 step 4 starting points) ----
constexpr double kImpactHitstopMin = 0.03;   // s, the smallest hit
constexpr double kImpactHitstopMax = 0.1;    // s, a full hit (under Hitstop's 0.25 s cap)
constexpr double kImpactTraumaMin = 0.15;
constexpr double kImpactTraumaMax = 0.6;
constexpr double kImpactFlashAt = 0.5;       // a hit of at least half of `full` asks for a flash
constexpr double kFloatLife = 0.8;           // s
constexpr double kFloatRise = 24.0;          // px
constexpr double kFloatPop = 0.12;           // s
constexpr double kTrailSpacing = 6.0;        // px between kept points
constexpr double kTrailLength = 48.0;        // px, the longest trail
constexpr double kTrailEps = 1e-12;          // a cut this close to a point removes the point

struct Impact {
    double hitstop = 0.0;
    double trauma = 0.0;
    bool flash = false;
};

struct FloatText {
    double dy = 0.0;
    double scale = 1.0;
    double alpha = 1.0;
    bool done = false;
};

using TrailPoint = std::array<double, 2>;
using Trail = std::vector<TrailPoint>;

inline Impact impact(double damage, double full, double hitstop_min = kImpactHitstopMin,
                     double hitstop_max = kImpactHitstopMax, double trauma_min = kImpactTraumaMin,
                     double trauma_max = kImpactTraumaMax, double flash_at = kImpactFlashAt) {
    if (damage <= 0.0) {
        return {};
    }
    const double f = full <= 0.0 ? 1.0 : std::min(std::max(damage / full, 0.0), 1.0);
    return {hitstop_min + (hitstop_max - hitstop_min) * f, trauma_min + (trauma_max - trauma_min) * f, f >= flash_at};
}

inline FloatText float_text(double t, double life = kFloatLife, double rise = kFloatRise, double pop_s = kFloatPop) {
    const double u = life > 0.0 ? std::min(std::max(t / life, 0.0), 1.0) : 1.0;
    FloatText out;
    out.dy = -rise * ease(Ease::OutCubic, u);
    out.scale = pop_s > 0.0 ? ease(Ease::OutBack, t / pop_s) : 1.0;
    out.alpha = 1.0 - ease(Ease::InCubic, u);
    out.done = t >= life;
    return out;
}

inline double trail_segment(const TrailPoint& a, const TrailPoint& b) {
    const double dx = b[0] - a[0];
    const double dy = b[1] - a[1];
    return std::sqrt(dx * dx + dy * dy);
}

// Total length, tail to head (summed in order, as the reference does).
inline double trail_length(const Trail& points) {
    double total = 0.0;
    for (std::size_t i = 0; i + 1 < points.size(); ++i) {
        total += trail_segment(points[i], points[i + 1]);
    }
    return total;
}

inline Trail trail_trim_to(Trail pts, double keep) {
    double excess = trail_length(pts) - std::max(keep, 0.0);
    while (excess > kTrailEps && pts.size() > 1) {
        const double s = trail_segment(pts[0], pts[1]);
        if (s <= excess + kTrailEps) {
            pts.erase(pts.begin());
            excess -= s;
        } else {
            const double k = excess / s;
            pts[0] = {pts[0][0] + (pts[1][0] - pts[0][0]) * k, pts[0][1] + (pts[1][1] - pts[0][1]) * k};
            excess = 0.0;
        }
    }
    return pts;
}

inline Trail trail_push(Trail pts, double x, double y, double spacing = kTrailSpacing, double max_len = kTrailLength) {
    if (pts.size() < 2 || trail_segment(pts[pts.size() - 2], pts[pts.size() - 1]) >= spacing) {
        pts.push_back({x, y});
    } else {
        pts.back() = {x, y};
    }
    return trail_trim_to(std::move(pts), max_len);
}

inline Trail trail_shrink(const Trail& points, double amount) {
    return trail_trim_to(points, trail_length(points) - amount);
}

}  // namespace core

// {{FOOTER}}
