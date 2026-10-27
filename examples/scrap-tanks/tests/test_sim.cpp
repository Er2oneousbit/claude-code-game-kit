// ---------------------------------------------------------------------------
// test_sim.cpp
// Purpose : The fight's rules: waves, shells stopped by cover, damage, scrap drops and repairs,
//           god mode, winning and losing, and determinism (same seed, same fight).
// Usage   : python tools/dev.py test
// Notes   : Raiders are frozen where a test needs a still target (their think timer pushed out and
//           their control cleared every step).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include <algorithm>

#include "core/Bot.hpp"
#include "core/Sim.hpp"

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

// Keep one raider where the test put it and drop the rest.
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

std::vector<core::Event> run(Sim& sim, Tank& keep, const Control& c, int steps) {
    std::vector<core::Event> all;
    for (int i = 0; i < steps; ++i) {
        freeze(sim, keep);
        for (const auto& e : sim.step(c)) all.push_back(e);
    }
    return all;
}

Control aim_and_fire(Vec2 at) {
    Control c;
    c.aim = at;
    c.fire = true;
    c.aim_tolerance = 0.02;
    return c;
}

}  // namespace

TEST_CASE("the first wave arrives after a short pause with three scouts") {
    Sim sim(1);
    sim.step({});
    CHECK(sim.wave() == 0);
    Sim started = with_first_wave();
    CHECK(started.wave() == 1);
    CHECK(started.raiders_alive() == tuning::kWaves[0].scouts + tuning::kWaves[0].heavies);
}

TEST_CASE("cover stops shells; a clear shot hits") {
    Sim sim = with_first_wave(true);
    Tank& r = first_raider(sim);
    r.pos = {19.0, 12.5};                 // behind the center rock (19, 15.5) as seen from below
    sim.player().pos = {19.0, 19.5};
    REQUIRE_FALSE(sim.clear_shot(sim.player().pos, r.pos));
    auto evs = run(sim, r, aim_and_fire(r.pos), 120);
    CHECK_FALSE(has(evs, EventType::Hit));
    CHECK(r.hp == doctest::Approx(r.spec->max_hp));

    sim.player().pos = {24.0, 13.0};      // now in the open, beside the rock
    REQUIRE(sim.clear_shot(sim.player().pos, r.pos));
    evs = run(sim, r, aim_and_fire(r.pos), 90);
    CHECK(has(evs, EventType::Hit));
    CHECK(r.hp < r.spec->max_hp);
}

TEST_CASE("a destroyed raider drops scrap; scrap repairs the player once") {
    Sim sim = with_first_wave(true);
    Tank& r = first_raider(sim);
    r.pos = {24.0, 21.0};
    r.hp = 1.0;
    sim.player().pos = {19.0, 21.0};
    const auto evs = run(sim, r, aim_and_fire(r.pos), 90);
    REQUIRE(has(evs, EventType::TankDestroyed));
    REQUIRE(sim.scrap().size() == 1);

    sim.player().hp = 50.0;
    sim.player().pos = sim.scrap().front().pos;
    const auto picked = sim.step({});
    CHECK(has(picked, EventType::Pickup));
    CHECK(sim.player().hp == doctest::Approx(50.0 + tuning::kScrapHeal));
    CHECK(sim.scrap().front().taken);
}

TEST_CASE("god mode takes hits but no damage") {
    Sim sim = with_first_wave(true);
    Tank& r = first_raider(sim);
    r.pos = {24.0, 21.0};
    sim.player().pos = {19.0, 21.0};
    std::vector<core::Event> evs;
    for (int i = 0; i < 240; ++i) {
        freeze(sim, r);
        r.control = aim_and_fire(sim.player().pos);
        for (const auto& e : sim.step({})) evs.push_back(e);
    }
    CHECK(has(evs, EventType::Hit));
    CHECK(sim.player().hp == doctest::Approx(tuning::kPlayer.max_hp));
}

TEST_CASE("clearing every wave wins; losing the player ends the run") {
    Sim sim(3, true);
    std::vector<core::Event> evs;
    for (int i = 0; i < 60 * 60 && sim.outcome() == core::Outcome::Playing; ++i) {
        for (Tank& t : sim.tanks()) {
            if (t.team == core::Team::Raider) t.alive = false;
        }
        for (const auto& e : sim.step({})) evs.push_back(e);
    }
    CHECK(sim.outcome() == core::Outcome::Won);
    CHECK(sim.wave() == Sim::waves_total());
    CHECK(has(evs, EventType::RunWon));

    Sim lost(3);
    lost.player().alive = false;
    CHECK(has(lost.step({}), EventType::PlayerDestroyed));
    CHECK(lost.outcome() == core::Outcome::Destroyed);
    CHECK(lost.step({}).empty());  // nothing happens after the end
}

TEST_CASE("same seed, same fight") {
    Sim a(7);
    Sim b(7);
    core::Bot ba(core::BotMode::Skilled);
    core::Bot bb(core::BotMode::Skilled);
    for (int i = 0; i < 60 * 20; ++i) {
        a.step(ba.think(a));
        b.step(bb.think(b));
    }
    REQUIRE(a.tanks().size() == b.tanks().size());
    for (size_t i = 0; i < a.tanks().size(); ++i) {
        CHECK(a.tanks()[i].pos.x == b.tanks()[i].pos.x);
        CHECK(a.tanks()[i].pos.y == b.tanks()[i].pos.y);
        CHECK(a.tanks()[i].hp == b.tanks()[i].hp);
    }
}
