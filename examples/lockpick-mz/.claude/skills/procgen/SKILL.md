---
name: procgen
description: Design, build, test or debug procedurally generated levels, maps, dungeons, nights or runs made while the game runs (seeds, generators, "a new level every time", roguelike floors, random layouts). Use when the user asks for random or generated levels, replayable seeds, "why is this seed broken", or making a hand-made level into a generator. Follows SOP-17. Not for generating art or audio assets (that is /gen-brief and /asset-intake).
---

# Procedural generation

Follow `docs/sop/SOP-17-procedural-generation.md`.

1. **Frame:** what changes each run and what stays. Name the hand-made level the generator should make more of; if
   there is none yet, build and playtest one first (SOP-17 "When to use it"). Confirm it is in ROADMAP Now (SOP-01).
2. **Invariants first:** write the sentences every level must satisfy, then code them as a check that returns a list of
   problems (SOP-17 step 1), plus one test per invariant that feeds it a broken level and expects the problem. Run it
   on the hand-made level and record what it finds before writing the generator.
3. **Real shapes:** measure prop footprints and the navigation agent's numbers from the engine (log them), and keep a
   test that compares the footprints with the meshes.
4. **Seed:** one integer seed, your own PRNG, positions on an exact lattice, the seed on screen and `--seed N` on the
   command line (SOP-17 step 2). Pin a few fingerprints in a test.
5. **Pseudocode** of the generator: skeleton first (path, big pieces), then fill; pickups and patrol points picked from
   the reachable area (SOP-17 step 3). Then build it engine-free, tunables in one constants block.
6. **Retry loop:** validate, reject, retry with a capped number of attempts, fall back to the hand-made level, record
   why each attempt was rejected (SOP-17 step 4).
7. **Tests:** a property test over hundreds of seeds that prints its count; a test that checks the model against the
   engine's navmesh on a sample of seeds (SOP-17 step 5). `check`, `test`, `smoke`.
8. **Bots:** run the scenario bots (SOP-14 step 6) on the hand-made level and on at least 8 generated seeds. If a
   pillar fails on generated levels, tune the generator, not the bots (SOP-17 step 6).
9. **Report:** the invariants, seeds tested and their results, rejection reasons, bot results on both kinds of level,
   bad seeds added to the regression list, screenshots of a few generated levels, and what is still unverified.
