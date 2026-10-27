// ---------------------------------------------------------------------------
// Bot.cpp
// Purpose : Implementation of the autoplay bots (see Bot.hpp).
// Usage   : game::Game with `-- --autoplay skilled|reckless`, and tests/test_scenario.cpp
// Notes   : The bots may read raider positions directly; a human reads the same from the screen.
//
// Pseudocode (skilled, re-planned every kReplan seconds):
//   target = the weakest raider I can hit (lead the shot, fire when aimed)
//   no target: pre-aim at the nearest raider
//   if no raiders: collect scrap if hurt, else wait
//   elif hurt and some scrap is hidden from every raider: go get it
//   else exposure = raiders that can see a spot:
//     nobody sees me: HOLD, gun pre-aimed at the nearest raider (flankers drive into it)
//     one sees me and my gun is loaded: DUEL (our gun reloads more than twice as fast)
//     otherwise: HIDE at the spot within kMoveRange with the lowest exposure * kExposureCost + distance
//   hunt: one raider left, or all of them retreating, and nobody sees me: go to a spot with a shot at the weakest
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "core/Bot.hpp"

#include <algorithm>
#include <limits>
#include <vector>

#include "core/Tactics.hpp"

namespace core {

namespace {
constexpr double kReplan = 0.25;        // s between movement decisions
constexpr double kHurt = 0.5;           // fraction of max hp that sends the skilled bot for scrap
constexpr double kReloadingAbove = 0.2; // s of reload left that counts as "reloading"
constexpr double kHuntRange = 12.0;     // m: the hunt looks for a shot from this far
constexpr double kMoveRange = 12.0;      // m: how far the bot looks for a less exposed spot
constexpr double kExposureCost = 10.0;   // m of driving worth one raider fewer seeing you

std::vector<const Tank*> raiders(const Sim& sim) {
    std::vector<const Tank*> out;
    for (const Tank& t : sim.tanks()) {
        if (t.team == Team::Raider && t.alive) out.push_back(&t);
    }
    return out;
}
}  // namespace

Control Bot::think(Sim& sim) {
    return mode_ == BotMode::Skilled ? skilled(sim) : reckless(sim);
}

Control Bot::reckless(Sim& sim) {
    const Tank& me = sim.player();
    Control c;
    const Tank* nearest = nullptr;
    for (const Tank* r : raiders(sim)) {
        if (!nearest || distance(r->pos, me.pos) < distance(nearest->pos, me.pos)) nearest = r;
    }
    if (!nearest) {
        c.aim = me.pos + from_angle(me.turret);
        return c;
    }
    reason_ = "CHARGE";
    c.use_goal = true;
    c.goal = nearest->pos;
    c.aim = nearest->pos;
    c.fire = true;
    c.aim_tolerance = tuning::kAimTolerance;
    return c;
}

Control Bot::skilled(Sim& sim) {
    const Tank& me = sim.player();
    const auto foes = raiders(sim);
    std::vector<Vec2> threats;
    std::vector<const Tank*> seeing_me;
    const Tank* target = nullptr;
    for (const Tank* r : foes) {
        threats.push_back(r->pos);
        if (sim.can_hit(r->pos, me.pos)) seeing_me.push_back(r);
        // The weakest raider I can hit (tried "the one in FIRE first": it switched targets mid-duel and lost more)
        if (sim.can_hit(me.pos, r->pos) && (!target || r->hp < target->hp)) target = r;
    }

    Control c;
    if (target) {
        c.aim = lead(me.pos, target->pos, target->vel, me.spec->shell_speed);
        c.fire = true;
        c.aim_tolerance = tuning::kAimTolerance;
    } else if (!foes.empty()) {
        const Tank* nearest = foes.front();
        for (const Tank* r : foes) {
            if (distance(r->pos, me.pos) < distance(nearest->pos, me.pos)) nearest = r;
        }
        c.aim = nearest->pos;  // pre-aim at the nearest raider: whoever flanks into view gets shot first
    } else {
        c.aim = me.pos + from_angle(me.turret);
    }

    replan_ -= tuning::kStep;
    if (replan_ <= 0.0 || !goal_) {
        replan_ = kReplan;
        goal_.reset();
        const Scrap* scrap = nullptr;
        for (const Scrap& s : sim.scrap()) {
            if (s.taken) continue;
            if (!scrap || distance(s.pos, me.pos) < distance(scrap->pos, me.pos)) scrap = &s;
        }
        const bool hurt = me.hp < kHurt * me.spec->max_hp;
        if (foes.empty()) {
            if (scrap && me.hp < me.spec->max_hp) goal_ = scrap->pos;
            reason_ = "SCRAP";
        } else if (hurt && scrap && hidden_from_all(sim, scrap->pos, threats)) {
            goal_ = scrap->pos;
            reason_ = "SCRAP";
        } else {
            // Exposure = how many raiders can see a spot. Hold at 0, duel at 1 with a loaded gun,
            // otherwise move to the nearby spot the fewest raiders can see (perfect cover rarely exists).
            const bool loaded = me.reload <= kReloadingAbove;
            const auto exposure = [&](Vec2 p) {
                int n = 0;
                for (const Vec2& t : threats) n += sim.can_hit(t, p) ? 1 : 0;
                return n;
            };
            const int here = static_cast<int>(seeing_me.size());
            if (here == 0) {
                goal_ = me.pos;
                reason_ = "HOLD";
            } else if (here == 1 && loaded && sim.can_hit(me.pos, seeing_me.front()->pos)) {
                goal_ = me.pos;
                reason_ = "DUEL";
            } else {
                double best = kExposureCost * here;  // moving must beat staying
                goal_ = me.pos;
                reason_ = "HIDE";
                for (const Vec2& s : sim.arena().spots) {
                    const double d = distance(me.pos, s);
                    if (d > kMoveRange) continue;
                    const double score = kExposureCost * exposure(s) + d;
                    if (score < best) {
                        best = score;
                        goal_ = s;
                    }
                }
            }
        }
        // Hunt: a lone raider, or raiders that all run to heal, get chased down (a stand-off never ends otherwise)
        const bool all_retreating = !foes.empty() && std::all_of(foes.begin(), foes.end(), [](const Tank* r) { return r->retreating; });
        if (!foes.empty() && (foes.size() == 1 || all_retreating) && seeing_me.empty() && me.reload <= kReloadingAbove) {
            const Tank* prey = foes.front();
            for (const Tank* r : foes) {
                if (r->hp < prey->hp) prey = r;
            }
            const auto spot = find_firing_spot(sim, me.pos, prey->pos, kHuntRange, {});
            goal_ = spot ? *spot : prey->pos;
            reason_ = "HUNT";
        }
        if (!goal_) goal_ = me.pos;
        goal_last_ = goal_;
    }
    c.use_goal = true;
    c.goal = *goal_;
    return c;
}

}  // namespace core
