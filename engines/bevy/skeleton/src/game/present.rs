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
//           Dotwork art (assets/dotwork/*.assets.json, crate::dotwork): when the game has some, show_dotwork puts a
//           showcase in the top-left corner (a map, a character walking through its directions, a prop and a label
//           in the font). Replace it with the game's own use of the art: the Dotwork system parameter spawns it.
// Updated : 2026-11-01 with Claude (Opus 5.5, claude-opus-5-5): shake_camera applies ScreenShake
//           2026-11-09 with Claude (Fable 5.1, claude-fable-5-1): palette colours; input moved to the shell
//           2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): the Dotwork showcase (#59)
// ---------------------------------------------------------------------------
use bevy::prelude::*;

use super::{Goal, Palette, Player, ScreenShake, TITLE};
use crate::dotwork::Dotwork;
use crate::shell::HideUnderJuice;

// ---- Fallback colours (the palette's "none" set normally wins) ------------------
const PLAYER_COLOUR: Color = Color::srgb(0.95, 0.75, 0.3);
const TARGET_COLOUR: Color = Color::srgb(0.35, 0.8, 0.45);
const FLOOR_COLOUR: Color = Color::srgb(0.25, 0.27, 0.32);

// ---- Dotwork showcase ------------------------------------------------------------
/// Whole-number scale for pixel art (a fractional one blurs or drops pixels).
const ART_SCALE: f32 = 3.0;
/// Top-left corner of the showcase, in world units (the camera looks at 0, 0).
const SHOWCASE_AT: Vec3 = Vec3::new(-600.0, 260.0, 1.0);
/// Seconds the showcase character walks one way before turning.
const TURN_SECONDS: f32 = 1.5;

pub struct PresentPlugin;

impl Plugin for PresentPlugin {
    fn build(&self, app: &mut App) {
        app.insert_resource(ClearColor(FLOOR_COLOUR))
            .add_systems(Startup, (setup_view, show_dotwork))
            .add_systems(Update, (shake_camera, recolour, turn_walker))
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

/// The showcase character: walks through the clips of its "walk" directions, one turn every TURN_SECONDS.
#[derive(Component, Debug)]
struct Walker {
    sprite: String,
    clips: Vec<String>,
    next: usize,
    timer: Timer,
}

/// Shows the game's Dotwork art, when it has some: its first map, a character with a walk cycle, a prop and a
/// label in its first font, under one parent at ART_SCALE.
fn show_dotwork(mut commands: Commands, mut dw: Dotwork) {
    let packs = &dw.library.packs;
    let walker = packs.iter().flat_map(|p| p.animated.values()).find_map(|a| {
        Some((
            a.name.clone(),
            a.directions.get("walk")?.values().cloned().collect::<Vec<_>>(),
        ))
    });
    let map = packs
        .iter()
        .find_map(|p| p.maps.values().next())
        .map(|m| m.name.clone());
    let prop = packs.iter().find_map(|p| p.sprites.keys().next().cloned());
    let font = packs.iter().find_map(|p| p.fonts.keys().next().cloned());
    if walker.is_none() && map.is_none() && prop.is_none() && font.is_none() {
        return;
    }
    let root = commands
        .spawn((
            Name::new("Dotwork showcase"),
            Transform::from_translation(SHOWCASE_AT).with_scale(Vec3::new(ART_SCALE, ART_SCALE, 1.0)),
            Visibility::default(),
            HideUnderJuice,
        ))
        .id();
    let mut x = 0.0; // the next free column, in art pixels
    if let Some(name) = map
        && let Some(e) = dw.spawn_map(&mut commands, &name)
    {
        commands.entity(e).insert(ChildOf(root));
        x += dw
            .library
            .map(&name)
            .map_or(0.0, |(_, m, _)| (m.size.x * m.cell_size.x) as f32)
            + 16.0;
    }
    if let Some((name, clips)) = walker
        && let Some(e) = dw.spawn_clip(&mut commands, &name, &clips[0])
    {
        commands.entity(e).insert((
            Transform::from_xyz(x + 8.0, -32.0, 0.5),
            ChildOf(root),
            Walker {
                sprite: name,
                clips,
                next: 1,
                timer: Timer::from_seconds(TURN_SECONDS, TimerMode::Repeating),
            },
        ));
        x += 32.0;
    }
    if let Some(name) = prop
        && let Some(e) = dw.spawn_sprite(&mut commands, &name)
    {
        commands
            .entity(e)
            .insert((Transform::from_xyz(x + 8.0, -32.0, 0.5), ChildOf(root)));
    }
    if let Some(name) = font
        && let Some(e) = dw.spawn_text(&mut commands, &name, TITLE, Color::WHITE)
    {
        commands
            .entity(e)
            .insert((Transform::from_xyz(0.0, 12.0, 0.5), ChildOf(root)));
    }
}

/// Turns the showcase character: the next clip of its walk directions (the Dotwork bundle replaces the old one).
fn turn_walker(time: Res<Time>, mut commands: Commands, mut dw: Dotwork, mut walkers: Query<(Entity, &mut Walker)>) {
    for (e, mut w) in &mut walkers {
        if !w.timer.tick(time.delta()).just_finished() {
            continue;
        }
        let clip = w.clips[w.next % w.clips.len()].clone();
        w.next += 1;
        if let Some(bundle) = dw.clip_bundle(&w.sprite, &clip) {
            commands.entity(e).insert(bundle);
        }
    }
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
