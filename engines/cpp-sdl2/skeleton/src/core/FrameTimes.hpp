// ---------------------------------------------------------------------------
// FrameTimes.hpp
// Purpose : Frame-time sampling for `dev.py smoke` (#90): main.cpp records how long each smoke frame took and prints
//           one line at the end of the run, which dev.py reports and checks against --frame-budget:
//             FRAME_TIMES frames=N mean=MS p95=MS p99=MS worst=MS mode=software
// Usage   : core::FrameTimes times;  times.add(ms);  ...  std::cout << times.line("software") << "\n";
//           core::summarize_frames(samples) is a plain function (tests/test_frame_times.cpp).
// Notes   : Header-only, no SDL: the caller measures (SDL_GetPerformanceCounter in main.cpp). Smoke frames run
//           unthrottled under SDL's dummy video driver with the software renderer, so the numbers are the CPU work
//           of a frame including drawing in software: "software", not a GPU budget. Percentiles are nearest-rank,
//           the same rule as every engine's FRAME_TIMES line.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <string>
#include <vector>

namespace core {

struct FrameSummary {
    std::size_t frames = 0;
    double mean = 0.0;
    double p95 = 0.0;
    double p99 = 0.0;
    double worst = 0.0;
};

// Nearest rank: the smallest sample with at least q of the samples at or below it. `sorted` must not be empty.
inline double frame_rank(const std::vector<double>& sorted, double q) {
    const auto n = static_cast<double>(sorted.size());
    const auto i = static_cast<std::size_t>(std::max(0.0, std::ceil(q * n) - 1.0));
    return sorted[std::min(i, sorted.size() - 1)];
}

// Mean, p95, p99 and worst of these frame times (all zero when there are none).
inline FrameSummary summarize_frames(std::vector<double> ms) {
    FrameSummary s;
    s.frames = ms.size();
    if (ms.empty()) {
        return s;
    }
    std::sort(ms.begin(), ms.end());
    double total = 0.0;
    for (double v : ms) {
        total += v;
    }
    s.mean = total / static_cast<double>(ms.size());
    s.p95 = frame_rank(ms, 0.95);
    s.p99 = frame_rank(ms, 0.99);
    s.worst = ms.back();
    return s;
}

// The FRAME_TIMES line ("" when there are no frames).
inline std::string frame_times_line(const FrameSummary& s, const char* mode) {
    if (s.frames == 0) {
        return "";
    }
    char buf[192];
    std::snprintf(buf, sizeof buf, "FRAME_TIMES frames=%zu mean=%.2f p95=%.2f p99=%.2f worst=%.2f mode=%s", s.frames,
                  s.mean, s.p95, s.p99, s.worst, mode);
    return buf;
}

// The samples of one run.
class FrameTimes {
public:
    void add(double ms) { samples_.push_back(ms); }
    std::size_t size() const { return samples_.size(); }
    std::string line(const char* mode) const { return frame_times_line(summarize_frames(samples_), mode); }

private:
    std::vector<double> samples_;
};

}  // namespace core

// {{FOOTER}}
