# Architecture

> How the code is organized and why. Keep it short and true. Update when structure changes.
> Last reviewed: 2026-10-21

## Big picture
```
main.cpp (SDL, fixed step) -> game/Game.cpp (input or bot) -> core/Sim.cpp (rules) -> core/EnemyBrain.cpp (behavior tree)
                                                                    \-> core/Nav, Tactics, Geom, Bt
game/Game.cpp render -> game/Assets (sprites, font, sound) + core/View.hpp (camera math)
```
Everything that decides anything lives in `src/core/` and never includes SDL; the tests play whole fights.

## Layers (dependency direction: top depends on bottom, never upward)
1. **Game**: gameplay rules, entities, levels, content
2. **Systems**: input, physics helpers, audio, UI, save, camera
3. **Core**: logging, time, math, events, config, RNG
4. **Engine/platform**: provided by C++17 + SDL2 (CMake, vcpkg)

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
| Fight rules | Tanks, shells stopped by cover, damage, scrap, waves, outcome | `src/core/Sim.cpp` | `test_sim.cpp` |
| Arena | Bounds, cover circles (mirrored), spawns, candidate spots | `src/core/Arena.hpp` | `test_arena.cpp` |
| Raider AI: decision | Behavior tree: RETREAT, COVER, FIRE, FLANK (ADR 0002) | `src/core/EnemyBrain.cpp`, `src/core/Bt.hpp` | `test_brain.cpp`, `test_bt.cpp` |
| Raider AI: perception and spots | Sight, clear shots, cover and firing spots, aim leading | `src/core/Tactics.cpp` | `test_brain.cpp` |
| Movement | Tank drive, grid A* with string pulling | `src/core/Sim.cpp`, `src/core/Nav.cpp` | `test_nav.cpp` |
| Autoplay bots | `skilled` (exposure-based cover) and `reckless` (charge) | `src/core/Bot.cpp` | `test_scenario.cpp` |
| Camera | World to screen, sprite rows per direction | `src/core/View.hpp` | `test_view.cpp` |
| Presentation | Sprites, labels, HUD, sound, debug overlay, input | `src/game/Game.cpp`, `src/game/Assets.cpp` | smoke screenshots |
| Art | Kenney 3D models to sprite sheets | `tools/make_sprites.py` | `render_sprites` exam |

## Data flow and events
Drivers write a `core::Control` (throttle and turn, or a goal; aim; fire). `Sim::step` returns events (Fire, Hit,
TankDestroyed, Pickup, WaveStart, RunWon, PlayerDestroyed); `Game::on_events` turns them into sounds and log markers.

## State and save data
- What persists, format, version field, migration plan.
- Rule: save files carry a version number from day one.

## Determinism and randomness
- One seeded RNG (`src/core/Rng.hpp`, xorshift64*: same numbers on every compiler) picks raider spawns; fixed steps of
  `tuning::kStep`. `-- --seed N` replays a fight exactly, in the game and in the tests.
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
