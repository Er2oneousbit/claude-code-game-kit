# Architecture

> How the code is organized and why. Keep it short and true. Update when structure changes.
> Last reviewed: 2026-10-28

## Big picture
```
main.rs -> app::build (plugins per run mode)
             GamePlugin (FixedUpdate, 60 Hz): PlayerInput / bots -> Race::step -> log markers
             PresentPlugin (window only): keyboard+pad -> PlayerInput; RaceRes -> 3D scene, camera, HUD
           logic::race::Race  <- the whole race, plain Rust (track, karts, items, changes, finish)
```

## Layers (dependency direction: top depends on bottom, never upward)
1. **Game** (`src/game/`): Bevy plugins that wrap the race and draw it.
2. **Logic** (`src/logic/`): the race itself: `track`, `kart`, `race`, `bots`, `tuning`, plus `math` and `rng`.
3. **Engine/platform**: Bevy 0.20.

Rule: `logic/` never uses the ECS (plain math only), so the whole race runs in unit tests and bots race it in
milliseconds. `src/game/mod.rs` never touches a renderer; `src/game/present.rs` only reads the race and writes input.

## Directory map
| Folder | Contents |
|---|---|
| `src/logic/` | Race simulation and bots (unit tests next to the code) |
| `src/game/` | `mod.rs` simulation plugin and markers, `present.rs` 3D view, HUD, input |
| `tests/headless.rs` | Full races through the real GamePlugin, headless |
| `docs/`, `tools/`, `.claude/` | Kit docs, `dev.py`, Claude setup |

## Key systems
| System | Responsibility | Entry point | Tests |
|---|---|---|---|
| Track | Loop strip, shortcuts, tapered lane closures, drivable test, lap distance | `src/logic/track.rs` `Track::neon_loop` | `track::tests` |
| Kart | Arcade handling: speed, steering, slip and grip, drift charge, boost | `src/logic/kart.rs` `Kart::drive` | `kart::tests` |
| Race | Countdown, walls and barrier zaps, bumps, items, laps, the change schedule, finish | `src/logic/race.rs` `Race::step` | `race::tests`, `tests/headless.rs` |
| Bots | Plan a path (loop lane or shortcut), steer at a lookahead point, brake for bends, pass, read changes by style | `src/logic/bots.rs` `drive` | `bots::tests` (bot pair, 20 seeds) |
| View | Meshes from the race geometry, change visuals, chase camera, HUD, results, restart | `src/game/present.rs` | windowed smoke with `--screenshot` |

## Data flow and events
One direction: input -> `Race::step` -> state. `Race.events` (cleared each step) feed the log markers; the view never
consumes events, it reads state every frame (a zap is `zap_cooldown`, a boost is `kart.boost`), so several fixed
ticks per frame never lose anything.

## State and save data
- Nothing persists yet (toy tier). Unlocks will need a save file with a version field (GDD MVP tier).

## Determinism and randomness
- One seed per race (`--seed N`, shown on the results screen) picks the change schedule (`race::make_schedule`).
  Everything else is deterministic: same seed and inputs, same race, tick for tick (`the_same_seed_replays_the_same_race`).

## Budgets
| Budget | Target | Measured on | Last measured |
|---|---|---|---|
| Frame time | 16.6 ms (60 FPS) | the dev PC, release build | not yet |
| Min-spec hardware | any GPU with Vulkan or DX12 | | |

## Debug tooling
- `dev.py --debug smoke ...` shows BONK lines; markers RACE_SEED, RACE_GO, LAP, CHANGE_WARN, CHANGE_LIVE, FINISH, RACE_OVER.
- `cargo test --lib balance_report -- --ignored --nocapture`: per seed, the change schedule and how much reading it gained.
- `--autoplay reader|late|ignorer` lets a bot drive your kart; `--seed N` replays a race.

## Open questions
- Render interpolation: the sim ticks at 60 Hz; on a 120 Hz+ screen motion may look uneven (ENGINE.md gotcha).
