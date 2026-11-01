// ---------------------------------------------------------------------------
// FlashLimiter.hpp
// Purpose : Photosensitivity guard: allows at most max_flashes full-screen flashes in any window of
//           window_seconds (three per second by default). Pure logic, no SDL, time injected.
// Usage   : core::FlashLimiter flashes;          // or FlashLimiter(max_flashes, window_seconds)
//           before a white-out or hit flash:
//             if (!settings["access"]["flash_limit"].get<bool>() || flashes.request(now_seconds)) flash();
//             else use a gentler cue (a tint, a shake, a sound)
// Notes   : request() records the flash when it allows it, so ask only when the flash will really be drawn.
//           now is any steadily rising clock in seconds (game time is fine). Matches tools/golden_vectors.py
//           (FlashLimiter), checked against data/golden/juice.json.
//
// Pseudocode:
//   request(now): forget flashes at or before now - window
//                 fewer than max left -> remember now, true ; else false
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <algorithm>
#include <cstddef>
#include <vector>

namespace core {

// ---- Tunables ----
constexpr int kFlashMax = 3;              // flashes allowed ...
constexpr double kFlashWindow = 1.0;      // ... in any window this long (seconds)

class FlashLimiter {
public:
    explicit FlashLimiter(int max_flashes = kFlashMax, double window_seconds = kFlashWindow)
        : max_(max_flashes), window_(window_seconds) {}

    // True (and recorded) when a flash at time now stays within the limit.
    bool request(double now) {
        const double cutoff = now - window_;
        times_.erase(std::remove_if(times_.begin(), times_.end(), [cutoff](double t) { return !(t > cutoff); }),
                     times_.end());
        if (static_cast<long long>(times_.size()) < max_) {
            times_.push_back(now);
            return true;
        }
        return false;
    }

    void reset() { times_.clear(); }

private:
    int max_;
    double window_;
    std::vector<double> times_;  // allowed flashes still inside the window
};

}  // namespace core

// {{FOOTER}}
