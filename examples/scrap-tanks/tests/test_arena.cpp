// ---------------------------------------------------------------------------
// test_arena.cpp
// Purpose : Guards the arena data: start and spawns on open ground, every spawn reachable from the
//           start, every spot the spot pickers can return reachable too, cover mirrored left/right
//           (no safe side), enough standing spots.
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): picker spots have a path (Fable review)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include <cmath>

#include "core/Arena.hpp"
#include "core/Nav.hpp"
#include "core/Sim.hpp"
#include "core/Tactics.hpp"
#include "core/Tuning.hpp"

TEST_CASE("start and spawns are on open ground and connected") {
    const core::Arena& a = core::scrapyard();
    const core::NavGrid nav(a.bounds, a.blockers(), 0.5, tuning::kTankRadius + 0.05);
    CHECK(nav.walkable_at(a.player_start));
    for (const core::Vec2& s : a.spawns) {
        CHECK_MESSAGE(nav.walkable_at(s), "spawn " << s.x << "," << s.y);
        CHECK_FALSE(nav.find_path(a.player_start, s).empty());
    }
}

TEST_CASE("cover is mirrored left to right") {
    const core::Arena& a = core::scrapyard();
    const double mid = (a.bounds.min_x + a.bounds.max_x) / 2.0;
    for (const core::Cover& c : a.cover) {
        bool twin = false;
        for (const core::Cover& d : a.cover) {
            twin |= d.kind == c.kind && std::abs(d.shape.c.x - (2.0 * mid - c.shape.c.x)) < 1e-6 &&
                    std::abs(d.shape.c.y - c.shape.c.y) < 1e-6;
        }
        CHECK_MESSAGE(twin, core::cover_name(c.kind) << " at " << c.shape.c.x << "," << c.shape.c.y << " has no mirror twin");
    }
}

TEST_CASE("there are standing spots to choose from") {
    CHECK(core::scrapyard().spots.size() > 100);
}

TEST_CASE("reachable() agrees with find_path from the start for every spot") {
    const core::Arena& a = core::scrapyard();
    const core::NavGrid nav(a.bounds, a.blockers(), 0.5, tuning::kTankRadius + 0.05, a.player_start);
    int reachable = 0;
    for (const core::Vec2& s : a.spots) {
        const bool has_path = !nav.find_path(a.player_start, s).empty();
        CHECK_MESSAGE(nav.reachable(s) == has_path, "spot " << s.x << "," << s.y);
        reachable += has_path ? 1 : 0;
    }
    // Nearly all spots are on the main component (the known island near (19, 6.25) holds a few)
    CHECK(reachable > static_cast<int>(a.spots.size()) - 10);
}

TEST_CASE("every spot the pickers can return has a path from the player start") {
    const core::Sim sim(1);
    const core::Arena& a = sim.arena();
    // Pickers score by straight-line distance, so try them from every spot against threats all over the yard
    const std::vector<core::Vec2> threats{{19.0, 21.0}, {19.0, 2.0}, {4.0, 4.0}, {34.0, 4.0},
                                          {4.0, 20.0}, {34.0, 20.0}, {19.0, 12.0}};
    int picks = 0;
    for (size_t i = 0; i < a.spots.size(); i += 3) {
        const core::Vec2 from = a.spots[i];
        for (const core::Vec2& t : threats) {
            for (const auto& spot : {core::find_cover(sim, from, {t}), core::find_cover(sim, from, {t}, 2.0, 1.0),
                                     core::find_firing_spot(sim, from, t, tuning::kSightRange, {})}) {
                if (!spot) continue;
                ++picks;
                CHECK_MESSAGE(!sim.nav().find_path(a.player_start, *spot).empty(), "picked " << spot->x << "," << spot->y);
            }
        }
    }
    CHECK(picks > 100);
}
