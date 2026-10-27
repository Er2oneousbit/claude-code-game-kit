// ---------------------------------------------------------------------------
// test_regressions.cpp
// Purpose : Regression tests for defects found by a Fable review (2026-10-26). Each case failed on the
//           code before its fix: shells that reach cover first still hitting the tank behind it, and a
//           tank sent to a goal with no nav path standing still.
// Usage   : python tools/dev.py test      (or build/debug/bin/Debug/unit_tests.exe -tc="regression*")
// Notes   : Ported from the review's proof tests (its "BUG ..." cases). The island itself stays: grid
//           rounding seals a few walkable cells near (19, 6.25); test_arena.cpp checks the spot pickers
//           never hand those spots out, and the last case here checks a tank still moves if sent there.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5), from proof tests by Claude (Fable 5.1,
//           claude-fable-5-1)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include <algorithm>
#include <vector>

#include "core/Sim.hpp"

using core::Circle;
using core::Control;
using core::EventType;
using core::Sim;
using core::Tank;
using core::Vec2;

namespace {

Sim with_first_wave(bool god = false) {
    Sim sim(1, god);
    for (int i = 0; i < 600 && sim.wave() == 0; ++i) sim.step({});
    return sim;
}

Tank& first_raider(Sim& sim) {
    for (Tank& t : sim.tanks()) {
        if (t.team == core::Team::Raider && t.alive) return t;
    }
    FAIL("no raider");
    return sim.tanks().front();
}

// Keep `keep` as the only live raider and stop every raider's brain, so the test drives the scene
void freeze(Sim& sim, Tank& keep) {
    for (Tank& t : sim.tanks()) {
        if (t.team != core::Team::Raider) continue;
        if (&t != &keep) t.alive = false;
        t.think = 1e9;
        t.control = Control{};
        t.control.aim = t.pos;
        t.speed = 0.0;
    }
}

bool has(const std::vector<core::Event>& evs, EventType type) {
    return std::any_of(evs.begin(), evs.end(), [type](const core::Event& e) { return e.type == type; });
}

Control aim_and_fire(Vec2 at) {
    Control c;
    c.aim = at;
    c.fire = true;
    c.aim_tolerance = 0.0;  // fire only when the turret is exactly on the aim point (turn_toward snaps)
    return c;
}

// A raider touching the first crate of the lower-left wall from below, the player far left on a line
// whose padded shell path enters the crate (x = 7.352) before the tank (x = 7.542)
const Circle kCrate{{8.0, 17.0}, core::kCrateR};
constexpr double kLineY = 17.95;

bool crate_first_shot_hits(double player_x) {
    Sim sim = with_first_wave(true);
    Tank& r = first_raider(sim);
    r.pos = {8.0, 18.95};
    r.heading = 0.0;
    sim.player().pos = {player_x, kLineY};
    sim.player().turret = 0.0;
    sim.player().heading = 0.0;
    const Vec2 far{100.0, kLineY};
    const Vec2 muzzle = sim.player().pos + Vec2{tuning::kMuzzle, 0.0};
    const double t_crate = core::segment_circle_t(muzzle, far, kCrate, tuning::kShellRadius);
    const double t_tank = core::segment_circle_t(muzzle, far, {r.pos, tuning::kTankRadius}, tuning::kShellRadius);
    REQUIRE(t_crate >= 0.0);
    REQUIRE(t_tank >= 0.0);
    REQUIRE_MESSAGE(t_crate < t_tank, "the crate is in front of the tank on this line");
    std::vector<core::Event> evs;
    for (int i = 0; i < 90; ++i) {
        freeze(sim, r);
        for (const auto& e : sim.step(aim_and_fire(far))) evs.push_back(e);
    }
    REQUIRE(has(evs, EventType::Fire));
    return has(evs, EventType::Hit) || r.hp < r.spec->max_hp;
}

}  // namespace

TEST_CASE("regression: a shell that reaches cover before the tank does not damage the tank") {
    CHECK_FALSE(crate_first_shot_hits(3.12));
}

TEST_CASE("regression: crate-first shells never land, whatever the step phase") {
    // 34 cm of shooter offsets = just over one shell step (0.333 m), so every phase of the step is tried
    int landed = 0;
    for (int k = 0; k < 34; ++k) landed += crate_first_shot_hits(3.0 + k * 0.01) ? 1 : 0;
    MESSAGE("crate-first shells that hit the tank: " << landed << "/34");
    CHECK(landed == 0);
}

TEST_CASE("regression: a tank sent to a goal with no nav path still drives toward it") {
    Sim sim = with_first_wave(true);
    Tank& r = first_raider(sim);
    const Vec2 spawn{19.0, 2.0};  // the top-center spawn
    r.pos = spawn;
    r.heading = core::kPi / 2;
    const Vec2 island{18.991, 6.091};  // ring spot of the crate at (17.4, 4.5), on the nav island
    REQUIRE(sim.nav().walkable_at(island));
    REQUIRE(sim.nav().find_path(r.pos, island).empty());
    CHECK_FALSE(sim.nav().reachable(island));
    freeze(sim, r);  // once: freezing every step would also zero the speed every step
    for (int i = 0; i < 300; ++i) {
        r.think = 1e9;
        r.control.use_goal = true;
        r.control.goal = island;
        sim.step({});
    }
    // Straight at the goal it meets the 1.2 m gap between the upper crates (a tank is 1.9 m) and stops
    // there, at about y = 3.4: progress instead of standing at the spawn, though not on the island
    MESSAGE("after 5 s the raider is at " << r.pos.x << "," << r.pos.y);
    CHECK(core::distance(r.pos, spawn) > 1.0);
    CHECK(core::distance(r.pos, island) < core::distance(spawn, island) - 1.0);
}
