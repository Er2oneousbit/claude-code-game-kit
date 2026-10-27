// ---------------------------------------------------------------------------
// Tactics.hpp
// Purpose : Spot finding shared by the raiders' behavior tree and the autoplay bots: where to hide,
//           where to shoot from, and where to aim at a moving target.
// Usage   : auto spot = core::find_cover(sim, me.pos, threats);  core::lead(shooter, target, vel, speed)
// Notes   : Spots come from Arena::spots (a grid plus rings around cover). Hidden means no line of
//           sight from any threat (cover blocks with a small pad, so a spot right at an edge does not count).
//           Both pickers return only spots with a nav path from the player start (NavGrid::reachable).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): unreachable spots are skipped (Fable review)
// ---------------------------------------------------------------------------
#pragma once

#include <optional>
#include <vector>

#include "core/Sim.hpp"

namespace core {

constexpr double kHidePad = 0.35;  // m: a hiding spot must be hidden by this margin

// Hidden from every threat?
bool hidden_from_all(const Sim& sim, Vec2 p, const std::vector<Vec2>& threats);

// Nearest hidden spot to `from` (keeping `min_threat_distance` from every threat), or nothing.
// `far_weight` > 0 prefers spots farther from the threats (retreats).
std::optional<Vec2> find_cover(const Sim& sim, Vec2 from, const std::vector<Vec2>& threats,
                               double min_threat_distance = 5.0, double far_weight = 0.0);

// A spot that sees `target` from between 0.5 and 0.9 of `range`, close to `from`, away from `avoid`
// (other raiders' spots: so raiders spread out and flank).
std::optional<Vec2> find_firing_spot(const Sim& sim, Vec2 from, Vec2 target, double range,
                                     const std::vector<Vec2>& avoid);

// Where to aim so a shell at `shell_speed` meets a target moving at `target_vel` (one refinement step).
Vec2 lead(Vec2 shooter, Vec2 target, Vec2 target_vel, double shell_speed);

}  // namespace core
