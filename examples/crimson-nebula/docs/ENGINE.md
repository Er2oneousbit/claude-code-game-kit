# Engine: Bevy 0.20 (Rust, ECS)

> Imported into CLAUDE.md. Keep it short. Long-form flow is in `docs/ENGINE_FLOW.md`.

## Version and setup
- **Bevy 0.20** (`Cargo.toml`: `bevy = "0.20"`; `Cargo.lock` pins the exact crates, commit it). **Rust 1.97.1+**
  (Bevy's `rust-version`), installed with rustup. Windows: Visual Studio Build Tools, workload "Desktop development
  with C++" (the MSVC linker). Linux: `libasound2-dev libudev-dev pkg-config` (verify per distro).
- **First build compiles Bevy itself:** 5 to 15 minutes and several GB in `target/`. Later builds take seconds.
- **Version:** one source, `version` in `Cargo.toml` (SOP-06). Code reads `env!("CARGO_PKG_VERSION")`; `--version`
  prints it and the BOOT_OK line carries it.
- **Game options:** everything after `--` goes to `game::configure()` (bots, seeds, cheats), so a game adds options
  without touching `main.rs`: `python tools/dev.py smoke --frames 3000 --until GOAL_REACHED -- --autoplay right`.
  `--screenshot build/shot.png` and `--record build/frames` open a window and capture PNGs
  (`--record-from 4200 --record-every 3` films one moment deep into a run).
- **Verify:** `python tools/dev.py doctor`.

## Layout
```
Cargo.toml, Cargo.lock
src/main.rs        launcher: command line -> app::build -> exit code
src/app.rs         plugin sets per run mode (window, headless smoke, capture, tests), tick rate, smoke budget
src/cli.rs         the program's own options (--smoke, --screenshot, ...)
src/logic/         engine-free rules and helpers (math, seeded Rng). Plain Rust, unit tested
src/game/mod.rs    GamePlugin: components, resources, FixedUpdate systems. Must run headless
src/game/present.rs PresentPlugin: camera, sprites, meshes, audio, keyboard -> Intent. Window only
tests/             integration tests: drive the real GamePlugin headless with app.update()
assets/            art, audio, fonts (docs/ASSET_LOG.md); Bevy loads paths relative to it
target/            build output (git-ignored)
```

## Conventions
- `snake_case` functions, modules and files, `PascalCase` types, `SCREAMING_CASE` constants (rustfmt and clippy enforce
  most of it: `dev.py check` runs both).
- **Simulation in `FixedUpdate`** (60 Hz, `app.rs` `TICK_HZ`), reading input only from a resource such as `Intent`.
  Visuals, audio and raw input in `present.rs`. That split is what lets smoke runs, bots and tests run without a GPU.
- One plugin per feature (`impl Plugin`), registered in `GamePlugin` or `PresentPlugin`. Tunables as `const` at the
  top of the module, or a `Resource` when they change at run time.
- Errors: `Result` and `?` in helpers; systems log with `error!`/`warn!` and carry on. `unwrap()` only where a failure
  is a bug (and say why in a comment): a panic kills the game.
- Tests name the behavior they guard; count `SimTick`, never frames.

## Gotchas (Claude: read before editing)
1. **Your Bevy memory is probably from an older version.** Bevy breaks its API every release (about every three
   months) and most examples online are for older ones. Before using an API, confirm it in the pinned source:
   `~/.cargo/registry/src/*/bevy_<crate>-0.20.*/` (grep it), or docs.rs for 0.20. Examples that changed recently:
   events are `Message` / `MessageWriter::write` / `MessageReader`; observers are `On<Add<Player>>` (not
   `On<Add, Player>`) with `add.entity`; the lifecycle `Replace` is now `Discard`; `Query::single` returns a `Result`.
   Moving to a new Bevy minor is a migration: follow its migration guide, one minor at a time.
2. **Query conflicts panic at startup (error B0001):** two queries in one system that touch the same component,
   one mutably, need `Without<...>` filters or a `ParamSet`. The message names the system.
3. **System order is not the order you add them.** Chain them (`.chain()`), use `.before`/`.after` or system sets
   when one reads what another writes. Unordered systems can run in any order, frame to frame.
4. **`Commands` apply later**, at the end of the schedule step: an entity spawned with `commands.spawn` is not visible
   to queries in the same system. Use observers or the next tick.
5. **Headless means no renderer:** `GamePlugin` must not use `Assets<Mesh>`, `Sprite`, cameras, `ButtonInput` or
   audio. Smoke runs and tests would panic on the missing resource. Put those in `present.rs`.
6. **`--features dev` (dynamic linking) is for development only:** it speeds up rebuilds, but a shipped exe needs the
   Bevy DLL next to it. `dev.py build` never uses it.
7. **Long first compile:** `cargo clean` or a new Bevy version means minutes of recompiling. Do not clean to "fix"
   ordinary errors; read the compiler's message (it names the file, line and usually the fix).
8. **Asset paths are relative to `assets/`** (`asset_server.load("sprites/car.png")`); a missing file logs an
   `ERROR` at run time, which fails `dev.py smoke`, but only in a window run (headless loads no assets).
9. **Do not edit** `target/` or `Cargo.lock` by hand (cargo writes it; `cargo update` changes it, which asks first).

## Generated (do not hand-edit)
`target/`, `Cargo.lock` (cargo maintains it; commit it).
