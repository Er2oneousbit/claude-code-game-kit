// ---------------------------------------------------------------------------
// test_motor_access.cpp
// Purpose : Tests the motor-access logic (#166, #269): access.timing_scale lengthens the input buffer and the coyote
//           window, and access.hold_to_toggle turns a held action into a toggle (core/MotorAccess.hpp).
// Usage   : python tools/dev.py test     (ctest lists one test per TEST_CASE)
// Notes   : Pure logic, no SDL. Times are stepped at 60 Hz like the game's fixed step.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include <limits>

#include "core/CoyoteTimer.hpp"
#include "core/InputBuffer.hpp"
#include "core/MotorAccess.hpp"

namespace {

constexpr double kStep = 1.0 / 60.0;

// A jump pressed `age` seconds before landing: does the buffer still hold it?
bool buffered_after(double timing_scale, double age) {
    core::InputBuffer buffer;
    buffer.set_window(core::scaled_window(core::kInputBufferWindow, timing_scale));
    buffer.press("jump");
    buffer.update(age);
    return buffer.consume("jump");
}

// Walked off a ledge `age` seconds ago: can the player still jump?
bool coyote_after(double timing_scale, double age) {
    core::CoyoteTimer coyote;
    coyote.set_window(core::scaled_window(core::kCoyoteWindow, timing_scale));
    coyote.update(kStep, true);        // on the floor: the window starts full
    coyote.update(age, false);
    return coyote.can_jump();
}

}  // namespace

TEST_CASE("timing_scale multiplies a window and never shortens it") {
    CHECK(core::scaled_window(0.12, 1.0) == doctest::Approx(0.12));
    CHECK(core::scaled_window(0.12, 2.5) == doctest::Approx(0.30));
    CHECK(core::scaled_window(0.1, 3.0) == doctest::Approx(0.30));
    CHECK(core::scaled_window(0.12, 0.5) == doctest::Approx(0.12));    // under 1: the base window
    CHECK(core::scaled_window(0.12, std::numeric_limits<double>::quiet_NaN()) == doctest::Approx(0.12));
}

TEST_CASE("a longer timing_scale keeps a buffered press alive longer") {
    CHECK(buffered_after(1.0, 0.10));
    CHECK_FALSE(buffered_after(1.0, 0.20));    // past 0.12 s
    CHECK(buffered_after(2.0, 0.20));          // 0.24 s window
    CHECK_FALSE(buffered_after(2.0, 0.30));
    core::InputBuffer buffer;
    buffer.press("jump");                      // a press already buffered keeps what it has left
    buffer.set_window(1.0);
    buffer.update(0.2);
    CHECK_FALSE(buffer.consume("jump"));
}

TEST_CASE("a longer timing_scale stretches coyote time") {
    CHECK(coyote_after(1.0, 0.05));
    CHECK_FALSE(coyote_after(1.0, 0.15));      // past 0.1 s
    CHECK(coyote_after(2.0, 0.15));            // 0.2 s window
    CHECK(coyote_after(3.0, 0.25));
    CHECK_FALSE(coyote_after(3.0, 0.35));
    core::CoyoteTimer coyote;
    coyote.set_window(-1.0);                   // bad data counts as no coyote time
    CHECK(coyote.window() == 0.0);
}

TEST_CASE("a held action follows the button without hold_to_toggle") {
    core::HeldAction guard;
    CHECK_FALSE(guard.update(false, false));
    CHECK(guard.update(true, false));
    CHECK(guard.update(true, false));
    CHECK_FALSE(guard.update(false, false));
}

TEST_CASE("hold_to_toggle: one press turns the action on, the next turns it off") {
    core::HeldAction guard;
    CHECK(guard.update(true, true));           // press: on
    CHECK(guard.update(true, true));           // still held: no second flip
    CHECK(guard.update(false, true));          // released: stays on
    CHECK(guard.update(false, true));
    CHECK_FALSE(guard.update(true, true));     // second press: off
    CHECK_FALSE(guard.update(false, true));
    CHECK(guard.update(true, true));           // and on again
    // switching the setting off while toggled on hands the action back to the button
    CHECK_FALSE(guard.update(false, false));
    guard.reset();
    CHECK_FALSE(guard.active());
}
