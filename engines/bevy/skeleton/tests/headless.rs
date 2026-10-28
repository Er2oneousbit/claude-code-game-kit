// ---------------------------------------------------------------------------
// tests/headless.rs
// Purpose : Integration tests that drive the real GamePlugin headless: build the test App, set the input or a
//           bot, call app.update() frame by frame, read the world. The pattern to copy for game rules.
// Usage   : python tools/dev.py test   (or cargo test --test headless)
// Notes   : Count SimTick, never frames: one frame runs one 1/60 s tick here, but rules are written per tick.
//           Each test names the behavior it guards. No window or GPU needed.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use bevy::prelude::*;

use {{GAME_SLUG}}::app::{TICK_HZ, test_app};
use {{GAME_SLUG}}::game::{Autoplay, GameConfig, Intent, PLAYER_SPEED, Player, SimTick};

fn player_x(app: &mut App) -> f32 {
    let mut q = app.world_mut().query_filtered::<&Transform, With<Player>>();
    q.single(app.world()).expect("exactly one player").translation.x
}

fn ticks(app: &App) -> u64 {
    app.world().resource::<SimTick>().0
}

#[test]
fn each_frame_runs_one_fixed_tick() {
    let mut app = test_app(GameConfig::default());
    for _ in 0..61 {
        app.update();
    }
    // The first frame only starts the clock; every frame after it is one tick
    assert_eq!(ticks(&app), 60);
}

#[test]
fn the_bot_moves_the_player_at_its_speed() {
    let mut app = test_app(GameConfig {
        autoplay: Some(Autoplay::Right),
    });
    for _ in 0..31 {
        app.update();
    }
    let expected = PLAYER_SPEED * ticks(&app) as f32 / TICK_HZ as f32;
    assert!(ticks(&app) > 0);
    assert!(
        (player_x(&mut app) - expected).abs() < 0.01,
        "x {} vs {}",
        player_x(&mut app),
        expected
    );
}

#[test]
fn without_input_the_player_stays_put() {
    let mut app = test_app(GameConfig::default());
    for _ in 0..30 {
        app.update();
    }
    assert_eq!(player_x(&mut app), 0.0);
}

#[test]
fn diagonal_input_is_not_faster() {
    let mut app = test_app(GameConfig::default());
    app.update();
    app.world_mut().resource_mut::<Intent>().dir = Vec2::new(1.0, 1.0); // unnormalized, as a careless bot might
    for _ in 0..30 {
        app.update();
    }
    let mut q = app.world_mut().query_filtered::<&Transform, With<Player>>();
    let moved = q.single(app.world()).unwrap().translation.truncate().length();
    let max = PLAYER_SPEED * ticks(&app) as f32 / TICK_HZ as f32;
    assert!(moved <= max + 0.01, "moved {moved} > {max}");
}

// {{FOOTER}}
