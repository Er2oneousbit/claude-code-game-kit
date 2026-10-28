// ---------------------------------------------------------------------------
// app.rs
// Purpose : Builds the Bevy App for each way the game runs: a normal window, a headless smoke run, a
//           windowed capture run (screenshots, recordings) and the test app. One place decides the plugins,
//           the tick rate and the smoke frame budget, so main.rs and the tests share it.
// Usage   : app::build(&cli, cfg).run()   |   tests: let mut app = app::test_app(cfg); app.update();
// Notes   : Headless = MinimalPlugins + LogPlugin + StatesPlugin + TransformPlugin + GamePlugin: no window,
//           no renderer, no GPU. Smoke and capture runs advance time by exactly one 1/60 s tick per frame
//           (TimeUpdateStrategy::ManualDuration), so N frames = N fixed ticks on any machine, as fast as it
//           can go. Normal play uses real time.
//
// Pseudocode:
//   build(cli): plugins for the mode -> fixed tick 60 Hz -> GameConfig -> GamePlugin (+ PresentPlugin with
//   a window) -> boot marker on the first frame -> (smoke) count frames in Last; capture screenshots on
//   the frames asked for; after N frames pause the game, wait for pending screenshots, print SMOKE_DONE, exit
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::path::PathBuf;
use std::time::Duration;

use bevy::app::ScheduleRunnerPlugin;
use bevy::log::LogPlugin;
use bevy::prelude::*;
use bevy::render::view::screenshot::{Screenshot, ScreenshotCaptured, save_to_disk};
use bevy::state::app::StatesPlugin;
use bevy::time::TimeUpdateStrategy;
use bevy::window::WindowResolution;

use crate::cli::Cli;
use crate::game::{GameConfig, GamePlugin, PresentPlugin, TITLE};

// ---- Tunables ------------------------------------------------------------------
pub const TICK_HZ: f64 = 60.0;
pub const WINDOW_SIZE: (u32, u32) = (1280, 720);
/// Frames to wait for screenshots still being read back from the GPU after the last smoke frame.
const CAPTURE_GRACE_FRAMES: u32 = 240;

/// One simulation tick. The fixed timestep and the manual time step are built from this same value,
/// so they are bit-identical and each smoke frame runs exactly one tick.
pub fn tick() -> Duration {
    Duration::from_secs_f64(1.0 / TICK_HZ)
}

/// The smoke run's frame budget and capture requests.
#[derive(Resource, Debug)]
struct Smoke {
    frames: u32,
    done: u32,
    screenshot: Option<PathBuf>,
    record: Option<PathBuf>,
    record_every: u32,
    record_from: u32,
    pending: u32,
    grace: u32,
}

pub fn build(cli: &Cli, cfg: GameConfig) -> App {
    let mut app = App::new();
    let log = LogPlugin {
        filter: format!(
            "wgpu=error,naga=warn,{}={}",
            env!("CARGO_CRATE_NAME"),
            if cli.debug { "debug" } else { "info" }
        ),
        ..default()
    };
    if cli.wants_window() {
        let window = Window {
            title: TITLE.into(),
            resolution: WindowResolution::new(WINDOW_SIZE.0, WINDOW_SIZE.1),
            ..default()
        };
        app.add_plugins(
            DefaultPlugins
                .set(WindowPlugin {
                    primary_window: Some(window),
                    ..default()
                })
                .set(log),
        )
        .add_plugins(PresentPlugin);
    } else {
        app.add_plugins((
            MinimalPlugins.set(ScheduleRunnerPlugin::run_loop(Duration::ZERO)),
            log,
            StatesPlugin,
            TransformPlugin,
        ));
    }
    add_game(&mut app, cfg);
    if let Some(frames) = cli.smoke {
        app.insert_resource(TimeUpdateStrategy::ManualDuration(tick()))
            .insert_resource(Smoke {
                frames,
                done: 0,
                screenshot: cli.screenshot.clone(),
                record: cli.record.clone(),
                record_every: cli.record_every,
                record_from: cli.record_from,
                pending: 0,
                grace: 0,
            })
            .add_systems(Last, smoke_budget);
    }
    app.add_systems(Update, boot_marker.run_if(run_once));
    app
}

/// The headless app the integration tests drive by hand with app.update(): no logging, no runner loop.
pub fn test_app(cfg: GameConfig) -> App {
    let mut app = App::new();
    app.add_plugins((MinimalPlugins, StatesPlugin, TransformPlugin))
        .insert_resource(TimeUpdateStrategy::ManualDuration(tick()));
    add_game(&mut app, cfg);
    app
}

fn add_game(app: &mut App, cfg: GameConfig) {
    app.insert_resource(Time::<Fixed>::from_duration(tick()))
        .insert_resource(cfg)
        .add_plugins(GamePlugin);
}

fn boot_marker() {
    // dev.py smoke requires this line: proof the game got through startup and ran a frame
    println!("BOOT_OK {} {}", env!("CARGO_PKG_NAME"), env!("CARGO_PKG_VERSION"));
}

fn smoke_budget(
    mut smoke: ResMut<Smoke>,
    mut time: ResMut<Time<Virtual>>,
    mut commands: Commands,
    mut exit: MessageWriter<AppExit>,
) {
    if smoke.done < smoke.frames {
        smoke.done += 1;
        let n = smoke.done;
        let (every, from) = (smoke.record_every, smoke.record_from);
        let due = n >= from && (n - from).is_multiple_of(every);
        if let Some(dir) = smoke.record.clone().filter(|_| due) {
            request_screenshot(&mut commands, &mut smoke, dir.join(format!("frame_{n:05}.png")));
        }
        if n == smoke.frames {
            time.pause(); // the game stops on its last frame, so the screenshot shows exactly that frame
            if let Some(path) = smoke.screenshot.clone() {
                request_screenshot(&mut commands, &mut smoke, path);
            }
        }
        return;
    }
    if smoke.pending > 0 && smoke.grace < CAPTURE_GRACE_FRAMES {
        smoke.grace += 1;
        return;
    }
    if smoke.pending > 0 {
        error!("{} screenshot(s) never arrived from the GPU", smoke.pending);
        exit.write(AppExit::from_code(1));
        return;
    }
    println!("SMOKE_DONE frames={}", smoke.frames);
    exit.write(AppExit::Success);
}

fn request_screenshot(commands: &mut Commands, smoke: &mut Smoke, path: PathBuf) {
    smoke.pending += 1;
    commands
        .spawn(Screenshot::primary_window())
        .observe(save_to_disk(path))
        .observe(|_: On<ScreenshotCaptured>, mut smoke: ResMut<Smoke>| {
            smoke.pending = smoke.pending.saturating_sub(1);
        });
}
