# ADR 0001: Utility AI for the ghosts

- Status: accepted
- Date: 2026-10-21

## Context
Ghosts must chase in the dark, flee the lantern, and wander otherwise, and the GDD wants them readable (pillar 1) and the
light to be the deciding resource (pillar 2). How strongly a ghost wants each thing depends on two continuous inputs at
once (distance and light), plus memory of the player. SOP-14 says start with an FSM and move up only for a named problem.

## Options considered
1. **FSM** (wander, chase, flee with threshold transitions): simplest. Two continuous inputs mean a grid of thresholds
   (near and dim, near and bright, far and remembered...) and hard edges that feel twitchy at the light boundary.
2. **Utility AI** (score each action 0..1 from the inputs, pick the best, inertia against flicker): handles continuous
   inputs naturally, a handful of weights to tune, scores are easy to show in a debug view.
3. **Behavior tree**: good for priorities and sequences; the ghosts have neither.

## Decision
Utility AI (`src/core/ghostBrain.ts`), because the choice is a trade-off between continuous inputs, which is exactly what
scores express, and the scores double as the debug view.

## Consequences
- Good: tuning is a few weights in `src/game/tuning.ts`; tests pin the behaviors that matter; the debug HUD shows why.
- Bad / costs: less predictable than an FSM if weights drift; needs the inertia bonus and a think timer.
- What we would need to see to revisit this: ghosts needing multi-step plans or ordered sequences (then a BT).

## Notes
SOP-14 (technique table), Graham "An Introduction to Utility Theory" (Game AI Pro, E39). Verified in this project by
`tests/ghostBrain.test.ts` and the autoplay scenario pair (6 seeds each).
