# Architecture

> How the code is organized and why. Keep it short and true. Update when structure changes.
> Last reviewed: 2026-10-21

## Big picture
```
main.ts -> GameScene (map, actors, input, bot) -> core: grid / astar / ghostBrain / lantern / separation / rng
                    \-> HudScene (oil, key, time, message, AI debug table) via the "hud" event
```

## Layers (dependency direction: top depends on bottom, never upward)
1. **Game**: gameplay rules, entities, levels, content
2. **Systems**: input, physics helpers, audio, UI, save, camera
3. **Core**: logging, time, math, events, config, RNG
4. **Engine/platform**: provided by Web (Phaser 4 + TypeScript + Vite)

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
| Level | Map as ASCII data, parsing, collision | `src/game/level.ts`, `src/core/grid.ts` | `level.test.ts`, `grid.test.ts` |
| Lantern | Oil, radius, light power | `src/core/lantern.ts` | `lantern.test.ts` |
| Ghost AI: perception | Distance, light at the ghost, memory | `GameScene.updateGhost` | scenario runs |
| Ghost AI: decision | Utility scores, inertia (ADR 0001) | `src/core/ghostBrain.ts` | `ghostBrain.test.ts` |
| Ghost AI: movement | A* paths, separation steering | `src/core/astar.ts`, `src/core/separation.ts` | `astar.test.ts`, `separation.test.ts` |
| HUD | Oil bar, key, timer, messages, AI debug table | `src/game/HudScene.ts` | smoke |
| Autoplay bot | Scenario check: `?autoplay` escapes, `?autoplay=dark` is caught | `GameScene.botIntent` | `dev.py smoke --query ...` |

## Data flow and events
Direct calls inside GameScene; one event (`hud`) from GameScene to HudScene each frame. Markers in the console log (`GOT_KEY`, `ESCAPED`, `CAUGHT`) are the contract with smoke and scenario runs.

## State and save data
- What persists, format, version field, migration plan.
- Rule: save files carry a version number from day one.

## Determinism and randomness
- Seeded RNG, one source (`src/core/rng.ts`), seed from `SEED` in tuning or `?seed=N`. Needed for replays, tests, and reproducing bugs.

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
