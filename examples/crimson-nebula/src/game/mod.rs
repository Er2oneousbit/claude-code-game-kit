// ---------------------------------------------------------------------------
// game/mod.rs
// Purpose : The simulation plugin: holds the race (logic::race::Race) as a resource, feeds it the player's input
//           (or a bot) and the rivals' bot inputs every fixed tick, and logs scenario markers. Runs the same in a
//           window, headless (dev.py smoke) and in tests; never touches a renderer, window or keyboard.
// Usage   : app.add_plugins(GamePlugin);   game options: configure(&args) -> GameConfig
//           smoke scenario: dev.py smoke --frames 9000 --until RACE_OVER -- --autoplay reader --seed 3
// Notes   : Visuals live in present.rs, which reads RaceRes. Input arrives only through the Intent resource: the
//           shell (src/shell/) fills it from the player's bindings and the pad (#265): the right and left triggers
//           are analog gas and brake, the left stick steers by how far it leans, the keys and d-pad (move_*) are
//           the digital fallback, jump held = drift, attack = use the item. race_requests below asks for a new race
//           (RestartRequest) when Play is entered or the results get a press. The race ticks only while
//           GameActive is true (Play on top of the shell: never under the title, the menus or the pause screen).
//           AccessRules.game_speed scales the tick (SOP-20); Palette and ScreenShake follow the settings (present.rs
//           reads them). Markers (info! lines, one word first): RACE_SEED, RACE_GO, LAP, CHANGE_WARN, CHANGE_LIVE,
//           FINISH, RACE_OVER (BONK at debug level: run with --debug to see them).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-10 with Claude (Fable 5.1, claude-fable-5-1): the kit's shell (#168): Intent replaces
//           PlayerInput, GameActive gates the race, AccessRules, Palette, ScreenShake (a bonk rattles the camera),
//           the shell's options (--drive, --data-dir, --locale), the restart moved here from present.rs
//           2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): kit 0.14.4: analog gas, brake and steering from the
//           kit's Intent (stick, triggers, held actions, #265); the restart is its own resource (RestartRequest);
//           the new drives (crash, pseudo, pseudo-plant, bug, show:juice)
// ---------------------------------------------------------------------------
pub mod present;

use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;

use bevy::prelude::*;

use crate::logic::bots::{self, Style};
use crate::logic::kart::KartInput;
use crate::logic::race::{Phase, Race, RaceEvent};
use crate::logic::shake::Shake;
use crate::shell::{ScreenName, Shell};

pub use present::PresentPlugin;

/// Window title and log name.
pub const TITLE: &str = "Project_Crimson_Nebula";

/// Karts in a race: the player plus three rivals.
pub const KARTS: usize = 4;
/// Rivals, kart 1 to 3: one sharp reader, one a beat late, one who never reads the track (GDD: no rubber-banding,
/// they differ only in how they read the changes).
pub const RIVALS: [Style; 3] = [Style::Reader, Style::Late, Style::Ignorer];
pub const NAMES: [&str; KARTS] = ["You", "Vex", "Nova", "Rook"];

// ---- Input mapping (the kit's actions -> the kart) -----------------------------
/// The held game action that drifts (Space, pad south by default; rebindable in Settings > Controls): read with
/// Intent::is_held.
pub const DRIFT_ACTION: &str = "jump";
/// The pressed game action that uses the item (J, pad west by default).
pub const ITEM_ACTION: &str = "attack";
/// Any of these on the results screen starts a new race.
pub const RESTART_ACTIONS: [&str; 3] = ["jump", "attack", "interact"];
/// Intent.dir from the keys or d-pad is a unit vector (a diagonal is 0.707 per axis): anything past this counts as
/// the full axis, so key gas and steering stay digital like the keys they come from. The stick and the triggers
/// are read as they are (analog).
const AXIS_ON: f32 = 0.3;
/// Trauma a bump adds to the screen shake (present.rs rattles the chase camera by it; 0 with reduce motion).
pub const BONK_TRAUMA: f64 = 0.35;

/// Game options from the command line (everything after `--`).
#[derive(Resource, Debug, Clone, Default, PartialEq)]
pub struct GameConfig {
    /// A bot drives the player's kart (smoke scenarios, balance runs).
    pub autoplay: Option<Style>,
    /// Track-change schedule seed; None picks one from the clock (a new race each time).
    pub seed: Option<u64>,
    /// A scripted smoke scenario (shell/drive.rs): menus, crash, pseudo, pseudo-plant, bug, access[:opts],
    /// show:<screen>.
    pub drive: Option<String>,
    /// Where settings and saves go (dev.py smoke always sets it, so a test never touches the player's files).
    pub data_dir: Option<PathBuf>,
    /// The language for this run ("pseudo" = the pseudo-locale), over the settings.
    pub locale: Option<String>,
    /// A smoke run: no quitting the process from the menus, no speech, no window mode changes.
    pub automated: bool,
}

impl GameConfig {
    /// Does the run need a window even with --smoke? (show: captures a picture, access measures drawn text.)
    pub fn needs_window(&self) -> bool {
        self.drive.as_deref().is_some_and(crate::shell::drive::needs_window)
    }
}

pub const OPTIONS_HELP: &str = "\
Game options (after --):
  --autoplay STYLE     a bot drives your kart: reader | late | ignorer
  --seed N             replay the track changes of race N (shown on the results screen)
  --drive NAME         with --smoke: a scripted path through the shell (menus, crash, pseudo, pseudo-plant, bug,
                       access[:res=WxH,scale=N,pad,read],
                       show:<title|main_menu|settings|pause|help|history|credits|subtitle|juice>); dev.py smoke --drive
  --data-dir DIR       settings and saves go here (dev.py smoke passes a fresh build/smoke-data)
  --locale LANG        language for the run (pseudo = the pseudo-locale)
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
            "--drive" => {
                let name = it.next().ok_or("--drive needs a scenario name")?;
                crate::shell::drive::validate(name)?;
                cfg.drive = Some(name.clone());
            }
            "--data-dir" => cfg.data_dir = Some(PathBuf::from(it.next().ok_or("--data-dir needs a folder")?)),
            "--locale" => cfg.locale = Some(it.next().ok_or("--locale needs a language")?.clone()),
            other => return Err(format!("unknown game option {other:?}\n{OPTIONS_HELP}")),
        }
    }
    Ok(cfg)
}

/// The race in progress.
#[derive(Resource, Debug)]
pub struct RaceRes(pub Race);

/// What the player wants this tick. The shell (from the bindings) or a bot writes it; the simulation only reads it.
/// Everything is zero or empty while the game is not active (menus, pause).
#[derive(Resource, Debug, Default, Clone, PartialEq)]
pub struct Intent {
    /// Desired direction, length 0 to 1: the held move_* actions (keys, d-pad) plus the analog `stick`, so keyboard
    /// play gives unit directions and a half-leaned stick gives half. Up is gas, down is brake, x steers.
    pub dir: Vec2,
    /// Game actions pressed this frame (jump, attack, interact), auto-repeats included.
    pub pressed: Vec<String>,
    /// Game actions held right now (no ui_*): the drift button. The left stick past the deadzone also holds
    /// move_left/right/up/down here, invert_y honoured.
    pub held: BTreeSet<String>,
    /// The left stick, deadzone (input.deadzone, radial, rescaled) and input.invert_y applied: each axis -1 to 1,
    /// up is +y. Zero without a pad.
    pub stick: Vec2,
    /// The analog triggers, 0 at rest to 1 fully in (logic::analog::TRIGGER_DEADZONE applied): brake and gas.
    pub left_trigger: f32,
    pub right_trigger: f32,
}

impl Intent {
    /// Is this game action held right now?
    pub fn is_held(&self, action: &str) -> bool {
        self.held.contains(action)
    }

    /// Was this game action pressed this frame?
    pub fn just_pressed(&self, action: &str) -> bool {
        self.pressed.iter().any(|a| a == action)
    }

    /// The kart input the intent asks for. Gas is the right trigger, brake the left one, each at least what the
    /// keys, d-pad or stick ask (a held key counts as fully in); throttle = gas - brake, so both at once coast.
    /// Steering follows the stick's lean while it leans (analog), else the keys or d-pad (full lock). Drift is
    /// held, the item goes on its press.
    pub fn kart_input(&self) -> KartInput {
        // per axis: the stick while it leans on that axis, else dir (keys and d-pad, or a writer that sets only
        // dir, like the headless tests) made digital
        let y = if self.stick.y != 0.0 {
            self.stick.y
        } else {
            axis(self.dir.y)
        };
        let gas = self.right_trigger.max(y.max(0.0));
        let brake = self.left_trigger.max((-y).max(0.0));
        let steer = if self.stick.x != 0.0 {
            -self.stick.x
        } else {
            -axis(self.dir.x)
        };
        KartInput {
            throttle: (gas - brake).clamp(-1.0, 1.0),
            steer: steer.clamp(-1.0, 1.0),
            drift: self.is_held(DRIFT_ACTION),
            use_item: self.just_pressed(ITEM_ACTION),
        }
    }
}

fn axis(v: f32) -> f32 {
    if v > AXIS_ON {
        1.0
    } else if v < -AXIS_ON {
        -1.0
    } else {
        0.0
    }
}

/// Start a new race (entering Play from the menus, or a press on the results): acted on once per rising edge.
/// race_requests sets it from the shell every frame; nothing sets it without the shell (the headless tests).
#[derive(Resource, Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct RestartRequest(pub bool);

/// Fixed ticks run so far: tests count ticks, never frames.
#[derive(Resource, Debug, Default)]
pub struct SimTick(pub u64);

/// The simulation runs only while this is true: the shell clears it on every screen but Play (menus, pause).
/// Without the shell (tests) it stays true.
#[derive(Resource, Debug, Clone, Copy, PartialEq, Eq)]
pub struct GameActive(pub bool);

impl Default for GameActive {
    fn default() -> Self {
        GameActive(true)
    }
}

/// The accessibility rules the game reads (SOP-20); the shell keeps them in step with the settings.
#[derive(Resource, Debug, Clone, PartialEq)]
pub struct AccessRules {
    /// 0.5 to 1: multiply the simulation's dt (access.game_speed).
    pub game_speed: f64,
    /// 1 to 3: multiply timing windows (coyote time, input buffers, parry windows) by it (access.timing_scale).
    pub timing_scale: f64,
    pub auto_repeat: bool,
    /// Keep flashes to three a second (logic::flash_limiter) when true.
    pub flash_limit: bool,
    pub reduce_motion: bool,
}

impl Default for AccessRules {
    fn default() -> Self {
        AccessRules {
            game_speed: 1.0,
            timing_scale: 1.0,
            auto_repeat: false,
            flash_limit: true,
            reduce_motion: false,
        }
    }
}

/// The colours the game tells apart, by name, for the current colour-blind setting (data/access/colours.json).
/// present.rs asks it for "hit" (a lane closing) and "target" (a shortcut opening) when a colour-blind mode is on;
/// a name it lacks gets the fallback you pass.
#[derive(Resource, Debug, Clone, Default)]
pub struct Palette(pub BTreeMap<String, Color>);

impl Palette {
    pub fn get(&self, name: &str, fallback: Color) -> Color {
        self.0.get(name).copied().unwrap_or(fallback)
    }
}

/// Screen shake: a bump adds trauma here; present.rs rattles the chase camera by it.
/// `intensity` follows logic::settings::effective_shake (0 with reduce motion) through the shell.
#[derive(Resource, Debug)]
pub struct ScreenShake {
    pub shake: Shake,
    pub intensity: f64,
}

impl Default for ScreenShake {
    fn default() -> Self {
        ScreenShake {
            shake: Shake::default(),
            intensity: 1.0,
        }
    }
}

pub struct GamePlugin;

impl Plugin for GamePlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<GameConfig>()
            .init_resource::<Intent>()
            .init_resource::<RestartRequest>()
            .init_resource::<SimTick>()
            .init_resource::<GameActive>()
            .init_resource::<AccessRules>()
            .init_resource::<Palette>()
            .init_resource::<ScreenShake>()
            .add_systems(PreStartup, start_race)
            .add_systems(
                RunFixedMainLoop,
                race_requests.in_set(RunFixedMainLoopSystems::BeforeFixedMainLoop),
            )
            .add_systems(FixedUpdate, (restart_race, race_tick.run_if(game_active)).chain());
    }
}

fn game_active(active: Res<GameActive>) -> bool {
    active.0
}

/// A seed from the clock, for "a new race every time".
pub fn fresh_seed() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64 % 1_000_000)
        .unwrap_or(1)
}

/// A new race on `seed`.
pub fn new_race(seed: u64) -> RaceRes {
    info!("RACE_SEED {seed}");
    RaceRes(Race::new(seed, KARTS))
}

fn start_race(mut commands: Commands, cfg: Res<GameConfig>) {
    commands.insert_resource(new_race(cfg.seed.unwrap_or_else(fresh_seed)));
}

/// A restart, read from the shell (absent in the headless tests): when Play is being entered from the menus
/// (Loading on top) or the results get a press. The press is read from the shell itself, so it works under
/// --autoplay too (the shell drops presses from Intent for bots).
fn race_requests(shell: Option<Res<Shell>>, race: Res<RaceRes>, mut restart: ResMut<RestartRequest>) {
    let Some(shell) = shell else {
        return;
    };
    let entering_play = shell.top_name() == Some(ScreenName::Loading);
    let again = race.0.phase == Phase::Over && shell.game_pressed.iter().any(|a| RESTART_ACTIONS.contains(&a.as_str()));
    restart.0 = entering_play || again;
}

/// A rising edge of RestartRequest starts a new race: on the seed asked for when Play is entered from the menus
/// (so --seed N replays race N each time), on a fresh seed after the results ("race again"). Not gated on
/// GameActive: the Loading screen is where the menus' restart happens.
fn restart_race(
    mut was: Local<bool>,
    restart: Res<RestartRequest>,
    cfg: Res<GameConfig>,
    race: Res<RaceRes>,
    mut commands: Commands,
) {
    let rising = restart.0 && !*was;
    *was = restart.0;
    if !rising {
        return;
    }
    let seed = if race.0.phase == Phase::Over {
        fresh_seed()
    } else {
        cfg.seed.unwrap_or_else(fresh_seed)
    };
    commands.insert_resource(new_race(seed));
}

fn race_tick(
    time: Res<Time>,
    cfg: Res<GameConfig>,
    intent: Res<Intent>,
    rules: Res<AccessRules>,
    mut race: ResMut<RaceRes>,
    mut tick: ResMut<SimTick>,
    mut shake: ResMut<ScreenShake>,
) {
    tick.0 += 1;
    let race = &mut race.0;
    let mut inputs = Vec::with_capacity(KARTS);
    inputs.push(match cfg.autoplay {
        Some(style) => bots::drive(race, 0, style),
        None => intent.kart_input(),
    });
    for (i, style) in RIVALS.iter().enumerate().take(race.racers.len() - 1) {
        inputs.push(bots::drive(race, i + 1, *style));
    }
    race.step(&inputs, time.delta_secs() * rules.game_speed as f32);
    for event in race.events.clone() {
        if event == (RaceEvent::Bonk { kart: 0 }) {
            shake.shake.add_trauma(BONK_TRAUMA);
        }
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

    #[test]
    fn shell_options_are_read_and_unknown_drives_refused() {
        let cfg = configure(&args(&[
            "--drive",
            "menus",
            "--data-dir",
            "build/x",
            "--locale",
            "pseudo",
        ]))
        .unwrap();
        assert_eq!(cfg.drive.as_deref(), Some("menus"));
        assert_eq!(cfg.data_dir, Some(PathBuf::from("build/x")));
        assert_eq!(cfg.locale.as_deref(), Some("pseudo"));
        assert!(!cfg.needs_window(), "menus runs headless");
        assert!(configure(&args(&["--drive", "show:settings"])).unwrap().needs_window());
        for (drive, window) in [
            ("crash", false),
            ("pseudo", true),
            ("pseudo-plant", true),
            ("bug", true),
        ] {
            assert_eq!(
                configure(&args(&["--drive", drive])).unwrap().needs_window(),
                window,
                "{drive}"
            );
        }
        assert!(configure(&args(&["--drive", "show:juice"])).is_ok());
        assert!(configure(&args(&["--drive", "dance"])).is_err());
        assert!(configure(&args(&["--drive", "show:kitchen"])).is_err());
    }

    #[test]
    fn keys_give_digital_gas_and_steering_with_drift_and_item() {
        // a held W and A: the shell's unit direction is (-0.707, 0.707), which must still be full gas, full left
        let intent = Intent {
            dir: Vec2::new(-1.0, 1.0).normalize(),
            pressed: vec![ITEM_ACTION.to_string()],
            held: BTreeSet::from([DRIFT_ACTION.to_string(), "move_up".into(), "move_left".into()]),
            ..Intent::default()
        };
        assert_eq!(
            intent.kart_input(),
            KartInput {
                throttle: 1.0,
                steer: 1.0,
                drift: true,
                use_item: true,
            }
        );
        let brake_right = Intent {
            dir: Vec2::new(1.0, -1.0).normalize(),
            ..Intent::default()
        };
        let k = brake_right.kart_input();
        assert_eq!((k.throttle, k.steer, k.drift, k.use_item), (-1.0, -1.0, false, false));
        assert_eq!(Intent::default().kart_input(), KartInput::default());
    }

    #[test]
    fn triggers_are_analog_gas_and_brake_and_the_stick_steers_by_its_lean() {
        // half the right trigger: half gas; the left trigger on top takes it back down
        let half_gas = Intent {
            right_trigger: 0.5,
            ..Intent::default()
        };
        assert_eq!(half_gas.kart_input().throttle, 0.5);
        let both = Intent {
            right_trigger: 0.75,
            left_trigger: 0.25,
            ..Intent::default()
        };
        assert_eq!(both.kart_input().throttle, 0.5);
        let brake = Intent {
            left_trigger: 0.4,
            ..Intent::default()
        };
        assert_eq!(brake.kart_input().throttle, -0.4);
        // a held gas key counts as a fully pressed trigger: max(trigger, key), never less
        let key_and_trigger = Intent {
            dir: Vec2::Y,
            right_trigger: 0.3,
            ..Intent::default()
        };
        assert_eq!(key_and_trigger.kart_input().throttle, 1.0);
        // the stick leaned 40% right (dir carries it too, and the stick holds move_right): 40% lock, not full lock
        let lean = Intent {
            dir: Vec2::new(0.4, 0.0),
            stick: Vec2::new(0.4, 0.0),
            held: BTreeSet::from(["move_right".to_string()]),
            right_trigger: 1.0,
            ..Intent::default()
        };
        let k = lean.kart_input();
        assert_eq!((k.throttle, k.steer), (1.0, -0.4));
        // a stick leaned forward is analog gas as well
        let stick_gas = Intent {
            dir: Vec2::new(0.0, 0.6),
            stick: Vec2::new(0.0, 0.6),
            ..Intent::default()
        };
        assert_eq!(stick_gas.kart_input().throttle, 0.6);
    }
}
