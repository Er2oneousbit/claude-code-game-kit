// ---------------------------------------------------------------------------
// game/mod.rs
// Purpose : The simulation plugin: holds the race (logic::race::Race) as a resource, feeds it the player's input
//           (or a bot) and the rivals' bot inputs every fixed tick, and logs scenario markers. Runs the same in a
//           window, headless (dev.py smoke) and in tests; never touches a renderer, window or keyboard.
// Usage   : app.add_plugins(GamePlugin);   game options: configure(&args) -> GameConfig
//           smoke scenario: dev.py smoke --frames 9000 --until RACE_OVER -- --autoplay reader --seed 3
// Notes   : Visuals and input live in present.rs, which reads RaceRes and writes PlayerInput.
//           Markers (info! lines, one word first): RACE_SEED, RACE_GO, LAP, CHANGE_WARN, CHANGE_LIVE, FINISH,
//           RACE_OVER (BONK at debug level: run with --debug to see them).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
pub mod present;

use bevy::prelude::*;

use crate::logic::bots::{self, Style};
use crate::logic::kart::KartInput;
use crate::logic::race::{Race, RaceEvent};

pub use present::PresentPlugin;

/// Window title and log name.
pub const TITLE: &str = "Project_Crimson_Nebula";

/// Karts in a race: the player plus three rivals.
pub const KARTS: usize = 4;
/// Rivals, kart 1 to 3: one sharp reader, one a beat late, one who never reads the track (GDD: no rubber-banding,
/// they differ only in how they read the changes).
pub const RIVALS: [Style; 3] = [Style::Reader, Style::Late, Style::Ignorer];
pub const NAMES: [&str; KARTS] = ["You", "Vex", "Nova", "Rook"];

/// Game options from the command line (everything after `--`).
#[derive(Resource, Debug, Clone, Default, PartialEq)]
pub struct GameConfig {
    /// A bot drives the player's kart (smoke scenarios, balance runs).
    pub autoplay: Option<Style>,
    /// Track-change schedule seed; None picks one from the clock (a new race each time).
    pub seed: Option<u64>,
}

pub const OPTIONS_HELP: &str = "\
Game options (after --):
  --autoplay STYLE     a bot drives your kart: reader | late | ignorer
  --seed N             replay the track changes of race N (shown on the results screen)
";

/// Reads the game's own options. An unknown option is an error, so a misspelled bot never runs silently.
pub fn configure(args: &[String]) -> Result<GameConfig, String> {
    let mut cfg = GameConfig::default();
    let mut it = args.iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--autoplay" => {
                cfg.autoplay = Some(match it.next().map(String::as_str) {
                    Some("reader") => Style::Reader,
                    Some("late") => Style::Late,
                    Some("ignorer") => Style::Ignorer,
                    other => return Err(format!("--autoplay needs reader, late or ignorer, got {other:?}")),
                })
            }
            "--seed" => {
                let value = it.next().ok_or("--seed needs a number")?;
                cfg.seed = Some(
                    value
                        .parse()
                        .map_err(|_| format!("--seed needs a whole number, got {value:?}"))?,
                );
            }
            other => return Err(format!("unknown game option {other:?}\n{OPTIONS_HELP}")),
        }
    }
    Ok(cfg)
}

/// The race in progress.
#[derive(Resource, Debug)]
pub struct RaceRes(pub Race);

/// What the player asks for this tick: present.rs writes it from the keyboard or a gamepad.
#[derive(Resource, Debug, Default, Clone, Copy, PartialEq)]
pub struct PlayerInput(pub KartInput);

/// Fixed ticks run so far: tests count ticks, never frames.
#[derive(Resource, Debug, Default)]
pub struct SimTick(pub u64);

pub struct GamePlugin;

impl Plugin for GamePlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<GameConfig>()
            .init_resource::<PlayerInput>()
            .init_resource::<SimTick>()
            .add_systems(PreStartup, start_race)
            .add_systems(FixedUpdate, race_tick);
    }
}

/// A seed from the clock, for "a new race every time".
pub fn fresh_seed() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64 % 1_000_000)
        .unwrap_or(1)
}

/// A new race on `seed` (also used by present.rs to restart).
pub fn new_race(seed: u64) -> RaceRes {
    info!("RACE_SEED {seed}");
    RaceRes(Race::new(seed, KARTS))
}

fn start_race(mut commands: Commands, cfg: Res<GameConfig>) {
    commands.insert_resource(new_race(cfg.seed.unwrap_or_else(fresh_seed)));
}

fn race_tick(
    time: Res<Time>,
    cfg: Res<GameConfig>,
    player: Res<PlayerInput>,
    mut race: ResMut<RaceRes>,
    mut tick: ResMut<SimTick>,
) {
    tick.0 += 1;
    let race = &mut race.0;
    let mut inputs = Vec::with_capacity(KARTS);
    inputs.push(match cfg.autoplay {
        Some(style) => bots::drive(race, 0, style),
        None => player.0,
    });
    for (i, style) in RIVALS.iter().enumerate().take(race.racers.len() - 1) {
        inputs.push(bots::drive(race, i + 1, *style));
    }
    race.step(&inputs, time.delta_secs());
    for event in race.events.clone() {
        log_marker(race, event);
    }
}

/// One log line per race event, starting with a marker word smoke runs can wait for (--until) or fail on.
fn log_marker(race: &Race, event: RaceEvent) {
    match event {
        RaceEvent::Go => info!("RACE_GO seed={}", race.seed),
        RaceEvent::Lap { kart, lap } => info!("LAP kart={} lap={lap}", NAMES[kart]),
        RaceEvent::ChangeWarn { change, lap } => {
            info!("CHANGE_WARN {:?} lap={lap}", race.track.changes[change])
        }
        RaceEvent::ChangeLive { change } => info!("CHANGE_LIVE {:?}", race.track.changes[change]),
        RaceEvent::Bonk { kart } => debug!("BONK kart={}", NAMES[kart]),
        RaceEvent::ItemPicked { .. } | RaceEvent::Boost { .. } => {}
        RaceEvent::Finish { kart, place, time } => {
            info!("FINISH kart={} place={place} time={time:.2}", NAMES[kart])
        }
        RaceEvent::RaceOver => {
            let order: Vec<&str> = race.standings().iter().map(|&k| NAMES[k]).collect();
            info!("RACE_OVER order={} seed={}", order.join(","), race.seed);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(list: &[&str]) -> Vec<String> {
        list.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn options_select_a_bot_and_a_seed_and_reject_typos() {
        assert_eq!(configure(&[]).unwrap(), GameConfig::default());
        let cfg = configure(&args(&["--autoplay", "late", "--seed", "42"])).unwrap();
        assert_eq!(cfg.autoplay, Some(Style::Late));
        assert_eq!(cfg.seed, Some(42));
        assert!(configure(&args(&["--autoplay"])).is_err());
        assert!(configure(&args(&["--autoplay", "right"])).is_err());
        assert!(configure(&args(&["--seed", "x"])).is_err());
        assert!(configure(&args(&["--autoply", "reader"])).is_err());
    }
}
