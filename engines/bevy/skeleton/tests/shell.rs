// ---------------------------------------------------------------------------
// tests/shell.rs
// Purpose : The shell's screens, headless: the title, menu and settings answer the ui_* actions, settings edits save
//           to the run's own data folder, the one-handed layouts apply and reset, a rebind swaps, pause shows "What
//           now?" and the dialogue history, subtitle_hold waits for accept, auto_repeat repeats a held action, the
//           Intent carries the analog stick, triggers and held actions (#265), the display settings reach a window
//           outside automated runs (#268), the `menus` drive finishes with the file it promises, the juice demo
//           answers its actions and F8 writes a bug report (SOP-19, SOP-20; #165, #166, #167, #168, #275), and a
//           drive ignores the real keyboard that normal play reads (#276).
// Usage   : python tools/dev.py test   (or cargo test --test shell)
// Notes   : app::shell_test_app builds the real ShellPlugin on the headless test App; every test gets its own data
//           folder under the system temp dir, so no test touches another's settings.json or the player's.
//           Actions are injected as a key press would be (shell.inject) and take effect on the next update.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): real input during a drive (#276)
// ---------------------------------------------------------------------------
use std::path::PathBuf;

use bevy::prelude::*;
use bevy::window::{
    Monitor, MonitorSelection, PresentMode, PrimaryMonitor, PrimaryWindow, WindowMode, WindowResolution,
};
use serde_json::{Value, json};

use {{GAME_SLUG}}::app::shell_test_app;
use {{GAME_SLUG}}::game::{AccessRules, GameActive, GameConfig, Intent, Palette, ScreenShake};
use {{GAME_SLUG}}::shell::display::FrameLimit;
use {{GAME_SLUG}}::shell::view::ShellInputPlugin;
use {{GAME_SLUG}}::shell::{PadAxes, ScreenName, Shell};

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
fn the_intent_carries_the_analog_stick_triggers_and_held_actions() {
    let dir = TempDir::new("shell-analog");
    let mut app = shell_test_app(cfg(&dir), None);
    // in the menus a leaning stick and a held trigger never reach the game
    to_menu(&mut app);
    shell_mut(&mut app).pad = PadAxes {
        left: Vec2::new(0.6, 0.0),
        left_trigger: 1.0,
        right_trigger: 0.525,
    };
    app.update();
    assert_eq!(
        *app.world().resource::<Intent>(),
        Intent::default(),
        "menus: an empty Intent"
    );
    focus(&mut app, "play");
    press(&mut app, "ui_accept");
    until_screen(&mut app, ScreenName::Play);
    shell_mut(&mut app).held.insert("drift".into());
    shell_mut(&mut app).held.insert("ui_accept".into());
    app.update();
    let intent = app.world().resource::<Intent>().clone();
    // deadzone 0.2 (the default), radial and rescaled: 0.6 -> 0.5
    assert!(
        (intent.stick - Vec2::new(0.5, 0.0)).length() < 1e-5,
        "{:?}",
        intent.stick
    );
    assert!(
        (intent.dir - intent.stick).length() < 1e-5,
        "the stick alone steers dir at half speed"
    );
    assert_eq!(intent.left_trigger, 1.0);
    assert!((intent.right_trigger - 0.5).abs() < 1e-5, "{}", intent.right_trigger);
    assert!(intent.is_held("drift"), "a game action held through its binding");
    assert!(
        intent.is_held("move_right"),
        "the stick past the deadzone holds move_right"
    );
    assert!(!intent.is_held("ui_accept"), "ui_* actions never reach the game");
    // keyboard only: dir is a unit direction, the analog fields stay zero
    shell_mut(&mut app).pad = PadAxes::default();
    shell_mut(&mut app).held.insert("move_up".into());
    app.update();
    let intent = app.world().resource::<Intent>().clone();
    assert_eq!(intent.dir, Vec2::Y);
    assert_eq!(
        (intent.stick, intent.left_trigger, intent.right_trigger),
        (Vec2::ZERO, 0.0, 0.0)
    );
    // invert_y and a bigger deadzone come from the settings
    shell_mut(&mut app).held.clear();
    shell_mut(&mut app).set("input", "invert_y", json!(true));
    shell_mut(&mut app).set("input", "deadzone", json!(0.5));
    shell_mut(&mut app).pad.left = Vec2::new(0.0, 0.4);
    app.update();
    assert_eq!(
        app.world().resource::<Intent>().stick,
        Vec2::ZERO,
        "inside the 0.5 deadzone"
    );
    shell_mut(&mut app).pad.left = Vec2::new(0.0, 1.0);
    app.update();
    let intent = app.world().resource::<Intent>().clone();
    assert!((intent.stick - Vec2::NEG_Y).length() < 1e-5, "{:?}", intent.stick);
    assert!(intent.is_held("move_down") && !intent.is_held("move_up"));
}

/// A primary window and a 2560x1440 primary monitor in the headless world, as winit would spawn them.
fn spawn_window(app: &mut App) -> Entity {
    app.world_mut().spawn((
        Monitor {
            name: None,
            physical_height: 1440,
            physical_width: 2560,
            physical_position: IVec2::ZERO,
            refresh_rate_millihertz: None,
            scale_factor: 1.0,
            video_modes: Vec::new(),
        },
        PrimaryMonitor,
    ));
    let window = Window {
        resolution: WindowResolution::new(1280, 720).with_scale_factor_override(1.0),
        ..default()
    };
    app.world_mut().spawn((window, PrimaryWindow)).id()
}

#[test]
fn display_settings_reach_the_window_but_never_in_automated_runs() {
    let dir = TempDir::new("shell-display");
    let mut app = shell_test_app(
        GameConfig {
            automated: false,
            ..cfg(&dir)
        },
        None,
    );
    let win = spawn_window(&mut app);
    let window = |app: &App| app.world().get::<Window>(win).unwrap().clone();
    app.update();
    // the defaults: windowed 1920x1080 (fits the monitor), vsync, no cap
    let w = window(&app);
    assert_eq!(w.mode, WindowMode::Windowed);
    assert_eq!(w.present_mode, PresentMode::AutoVsync);
    assert_eq!((w.physical_width(), w.physical_height()), (1920, 1080));
    {
        let mut s = shell_mut(&mut app);
        s.set("display", "mode", json!("borderless"));
        s.set("display", "vsync", json!(false));
        s.set("display", "frame_cap", json!(120));
    }
    app.update();
    let w = window(&app);
    assert_eq!(w.mode, WindowMode::BorderlessFullscreen(MonitorSelection::Current));
    assert_eq!(w.present_mode, PresentMode::AutoNoVsync);
    assert_eq!(
        app.world().resource::<FrameLimit>().frame_time,
        Some(std::time::Duration::from_secs_f64(1.0 / 120.0))
    );
    {
        let mut s = shell_mut(&mut app);
        s.set("display", "mode", json!("windowed"));
        s.set("display", "resolution", json!([3840, 2160]));
        s.set("display", "frame_cap", json!(0));
    }
    app.update();
    let w = window(&app);
    assert_eq!(w.mode, WindowMode::Windowed);
    assert_eq!(
        (w.physical_width(), w.physical_height()),
        (2560, 1440),
        "a size bigger than the monitor is clamped to it"
    );
    assert_eq!(app.world().resource::<FrameLimit>().frame_time, None);

    // an automated run (dev.py smoke, captures, the sweep) leaves the window as the run made it
    let dir = TempDir::new("shell-display-auto");
    let mut app = shell_test_app(cfg(&dir), None);
    let win = spawn_window(&mut app);
    shell_mut(&mut app).set("display", "mode", json!("fullscreen"));
    frames(&mut app, 2);
    let w = app.world().get::<Window>(win).unwrap();
    assert_eq!(w.mode, WindowMode::Windowed);
    assert_eq!((w.physical_width(), w.physical_height()), (1280, 720));
}

/// The shell plus its real-input polling (as a windowed run has it), and a real key held down on the keyboard the
/// way winit reports it (ButtonInput<KeyCode>), for one update.
fn hold_real_key(app: &mut App, key: KeyCode) {
    app.world_mut().resource_mut::<ButtonInput<KeyCode>>().press(key);
    app.update();
}

#[test]
fn a_drive_ignores_the_real_keyboard_and_normal_play_reads_it() {
    // #276: a stray key or a virtual pad on a shared machine opened extra screens during a windowed access drive
    for (drive, read) in [(None, true), (Some("menus"), false)] {
        let dir = TempDir::new(&format!("shell-real-input-{read}"));
        let mut app = shell_test_app(cfg(&dir), drive.map(|name| (name, 5000)));
        app.add_plugins(ShellInputPlugin)
            .init_resource::<ButtonInput<KeyCode>>();
        frames(&mut app, 2);
        shell_mut(&mut app).last_device = "pad_xbox".into();
        hold_real_key(&mut app, KeyCode::KeyD); // move_right's key
        let s = shell(&app);
        let what = if read { "normal play" } else { "a drive" };
        assert_eq!(s.held.contains("move_right"), read, "{what}: the held D key");
        assert_eq!(
            s.last_device == "keyboard",
            read,
            "{what}: the device the prompts follow"
        );
    }
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
fn the_juice_demo_lands_hits_toggles_the_guard_and_leaves_with_its_screen() {
    let dir = TempDir::new("shell-juice");
    let mut app = shell_test_app(cfg(&dir), None);
    to_menu(&mut app);
    // the demo is on the menu of debug builds (cargo test builds one), right before Quit
    let ids: Vec<String> = shell(&app).rows().iter().map(|r| r.id.clone()).collect();
    assert_eq!(ids, ["play", "settings", "credits", "juice", "quit"]);
    focus(&mut app, "juice");
    press(&mut app, "ui_accept");
    until_screen(&mut app, ScreenName::Juice);
    assert!(
        !app.world().resource::<GameActive>().0,
        "the game itself does not run under the demo"
    );
    assert_eq!(shell(&app).history.len(), 1, "the guide's line is in the history");
    press(&mut app, "attack");
    let demo = shell(&app).juice.clone().expect("the demo's state");
    assert_eq!(demo.hits, 1, "the player starts in reach of the box");
    assert!(demo.shake.trauma > 0.0 && demo.spring.x != 0.0);
    assert_eq!(
        shell(&app).history.len(),
        1,
        "barks are off by default: no subtitle, no history line"
    );
    shell_mut(&mut app).set("access", "subtitle_barks", json!(true));
    press(&mut app, "attack");
    assert_eq!(shell(&app).history.len(), 2, "with barks on the box says something");
    // hold_to_toggle: interact flips the guard instead of holding it
    shell_mut(&mut app).set("access", "hold_to_toggle", json!(true));
    press(&mut app, "interact");
    assert!(shell(&app).juice.as_ref().unwrap().guard);
    // pause freezes it; quitting to the title drops it
    press(&mut app, "pause");
    until_screen(&mut app, ScreenName::Pause);
    let t = shell(&app).juice.as_ref().unwrap().real_time;
    frames(&mut app, 10);
    assert_eq!(
        shell(&app).juice.as_ref().unwrap().real_time,
        t,
        "paused: the demo's clock stops"
    );
    focus(&mut app, "quit");
    press(&mut app, "ui_accept");
    until_screen(&mut app, ScreenName::Title);
    frames(&mut app, 1);
    assert!(shell(&app).juice.is_none());
}

#[test]
fn f8_writes_a_bug_report_folder() {
    let dir = TempDir::new("shell-bug");
    let mut app = shell_test_app(cfg(&dir), None);
    to_menu(&mut app);
    shell_mut(&mut app).bug_key();
    frames(&mut app, 2);
    let folder = shell(&app).last_bug_report.clone().expect("a report folder");
    assert!(
        folder.starts_with(&dir.0),
        "in the run's data folder: {}",
        folder.display()
    );
    let info = std::fs::read_to_string(folder.join("info.txt")).unwrap();
    assert!(info.contains("screen: main_menu"), "{info}");
    let settings: Value =
        serde_json::from_str(&std::fs::read_to_string(folder.join("settings.json")).unwrap()).unwrap();
    assert!(settings["audio"].is_object());
    assert!(folder.join("log_tail.txt").is_file());
    assert!(
        !folder.join("screenshot.png").exists(),
        "headless: no window, no screenshot"
    );
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
