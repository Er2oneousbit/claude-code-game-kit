// ---------------------------------------------------------------------------
// test_frame_times.cpp
// Purpose : Unit tests for core::FrameTimes, the FRAME_TIMES line `dev.py smoke` reads (#90).
// Usage   : python tools/dev.py test
// Notes   : Nearest-rank percentiles, the same rule as every engine's FRAME_TIMES line.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include <string>
#include <vector>

#include "core/FrameTimes.hpp"

TEST_CASE("frame summary of 1..100 ms in any order") {
    std::vector<double> ms;
    for (int i = 100; i >= 1; --i) {
        ms.push_back(static_cast<double>(i));
    }
    const core::FrameSummary s = core::summarize_frames(ms);
    CHECK(s.frames == 100);
    CHECK(s.mean == doctest::Approx(50.5));
    CHECK(s.p95 == 95.0);
    CHECK(s.p99 == 99.0);
    CHECK(s.worst == 100.0);
}

TEST_CASE("one frame is every percentile") {
    const core::FrameSummary s = core::summarize_frames({7.5});
    CHECK(s.p95 == 7.5);
    CHECK(s.p99 == 7.5);
    CHECK(s.worst == 7.5);
}

TEST_CASE("the FRAME_TIMES line dev.py reads") {
    core::FrameTimes times;
    times.add(16.0);
    times.add(17.0);
    times.add(40.0);
    CHECK(times.line("software") == "FRAME_TIMES frames=3 mean=24.33 p95=40.00 p99=40.00 worst=40.00 mode=software");
}

TEST_CASE("no frames, no line") {
    CHECK(core::FrameTimes().line("software").empty());
}
