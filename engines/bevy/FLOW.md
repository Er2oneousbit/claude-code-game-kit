# Bevy Flow

Engine-specific workflow for a Bevy 0.20 game in Rust. Universal process lives in `docs/sop/`.

> **Tested.** On Windows 11 (2026-10-28) with Rust 1.99.1 (MSVC, VS 2022 Build Tools) and Bevy 0.20.0: `doctor`, `check`, `test`,
> `smoke` (headless; `--until`, `--fail-on`, game options, `--screenshot` and `--record` in a window), `build` (the release exe
> ran from a clean folder), `run` (window opened on Vulkan, `BOOT_OK`), `clean` (refuses a shared target folder without `--yes`), and
> planted failures: compile error, failing test, unformatted code, `error!` at boot, a panic mid-run, a bad game option (exit 2).
> First build 14.5 minutes on an 8-core Ryzen 7 5700G; the first release build about as long again. Linux and macOS untested.
> Anything marked **(verify)** is the likeliest to need tweaks. Paste errors to Claude verbatim.

## One-time setup
1. Install Rust with rustup: https://rustup.rs (Windows: run `rustup-init.exe`, accept the defaults; it installs the
   stable toolchain with `cargo`, `clippy` and `rustfmt`). Open a **new** terminal afterwards so `PATH` has
   `~/.cargo/bin`.
2. Windows: Build Tools for Visual Studio (workload "Desktop development with C++"); rustup offers to install it when
   it is missing **(verify)**. Linux: `sudo apt install libasound2-dev libudev-dev pkg-config` (Debian/Ubuntu; others (verify)).
3. `python tools/dev.py doctor`, then `python tools/dev.py check`. The first build compiles Bevy: 5 to 15 minutes.
4. Optional, VS Code: the rust-analyzer extension (recommended in `.vscode/extensions.json`). It builds into its own
   folder (`.vscode/settings.json`), so it does not lock `target/` while dev.py builds.

## Daily loop
```
python tools/dev.py check     # cargo fmt --check, then clippy on every target
python tools/dev.py test      # cargo test: logic/ unit tests and tests/ headless App tests
python tools/dev.py smoke     # 120 headless frames, fail on errors or a panic
python tools/dev.py run       # play it in a window (Esc quits)
python tools/dev.py build     # release exe
```
Formatting: `cargo fmt` fixes what `check` complains about.

## Mapped to cargo
| dev.py | What it runs |
|---|---|
| `check` | `cargo fmt --check`, then `cargo clippy --all-targets` (or `cargo check` without clippy) |
| `test` | `cargo test --no-run` (shows compile progress), then `cargo test`; counts the `test result` lines |
| `smoke` | `cargo build`, then `cargo run -- --smoke N [--screenshot F] [--record D] -- --data-dir build/smoke-data [--drive X] [--locale L] [game options]`; needs `BOOT_OK` and `SMOKE_DONE` (and `DRIVE_DONE` with a drive), fails on ` ERROR ` lines, `panicked at` and a non-zero exit; echoes the drives' proof lines (`SETTINGS_WRITTEN`, `CRASH_WRITTEN`, `PSEUDO_*`, `DRIVE_*`, `ACCESS_*`); a panic names its crash file |
| `build` | `cargo build --release`, prints the exe path |
| `run` | `cargo build`, then `cargo run [-- game options]` |
| `clean` | deletes the target folder (asks first when `CARGO_TARGET_DIR` points outside the project) |

`--release` (before or after the command) switches check, test, smoke and run to the optimized build.

## How the smoke run works
`--smoke N` without capture options builds a headless App (`app.rs`): `MinimalPlugins`, logging, states, transforms
and `GamePlugin`, no window and no renderer. Time advances exactly one 1/60 s tick per frame
(`TimeUpdateStrategy::ManualDuration`), so 3000 frames are 50 seconds of game time, run as fast as the CPU allows,
the same on every machine. After the last frame the game prints `SMOKE_DONE` and exits.
With `--screenshot` or `--record` the run opens a window (it needs the renderer), still ticks exactly once per frame,
pauses on the last frame, waits for the GPU to hand back the pictures, then exits. Frames are PNG;
`python tools/art/frames_to_gif.py build/frames out.gif` makes a GIF.

Every smoke run follows a scripted scenario through the shell's screens (`src/shell/drive.rs`); without `--drive` it
walks title -> menu -> play and lets the game run, so `--until GOAL_REACHED -- --autoplay right` still works. The
game's files (settings.json) go to a fresh `build/smoke-data/` unless `--data-dir` names a folder, never to the
player's own. A `--data-dir` inside cargo's target folder (`target/` or `CARGO_TARGET_DIR`) is refused (exit 2): the
shipped exe lives there. Scenarios:

| `--drive` | What it does | Window |
|---|---|---|
| `menus` | title -> settings: master volume 0.5, reduce motion on -> back (saves) -> quit; prints `SETTINGS_WRITTEN <path>` once the file holds the values | no |
| `crash` | a planted panic on the main menu: prints `CRASH_WRITTEN <path>` and fails on purpose (exit 101) | no |
| `pseudo` | with `--locale pseudo`: visits every screen (each settings tab at its top and scrolled to its end, the rebind prompt, credits, the juice demo and a hit in it, loading, play, pause, "What now?", the history) and checks every visible label: not in brackets (it did not go through `t()`; names from CREDITS.md are exempt), wider than its box, or past the window's edge. `PSEUDO_SCREEN` per screen, `PSEUDO_FAIL` per problem, then `PSEUDO_PASS` or `PSEUDO_FAILED` and exit 1 | yes |
| `pseudo-plant` | the same with one planted label too small for its text: must fail naming `plant.too_small` | yes |
| `bug` | presses F8 on the main menu (debug builds) and checks the `bug_<time>/` files: `DRIVE_BUG <path>` | yes |
| `show:<screen>` | opens `title`, `main_menu`, `settings`, `pause`, `help`, `history`, `credits`, `subtitle` or `juice` (a hit landed: flash, ring, squash), then ends; add `--screenshot build/x.png` | yes |
| `access[:res=WxH,scale=N,pad,read]` | the accessibility sweep's tour: every screen measured (`ACCESS_SCREEN`), the one-handed layout applied and reset, the subtitle hold, the prompts' device; `python tools/access/sweep.py` runs the four standard runs | yes |

A drive that cannot finish (a menu that never opens, an item it cannot focus) logs an `ERROR` line naming the step
and exits 1. `--locale pseudo` runs the whole shell in the pseudo-locale. The juice demo, F8 and the pseudo language
exist in debug builds only, so `bug` and `show:juice` refuse `--release`; the access tour visits the juice demo in
debug builds.

The player's files: `settings.json`, `crashes/crash_<time>.txt` (written by the panic hook in `src/shell/crash.rs`:
version, build, screen, locale, the error and where, the backtrace, the settings, the last 60 log lines) and
`bug_<time>/` (F8 in a debug build: `bug_<time>/info.txt`, `bug_<time>/log_tail.txt`, the settings and a screenshot; no screenshot
headless). In a smoke run they land in `build/smoke-data/`.

## Testing
- `src/logic/`: plain `#[test]` functions next to the code (`#[cfg(test)] mod tests`).
- `tests/golden.rs`: replays every case in `data/golden/juice.json` and `shell.json` through the juice and shell
  modules (one test per case type; `cargo test --test golden -- --nocapture` prints the counts). To change their
  behavior, change `tools/golden_vectors.py` first, run it with `--write`, then fix `src/logic/` until this passes.
  `audio.json`, `music.json` and `access.json` check the audio modules the same way (`audio_director`,
  `music_director`, `audio_access`); their references are in `tools/audio/wavesmith/`, and each file is written by
  its own command: `python tools/audio/wavesmith/wavesmith.py events vectors --write` (audio.json), then
  `music vectors --write` and `access vectors --write` the same way.
- `tests/*.rs`: integration tests that use `app::test_app(GameConfig)`, call `app.update()` and read the world
  (`app.world_mut().query_filtered::<&Transform, With<Player>>()`). Set input by writing the `Intent` resource,
  or pick a bot through `GameConfig`. `tests/shell.rs` uses `app::shell_test_app` (the shell on the headless App)
  and `shell.inject("ui_down")` to walk the screens; `GameConfig.data_dir` gives each test its own settings folder.
- A bot is an `Autoplay` mode: a system that writes `Intent`. Scenario markers (`GOAL_REACHED`) are `info!` lines;
  `dev.py smoke --until` and `--fail-on` look for them (SOP-14 for bot pairs that prove a design idea).

## Adding a feature
1. A new module under `src/game/` with its own `Plugin`; add it in `GamePlugin::build` (simulation) or
   `PresentPlugin::build` (visuals, input, audio).
2. Rules that need no ECS go in `src/logic/` with unit tests.
3. A new crate: `cargo add <name>` (asks first), write an `/adr`, check that its Bevy version matches 0.20 (Bevy
   plugins pin a Bevy minor; a mismatch shows as two `bevy_ecs` versions and confusing trait errors).

## Assets and audio
- Files under `assets/`, loaded with `Res<AssetServer>` in `present.rs`: `asset_server.load("sprites/car.png")`.
  Bevy reads PNG, glTF (`.glb`), OGG and WAV out of the box (default features).
- Audio: `AudioPlayer::new(asset_server.load("audio/sfx_engine.ogg"))` (verify the playback settings API for 0.20).
- Naming: `spr_car_red.png`, `sfx_skid_01.wav`, `mus_race.ogg`, `fnt_ui.ttf`. Sources and licenses:
  `docs/RESOURCES.md`, `docs/ASSET_LOG.md`.
- 3D: export `.glb` (Blender scripts in `tools/blender/`), spawn with `SceneRoot(asset_server.load("models/car.glb#Scene0"))`
  (verify the label syntax for 0.20).

## Profiling
- Measure in `--release`. Frame time: add `FrameTimeDiagnosticsPlugin` and `LogDiagnosticsPlugin` in `present.rs`.
- Deeper: Tracy through Bevy's `trace_tracy` feature (verify), or the OS profiler. See SOP-10.

## Packaging (release)
1. `python tools/dev.py build` -> `target/release/<game>.exe`.
2. Ship the exe with the `assets/` folder next to it, plus license files. Release builds hide the console window on
   Windows (`windows_subsystem` in `main.rs`).
3. Run it from a clean folder on a machine without Rust (SOP-06).
4. Web (WASM): possible with `wasm32-unknown-unknown` and a tool such as trunk or wasm-bindgen-cli, not wired into
   dev.py yet (verify; an ADR when you need it).

## Adopting an existing project
Keep your `Cargo.toml` and merge from `Cargo.toml.gold`: the `[profile.dev]` lines and the `dev` feature. dev.py needs
the binary to accept `--smoke N`, print `BOOT_OK` on its first frame and `SMOKE_DONE` after the last; `src/app.rs` and
`src/cli.rs` show the pattern to copy.

## Common errors
| Symptom | Likely cause | Fix |
|---|---|---|
| `error[E0432]: unresolved import` / `cannot find type` for a Bevy item | API from another Bevy version | Gotcha 1: grep the 0.20 source, read the migration guide |
| Panic `error[B0001]` at startup | two queries conflict | `Without<...>` filters or a `ParamSet` (gotcha 2) |
| `Resource requested by ... does not exist` in smoke or tests | a window-only resource in GamePlugin | move that system to `present.rs` (gotcha 5) |
| `linker link.exe not found` (Windows) | MSVC build tools missing | install Build Tools, C++ workload |
| `failed to remove file ... Access is denied` | the game or rust-analyzer still running | close it, build again |
| Two versions of `bevy_ecs` in `cargo tree -d` | a plugin crate built for another Bevy | pick the plugin release made for 0.20 |
| Window opens and closes, exit code 101 | a panic | read the `panicked at` line; run with `--debug` |

## Field notes (reported, unverified)
None recorded yet. Add notes from videos, forums or your own runs here, with an `E##` id in `docs/EVIDENCE.md`.
