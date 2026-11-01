// ---------------------------------------------------------------------------
// Spring.hpp
// Purpose : A damped spring for squash-and-stretch recovery, UI pops and wobble, plus the volume-keeping
//           squash scale. Pure logic, no SDL.
// Usage   : core::Spring spring;              // or Spring(frequency_hz, damping)
//           on landing: spring.x = 0.3;      // or spring.v += 4.0 for a kick
//           each tick:  const auto s = core::squash(spring.update(dt));
//                       draw the sprite scaled by (s.sx, s.sy), anchored at its feet
// Notes   : Semi-implicit Euler (velocity first), stable at game step sizes. damping 1 = no overshoot,
//           below 1 wobbles. squash() keeps the area: sx * sy = 1. Matches tools/golden_vectors.py (Spring,
//           squash), checked against data/golden/juice.json.
//
// Pseudocode:
//   w = 2 * pi * frequency
//   a = -w^2 * (x - target) - 2 * damping * w * v ;  v += a * dt ;  x += v * dt
//   squash(a): a = max(a, -0.9) ; return (1 + a, 1 / (1 + a))
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <algorithm>

namespace core {

// ---- Tunables ----
constexpr double kSpringFrequency = 4.0;    // oscillations per second
constexpr double kSpringDamping = 0.5;      // 0 = rings forever, 1 = critically damped
constexpr double kSquashMin = -0.9;         // the most stretch squash() allows (keeps 1 + a above 0)
constexpr double kSpringPi = 3.14159265358979323846;

class Spring {
public:
    explicit Spring(double frequency = kSpringFrequency, double damping = kSpringDamping)
        : frequency(frequency), damping(damping) {}

    // Advances the spring by dt seconds and returns the new position.
    double update(double dt) {
        const double w = 2.0 * kSpringPi * frequency;
        const double a = -w * w * (x - target) - 2.0 * damping * w * v;
        v += a * dt;
        x += v * dt;
        return x;
    }

    // Plain fields on purpose: games poke x, v and target directly (a kick, a new rest point).
    double frequency;
    double damping;
    double x = 0.0;
    double v = 0.0;
    double target = 0.0;
};

struct SquashScale {
    double sx = 1.0;
    double sy = 1.0;
};

// Volume-keeping scale: amount > 0 widens and flattens, < 0 stretches tall. Clamped above kSquashMin.
inline SquashScale squash(double amount) {
    const double a = std::max(amount, kSquashMin);
    return {1.0 + a, 1.0 / (1.0 + a)};
}

}  // namespace core
