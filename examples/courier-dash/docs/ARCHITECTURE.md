# Architecture

> How the code is organized and why. Keep it short and true. Update when structure changes.
> Last reviewed: 2026-10-21

## Big picture
```
main.ts (renderer, frame loop) -> game/Game.ts (fixed steps, input or bot) -> core/sim.ts (rules) -> core/robot.ts (FSM) -> core/nav.ts, core/geom.ts
                                  \-> views: courierView, robotView, parcels, hud, sound (read the Sim, never change it)
```
Everything that decides anything lives in `src/core/` and never imports three. `src/game/` only loads, draws and plays sounds.

## Layers (dependency direction: top depends on bottom, never upward)
1. **Game**: gameplay rules, entities, levels, content
2. **Systems**: input, physics helpers, audio, UI, save, camera
3. **Core**: logging, time, math, events, config, RNG
4. **Engine/platform**: provided by Web 3D (Three.js + TypeScript + Vite)

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
| Run rules | Clock, stamina, pickup and delivery, win, caught, time up | `src/core/sim.ts` | `sim.test.ts`, `regressions.test.ts` |
| Level | Buildings and trees as boxes, parcels, depot, patrol loop, road tiles | `src/core/level.ts` | `level.test.ts` |
| Geometry | Line of sight, sight-cone rays, move and slide | `src/core/geom.ts` | `geom.test.ts` |
| Robot AI: perception | Sight cone (range, angle, buildings block it), asleep until the run starts | `Robot.canSee` | `robot.test.ts` |
| Robot AI: decision | FSM: patrol, alert, chase, search, return | `src/core/robot.ts` | `robot.test.ts`, `regressions.test.ts` |
| Robot AI: movement | Tank drive, grid A* with string pulling for search, return and a stuck chase | `src/core/robot.ts`, `src/core/nav.ts` | `nav.test.ts` |
| Autoplay bots | `careful` (waits, sidesteps, hides) and `reckless` | `src/core/bot.ts` | `scenario.test.ts`, smoke |
| Rendering | Town from level data, models fitted into their boxes, camera, debug view | `src/game/Game.ts`, `src/game/assets.ts` | smoke screenshots |
| Readability | Robot glow color, "!"/"?" tell, sight cone drawn as far as it sees | `src/game/robotView.ts` | `&close=robot` screenshots |
| Courier | Animations (idle, walk, sprint, pick-up, die, emotes), carried parcel | `src/game/courierView.ts` | `&close` screenshots |
| HUD, input, sound | Clock, parcels, stamina; keyboard and gamepad; four sounds | `hud.ts`, `input.ts`, `sound.ts` | smoke |

## Data flow and events
`Sim.step(input)` returns events (`PICKUP`, `DELIVERED`, `SPOTTED`, `CAUGHT`, `RUN_WON`, ...); `Game.onEvent` turns them into sounds and log lines. Views read the Sim's state each frame. Console markers (`RUN_WON`, `CAUGHT`, `TIME_UP`) are the contract with smoke.

## State and save data
- What persists, format, version field, migration plan.
- Rule: save files carry a version number from day one.

## Determinism and randomness
- No randomness at all. The simulation runs in fixed steps of `TUNING.stepSeconds`, so the same inputs give the same run at any
  frame rate: the browser autoplay run and `tests/scenario.test.ts` end with the same time left to the tenth of a second.
- No save data in the slice (best time is kept for the session only).

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
