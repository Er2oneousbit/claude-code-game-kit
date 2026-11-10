// ---------------------------------------------------------------------------
// shell/mod.rs
// Purpose : The runtime shell around the game: the screen stack (boot, title, main menu, settings, credits, loading,
//           play, pause, "What now?", dialogue history), the player's settings applied at run time, the user-data
//           folder, localization, subtitles, menu narration, and the scripted smoke scenarios (drive.rs).
// Usage   : app.add_plugins(ShellPlugin) (app.rs does it for every run; tests use app::shell_test_app)
//           shell.push(ScreenName::Settings); shell.inject("ui_down"); shell.t("menu.play"); shell.say("Guide", "...")
//           shell.set_objective(text); shell.focus_id()
// Notes   : Headless by design: this module touches no renderer or ButtonInput, and a window only when one exists
//           outside an automated run (display.rs), so `dev.py smoke --drive menus`
//           walks the menus and saves settings.json without a GPU, and tests/shell.rs drives it with app.update().
//           The screens' rows are rebuilt from the settings each time they are needed (screens.rs): the stack only
//           keeps focus, tab and scroll. Drawing lives in view.rs (added with a window), which rebuilds its bevy_ui
//           tree whenever `version` changes. Only the top screen gets input; the game (GamePlugin) runs only while
//           Play is on top (the GameActive resource). Actions arrive as groups: every action one key is bound to, in
//           sorted order, tried until one is used, so Esc backs out of a menu (ui_cancel) but pauses the game (pause).
//
// Pseudocode:
//   each frame: tick timers (boot and loading advance, blink, subtitle, messages) -> for each pending press group:
//   a held subtitle takes ui_accept first, else the top screen's action() -> auto-repeat held game actions -> write
//   Intent (held move_* + shaped stick -> dir, presses, held game actions, stick, triggers; all zero outside Play)
//   -> GameActive = Play on top -> narrator line for the focused row ->
//   when the settings changed: ScreenShake, Palette, AccessRules, UiScale follow them, and the display settings
//   go to the primary window (display.rs, never in automated runs)
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): analog stick, triggers and held actions in the
//           Intent (#265); display settings applied to the window (#268)
//           2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): crash files, the F8 bug report, the juice demo
//           screen (debug builds) and the loading screen's next screen (#275)
// ---------------------------------------------------------------------------
pub mod bug_report;
pub mod crash;
pub mod display;
pub mod drive;
pub mod input;
pub mod juice;
pub mod narrator;
pub mod screens;
pub mod store;
pub mod view;

use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;

use bevy::prelude::*;
use serde_json::{Value, json};

pub use juice::HideUnderJuice;

use crate::game::{AccessRules, GameActive, GameConfig, Intent, Palette, ScreenShake};
use crate::logic::analog;
use crate::logic::auto_repeat::AutoRepeat;
use crate::logic::bindings::{self, Bindings};
use crate::logic::i18n::{self, Tables};
use crate::logic::settings;
use narrator::Narrator;
use screens::{Row, RowKind};
use store::Store;

// ---- Tunables ------------------------------------------------------------------
/// Lines the dialogue history keeps (#167).
pub const MAX_HISTORY: usize = 50;
/// Seconds a settings message (rebound, reset) stays.
pub const MESSAGE_S: f64 = 3.0;
pub const TOAST_S: f64 = 2.5;
/// The title's "press any key" blinks at this period.
pub const BLINK_S: f64 = 1.2;
/// Boot and loading screens stay this long (one frame of settle time in automated runs).
pub const LOADING_S: f64 = 0.4;
/// A subtitle shows for this long plus a share per word.
pub const SUBTITLE_MIN_S: f64 = 1.5;
pub const SUBTITLE_PER_WORD_S: f64 = 0.3;
/// The game actions a held key repeats with access.auto_repeat (#166).
pub const REPEAT_ACTIONS: [&str; 3] = ["jump", "attack", "interact"];
pub const MOVE_ACTIONS: [(&str, Vec2); 4] = [
    ("move_left", Vec2::NEG_X),
    ("move_right", Vec2::X),
    ("move_up", Vec2::Y),
    ("move_down", Vec2::NEG_Y),
];
/// Raw stick deflection that also holds a move_* action (Intent.held); never below the player's deadzone.
pub const STICK_HOLD_MIN: f32 = 0.2;

/// The pad's analog inputs as the hardware reports them (view.rs polls them; tests and drives may set them).
/// The shell shapes them into the Intent with the player's deadzone and invert_y.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct PadAxes {
    /// Left stick, -1..1 each, up is +y.
    pub left: Vec2,
    /// Triggers, 0 at rest to 1.
    pub left_trigger: f32,
    pub right_trigger: f32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ScreenName {
    Boot,
    Title,
    MainMenu,
    Settings,
    Credits,
    Loading,
    Play,
    Pause,
    Help,
    History,
    /// The juice demo (debug builds; juice.rs).
    Juice,
}

impl ScreenName {
    pub fn as_str(self) -> &'static str {
        match self {
            ScreenName::Boot => "boot",
            ScreenName::Title => "title",
            ScreenName::MainMenu => "main_menu",
            ScreenName::Settings => "settings",
            ScreenName::Credits => "credits",
            ScreenName::Loading => "loading",
            ScreenName::Play => "play",
            ScreenName::Pause => "pause",
            ScreenName::Help => "help",
            ScreenName::History => "history",
            ScreenName::Juice => "juice",
        }
    }

    pub fn parse(name: &str) -> Option<ScreenName> {
        [
            ScreenName::Boot,
            ScreenName::Title,
            ScreenName::MainMenu,
            ScreenName::Settings,
            ScreenName::Credits,
            ScreenName::Loading,
            ScreenName::Play,
            ScreenName::Pause,
            ScreenName::Help,
            ScreenName::History,
            ScreenName::Juice,
        ]
        .into_iter()
        .find(|s| s.as_str() == name)
    }

    /// Drawn over the screen below it (the game keeps showing, frozen).
    pub fn transparent(self) -> bool {
        matches!(self, ScreenName::Pause | ScreenName::Help | ScreenName::History)
    }
}

/// One screen on the stack: what it remembers between frames.
#[derive(Debug, Clone)]
pub struct ScreenState {
    pub name: ScreenName,
    /// Index into screens::rows_for.
    pub focus: usize,
    /// Settings: the open tab and whether focus sits on the tab bar.
    pub tab: usize,
    pub on_tabs: bool,
    /// Controls: 0 = the keyboard cell, 1 = the pad cell.
    pub cell: usize,
    /// Text pages: the first visible line.
    pub scroll: usize,
    /// Title: the telemetry consent question is open.
    pub consent: bool,
    /// Seconds since the screen opened.
    pub t: f64,
}

impl ScreenState {
    fn new(name: ScreenName) -> Self {
        ScreenState {
            name,
            focus: 0,
            tab: 0,
            on_tabs: true,
            cell: 0,
            scroll: 0,
            consent: false,
            t: 0.0,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Subtitle {
    pub speaker: String,
    pub text: String,
    pub remaining: f64,
    /// Finished, waiting for accept (access.subtitle_hold, #167).
    pub holding: bool,
}

#[derive(Resource)]
pub struct Shell {
    pub store: Store,
    pub settings: Value,
    pub tables: Tables,
    /// --locale: beats the settings until the player picks a language.
    pub locale_override: Option<String>,
    pub presets: Value,
    pub colours: Value,
    pub stack: Vec<ScreenState>,
    /// Presses waiting for this frame: each entry is the actions one key is bound to, in sorted order.
    pub pending: Vec<Vec<String>>,
    /// Game actions held right now through their bindings (the view polls them; drives set them). The stick's own
    /// move_* holds are added in held_actions().
    pub held: BTreeSet<String>,
    /// The pad's analog inputs, raw (view.rs writes them every frame).
    pub pad: PadAxes,
    /// Game actions pressed this frame, auto-repeats included; the Intent takes them.
    pub game_pressed: Vec<String>,
    repeaters: BTreeMap<String, AutoRepeat>,
    pub history: Vec<(String, String)>,
    pub objective: String,
    pub message: Option<(String, f64)>,
    pub toasts: Vec<(String, f64)>,
    pub subtitle: Option<Subtitle>,
    /// A rebind waiting for a key or button: (action, slot).
    pub capturing: Option<(String, usize)>,
    pub last_device: String,
    pub narrator: Narrator,
    pub asked_consent: bool,
    pub automated: bool,
    pub debug_build: bool,
    /// Bumped on every visible change; view.rs rebuilds its tree when it moves.
    pub version: u64,
    /// Bumped when the settings change; sync_settings applies them to the game.
    pub settings_version: u64,
    pub blink_on: bool,
    screen_changed: bool,
    pub quit_requested: bool,
    pub last_saved: Option<PathBuf>,
    /// Where the loading screen goes when it is done: Play, or the juice demo.
    pub loading_next: ScreenName,
    /// The juice demo's state while its screen is on the stack.
    pub juice: Option<juice::Demo>,
    /// F8 was pressed (debug builds): bug_report::capture writes the report next frame.
    pub bug_requested: bool,
    /// The last bug report's folder, once all its files are on disk.
    pub last_bug_report: Option<PathBuf>,
    /// `--drive pseudo-plant`: view.rs draws one label too small for its text on the main menu.
    pub plant: bool,
}

impl Shell {
    pub fn new(cfg: &GameConfig) -> Shell {
        let store = Store::new(cfg.data_dir.clone());
        let (settings, problems) = settings::load_file(&store.settings_path());
        for p in &problems {
            if p != "unreadable" || store.settings_path().exists() {
                warn!("settings: fixed {p}");
            }
        }
        let mut shell = Shell {
            tables: load_tables(&store),
            presets: serde_json::from_str(store::BUILTIN_PRESETS).unwrap_or(Value::Null),
            colours: serde_json::from_str(store::BUILTIN_COLOURS).unwrap_or(Value::Null),
            store,
            settings,
            locale_override: cfg.locale.clone(),
            stack: Vec::new(),
            pending: Vec::new(),
            held: BTreeSet::new(),
            pad: PadAxes::default(),
            game_pressed: Vec::new(),
            repeaters: BTreeMap::new(),
            history: Vec::new(),
            objective: String::new(),
            message: None,
            toasts: Vec::new(),
            subtitle: None,
            capturing: None,
            last_device: "keyboard".into(),
            narrator: Narrator::default(),
            asked_consent: false,
            automated: cfg.automated,
            debug_build: cfg!(debug_assertions),
            version: 0,
            settings_version: 0,
            blink_on: true,
            screen_changed: false,
            quit_requested: false,
            last_saved: None,
            loading_next: ScreenName::Play,
            juice: None,
            bug_requested: false,
            last_bug_report: None,
            plant: false,
        };
        if let Some(text) = shell.store.read_data("input/presets.json")
            && let Ok(v) = serde_json::from_str::<Value>(&text)
        {
            shell.presets = v;
        }
        if let Some(text) = shell.store.read_data("access/colours.json")
            && let Ok(v) = serde_json::from_str::<Value>(&text)
        {
            shell.colours = v;
        }
        shell.push(ScreenName::Boot);
        shell
    }

    // ---- Text ------------------------------------------------------------------------------------------------
    /// The language in use: --locale, else the settings.
    pub fn language(&self) -> String {
        match &self.locale_override {
            Some(l) => l.clone(),
            None => self.settings["language"].as_str().unwrap_or("en").to_string(),
        }
    }

    pub fn is_pseudo(&self) -> bool {
        self.language() == "pseudo"
    }

    pub fn t(&self, key: &str) -> String {
        self.t_args(key, &[])
    }

    pub fn t_args(&self, key: &str, args: &[(&str, &str)]) -> String {
        let lang = self.language();
        if lang == "pseudo" {
            return i18n::pseudo(&i18n::tr(&self.tables, "en", key, args));
        }
        i18n::tr(&self.tables, &lang, key, args)
    }

    /// A value the game made up (a number, a name) through the "value.raw" template, so the pseudo check sees it.
    pub fn tv(&self, value: &str) -> String {
        self.t_args("value.raw", &[("v", value)])
    }

    pub fn has_text(&self, key: &str) -> bool {
        i18n::locale_chain(&self.language())
            .iter()
            .any(|loc| self.tables.get(loc).is_some_and(|t| t.contains_key(key)))
    }

    /// The locales the language setting offers (the pseudo-locale in debug builds).
    pub fn locales(&self) -> Vec<String> {
        let mut out: Vec<String> = self.tables.keys().cloned().collect();
        if self.debug_build {
            out.push("pseudo".into());
        }
        out
    }

    // ---- Settings ----------------------------------------------------------------------------------------------
    pub fn bindings(&self) -> Bindings {
        settings::bindings(&self.settings)
    }

    pub fn set_bindings(&mut self, b: &Bindings) {
        settings::set_bindings(&mut self.settings, b);
        self.changed();
    }

    pub fn num(&self, section: &str, name: &str) -> f64 {
        settings::num(&self.settings, section, name)
    }

    pub fn flag(&self, section: &str, name: &str) -> bool {
        settings::flag(&self.settings, section, name)
    }

    pub fn text(&self, section: &str, name: &str) -> String {
        settings::text(&self.settings, section, name).to_string()
    }

    pub fn set(&mut self, section: &str, name: &str, value: Value) {
        self.settings[section][name] = value;
        self.changed();
    }

    /// After any settings change: the game follows (sync_settings) and the screens redraw.
    pub fn changed(&mut self) {
        self.settings_version += 1;
        self.version += 1;
    }

    /// Writes settings.json (atomic); the path, or None when it failed (a toast says so).
    pub fn save_settings(&mut self) -> Option<PathBuf> {
        let path = self.store.settings_path();
        if let Some(dir) = path.parent()
            && let Err(e) = std::fs::create_dir_all(dir)
        {
            error!("settings: cannot create {}: {e}", dir.display());
        }
        match settings::save_file(&path, &self.settings) {
            Ok(()) => {
                info!("settings: saved {}", path.display());
                self.last_saved = Some(path.clone());
                Some(path)
            }
            Err(e) => {
                error!("settings: not saved: {e}");
                let text = self.t("toast.settings_failed");
                self.toast(text);
                None
            }
        }
    }

    pub fn set_consent(&mut self, value: &str) {
        self.set("telemetry", "consent", json!(value));
        if value != "unset" {
            self.save_settings();
        }
        info!("telemetry: consent {value}");
    }

    /// The one-handed layout `name` from data/input/presets.json (#166) on top of the defaults.
    pub fn apply_preset(&mut self, name: &str) -> bool {
        let Some(chosen) = self.presets["presets"][name]["bindings"].as_object() else {
            return false;
        };
        let mut b = bindings::default_bindings();
        for (action, pair) in chosen {
            let slots: Vec<String> = pair
                .as_array()
                .map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect())
                .unwrap_or_default();
            b.insert(action.clone(), slots);
        }
        self.set_bindings(&b);
        let text = self.t("controls.preset_done");
        self.say_message(text);
        true
    }

    pub fn preset_names(&self) -> Vec<String> {
        self.presets["presets"]
            .as_object()
            .map(|m| m.keys().cloned().collect())
            .unwrap_or_default()
    }

    pub fn reset_bindings(&mut self) {
        self.set_bindings(&bindings::default_bindings());
        let text = self.t("controls.reset_done");
        self.say_message(text);
    }

    /// Finishes a rebind that waits for a key: the binding pressed ("" cancels), with the swap from logic::bindings.
    pub fn capture(&mut self, binding: &str) {
        let Some((action, slot)) = self.capturing.take() else {
            return;
        };
        self.version += 1;
        if binding.is_empty() || binding == "key:escape" {
            return;
        }
        match bindings::rebind(&self.bindings(), &action, slot, binding) {
            Ok((b, conflicts)) => {
                self.set_bindings(&b);
                let text = match conflicts.first() {
                    Some((other, _)) => {
                        let label = self.t(&format!("action.{other}"));
                        self.t_args("controls.swapped", &[("action", &label)])
                    }
                    None => {
                        let label = self.t(&format!("action.{action}"));
                        self.t_args("controls.bound", &[("action", &label)])
                    }
                };
                self.say_message(text);
            }
            Err(e) => warn!("rebind: {e}"),
        }
    }

    pub fn say_message(&mut self, text: String) {
        self.message = Some((text, MESSAGE_S));
        self.version += 1;
    }

    pub fn toast(&mut self, text: String) {
        self.toasts.push((text, TOAST_S));
        self.version += 1;
    }

    // ---- Prompts -----------------------------------------------------------------------------------------------
    pub fn glyph_set(&self) -> String {
        bindings::glyph_set(settings::text(&self.settings, "input", "glyphs"), &self.last_device).to_string()
    }

    /// The label of a binding for the current glyph set: the glyph's own string if the table has one, else the
    /// binding's name ("Space", "A", "Cross").
    pub fn binding_label(&self, gname: &str) -> String {
        let key = format!("glyph.{gname}");
        if self.has_text(&key) {
            return self.t(&key);
        }
        let name = gname.split_once('_').map_or(gname, |(_, rest)| rest).replace('_', " ");
        let mut chars = name.chars();
        let cap = match chars.next() {
            Some(c) => c.to_uppercase().collect::<String>() + chars.as_str(),
            None => String::new(),
        };
        self.tv(&cap)
    }

    /// The prompt for an action right now: (glyph name, text label).
    pub fn prompt(&self, action: &str) -> (String, String) {
        let gset = self.glyph_set();
        let b = self.bindings();
        let binding = bindings::prompt_binding(&b, action, &gset);
        if binding.is_empty() {
            return ("unknown".into(), self.t("controls.unbound"));
        }
        let gname = bindings::glyph_name(&gset, binding);
        let label = self.binding_label(&gname);
        (gname, label)
    }

    // ---- Screens -----------------------------------------------------------------------------------------------
    pub fn top(&self) -> Option<&ScreenState> {
        self.stack.last()
    }

    pub fn top_mut(&mut self) -> Option<&mut ScreenState> {
        self.stack.last_mut()
    }

    pub fn top_name(&self) -> Option<ScreenName> {
        self.stack.last().map(|s| s.name)
    }

    pub fn push(&mut self, name: ScreenName) {
        let mut state = ScreenState::new(name);
        screens::enter(self, &mut state);
        self.stack.push(state);
        info!("shell: screen {}", name.as_str());
        self.screen_changed = true;
        self.version += 1;
    }

    pub fn pop(&mut self) -> Option<ScreenState> {
        let out = self.stack.pop();
        self.screen_changed = true;
        self.version += 1;
        out
    }

    pub fn replace(&mut self, name: ScreenName) {
        self.stack.pop();
        self.push(name);
    }

    pub fn reset(&mut self, name: ScreenName) {
        self.stack.clear();
        self.push(name);
    }

    pub fn find(&self, name: ScreenName) -> Option<&ScreenState> {
        self.stack.iter().rev().find(|s| s.name == name)
    }

    /// The game runs only while Play is on top.
    pub fn game_active(&self) -> bool {
        self.top_name() == Some(ScreenName::Play)
    }

    pub fn rows(&self) -> Vec<Row> {
        screens::rows_for(self)
    }

    /// The focused control's id ("audio.master", "tabs.audio", "quit"), "" when nothing has focus.
    pub fn focus_id(&self) -> String {
        screens::focus_id(self)
    }

    // ---- Input -------------------------------------------------------------------------------------------------
    /// As if a bound key was pressed: the action goes to the top screen next frame (drives and tests).
    pub fn inject(&mut self, action: &str) {
        self.pending.push(vec![action.to_string()]);
    }

    /// A key or button went down: every action it is bound to, tried in sorted order next frame.
    pub fn press_binding(&mut self, binding: &str) {
        let actions = input::actions_for(&self.bindings(), binding);
        if !actions.is_empty() {
            self.pending.push(actions);
        }
    }

    /// Runs one press group now. A held subtitle line takes accept first (on a pad, south is accept and jump: the
    /// line must go before the game jumps). Returns the action used, if any.
    pub fn dispatch(&mut self, actions: &[String]) -> Option<String> {
        if actions.iter().any(|a| a == "ui_accept")
            && let Some(sub) = &self.subtitle
            && sub.holding
        {
            self.subtitle = None;
            self.version += 1;
            return Some("ui_accept".into());
        }
        for action in actions {
            if screens::action(self, action) {
                self.version += 1;
                return Some(action.clone());
            }
            if self.game_active() && !action.starts_with("ui_") {
                self.game_pressed.push(action.clone());
                return Some(action.clone());
            }
        }
        None
    }

    fn process_pending(&mut self) {
        let groups = std::mem::take(&mut self.pending);
        for group in groups {
            self.dispatch(&group);
        }
    }

    // ---- Subtitles, history, the goal (#167) --------------------------------------------------------------------
    /// Shows a line as a subtitle and records it in the dialogue history. A bark shows only with subtitle_barks.
    /// Returns whether it was shown.
    pub fn say(&mut self, speaker: &str, text: &str, bark: bool) -> bool {
        if !self.flag("access", "subtitles") || (bark && !self.flag("access", "subtitle_barks")) {
            return false;
        }
        let words = text.split_whitespace().count() as f64;
        self.subtitle = Some(Subtitle {
            speaker: speaker.to_string(),
            text: text.to_string(),
            remaining: SUBTITLE_MIN_S + words * SUBTITLE_PER_WORD_S,
            holding: false,
        });
        self.history.push((speaker.to_string(), text.to_string()));
        if self.history.len() > MAX_HISTORY {
            self.history.remove(0);
        }
        self.version += 1;
        true
    }

    pub fn subtitle_holding(&self) -> bool {
        self.subtitle.as_ref().is_some_and(|s| s.holding)
    }

    /// The goal "What now?" shows on the pause menu (#167); "" clears it. Pass translated text (shell.t()).
    pub fn set_objective(&mut self, text: &str) {
        self.objective = text.to_string();
        self.version += 1;
    }

    pub fn quit(&mut self) {
        info!("shell: quit");
        self.quit_requested = true;
    }

    /// The loading screen, then `next` (Play or the juice demo).
    pub fn load(&mut self, next: ScreenName) {
        self.loading_next = next;
        self.push(ScreenName::Loading);
    }

    /// The bug-report key (F8): in debug builds the report is written next frame (bug_report.rs).
    pub fn bug_key(&mut self) {
        if self.debug_build {
            self.bug_requested = true;
        }
    }

    // ---- Frame -------------------------------------------------------------------------------------------------
    /// Timers: the boot and loading screens move on, the title blinks, messages and subtitles run out.
    pub fn tick(&mut self, dt: f64) {
        let mut bump = false;
        if let Some(top) = self.stack.last_mut() {
            top.t += dt;
            let (name, t) = (top.name, top.t);
            if (name == ScreenName::Boot || name == ScreenName::Loading) && t >= LOADING_S {
                let next = if name == ScreenName::Boot {
                    ScreenName::Title
                } else {
                    self.loading_next
                };
                self.replace(next);
                match next {
                    ScreenName::Play => screens::start_play(self),
                    ScreenName::Juice => juice::start(self),
                    _ => {}
                }
            }
        }
        let blink = (self.stack.last().map_or(0.0, |s| s.t) % BLINK_S) < BLINK_S * 0.6;
        if blink != self.blink_on {
            self.blink_on = blink;
            bump |= self.top_name() == Some(ScreenName::Title);
        }
        if let Some((_, left)) = &mut self.message {
            *left -= dt;
            if *left <= 0.0 {
                self.message = None;
                bump = true;
            }
        }
        let before = self.toasts.len();
        for toast in &mut self.toasts {
            toast.1 -= dt;
        }
        self.toasts.retain(|t| t.1 > 0.0);
        bump |= self.toasts.len() != before;
        let hold = self.flag("access", "subtitle_hold");
        if let Some(sub) = &mut self.subtitle
            && !sub.holding
        {
            sub.remaining -= dt;
            if sub.remaining <= 0.0 {
                if hold {
                    sub.holding = true;
                } else {
                    self.subtitle = None;
                }
                bump = true;
            }
        }
        if bump {
            self.version += 1;
        }
    }

    /// Held game actions repeat their press with access.auto_repeat (#166).
    fn auto_repeat(&mut self, dt: f64) {
        let on = self.flag("access", "auto_repeat") && self.game_active();
        for action in REPEAT_ACTIONS {
            let held = on && self.held.contains(action);
            let rep = self.repeaters.entry(action.to_string()).or_default();
            if rep.update(dt, held) {
                self.game_pressed.push(action.to_string());
            }
        }
    }

    /// The direction the held move_* actions ask for (unit length at most).
    pub fn held_dir(&self) -> Vec2 {
        let mut dir = Vec2::ZERO;
        for (action, v) in MOVE_ACTIONS {
            if self.held.contains(action) {
                dir += v;
            }
        }
        dir.normalize_or_zero()
    }

    /// The left stick for gameplay: input.deadzone (radial, rescaled) and input.invert_y applied (#265).
    pub fn stick(&self) -> Vec2 {
        let (x, y) = analog::stick(
            self.pad.left.x,
            self.pad.left.y,
            self.num("input", "deadzone") as f32,
            self.flag("input", "invert_y"),
        );
        Vec2::new(x, y)
    }

    /// (left, right) trigger, 0 to 1, past analog::TRIGGER_DEADZONE.
    pub fn triggers(&self) -> (f32, f32) {
        (
            analog::trigger(self.pad.left_trigger, analog::TRIGGER_DEADZONE),
            analog::trigger(self.pad.right_trigger, analog::TRIGGER_DEADZONE),
        )
    }

    /// The move_* actions the stick holds: a raw lean past the deadzone (at least STICK_HOLD_MIN), invert_y honoured.
    pub fn stick_actions(&self) -> Vec<&'static str> {
        let on = (self.num("input", "deadzone") as f32).max(STICK_HOLD_MIN);
        let x = self.pad.left.x;
        let y = if self.flag("input", "invert_y") {
            -self.pad.left.y
        } else {
            self.pad.left.y
        };
        let mut out = Vec::new();
        for (action, lean) in [("move_left", -x), ("move_right", x), ("move_up", y), ("move_down", -y)] {
            if lean > on {
                out.push(action);
            }
        }
        out
    }

    /// The game actions held right now (no ui_*): the bindings' holds plus the stick's move_* holds.
    pub fn held_actions(&self) -> BTreeSet<String> {
        let mut out: BTreeSet<String> = self.held.iter().filter(|a| !a.starts_with("ui_")).cloned().collect();
        out.extend(self.stick_actions().into_iter().map(str::to_string));
        out
    }

    fn narrate(&mut self) {
        let changed = std::mem::take(&mut self.screen_changed);
        let Some(top) = self.top() else {
            return;
        };
        let title_key = match top.name {
            ScreenName::Settings => Some("settings.title"),
            ScreenName::Credits => Some("credits.title"),
            ScreenName::Pause => Some("pause.title"),
            ScreenName::Help => Some("help.title"),
            ScreenName::History => Some("history.title"),
            ScreenName::Juice => Some("juice.title"),
            _ => None,
        };
        let title = title_key.map_or_else(|| top.name.as_str().to_string(), |k| self.t(k));
        let word = self.t("narrate.screen");
        let rows = self.rows();
        let focused = screens::focused_row(self, &rows);
        let role = focused.map(|r| self.t(role_key(r.kind))).unwrap_or_default();
        let row = focused.map(|r| (r.label.as_str(), role.as_str(), r.value.as_str()));
        // The line is always worked out (the access report lists it); it is spoken only with the setting on and
        // never in an automated run (dev.py smoke must not start the system's speech).
        let enabled = self.flag("access", "narration") && !self.automated;
        self.narrator.update(&narrator::Focus {
            screen_title: &title,
            screen_word: &word,
            row,
            screen_changed: changed,
            enabled,
        });
    }

    /// The colour-blind palette for the current setting: name -> colour, from data/access/colours.json.
    pub fn palette(&self) -> BTreeMap<String, Color> {
        let mode = self.text("access", "colorblind");
        let pals = &self.colours["palettes"];
        let chosen = if pals[&mode].is_object() && pals[&mode].as_object().is_some_and(|m| !m.is_empty()) {
            &pals[&mode]
        } else {
            &pals["none"]
        };
        let mut out = BTreeMap::new();
        if let Some(map) = chosen.as_object() {
            for (name, hex) in map {
                if let Some(c) = hex.as_str().and_then(|h| Srgba::hex(h).ok()) {
                    out.insert(name.clone(), Color::Srgba(c));
                }
            }
        }
        out
    }
}

/// The narration word for a row kind ("button", "slider", ...).
pub fn role_key(kind: RowKind) -> &'static str {
    match kind {
        RowKind::Button | RowKind::Binding => "narrate.button",
        RowKind::Toggle => "narrate.toggle",
        RowKind::Slider => "narrate.slider",
        RowKind::Choice => "narrate.choice",
    }
}

/// The string tables: the built-in ones, with data/i18n/*.json on top (a new language needs no code).
fn load_tables(store: &Store) -> Tables {
    let mut tables = Tables::new();
    let mut sources: Vec<(String, String)> = store::BUILTIN_I18N
        .iter()
        .map(|(l, t)| (l.to_string(), t.to_string()))
        .collect();
    sources.extend(store.data_locales());
    for (locale, text) in sources {
        match serde_json::from_str::<Value>(&text) {
            Ok(v) => match i18n::tables_from_value(&json!({ locale.clone(): v })) {
                Ok(t) => tables.extend(t),
                Err(e) => error!("i18n: {locale}: {e}"),
            },
            Err(e) => error!("i18n: {locale}.json is not JSON: {e}"),
        }
    }
    tables
}

// ---- The plugin ------------------------------------------------------------------------------------------------
pub struct ShellPlugin;

impl Plugin for ShellPlugin {
    fn build(&self, app: &mut App) {
        let cfg = app.world().get_resource::<GameConfig>().cloned().unwrap_or_default();
        app.insert_resource(Shell::new(&cfg))
            .init_resource::<display::FrameLimit>()
            .add_systems(
                Update,
                (shell_frame, drive::drive_update, sync_settings, quit_when_asked).chain(),
            )
            .add_systems(Update, (crash::track, bug_report::capture).after(shell_frame))
            .add_systems(Update, display::apply_display.after(sync_settings))
            .add_systems(Last, display::limit_frame_rate)
            .add_systems(
                RunFixedMainLoop,
                write_intent.in_set(RunFixedMainLoopSystems::BeforeFixedMainLoop),
            );
    }
}

/// One shell frame: timers, the pending presses, auto-repeat, the narrator.
fn shell_frame(time: Res<Time>, mut shell: ResMut<Shell>, mut active: ResMut<GameActive>) {
    let dt = time.delta_secs_f64();
    shell.game_pressed.clear();
    shell.tick(dt);
    shell.process_pending();
    juice::frame(&mut shell, dt);
    shell.auto_repeat(dt);
    shell.narrate();
    let now = shell.game_active();
    if active.0 != now {
        active.0 = now;
    }
}

/// The held actions, the stick, the triggers and this frame's presses become the Intent, right before the fixed
/// ticks. Outside Play everything is zero, so a menu never leaks a held trigger into the game.
fn write_intent(shell: Res<Shell>, cfg: Res<GameConfig>, mut intent: ResMut<Intent>) {
    if cfg.autoplay.is_some() {
        // bots win: a stray key or stick cannot disturb a recorded scenario (the bot sets dir itself)
        let dir = intent.dir;
        *intent = Intent {
            dir,
            ..Intent::default()
        };
        return;
    }
    if !shell.game_active() {
        *intent = Intent {
            pressed: shell.game_pressed.clone(),
            ..Intent::default()
        };
        return;
    }
    let stick = shell.stick();
    let (left_trigger, right_trigger) = shell.triggers();
    *intent = Intent {
        dir: (shell.held_dir() + stick).clamp_length_max(1.0),
        pressed: shell.game_pressed.clone(),
        held: shell.held_actions(),
        stick,
        left_trigger,
        right_trigger,
    };
}

/// The game follows the settings: shake, the colour-blind palette, the access rules, the interface scale.
fn sync_settings(
    mut last: Local<Option<u64>>,
    shell: Res<Shell>,
    mut shake: ResMut<ScreenShake>,
    mut palette: ResMut<Palette>,
    mut rules: ResMut<AccessRules>,
    ui_scale: Option<ResMut<bevy::ui::UiScale>>,
) {
    if *last == Some(shell.settings_version) {
        return;
    }
    *last = Some(shell.settings_version);
    shake.intensity = settings::effective_shake(&shell.settings);
    palette.0 = shell.palette();
    *rules = AccessRules {
        game_speed: shell.num("access", "game_speed"),
        timing_scale: shell.num("access", "timing_scale"),
        auto_repeat: shell.flag("access", "auto_repeat"),
        flash_limit: shell.flag("access", "flash_limit"),
        reduce_motion: shell.flag("access", "reduce_motion"),
    };
    if let Some(mut scale) = ui_scale {
        scale.0 = shell.num("display", "ui_scale") as f32;
    }
}

fn quit_when_asked(shell: Res<Shell>, mut exit: MessageWriter<AppExit>) {
    if shell.quit_requested && !shell.automated {
        exit.write(AppExit::Success);
    }
}
