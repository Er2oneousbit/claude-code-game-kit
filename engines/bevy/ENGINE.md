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
- **The shell (SOP-19, SOP-20):** `src/shell/` is the title, main menu, settings (five tabs, every field of the
  settings schema, rebinding with conflict swaps, the one-handed layouts from `data/input/presets.json`), credits,
  loading, pause with "What now?" and the dialogue history, subtitles and menu narration, on bevy_ui. The model is
  headless (`dev.py smoke --drive menus` saves settings.json without a GPU; `tests/shell.rs` drives it); only
  `src/shell/view.rs` draws. The game runs only while Play is on top (`GameActive`), reads input from `Intent` (the shell
  fills it from the player's bindings: `dir`, `pressed` and `held` actions, the analog `stick` with the player's deadzone
  and invert_y, and `left_trigger`/`right_trigger`) and its accessibility rules from `AccessRules` and `Palette`. The
  display settings (mode, vsync, frame cap, window size) go to the window through `src/shell/display.rs`, never in
  automated runs. A panic writes `crashes/crash_<time>.txt` in the user-data folder (version, screen, error,
  backtrace, settings, log tail; `src/shell/crash.rs`). Debug builds add F8 (a `bug_<time>/` folder with a screenshot,
  the log tail, the settings and an info file), the pseudo language and "Juice demo" on the main menu
  (`src/shell/juice.rs`: every juice primitive and the access settings, live).
  `smoke --drive show:<screen> --screenshot build/x.png` pictures a screen; `python tools/access/sweep.py` runs the
  access drive. Text is Fira Mono Medium in full and the readable font Atkinson Hyperlegible with Fira Mono behind it
  (`src/shell/fonts/`, OFL, compiled into the exe); Bevy's own built-in font is ASCII only, so a font you swap in must
  cover your languages: the pseudo drive fails a character no font in the stack has, and a test checks every
  `data/i18n/` table against the font.
- **Verify:** `python tools/dev.py doctor`.

## Layout
```
Cargo.toml, Cargo.lock
src/main.rs        launcher: command line -> app::build -> exit code
src/app.rs         plugin sets per run mode (window, headless smoke, capture, tests), tick rate, smoke budget
src/cli.rs         the program's own options (--smoke, --screenshot, ...)
src/logic/         engine-free rules and helpers (math, seeded Rng). Plain Rust, unit tested
                   juice: shake, hitstop, ease, follow, input_buffer, coyote, spring (+ squash), flash_limiter
                   shell: settings, bindings (+ glyphs), save_store, i18n (+ pseudo-locale), atomic_file, auto_repeat,
                   charmap (which characters a font can draw)
                   audio: audio_director (events, voices, ducking), music_director, audio_access (sliders, arrows)
src/game/mod.rs    GamePlugin: components, resources (ScreenShake, GameActive, AccessRules, Palette), FixedUpdate
                   systems. Must run headless
src/game/present.rs PresentPlugin: camera (+ shake), sprites in the palette's colours, meshes, audio. Window only
src/shell/mod.rs   ShellPlugin: the screen stack, settings applied live, subtitles, history, narration. Headless
src/shell/screens.rs the rows and actions of every screen; view.rs draws them with bevy_ui and polls keys and pads;
                   drive.rs the scripted smoke runs; input.rs key names; store.rs the data folder; narrator.rs speech;
                   crash.rs crash files and the log tail; bug_report.rs F8; juice.rs the juice demo (debug builds)
data/i18n/         string tables (en, fr; compiled in, a new file here is picked up at start)
data/access/colours.json the colour-blind palettes;  data/input/presets.json the one-handed layouts (from the kit)
src/shell/fonts/   Fira Mono Medium (the text font) and Atkinson Hyperlegible (the readable font), both OFL; compiled
                   in with include_bytes!
src/kit_shaders.rs the kit's shader recipes as typed 2D materials (generated, with assets/shaders/kit/*.wesl)
examples/shader_check.rs renders every recipe on the GPU for `smoke --shaders`
tests/             integration tests: drive the real GamePlugin headless with app.update()
tests/golden.rs    the juice, shell and audio modules against data/golden/*.json (the kit's shared vectors)
data/golden/       golden vectors from tools/golden_vectors.py and tools/audio/wavesmith/; never edit by hand
assets/            art, audio, fonts (docs/ASSET_LOG.md); Bevy loads paths relative to it
target/            build output (git-ignored)
```

## Conventions
- `snake_case` functions, modules and files, `PascalCase` types, `SCREAMING_CASE` constants (rustfmt and clippy enforce
  most of it: `dev.py check` runs both).
- **Simulation in `FixedUpdate`** (60 Hz, `app.rs` `TICK_HZ`), reading input only from a resource such as `Intent`
  (`dir` from the held move actions, `pressed` for jump, attack, interact; the shell fills both from the bindings).
  Visuals and audio in `present.rs`, raw keys and pads in `src/shell/view.rs`. That split is what lets smoke runs, bots
  and tests run without a GPU. Say a line with `shell.say(speaker, text, bark)` (subtitles, the history), set the
  goal "What now?" shows with `shell.set_objective(text)`.
- One plugin per feature (`impl Plugin`), registered in `GamePlugin` or `PresentPlugin`. Tunables as `const` at the
  top of the module, or a `Resource` when they change at run time.
- Errors: `Result` and `?` in helpers; systems log with `error!`/`warn!` and carry on. `unwrap()` only where a failure
  is a bug (and say why in a comment): a panic kills the game.
- Tests name the behavior they guard; count `SimTick`, never frames.
- 3D models: a `.glb` from `tools/bozzetto/bozzetto.py` (in `assets/models/`) loads with the default features:
  `SceneRoot(asset_server.load("models/<name>.glb#Scene0"))` (ENGINE_FLOW; the starter itself is 2D) **(verify)**.
  A `--material vertex` model keeps its colours in glTF `COLOR_0`: check that it is not white, because Godot ignores
  them by default (#202) and Bevy is not tested here **(verify)**.
- **Shaders:** add `kit_shaders::KitShadersPlugin`, then give an entity `Mesh2d(meshes.add(Rectangle::new(w, h)))` and
  `MeshMaterial2d(materials.add(FlashMaterial { params: FlashParams { amount: 1.0, ..default() }, main: texture }))`
  (`ResMut<Assets<FlashMaterial>>`; recipes with a second picture take `aux`). Tween a parameter through
  `materials.get_mut(&handle)`. Coordinates run 0 to 1 over the mesh's UVs: `params.texel` is one over the picture's
  size in texels, `params.canvas` the size pixel parameters (`light_pos`) are given in. Textures want
  `ImageSampler::nearest()` for pixel art. Post effects (`crt`, `vignette`, `colorblind`) go on a full-screen quad
  showing a render-target image of the scene. Bevy 0.20 shaders are WESL (naga_oil and `#import` are gone);
  Bevy compiles them only when it builds a pipeline, so `check` checks the generated files and `smoke --shaders`
  compiles and renders them.

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
5. **Headless means no renderer:** `GamePlugin` and `ShellPlugin` must not use `Assets<Mesh>`, `Sprite`, cameras,
   `ButtonInput` or audio. Smoke runs and tests would panic on the missing resource. Put those in `present.rs` or
   `src/shell/view.rs`. `bevy_ui` nodes exist only with a window: `dev.py smoke --drive show:...` and `--drive access`
   open one on their own.
6. **`--features dev` (dynamic linking) is for development only:** it speeds up rebuilds, but a shipped exe needs the
   Bevy DLL next to it. `dev.py build` never uses it.
7. **Long first compile:** `cargo clean` or a new Bevy version means minutes of recompiling. Do not clean to "fix"
   ordinary errors; read the compiler's message (it names the file, line and usually the fix).
8. **Asset paths are relative to `assets/`** (`asset_server.load("sprites/car.png")`); a missing file logs an
   `ERROR` at run time, which fails `dev.py smoke`, but only in a window run (headless loads no assets).
9. **Do not edit** `target/` or `Cargo.lock` by hand (cargo writes it; `cargo update` changes it, which asks first).

## Generated (do not hand-edit)
`target/`, `Cargo.lock` (cargo maintains it; commit it), the kit_shaders module and `assets/shaders/kit/` (edit
`tools/shaders/ksl/`, then `python tools/shaders/shader_gen.py`).
