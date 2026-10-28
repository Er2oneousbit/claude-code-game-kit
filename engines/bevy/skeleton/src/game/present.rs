// ---------------------------------------------------------------------------
// game/present.rs
// Purpose : Everything the player sees and touches: camera, sprites, keyboard input -> Intent, quit key.
//           Added only when there is a window (app.rs), so headless smoke runs and tests never need a GPU.
// Usage   : app.add_plugins(PresentPlugin);
// Notes   : Visuals attach to simulation entities through observers (On<Add<Player>>), so game/mod.rs
//           spawns plain data and stays headless. Bevy 0.20 spelling: On<Add<T>>, not the older On<Add, T>.
//           Simulation moves in fixed 1/60 s ticks; on a 120 Hz screen motion can look slightly uneven
//           until you add interpolation (an ADR: a crate such as bevy_transform_interpolation (verify)).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use bevy::prelude::*;

use super::{GOAL_X, GameConfig, Intent, Player};

pub struct PresentPlugin;

impl Plugin for PresentPlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(Startup, setup_view)
            .add_systems(
                RunFixedMainLoop,
                keyboard_intent.in_set(RunFixedMainLoopSystems::BeforeFixedMainLoop),
            )
            .add_systems(Update, quit_on_escape)
            .add_observer(dress_player);
    }
}

fn setup_view(mut commands: Commands) {
    commands.spawn(Camera2d);
    // The goal line of the prototype scenario
    commands.spawn((
        Sprite::from_color(Color::srgb(0.3, 0.8, 0.4), Vec2::new(4.0, 400.0)),
        Transform::from_xyz(GOAL_X, 0.0, -1.0),
    ));
}

fn dress_player(add: On<Add<Player>>, mut commands: Commands) {
    commands
        .entity(add.entity)
        .insert(Sprite::from_color(Color::srgb(0.9, 0.35, 0.2), Vec2::splat(32.0)));
}

/// Keyboard -> Intent, right before the fixed ticks of this frame (no frame of input lag). Bots win: with
/// --autoplay the keyboard is ignored, so a recorded scenario cannot be disturbed by a stray key.
fn keyboard_intent(keys: Res<ButtonInput<KeyCode>>, cfg: Res<GameConfig>, mut intent: ResMut<Intent>) {
    if cfg.autoplay.is_some() {
        return;
    }
    let mut dir = Vec2::ZERO;
    if keys.any_pressed([KeyCode::ArrowLeft, KeyCode::KeyA]) {
        dir.x -= 1.0;
    }
    if keys.any_pressed([KeyCode::ArrowRight, KeyCode::KeyD]) {
        dir.x += 1.0;
    }
    if keys.any_pressed([KeyCode::ArrowDown, KeyCode::KeyS]) {
        dir.y -= 1.0;
    }
    if keys.any_pressed([KeyCode::ArrowUp, KeyCode::KeyW]) {
        dir.y += 1.0;
    }
    intent.dir = dir.normalize_or_zero();
}

fn quit_on_escape(keys: Res<ButtonInput<KeyCode>>, mut exit: MessageWriter<AppExit>) {
    if keys.just_pressed(KeyCode::Escape) {
        exit.write(AppExit::Success);
    }
}

// {{FOOTER}}
