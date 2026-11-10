// ---------------------------------------------------------------------------
// shell/drive.rs
// Purpose : Scripted smoke scenarios (`python tools/dev.py smoke --drive <name>`): they press the same actions a
//           player would, frame by frame, and print proof lines dev.py echoes (SETTINGS_WRITTEN, PSEUDO_*, ACCESS_*,
//           DRIVE_*; CRASH_WRITTEN comes from the panic hook, crash.rs). Without --drive, a smoke run walks
//           title -> menu -> play and lets the game run.
// Usage   : menus          title -> settings: master volume 0.5 (left or right from whatever the data folder held),
//                          reduce motion on -> back (saves) -> quit; prints SETTINGS_WRITTEN <path> once the file
//                          holds the new values. Headless.
//           crash          a planted panic on the main menu: the hook writes the crash file (CRASH_WRITTEN <path>)
//                          and the run fails on purpose (exit 101). Headless.
//           pseudo         (with --locale pseudo) visits every screen and checks every visible label: not in
//                          brackets (untranslated), wider than its box (truncated) or past the window's edge:
//                          PSEUDO_SCREEN per screen, PSEUDO_FAIL per problem, then PSEUDO_PASS or PSEUDO_FAILED
//                          (exit 1). Opens a window (it measures the drawn text).
//           pseudo-plant   the same plus one label too small for its text: must fail and name plant.too_small
//           bug            presses F8 on the main menu and checks the bug_<time>/ folder: DRIVE_BUG <path>. Window.
//           show:<screen>  title | main_menu | settings | pause | help | history | credits | subtitle | juice: opens
//                          it, then ends (add --screenshot; juice lands a hit first). Opens a window.
//           access[:opts]  the accessibility sweep's tour (tools/access/sweep.py): res=WxH, scale=N, pad, read.
//                          Opens a window (it measures the drawn text).
// Notes   : A scenario is a list of steps; each step runs once a frame until it reports done, and every step has a
//           frame limit, so a broken menu fails instead of hanging. Steps run in an exclusive system (they need the
//           whole World: the shell, the window, the access report). A failure logs an ERROR line (dev.py fails on it)
//           and exits 1 (after the screenshot of where it stopped, with --screenshot: #276); done prints DRIVE_DONE
//           <name> and hands the smoke budget its last frame (the screenshot). While a drive runs, the window's real
//           keyboard and pads are not read at all (view.rs ShellInputPlugin, #276): only the drive presses.
//           Add a scenario: a function in scenario(), then document it in docs/ENGINE_FLOW.md.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): crash, pseudo, pseudo-plant, bug and show:juice;
//           the access tour visits the juice demo in debug builds (#275)
//           2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): a failed drive's screenshot (#276)
// ---------------------------------------------------------------------------
use std::collections::{BTreeMap, VecDeque};

use bevy::prelude::*;
use bevy::window::PrimaryWindow;
use serde_json::{Value, json};

use super::screens::TABS;
use super::view::AccessReport;
use super::{ScreenName, Shell};
use crate::app::Smoke;
use crate::logic::bindings;

// ---- Tunables ------------------------------------------------------------------
/// Frames after each injected press.
const PRESS_GAP: u32 = 2;
/// Frames a wait may take before the scenario fails.
const WAIT_LIMIT: u32 = 900;
/// Presses to reach a menu item.
const FOCUS_LIMIT: u32 = 60;
/// Frames for a whole scenario.
const DRIVE_LIMIT: u32 = 6000;
/// `menus` drives the master volume here.
pub const TARGET_MASTER: f64 = 0.5;
/// Presses a slider gets to reach its target (0..1 is 10 steps of 0.1).
const MAX_SLIDER_STEPS: u32 = 40;
const SLIDER_EPS: f64 = 1e-6;
/// Frames into the juice demo before show:juice attacks (the guide's line has settled), then frames after the hit
/// before the picture (still inside the hitstop, the flash and the ring).
const JUICE_HIT_FRAME: u32 = 40;
const JUICE_SHOT_FRAMES: u32 = 1;
pub const SHOW_TARGETS: [&str; 9] = [
    "title",
    "main_menu",
    "settings",
    "pause",
    "help",
    "history",
    "credits",
    "subtitle",
    "juice",
];
pub const SCENARIOS: [&str; 6] = ["menus", "crash", "pseudo", "pseudo-plant", "bug", "access"];
/// Drives that measure or picture the drawn screen, so they open a window.
const WINDOW_SCENARIOS: [&str; 4] = ["pseudo", "pseudo-plant", "bug", "access"];
const ACCESS_ACTIONS: [&str; 7] = [
    "ui_up",
    "ui_down",
    "ui_left",
    "ui_right",
    "ui_accept",
    "ui_cancel",
    "pause",
];
const PROMPT_ACTIONS: [&str; 6] = ["move_left", "move_right", "jump", "attack", "interact", "pause"];

type StepFn = Box<dyn FnMut(&mut World, &mut Drive) -> Result<bool, String> + Send + Sync>;

struct Step {
    what: String,
    limit: u32,
    run: StepFn,
}

#[derive(Resource)]
pub struct Drive {
    pub name: String,
    steps: VecDeque<Step>,
    frame: u32,
    step_frames: u32,
    /// The access drive's gamepad-only run: presses go through the pad bindings.
    pub pad: bool,
    /// Without --drive: walk into the game and stay there (the smoke budget ends the run).
    ends_run: bool,
    finished: bool,
    /// The access report of the screen being checked, waiting for its focus walk.
    report: Option<Value>,
    reach_seen: Vec<String>,
    /// Facts one step leaves for a later one (the preset applied before the reset).
    scratch: BTreeMap<String, Value>,
    /// The pseudo drive's tally: screens checked, labels seen, problems found.
    checked: u32,
    labels: u64,
    problems: u32,
}

/// The press that moves a slider from now towards target ("" once it is there).
pub fn slide_action(now: f64, target: f64) -> &'static str {
    if (now - target).abs() <= SLIDER_EPS {
        ""
    } else if now > target {
        "ui_left"
    } else {
        "ui_right"
    }
}

/// Is `name` a drive this build knows? (main.rs refuses unknown ones with exit 2.)
pub fn validate(name: &str) -> Result<(), String> {
    if name == "default" || SCENARIOS.contains(&name) || name.starts_with("access:") {
        return Ok(());
    }
    if let Some(target) = name.strip_prefix("show:") {
        if SHOW_TARGETS.contains(&target) {
            return Ok(());
        }
        return Err(format!("unknown --drive show:{target} ({})", SHOW_TARGETS.join(", ")));
    }
    Err(format!(
        "unknown --drive {name:?} ({}, access:<opts>, show:<screen>)",
        SCENARIOS.join(", ")
    ))
}

/// Does this drive need a window? (show: captures a picture; access and pseudo measure drawn text; bug's report
/// has a screenshot.)
pub fn needs_window(name: &str) -> bool {
    name.starts_with("show:") || WINDOW_SCENARIOS.contains(&name) || name.starts_with("access:")
}

impl Drive {
    pub fn new(name: &str) -> Result<Drive, String> {
        validate(name)?;
        let mut d = Drive {
            name: name.to_string(),
            steps: VecDeque::new(),
            frame: 0,
            step_frames: 0,
            pad: false,
            ends_run: name != "default",
            finished: false,
            report: None,
            reach_seen: Vec::new(),
            scratch: BTreeMap::new(),
            checked: 0,
            labels: 0,
            problems: 0,
        };
        scenario(&mut d)?;
        if name != "default" {
            info!("drive: scenario {name}");
        }
        Ok(d)
    }

    fn add(&mut self, what: &str, limit: u32, run: StepFn) {
        self.steps.push_back(Step {
            what: what.to_string(),
            limit,
            run,
        });
    }

    // ---- Steps -------------------------------------------------------------------------------------------------
    fn frames(&mut self, n: u32) {
        let mut left = n;
        self.add(
            &format!("{n} frames"),
            n + 2,
            Box::new(move |_, _| {
                left = left.saturating_sub(1);
                Ok(left == 0)
            }),
        );
    }

    /// Injects an action (through its pad binding in a pad run), then waits PRESS_GAP frames.
    fn press(&mut self, action: &str) {
        let action = action.to_string();
        let mut state = 0u32;
        self.add(
            &format!("press {action}"),
            PRESS_GAP + 2,
            Box::new(move |world, d| {
                if state == 0 {
                    press_now(world, d, &action)?;
                }
                state += 1;
                Ok(state > PRESS_GAP)
            }),
        );
    }

    fn wait_screen(&mut self, name: ScreenName) {
        self.add(
            &format!("screen {}", name.as_str()),
            WAIT_LIMIT,
            Box::new(move |world, _| Ok(world.resource::<Shell>().top_name() == Some(name))),
        );
    }

    /// Presses `step` until the focused item is `id`.
    fn focus_with(&mut self, id: &str, step: &str) {
        let (id, step) = (id.to_string(), step.to_string());
        let mut presses = 0u32;
        self.add(
            &format!("focus {id}"),
            FOCUS_LIMIT * 2 + 4,
            Box::new(move |world, d| {
                let now = world.resource::<Shell>().focus_id();
                if now == id {
                    return Ok(true);
                }
                if presses >= FOCUS_LIMIT {
                    return Err(format!("could not focus {id} (focused: {now:?})"));
                }
                presses += 1;
                press_now(world, d, &step)?;
                Ok(false)
            }),
        );
    }

    fn focus(&mut self, id: &str) {
        self.focus_with(id, "ui_down");
    }

    fn open(&mut self, item: &str, screen: ScreenName) {
        self.focus(item);
        self.press("ui_accept");
        self.wait_screen(screen);
    }

    /// Title (answers the consent question with Later) -> main menu.
    fn menu_from_title(&mut self) {
        self.wait_screen(ScreenName::Title);
        self.run("dismiss consent", |world, d| {
            if world.resource::<Shell>().top().is_some_and(|t| t.consent) {
                press_now(world, d, "ui_cancel")?;
            }
            Ok(())
        });
        self.frames(PRESS_GAP);
        self.press("ui_accept");
        self.wait_screen(ScreenName::MainMenu);
    }

    /// Settings: from the rows back up to the tab bar, then to a tab.
    fn open_tab(&mut self, tab: &str) {
        let mut presses = 0u32;
        self.add(
            "back to the tab bar",
            FOCUS_LIMIT * 2 + 4,
            Box::new(move |world, d| {
                let shell = world.resource::<Shell>();
                if shell.focus_id().starts_with("tabs.") {
                    return Ok(true);
                }
                if presses >= FOCUS_LIMIT {
                    return Err("could not get back to the tab bar".into());
                }
                presses += 1;
                press_now(world, d, "ui_up")?;
                Ok(false)
            }),
        );
        self.focus_with(&format!("tabs.{tab}"), "ui_right");
    }

    /// Presses left or right on the focused slider until the setting equals target, from any start value.
    fn slide_to(&mut self, section: &'static str, name: &'static str, target: f64) {
        let mut presses = 0u32;
        self.add(
            &format!("slide {section}.{name} to {target}"),
            MAX_SLIDER_STEPS * 2 + 4,
            Box::new(move |world, d| {
                let now = world.resource::<Shell>().num(section, name);
                let action = slide_action(now, target);
                if action.is_empty() {
                    return Ok(true);
                }
                if presses >= MAX_SLIDER_STEPS {
                    return Err(format!("{section}.{name} did not reach {target} (is {now})"));
                }
                presses += 1;
                press_now(world, d, action)?;
                Ok(false)
            }),
        );
    }

    /// A one-shot check or change.
    fn run(&mut self, what: &str, f: impl FnMut(&mut World, &mut Drive) -> Result<(), String> + Send + Sync + 'static) {
        let mut f = f;
        self.add(what, 2, Box::new(move |world, d| f(world, d).map(|()| true)));
    }

    fn wait_for(&mut self, what: &str, limit: u32, f: impl FnMut(&mut World) -> bool + Send + Sync + 'static) {
        let mut f = f;
        self.add(what, limit, Box::new(move |world, _| Ok(f(world))));
    }

    /// The access report of the screen on top: measure the drawn frame, walk the list with ui_down, print it.
    fn access_screen(&mut self, screen: &str) {
        let name = screen.to_string();
        let world_screen = screen == "play";
        self.run(&format!("request the report of {screen}"), move |world, _| {
            let Some(mut report) = world.get_resource_mut::<AccessReport>() else {
                return Err("the access drive needs a window: it measures the drawn text".into());
            };
            report.request(&name, world_screen);
            Ok(())
        });
        self.add(
            &format!("the report of {screen}"),
            WAIT_LIMIT,
            Box::new(|world, d| {
                let mut report = world.resource_mut::<AccessReport>();
                match report.result.take() {
                    Some(r) => {
                        d.report = Some(r);
                        Ok(true)
                    }
                    None => Ok(false),
                }
            }),
        );
        // which controls ui_down reaches (every enabled row must come round)
        let mut state: Option<(usize, Vec<String>, String)> = None; // (presses left, wanted ids, start)
        self.add(
            &format!("walk the list of {screen}"),
            FOCUS_LIMIT * 2 + 4,
            Box::new(move |world, d| {
                let shell = world.resource::<Shell>();
                if state.is_none() {
                    let rows = shell.rows();
                    let prefix = match shell.top() {
                        Some(t) if t.name == ScreenName::Settings => format!("{}.", TABS[t.tab.min(TABS.len() - 1)]),
                        _ => String::new(),
                    };
                    let want: Vec<String> = rows.iter().map(|r| format!("{prefix}{}", r.id)).collect();
                    d.reach_seen.clear();
                    state = Some((rows.len() + 1, want, shell.focus_id()));
                }
                let (left, _, _) = state.as_mut().unwrap();
                let id = shell.focus_id();
                if !id.is_empty() {
                    d.reach_seen.push(id);
                }
                if *left == 0 {
                    return Ok(true);
                }
                *left -= 1;
                press_now(world, d, "ui_down")?;
                Ok(false)
            }),
        );
        let screen_name = screen.to_string();
        self.run(&format!("print the report of {screen}"), move |world, d| {
            let shell = world.resource::<Shell>();
            let rows = shell.rows();
            let prefix = match shell.top() {
                Some(t) if t.name == ScreenName::Settings => format!("{}.", TABS[t.tab.min(TABS.len() - 1)]),
                _ => String::new(),
            };
            let want: Vec<String> = rows.iter().map(|r| format!("{prefix}{}", r.id)).collect();
            let unreached: Vec<&String> = want.iter().filter(|w| !d.reach_seen.contains(w)).collect();
            let mut narration = BTreeMap::new();
            for row in &rows {
                let role = shell.t(super::role_key(row.kind));
                narration.insert(
                    format!("{prefix}{}", row.id),
                    super::narrator::Narrator::describe(&row.label, &role, &row.value),
                );
            }
            let start = if want.is_empty() {
                String::new()
            } else {
                d.reach_seen.first().cloned().unwrap_or_default()
            };
            let mut r = d
                .report
                .take()
                .unwrap_or_else(|| json!({"screen": screen_name, "texts": []}));
            r["focus"] = json!({
                "start": start,
                "controls": want.len(),
                "reached": want.len() - unreached.len(),
                "unreached": unreached,
                "focus_like_hover": [],
                "narration": narration,
            });
            println!("ACCESS_SCREEN {}", serde_json::to_string(&r).unwrap_or_default());
            Ok(())
        });
    }

    /// The pseudo check of the screen on top: PSEUDO_SCREEN, a PSEUDO_FAIL line per problem, counted for the end.
    fn check(&mut self, screen: &str) {
        let name = screen.to_string();
        self.run(&format!("request the check of {screen}"), move |world, _| {
            let Some(mut report) = world.get_resource_mut::<AccessReport>() else {
                return Err("the pseudo drive needs a window: it measures the drawn text".into());
            };
            report.request_check(&name);
            Ok(())
        });
        let name = screen.to_string();
        self.add(
            &format!("the check of {screen}"),
            WAIT_LIMIT,
            Box::new(move |world, d| {
                let Some(r) = world.resource_mut::<AccessReport>().result.take() else {
                    return Ok(false);
                };
                let problems = r["problems"].as_array().cloned().unwrap_or_default();
                let labels = r["labels"].as_u64().unwrap_or(0);
                println!("PSEUDO_SCREEN {name} labels {labels} problems {}", problems.len());
                for p in &problems {
                    println!(
                        "PSEUDO_FAIL {name} label {}: {} ({:?})",
                        p["id"].as_str().unwrap_or("?"),
                        p["why"].as_str().unwrap_or("?"),
                        p["text"].as_str().unwrap_or("")
                    );
                }
                d.checked += 1;
                d.labels += labels;
                d.problems += problems.len() as u32;
                Ok(true)
            }),
        );
    }

    fn done(&mut self, code: u8) {
        self.run("done", move |world, d| {
            finish(world, d, code);
            Ok(())
        });
    }
}

/// Injects one action now: through the action's pad binding in a pad run (a gamepad-only player must be able to
/// press it), else straight in.
fn press_now(world: &mut World, d: &Drive, action: &str) -> Result<(), String> {
    let mut shell = world.resource_mut::<Shell>();
    if d.pad {
        let b = shell.bindings();
        let pad = b
            .get(action)
            .and_then(|slots| slots.iter().find(|s| s.starts_with("pad:")))
            .cloned()
            .ok_or_else(|| format!("{action} has no gamepad button: a gamepad-only player cannot press it"))?;
        shell.last_device = "pad_generic".into();
        shell.press_binding(&pad);
    } else {
        shell.inject(action);
    }
    Ok(())
}

fn finish(world: &mut World, d: &mut Drive, code: u8) {
    if d.finished {
        return;
    }
    d.finished = true;
    println!("DRIVE_DONE {}", d.name);
    if code == 0
        && let Some(mut smoke) = world.get_resource_mut::<Smoke>()
    {
        smoke.finish_now(); // the next frame is the smoke run's last: screenshot, SMOKE_DONE, exit 0
        return;
    }
    world.write_message(if code == 0 {
        AppExit::Success
    } else {
        AppExit::from_code(code)
    });
}

fn fail(world: &mut World, d: &mut Drive, msg: &str) {
    error!("drive {}: {msg}", d.name);
    d.finished = true;
    d.steps.clear();
    // with --screenshot, one more frame for the picture of where the drive stopped (#276); else exit now
    if !world
        .get_resource_mut::<Smoke>()
        .is_some_and(|mut smoke| smoke.finish_failed(1))
    {
        world.write_message(AppExit::from_code(1));
    }
}

/// Runs the current step once a frame (an exclusive system: steps need the whole World).
pub fn drive_update(world: &mut World) {
    let Some(mut drive) = world.remove_resource::<Drive>() else {
        return;
    };
    if !drive.finished {
        drive.frame += 1;
        if drive.frame > DRIVE_LIMIT {
            let msg = format!("did not finish in {DRIVE_LIMIT} frames");
            fail(world, &mut drive, &msg);
        } else if let Some(mut step) = drive.steps.pop_front() {
            drive.step_frames += 1;
            match (step.run)(world, &mut drive) {
                Ok(true) => drive.step_frames = 0,
                Ok(false) if drive.step_frames > step.limit => {
                    let msg = format!("timed out waiting for {}", step.what);
                    fail(world, &mut drive, &msg);
                }
                Ok(false) => drive.steps.push_front(step),
                Err(e) => {
                    let msg = format!("{}: {e}", step.what);
                    fail(world, &mut drive, &msg);
                }
            }
        } else if drive.ends_run {
            finish(world, &mut drive, 0);
        } else {
            // The default drive is through once the game is up: stop counting, or a run longer than DRIVE_LIMIT
            // frames (a whole race is about 7,500) fails as "did not finish"
            drive.finished = true;
        }
    }
    world.insert_resource(drive);
}

// ---- Scenarios -----------------------------------------------------------------------------------------------
fn scenario(d: &mut Drive) -> Result<(), String> {
    let name = d.name.clone();
    match name.as_str() {
        "default" => {
            d.menu_from_title();
            d.open("play", ScreenName::Loading);
            d.wait_screen(ScreenName::Play);
        }
        "menus" => menus(d),
        "crash" => crash(d),
        "pseudo" => pseudo(d, false),
        "pseudo-plant" => pseudo(d, true),
        "bug" => bug(d),
        _ if name.starts_with("show:") => show(d, &name[5..]),
        _ if name == "access" || name.starts_with("access:") => access(d, name.strip_prefix("access:").unwrap_or(""))?,
        _ => return validate(&name),
    }
    Ok(())
}

fn menus(d: &mut Drive) {
    d.menu_from_title();
    d.open("settings", ScreenName::Settings);
    d.open_tab("audio");
    d.press("ui_down");
    d.focus("audio.master");
    d.slide_to("audio", "master", TARGET_MASTER);
    d.open_tab("access");
    d.press("ui_down");
    d.focus("access.reduce_motion");
    d.run("reduce motion on", |world, d| {
        if !world.resource::<Shell>().flag("access", "reduce_motion") {
            press_now(world, d, "ui_accept")?;
        }
        Ok(())
    });
    d.frames(PRESS_GAP);
    d.press("ui_cancel"); // back: saves settings.json
    d.wait_screen(ScreenName::MainMenu);
    d.run("settings.json holds the new values", |world, _| {
        let shell = world.resource::<Shell>();
        let path = shell.store.settings_path();
        let text = std::fs::read_to_string(&path).map_err(|e| format!("{}: {e}", path.display()))?;
        let saved: Value = serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))?;
        let master = saved["audio"]["master"].as_f64().unwrap_or(-1.0);
        if !slide_action(master, TARGET_MASTER).is_empty() || saved["access"]["reduce_motion"] != json!(true) {
            return Err(format!(
                "settings.json does not hold master {TARGET_MASTER} and reduce_motion true: {}",
                path.display()
            ));
        }
        println!("SETTINGS_WRITTEN {}", path.display());
        Ok(())
    });
    d.focus("quit");
    d.press("ui_accept");
    d.run("quit ends the run", |world, _| {
        if world.resource::<Shell>().quit_requested {
            Ok(())
        } else {
            Err("quit did not end the run".into())
        }
    });
    d.done(0);
}

fn crash(d: &mut Drive) {
    d.menu_from_title();
    d.frames(2);
    d.run("the planted panic", |_, _| {
        panic!("drive crash: a planted panic to prove the crash file (expected)");
    });
}

/// Esc on the "press a key" prompt: the capture ends without a change (view.rs does this for a real key).
fn cancel_capture(world: &mut World, _: &mut Drive) -> Result<(), String> {
    world.resource_mut::<Shell>().capture("");
    Ok(())
}

/// The pseudo-locale tour: every screen, each settings tab at its top and scrolled to its end.
fn pseudo(d: &mut Drive, plant: bool) {
    d.run("the pseudo-locale", move |world, _| {
        let mut shell = world.resource_mut::<Shell>();
        shell.plant = plant; // view.rs draws one label too small for its text on the main menu
        if !shell.is_pseudo() {
            shell.locale_override = Some("pseudo".into());
            shell.changed();
            println!("DRIVE_NOTE the pseudo drive switched the locale to pseudo (pass --locale pseudo next time)");
        }
        Ok(())
    });
    d.wait_screen(ScreenName::Title);
    d.frames(PRESS_GAP);
    // the consent question when it shows (a first start: a fresh data folder), then the title itself
    d.check("title.first");
    d.run("dismiss consent", |world, d| {
        if world.resource::<Shell>().top().is_some_and(|t| t.consent) {
            press_now(world, d, "ui_cancel")?;
        }
        Ok(())
    });
    d.frames(PRESS_GAP);
    d.wait_for("the blinking prompt", WAIT_LIMIT, |world| {
        world.resource::<Shell>().blink_on
    });
    d.check("title");
    d.press("ui_accept");
    d.wait_screen(ScreenName::MainMenu);
    d.check("main_menu");
    d.open("settings", ScreenName::Settings);
    for tab in TABS {
        d.open_tab(tab);
        d.check(&format!("settings.{tab}"));
        d.press("ui_down");
        d.focus(&format!("{tab}.back")); // scrolled to the end: the rows below the fold
        d.check(&format!("settings.{tab}.end"));
        if tab == "controls" {
            d.focus("controls.bind_jump");
            d.press("ui_accept"); // the "press a key" prompt
            d.check("settings.capture");
            d.run("cancel the capture", cancel_capture);
            d.frames(PRESS_GAP);
        }
    }
    d.press("ui_cancel");
    d.wait_screen(ScreenName::MainMenu);
    d.open("credits", ScreenName::Credits);
    d.check("credits");
    d.press("ui_cancel");
    d.wait_screen(ScreenName::MainMenu);
    if cfg!(debug_assertions) {
        // the juice demo (debug builds), a hit in it, and the pause menu over it
        d.run("barks on", |world, _| {
            world
                .resource_mut::<Shell>()
                .set("access", "subtitle_barks", json!(true));
            Ok(())
        });
        d.open("juice", ScreenName::Loading);
        d.check("loading");
        d.wait_screen(ScreenName::Juice);
        d.frames(20);
        d.check("juice");
        d.press("attack");
        d.frames(3);
        d.check("juice.hit");
        d.press("pause");
        d.wait_screen(ScreenName::Pause);
        d.check("pause");
        d.open("quit", ScreenName::Title);
        d.press("ui_accept");
        d.wait_screen(ScreenName::MainMenu);
        d.open("play", ScreenName::Loading);
    } else {
        d.open("play", ScreenName::Loading);
        d.check("loading");
    }
    d.wait_screen(ScreenName::Play);
    d.frames(5);
    d.check("play");
    d.press("pause");
    d.wait_screen(ScreenName::Pause);
    d.check("pause.play");
    for (item, screen) in [("help", ScreenName::Help), ("history", ScreenName::History)] {
        d.open(item, screen);
        d.check(item);
        d.press("ui_cancel");
        d.wait_screen(ScreenName::Pause);
    }
    d.open("quit", ScreenName::Title);
    d.run("the verdict", |world, d| {
        if d.problems == 0 {
            println!(
                "PSEUDO_PASS {} screens, {} labels, nothing truncated or untranslated",
                d.checked, d.labels
            );
            finish(world, d, 0);
        } else {
            println!("PSEUDO_FAILED {} problem(s) on {} screens", d.problems, d.checked);
            error!("pseudo: {} label problem(s); see the PSEUDO_FAIL lines", d.problems);
            finish(world, d, 1);
        }
        Ok(())
    });
}

/// F8 on the main menu, then the report's four files on disk.
fn bug(d: &mut Drive) {
    d.menu_from_title();
    d.run("press F8", |world, _| {
        let mut shell = world.resource_mut::<Shell>();
        if !shell.debug_build {
            return Err("the bug report key works in debug builds only (drop --release)".into());
        }
        shell.bug_key();
        Ok(())
    });
    d.wait_for("the bug report", WAIT_LIMIT, |world| {
        world.resource::<Shell>().last_bug_report.is_some()
    });
    d.run("DRIVE_BUG", |world, _| {
        let dir = world.resource::<Shell>().last_bug_report.clone().unwrap_or_default();
        for f in super::bug_report::FILES {
            let path = dir.join(f);
            if !path.is_file() || std::fs::metadata(&path).map_or(0, |m| m.len()) == 0 {
                return Err(format!("the bug report lacks {f} ({})", dir.display()));
            }
        }
        println!("DRIVE_BUG {}", dir.display());
        Ok(())
    });
    d.done(0);
}

/// Main menu > Juice demo (debug builds only).
fn to_juice(d: &mut Drive) {
    d.menu_from_title();
    d.run("a debug build", |world, _| {
        if world.resource::<Shell>().debug_build {
            Ok(())
        } else {
            Err("the juice demo is in debug builds only (drop --release)".into())
        }
    });
    d.open("juice", ScreenName::Loading);
    d.wait_screen(ScreenName::Juice);
}

fn to_play(d: &mut Drive) {
    d.menu_from_title();
    d.open("play", ScreenName::Loading);
    d.wait_screen(ScreenName::Play);
}

fn show(d: &mut Drive, target: &str) {
    match target {
        "title" => {
            d.wait_screen(ScreenName::Title);
            d.run("dismiss consent", |world, d| {
                if world.resource::<Shell>().top().is_some_and(|t| t.consent) {
                    press_now(world, d, "ui_cancel")?;
                }
                Ok(())
            });
            d.frames(10);
            d.wait_for("the blinking prompt", WAIT_LIMIT, |world| {
                world.resource::<Shell>().blink_on
            });
        }
        "main_menu" => d.menu_from_title(),
        "settings" => {
            d.menu_from_title();
            d.open("settings", ScreenName::Settings);
            d.open_tab("audio");
            d.press("ui_down");
            d.focus("audio.master");
            d.press("ui_left");
            d.frames(5);
        }
        "credits" => {
            d.menu_from_title();
            d.open("credits", ScreenName::Credits);
            d.frames(5);
        }
        "juice" => {
            to_juice(d);
            d.frames(JUICE_HIT_FRAME); // the guide's line is up, the camera settled
            d.press("attack");
            d.frames(JUICE_SHOT_FRAMES); // the picture: the hit's flash, ring and squash
        }
        "subtitle" => {
            d.run("speaker names on", |world, _| {
                world
                    .resource_mut::<Shell>()
                    .set("access", "speaker_names", json!(true));
                Ok(())
            });
            to_play(d);
            d.frames(10);
        }
        _ => {
            // pause, help, history: through the pause menu
            to_play(d);
            d.frames(30);
            d.press("pause");
            d.wait_screen(ScreenName::Pause);
            if target == "help" {
                d.open("help", ScreenName::Help);
            } else if target == "history" {
                d.open("history", ScreenName::History);
            }
            d.frames(5);
        }
    }
    d.done(0);
}

/// The accessibility sweep (#91, #85): access[:res=WxH][,scale=N][,pad][,read].
fn access(d: &mut Drive, options: &str) -> Result<(), String> {
    let (mut scale, mut res, mut read) = (1.0f64, None::<(f32, f32)>, false);
    for part in options.split(',').filter(|p| !p.is_empty()) {
        if part == "pad" {
            d.pad = true;
        } else if part == "read" {
            read = true; // the readable font and double line spacing (#167)
        } else if let Some(v) = part.strip_prefix("scale=") {
            scale = v.parse().map_err(|_| format!("bad scale {v:?}"))?;
        } else if let Some(v) = part.strip_prefix("res=") {
            let (w, h) = v.split_once('x').ok_or(format!("bad res {v:?} (WxH)"))?;
            res = Some((
                w.parse().map_err(|_| format!("bad res {v:?}"))?,
                h.parse().map_err(|_| format!("bad res {v:?}"))?,
            ));
        } else {
            return Err(format!("unknown access option {part} (res=WxH, scale=N, pad, read)"));
        }
    }
    let pad = d.pad;
    d.run("ACCESS_INPUT", move |world, _| {
        let shell = world.resource::<Shell>();
        let b = shell.bindings();
        let mut actions = serde_json::Map::new();
        for a in ACCESS_ACTIONS {
            let slots = b.get(a).cloned().unwrap_or_default();
            actions.insert(
                a.to_string(),
                json!({
                    "keyboard": slots.iter().any(|s| s.starts_with("key:")),
                    "gamepad": slots.iter().any(|s| s.starts_with("pad:")),
                }),
            );
        }
        println!(
            "ACCESS_INPUT {}",
            json!({"pad": pad, "text_scale": scale, "actions": actions})
        );
        Ok(())
    });
    d.wait_screen(ScreenName::Title);
    if let Some((w, h)) = res {
        d.run("window size", move |world, _| {
            let mut q = world.query_filtered::<&mut Window, With<PrimaryWindow>>();
            match q.single_mut(world) {
                Ok(mut win) => {
                    win.resolution.set(w, h);
                    Ok(())
                }
                Err(_) => Err("the access drive needs a window".into()),
            }
        });
        d.frames(3);
    }
    if scale != 1.0 || read {
        d.run("text scale", move |world, _| {
            let mut shell = world.resource_mut::<Shell>();
            shell.set("access", "text_scale", json!(scale));
            if read {
                shell.set("access", "readable_font", json!(true));
                shell.set("access", "line_spacing", json!(2.0));
            }
            Ok(())
        });
        d.frames(3);
    }
    d.access_screen("title");
    d.run("dismiss consent", |world, d| {
        if world.resource::<Shell>().top().is_some_and(|t| t.consent) {
            press_now(world, d, "ui_cancel")?;
        }
        Ok(())
    });
    d.frames(PRESS_GAP);
    d.press("ui_accept");
    d.wait_screen(ScreenName::MainMenu);
    d.access_screen("main_menu");
    d.open("settings", ScreenName::Settings);
    for tab in TABS {
        d.open_tab(tab);
        d.access_screen(&format!("settings/{tab}"));
        if tab == "controls" {
            // the one-handed layout (#166), live, then reset
            d.focus("controls.preset_one_hand_left");
            d.press("ui_accept");
            d.run("the layout applied", |world, d| {
                let applied = world.resource::<Shell>().bindings()["attack"]
                    .first()
                    .is_some_and(|b| b == "key:f");
                d.scratch.insert("preset_applied".into(), json!(applied));
                Ok(())
            });
            d.focus("controls.reset");
            d.press("ui_accept");
            d.run("ACCESS_PRESET", |world, d| {
                let shell = world.resource::<Shell>();
                let applied = d.scratch.get("preset_applied") == Some(&json!(true));
                let reset = shell.bindings()["attack"].first().is_some_and(|b| b == "key:j");
                println!("ACCESS_PRESET {}", json!({"applied": applied, "reset": reset}));
                Ok(())
            });
        }
    }
    d.press("ui_cancel");
    d.wait_screen(ScreenName::MainMenu);
    d.open("credits", ScreenName::Credits);
    d.access_screen("credits");
    d.press("ui_cancel");
    d.wait_screen(ScreenName::MainMenu);
    if cfg!(debug_assertions) {
        // the juice demo (debug builds): its HUD over the world, like play's
        d.open("juice", ScreenName::Loading);
        d.wait_screen(ScreenName::Juice);
        d.frames(30);
        d.access_screen("juice");
        d.press("pause");
        d.wait_screen(ScreenName::Pause);
        d.open("quit", ScreenName::Title);
        d.press("ui_accept");
        d.wait_screen(ScreenName::MainMenu);
    }
    d.open("play", ScreenName::Loading);
    d.wait_screen(ScreenName::Play);
    d.frames(40);
    d.access_screen("play");
    d.run("ACCESS_SUBTITLE", |world, _| {
        let shell = world.resource::<Shell>();
        let sub = shell.subtitle.as_ref();
        println!(
            "ACCESS_SUBTITLE {}",
            json!({
                "visible": sub.is_some() && shell.flag("access", "subtitles"),
                "text": sub.map_or("", |s| s.text.as_str()),
                "speaker": sub.map_or("", |s| s.speaker.as_str()),
                "id": "",
            })
        );
        Ok(())
    });
    d.run("ACCESS_PROMPTS", |world, _| {
        let shell = world.resource::<Shell>();
        let b = shell.bindings();
        let mut rows = serde_json::Map::new();
        for a in PROMPT_ACTIONS {
            let kb = bindings::prompt_binding(&b, a, "keyboard");
            let (_, shown) = shell.prompt(a);
            rows.insert(
                a.to_string(),
                json!({"keyboard": shell.binding_label(&bindings::glyph_name("keyboard", kb)), "shown": shown}),
            );
        }
        println!(
            "ACCESS_PROMPTS {}",
            json!({"device": shell.last_device, "glyphs": shell.glyph_set(), "actions": rows})
        );
        Ok(())
    });
    // subtitle_hold (#167), live: a finished line stays until accept, then goes
    d.run("subtitle hold on", |world, _| {
        let mut shell = world.resource_mut::<Shell>();
        shell.set("access", "subtitle_hold", json!(true));
        shell.subtitle = None;
        let (speaker, text) = (shell.t("play.guide"), shell.t("play.welcome"));
        if !shell.say(&speaker, &text, false) {
            return Err("the hold check could not show a line (subtitles off?)".into());
        }
        Ok(())
    });
    d.wait_for("the line to finish and hold", WAIT_LIMIT, |world| {
        world.resource::<Shell>().subtitle_holding()
    });
    d.press("ui_accept");
    d.run("ACCESS_HOLD", |world, _| {
        let mut shell = world.resource_mut::<Shell>();
        let dismissed = shell.subtitle.is_none();
        println!("ACCESS_HOLD {}", json!({"held": true, "dismissed": dismissed}));
        shell.set("access", "subtitle_hold", json!(false));
        Ok(())
    });
    d.press("pause");
    d.wait_screen(ScreenName::Pause);
    d.access_screen("pause");
    for (item, screen) in [("help", ScreenName::Help), ("history", ScreenName::History)] {
        // #167: both reachable and readable
        d.open(item, screen);
        d.access_screen(item);
        d.press("ui_cancel");
        d.wait_screen(ScreenName::Pause);
    }
    d.open("quit", ScreenName::Title);
    d.done(0);
    Ok(())
}
