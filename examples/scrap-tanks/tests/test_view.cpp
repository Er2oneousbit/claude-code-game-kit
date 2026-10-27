// ---------------------------------------------------------------------------
// test_view.cpp
// Purpose : The camera math: world to screen and back, and the sprite row for each direction.
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include "core/View.hpp"

TEST_CASE("world to screen and back") {
    const core::Vec2 p{12.5, 7.25};
    const auto s = view::to_screen(p);
    const core::Vec2 back = view::to_world(s.x, s.y);
    CHECK(back.x == doctest::Approx(p.x));
    CHECK(back.y == doctest::Approx(p.y));
    CHECK(view::to_screen(p, 1.0).y < s.y);  // height lifts a point up the screen
}

TEST_CASE("sheet rows follow the rendered camera turns") {
    const double up = -core::kPi / 2;    // world angle pointing up the screen
    const double right = 0.0;
    const double down = core::kPi / 2;
    CHECK(view::sheet_row(up, 32) == 0);         // front up the screen in row 0
    CHECK(view::sheet_row(right, 32) == 8);      // right in row N/4
    CHECK(view::sheet_row(down, 32) == 16);
    CHECK(view::sheet_row(core::kPi, 32) == 24); // left
    CHECK(view::sheet_row(up, 32, core::kPi) == 16);  // a model that faces backward in its file
    CHECK(view::sheet_row(up + 0.01, 32) == 0);
    CHECK(view::sheet_row(up - 0.01, 32) == 0);  // wraps to 0, never 32
}
