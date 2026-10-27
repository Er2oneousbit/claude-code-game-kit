// ---------------------------------------------------------------------------
// Tactics.cpp
// Purpose : Implementation of the spot finders in Tactics.hpp.
// Usage   : called by core/EnemyBrain.cpp and core/Bot.cpp
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): both pickers skip spots no path reaches (Fable review)
// ---------------------------------------------------------------------------
#include "core/Tactics.hpp"

#include <limits>

namespace core {

bool hidden_from_all(const Sim& sim, Vec2 p, const std::vector<Vec2>& threats) {
    for (const Vec2& t : threats) {
        if (line_of_sight(t, p, sim.blockers(), -kHidePad)) return false;
    }
    return true;
}

std::optional<Vec2> find_cover(const Sim& sim, Vec2 from, const std::vector<Vec2>& threats,
                               double min_threat_distance, double far_weight) {
    std::optional<Vec2> best;
    double best_score = std::numeric_limits<double>::infinity();
    for (const Vec2& s : sim.arena().spots) {
        // Scores are straight-line; a spot on a nav island would look close and never be reached
        if (!sim.nav().reachable(s)) continue;
        double nearest_threat = std::numeric_limits<double>::infinity();
        for (const Vec2& t : threats) nearest_threat = std::min(nearest_threat, distance(s, t));
        if (nearest_threat < min_threat_distance || !hidden_from_all(sim, s, threats)) continue;
        const double score = distance(from, s) - far_weight * nearest_threat;
        if (score < best_score) {
            best_score = score;
            best = s;
        }
    }
    return best;
}

std::optional<Vec2> find_firing_spot(const Sim& sim, Vec2 from, Vec2 target, double range,
                                     const std::vector<Vec2>& avoid) {
    std::optional<Vec2> best;
    double best_score = std::numeric_limits<double>::infinity();
    for (const Vec2& s : sim.arena().spots) {
        if (!sim.nav().reachable(s)) continue;
        const double d = distance(s, target);
        if (d < 0.5 * range || d > 0.9 * range || !sim.clear_shot(s, target)) continue;
        double score = distance(from, s);
        for (const Vec2& a : avoid) {
            const double gap = distance(s, a);
            if (gap < tuning::kSpotSpread) score += (tuning::kSpotSpread - gap) * 4.0;
        }
        if (score < best_score) {
            best_score = score;
            best = s;
        }
    }
    return best;
}

Vec2 lead(Vec2 shooter, Vec2 target, Vec2 target_vel, double shell_speed) {
    Vec2 aim = target;
    for (int i = 0; i < 2; ++i) {
        const double t = distance(shooter, aim) / shell_speed;
        aim = target + target_vel * t;
    }
    return aim;
}

}  // namespace core
