// ---------------------------------------------------------------------------
// test_analog.cpp
// Purpose : Tests the analog input shaping (#274, core/Analog.hpp): the stick's radial, rescaled deadzone and
//           invert_y, the triggers' own deadzone, the move direction that adds held keys to the stick, and the
//           menus' d-pad hysteresis. The same cases as the Bevy shell's logic/analog.rs tests.
// Usage   : python tools/dev.py test     (ctest lists one test per TEST_CASE)
// Notes   : Pure logic, no SDL. SDL's axes: +y is down, so "up" on a stick is a negative y. Everything is in
//           core::analog, so a game's own core::Vec2 compiles next to it (the first test proves it).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include <cmath>
#include <limits>

#include "core/Analog.hpp"

namespace {

bool close(core::analog::Vec2 a, double x, double y) {
    return std::abs(a.x - x) < 1e-6 && std::abs(a.y - y) < 1e-6;
}

}  // namespace

// A game's own core::Vec2 (a math header in src/core, as games often have) next to the kit's analog header. The
// unnamed namespace keeps it out of other files; if Analog.hpp declared core::Vec2 again, the test below would stop
// compiling (ambiguous name).
namespace core {
namespace {
struct Vec2 {
    int game_owned = 1;
};
}  // namespace
}  // namespace core

TEST_CASE("the kit's analog types leave the name core::Vec2 to the game") {
    const core::Vec2 mine{};
    CHECK(mine.game_owned == 1);
}

TEST_CASE("the stick is still inside the deadzone and rescales from zero past it") {
    CHECK(close(core::analog::stick(0.15, 0.1, 0.2, false), 0.0, 0.0));
    const core::analog::Vec2 just_past = core::analog::stick(0.21, 0.0, 0.2, false);
    CHECK(just_past.x > 0.0);
    CHECK(just_past.x < 0.02);                     // a small push, never a jump to the deadzone's 0.2
    CHECK(close(core::analog::stick(0.6, 0.0, 0.2, false), 0.5, 0.0));
    CHECK(close(core::analog::stick(1.0, 0.0, 0.2, false), 1.0, 0.0));
    CHECK(close(core::analog::stick(-0.3, 0.4, 0.0, false), -0.3, 0.4));   // no deadzone: the raw value
}

TEST_CASE("the stick's deadzone is radial: a diagonal counts by its length, not per axis") {
    // each axis 0.15 is inside a 0.2 deadzone on its own, but the vector is 0.21 long: it moves
    const core::analog::Vec2 d = core::analog::stick(0.15, 0.15, 0.2, false);
    CHECK(d.x > 0.0);
    CHECK(d.x == doctest::Approx(d.y));
    // past full deflection the length is cut to 1 and the direction kept
    const core::analog::Vec2 corner = core::analog::stick(1.0, 1.0, 0.2, false);
    CHECK(corner.length() == doctest::Approx(1.0));
    CHECK(corner.x == doctest::Approx(corner.y));
}

TEST_CASE("invert_y flips only the vertical axis") {
    CHECK(close(core::analog::stick(0.0, -1.0, 0.2, true), 0.0, 1.0));
    CHECK(close(core::analog::stick(1.0, 0.0, 0.2, true), 1.0, 0.0));
}

TEST_CASE("triggers rescale past their own deadzone and ignore bad values") {
    CHECK(core::analog::trigger(0.04) == 0.0);
    CHECK(core::analog::trigger(1.0) == 1.0);
    CHECK(core::analog::trigger(0.525) == doctest::Approx(0.5));
    CHECK(core::analog::trigger(-0.5, 0.0) == 0.0);                       // a trigger never goes negative
    CHECK(core::analog::trigger(std::numeric_limits<double>::quiet_NaN(), 0.0) == 0.0);
    CHECK(close(core::analog::stick(std::numeric_limits<double>::quiet_NaN(), 1.0, 0.0, false), 0.0, 1.0));
    CHECK(close(core::analog::stick(0.5, 0.0, 5.0, false), 0.0, 0.0));     // a silly deadzone is clamped, not inf
}

TEST_CASE("SDL's raw axis values map to -1..1 and 0..1") {
    CHECK(core::analog::axis_from_raw(32767) == doctest::Approx(1.0));
    CHECK(core::analog::axis_from_raw(-32768) == doctest::Approx(-1.0));         // clamped, not -1.00003
    CHECK(core::analog::axis_from_raw(0) == 0.0);
}

TEST_CASE("the move direction adds held keys to the stick and never exceeds length 1") {
    CHECK(close(core::analog::move_vector({1.0, 0.0}, {}), 1.0, 0.0));            // a key: full speed
    CHECK(close(core::analog::move_vector({}, {0.5, 0.0}), 0.5, 0.0));            // a half lean: half speed
    CHECK(core::analog::move_vector({1.0, 0.0}, {1.0, 0.0}).length() == doctest::Approx(1.0));
    const core::analog::Vec2 both = core::analog::move_vector({1.0, 0.0}, {0.0, -1.0});
    CHECK(both.length() == doctest::Approx(1.0));
    CHECK(both.x == doctest::Approx(-both.y));
}

TEST_CASE("the menus' d-pad from the stick has hysteresis") {
    const double on = 0.5;
    const double off = 0.3;
    bool held = core::analog::hysteresis(0.4, false, on, off);
    CHECK_FALSE(held);                             // not past on yet
    held = core::analog::hysteresis(0.6, held, on, off);
    CHECK(held);
    held = core::analog::hysteresis(0.4, held, on, off);
    CHECK(held);                                   // between off and on: stays on (no flicker)
    held = core::analog::hysteresis(0.2, held, on, off);
    CHECK_FALSE(held);
}

// {{FOOTER}}
