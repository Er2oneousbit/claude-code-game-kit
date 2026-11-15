// ---------------------------------------------------------------------------
// test_window_fit.cpp
// Purpose : Unit tests for core::fit_window (#308): a windowed size fits the usable screen with its frame and is
//           centred there, as Godot's screen_get_usable_rect does.
// Usage   : python tools/dev.py test
// Notes   : Seen on a real window before this: the window kept its old position and ran past the screen's edge.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include "core/WindowFit.hpp"

using core::fit_window;

TEST_CASE("window fit: a size that fits is kept and centred in the usable area") {
    const core::WindowPlace p = fit_window(1600, 900, {0, 0, 1920, 1152}, {31, 8, 8, 8});
    CHECK(p.w == 1600);
    CHECK(p.h == 900);
    CHECK(p.x == 8 + (1904 - 1600) / 2);
    CHECK(p.y == 31 + (1113 - 900) / 2);
}

TEST_CASE("window fit: a size larger than the screen shrinks so the frame stays on screen") {
    const core::WindowPlace p = fit_window(1920, 1080, {0, 0, 1920, 1152}, {31, 8, 8, 8});
    CHECK(p.w == 1904);
    CHECK(p.h == 1080);
    CHECK(p.y - 31 >= 0);
    CHECK(p.y + p.h + 8 <= 1152);
    CHECK(p.x - 8 >= 0);
    CHECK(p.x + p.w + 8 <= 1920);
}

TEST_CASE("window fit: a second screen's offset is kept") {
    const core::WindowPlace p = fit_window(800, 600, {1920, 0, 1280, 1024}, {0, 0, 0, 0});
    CHECK(p.x == 1920 + 240);
    CHECK(p.y == 212);
}
