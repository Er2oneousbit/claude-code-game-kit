# SOP-17: Procedural generation (levels made while the game runs)

## Goal
A new level every run that is **fair every time**, can be replayed from one number, and is tested like any other
system. Making levels is the easy half. Proving that every one of them can be finished, and is fun to finish, is the
work. Run it with `/procgen`.

Sources: `docs/EVIDENCE.md` E56 to E59 and findings F28 to F31; K01 is this kit's own Graveyard Shift work (below).

## When to use it, and when not
- Use it when replay is the point (a run, a night, a dungeon floor) and the content follows rules you can write down
  (E56: Rogue and Elite are the classic cases).
- Prefer a hand-made level when the game is short, when one level carries the story or tutorial, or when you cannot
  yet say what makes a level good (K01). Generate from a level you already know is fun: the generator's job is to make
  more like it (K01: Graveyard Shift's generator only became fair once it copied the hand-made yard's skeleton).
- Keep one hand-made level as seed 0 and as the fallback (step 4). It is the baseline every test compares against (K01).

## 1. Write the invariants before the generator
An invariant is a sentence every level must make true. Write them first, as code that checks a level and returns a
list of problems, so the generator, the tests and the debug view share one definition.
- A level that cannot be finished is a catastrophic failure, not a weird one: check every level against written
  criteria instead of trusting the generator (F28: E56, K01).
- Typical invariants: the goal and every pickup are reachable on foot from the start; pickups are spread out and away
  from the start; no prop sits on another, on the start or on a pickup; every patrol point is reachable by the
  enemy that walks it; there is cover or an escape near each objective when the design needs one (K01).
- Reachability is checked against the **same shapes the engine uses**: measure the props' real footprints once, and
  keep a test that compares them with the meshes (K01: a rotated mesh's bounds are the box around its rotated box, so a
  pine at 45 degrees blocks 3.6 m, not the 2.7 m a guess gave).
- Use the navigation agent's real numbers (radius, step height) and a small margin for the bake's voxels. Log them from
  the engine instead of remembering them (K01: Unity's default agent read back as radius 0.5, climb 0.75).
- The player cannot leave the level: check it in the engine with a test that walks into every gap, door and corner,
  because a level model that only covers the inside never sees the holes in its edge (K01: the playtester walked out
  of Graveyard Shift's open gate and fell forever; the corners leaked too, on the hand-made yard as well).
- Run the invariants on your hand-made level too. They will find things; decide case by case and write the exceptions
  into a test (K01: five decorative overlaps and three tight spots in a hand-made yard that had passed every test).
- Give every invariant a test that feeds it a deliberately broken level and expects its problem. A check that never
  fails looks exactly like a level that never breaks (K01: an independent review found the soul reachability check
  swallowed by a comment; good levels never tripped it, so every other test passed).

## 2. One seed in, the same level out
- Every random choice comes from one seed, so a level can be replayed (F29: E56, E57, K01).
- Use your own small PRNG (a few lines of integer math, e.g. Mulberry32 or SplitMix): .NET does not promise that
  `System.Random`'s seeded sequence stays the same across versions (F29: E57), and engine RNGs are often global state.
- Keep float arithmetic out of the generator's decisions, or keep it exact: put positions on a lattice of
  power-of-two steps (1/16 m) so every sum is exact. The same C# code and seed built **different levels** in Unity's
  Mono and in .NET 8 while the PRNG matched bit for bit; `min + (max - min) * r` rounded differently. With a lattice,
  traces from both runtimes matched line for line (K01).
- Pin a few levels by fingerprint (a hash of every number) in a test, made on a second runtime if you can. Changing
  the generator changes every seed players saved or shared, so make that a deliberate edit (K01).
- Show the seed on screen and accept it on the command line (`--seed N`), so a bug report carries its level (K01).

## 3. Build the skeleton first, then fill in around it
- Place what matters most first (the critical path, the big pieces), then fill the rest around it; shipped generators
  get their guarantees from that construction, built from hand-made pieces (F31: E58, E59; K01).
- Pick spots for pickups and patrol points from the reachable area you computed, not from random coordinates, so the
  checks mostly confirm instead of reject (K01: 9,994 of 10,000 yards passed on the first attempt).
- Tip (C, E58): random fill off the main path may be walled off; that is fine as long as nothing required is there.

## 4. Generate, validate, reject and retry, with a cap and a fallback
- Loop: generate, run the invariants, throw the level away on any problem, try again with a seed derived from the
  seed and the attempt number (F28: E56, K01).
- Cap the attempts and fall back to the hand-made level, logged loudly; a test fails if any tested seed falls back (K01).
- Record why each attempt was rejected and look at the tally: it tells you which rule or piece to fix. Every early
  rejection in Graveyard Shift was "no room for a tree", which made trees optional instead of fatal (K01).
- Tip (C, E59): retry locally (one room, one piece) before you throw away the whole level, when pieces are expensive.

## 5. Test the generator over many seeds
- Property tests: generate hundreds of levels from the seeds players will really get and assert every invariant,
  printing the count of seeds checked, problems, fallbacks and the time per level (F30: E56, K01).
- Judge the generator by distributions, not by looking at a few levels: pick two or three metrics (tour length,
  distance from pickups to patrols, prop count) and look at their spread across seeds (F30: E56).
- Check your model of the world against the engine: build a sample of levels in the engine and compare reachability
  with the real navmesh. The model may be stricter than the engine (it then only wastes good levels), never looser
  (K01: a 1.0 m gap the grid passed was closed by the NavMesh bake; a low rock was walkable for the NavMesh but not
  for the character controller). So also walk a sample through the player's own controller (its radius, step height
  and slope): the bots in step 6 do, if they move like the player.

## 6. Play generated levels with bots (SOP-14 step 6)
- Run the same bot set over the hand-made level and over at least 8 generated seeds, and assert the design's gaps
  on both (F30: E56, K01).
- Expect the generated levels to break pillars the hand-made level kept: they are new levels nobody tuned (K01: the
  first generated yards had the careful bot caught 18 times in 8 nights against 0 on the hand-made yard).
- Change the generator, not the bots, when a pillar fails on generated levels; rerun both sets after any change to
  the navmesh, colliders or bot (K01: a correct NavMesh fix moved the hand-made balance enough to fail its test, and
  was reverted pending a playtest).

## 7. A bad seed becomes a regression test
- Any seed that ever broke an invariant or a bot run goes into a fixed list the property test always checks, with a
  comment saying what it broke (F28: E56, K01).

## Engine notes
| Engine | Seeded random | Reachability to check against | Watch out |
|---|---|---|---|
| Unity 6 | Your own PRNG in an engine-free assembly; not `UnityEngine.Random` (global) or `System.Random` (E57) | NavMesh from `NavMeshSurface` (AI Navigation); compare with `NavMesh.CalculatePath` in a PlayMode test (K01) | Mono and .NET round float formulas differently (K01); IL2CPP not tested here **(verify)**. `Renderer.bounds` of a rotated mesh is the box around its rotated box (K01) |
| Godot 4 | `RandomNumberGenerator` with `seed` set, one instance per generator **(verify cross-platform sequence)** | `NavigationServer2D/3D` map queries after the region bakes (SOP-14) | Path queries on the first physics frame come back empty (SOP-14) **(verify for your Godot version)** |
| Web (Phaser), Web 3D | A seeded PRNG in `src/core` (`Math.random()` takes no seed) **(verify)** | Grid A* in `src/core` is both the model and the engine: test it directly (SOP-14) | Keep generation in `src/core` so Vitest runs hundreds of seeds |
| Unreal 5 | `FRandomStream` with a seed **(verify)** | Recast navmesh; `UNavigationSystemV1::FindPathToLocationSynchronously` **(verify)** | Generate in C++ or Python editor scripts first; runtime spawning needs the navmesh to rebuild **(verify)** |
| C++ / SDL2 | Your own PRNG (the standard library's distributions are not portable across implementations **(verify)**) | Your own grid or Recast/Detour | Same float rule as Unity: lattice positions |
| RPG Maker MZ | Your own PRNG in the engine-free plugin (`Math.random()` takes no seed) | Tile passability from the map's tileset flags; check it in your own grid in Node **(verify)** | Maps are JSON files (Map001.json and up) the editor overwrites if it is open; a generated map needs valid tile ids for its tileset **(verify)** |

## Worked example: Graveyard Shift's nights (K01)
The kit's Graveyard Shift example: `LevelGenerator.Generate(seed)` in its engine-free Core assembly. Night 0 is the
hand-made yard; every later night gets `SeedForNight(n)`, shown on the HUD and replayable with `--seed N`. The outline
is generated too: a main body plus 1 to 3 wings (a union of rectangles on the 2 m wall grid), 4,000 to 5,200 m2, with a
wall segment on every edge between inside and outside.
| Invariant (LevelCheck) | Number |
|---|---|
| Twelve souls, inside the outline, at least 0.6 m from any prop | `SoulCount`, `SpotClearance`, `WallMargin` |
| Every soul and the gate reachable on foot (walk grid, agent radius 0.5 m plus a 0.125 m bake margin) | `KeeperRadius`, `BakeMargin` |
| Souls at least 10 m apart, and 15 m from the start (7 m on the hand-made yard) | `SoulSpacing`, `GeneratedFromStart`, `SoulFromStart` |
| Cover that reaches the keeper's chest (not a wall, a post, or a knee-high grave) within 4 m of every soul, so dark sneaking works | `CoverReach` |
| 6 to 12 closed ghost loops at least 24 m long; a ghost can reach every corner within its arrive radius; no corner within 8 m of the start | `MinRoutes`, `MaxRoutes`, `MinLoop`, `GhostStartSafe` |
| No prop overlaps another (within the lattice snap's 1/8 m) | `OverlapTolerance` |
Results for the 4x yards: 250 night seeds in the EditMode property test with 0 problems and 0 fallbacks; 500 seeds in a
scratch harness, 446 on the first attempt and 0 fallbacks; 9 yards checked against the real NavMesh (405 checks, the
grid never looser); 30 pushes at the gate and out of every corner, none got out. Bot trio at Easy over nights 1 to 8:
careful escaped 5 of 8, always dark 7, always lit 0 (hand-made yard: 8, 8, 0; after the 2026-10 review fixes, which
regenerated every yard). The bots see in the dark, so careful
against always-dark is logged on generated nights, asserted only on the hand-made yard. Difficulty adds ghosts on the
checked loops and takes light away, so it never changes the yard or its checks (K01).
The full story, with what each check caught, is in that example's HOW_IT_WAS_MADE.md (the kit repo, not your game).

## Done when
- The invariants are code, each with a broken-level test, run by the generator and by a property test over hundreds of
  seeds that prints its count (steps 1 and 5: F28, F30, E56, K01).
- One seed rebuilds one level, the seed is on screen, `--seed N` replays it, and pinned fingerprints guard it (step 2:
  F29, E56, E57, K01).
- The generator retries with a cap and falls back to a hand-made level; no tested seed falls back (step 4: F28, K01).
- The bot set passes on the hand-made level and on at least 8 generated seeds (step 6: F30, K01).
- Every bad seed found is in the regression list (step 7: F28, K01).

## Common mistakes
- Writing the generator first and the checks "later": every bug then looks like bad luck (F28: E56, K01).
- Trusting `Random(seed)` to replay forever, or float formulas to round the same everywhere (F29: E57, K01).
- Checking reachability with guessed sizes, or with a model looser than the engine's navmesh (K01).
- Checks that were never seen to fail (K01).
- Judging a generator by the three levels you looked at (F30: E56).
- Tuning the bots until the generated levels pass. The bots are the measuring stick; the generator is what you tune (K01).
- No hand-made fallback, so a rare bad seed ships a broken level instead of a familiar one (K01).
