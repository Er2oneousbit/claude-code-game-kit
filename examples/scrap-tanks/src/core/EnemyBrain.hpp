// ---------------------------------------------------------------------------
// EnemyBrain.hpp
// Purpose : The raiders' behavior tree (ADR 0002): retreat when badly hurt, take cover while
//           reloading in the player's sight, fire when there is a shot, otherwise flank.
// Usage   : core::think_raider(sim, tank);   // called by core::Sim every tuning::kThinkEvery seconds
//           sets tank.control (goal, aim, fire) and tank.intent (the action that ran: shown in game)
// Notes   : Engine-free, one shared tree; all per-raider state lives in core::Tank.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

namespace core {

class Sim;
struct Tank;

void think_raider(Sim& sim, Tank& me);

// The tree as text, for --help style listings and the debug overlay.
const char* raider_tree_text();

}  // namespace core
