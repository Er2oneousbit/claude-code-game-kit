// ---------------------------------------------------------------------------
// Shake.hpp
// Purpose : Trauma-based screen shake plus the smooth 1D value noise it samples. Pure logic, no SDL,
//           no clock: time comes in as dt, so tests are deterministic.
// Usage   : core::Shake shake;                       // or Shake(max_offset, max_angle, decay, frequency, seed)
//           on a hit:   shake.add_trauma(0.4);
//           each frame: auto o = shake.update(dt, core::effective_shake(settings));
//                       draw the world offset by (o.x, o.y) and rotated by o.angle (radians)
// Notes   : The shake is trauma squared, so small hits stay small. intensity is the player's shake setting
//           (0 with reduce motion, see Settings.hpp). Matches tools/golden_vectors.py (Shake, noise),
//           checked against data/golden/juice.json by tests/test_golden_vectors.cpp.
//           noise() uses Park-Miller integer arithmetic in 64-bit ints, so every port gets the same values.
//
// Pseudocode:
//   lattice(seed, i, ch) = Park-Miller twice on a mix of the inputs, mapped to (-1, 1]
//   noise(seed, t, ch)   = lattice values at floor(t) and floor(t) + 1 blended with smoothstep
//   add_trauma(a)        : trauma = clamp(trauma + a, 0, 1)
//   update(dt, k)        : time += dt; trauma -= decay * dt (not below 0); s = trauma^2 * k
//                          return max_offset * s * noise(ch 0), max_offset * s * noise(ch 1), max_angle * s * noise(ch 2)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace core {

// ---- Tunables (defaults; a game passes its own to the constructor) ----
constexpr double kShakeMaxOffset = 8.0;    // pixels at full trauma
constexpr double kShakeMaxAngle = 0.05;    // radians at full trauma
constexpr double kShakeDecay = 1.5;        // trauma lost per second
constexpr double kShakeFrequency = 15.0;   // noise lattice points per second
constexpr std::int64_t kShakeSeed = 1;

// Park-Miller "minimal standard" generator: modulus 2^31 - 1, multiplier 16807
constexpr std::int64_t kNoiseModulus = 2147483647;
constexpr std::int64_t kNoiseMultiplier = 16807;

// A value in (-1, 1] for integer lattice point i of channel ch.
inline double noise_lattice(std::int64_t seed, std::int64_t i, std::int64_t ch) {
    std::int64_t s = (seed * 7919 + i * 104729 + ch * 15485863) % kNoiseModulus;
    if (s < 0) {
        s += kNoiseModulus;  // C++ % keeps the sign of the left side; the reference (Python) never goes negative
    }
    if (s == 0) {
        s = 1;  // 0 is a fixed point of Park-Miller
    }
    s = (s * kNoiseMultiplier) % kNoiseModulus;
    s = (s * kNoiseMultiplier) % kNoiseModulus;
    return static_cast<double>(s) / static_cast<double>(kNoiseModulus - 1) * 2.0 - 1.0;
}

// Smooth 1D value noise in about -1..1. t >= 0 in normal use; NaN or infinite t gives 0 (no shake, no UB).
inline double noise(std::int64_t seed, double t, std::int64_t ch) {
    if (!std::isfinite(t)) {
        return 0.0;
    }
    const double fi = std::floor(t);
    const auto i = static_cast<std::int64_t>(fi);
    const double f = t - fi;
    const double a = noise_lattice(seed, i, ch);
    const double b = noise_lattice(seed, i + 1, ch);
    const double u = f * f * (3.0 - 2.0 * f);  // smoothstep
    return a + (b - a) * u;
}

struct ShakeOffset {
    double x = 0.0;
    double y = 0.0;
    double angle = 0.0;  // radians
};

class Shake {
public:
    explicit Shake(double max_offset = kShakeMaxOffset, double max_angle = kShakeMaxAngle,
                   double decay = kShakeDecay, double frequency = kShakeFrequency,
                   std::int64_t seed = kShakeSeed)
        : max_offset_(max_offset), max_angle_(max_angle), decay_(decay), frequency_(frequency), seed_(seed) {}

    // Adds (or with a negative amount removes) trauma, kept within 0..1.
    void add_trauma(double amount) { trauma_ = std::min(std::max(trauma_ + amount, 0.0), 1.0); }

    // Advances by dt seconds and returns this frame's offset. intensity scales it (the player's setting).
    ShakeOffset update(double dt, double intensity = 1.0) {
        time_ += dt;
        trauma_ = std::max(trauma_ - decay_ * dt, 0.0);
        const double s = trauma_ * trauma_ * intensity;
        const double t = time_ * frequency_;
        return {max_offset_ * s * noise(seed_, t, 0), max_offset_ * s * noise(seed_, t, 1),
                max_angle_ * s * noise(seed_, t, 2)};
    }

    double trauma() const { return trauma_; }

private:
    double max_offset_;
    double max_angle_;
    double decay_;
    double frequency_;
    std::int64_t seed_;
    double trauma_ = 0.0;
    double time_ = 0.0;
};

}  // namespace core
