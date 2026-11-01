// ---------------------------------------------------------------------------
// logic/audio_access.rs
// Purpose : Audio accessibility rules with no Bevy audio in them: which settings slider turns which bus of
//           data/audio_events.json up or down, and which arrow a directional caption gets when the sound comes
//           from off screen.
// Usage   : let gains = audio_access::user_bus_gains(&events["buses"], &settings["audio"]);  // {"music": 0.8, ...}
//           audio_access::caption_arrow(src.x - cam.x, cam.y - src.y, half_w, half_h)    // "" | "←" | "↗" ...
// Notes   : Sliders are linear 0..1 (settings.audio: master, music, sfx, ui, voice), as the settings screen shows
//           them; a slider multiplies its bus on top of the bus's volume_db and the ducking. A bus follows the
//           slider named in SLIDER_FOR_BUS; when one of its parents already follows the same slider it gets 1, so
//           a slider never counts twice down one branch (ambience under sfx). Buses without a slider get 1. A bad
//           value clamps to 0..1; a missing or non-numeric one (text, null) counts as 1. Parents default to
//           "master" (master has none); the walk stops after one step per bus, so a cycle cannot hang.
//           Arrows use SCREEN coordinates (y grows downwards; Bevy's world y grows upwards, so flip it): nothing
//           while the source is inside the view (edges included), otherwise
//           k = floor(atan2(dy, dx) / 45 degrees + 0.5) mod 8, clockwise from the right. floor(x + 0.5) is the
//           rule in every engine: f64::round rounds halves away from zero and is not used.
//           The spec is tools/audio/wavesmith/access.py; tests/golden.rs checks data/golden/access.json.
//
// Pseudocode:
//   gains: for each bus: slider = SLIDER_FOR_BUS[bus]; walk the parents; a parent with the same slider -> 1;
//          no slider -> 1; else clamp(slider value)
//   arrow: inside the half sizes -> none; else k from atan2 -> ARROWS[k]
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::collections::BTreeMap;
use std::f64::consts::PI;

use serde_json::Value;

// ---- Tunables ------------------------------------------------------------------
/// Bus name -> settings slider. Edit it when your audio_events.json uses other bus names.
pub const SLIDER_FOR_BUS: [(&str, &str); 7] = [
    ("master", "master"),
    ("music", "music"),
    ("sfx", "sfx"),
    ("ambience", "sfx"),
    ("ui", "ui"),
    ("dialogue", "voice"),
    ("voice", "voice"),
];
/// Every 45 degrees, clockwise from the right (screen y grows downwards): k = 0..7.
pub const ARROWS: [&str; 8] = ["→", "↘", "↓", "↙", "←", "↖", "↑", "↗"];
/// The bus every bus without a parent hangs under.
pub const ROOT_BUS: &str = "master";

/// The slider that drives `bus` in the built-in mapping, if any.
pub fn slider_for(bus: &str) -> Option<&'static str> {
    SLIDER_FOR_BUS.iter().find(|(b, _)| *b == bus).map(|(_, s)| *s)
}

/// A slider value as a gain: numbers clamp to 0..1, anything else (missing, text, null, true) is 1.
pub fn clamp01(v: Option<&Value>) -> f64 {
    match v.and_then(Value::as_f64) {
        Some(x) if x.is_finite() => x.clamp(0.0, 1.0),
        _ => 1.0,
    }
}

/// {bus: linear gain} from the player's sliders (settings["audio"]), a slider never applied twice down one
/// branch. `buses` is audio_events.json "buses": {"name": {"parent": "master"}, ...}.
pub fn user_bus_gains(buses: &Value, sliders: &Value) -> BTreeMap<String, f64> {
    user_bus_gains_with(buses, sliders, slider_for)
}

/// user_bus_gains with your own bus -> slider mapping.
pub fn user_bus_gains_with(
    buses: &Value,
    sliders: &Value,
    mapping: impl Fn(&str) -> Option<&'static str>,
) -> BTreeMap<String, f64> {
    let empty = serde_json::Map::new();
    let buses = buses.as_object().unwrap_or(&empty);
    // a bus with no (or a null) parent hangs under master; master and unknown names past it end the walk
    let parent_of = |b: &str| -> Option<String> {
        match buses.get(b).and_then(|v| v.get("parent")).and_then(Value::as_str) {
            Some(p) => Some(p.to_string()),
            None if b == ROOT_BUS => None,
            None => Some(ROOT_BUS.to_string()),
        }
    };
    let mut out = BTreeMap::new();
    for name in buses.keys() {
        let slider = mapping(name);
        let mut inherited = false;
        let (mut p, mut n) = (parent_of(name), 0);
        while let Some(parent) = p.as_deref() {
            if n >= buses.len() {
                break; // one step per bus at most: a cycle stops here
            }
            if slider.is_some() && mapping(parent) == slider {
                inherited = true;
            }
            p = parent_of(parent);
            n += 1;
        }
        let gain = match slider {
            Some(s) if !inherited => clamp01(sliders.get(s)),
            _ => 1.0,
        };
        out.insert(name.clone(), gain);
    }
    out
}

/// -1 while a sound at (dx, dy) from the view's centre is inside the view (edges included), else the direction
/// 0..7 clockwise from the right (screen y grows downwards).
pub fn caption_direction(dx: f64, dy: f64, half_w: f64, half_h: f64) -> i32 {
    if !(dx.is_finite() && dy.is_finite()) {
        return -1;
    }
    if dx.abs() <= half_w && dy.abs() <= half_h {
        return -1;
    }
    // floor(x + 0.5), then a modulo that is never negative (Python's %)
    let k = (dy.atan2(dx) / (PI / 4.0) + 0.5).floor() as i32;
    k.rem_euclid(8)
}

/// The arrow for a sound at (dx, dy) from the view's centre, or "" while it is inside the view.
pub fn caption_arrow(dx: f64, dy: f64, half_w: f64, half_h: f64) -> &'static str {
    match caption_direction(dx, dy, half_w, half_h) {
        k if k < 0 => "",
        k => ARROWS[k as usize],
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_slider_is_never_applied_twice_down_one_branch() {
        let buses = json!({"master": {}, "sfx": {}, "ambience": {"parent": "sfx"}, "bells": {"parent": "ambience"}});
        let g = user_bus_gains(&buses, &json!({"master": 0.5, "sfx": 0.25}));
        assert_eq!(g["sfx"], 0.25);
        assert_eq!(g["ambience"], 1.0, "sfx already turns it down through its parent");
        assert_eq!(g["bells"], 1.0, "no slider of its own");
        assert_eq!(g["master"], 0.5);
    }

    #[test]
    fn text_null_and_missing_sliders_count_as_one_and_numbers_clamp() {
        let buses = json!({"master": {}, "music": {}, "sfx": {}, "ui": {}});
        let g = user_bus_gains(&buses, &json!({"master": 2, "music": "loud", "sfx": null}));
        assert_eq!((g["master"], g["music"], g["sfx"], g["ui"]), (1.0, 1.0, 1.0, 1.0));
        assert_eq!(user_bus_gains(&buses, &json!({"music": -1}))["music"], 0.0);
    }

    #[test]
    fn a_parent_cycle_ends() {
        let g = user_bus_gains(&json!({"a": {"parent": "b"}, "b": {"parent": "a"}}), &json!({}));
        assert_eq!(g.len(), 2);
    }

    #[test]
    fn halves_of_a_direction_round_up_not_away_from_zero() {
        // straight left is atan2(0, -1) = pi: k = floor(4 + 0.5) = 4
        assert_eq!(caption_arrow(-500.0, 0.0, 320.0, 180.0), "←");
        assert_eq!(
            caption_direction(320.0, 180.0, 320.0, 180.0),
            -1,
            "the edge counts as on screen"
        );
        assert_eq!(caption_direction(f64::NAN, 0.0, 1.0, 1.0), -1);
    }
}

// {{FOOTER}}
