// ---------------------------------------------------------------------------
// tests/headless.rs
// Purpose : Integration tests that drive the real GamePlugin headless: build the test App, pick a seed and a bot or
//           set the player's input, call app.update() frame by frame, read the race. No window or GPU needed.
// Usage   : python tools/dev.py test   (or cargo test --test headless)
// Notes   : One frame = one 1/60 s fixed tick here (app::test_app), so a full 3-lap race is about 7,500 frames.
//           Each test names the behavior it guards.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use bevy::prelude::*;

use project_crimson_nebula::app::test_app;
use project_crimson_nebula::game::{GameConfig, PlayerInput, RaceRes, SimTick};
use project_crimson_nebula::logic::bots::Style;
use project_crimson_nebula::logic::kart::KartInput;
use project_crimson_nebula::logic::race::Phase;
use project_crimson_nebula::logic::tuning::{COUNTDOWN, RACE_TIME_LIMIT};

fn race(app: &App) -> &project_crimson_nebula::logic::race::Race {
    &app.world().resource::<RaceRes>().0
}

#[test]
fn each_frame_runs_one_fixed_tick() {
    let mut app = test_app(GameConfig {
        seed: Some(1),
        ..default()
    });
    for _ in 0..61 {
        app.update();
    }
    // The first frame only starts the clock; every frame after it is one tick
    assert_eq!(app.world().resource::<SimTick>().0, 60);
}

#[test]
fn a_bot_driven_player_finishes_a_whole_race() {
    let mut app = test_app(GameConfig {
        autoplay: Some(Style::Reader),
        seed: Some(3),
    });
    let max_frames = (RACE_TIME_LIMIT * 60.0) as usize;
    for _ in 0..max_frames {
        app.update();
        if race(&app).phase == Phase::Over {
            break;
        }
    }
    let r = race(&app);
    assert_eq!(r.phase, Phase::Over);
    assert!(r.racers[0].finished.is_some(), "the player's bot finished");
    assert_eq!(r.racers.len(), 4);
}

#[test]
fn the_same_seed_replays_the_same_race() {
    let run = || {
        let mut app = test_app(GameConfig {
            autoplay: Some(Style::Late),
            seed: Some(11),
        });
        for _ in 0..3000 {
            app.update();
        }
        race(&app).racers.iter().map(|r| r.kart.pos).collect::<Vec<_>>()
    };
    assert_eq!(run(), run());
}

#[test]
fn player_input_drives_the_players_kart_after_the_countdown() {
    let mut app = test_app(GameConfig {
        seed: Some(1),
        ..default()
    });
    app.update(); // startup creates the race
    let start = race(&app).racers[0].kart.pos;
    app.world_mut().resource_mut::<PlayerInput>().0 = KartInput {
        throttle: 1.0,
        ..default()
    };
    for _ in 0..(COUNTDOWN * 60.0) as usize - 2 {
        app.update();
    }
    assert_eq!(race(&app).racers[0].kart.pos, start, "frozen during the countdown");
    for _ in 0..60 {
        app.update();
    }
    assert!(race(&app).racers[0].kart.pos.distance(start) > 5.0);
}
