// ---------------------------------------------------------------------------
// logic/settings.rs
// Purpose : The player's settings (display, audio, language, accessibility, input, telemetry consent): built-in
//           defaults, a validating load that repairs a damaged or hand-edited file, and an atomic save.
// Usage   : let (s, problems) = settings::load_file(&path);          // never fails: bad fields fall back
//           settings::num(&s, "audio", "music");  settings::flag(&s, "access", "reduce_motion");
//           settings::effective_shake(&s);  settings::telemetry_allowed(&s);  settings::save_file(&path, &s)?;
// Notes   : Settings stay a JSON object (serde_json::Value) so unknown keys survive: a file written by a newer
//           build loads in an older one without losing anything. Missing fields take the default, each fixed
//           field is one problem (log them, do not nag the player). SCHEMA below is the one list of fields and
//           their rules; add a field there and in defaults(). Tested in tests/golden.rs against
//           data/golden/shell.json (tools/golden_vectors.py is the reference).
//
// Pseudocode:
//   load(text): not JSON -> defaults + "unreadable"; not an object -> defaults + "not an object"
//   keep every key -> version = 1 -> language (2 to 12 chars, else "en") -> for each section in SCHEMA:
//   not an object -> problem, use {}; keep its keys; each field: missing -> default, present -> fix by rule
//   (num: clamp, NaN or wrong type -> default; bool; enum; resolution) -> input.bindings: strings only
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::io;
use std::path::Path;

use serde_json::{Map, Value, json};

use super::atomic_file;
use super::bindings::{self, Bindings};

// ---- Choices -------------------------------------------------------------------
pub const VERSION: i64 = 1;
pub const DEFAULT_LANGUAGE: &str = "en";
pub const DIFFICULTIES: &[&str] = &["story", "easy", "normal", "hard"];
pub const COLORBLIND: &[&str] = &["none", "protanopia", "deuteranopia", "tritanopia"];
pub const SUB_SIZES: &[&str] = &["small", "medium", "large", "xl"];
pub const DISPLAY_MODES: &[&str] = &["windowed", "fullscreen", "borderless"];
/// 0 = no cap.
pub const FRAME_CAPS: &[i64] = &[0, 30, 60, 120, 144, 240];
pub const CONSENT: &[&str] = &["unset", "yes", "no"];

/// How one field is validated.
#[derive(Debug, Clone, Copy)]
enum Rule {
    /// A number, clamped to lo..hi.
    Num(f64, f64),
    Bool,
    /// One of these strings.
    Text(&'static [&'static str]),
    /// One of these whole numbers.
    Whole(&'static [i64]),
    /// [width, height], whole numbers >= 1.
    Resolution,
}

/// Every validated field, by section. Fields not listed (and whole sections not listed) are kept as they are.
const SCHEMA: &[(&str, &[(&str, Rule)])] = &[
    (
        "display",
        &[
            ("mode", Rule::Text(DISPLAY_MODES)),
            ("vsync", Rule::Bool),
            ("frame_cap", Rule::Whole(FRAME_CAPS)),
            ("resolution", Rule::Resolution),
            ("ui_scale", Rule::Num(0.75, 2.0)),
        ],
    ),
    (
        "audio",
        &[
            ("master", Rule::Num(0.0, 1.0)),
            ("music", Rule::Num(0.0, 1.0)),
            ("sfx", Rule::Num(0.0, 1.0)),
            ("ui", Rule::Num(0.0, 1.0)),
            ("voice", Rule::Num(0.0, 1.0)),
            ("mono", Rule::Bool),
        ],
    ),
    (
        "access",
        &[
            ("text_scale", Rule::Num(0.75, 2.0)),
            ("subtitles", Rule::Bool),
            ("subtitle_size", Rule::Text(SUB_SIZES)),
            ("subtitle_background", Rule::Num(0.0, 1.0)),
            ("speaker_names", Rule::Bool),
            ("subtitle_barks", Rule::Bool),
            ("captions_sfx", Rule::Bool),
            ("colorblind", Rule::Text(COLORBLIND)),
            ("reduce_motion", Rule::Bool),
            ("shake_scale", Rule::Num(0.0, 1.0)),
            ("flash_limit", Rule::Bool),
            ("hold_to_toggle", Rule::Bool),
            ("difficulty", Rule::Text(DIFFICULTIES)),
            ("game_speed", Rule::Num(0.5, 1.0)),
            ("readable_font", Rule::Bool),
            ("line_spacing", Rule::Num(1.0, 2.0)),
            ("subtitle_hold", Rule::Bool),
            ("timing_scale", Rule::Num(1.0, 3.0)),
            ("auto_repeat", Rule::Bool),
        ],
    ),
    (
        "input",
        &[
            ("deadzone", Rule::Num(0.0, 0.9)),
            ("invert_y", Rule::Bool),
            ("glyphs", Rule::Text(&bindings::GLYPH_SETS)),
        ],
    ),
    ("telemetry", &[("consent", Rule::Text(CONSENT))]),
];

/// The built-in settings: what a first start (or a missing file) uses.
pub fn defaults() -> Value {
    json!({
        "version": VERSION,
        "display": {"mode": "windowed", "vsync": true, "frame_cap": 0, "resolution": [1920, 1080], "ui_scale": 1.0},
        "audio": {"master": 1.0, "music": 0.8, "sfx": 1.0, "ui": 1.0, "voice": 1.0, "mono": false},
        "language": DEFAULT_LANGUAGE,
        "access": {"text_scale": 1.0, "subtitles": true, "subtitle_size": "medium", "subtitle_background": 0.6,
                   "speaker_names": true, "subtitle_barks": false, "captions_sfx": false, "colorblind": "none",
                   "reduce_motion": false, "shake_scale": 1.0, "flash_limit": true, "hold_to_toggle": false,
                   "difficulty": "normal", "game_speed": 1.0, "readable_font": false, "line_spacing": 1.0,
                   "subtitle_hold": false, "timing_scale": 1.0, "auto_repeat": false},
        "input": {"bindings": bindings_value(&bindings::default_bindings()), "deadzone": 0.2, "invert_y": false,
                  "glyphs": "auto"},
        "telemetry": {"consent": "unset"},
    })
}

/// (fixed value, was it a problem?) for one present field.
fn fix(rule: Rule, value: &Value, default: &Value) -> (Value, bool) {
    match rule {
        Rule::Bool if value.is_boolean() => (value.clone(), false),
        Rule::Num(lo, hi) => match value.as_f64() {
            Some(n) if !n.is_nan() => {
                let clamped = n.clamp(lo, hi);
                (json!(clamped), clamped != n)
            }
            _ => (default.clone(), true),
        },
        Rule::Text(allowed) => match value.as_str() {
            Some(s) if allowed.contains(&s) => (value.clone(), false),
            _ => (default.clone(), true),
        },
        Rule::Whole(allowed) => match value.as_f64() {
            Some(n) => match allowed.iter().find(|a| **a as f64 == n) {
                Some(a) => (json!(a), false),
                None => (default.clone(), true),
            },
            None => (default.clone(), true),
        },
        Rule::Resolution => {
            let whole = |v: &Value| v.as_f64().filter(|n| *n >= 1.0 && n.fract() == 0.0);
            match value
                .as_array()
                .map(|a| a.iter().map(whole).collect::<Vec<_>>())
                .as_deref()
            {
                Some([Some(w), Some(h)]) => (json!([*w as i64, *h as i64]), false),
                _ => (default.clone(), true),
            }
        }
        Rule::Bool => (default.clone(), true),
    }
}

/// input.bindings from the file: the defaults, with each valid action list from the file on top (strings only).
fn fix_bindings(value: &Value, problems: &mut Vec<String>) -> Value {
    let mut out = bindings::default_bindings();
    let Some(map) = value.as_object() else {
        problems.push("input.bindings".into());
        return bindings_value(&out);
    };
    for (action, list) in map {
        let Some(list) = list.as_array() else {
            problems.push(format!("input.bindings.{action}"));
            continue;
        };
        let clean: Vec<String> = list.iter().filter_map(|b| b.as_str().map(str::to_string)).collect();
        if clean.len() != list.len() {
            problems.push(format!("input.bindings.{action}"));
        }
        out.insert(action.clone(), clean);
    }
    bindings_value(&out)
}

/// Settings from the file's text (None = no file): (settings, problems). Never fails.
pub fn load(text: Option<&str>) -> (Value, Vec<String>) {
    let raw = match text {
        None => Value::Object(Map::new()),
        Some(t) => match serde_json::from_str::<Value>(t) {
            Ok(v) => v,
            Err(_) => return (defaults(), vec!["unreadable".into()]),
        },
    };
    let Value::Object(raw) = raw else {
        return (defaults(), vec!["not an object".into()]);
    };
    let base = defaults();
    let mut problems = Vec::new();
    let mut out = raw.clone(); // unknown keys are kept
    out.insert("version".into(), json!(VERSION));
    let language = match raw.get("language") {
        Some(Value::String(lang)) if (2..=12).contains(&lang.chars().count()) => lang.clone(),
        Some(_) => {
            problems.push("language".into());
            DEFAULT_LANGUAGE.into()
        }
        None => DEFAULT_LANGUAGE.into(),
    };
    out.insert("language".into(), json!(language));
    for &(section, fields) in SCHEMA {
        let src = match raw.get(section) {
            None => Map::new(),
            Some(Value::Object(m)) => m.clone(),
            Some(_) => {
                problems.push(section.to_string());
                Map::new()
            }
        };
        let mut sec = src.clone();
        for &(name, rule) in fields {
            let default = &base[section][name];
            let value = match src.get(name) {
                Some(v) => {
                    let (fixed, bad) = fix(rule, v, default);
                    if bad {
                        problems.push(format!("{section}.{name}"));
                    }
                    fixed
                }
                None => default.clone(),
            };
            sec.insert(name.to_string(), value);
        }
        if section == "input" {
            let b = match src.get("bindings") {
                Some(v) => fix_bindings(v, &mut problems),
                None => base["input"]["bindings"].clone(),
            };
            sec.insert("bindings".into(), b);
        }
        out.insert(section.to_string(), Value::Object(sec));
    }
    (Value::Object(out), problems)
}

/// Loads the settings file; a missing file gives the defaults with no problems, an unreadable one "unreadable".
pub fn load_file(path: &Path) -> (Value, Vec<String>) {
    match atomic_file::read_text(path) {
        Ok(text) => load(text.as_deref()),
        Err(_) => (defaults(), vec!["unreadable".into()]),
    }
}

/// Writes the settings atomically (pretty JSON, so players can read and edit it).
pub fn save_file(path: &Path, settings: &Value) -> io::Result<()> {
    let text = serde_json::to_string_pretty(settings).map_err(io::Error::other)?;
    atomic_file::write(path, text.as_bytes())
}

// ---- Reading loaded settings (every field is valid after load) -------------------
pub fn num(s: &Value, section: &str, name: &str) -> f64 {
    s[section][name].as_f64().unwrap_or(0.0)
}

pub fn flag(s: &Value, section: &str, name: &str) -> bool {
    s[section][name].as_bool().unwrap_or(false)
}

pub fn text<'a>(s: &'a Value, section: &str, name: &str) -> &'a str {
    s[section][name].as_str().unwrap_or("")
}

/// The shake intensity to use: 0 with reduce motion, else the shake_scale slider.
pub fn effective_shake(s: &Value) -> f64 {
    if flag(s, "access", "reduce_motion") {
        0.0
    } else {
        num(s, "access", "shake_scale")
    }
}

/// Telemetry only after an explicit yes ("unset" and "no" both mean no).
pub fn telemetry_allowed(s: &Value) -> bool {
    text(s, "telemetry", "consent") == "yes"
}

/// input.bindings as Bindings.
pub fn bindings(s: &Value) -> Bindings {
    bindings_from_value(&s["input"]["bindings"])
}

/// A JSON object of action -> [binding, ...] as Bindings (non-string entries are dropped).
pub fn bindings_from_value(value: &Value) -> Bindings {
    let mut out = Bindings::new();
    if let Some(map) = value.as_object() {
        for (action, list) in map {
            let slots = list
                .as_array()
                .map(|l| l.iter().filter_map(|b| b.as_str().map(str::to_string)).collect());
            out.insert(action.clone(), slots.unwrap_or_default());
        }
    }
    out
}

/// Bindings as the JSON object stored in input.bindings (and in the golden vectors).
pub fn bindings_value(b: &Bindings) -> Value {
    json!(b)
}

/// Stores new bindings (after a rebind) in the settings.
pub fn set_bindings(s: &mut Value, b: &Bindings) {
    s["input"]["bindings"] = bindings_value(b);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::logic::atomic_file::TempDir;

    #[test]
    fn a_missing_file_is_the_defaults_without_problems() {
        let dir = TempDir::new("settings-missing");
        assert_eq!(load_file(&dir.0.join("settings.json")), (defaults(), vec![]));
    }

    #[test]
    fn saved_settings_load_back_unchanged() {
        let dir = TempDir::new("settings-roundtrip");
        let path = dir.0.join("settings.json");
        let (mut s, _) = load(None);
        s["audio"]["music"] = json!(0.25);
        s["mod_menu"] = json!({"enabled": true}); // unknown keys survive the round trip
        save_file(&path, &s).unwrap();
        let (back, problems) = load_file(&path);
        assert!(problems.is_empty(), "{problems:?}");
        assert_eq!(back, s);
    }
}

// {{FOOTER}}
