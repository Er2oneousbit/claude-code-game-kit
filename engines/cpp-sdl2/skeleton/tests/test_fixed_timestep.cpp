// ---------------------------------------------------------------------------
// test_fixed_timestep.cpp
// Purpose : Unit tests for core::FixedTimestep. Also the pattern to copy for
//           new engine-free tests (name tests after behavior, inject time).
// Usage   : python tools/dev.py test
// Notes   : Each guard is checked by its effect on the NEXT advance(), so deleting the guard fails a test.
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include <limits>

#include "core/FixedTimestep.hpp"

TEST_CASE("runs exactly one step when frame time equals the step") {
    core::FixedTimestep ts(1.0 / 60.0);
    CHECK(ts.advance(1.0 / 60.0) == 1);
}

TEST_CASE("accumulates fractional frames across calls") {
    core::FixedTimestep ts(0.1);
    CHECK(ts.advance(0.06) == 0);  // 0.06 banked
    CHECK(ts.advance(0.06) == 1);  // 0.12 total, one step, 0.02 left
    CHECK(ts.alpha() == doctest::Approx(0.2));
}

TEST_CASE("runs multiple steps for a long frame (within the clamp)") {
    // max_frame raised to 1.0 so the default 0.25 s clamp does not apply here.
    core::FixedTimestep ts(0.1, /*max_frame*/ 1.0);
    CHECK(ts.advance(0.35) == 3);
}

TEST_CASE("clamps a huge frame time (debugger pause) instead of spiraling") {
    core::FixedTimestep ts(0.1, /*max_frame*/ 0.25, /*max_steps*/ 8);
    CHECK(ts.advance(30.0) == 2);  // clamped to 0.25 => 2 steps, 0.05 left
}

TEST_CASE("caps steps per frame and drops backlog") {
    core::FixedTimestep ts(0.01, /*max_frame*/ 1.0, /*max_steps*/ 4);
    CHECK(ts.advance(0.5) == 4);
    CHECK(ts.dropped_time());
    CHECK(ts.advance(0.0) == 0);   // backlog was dropped, nothing left
}

TEST_CASE("negative frame time is treated as zero") {
    core::FixedTimestep ts(0.1);
    CHECK(ts.advance(-5.0) == 0);
    CHECK(ts.advance(0.1) == 1);   // a negative accumulator would swallow this step
    CHECK(ts.alpha() == doctest::Approx(0.0));
}

TEST_CASE("NaN frame time is ignored instead of freezing the simulation") {
    core::FixedTimestep ts(0.1);
    CHECK(ts.advance(std::numeric_limits<double>::quiet_NaN()) == 0);
    CHECK(ts.advance(0.1) == 1);
}

TEST_CASE("non-positive max_frame falls back to 0.25 s") {
    core::FixedTimestep ts(0.1, /*max_frame*/ -1.0);
    CHECK(ts.advance(0.1) == 1);   // with max_frame <= 0 no step would ever run
    CHECK(ts.advance(30.0) == 2);  // clamped to the 0.25 s default
}

TEST_CASE("dropped flag clears on the next advance") {
    core::FixedTimestep ts(0.01, /*max_frame*/ 1.0, /*max_steps*/ 4);
    ts.advance(0.5);
    CHECK(ts.dropped_time());
    ts.advance(0.01);
    CHECK_FALSE(ts.dropped_time());
}

TEST_CASE("zero max_steps still runs one step per frame") {
    core::FixedTimestep ts(0.1, /*max_frame*/ 1.0, /*max_steps*/ 0);
    CHECK(ts.advance(0.1) == 1);
}

TEST_CASE("non-positive step falls back to 60 Hz") {
    core::FixedTimestep ts(0.0);
    CHECK(ts.step() == doctest::Approx(1.0 / 60.0));
}

// {{FOOTER}}
