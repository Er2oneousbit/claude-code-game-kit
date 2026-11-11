// ---------------------------------------------------------------------------
// shell/screens.rs
// Purpose : What each screen shows and does: its rows (buttons, toggles, sliders, choices, bindings), its text
//           lines (credits, "What now?", the dialogue history), and how it answers the ui_* actions. The settings
//           screen has one row per field of the settings schema (logic/settings.rs) over five tabs, with rebinding,
//           conflict marks, reset and the one-handed layouts on Controls.
// Usage   : screens::rows_for(&shell) -> Vec<Row>;  screens::action(&mut shell, "ui_down") -> used;
//           screens::lines_for(&shell) for the text pages;  screens::focus_id(&shell)
// Notes   : Rows are rebuilt from the settings whenever asked (cheap: a few dozen), so nothing caches a stale
//           value. A Row owns its strings and its closures capture only owned data, so a row can run against the
//           shell that built it. Focus starts on the settings tab bar: left/right switch tabs, down enters the rows,
//           up from the first row returns to the tabs. Back (or cancel) saves settings.json.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): "Juice demo" on the main menu of debug builds, the
//           demo's actions (juice.rs), the text pages say which lines are raw (credits names, #275)
// ---------------------------------------------------------------------------
use serde_json::json;

use super::{ScreenName, ScreenState, Shell};
use crate::logic::bindings;
use crate::logic::settings;

// ---- Tunables ------------------------------------------------------------------
pub const TABS: [&str; 5] = ["display", "audio", "controls", "access", "language"];
/// The actions the Controls tab lists (ui_* actions are not rebindable here, see logic/bindings.rs).
pub const GAME_ACTIONS: [&str; 8] = [
    "move_left",
    "move_right",
    "move_up",
    "move_down",
    "jump",
    "attack",
    "interact",
    "pause",
];
/// The controls "What now?" lists (#167).
pub const HELP_ACTIONS: [&str; 6] = ["move_left", "move_right", "jump", "attack", "interact", "pause"];
const RESOLUTIONS: [(i64, i64); 5] = [(1280, 720), (1600, 900), (1920, 1080), (2560, 1440), (3840, 2160)];
/// Lines a text page shows at once.
pub const PAGE_LINES: usize = 10;

pub type Act = Box<dyn Fn(&mut Shell)>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RowKind {
    Button,
    Toggle,
    Slider,
    Choice,
    Binding,
}

pub struct Row {
    pub id: String,
    pub kind: RowKind,
    pub label: String,
    /// The value shown and narrated ("80%", "On", "Xbox"); "" for buttons.
    pub value: String,
    /// Slider position 0..1 for the bar.
    pub fraction: Option<f32>,
    /// Binding rows: the keyboard and pad cells (glyph name, label) and whether each clashes.
    pub cells: [(String, String); 2],
    pub conflict: [bool; 2],
    pub on_accept: Option<Act>,
    pub on_left: Option<Act>,
    pub on_right: Option<Act>,
}

impl Row {
    fn new(id: &str, kind: RowKind, label: String) -> Row {
        Row {
            id: id.to_string(),
            kind,
            label,
            value: String::new(),
            fraction: None,
            cells: [(String::new(), String::new()), (String::new(), String::new())],
            conflict: [false, false],
            on_accept: None,
            on_left: None,
            on_right: None,
        }
    }
}

fn button(id: &str, label: String, act: impl Fn(&mut Shell) + 'static) -> Row {
    let mut row = Row::new(id, RowKind::Button, label);
    row.on_accept = Some(Box::new(act));
    row
}

// ---- Settings rows ---------------------------------------------------------------------------------------------
fn percent(shell: &Shell, v: f64) -> String {
    shell.t_args(
        "value.percent",
        &[("n", &format!("{}", (v * 100.0 + 0.5).floor() as i64))],
    )
}

fn times(shell: &Shell, v: f64) -> String {
    let text = if v.fract() == 0.0 {
        format!("{}", v as i64)
    } else {
        format!("{v}")
    };
    shell.t_args("value.times", &[("n", &text)])
}

fn toggle(shell: &Shell, section: &'static str, name: &'static str) -> Row {
    let mut row = Row::new(name, RowKind::Toggle, shell.t(&format!("settings.{section}.{name}")));
    let on = shell.flag(section, name);
    row.value = shell.t(if on { "value.on" } else { "value.off" });
    let flip: Act = Box::new(move |s: &mut Shell| {
        let now = s.flag(section, name);
        s.set(section, name, json!(!now));
    });
    row.on_accept = Some(flip);
    row.on_left = Some(Box::new(move |s: &mut Shell| s.set(section, name, json!(false))));
    row.on_right = Some(Box::new(move |s: &mut Shell| s.set(section, name, json!(true))));
    row
}

fn slider(shell: &Shell, section: &'static str, name: &'static str, lo: f64, hi: f64, step: f64) -> Row {
    let mut row = Row::new(name, RowKind::Slider, shell.t(&format!("settings.{section}.{name}")));
    let v = shell.num(section, name);
    row.value = if section == "display" || name == "text_scale" || name == "line_spacing" || name == "timing_scale" {
        times(shell, v)
    } else {
        percent(shell, v)
    };
    row.fraction = Some(((v - lo) / (hi - lo)) as f32);
    let nudge = move |s: &mut Shell, dir: f64| {
        let now = s.num(section, name);
        // round to the step so 0.1 + 0.1 + 0.1 stays 0.3, as the other engines' sliders do
        let next = (((now + dir * step) / step).round() * step).clamp(lo, hi);
        let next = (next * 1e6).round() / 1e6;
        s.set(section, name, json!(next));
    };
    row.on_left = Some(Box::new(move |s: &mut Shell| nudge(s, -1.0)));
    row.on_right = Some(Box::new(move |s: &mut Shell| nudge(s, 1.0)));
    row
}

fn choice(shell: &Shell, section: &'static str, name: &'static str, options: &'static [&'static str]) -> Row {
    let mut row = Row::new(name, RowKind::Choice, shell.t(&format!("settings.{section}.{name}")));
    let now = shell.text(section, name);
    row.value = shell.t(&format!("opt.{name}.{now}"));
    let turn = move |s: &mut Shell, dir: i64| {
        let now = s.text(section, name);
        let idx = options.iter().position(|o| *o == now).unwrap_or(0) as i64;
        let next = (idx + dir).rem_euclid(options.len() as i64) as usize;
        s.set(section, name, json!(options[next]));
    };
    row.on_left = Some(Box::new(move |s: &mut Shell| turn(s, -1)));
    row.on_right = Some(Box::new(move |s: &mut Shell| turn(s, 1)));
    row.on_accept = Some(Box::new(move |s: &mut Shell| turn(s, 1)));
    row
}

fn back_row(shell: &Shell) -> Row {
    button("back", shell.t("settings.back"), close_settings)
}

fn close_settings(shell: &mut Shell) {
    shell.save_settings();
    shell.pop();
}

fn display_rows(shell: &Shell) -> Vec<Row> {
    let mut rows = vec![
        choice(shell, "display", "mode", settings::DISPLAY_MODES),
        toggle(shell, "display", "vsync"),
    ];
    // frame cap: a choice over numbers
    let mut cap = Row::new("frame_cap", RowKind::Choice, shell.t("settings.display.frame_cap"));
    let now = shell.num("display", "frame_cap") as i64;
    cap.value = if now == 0 {
        shell.t("opt.frame_cap.0")
    } else {
        shell.t_args("value.fps", &[("n", &now.to_string())])
    };
    let turn_cap = move |s: &mut Shell, dir: i64| {
        let now = s.num("display", "frame_cap") as i64;
        let idx = settings::FRAME_CAPS.iter().position(|c| *c == now).unwrap_or(0) as i64;
        let next = (idx + dir).rem_euclid(settings::FRAME_CAPS.len() as i64) as usize;
        s.set("display", "frame_cap", json!(settings::FRAME_CAPS[next]));
    };
    cap.on_left = Some(Box::new(move |s| turn_cap(s, -1)));
    cap.on_right = Some(Box::new(move |s| turn_cap(s, 1)));
    cap.on_accept = Some(Box::new(move |s| turn_cap(s, 1)));
    rows.push(cap);
    // resolution: a choice over the common sizes
    let mut res = Row::new("resolution", RowKind::Choice, shell.t("settings.display.resolution"));
    let (w, h) = current_resolution(shell);
    res.value = shell.t_args("value.resolution", &[("w", &w.to_string()), ("h", &h.to_string())]);
    let turn_res = move |s: &mut Shell, dir: i64| {
        let now = current_resolution(s);
        let idx = RESOLUTIONS.iter().position(|r| *r == now).unwrap_or(0) as i64;
        let next = RESOLUTIONS[(idx + dir).rem_euclid(RESOLUTIONS.len() as i64) as usize];
        s.set("display", "resolution", json!([next.0, next.1]));
    };
    res.on_left = Some(Box::new(move |s| turn_res(s, -1)));
    res.on_right = Some(Box::new(move |s| turn_res(s, 1)));
    res.on_accept = Some(Box::new(move |s| turn_res(s, 1)));
    rows.push(res);
    rows.push(slider(shell, "display", "ui_scale", 0.75, 2.0, 0.25));
    rows.push(back_row(shell));
    rows
}

fn current_resolution(shell: &Shell) -> (i64, i64) {
    let r = &shell.settings["display"]["resolution"];
    (
        r[0].as_f64().unwrap_or(1920.0) as i64,
        r[1].as_f64().unwrap_or(1080.0) as i64,
    )
}

fn audio_rows(shell: &Shell) -> Vec<Row> {
    let mut rows: Vec<Row> = ["master", "music", "sfx", "ui", "voice"]
        .into_iter()
        .map(|bus| slider(shell, "audio", bus, 0.0, 1.0, 0.1))
        .collect();
    rows.push(toggle(shell, "audio", "mono"));
    rows.push(back_row(shell));
    rows
}

/// The glyph set for the pad column (the keyboard set makes no sense there).
fn pad_set(shell: &Shell) -> String {
    let gset = shell.glyph_set();
    if gset == "keyboard" { "generic".into() } else { gset }
}

fn binding_row(shell: &Shell, action: &'static str, cell: usize) -> Row {
    let mut row = Row::new(
        &format!("bind_{action}"),
        RowKind::Binding,
        shell.t(&format!("action.{action}")),
    );
    let all = shell.bindings();
    let list = all.get(action).cloned().unwrap_or_default();
    let pads = pad_set(shell);
    for slot in 0..2 {
        let binding = list.get(slot).map_or("", String::as_str);
        let gset = if slot == 0 { "keyboard" } else { pads.as_str() };
        let (gname, label) = if binding.is_empty() {
            ("unknown".to_string(), shell.t("controls.unbound"))
        } else {
            let g = bindings::glyph_name(gset, binding);
            let l = shell.binding_label(&g);
            (g, l)
        };
        row.cells[slot] = (gname, label);
        // a clash: another action of the same group holds the same binding
        row.conflict[slot] = !binding.is_empty()
            && all.iter().any(|(other, slots)| {
                other.as_str() != action
                    && bindings::group_of(other) == bindings::group_of(action)
                    && slots.iter().any(|b| b == binding)
            });
    }
    row.value = format!("{}, {}", row.cells[0].1, row.cells[1].1);
    row.on_left = Some(Box::new(|s| {
        if let Some(top) = s.top_mut() {
            top.cell = 0;
        }
    }));
    row.on_right = Some(Box::new(|s| {
        if let Some(top) = s.top_mut() {
            top.cell = 1;
        }
    }));
    row.on_accept = Some(Box::new(move |s| {
        s.capturing = Some((action.to_string(), cell));
    }));
    row
}

fn controls_rows(shell: &Shell) -> Vec<Row> {
    let cell = shell.top().map_or(0, |t| t.cell);
    let mut rows: Vec<Row> = GAME_ACTIONS.into_iter().map(|a| binding_row(shell, a, cell)).collect();
    rows.push(choice(shell, "input", "glyphs", &bindings::GLYPH_SETS));
    rows.push(slider(shell, "input", "deadzone", 0.0, 0.9, 0.05));
    rows.push(toggle(shell, "input", "invert_y"));
    rows.push(button("reset", shell.t("controls.reset"), |s| s.reset_bindings()));
    // the one-handed layouts (#166, motor access), from data/input/presets.json
    for name in shell.preset_names() {
        let label = shell.t(&format!("controls.preset.{name}"));
        let id = format!("preset_{name}");
        let chosen = name.clone();
        rows.push(button(&id, label, move |s| {
            s.apply_preset(&chosen);
        }));
    }
    rows.push(back_row(shell));
    rows
}

fn access_rows(shell: &Shell) -> Vec<Row> {
    vec![
        slider(shell, "access", "text_scale", 0.75, 2.0, 0.25),
        toggle(shell, "access", "subtitles"),
        choice(shell, "access", "subtitle_size", settings::SUB_SIZES),
        slider(shell, "access", "subtitle_background", 0.0, 1.0, 0.1),
        toggle(shell, "access", "speaker_names"),
        toggle(shell, "access", "subtitle_barks"),
        toggle(shell, "access", "captions_sfx"),
        choice(shell, "access", "colorblind", settings::COLORBLIND),
        toggle(shell, "access", "reduce_motion"),
        slider(shell, "access", "shake_scale", 0.0, 1.0, 0.25),
        toggle(shell, "access", "flash_limit"),
        toggle(shell, "access", "hold_to_toggle"),
        choice(shell, "access", "difficulty", settings::DIFFICULTIES),
        slider(shell, "access", "game_speed", 0.5, 1.0, 0.1),
        toggle(shell, "access", "readable_font"), // #167: cognitive access
        slider(shell, "access", "line_spacing", 1.0, 2.0, 0.25),
        toggle(shell, "access", "subtitle_hold"),
        slider(shell, "access", "timing_scale", 1.0, 3.0, 0.5), // #166: motor access
        toggle(shell, "access", "auto_repeat"),
        toggle(shell, "access", "narration"), // #165: menu narration
        back_row(shell),
    ]
}

fn language_rows(shell: &Shell) -> Vec<Row> {
    let mut lang = Row::new("language", RowKind::Choice, shell.t("settings.language.language"));
    let now = shell.language();
    lang.value = match shell.tables.get(&now).and_then(|t| t.get("language.name")) {
        Some(name) => shell.tv(name),
        None if now == "pseudo" => shell.tv("Pseudo"),
        None => shell.tv(&now),
    };
    let turn = move |s: &mut Shell, dir: i64| {
        let list = s.locales();
        if list.is_empty() {
            return;
        }
        let now = s.language();
        let idx = list.iter().position(|l| *l == now).unwrap_or(0) as i64;
        let next = list[(idx + dir).rem_euclid(list.len() as i64) as usize].clone();
        s.locale_override = None; // the player's choice beats --locale from here on
        s.settings["language"] = json!(next);
        s.changed();
    };
    lang.on_left = Some(Box::new(move |s| turn(s, -1)));
    lang.on_right = Some(Box::new(move |s| turn(s, 1)));
    lang.on_accept = Some(Box::new(move |s| turn(s, 1)));
    vec![
        lang,
        choice(shell, "telemetry", "consent", settings::CONSENT),
        back_row(shell),
    ]
}

fn settings_rows(shell: &Shell, tab: usize) -> Vec<Row> {
    match TABS[tab.min(TABS.len() - 1)] {
        "display" => display_rows(shell),
        "audio" => audio_rows(shell),
        "controls" => controls_rows(shell),
        "access" => access_rows(shell),
        _ => language_rows(shell),
    }
}

// ---- The screens -----------------------------------------------------------------------------------------------
/// The rows of the screen on top (an empty list for screens without a menu).
pub fn rows_for(shell: &Shell) -> Vec<Row> {
    let Some(top) = shell.top() else {
        return Vec::new();
    };
    match top.name {
        ScreenName::Title if top.consent => vec![
            button("consent.yes", shell.t("consent.yes"), |s| answer_consent(s, "yes")),
            button("consent.no", shell.t("consent.no"), |s| answer_consent(s, "no")),
            button("consent.later", shell.t("consent.later"), |s| {
                answer_consent(s, "unset")
            }),
        ],
        ScreenName::MainMenu => {
            let mut rows = vec![
                button("play", shell.t("menu.play"), |s| s.load(ScreenName::Play)),
                button("settings", shell.t("menu.settings"), |s| s.push(ScreenName::Settings)),
                button("credits", shell.t("menu.credits"), |s| s.push(ScreenName::Credits)),
            ];
            if shell.debug_build {
                // the juice demo (juice.rs): debug builds only, like the pseudo-locale and the bug report key
                rows.push(button("juice", shell.t("menu.juice"), |s| s.load(ScreenName::Juice)));
            }
            rows.push(button("quit", shell.t("menu.quit"), |s| s.quit()));
            rows
        }
        ScreenName::Settings => settings_rows(shell, top.tab),
        ScreenName::Pause => vec![
            button("resume", shell.t("pause.resume"), |s| {
                s.pop();
            }),
            button("help", shell.t("pause.help"), |s| s.push(ScreenName::Help)), // #167
            button("history", shell.t("pause.history"), |s| s.push(ScreenName::History)),
            button("settings", shell.t("menu.settings"), |s| s.push(ScreenName::Settings)),
            button("quit", shell.t("pause.quit"), |s| s.reset(ScreenName::Title)),
        ],
        _ => Vec::new(),
    }
}

fn answer_consent(shell: &mut Shell, value: &str) {
    shell.set_consent(value);
    shell.asked_consent = true;
    if let Some(top) = shell.top_mut() {
        top.consent = false;
        top.focus = 0;
    }
}

/// The lines of a text page (credits, "What now?", the dialogue history); empty for other screens.
pub fn lines_for(shell: &Shell) -> Vec<String> {
    page_lines(shell).into_iter().map(|(line, _)| line).collect()
}

/// The lines of a text page with whether each is raw: names from CREDITS.md are shown as written, so the pseudo
/// drive does not expect them in brackets.
pub fn page_lines(shell: &Shell) -> Vec<(String, bool)> {
    match shell.top_name() {
        Some(ScreenName::Credits) => {
            let text = shell
                .store
                .project_data
                .as_ref()
                .and_then(|d| d.parent().map(|p| p.join("CREDITS.md")))
                .and_then(|p| std::fs::read_to_string(p).ok());
            let lines_from_file = text.map(|t| credits_lines(&t)).unwrap_or_default();
            let mut lines: Vec<(String, bool)> = if lines_from_file.is_empty() {
                vec![(shell.t("credits.placeholder"), false)]
            } else {
                lines_from_file.into_iter().map(|l| (l, true)).collect()
            };
            lines.push((String::new(), false));
            lines.push((shell.t("credits.engine"), false));
            lines
        }
        Some(ScreenName::Help) => {
            let mut lines = vec![if shell.objective.is_empty() {
                shell.t("help.no_objective")
            } else {
                shell.t_args("help.objective", &[("text", &shell.objective)])
            }];
            if let Some((name, text)) = shell.history.last() {
                lines.push(shell.t_args("help.last_line", &[("name", name), ("text", text)]));
            }
            lines.push(shell.t("help.controls"));
            for action in HELP_ACTIONS {
                let (_, label) = shell.prompt(action);
                lines.push(format!("{}: {label}", shell.t(&format!("action.{action}"))));
            }
            lines.into_iter().map(|l| (l, false)).collect()
        }
        Some(ScreenName::History) => {
            let lines: Vec<String> = shell
                .history
                .iter()
                .map(|(name, text)| shell.t_args("help.last_line", &[("name", name), ("text", text)]))
                .collect();
            let lines = if lines.is_empty() {
                vec![shell.t("history.empty")]
            } else {
                lines
            };
            lines.into_iter().map(|l| (l, false)).collect()
        }
        _ => Vec::new(),
    }
}

const COMMENT_OPEN: &str = "<!--";
const COMMENT_CLOSE: &str = "-->";

/// Only spaces and tabs (every port counts these two; Unicode whitespace differs between languages).
fn blank(line: &str) -> bool {
    line.chars().all(|c| c == ' ' || c == '\t')
}

/// CREDITS.md without its HTML comments (tools/credits.py writes one, #279): one line or many, an unclosed one runs
/// to the end; a line that held only comments goes, with one blank line after it when a blank line (or the top of the
/// file) came before. CRLF becomes LF. tools/golden_vectors.py strip_html_comments is the spec, data/golden/credits.json
/// the cases (tests/golden.rs).
pub fn strip_html_comments(text: &str) -> String {
    let unix = text.replace("\r\n", "\n");
    let mut out: Vec<String> = Vec::new();
    let mut in_comment = false;
    let mut skip_blank = false; // the blank line after a dropped comment-only line
    for line in unix.split('\n') {
        let mut kept = String::new();
        let mut had = in_comment;
        let mut i = 0;
        loop {
            if in_comment {
                match line[i..].find(COMMENT_CLOSE) {
                    Some(end) => {
                        in_comment = false;
                        i += end + COMMENT_CLOSE.len();
                    }
                    None => break, // the comment goes on into the next line
                }
            } else {
                match line[i..].find(COMMENT_OPEN) {
                    Some(start) => {
                        kept.push_str(&line[i..i + start]);
                        in_comment = true;
                        had = true;
                        i += start + COMMENT_OPEN.len();
                    }
                    None => {
                        kept.push_str(&line[i..]);
                        break;
                    }
                }
            }
        }
        if had && blank(&kept) {
            skip_blank = out.last().is_none_or(|l| blank(l));
            continue;
        }
        if skip_blank && blank(&kept) {
            skip_blank = false;
            continue;
        }
        skip_blank = false;
        out.push(kept);
    }
    out.join("\n")
}

/// CREDITS.md as the credits page's lines: HTML comments out, heading marks off. Empty (the placeholder) when nothing
/// is left.
pub fn credits_lines(markdown: &str) -> Vec<String> {
    let text = strip_html_comments(markdown);
    if text.trim().is_empty() {
        return Vec::new();
    }
    text.lines()
        .map(|l| l.trim_start_matches('#').trim().to_string())
        .collect()
}

/// What a screen does when it opens.
pub fn enter(shell: &mut Shell, state: &mut ScreenState) {
    match state.name {
        ScreenName::Title => {
            state.consent = shell.text("telemetry", "consent") == "unset" && !shell.asked_consent;
        }
        ScreenName::History => state.scroll = usize::MAX, // the page clamps it: open at the newest line
        _ => {}
    }
}

/// The prototype's first moment in play: the goal for "What now?" and a line for the history (#167).
pub fn start_play(shell: &mut Shell) {
    let goal = shell.t("juice.objective");
    shell.set_objective(&goal);
    let text = shell.t("play.welcome");
    let speaker = shell.t("play.guide");
    shell.say(&speaker, &text, false);
}

/// The focused row of `rows`, if the screen has one.
pub fn focused_row<'a>(shell: &Shell, rows: &'a [Row]) -> Option<&'a Row> {
    let top = shell.top()?;
    if top.name == ScreenName::Settings && top.on_tabs {
        return None;
    }
    rows.get(top.focus)
}

/// The focused control's id: "quit", "audio.master", "tabs.audio", or "" when nothing has focus.
pub fn focus_id(shell: &Shell) -> String {
    let Some(top) = shell.top() else {
        return String::new();
    };
    if top.name == ScreenName::Settings {
        let tab = TABS[top.tab.min(TABS.len() - 1)];
        if top.on_tabs {
            return format!("tabs.{tab}");
        }
        return match rows_for(shell).get(top.focus) {
            Some(row) => format!("{tab}.{}", row.id),
            None => String::new(),
        };
    }
    rows_for(shell).get(top.focus).map(|r| r.id.clone()).unwrap_or_default()
}

/// Moves focus over a list of `len` rows, wrapping.
fn move_focus(shell: &mut Shell, len: usize, delta: i64) {
    if len == 0 {
        return;
    }
    if let Some(top) = shell.top_mut() {
        top.focus = ((top.focus as i64 + delta).rem_euclid(len as i64)) as usize;
    }
}

/// The list navigation every menu shares: up/down move, left/right and accept run the row's closures.
fn list_action(shell: &mut Shell, action: &str) -> bool {
    let rows = rows_for(shell);
    if rows.is_empty() {
        return false;
    }
    let focus = shell.top().map_or(0, |t| t.focus).min(rows.len() - 1);
    match action {
        "ui_up" => {
            move_focus(shell, rows.len(), -1);
            true
        }
        "ui_down" => {
            move_focus(shell, rows.len(), 1);
            true
        }
        "ui_left" | "ui_right" | "ui_accept" => {
            let row = &rows[focus];
            let act = match action {
                "ui_left" => row.on_left.as_ref(),
                "ui_right" => row.on_right.as_ref(),
                _ => row.on_accept.as_ref(),
            };
            match act {
                Some(f) => {
                    f(shell);
                    true
                }
                None => false,
            }
        }
        _ => false,
    }
}

fn settings_action(shell: &mut Shell, action: &str) -> bool {
    if shell.capturing.is_some() {
        return true; // the "press a key" prompt swallows actions; the view's capture ends it
    }
    if action == "ui_cancel" {
        close_settings(shell);
        return true;
    }
    let on_tabs = shell.top().is_some_and(|t| t.on_tabs);
    if on_tabs {
        match action {
            "ui_left" | "ui_right" => {
                let delta = if action == "ui_left" { -1 } else { 1 };
                if let Some(top) = shell.top_mut() {
                    top.tab = ((top.tab as i64 + delta).rem_euclid(TABS.len() as i64)) as usize;
                    top.focus = 0;
                }
                true
            }
            "ui_down" | "ui_accept" => {
                if let Some(top) = shell.top_mut() {
                    top.on_tabs = false;
                    top.focus = 0;
                }
                true
            }
            "ui_up" => true,
            _ => false,
        }
    } else {
        if action == "ui_up" && shell.top().is_some_and(|t| t.focus == 0) {
            if let Some(top) = shell.top_mut() {
                top.on_tabs = true;
            }
            return true;
        }
        list_action(shell, action)
    }
}

/// Text pages: up and down scroll, accept or cancel leave.
fn page_action(shell: &mut Shell, action: &str) -> bool {
    let count = lines_for(shell).len();
    let max_scroll = count.saturating_sub(PAGE_LINES);
    match action {
        "ui_up" => {
            if let Some(top) = shell.top_mut() {
                top.scroll = top.scroll.min(max_scroll).saturating_sub(1);
            }
            true
        }
        "ui_down" => {
            if let Some(top) = shell.top_mut() {
                top.scroll = (top.scroll.saturating_add(1)).min(max_scroll);
            }
            true
        }
        "ui_accept" | "ui_cancel" => {
            shell.pop();
            true
        }
        _ => false,
    }
}

/// The top screen's answer to one action: true when it used it.
pub fn action(shell: &mut Shell, action: &str) -> bool {
    let Some(top) = shell.top() else {
        return false;
    };
    match top.name {
        ScreenName::Boot | ScreenName::Loading => false,
        ScreenName::Title => {
            if top.consent {
                if action == "ui_cancel" {
                    answer_consent(shell, "unset");
                    return true;
                }
                return list_action(shell, action);
            }
            // press any key or button
            shell.push(ScreenName::MainMenu);
            true
        }
        ScreenName::MainMenu => list_action(shell, action),
        ScreenName::Settings => settings_action(shell, action),
        ScreenName::Credits | ScreenName::Help | ScreenName::History => page_action(shell, action),
        ScreenName::Play => {
            if action == "pause" {
                shell.push(ScreenName::Pause);
                return true;
            }
            false
        }
        ScreenName::Juice => super::juice::action(shell, action),
        ScreenName::Pause => {
            if action == "pause" || action == "ui_cancel" {
                shell.pop();
                return true;
            }
            list_action(shell, action)
        }
    }
}

// {{FOOTER}}
