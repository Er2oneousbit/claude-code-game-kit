# ADR 0002: A behavior tree for the raiders, not an FSM

- Status: accepted
- Date: 2026-10-21

## Context
SOP-14 says to start with an FSM and move up only for a named problem. The raiders need four behaviors with a strict
priority order and fallbacks: retreat when badly hurt, take cover while reloading if the player can see them, fire when
they have a shot, otherwise move to a flanking spot. Every check can fail at any moment (the player moves, a shell lands).

## Options considered
1. **FSM** (states RETREAT, COVER, FIRE, FLANK): each state needs exit checks for every higher-priority state, which is
   the "transitions turn into a web" problem SOP-14 names: 4 states, 12 transitions, priorities spread over all of them.
2. **Behavior tree**: one selector over four sequences, top to bottom by priority. Each frame the first branch whose
   conditions hold wins, so priorities live in one place and adding a branch is one line.
3. **Utility AI**: scores per action. More tuning than this needs; the order is fixed, not situational.

## Decision
Option 2: a small engine-free behavior tree in `src/core/Bt.hpp` (Selector, Sequence, Condition, Action, with Running),
about 100 lines and unit tested. Its active leaf is shown over each raider (pillar 2: read the raiders).

## Consequences
- Good: priority order readable in one place (`src/core/EnemyBrain.cpp`); conditions and actions are plain functions on a
  blackboard, so tests can check "hurt and visible -> RETREAT" directly.
- Bad / costs: re-evaluating from the root each tick costs more than an FSM; with at most four raiders it does not matter.
- What we would need to see to revisit this: many more raiders (tick less often), or behaviors that need plans (SOP-14).

## Notes
SOP-14 step 2 and the Game AI Pro overview (E39). No library: BehaviorTree.CPP exists as a vcpkg port (E40) but is far
more than four branches need.
