// ---------------------------------------------------------------------------
// game/present.rs
// Purpose : Everything the player sees in the world: camera (with shake), the sprites in the colour-blind palette.
//           Added only when there is a window (app.rs), so headless smoke runs and tests never need a GPU.
// Usage   : app.add_plugins(PresentPlugin);
// Notes   : Visuals attach to simulation entities through observers (On<Add<Player>>), so game/mod.rs
//           spawns plain data and stays headless. Bevy 0.20 spelling: On<Add<T>>, not the older On<Add, T>.
//           Input is the shell's job (shell/view.rs polls keys and pads through the player's bindings and writes
//           Intent), so rebinding and the one-handed layouts reach the game without a line here. Colours come from
//           the Palette resource (data/access/colours.json): recolour() follows the colour-blind setting live.
//           Simulation moves in fixed 1/60 s ticks; on a 120 Hz screen motion can look slightly uneven
//           until you add interpolation (an ADR: a crate such as bevy_transform_interpolation (verify)).
//           shake_camera undoes last frame's shake before adding this frame's, so it composes with any camera
//           movement (a follow camera from logic::follow) that runs before it.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-01 with Claude (Opus 5.5, claude-opus-5-5): shake_camera applies ScreenShake
//           2026-11-09 with Claude (Fable 5.1, claude-fable-5-1): palette colours; input moved to the shell
// ---------------------------------------------------------------------------
use bevy::prelude::*;

use super::{Goal, Palette, Player, ScreenShake};

// ---- Fallback colours (the palette's "none" set normally wins) ------------------
const PLAYER_COLOUR: Color = Color::srgb(0.95, 0.75, 0.3);
const TARGET_COLOUR: Color = Color::srgb(0.35, 0.8, 0.45);
const FLOOR_COLOUR: Color = Color::srgb(0.25, 0.27, 0.32);

pub struct PresentPlugin;

impl Plugin for PresentPlugin {
    fn build(&self, app: &mut App) {
        app.insert_resource(ClearColor(FLOOR_COLOUR))
            .add_systems(Startup, setup_view)
            .add_systems(Update, (shake_camera, recolour))
            .add_observer(dress_player)
            .add_observer(dress_goal);
    }
}

fn setup_view(mut commands: Commands) {
    commands.spawn(Camera2d);
}

fn dress_player(add: On<Add<Player>>, palette: Res<Palette>, mut commands: Commands) {
    commands.entity(add.entity).insert(Sprite::from_color(
        palette.get("player", PLAYER_COLOUR),
        Vec2::splat(32.0),
    ));
}

fn dress_goal(add: On<Add<Goal>>, palette: Res<Palette>, mut commands: Commands) {
    commands.entity(add.entity).insert(Sprite::from_color(
        palette.get("target", TARGET_COLOUR),
        Vec2::new(4.0, 400.0),
    ));
}

/// The colour-blind setting changed: swap every palette colour (SOP-20: palettes, not a filter).
fn recolour(
    palette: Res<Palette>,
    mut clear: ResMut<ClearColor>,
    mut players: Query<&mut Sprite, (With<Player>, Without<Goal>)>,
    mut goals: Query<&mut Sprite, (With<Goal>, Without<Player>)>,
) {
    if !palette.is_changed() {
        return;
    }
    clear.0 = palette.get("floor", FLOOR_COLOUR);
    for mut sprite in &mut players {
        sprite.color = palette.get("player", PLAYER_COLOUR);
    }
    for mut sprite in &mut goals {
        sprite.color = palette.get("target", TARGET_COLOUR);
    }
}

/// Moves the camera by this frame's screen shake. `last` holds the offset and roll applied last frame.
fn shake_camera(
    time: Res<Time>,
    mut shake: ResMut<ScreenShake>,
    mut last: Local<(Vec3, f32)>,
    mut cameras: Query<&mut Transform, With<Camera2d>>,
) {
    let intensity = shake.intensity;
    let (x, y, angle) = shake.shake.update(time.delta_secs_f64(), intensity);
    let (offset, roll) = (Vec3::new(x as f32, y as f32, 0.0), angle as f32);
    for mut transform in &mut cameras {
        transform.translation += offset - last.0;
        transform.rotate_z(roll - last.1);
    }
    *last = (offset, roll);
}

// {{FOOTER}}
