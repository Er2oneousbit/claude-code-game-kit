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

## Data flow and events
Direct calls. Damage always goes through GAS (an effect spec into `URDAttributeSet`), which calls back the character
(`OnHurt`, `OnWardBlock`, `OnZeroHealth`); the characters tell `ARDGameMode` about deaths.

## State and save data
- Nothing persists in the slice (no saves; out of scope).
- Rule: save files carry a version number from day one.

## Determinism and randomness
- `-seed=N` moves the orcs (`FRDLevel::Orcs`, one `FRandomStream` per room). `-fixedfps` makes every frame 1/60 s and runs
  flat out: the smoke tests and the packaged game play the same delve (2026-10-26: seed 6 has the same counts, 44.5 s
  against 44.6 s, and seed 4 36.6 s against 36.7 s). Only with a renderer: the packaged game with `-nullrhi` played a
  different delve on both seeds (cause not known, `docs/TROUBLESHOOTING.md`).

## Budgets
| Budget | Target | Measured on | Last measured |
|---|---|---|---|
| Frame time | e.g. 16.6 ms (60 FPS) | min-spec machine, release build | |
| Memory ceiling | e.g. 2 GB | | |
| Load time | e.g. under 5 s to menu | | |
| Triangles per asset class | see `docs/sop/SOP-11-3d-pipeline.md` (prop, kit, hero, NPC) | `tools/blender/validate_asset.py` | |
| Min-spec hardware | CPU, GPU, RAM | | |
Set these early (`SOP-10`), measure before optimizing, update the last column when you measure.

## Debug tooling
- Debug overlay, console commands, cheat keys, log channels. List them here so Claude and testers can find them.

## Open questions
- 
