# Architecture

> How the code is organized and why. Keep it short and true. Update when structure changes.
> Last reviewed: 2026-10-21

## Big picture
```
<Boot> -> <Main loop/scene> -> <Systems> -> <Rendering/Audio/UI>
```
Replace with a real diagram as soon as one exists (ASCII is fine).

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
| | | | |

## Data flow and events
How systems talk (signals, event bus, direct calls). Pick one primary pattern and stick to it.

## State and save data
- What persists, format, version field, migration plan.
- Rule: save files carry a version number from day one.

## Determinism and randomness
- Seeded RNG, one source. Needed for replays, tests, and reproducing bugs.

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
