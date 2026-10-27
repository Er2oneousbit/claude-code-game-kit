---
name: game-ai
description: Design, build, debug or tune enemy, NPC or companion behavior (patrol, chase, flee, pathfinding, state machines, behavior trees, utility AI). Use when the user asks for an enemy, a guard, a ghost, an NPC that reacts, smarter or dumber AI, pathfinding, or "why does the enemy do that". Follows SOP-14. Not for language-model features (that is SOP-15).
---

# Game AI

Follow `docs/sop/SOP-14-game-ai.md`.

1. **Frame:** the behavior in plain words ("ghosts chase you but flee your lantern") and how a player should be able to
   read it on screen. Confirm it is in ROADMAP Now and serves a GDD pillar (SOP-01).
2. **Layers:** name the perception inputs, the decision options and the movement method (SOP-14 step 1).
3. **Technique:** pick from the SOP-14 table, simplest first. Say why in one line; record an ADR if it is a BT, utility
   or planner, or a new library.
4. **Engine facts:** read the SOP-14 engine row and `docs/ENGINE.md`. Verify navigation and AI APIs against the installed
   version (web: also `node_modules/phaser/skills/`), label anything unverified.
5. **Pseudocode** of the decision core, then build it engine-free with unit tests (SOP-14 step 6), tunables in one place,
   seeded randomness.
6. **Debug view** before the second behavior: state or scores, path, perception range, behind the debug flag.
7. **Wire it** into the engine side (perception in, movement out). `check`, `test`, `smoke`.
8. **Scenario check:** autoplay or scripted run with logged markers, as a pair: the bot that plays the design way wins, the
   cheap way through loses (SOP-14 step 6, F32); then a playtest note on fairness and readability.
9. **Report:** behaviors, where the tunables live, how to open the debug view, what still feels off.
