// ---------------------------------------------------------------------------
// test_nav.cpp
// Purpose : Grid A* on tiny hand-made yards (SOP-14 step 6): straight line, around cover, sealed
//           goal, start equals goal, goal inside cover.
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include "core/Nav.hpp"

using core::Circle;
using core::NavGrid;
using core::Vec2;

namespace {
const core::Rect kYard{0, 0, 20, 20};
}

TEST_CASE("open ground: one straight leg") {
    const NavGrid nav(kYard, {}, 0.5, 0.9);
    const auto path = nav.find_path({3, 10}, {17, 11});
    REQUIRE(path.size() == 1);
    CHECK(path[0].x == doctest::Approx(17.0));
}

TEST_CASE("cover in the way: a path around it with every leg clear") {
    const std::vector<Circle> cover{{{10, 10}, 3.0}};
    const NavGrid nav(kYard, cover, 0.5, 0.9);
    const Vec2 from{3, 10};
    const auto path = nav.find_path(from, {17, 10});
    REQUIRE(path.size() > 1);
    Vec2 a = from;
    for (const Vec2& p : path) {
        CHECK(core::line_of_sight(a, p, nav.grown()));
        a = p;
    }
}

TEST_CASE("a sealed goal has no path") {
    std::vector<Circle> ring;
    for (int k = 0; k < 12; ++k) ring.push_back({Vec2{10, 10} + core::from_angle(k * core::kPi / 6) * 3.0, 1.0});
    const NavGrid nav(kYard, ring, 0.5, 0.9);
    CHECK(nav.find_path({2, 2}, {10, 10}).empty());
}

TEST_CASE("start equals goal: just the goal") {
    const NavGrid nav(kYard, {}, 0.5, 0.9);
    const auto path = nav.find_path({5.0, 5.0}, {5.1, 5.1});
    REQUIRE(path.size() == 1);
    CHECK(path[0].x == doctest::Approx(5.1));
}

TEST_CASE("a goal inside cover snaps to the nearest open spot") {
    const std::vector<Circle> cover{{{10, 10}, 1.0}};
    const NavGrid nav(kYard, cover, 0.5, 0.9);
    const auto path = nav.find_path({2, 10}, {10, 10});
    REQUIRE_FALSE(path.empty());
    CHECK(core::distance(path.back(), {10, 10}) >= 1.9 - 0.36);  // outside the grown circle (half-cell slack)
}
