// ---------------------------------------------------------------------------
// tests/shell.rs
// Purpose : The shell's screens, headless: the title, menu and settings answer the ui_* actions, settings edits save
//           to the run's own data folder, the one-handed layouts apply and reset, a rebind swaps, pause shows "What
//           now?" and the dialogue history, subtitle_hold waits for accept, auto_repeat repeats a held action, and
//           the `menus` drive finishes with the file it promises (SOP-19, SOP-20; #165, #166, #167, #168).
// Usage   : python tools/dev.py test   (or cargo test --test shell)
// Notes   : app::shell_test_app builds the real ShellPlugin on the headless test App; every test gets its own data
//           folder under the system temp dir, so no test touches another's settings.json or the player's.
//           Actions are injected as a key press would be (shell.inject) and take effect on the next update.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
use std::path::PathBuf;

use bevy::prelude::*;
use serde_json::{Value, json};

use {{GAME_SLUG}}::app::shell_test_app;
use {{GAME_SLUG}}::game::{AccessRules, GameActive, GameConfig, Intent, Palette, ScreenShake};
use {{GAME_SLUG}}::shell::{ScreenName, Shell};

/// A data folder of this test's own under the system temp dir, removed when the test ends.
struct TempDir(PathBuf);

impl TempDir {
    fn new(name: &str) -> TempDir {
        let dir = std::env::temp_dir().join(format!("{}-{name}-{}", env!("CARGO_PKG_NAME"), std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("a temp folder");
        TempDir(dir)
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn cfg(dir: &TempDir) -> GameConfig {
    GameConfig {
        data_dir: Some(dir.0.clone()),
        automated: true,
        ..GameConfig::default()
    }
}

fn shell(app: &App) -> &Shell {
    app.world().resource::<Shell>()
}

fn shell_mut(app: &mut App) -> Mut<'_, Shell> {
    app.world_mut().resource_mut::<Shell>()
}

fn frames(app: &mut App, n: usize) {
    for _ in 0..n {
        app.update();
    }
}

/// Injects one action and lets it land.
fn press(app: &mut App, action: &str) {
    shell_mut(app).inject(action);
    frames(app, 2);
}

fn until_screen(app: &mut App, name: ScreenName) {
    for _ in 0..600 {
        if shell(app).top_name() == Some(name) {
            return;
        }
        app.update();
    }
    panic!(
        "screen {} never came up (top: {:?})",
        name.as_str(),
        shell(app).top_name()
    );
}

/// Boots to the main menu (answers the consent question with Later).
fn to_menu(app: &mut App) {
    until_screen(app, ScreenName::Title);
    if shell(app).top().is_some_and(|t| t.consent) {
        press(app, "ui_cancel");
    }
    press(app, "ui_accept");
    until_screen(app, ScreenName::MainMenu);
}

fn focus(app: &mut App, id: &str) {
    for _ in 0..60 {
        if shell(app).focus_id() == id {
            return;
        }
        press(app, "ui_down");
    }
    panic!("could not focus {id} (focused: {:?})", shell(app).focus_id());
}

fn to_tab(app: &mut App, tab: &str) {
    for _ in 0..60 {
        if shell(app).focus_id().starts_with("tabs.") {
            break;
        }
        press(app, "ui_up");
    }
    for _ in 0..10 {
        if shell(app).focus_id() == format!("tabs.{tab}") {
            return;
        }
        press(app, "ui_right");
    }
    panic!("could not reach tab {tab}");
}

fn to_play(app: &mut App) {
    to_menu(app);
    focus(app, "play");
    press(app, "ui_accept");
    until_screen(app, ScreenName::Play);
}

fn saved(dir: &TempDir) -> Value {
    let path: PathBuf = dir.0.join("settings.json");
    serde_json::from_str(&std::fs::read_to_string(&path).expect("settings.json written")).unwrap()
}

#[test]
fn the_game_waits_on_the_title_and_runs_only_in_play() {
    let dir = TempDir::new("shell-title");
    let mut app = shell_test_app(cfg(&dir), None);
    until_screen(&mut app, ScreenName::Title);
    assert!(
        !app.world().resource::<GameActive>().0,
        "the simulation must not run under the menus"
    );
    assert!(
        shell(&app).top().unwrap().consent,
        "a first start asks about play statistics"
    );
    to_play(&mut app);
    assert!(app.world().resource::<GameActive>().0);
    assert!(!shell(&app).objective.is_empty(), "play sets the goal for What now?");
    assert_eq!(shell(&app).history.len(), 1, "the welcome line is in the history");
}

#[test]
fn settings_change_with_the_arrows_and_back_saves_them() {
    let dir = TempDir::new("shell-settings");
    let mut app = shell_test_app(cfg(&dir), None);
    to_menu(&mut app);
    focus(&mut app, "settings");
    press(&mut app, "ui_accept");
    until_screen(&mut app, ScreenName::Settings);
    assert_eq!(shell(&app).focus_id(), "tabs.display", "focus starts on the tab bar");
    to_tab(&mut app, "audio");
    press(&mut app, "ui_down");
    focus(&mut app, "audio.master");
    press(&mut app, "ui_left");
    press(&mut app, "ui_left");
    assert!((shell(&app).num("audio", "master") - 0.8).abs() < 1e-9);
    to_tab(&mut app, "access");
    press(&mut app, "ui_down");
    focus(&mut app, "access.text_scale");
    press(&mut app, "ui_right");
    assert_eq!(shell(&app).num("access", "text_scale"), 1.25);
    focus(&mut app, "access.reduce_motion");
    press(&mut app, "ui_accept");
    assert!(shell(&app).flag("access", "reduce_motion"));
    frames(&mut app, 1);
    assert_eq!(
        app.world().resource::<ScreenShake>().intensity,
        0.0,
        "reduce motion zeroes the shake"
    );
    focus(&mut app, "access.colorblind");
    press(&mut app, "ui_right");
    assert_eq!(shell(&app).text("access", "colorblind"), "protanopia");
    frames(&mut app, 1);
    let palette = app.world().resource::<Palette>();
    assert_ne!(
        palette.get("target", Color::BLACK),
        Color::BLACK,
        "the palette swapped to protanopia"
    );
    focus(&mut app, "access.game_speed");
    press(&mut app, "ui_left");
    frames(&mut app, 1);
    assert!((app.world().resource::<AccessRules>().game_speed - 0.9).abs() < 1e-9);
    press(&mut app, "ui_cancel"); // back: saves
    until_screen(&mut app, ScreenName::MainMenu);
    let file = saved(&dir);
    assert_eq!(file["access"]["reduce_motion"], json!(true));
    assert_eq!(file["access"]["colorblind"], json!("protanopia"));
    assert!((file["audio"]["master"].as_f64().unwrap() - 0.8).abs() < 1e-9);
}

#[test]
fn one_handed_layouts_apply_and_reset_and_a_rebind_swaps() {
    let dir = TempDir::new("shell-controls");
    let mut app = shell_test_app(cfg(&dir), None);
    to_menu(&mut app);
    focus(&mut app, "settings");
    press(&mut app, "ui_accept");
    until_screen(&mut app, ScreenName::Settings);
    to_tab(&mut app, "controls");
    press(&mut app, "ui_down");
    focus(&mut app, "controls.preset_one_hand_left");
    press(&mut app, "ui_accept");
    let b = shell(&app).bindings();
    assert_eq!(
        b["attack"],
        vec!["key:f", "pad:l2"],
        "the left-hand layout from data/input/presets.json"
    );
    assert_eq!(b["ui_accept"][1], "pad:l1");
    focus(&mut app, "controls.reset");
    press(&mut app, "ui_accept");
    assert_eq!(shell(&app).bindings()["attack"][0], "key:j");
    // rebind jump's keyboard slot to attack's key: the swap gives attack jump's old key
    focus(&mut app, "controls.bind_jump");
    press(&mut app, "ui_accept");
    assert_eq!(shell(&app).capturing, Some(("jump".to_string(), 0)));
    assert!(shell(&app).rows().iter().any(|r| r.id == "bind_jump"));
    shell_mut(&mut app).capture("key:j");
    let b = shell(&app).bindings();
    assert_eq!((b["jump"][0].as_str(), b["attack"][0].as_str()), ("key:j", "key:space"));
    assert!(
        shell(&app).message.as_ref().is_some_and(|(m, _)| m.contains("swap")),
        "the hint names the swap"
    );
}

#[test]
fn pause_offers_what_now_and_the_dialogue_history() {
    let dir = TempDir::new("shell-pause");
    let mut app = shell_test_app(cfg(&dir), None);
    to_play(&mut app);
    shell_mut(&mut app).say("Guide", "Second line.", false);
    press(&mut app, "pause");
    until_screen(&mut app, ScreenName::Pause);
    assert!(!app.world().resource::<GameActive>().0, "paused: the simulation stops");
    let ids: Vec<String> = shell(&app).rows().iter().map(|r| r.id.clone()).collect();
    assert_eq!(ids, ["resume", "help", "history", "settings", "quit"]);
    focus(&mut app, "help");
    press(&mut app, "ui_accept");
    until_screen(&mut app, ScreenName::Help);
    let lines = {{GAME_SLUG}}::shell::screens::lines_for(shell(&app));
    assert!(lines[0].starts_with("Goal:"), "{lines:?}");
    assert_eq!(lines[1], "Guide: Second line.");
    assert!(
        lines.iter().any(|l| l.starts_with("Jump: Space")),
        "controls with their keys: {lines:?}"
    );
    press(&mut app, "ui_cancel");
    until_screen(&mut app, ScreenName::Pause);
    focus(&mut app, "history");
    press(&mut app, "ui_accept");
    until_screen(&mut app, ScreenName::History);
    let lines = {{GAME_SLUG}}::shell::screens::lines_for(shell(&app));
    assert_eq!(lines.len(), 2, "both lines, oldest first: {lines:?}");
    assert!(lines[0].starts_with("Guide: Move right"));
    press(&mut app, "ui_cancel");
    press(&mut app, "pause"); // resumes
    assert_eq!(shell(&app).top_name(), Some(ScreenName::Play));
}

#[test]
fn a_held_subtitle_waits_for_accept_and_barks_follow_their_setting() {
    let dir = TempDir::new("shell-subtitle");
    let mut app = shell_test_app(cfg(&dir), None);
    to_play(&mut app);
    shell_mut(&mut app).set("access", "subtitle_hold", json!(true));
    shell_mut(&mut app).subtitle = None;
    assert!(
        !shell_mut(&mut app).say("Crowd", "Bark!", true),
        "barks are off by default"
    );
    assert!(shell_mut(&mut app).say("Guide", "Hold me.", false));
    frames(&mut app, 60 * 4); // the line is over by now
    assert!(
        shell(&app).subtitle_holding(),
        "with subtitle_hold the finished line waits"
    );
    press(&mut app, "ui_accept");
    assert!(shell(&app).subtitle.is_none(), "accept dismisses it");
    shell_mut(&mut app).set("access", "subtitle_hold", json!(false));
    shell_mut(&mut app).say("Guide", "Short.", false);
    frames(&mut app, 60 * 4);
    assert!(shell(&app).subtitle.is_none(), "without hold it goes on its own");
}

#[test]
fn auto_repeat_repeats_a_held_action_only_when_on() {
    let dir = TempDir::new("shell-repeat");
    let mut app = shell_test_app(cfg(&dir), None);
    to_play(&mut app);
    let count = |app: &mut App| {
        let mut n = 0;
        for _ in 0..60 {
            shell_mut(app).held.insert("attack".into());
            app.update();
            n += app
                .world()
                .resource::<Intent>()
                .pressed
                .iter()
                .filter(|a| *a == "attack")
                .count();
        }
        n
    };
    assert_eq!(count(&mut app), 0, "off: a held key is one press, never more");
    shell_mut(&mut app).held.clear();
    frames(&mut app, 2);
    shell_mut(&mut app).set("access", "auto_repeat", json!(true));
    assert_eq!(count(&mut app), 5, "on: 0.35 s then every 0.15 s over one second");
    // and held move actions become the Intent's direction
    shell_mut(&mut app).held.insert("move_right".into());
    app.update();
    assert_eq!(app.world().resource::<Intent>().dir, Vec2::X);
}

#[test]
fn the_menus_drive_finishes_and_writes_the_settings_it_promises() {
    let dir = TempDir::new("shell-drive-menus");
    let mut app = shell_test_app(cfg(&dir), Some(("menus", 5000)));
    let mut updates = 0;
    while app.should_exit().is_none() {
        app.update();
        updates += 1;
        assert!(updates < 5000, "the menus drive never finished");
    }
    assert_eq!(app.should_exit(), Some(AppExit::Success));
    let file = saved(&dir);
    assert_eq!(file["audio"]["master"], json!(0.5));
    assert_eq!(file["access"]["reduce_motion"], json!(true));
    assert!(shell(&app).quit_requested);
}

#[test]
fn the_pseudo_locale_brackets_every_label_and_french_falls_back_to_english() {
    let dir = TempDir::new("shell-locale");
    let mut app = shell_test_app(
        GameConfig {
            locale: Some("pseudo".into()),
            ..cfg(&dir)
        },
        None,
    );
    to_menu(&mut app);
    for row in shell(&app).rows() {
        assert!(
            row.label.starts_with('[') && row.label.ends_with(']'),
            "{:?}",
            row.label
        );
    }
    shell_mut(&mut app).locale_override = Some("fr".into());
    assert_eq!(shell(&app).t("menu.play"), "Jouer");
    // fr.json is complete (#270); the fallback to en for a missing key is in the i18n golden vectors (tests/golden.rs)
    assert_eq!(
        shell(&app).t("settings.access.narration"),
        "Lire les menus à voix haute",
        "the accessibility rows are French too"
    );
    frames(&mut app, 1);
    assert_eq!(
        shell(&app).narrator.last_line,
        "Jouer, bouton",
        "the focused row is narrated in the new language"
    );
}

// {{FOOTER}}
