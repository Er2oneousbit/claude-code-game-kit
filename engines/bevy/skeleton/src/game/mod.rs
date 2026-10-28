// ---------------------------------------------------------------------------
// game/mod.rs
// Purpose : The simulation: components, resources and the systems that change game state. GamePlugin runs
//           the same in a window, headless (dev.py smoke) and in tests, so everything here must work without
//           a renderer, a window or a keyboard.
// Usage   : app.add_plugins(GamePlugin);   game options: configure(&args) -> GameConfig
// Notes   : PROTOTYPE: a square that moves toward GOAL_X proves the loop, the fixed tick and the scenario
//           markers work. Replace it with the real game. Rules:
//           - state changes run in FixedUpdate (one tick = 1/60 s, frame-rate independent, repeatable);
//           - input arrives only through the Intent resource (keyboard in present.rs, bots in autoplay);
//           - visuals live in present.rs; this file never spawns sprites, meshes or cameras.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
pub mod present;

use bevy::prelude::*;

pub use present::PresentPlugin;

/// Window title and log name.
pub const TITLE: &str = "{{GAME_NAME}}";

// ---- Tunables ------------------------------------------------------------------
/// World units (pixels in the 2D view) per second.
pub const PLAYER_SPEED: f32 = 240.0;
/// The prototype's scenario: reaching this x prints GOAL_REACHED.
pub const GOAL_X: f32 = 200.0;

/// Game options from the command line (everything after `--`). Add bot modes, seeds and cheats here.
#[derive(Resource, Debug, Clone, Default, PartialEq)]
pub struct GameConfig {
    pub autoplay: Option<Autoplay>,
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
            other => return Err(format!("unknown game option {other:?}\n{OPTIONS_HELP}")),
        }
    }
    Ok(cfg)
}

/// What the player wants this tick. The keyboard (present.rs) or a bot writes it; the simulation only reads it.
#[derive(Resource, Debug, Default, Clone, Copy, PartialEq)]
pub struct Intent {
    /// Desired direction, length 0 to 1.
    pub dir: Vec2,
}

#[derive(Component, Debug)]
pub struct Player;

/// Fixed ticks run so far: tests and bots count ticks, never frames.
#[derive(Resource, Debug, Default)]
pub struct SimTick(pub u64);

pub struct GamePlugin;

impl Plugin for GamePlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<GameConfig>()
            .init_resource::<Intent>()
            .init_resource::<SimTick>()
            .add_systems(Startup, spawn_player)
            .add_systems(FixedUpdate, (autoplay, move_player, check_goal).chain());
    }
}

fn spawn_player(mut commands: Commands) {
    commands.spawn((Player, Transform::default()));
}

fn autoplay(cfg: Res<GameConfig>, mut intent: ResMut<Intent>) {
    if cfg.autoplay == Some(Autoplay::Right) {
        intent.dir = Vec2::X;
    }
}

fn move_player(
    time: Res<Time>,
    intent: Res<Intent>,
    mut tick: ResMut<SimTick>,
    mut players: Query<&mut Transform, With<Player>>,
) {
    tick.0 += 1;
    let step = intent.dir.clamp_length_max(1.0) * PLAYER_SPEED * time.delta_secs();
    for mut transform in &mut players {
        transform.translation += step.extend(0.0);
    }
}

fn check_goal(mut reached: Local<bool>, tick: Res<SimTick>, players: Query<&Transform, With<Player>>) {
    if *reached {
        return;
    }
    if let Some(t) = players.iter().find(|t| t.translation.x >= GOAL_X) {
        *reached = true;
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
}

// {{FOOTER}}
