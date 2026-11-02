// ---------------------------------------------------------------------------
// logic/music_director.rs
// Purpose : The adaptive-music rules of data/music.json, with no Bevy audio in them: the sample grid, loop points,
//           where playback is, the next beat / bar / phrase / loop end, which transition rule applies, and the plan
//           for a change (when, fade, stinger, entry point).
// Usage   : let music = MusicFile::from_value(&music_json)?;
//           let p = music_director::plan(&music, "explore", since_sample, entry_sample, "combat", now_sample)?;
//           p.switch_at, p.from_stop_at, p.to_start_at, p.to_offset, p.stinger_at   (all in samples)
// Notes   : A port of tools/audio/wavesmith/music.py (the reference): every value is a whole number of samples and
//           tests/golden.rs checks data/golden/music.json exactly (tolerance 0). Beat k starts at
//           floor(k * 60 * rate / bpm + 0.5): f64::round is not the rule (it rounds halves away from zero, which
//           differs from floor(x + 0.5) below zero). The products stay far below 2^53, so f64 is exact where the
//           reference uses Python integers.
//
// Pseudocode:
//   beat_sample(k) = floor(k * 60 * rate / bpm + 0.5); bar b starts at beat_sample(b * beats_per_bar)
//   position(track, since, now, entry): p = now - since + entry; past the loop end -> wrap into the loop
//   plan(from, to, now): rule (exact pair, from *, to *, default) -> next boundary of its quantize at or after p
//                        -> switch_at = now + (boundary - p); stinger? target enters after the stinger's bars
//                        -> target entry offset 0, or the same position in the bar when "sync" and the grids match
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::collections::BTreeMap;

use serde_json::Value;

// ---- Tunables ------------------------------------------------------------------
pub const DEFAULT_BEATS_PER_BAR: i64 = 4;
pub const DEFAULT_PHRASE_BARS: i64 = 4;

/// When a transition may happen.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Quantize {
    Immediate,
    Beat,
    Bar,
    Phrase,
    LoopEnd,
}

impl Quantize {
    pub fn from_name(name: &str) -> Option<Quantize> {
        match name {
            "immediate" => Some(Quantize::Immediate),
            "beat" => Some(Quantize::Beat),
            "bar" => Some(Quantize::Bar),
            "phrase" => Some(Quantize::Phrase),
            "loop_end" => Some(Quantize::LoopEnd),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct MusicTrack {
    pub bpm: f64,
    pub beats_per_bar: i64,
    pub bars: i64,
    /// Bars before it are an intro that plays once.
    pub loop_start_bar: i64,
    /// stem name -> file; stems start together and stay locked.
    pub stems: BTreeMap<String, String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Stinger {
    pub file: String,
    /// The next track enters after this many of ITS bars (may be fractional).
    pub bars: f64,
}

/// A transition entry as written: every field may be missing, so rules merge like the reference's dicts
/// (built-in default, then the file's default_transition, then the matching rule).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct RulePatch {
    pub from: Option<String>,
    pub to: Option<String>,
    pub quantize: Option<Quantize>,
    pub fade_ms: Option<f64>,
    pub sync: Option<bool>,
    /// Some(None) is an explicit "stinger": null, which clears a stinger from default_transition.
    pub stinger: Option<Option<String>>,
    pub phrase_bars: Option<i64>,
}

/// The rule that applies, every field filled.
#[derive(Debug, Clone, PartialEq)]
pub struct Rule {
    pub quantize: Quantize,
    pub fade_ms: f64,
    pub sync: bool,
    pub stinger: Option<String>,
    pub phrase_bars: i64,
}

impl Default for Rule {
    /// The built-in default: next bar, no fade, no sync.
    fn default() -> Self {
        Rule {
            quantize: Quantize::Bar,
            fade_ms: 0.0,
            sync: false,
            stinger: None,
            phrase_bars: DEFAULT_PHRASE_BARS,
        }
    }
}

impl Rule {
    fn apply(&mut self, p: &RulePatch) {
        if let Some(q) = p.quantize {
            self.quantize = q;
        }
        if let Some(f) = p.fade_ms {
            self.fade_ms = f;
        }
        if let Some(s) = p.sync {
            self.sync = s;
        }
        if let Some(s) = &p.stinger {
            self.stinger = s.clone();
        }
        if let Some(b) = p.phrase_bars {
            self.phrase_bars = b;
        }
    }
}

/// data/music.json, parsed.
#[derive(Debug, Clone, PartialEq)]
pub struct MusicFile {
    pub sample_rate: i64,
    pub start: Option<String>,
    pub tracks: BTreeMap<String, MusicTrack>,
    pub stingers: BTreeMap<String, Stinger>,
    pub transitions: Vec<RulePatch>,
    pub default_transition: RulePatch,
}

/// A planned change; every value is a sample count on the shared clock (stinger is the stinger's name).
#[derive(Debug, Clone, PartialEq)]
pub struct MusicPlan {
    pub switch_at: i64,
    pub from_stop_at: i64,
    pub fade: i64,
    pub to_offset: i64,
    pub to_start_at: i64,
    pub stinger: Option<String>,
    pub stinger_at: Option<i64>,
}

// ---- The grid ------------------------------------------------------------------
/// First sample of beat k (k may be fractional for a stinger's bars).
pub fn beat_sample(k: f64, bpm: f64, rate: i64) -> i64 {
    (k * 60.0 * rate as f64 / bpm + 0.5).floor() as i64
}

pub fn bar_sample(b: i64, t: &MusicTrack, rate: i64) -> i64 {
    beat_sample((b * t.beats_per_bar) as f64, t.bpm, rate)
}

/// The bar that contains `sample` (exact on the rounded grid, not a float estimate).
pub fn bar_index_at(sample: i64, t: &MusicTrack, rate: i64) -> i64 {
    let mut b = (sample as f64 * t.bpm / (60 * rate * t.beats_per_bar) as f64).floor() as i64;
    while bar_sample(b + 1, t, rate) <= sample {
        b += 1;
    }
    while b > 0 && bar_sample(b, t, rate) > sample {
        b -= 1;
    }
    b
}

/// (loop start, loop end) in samples: the loop plays [start, end) forever after the intro.
pub fn loop_points(t: &MusicTrack, rate: i64) -> (i64, i64) {
    (bar_sample(t.loop_start_bar, t, rate), bar_sample(t.bars, t, rate))
}

/// Where in the track (samples from its start) playback is at `now`, when it started at `since` from `entry`.
pub fn position(t: &MusicTrack, rate: i64, since: i64, now: i64, entry: i64) -> i64 {
    let p = now - since + entry;
    let (start, end) = loop_points(t, rate);
    if p >= end {
        // rem_euclid: Python's % (never negative)
        return start + (p - start).rem_euclid(end - start);
    }
    p
}

/// The first boundary of the given kind at or after track position p (a loop position: 0 <= p < loop end).
pub fn next_boundary(t: &MusicTrack, rate: i64, p: i64, quantize: Quantize, phrase_bars: i64) -> i64 {
    let (_, end) = loop_points(t, rate);
    let step = match quantize {
        Quantize::Immediate => return p,
        Quantize::LoopEnd => return end,
        Quantize::Beat => 1,
        Quantize::Bar => t.beats_per_bar,
        Quantize::Phrase => t.beats_per_bar * phrase_bars,
    };
    // the beat at or after p, then up to the next multiple of step (counted from the track's first beat)
    let mut k = (p as f64 * t.bpm / (60 * rate) as f64).floor() as i64;
    while beat_sample(k as f64, t.bpm, rate) < p {
        k += 1;
    }
    while k % step != 0 {
        k += 1;
    }
    beat_sample(k as f64, t.bpm, rate).min(end)
}

/// The transition rule: exact pair, then from "*", then to "*", then the file's default, then the built-in one.
pub fn rule_for(m: &MusicFile, from: &str, to: &str) -> Rule {
    let mut rule = Rule::default();
    rule.apply(&m.default_transition);
    for (f, t) in [(from, to), ("*", to), (from, "*")] {
        if let Some(r) = m
            .transitions
            .iter()
            .find(|r| r.from.as_deref() == Some(f) && r.to.as_deref() == Some(t))
        {
            rule.apply(r);
            return rule;
        }
    }
    rule
}

/// When and how to change from track `from` (playing since sample `since` from offset `entry`) to `to`, asked at
/// sample `now`.
pub fn plan(m: &MusicFile, from: &str, since: i64, entry: i64, to: &str, now: i64) -> Result<MusicPlan, String> {
    let rate = m.sample_rate;
    let a = m.tracks.get(from).ok_or_else(|| format!("unknown track {from}"))?;
    let b = m.tracks.get(to).ok_or_else(|| format!("unknown track {to}"))?;
    let rule = rule_for(m, from, to);
    let p = position(a, rate, since, now, entry);
    let boundary = next_boundary(a, rate, p, rule.quantize, rule.phrase_bars);
    let switch_at = now + (boundary - p);
    let fade = (rule.fade_ms * rate as f64 / 1000.0 + 0.5).floor() as i64;
    let mut out = MusicPlan {
        switch_at,
        from_stop_at: switch_at + fade,
        fade,
        to_offset: 0,
        to_start_at: switch_at,
        stinger: rule.stinger.clone(),
        stinger_at: None,
    };
    // an empty stinger name counts as none, like the reference's truthiness test
    if let Some(name) = rule.stinger.as_deref().filter(|s| !s.is_empty()) {
        let st = m.stingers.get(name).ok_or_else(|| format!("unknown stinger {name}"))?;
        out.stinger_at = Some(switch_at);
        out.to_start_at = switch_at + beat_sample(st.bars * b.beats_per_bar as f64, b.bpm, rate);
    } else if rule.sync && a.bpm == b.bpm && a.beats_per_bar == b.beats_per_bar {
        // keep the beat: enter the target at the same place in its bar (bar boundaries are where they line up)
        out.to_offset = boundary - bar_sample(bar_index_at(boundary, a, rate), a, rate);
    }
    Ok(out)
}

// ---- Reading the JSON ------------------------------------------------------------
fn int_or(v: &Value, default: i64, what: &str) -> Result<i64, String> {
    match v {
        Value::Null => Ok(default),
        // whole numbers may arrive as 4.0 from other writers
        v => v
            .as_i64()
            .or_else(|| v.as_f64().filter(|x| x.fract() == 0.0).map(|x| x as i64))
            .ok_or_else(|| format!("{what} must be a whole number")),
    }
}

fn patch_from_value(r: &Value, what: &str) -> Result<RulePatch, String> {
    let quantize = match &r["quantize"] {
        Value::Null => None,
        v => {
            let q = v.as_str().unwrap_or("");
            Some(Quantize::from_name(q).ok_or_else(|| format!("{what}: unknown quantize {v}"))?)
        }
    };
    let stinger = match r.get("stinger") {
        None => None,
        Some(Value::Null) => Some(None),
        Some(v) => Some(Some(
            v.as_str().ok_or(format!("{what}: stinger must be a name"))?.to_string(),
        )),
    };
    Ok(RulePatch {
        from: r["from"].as_str().map(str::to_string),
        to: r["to"].as_str().map(str::to_string),
        quantize,
        fade_ms: r["fade_ms"].as_f64(),
        sync: r["sync"].as_bool(),
        stinger,
        phrase_bars: match &r["phrase_bars"] {
            Value::Null => None,
            v => Some(int_or(v, DEFAULT_PHRASE_BARS, &format!("{what}: phrase_bars"))?),
        },
    })
}

impl MusicFile {
    /// From parsed data/music.json (or a golden case's params).
    pub fn from_value(data: &Value) -> Result<MusicFile, String> {
        let sample_rate = int_or(&data["sample_rate"], 0, "sample_rate")?;
        if sample_rate <= 0 {
            return Err("sample_rate must be a whole number of Hz".into());
        }
        let mut tracks = BTreeMap::new();
        for (name, t) in data["tracks"].as_object().ok_or("tracks must be an object")? {
            let what = format!("track {name}");
            let stems = t["stems"]
                .as_object()
                .map(|s| {
                    s.iter()
                        .filter_map(|(k, v)| v.as_str().map(|f| (k.clone(), f.to_string())))
                        .collect()
                })
                .unwrap_or_default();
            let track = MusicTrack {
                bpm: t["bpm"].as_f64().ok_or(format!("{what}: bpm is required"))?,
                beats_per_bar: int_or(&t["beats_per_bar"], DEFAULT_BEATS_PER_BAR, &what)?,
                bars: int_or(&t["bars"], 0, &what)?,
                loop_start_bar: int_or(&t["loop_start_bar"], 0, &what)?,
                stems,
            };
            if track.bpm <= 0.0 || track.beats_per_bar < 1 || track.bars < 1 {
                return Err(format!("{what}: bpm, beats_per_bar and bars must be above 0"));
            }
            tracks.insert(name.clone(), track);
        }
        let mut stingers = BTreeMap::new();
        if let Some(list) = data["stingers"].as_object() {
            for (name, s) in list {
                let stinger = Stinger {
                    file: s["file"].as_str().unwrap_or("").to_string(),
                    bars: s["bars"].as_f64().ok_or(format!("stinger {name}: bars is required"))?,
                };
                stingers.insert(name.clone(), stinger);
            }
        }
        let mut transitions = Vec::new();
        if let Some(list) = data["transitions"].as_array() {
            for (n, r) in list.iter().enumerate() {
                transitions.push(patch_from_value(r, &format!("transition {n}"))?);
            }
        }
        let default_transition = match &data["default_transition"] {
            Value::Null => RulePatch::default(),
            v => patch_from_value(v, "default_transition")?,
        };
        Ok(MusicFile {
            sample_rate,
            start: data["start"].as_str().map(str::to_string),
            tracks,
            stingers,
            transitions,
            default_transition,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn track(bpm: f64, bars: i64) -> MusicTrack {
        MusicTrack {
            bpm,
            beats_per_bar: 4,
            bars,
            loop_start_bar: 0,
            stems: BTreeMap::new(),
        }
    }

    #[test]
    fn halves_round_up_on_the_grid() {
        // 1 beat at 96 BPM and 44100 Hz is 27562.5 samples: floor(x + 0.5) gives 27563
        assert_eq!(beat_sample(1.0, 96.0, 44100), 27563);
        assert_eq!(beat_sample(0.0, 96.0, 44100), 0);
    }

    #[test]
    fn position_wraps_into_the_loop_and_boundaries_never_pass_the_loop_end() {
        let t = track(120.0, 2); // 2 bars of 4 beats at 120 BPM, 48 kHz: 8 * 24000 = 192000 samples
        assert_eq!(position(&t, 48000, 0, 192_000 + 10, 0), 10);
        assert_eq!(
            next_boundary(&t, 48000, 191_000, Quantize::Phrase, 4),
            192_000,
            "a phrase is 4 bars: capped"
        );
        assert_eq!(next_boundary(&t, 48000, 5, Quantize::Immediate, 4), 5);
    }

    #[test]
    fn unknown_tracks_are_an_error() {
        let m = MusicFile::from_value(&serde_json::json!({
            "sample_rate": 44100, "tracks": {"a": {"bpm": 90, "bars": 4, "stems": {"x": "a.wav"}}}
        }))
        .unwrap();
        assert!(plan(&m, "a", 0, 0, "b", 0).is_err());
        assert!(plan(&m, "a", 0, 0, "a", 0).is_ok());
    }
}
