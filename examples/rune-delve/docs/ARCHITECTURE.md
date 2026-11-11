# Architecture

> How the code is organized and why. Keep it short and true. Update when structure changes.
> Last reviewed: 2026-10-22

## Big picture
```
Delve.umap (PlayerStart + NavMesh bounds, made by tools/unreal/build_content.py)
  -> ARDGameMode -> ARDDungeon (rooms from FRDLevel: instanced meshes, box colliders, gates, lights)
                -> ARDMage (Enhanced Input or RDBot) and ARDOrc x8 (RDOrcBrain + ARDOrcController: AI Perception, NavMesh)
                -> GAS: URDAbility_* -> URDEffect_* -> URDAttributeSet (hits resolved by RDRules)
  -> ARDHUD (canvas)
```
Rules and decisions live in `Source/RuneDelve/Public/Core` (plain C++, unit tests); `Game/` and `Abilities/` are the Unreal side.

## Layers (dependency direction: top depends on bottom, never upward)
1. **Game**: gameplay rules, entities, levels, content
2. **Systems**: input, physics helpers, audio, UI, save, camera
3. **Core**: logging, time, math, events, config, RNG
4. **Engine/platform**: provided by Unreal Engine 5 (C++ and Blueprints)

Rule: Core knows nothing about Game. Pure logic in Core and Game should be testable without the engine.

## Directory map
Engine-specific folder layout is documented in `docs/ENGINE.md`. Universal folders:
| Folder | Contents |
|---|---|
| `docs/` | All documentation and SOPs |
| `tools/` | Dev scripts, `dev.py` command wrapper, hooks |
| `tests/` | Automated tests |
| `.claude/` | Claude Code settings, skills, subagents |

## Key systems
| System | Responsibility | Entry point | Tests |
|---|---|---|---|
| Combat rules | Dash dodges, ward blocks and staggers, stagger doubles, mana | `Core/RDRules` | `RuneDelve.Core.Rules` |
| Orc decisions | FSM: sleep, hunt, wind-up, recover, staggered, dead (SOP-14) | `Core/RDOrcBrain` | `RuneDelve.Core.OrcBrain` |
| Level | Rooms, walls, gates, props, seeded spawns, NavMesh bounds | `Core/RDLevel` | `RuneDelve.Core.Level` |
| Bots | Weaver and Masher on one movement brain | `Core/RDBotPolicy` | `RuneDelve.Core.Bots`, `RuneDelve.Smoke.Pair` |
| Tunables | Every number, from `Config/DefaultGame.ini` | `Game/RDTuning` | `RuneDelve.Core.Tuning` |
| Spells (GAS) | Bolt, Ward, Dash; costs and cooldowns from the ini (ADR 0001) | `Abilities/RDAbilities`, `RDEffects`, `RDAttributeSet` | `RuneDelve.Smoke.Regressions`, `RuneDelve.Smoke.Pair` |
| Orc senses and movement | Sight cone, hearing, NavMesh chase (ADR 0002) | `Game/RDOrc`, `Game/RDOrcController` | `RuneDelve.Smoke.*` |
| Dungeon | Builds rooms at runtime; gates open on clear | `Game/RDDungeon` | `RuneDelve.Smoke.Boot` |
| Delve | Rooms, outcome, markers, restart, recording | `Game/RDGameMode` | `RuneDelve.Smoke.*` |
| Content | Imports and the map, headless (ADR 0003) | `tools/unreal/build_content.py` | `dev.py exec` |
| Replay | A seed plays the same with and without a renderer | `tools/unreal/replay_check.py` | itself (`--seed N`) |

## Data flow and events
Direct calls. Damage always goes through GAS (an effect spec into `URDAttributeSet`), which calls back the character
(`OnHurt`, `OnWardBlock`, `OnZeroHealth`); the characters tell `ARDGameMode` about deaths.

## State and save data
- Nothing persists in the slice (no saves; out of scope).
- Rule: save files carry a version number from day one.

## Determinism and randomness
- `-seed=N` moves the orcs (`FRDLevel::Orcs`, one `FRandomStream` per room). `-fixedfps` makes every frame 1/60 s and runs
  flat out: the smoke tests and the packaged game play the same delve (2026-10-26: seed 6 has the same counts, 44.5 s
  against 44.6 s, and seed 4 36.6 s against 36.7 s). With or without a renderer since 2026-11-05: the runtime NavMesh
  builds on worker threads, so under `-fixedfps` the game mode finishes every pending tile before the actors of a frame
  tick (`ARDGameMode::FinishNavBuild`), bolts no longer touch the NavMesh, and an orc's movement ticks after its path
  following (the engine orders neither; `docs/TROUBLESHOOTING.md`, #8).
  `-tracedelve` writes one line per frame (positions, health, orc states) after every actor has ticked;
  `tools/unreal/replay_check.py` runs a seed rendered and under `-nullrhi` and reports the first frame that differs.

## Budgets
| Budget | Target | Measured on | Last measured |
|---|---|---|---|
| Frame time | e.g. 16.6 ms (60 FPS) | min-spec machine, release build | |
| Smoke frame time (p95) | e.g. 20 ms | `dev.py smoke` on the dev machine | |
| Memory ceiling | e.g. 2 GB | | |
| Load time | e.g. under 5 s to menu | | |
| Triangles per asset class | see `docs/sop/SOP-11-3d-pipeline.md` (prop, kit, hero, NPC) | `tools/blender/validate_asset.py` | |
| Min-spec hardware | CPU, GPU, RAM | | |
Set these early (`SOP-10`), measure before optimizing, update the last column when you measure.
`dev.py smoke` prints the run's frame times (mean, p95, p99, worst) and fails when the p95 is over the
"Smoke frame time" target once it holds a number (replace the `e.g.` text, e.g. `20 ms`; `smoke --frame-budget MS`
overrides it for one run). It is a guard for this machine's smoke runs, not the min-spec target above: a headless run
draws nothing (a logic budget), and a browser run cannot go below its 60 Hz frame (about 16.7 ms).

## Debug tooling
- Debug overlay, console commands, cheat keys, log channels. List them here so Claude and testers can find them.

## Open questions
- 
