// ---------------------------------------------------------------------------
// app.rs
// Purpose : Builds the Bevy App for each way the game runs: a normal window, a headless smoke run, a
//           windowed capture run (screenshots, recordings) and the test app. One place decides the plugins,
//           the tick rate and the smoke frame budget, so main.rs and the tests share it.
// Usage   : app::build(&cli, cfg).run()   |   tests: let mut app = app::test_app(cfg); app.update();
//           (app::smoke_test_app(cfg, n) adds the smoke frame budget, for tests of the smoke run itself)
// Notes   : Headless = MinimalPlugins + LogPlugin + StatesPlugin + TransformPlugin + GamePlugin: no window,
//           no renderer, no GPU. Smoke and capture runs advance time by exactly one 1/60 s tick per frame
//           (TimeUpdateStrategy::ManualDuration), so N frames = N fixed ticks on any machine, as fast as it
//           can go. The very first update only starts the clock (zero delta, no tick), so the smoke budget
//           does not count it: frame n is tick n, and --record names frames the same way. Normal play uses
//           real time.
//
// Pseudocode:
//   build(cli): plugins for the mode -> fixed tick 60 Hz -> GameConfig -> GamePlugin (+ PresentPlugin with
//   a window) -> boot marker on the first frame -> (smoke) skip the clock-priming update, then count
//   frames in Last; capture screenshots on the frames asked for; after N frames pause the game, wait for
//   pending screenshots, print FRAME_TIMES (the real time between smoke frames, #90) and SMOKE_DONE, exit
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-30 with Claude (Opus 5.5, claude-opus-5-5): the smoke budget skips the clock-priming
//           update (--smoke 120 ran 119 ticks); smoke_test_app for the headless test of that
//           2026-11-09 with Claude (Fable 5.1, claude-fable-5-1): the shell (ShellPlugin always, ShellViewPlugin
//           with a window), the drive in smoke runs, a drive may end the run early (Smoke::finish_now)
//           2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): the log keeps a tail for crash files and bug
//           reports (shell/crash.rs, #275)
//           2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): a failed drive still gets its --screenshot, of the
//           frame it stopped on (Smoke::finish_failed, #276)
// ---------------------------------------------------------------------------
use std::path::PathBuf;
use std::time::{Duration, Instant};

use bevy::app::ScheduleRunnerPlugin;
use bevy::log::LogPlugin;
use bevy::prelude::*;
use bevy::render::view::screenshot::{Screenshot, ScreenshotCaptured, save_to_disk};
use bevy::state::app::StatesPlugin;
use bevy::time::TimeUpdateStrategy;
use bevy::window::WindowResolution;

use crate::cli::Cli;
use crate::game::{GameConfig, GamePlugin, PresentPlugin, TITLE};
use crate::shell::ShellPlugin;
use crate::shell::drive::Drive;
use crate::shell::view::ShellViewPlugin;

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
pub struct Smoke {
    frames: u32,
    /// The first update only starts the clock (zero delta, no fixed tick): it is not a smoke frame.
    primed: bool,
    done: u32,
    screenshot: Option<PathBuf>,
    record: Option<PathBuf>,
    record_every: u32,
    record_from: u32,
    pending: u32,
    grace: u32,
    /// The run's exit code once the last frame is through: 0, or a failed drive's (finish_failed).
    exit_code: u8,
    /// Wall-clock time between smoke frames, for the FRAME_TIMES line dev.py smoke reports (#90).
    clock: FrameClock,
    /// What the frame times measure: "logic" headless (nothing drawn), "render" with a window.
    mode: &'static str,
}

/// The real time each smoke frame took (the game's clock is stepped by hand, so it cannot tell).
#[derive(Debug, Default)]
struct FrameClock {
    last: Option<Instant>,
    times_ms: Vec<f64>,
}

/// The App for this command line. `drive` is the scripted scenario a smoke run follows ("default" walks into the
/// game); a window opens for a normal run, a capture, and a drive that measures or pictures the screen.
pub fn build(cli: &Cli, cfg: GameConfig, drive: Option<Drive>) -> App {
    let mut app = App::new();
    let log = LogPlugin {
        filter: format!(
            "wgpu=error,naga=warn,{}={}",
            env!("CARGO_CRATE_NAME"),
            if cli.debug { "debug" } else { "info" }
        ),
        custom_layer: crate::shell::crash::log_layer, // the last lines, for crash files and F8 bug reports
        ..default()
    };
    let window = cli.wants_window() || cfg.needs_window();
    if window {
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
        .add_plugins((PresentPlugin, ShellViewPlugin));
    } else {
        app.add_plugins((
            MinimalPlugins.set(ScheduleRunnerPlugin::run_loop(Duration::ZERO)),
            log,
            StatesPlugin,
            TransformPlugin,
        ));
    }
    add_game(&mut app, cfg);
    app.add_plugins(ShellPlugin);
    if let Some(drive) = drive {
        app.insert_resource(drive);
    }
    if let Some(frames) = cli.smoke {
        app.insert_resource(TimeUpdateStrategy::ManualDuration(tick()));
        add_smoke(
            &mut app,
            Smoke {
                screenshot: cli.screenshot.clone(),
                record: cli.record.clone(),
                record_every: cli.record_every,
                record_from: cli.record_from,
                mode: if window { "render" } else { "logic" },
                ..Smoke::budget(frames)
            },
        );
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

/// test_app plus the smoke frame budget (no captures): it exits after `frames` frames, as `--smoke` does.
pub fn smoke_test_app(cfg: GameConfig, frames: u32) -> App {
    let mut app = test_app(cfg);
    add_smoke(&mut app, Smoke::budget(frames));
    app
}

/// test_app plus the shell (headless: the screens, settings and drives without a window), for tests/shell.rs.
/// With a drive name the scenario runs and its DRIVE_DONE ends the run through a smoke budget of `frames`.
pub fn shell_test_app(cfg: GameConfig, drive: Option<(&str, u32)>) -> App {
    let mut app = test_app(cfg);
    app.add_plugins(ShellPlugin);
    if let Some((name, frames)) = drive {
        app.insert_resource(Drive::new(name).expect("a known drive"));
        add_smoke(&mut app, Smoke::budget(frames));
    }
    app
}

impl Smoke {
    /// A drive finished: the next frame is the run's last (its screenshot, SMOKE_DONE, exit 0).
    pub fn finish_now(&mut self) {
        self.frames = self.done + 1;
    }

    /// A drive failed with `code`: when a screenshot was asked for, the next frame is still the run's last, so the
    /// picture shows where the drive stopped (#276), then the run exits with `code`. False (nothing changed) when
    /// there is no picture to take: the caller exits now.
    pub fn finish_failed(&mut self, code: u8) -> bool {
        if self.screenshot.is_none() {
            return false;
        }
        self.exit_code = code;
        self.finish_now();
        true
    }

    fn budget(frames: u32) -> Self {
        Smoke {
            frames,
            primed: false,
            done: 0,
            screenshot: None,
            record: None,
            record_every: 1,
            record_from: 1,
            pending: 0,
            grace: 0,
            exit_code: 0,
            clock: FrameClock::default(),
            mode: "logic",
        }
    }
}

fn add_smoke(app: &mut App, smoke: Smoke) {
    app.insert_resource(smoke).add_systems(Last, smoke_budget);
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
    let now = Instant::now();
    if !smoke.primed {
        smoke.primed = true; // the clock-priming update ran no tick: frame 1 is the next one
        smoke.clock.last = Some(now);
        return;
    }
    if smoke.done < smoke.frames {
        if let Some(last) = smoke.clock.last {
            smoke.clock.times_ms.push(now.duration_since(last).as_secs_f64() * 1000.0);
        }
        smoke.clock.last = Some(now);
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
    if smoke.exit_code != 0 {
        exit.write(AppExit::from_code(smoke.exit_code)); // a failed drive's last frame, pictured (#276)
        return;
    }
    let frames = frame_times_line(&smoke.clock.times_ms, smoke.mode);
    if !frames.is_empty() {
        println!("{frames}"); // dev.py smoke reports it and checks --frame-budget (#90)
    }
    println!("SMOKE_DONE frames={}", smoke.frames);
    exit.write(AppExit::Success);
}

/// The FRAME_TIMES line for these frame times in ms ("" when there are none): mean, nearest-rank p95 and p99, worst,
/// the same rule as every engine's line.
pub fn frame_times_line(times_ms: &[f64], mode: &str) -> String {
    if times_ms.is_empty() {
        return String::new();
    }
    let mut sorted = times_ms.to_vec();
    sorted.sort_by(|a, b| a.total_cmp(b));
    let n = sorted.len();
    let rank = |q: f64| sorted[((q * n as f64).ceil() as usize).clamp(1, n) - 1];
    let mean = sorted.iter().sum::<f64>() / n as f64;
    format!(
        "FRAME_TIMES frames={n} mean={mean:.2} p95={:.2} p99={:.2} worst={:.2} mode={mode}",
        rank(0.95),
        rank(0.99),
        sorted[n - 1]
    )
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_failed_drive_gets_its_screenshot_frame_only_when_one_was_asked_for() {
        // #276: the sweep keeps a failed run's last frame; a run without --screenshot still exits at once
        let mut smoke = Smoke::budget(6000);
        smoke.done = 40;
        assert!(!smoke.finish_failed(1), "no --screenshot: the caller exits now");
        assert_eq!((smoke.frames, smoke.exit_code), (6000, 0));
        smoke.screenshot = Some(PathBuf::from("last.png"));
        assert!(smoke.finish_failed(1));
        assert_eq!((smoke.frames, smoke.exit_code), (41, 1), "one more frame, then exit 1");
    }

    #[test]
    fn frame_times_line_is_what_dev_py_reads() {
        // #90: nearest-rank percentiles, in any order
        let ms: Vec<f64> = (1..=100).rev().map(f64::from).collect();
        assert_eq!(
            frame_times_line(&ms, "logic"),
            "FRAME_TIMES frames=100 mean=50.50 p95=95.00 p99=99.00 worst=100.00 mode=logic"
        );
        assert_eq!(
            frame_times_line(&[16.0, 17.0, 40.0], "render"),
            "FRAME_TIMES frames=3 mean=24.33 p95=40.00 p99=40.00 worst=40.00 mode=render"
        );
        assert_eq!(frame_times_line(&[], "logic"), "");
    }
}

// {{FOOTER}}
