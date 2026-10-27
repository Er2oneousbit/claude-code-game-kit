// ---------------------------------------------------------------------------
// Rng.hpp
// Purpose : The project's one random number generator: seeded, fast, the same on every compiler.
// Usage   : core::Rng rng(seed); rng.uniform(); rng.range(a, b); rng.below(n)
// Notes   : xorshift64* (Vigna). std::mt19937 is portable too, but std::uniform_*_distribution
//           is not (results differ between standard libraries), so replays would break across
//           MSVC, GCC and Clang. Same seed, same run, everywhere.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <cstdint>

namespace core {

class Rng {
public:
    explicit Rng(std::uint64_t seed) : state_(seed ? seed : 0x9E3779B97F4A7C15ull) {}

    std::uint64_t next() {
        state_ ^= state_ >> 12;
        state_ ^= state_ << 25;
        state_ ^= state_ >> 27;
        return state_ * 0x2545F4914F6CDD1Dull;
    }

    // [0, 1)
    double uniform() { return static_cast<double>(next() >> 11) * (1.0 / 9007199254740992.0); }
    double range(double lo, double hi) { return lo + (hi - lo) * uniform(); }
    // [0, n), n > 0
    int below(int n) { return static_cast<int>(next() % static_cast<std::uint64_t>(n)); }

private:
    std::uint64_t state_;
};

}  // namespace core
