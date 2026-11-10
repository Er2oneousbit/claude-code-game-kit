// ---------------------------------------------------------------------------
// game/mod.rs
// Purpose : The simulation: components, resources and the systems that change game state. GamePlugin runs
//           the same in a window, headless (dev.py smoke) and in tests, so everything here must work without
//           a renderer, a window or a keyboard.
// Usage   : app.add_plugins(GamePlugin);   game options: configure(&args) -> GameConfig
// Notes   : PROTOTYPE: a square that moves toward GOAL_X proves the loop, the fixed tick and the scenario
//           markers work. Replace it with the real game. Rules:
//           - state changes run in FixedUpdate (one tick = 1/60 s, frame-rate independent, repeatable), and only
//             while GameActive is true (the shell sets it: Play on top, not paused);
//           - input arrives only through the Intent resource (the shell writes it from the player's bindings,
//             bots in autoplay): dir, pressed and held actions, the analog stick and the triggers;
//           - visuals live in present.rs; this file never spawns sprites, meshes or cameras.
//           Juice: systems add trauma to the ScreenShake resource; present.rs moves the camera by it.
//           Accessibility: AccessRules (game speed, timing scale, auto repeat, flash limit) and Palette (the
//           colour-blind palette from data/access/colours.json) follow the settings; read them, never the file.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-01 with Claude (Opus 5.5, claude-opus-5-5): ScreenShake (logic::shake), the goal shakes it
//           2026-11-09 with Claude (Fable 5.1, claude-fable-5-1): GameActive, AccessRules, Palette, Intent.pressed,
//           the shell's options (--drive, --data-dir, --locale)
//           2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): Intent.held, stick and triggers (analog input, #265)
// ---------------------------------------------------------------------------
pub mod present;

use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;

use bevy::prelude::*;

use crate::logic::shake::Shake;

pub use present::PresentPlugin;

/// Window title and log name.
pub const TITLE: &str = "{{GAME_NAME}}";

// ---- Tunables ------------------------------------------------------------------
/// World units (pixels in the 2D view) per second.
pub const PLAYER_SPEED: f32 = 240.0;
/// The prototype's scenario: reaching this x prints GOAL_REACHED.
pub const GOAL_X: f32 = 200.0;
/// Screen shake trauma (0 to 1) when the goal is reached.
pub const GOAL_TRAUMA: f64 = 0.5;

/// Game options from the command line (everything after `--`). Add bot modes, seeds and cheats here.
#[derive(Resource, Debug, Clone, Default, PartialEq)]
pub struct GameConfig {
    pub autoplay: Option<Autoplay>,
    /// A scripted smoke scenario (shell/drive.rs): menus, access[:opts], show:<screen>.
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

/// Bots that drive the game through Intent, for smoke scenarios and balance runs (SOP-14).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Autoplay {
    /// Hold right until the goal.
    Right,
}

pub const OPTIONS_HELP: &str = "\
Game options (after --):
  --autoplay right     a bot holds right; prints GOAL_REACHED at the goal
  --drive NAME         with --smoke: a scripted path through the shell (menus, access[:res=WxH,scale=N,pad,read],
                       show:<title|main_menu|settings|pause|help|history|credits|subtitle>); dev.py smoke --drive
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
                    Some("right") => Autoplay::Right,
                    other => return Err(format!("--autoplay needs a mode (right), got {other:?}")),
                })
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

/// What the player wants this tick. The shell (from the bindings) or a bot writes it; the simulation only reads it.
/// Everything is zero or empty while the game is not active (menus, pause).
#[derive(Resource, Debug, Default, Clone, PartialEq)]
pub struct Intent {
    /// Desired direction, length 0 to 1: the held move_* actions (keys, d-pad) plus the analog `stick`, so keyboard
    /// play gives unit directions and a half-leaned stick gives half speed.
    pub dir: Vec2,
    /// Game actions pressed this frame (jump, attack, interact), auto-repeats included.
    pub pressed: Vec<String>,
    /// Game actions held right now (no ui_*): a drift button, a charge, "hold to sprint". The left stick past the
    /// deadzone also holds move_left/right/up/down here, invert_y honoured.
    pub held: BTreeSet<String>,
    /// The left stick, deadzone (input.deadzone, radial, rescaled) and input.invert_y applied: each axis -1 to 1,
    /// up is +y. Zero without a pad.
    pub stick: Vec2,
    /// The analog triggers, 0 at rest to 1 fully in (logic::analog::TRIGGER_DEADZONE applied): gas and brake.
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
}

#[derive(Component, Debug)]
pub struct Player;

/// The goal line of the prototype (present.rs dresses it in the palette's "target" colour).
#[derive(Component, Debug)]
pub struct Goal;

/// Fixed ticks run so far: tests and bots count ticks, never frames.
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
/// Ask it for "player", "target", "hit", "floor"; a name it lacks gets the fallback you pass.
#[derive(Resource, Debug, Clone, Default)]
pub struct Palette(pub BTreeMap<String, Color>);

impl Palette {
    pub fn get(&self, name: &str, fallback: Color) -> Color {
        self.0.get(name).copied().unwrap_or(fallback)
    }
}

/// Screen shake: add trauma here on hits (`shake.shake.add_trauma(0.4)`); present.rs applies it to the camera.
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
            .init_resource::<SimTick>()
            .init_resource::<ScreenShake>()
            .init_resource::<GameActive>()
            .init_resource::<AccessRules>()
            .init_resource::<Palette>()
            .add_systems(Startup, spawn_player)
            .add_systems(
                FixedUpdate,
                (autoplay, move_player, check_goal).chain().run_if(game_active),
            );
    }
}

fn game_active(active: Res<GameActive>) -> bool {
    active.0
}

fn spawn_player(mut commands: Commands) {
    commands.spawn((Player, Transform::default()));
    commands.spawn((Goal, Transform::from_xyz(GOAL_X, 0.0, -1.0)));
}

fn autoplay(cfg: Res<GameConfig>, mut intent: ResMut<Intent>) {
    if cfg.autoplay == Some(Autoplay::Right) {
        intent.dir = Vec2::X;
    }
}

fn move_player(
    time: Res<Time>,
    intent: Res<Intent>,
    rules: Res<AccessRules>,
    mut tick: ResMut<SimTick>,
    mut players: Query<&mut Transform, With<Player>>,
) {
    tick.0 += 1;
    let dt = time.delta_secs() * rules.game_speed as f32;
    let step = intent.dir.clamp_length_max(1.0) * PLAYER_SPEED * dt;
    for mut transform in &mut players {
        transform.translation += step.extend(0.0);
    }
}

fn check_goal(
    mut reached: Local<bool>,
    tick: Res<SimTick>,
    mut shake: ResMut<ScreenShake>,
    players: Query<&Transform, With<Player>>,
) {
    if *reached {
        return;
    }
    if let Some(t) = players.iter().find(|t| t.translation.x >= GOAL_X) {
        *reached = true;
        shake.shake.add_trauma(GOAL_TRAUMA);
        info!("GOAL_REACHED tick={} x={:.1}", tick.0, t.translation.x);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(list: &[&str]) -> Vec<String> {
        list.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn options_select_a_bot_and_reject_typos() {
        assert_eq!(configure(&[]).unwrap(), GameConfig::default());
        assert_eq!(
            configure(&args(&["--autoplay", "right"])).unwrap().autoplay,
            Some(Autoplay::Right)
        );
        assert!(configure(&args(&["--autoplay"])).is_err());
        assert!(configure(&args(&["--autoplay", "left"])).is_err());
        assert!(configure(&args(&["--autoply", "right"])).is_err());
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
        assert!(configure(&args(&["--drive", "dance"])).is_err());
        assert!(configure(&args(&["--drive", "show:kitchen"])).is_err());
    }
}

// {{FOOTER}}
