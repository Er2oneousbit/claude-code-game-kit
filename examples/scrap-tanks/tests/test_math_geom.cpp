// ---------------------------------------------------------------------------
// test_math_geom.cpp
// Purpose : Angles, the seeded RNG, segment-vs-circle, line of sight and move-and-slide.
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include "core/Geom.hpp"
#include "core/Math.hpp"
#include "core/Rng.hpp"

using core::Circle;
using core::Vec2;

TEST_CASE("angles wrap and turn the short way") {
    CHECK(core::wrap_angle(3.0 * core::kPi) == doctest::Approx(core::kPi));
    CHECK(core::wrap_angle(-core::kPi / 2) == doctest::Approx(-core::kPi / 2));
    CHECK(core::turn_toward(3.0, -3.0, 0.1) == doctest::Approx(3.1));  // across +-pi, not the long way
    CHECK(core::turn_toward(0.0, 0.05, 0.1) == doctest::Approx(0.05));
    CHECK(core::angle_of(core::from_angle(1.0)) == doctest::Approx(1.0));
}

TEST_CASE("the RNG is seeded and repeatable") {
    core::Rng a(42);
    core::Rng b(42);
    core::Rng c(43);
    bool differs = false;
    for (int i = 0; i < 100; ++i) {
        const auto x = a.next();
        CHECK(x == b.next());
        differs |= x != c.next();
        const double u = a.uniform();
        b.uniform();
        CHECK(u >= 0.0);
        CHECK(u < 1.0);
    }
    CHECK(differs);
}

TEST_CASE("segment against circle") {
    const Circle rock{{0.0, 0.0}, 1.0};
    CHECK(core::segment_circle_t({-5, 0}, {5, 0}, rock) == doctest::Approx(0.4));
    CHECK(core::segment_circle_t({-5, 2}, {5, 2}, rock) < 0.0);         // passes beside it
    CHECK(core::segment_circle_t({-5, 1.5}, {5, 1.5}, rock, 0.6) >= 0.0);  // ... but not with a pad
    CHECK(core::segment_circle_t({-5, 0}, {-3, 0}, rock) < 0.0);        // stops short
}

TEST_CASE("line of sight is blocked by cover") {
    const std::vector<Circle> cover{{{0.0, 0.0}, 1.0}};
    CHECK_FALSE(core::line_of_sight({-5, 0}, {5, 0}, cover));
    CHECK(core::line_of_sight({-5, 3}, {5, 3}, cover));
}

TEST_CASE("move_circle slides along cover and stays in bounds") {
    const std::vector<Circle> cover{{{0.0, 0.0}, 1.0}};
    const core::Rect bounds{-10, -10, 10, 10};
    const Vec2 p = core::move_circle({-2.0, 0.2}, {0.5, 0.0}, 0.9, cover, bounds);
    CHECK(core::distance(p, {0.0, 0.0}) == doctest::Approx(1.9));      // pushed out to touch, not inside
    const Vec2 q = core::move_circle({9.0, 0.0}, {5.0, 0.0}, 0.9, cover, bounds);
    CHECK(q.x == doctest::Approx(9.1));
}
