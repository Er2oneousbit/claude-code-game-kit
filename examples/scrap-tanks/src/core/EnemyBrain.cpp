// ---------------------------------------------------------------------------
// EnemyBrain.cpp
// Purpose : The raiders' behavior tree and its conditions and actions (see EnemyBrain.hpp, ADR 0002).
// Usage   : core::think_raider(sim, tank) from core::Sim::step
// Notes   : The tree, top to bottom = priority:
//             RETREAT  hurt (below kRetreatBelow, until back to kRecoverTo; once per life): hide far away, heal
//             COVER    reloading AND the player can see me: hide close by
//             FIRE     I can see the player, in range, clear shot: stop, lead the target, shoot
//             FLANK    otherwise: drive to a spot with a shot, spread out from the other raiders, gun forward
//           A chosen spot is kept while it still works (kSpotKeep), so raiders do not dither.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "core/EnemyBrain.hpp"

#include <cmath>
#include <string>
#include <vector>

#include "core/Bt.hpp"
#include "core/Sim.hpp"
#include "core/Tactics.hpp"

namespace core {

namespace {

using bt::Status;

constexpr double kSpotKeep = 2.0;     // s a chosen spot stays chosen while it still works
constexpr double kReloadingAbove = 0.6;  // fraction of the reload left that counts as "reloading"

struct Ctx {
    Sim& sim;
    Tank& me;
    const Tank& player;
};

std::vector<Vec2> other_spots(const Ctx& c) {
    std::vector<Vec2> out;
    for (const Tank& t : c.sim.tanks()) {
        if (t.team == Team::Raider && t.alive && t.id != c.me.id && t.has_spot) out.push_back(t.spot);
    }
    return out;
}

void go(Ctx& c, Vec2 goal) {
    c.me.control.use_goal = true;
    c.me.control.goal = goal;
}

void hold(Ctx& c) {
    c.me.control.use_goal = false;
    c.me.control.throttle = 0.0;
    c.me.control.turn = 0.0;
}

void pick_spot(Ctx& c, Vec2 spot) {
    c.me.has_spot = true;
    c.me.spot = spot;
    c.me.spot_age = 0.0;
}

bool keep_spot(const Ctx& c, const char* action) {
    return c.me.has_spot && c.me.intent == action && c.me.spot_age < kSpotKeep;
}

// ---- conditions ----
bool hurt(Ctx& c) {
    const double f = c.me.hp / c.me.spec->max_hp;
    if (c.me.retreating && f >= tuning::kRecoverTo) {
        c.me.retreating = false;
        c.me.retreat_used = true;  // once per life: after that it fights to the end
    }
    return c.me.retreating || (!c.me.retreat_used && f < tuning::kRetreatBelow);
}

bool reloading(Ctx& c) { return c.me.reload > kReloadingAbove * c.me.spec->reload; }

bool player_sees_me(Ctx& c) { return c.sim.sees(c.player.pos, c.me.pos); }

bool has_shot(Ctx& c) {
    return distance(c.me.pos, c.player.pos) <= c.me.spec->range * 1.1 && c.sim.sees(c.me.pos, c.player.pos) &&
           c.sim.clear_shot(c.me.pos, c.player.pos);
}

// ---- actions ----
Status hide(Ctx& c, const char* name, double min_dist, double far_weight) {
    const std::vector<Vec2> threat{c.player.pos};
    if (!(keep_spot(c, name) && hidden_from_all(c.sim, c.me.spot, threat))) {
        auto spot = find_cover(c.sim, c.me.pos, threat, min_dist, far_weight);
        if (!spot) spot = find_cover(c.sim, c.me.pos, threat, 2.0, far_weight);
        if (!spot) return Status::Failure;
        pick_spot(c, *spot);
    }
    go(c, c.me.spot);
    c.me.control.aim = c.me.pos + from_angle(c.me.heading) * 5.0;  // gun forward while running
    c.me.control.fire = false;
    return Status::Running;
}

Status retreat(Ctx& c) {
    c.me.retreating = true;
    return hide(c, "RETREAT", 8.0, 0.6);
}

Status cover(Ctx& c) { return hide(c, "COVER", 4.0, 0.0); }

Status fire(Ctx& c) {
    hold(c);
    c.me.has_spot = false;
    c.me.control.aim = lead(c.me.pos, c.player.pos, c.player.vel, c.me.spec->shell_speed);
    c.me.control.fire = true;
    c.me.control.aim_tolerance = tuning::kAimTolerance;
    return Status::Running;
}

Status flank(Ctx& c) {
    const double range = c.me.spec->range;
    // Keep the spot while it still has a shot; arrived there without one (a crate edge in the way): pick again
    const bool arrived = distance(c.me.pos, c.me.spot) < 1.2;
    const bool still_good = keep_spot(c, "FLANK") && c.sim.clear_shot(c.me.spot, c.player.pos) &&
                            distance(c.me.spot, c.player.pos) <= range &&
                            !(arrived && !c.sim.clear_shot(c.me.pos, c.player.pos));
    if (!still_good) {
        std::vector<Vec2> avoid = other_spots(c);
        if (arrived) avoid.push_back(c.me.pos);  // not this spot again
        const auto spot = find_firing_spot(c.sim, c.me.pos, c.player.pos, range, avoid);
        pick_spot(c, spot ? *spot : c.player.pos);
    }
    go(c, c.me.spot);
    // Turret points where it drives: the swing toward the player happens in FIRE, where a player in
    // cover can see it coming and shoot first (pillar 1 and 2: the defender's advantage, and a tell).
    c.me.control.aim = c.me.pos + from_angle(c.me.heading) * 5.0;
    c.me.control.fire = false;
    return Status::Running;
}

bt::NodePtr<Ctx> build_tree() {
    using namespace bt;
    return selector<Ctx>("root", children<Ctx>(
        sequence<Ctx>("retreat", children<Ctx>(condition<Ctx>("hurt", hurt), action<Ctx>("RETREAT", retreat))),
        sequence<Ctx>("cover", children<Ctx>(condition<Ctx>("reloading", reloading),
                                             condition<Ctx>("player sees me", player_sees_me),
                                             action<Ctx>("COVER", cover))),
        sequence<Ctx>("fire", children<Ctx>(condition<Ctx>("has shot", has_shot), action<Ctx>("FIRE", fire))),
        action<Ctx>("FLANK", flank)));
}

}  // namespace

void think_raider(Sim& sim, Tank& me) {
    static const bt::NodePtr<Ctx> tree = build_tree();
    Ctx ctx{sim, me, sim.player()};
    std::string active;
    tree->tick(ctx, active);
    me.intent = active;
    me.spot_age += tuning::kThinkEvery;
}

const char* raider_tree_text() {
    return "selector root\n"
           "  sequence retreat: hurt -> RETREAT\n"
           "  sequence cover:   reloading, player sees me -> COVER\n"
           "  sequence fire:    has shot -> FIRE\n"
           "  FLANK\n";
}

}  // namespace core
