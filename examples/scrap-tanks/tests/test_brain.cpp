// ---------------------------------------------------------------------------
// test_brain.cpp
// Purpose : The raiders' behavior tree, one test per branch (SOP-14 step 6): FLANK with the gun
//           forward, FIRE when there is a shot, COVER while reloading in sight, RETREAT when hurt
//           (once per life) with healing out of sight.
// Usage   : python tools/dev.py test
// Notes   : One raider, placed by hand; core::think_raider is called directly.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include "core/EnemyBrain.hpp"
#include "core/Sim.hpp"
#include "core/Tactics.hpp"

using core::Sim;
using core::Tank;

namespace {

struct Setup {
    Sim sim{1};
    Tank* raider = nullptr;

    Setup() {
        for (int i = 0; i < 600 && sim.wave() == 0; ++i) sim.step({});
        for (Tank& t : sim.tanks()) {
            if (t.team != core::Team::Raider) continue;
            if (!raider) raider = &t;
            else t.alive = false;  // one raider is enough
        }
        sim.player().pos = {19.0, 21.0};
    }

    // In the open, 5 m from the player, nothing between them.
    void in_the_open() {
        raider->pos = {24.0, 22.0};
        raider->heading = core::kPi;
    }
};

}  // namespace

TEST_CASE("FLANK: out of sight, drive to a firing spot with the gun pointing forward") {
    Setup s;
    s.raider->pos = {19.0, 12.5};  // behind the center rock
    REQUIRE_FALSE(s.sim.clear_shot(s.raider->pos, s.sim.player().pos));
    core::think_raider(s.sim, *s.raider);
    CHECK(s.raider->intent == "FLANK");
    CHECK(s.raider->control.use_goal);
    CHECK(s.sim.clear_shot(s.raider->control.goal, s.sim.player().pos));
    CHECK_FALSE(s.raider->control.fire);
    const core::Vec2 forward = s.raider->pos + core::from_angle(s.raider->heading) * 5.0;
    CHECK(core::distance(s.raider->control.aim, forward) < 1e-9);  // the tell: no gun on the player yet
}

TEST_CASE("FIRE: a clear shot in range stops the raider and opens fire") {
    Setup s;
    s.in_the_open();
    core::think_raider(s.sim, *s.raider);
    CHECK(s.raider->intent == "FIRE");
    CHECK_FALSE(s.raider->control.use_goal);
    CHECK(s.raider->control.fire);
}

TEST_CASE("COVER: reloading in the player's sight sends it to a hidden spot") {
    Setup s;
    s.in_the_open();
    s.raider->reload = s.raider->spec->reload;  // just fired
    core::think_raider(s.sim, *s.raider);
    CHECK(s.raider->intent == "COVER");
    REQUIRE(s.raider->control.use_goal);
    CHECK(core::hidden_from_all(s.sim, s.raider->control.goal, {s.sim.player().pos}));
}

TEST_CASE("RETREAT: badly hurt, it hides and heals out of sight, once per life") {
    Setup s;
    s.in_the_open();
    s.raider->hp = 0.2 * s.raider->spec->max_hp;
    core::think_raider(s.sim, *s.raider);
    CHECK(s.raider->intent == "RETREAT");
    CHECK(s.raider->retreating);
    CHECK(core::hidden_from_all(s.sim, s.raider->control.goal, {s.sim.player().pos}));

    // Out of sight it heals
    s.raider->pos = {19.0, 12.5};
    const double before = s.raider->hp;
    s.raider->think = 1e9;
    s.sim.step({});
    CHECK(s.raider->hp > before);

    // Healed: back to fighting, and the retreat is used up
    s.raider->hp = 0.8 * s.raider->spec->max_hp;
    core::think_raider(s.sim, *s.raider);
    CHECK(s.raider->intent != "RETREAT");
    CHECK(s.raider->retreat_used);
    s.raider->hp = 0.2 * s.raider->spec->max_hp;
    s.in_the_open();
    core::think_raider(s.sim, *s.raider);
    CHECK(s.raider->intent == "FIRE");  // hurt again, but it fights to the end
}
