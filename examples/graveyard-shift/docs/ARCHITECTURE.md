# Architecture

> How the code is organized and why. Keep it short and true. Update when structure changes.
> Last reviewed: 2026-11-03

## Big picture
```
Graveyard.unity (one Bootstrap object) -> Game/GraveyardGame.cs -> LevelBuilder (props, lights, runtime NavMesh)
                                                 -> KeeperController (input or KeeperBot) and GhostAgent per ghost (NavMeshAgent)
                                                 -> Core: NightRules, GhostBrain, Perception, SaveMigration, Level
Editor: SceneBuilder (scene, setup asset, version) and GraveyardImport (FBX import rules)
```
Rules and decisions live in `Assets/Scripts/Core` (plain C#, EditMode tests); `Assets/Scripts/Game` is the Unity glue.

## Layers (dependency direction: top depends on bottom, never upward)
1. **Game**: gameplay rules, entities, levels, content
2. **Systems**: input, physics helpers, audio, UI, save, camera
3. **Core**: logging, time, math, events, config, RNG
4. **Engine/platform**: provided by Unity (C#)

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
| Night rules | Clock to dawn, souls, gate, caught costs a soul, outcome | `Assets/Scripts/Core/NightRules.cs` | EditMode `NightRulesTests` |
| Ghost decision | FSM: patrol, suspicious, hunt (tires), search (gives up after `SearchMaxSeconds`), return (ADR 0003); a tired ghost never catches | `Assets/Scripts/Core/GhostBrain.cs` | EditMode `GhostBrainTests` |
| Ghost perception | Cone and range by lantern; raycast against Cover | `Assets/Scripts/Core/Perception.cs`, `Assets/Scripts/Game/GhostAgent.cs` | EditMode `PerceptionTests` |
| Level | Props, souls, gate, routes as data; built at runtime | `Assets/Scripts/Core/Level.cs`, `Assets/Scripts/Game/LevelBuilder.cs` | EditMode `LevelTests` |
| Save | Versioned JSON (v3), v1 and v2 migrations | `Assets/Scripts/Core/SaveData.cs`, `Assets/Scripts/Game/SaveStore.cs` | EditMode `SaveMigrationTests` |
| Keeper | CharacterController, lantern, legacy animation | `Assets/Scripts/Game/KeeperController.cs`, `Assets/Scripts/Game/CharacterAnimator.cs` | PlayMode trio |
| Bots | Careful, AlwaysLit, AlwaysDark on one movement brain | `Assets/Scripts/Game/KeeperBot.cs` | PlayMode `ScenarioTests` |
| Scene and assets | Scene from code, setup asset, version, import rules | `Assets/Editor/SceneBuilder.cs`, `Assets/Editor/GraveyardImport.cs` | `dev.py exec` |
| HUD | Souls, dawn clock, lantern, marks over ghosts | `Assets/Scripts/Game/Hud.cs` (IMGUI, ADR 0001) | smoke |

## Data flow and events
Direct calls from GraveyardGame each frame; `NightRules.Tick` returns events (SoulCollected, Caught, Escaped, Dawn) that
GraveyardGame turns into sounds, log markers and the save.

## State and save data
- save.json in `Application.persistentDataPath`: version 3 (best escape, nights, escapes, settings with the
  difficulty). v1 (the toy) and v2 migrate forward (`SaveMigration.Upgrade`); a newer version is refused and the file kept as `.bad`. Written to a temp file, then swapped.
  An unreadable save, or an unreadable `.tmp` left with no save, is kept as `save.json.bad` and the game starts fresh (the
  `.tmp` is removed so the next launch does not read it again). Bot nights (`--autoplay`) never write the save.
- Rule: save files carry a version number from day one.

## Determinism and randomness
- One seed per night: `--seed N` picks the yard (`LevelGenerator.Generate`, 0 is the hand-made yard; `--handmade` forces
  it) and each ghost's starting corner and direction. Without it the night's seed is `SeedForNight(nights played)`. All
  generation randomness is `Assets/Scripts/Core/SeededRandom.cs` on a 1/16 m lattice, so the editor and a .NET 8 build make the same yard.
  With `Time.captureFramerate = 60` (tests, and `--fixed-fps` in the player) a night replays: the built player
  reproduces a test night to the tenth of a second, generated or hand-made (seeds 6 and 6258 checked). The bot trio's
  catch totals still moved by one or two between identical runs once (HOW_IT_WAS_MADE, cause not found), so treat
  the trio's gaps, not its exact counts, as the result.

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
