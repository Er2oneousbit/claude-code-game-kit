// ---------------------------------------------------------------------------
// logic/audio_director.rs
// Purpose : Decides how each game sound plays: which file of the event (no back-to-back repeats), its pitch and
//           volume within the event's ranges, voice limits (steal the oldest or refuse), cooldowns, and how far
//           dialogue ducks the music and ambience buses. Data comes from data/audio_events.json.
// Usage   : let mut dir = AudioDirector::from_value(&events_json)?;   // { seed?, events, ducking? }
//           match dir.play("step_stone", now_ms)? {
//               PlayResult::Played(p) => start(&event.files[p.variant], p.pitch_ratio, p.gain_db, p.voice, p.stolen),
//               PlayResult::Cooldown | PlayResult::Capped => {}       // nothing to play, nothing was drawn
//           }
//           each frame: for (bus, db) in dir.duck(now_ms)? { set_bus_duck(&bus, db) }
// Notes   : Decisions only, no Bevy audio: a player system calls it and plays what it says (so cargo test runs it
//           in milliseconds). The spec is tools/audio/wavesmith/audio_events.py; tests/golden.rs replays every
//           step of data/golden/audio.json through it. Every port agrees because the random source is Park-Miller
//           (products stay below 2^53, no bit operations), event ids are ASCII, and randomness is drawn in a fixed
//           order (variant, pitch, volume) and never by a rejected play (cooldown, voice cap). Calls must come in
//           time order (milliseconds). lengths_ms per file: from the loaded clips (fill events[..].lengths_ms).
//
// Pseudocode:
//   play(e, t): drop finished voices -> cooldown? Cooldown -> at max_voices: steal the oldest or Capped
//               -> variant by pick rule -> pitch -> volume -> new voice (ends at t + length / pitch ratio)
//   duck(t):    per ducking rule: walk the trigger bus's voice edges since the last call, ramp in dB, then
//               forget trigger voices that ended by t (they can add no later edge)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::collections::{BTreeMap, BTreeSet};

use serde_json::Value;

// ---- Tunables ------------------------------------------------------------------
/// Voices one event may hold at once when its entry has no max_voices.
pub const DEFAULT_MAX_VOICES: usize = 8;
/// Park-Miller modulus (2^31 - 1) and multiplier: the "minimal standard" generator.
const PM_M: i64 = 2_147_483_647;
const PM_A: i64 = 16_807;

/// How an event chooses among its files.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Pick {
    /// Round robin: 0, 1, 2, 0, ...
    Sequence,
    /// Any file, repeats allowed.
    Random,
    /// Any file but the last one (the default).
    RandomNoRepeat,
    /// Every file once per round, never the same file twice across rounds.
    Shuffle,
}

impl Pick {
    pub fn from_name(name: &str) -> Option<Pick> {
        match name {
            "sequence" => Some(Pick::Sequence),
            "random" => Some(Pick::Random),
            "random_no_repeat" => Some(Pick::RandomNoRepeat),
            "shuffle" => Some(Pick::Shuffle),
            _ => None,
        }
    }
}

/// One entry of audio_events.json "events".
#[derive(Debug, Clone, PartialEq)]
pub struct AudioEvent {
    pub bus: String,
    pub files: Vec<String>,
    /// Length of each file in ms at pitch ratio 1 (the voice ends at start + length / ratio).
    pub lengths_ms: Vec<f64>,
    pub pick: Pick,
    /// [low, high] semitones; low == high draws nothing.
    pub pitch_semitones: (f64, f64),
    /// [low, high] dB; low == high draws nothing.
    pub volume_db: (f64, f64),
    pub max_voices: usize,
    /// At max_voices: true stops the oldest voice, false refuses the new play ("steal": "none").
    pub steal_oldest: bool,
    pub cooldown_ms: f64,
    /// Subtitle text for deaf and hard-of-hearing players ("[door creaks]"), shown by the game.
    pub caption: Option<String>,
    /// true: the caption gets an arrow when the source is off screen (logic/audio_access.rs).
    pub directional: bool,
}

/// One entry of audio_events.json "ducking": while `trigger` plays, `targets` dip towards depth_db.
#[derive(Debug, Clone, PartialEq)]
pub struct DuckRule {
    pub trigger: String,
    pub targets: Vec<String>,
    pub depth_db: f64,
    pub attack_ms: f64,
    pub release_ms: f64,
}

/// What play() decided.
#[derive(Debug, Clone, PartialEq)]
pub enum PlayResult {
    Played(Played),
    /// Inside the event's cooldown: nothing plays.
    Cooldown,
    /// At max_voices with steal "none": nothing plays.
    Capped,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Played {
    /// Index into the event's files.
    pub variant: usize,
    pub pitch_semitones: f64,
    /// Playback speed: 2^(semitones / 12).
    pub pitch_ratio: f64,
    pub gain_db: f64,
    /// Id of the new voice (1, 2, 3, ... per director).
    pub voice: u64,
    /// The voice to stop now, when the cap stole one.
    pub stolen: Option<u64>,
    pub ends_ms: f64,
}

#[derive(Debug, Clone)]
struct Voice {
    id: u64,
    event: String,
    bus: String,
    start: f64,
    /// Shortened to the steal time when the voice is stolen.
    end: f64,
}

/// Where one ducking envelope stood at its last duck() call.
#[derive(Debug, Clone, Copy)]
struct DuckState {
    gain: f64,
    t: f64,
}

/// Park-Miller minimal standard generator: exact in i64 (and in doubles), so every language agrees.
#[derive(Debug, Clone)]
pub struct ParkMiller {
    s: i64,
}

impl ParkMiller {
    pub fn new(seed: i64) -> Self {
        let s = seed.rem_euclid(PM_M);
        ParkMiller {
            s: if s == 0 { 1 } else { s },
        }
    }

    /// A float in [0, 1).
    pub fn next_f64(&mut self) -> f64 {
        self.s = (self.s * PM_A) % PM_M;
        (self.s - 1) as f64 / (PM_M - 1) as f64
    }
}

/// The seed of one event's generator: a hash of its (ASCII) id mixed with the file's seed.
pub fn event_seed(event_id: &str, global_seed: i64) -> i64 {
    let mut h: i64 = 0;
    for byte in event_id.bytes() {
        // ids are ASCII (validated), so byte, UTF-16 unit and code point agree across ports
        h = (h * 31 + byte as i64) % PM_M;
    }
    let s = (h + global_seed.rem_euclid(PM_M) * 7919) % PM_M;
    if s == 0 { 1 } else { s }
}

pub struct AudioDirector {
    /// Public so the player can fill lengths_ms from the loaded clips before the first play.
    pub events: BTreeMap<String, AudioEvent>,
    pub ducking: Vec<DuckRule>,
    rng: BTreeMap<String, ParkMiller>,
    voices: Vec<Voice>,
    /// Trigger-bus voices the ducking envelopes may still need (copies; a steal updates both).
    history: Vec<Voice>,
    triggers: BTreeSet<String>,
    next_id: u64,
    last_play: BTreeMap<String, f64>,
    last_variant: BTreeMap<String, usize>,
    bags: BTreeMap<String, Vec<usize>>,
    duck_state: Vec<DuckState>,
    now: f64,
}

impl AudioDirector {
    pub fn new(events: BTreeMap<String, AudioEvent>, ducking: Vec<DuckRule>, seed: i64) -> Self {
        let rng = events
            .keys()
            .map(|name| (name.clone(), ParkMiller::new(event_seed(name, seed))))
            .collect();
        let triggers = ducking.iter().map(|r| r.trigger.clone()).collect();
        let duck_state = vec![DuckState { gain: 0.0, t: 0.0 }; ducking.len()];
        AudioDirector {
            events,
            ducking,
            rng,
            voices: Vec::new(),
            history: Vec::new(),
            triggers,
            next_id: 1,
            last_play: BTreeMap::new(),
            last_variant: BTreeMap::new(),
            bags: BTreeMap::new(),
            duck_state,
            now: 0.0,
        }
    }

    /// From parsed audio_events.json (or a golden case's params): { seed?, events, ducking? }.
    pub fn from_value(params: &Value) -> Result<Self, String> {
        let seed = match &params["seed"] {
            Value::Null => 1,
            v => v
                .as_i64()
                .or_else(|| v.as_f64().map(|x| x as i64))
                .ok_or("seed must be a whole number")?,
        };
        let mut events = BTreeMap::new();
        let list = params["events"].as_object().ok_or("events must be an object")?;
        for (name, ev) in list {
            events.insert(name.clone(), event_from_value(name, ev)?);
        }
        let mut ducking = Vec::new();
        if let Some(rules) = params["ducking"].as_array() {
            for (n, rule) in rules.iter().enumerate() {
                ducking.push(duck_rule_from_value(n, rule)?);
            }
        }
        Ok(AudioDirector::new(events, ducking, seed))
    }

    fn clock(&mut self, t: f64) -> Result<(), String> {
        if t < self.now {
            return Err(format!("calls must come in time order ({t} ms after {} ms)", self.now));
        }
        self.now = t;
        Ok(())
    }

    /// Plays event `name` at `t` ms, or says why not. Errors (unknown event, missing lengths, time going
    /// backwards) change nothing.
    pub fn play(&mut self, name: &str, t: f64) -> Result<PlayResult, String> {
        let ev = self
            .events
            .get(name)
            .ok_or_else(|| format!("unknown audio event {name}"))?;
        if ev.lengths_ms.len() < ev.files.len() {
            return Err(format!(
                "event {name}: lengths_ms needs one length per file (from the loaded clips)"
            ));
        }
        let ev = ev.clone();
        self.clock(t)?;
        self.voices.retain(|v| v.end > t);
        if ev.cooldown_ms != 0.0 && self.last_play.get(name).is_some_and(|last| t - last < ev.cooldown_ms) {
            return Ok(PlayResult::Cooldown);
        }
        let mut stolen = None;
        let mine = self.voices.iter().filter(|v| v.event == name).count();
        if mine >= ev.max_voices {
            if !ev.steal_oldest {
                return Ok(PlayResult::Capped);
            }
            // the oldest voice of this event: earliest start, then lowest id
            let (at, victim) = self
                .voices
                .iter()
                .enumerate()
                .filter(|(_, v)| v.event == name)
                .min_by(|(_, a), (_, b)| a.start.total_cmp(&b.start).then(a.id.cmp(&b.id)))
                .map(|(at, v)| (at, v.id))
                .expect("mine >= max_voices >= 1, so this event has a voice");
            self.voices.remove(at);
            // it stops now: the ducking envelope must see the shortened end
            for h in self.history.iter_mut().filter(|h| h.id == victim) {
                h.end = t;
            }
            stolen = Some(victim);
        }
        let idx = self.pick(name, &ev);
        let rng = self.rng.get_mut(name).expect("one generator per event, made in new()");
        let (lo, hi) = ev.pitch_semitones;
        let semis = if lo == hi { lo } else { lo + (hi - lo) * rng.next_f64() };
        let (vlo, vhi) = ev.volume_db;
        let gain = if vlo == vhi {
            vlo
        } else {
            vlo + (vhi - vlo) * rng.next_f64()
        };
        let ratio = 2f64.powf(semis / 12.0);
        let voice = Voice {
            id: self.next_id,
            event: name.to_string(),
            bus: ev.bus.clone(),
            start: t,
            end: t + ev.lengths_ms[idx] / ratio,
        };
        self.next_id += 1;
        if self.triggers.contains(&voice.bus) {
            self.history.push(voice.clone());
        }
        let played = Played {
            variant: idx,
            pitch_semitones: semis,
            pitch_ratio: ratio,
            gain_db: gain,
            voice: voice.id,
            stolen,
            ends_ms: voice.end,
        };
        self.voices.push(voice);
        self.last_play.insert(name.to_string(), t);
        self.last_variant.insert(name.to_string(), idx);
        Ok(PlayResult::Played(played))
    }

    /// The variant to play; draws from the event's generator only when the pick rule needs it.
    fn pick(&mut self, name: &str, ev: &AudioEvent) -> usize {
        let n = ev.files.len();
        let last = self.last_variant.get(name).copied();
        if n == 1 {
            return 0;
        }
        let rng = self.rng.get_mut(name).expect("one generator per event, made in new()");
        // int(r * n) in the reference: r is in [0, 1), the min() guards the top end
        let draw = |rng: &mut ParkMiller, n: usize| ((rng.next_f64() * n as f64) as usize).min(n - 1);
        match ev.pick {
            Pick::Sequence => last.map_or(0, |l| (l + 1) % n),
            Pick::Random => draw(rng, n),
            Pick::RandomNoRepeat => match last {
                None => draw(rng, n),
                Some(l) => {
                    // one of the n - 1 other files: draw among them, skip over the last one
                    let k = draw(rng, n - 1);
                    if k >= l { k + 1 } else { k }
                }
            },
            Pick::Shuffle => {
                let mut bag = self.bags.remove(name).unwrap_or_default();
                if bag.is_empty() {
                    // refill with Fisher-Yates from the top down (the reference's order of draws)
                    bag = (0..n).collect();
                    for i in (1..n).rev() {
                        let j = draw(rng, i + 1);
                        bag.swap(i, j);
                    }
                    if Some(bag[0]) == last {
                        bag.swap(0, 1); // never the same file twice across a refill
                    }
                }
                let idx = bag.remove(0);
                self.bags.insert(name.to_string(), bag);
                idx
            }
        }
    }

    /// Duck gain in dB per target bus at `t` ms (every rule advanced to t; a bus under two rules takes the
    /// deeper one). Buses no rule targets are absent (0 dB).
    pub fn duck(&mut self, t: f64) -> Result<BTreeMap<String, f64>, String> {
        self.clock(t)?;
        let mut out: BTreeMap<String, f64> = BTreeMap::new();
        for (rule, st) in self.ducking.iter().zip(self.duck_state.iter_mut()) {
            let mine: Vec<&Voice> = self.history.iter().filter(|v| v.bus == rule.trigger).collect();
            // every start or end strictly between the last call and now, sorted, each once
            let mut edges: Vec<f64> = mine
                .iter()
                .flat_map(|v| [v.start, v.end])
                .filter(|e| st.t < *e && *e < t)
                .collect();
            edges.sort_by(f64::total_cmp);
            edges.dedup();
            edges.push(t);
            let (mut gain, mut at) = (st.gain, st.t);
            for edge in edges {
                let active = mine.iter().any(|v| v.start <= at && at < v.end);
                gain = ramp(gain, active, rule, edge - at);
                at = edge;
            }
            *st = DuckState { gain, t };
            for bus in &rule.targets {
                let slot = out.entry(bus.clone()).or_insert(0.0);
                *slot = slot.min(gain);
            }
        }
        // every rule now stands at t: a voice that ended at or before t adds no later edge and is never active
        // again, so it can go (keeps duck() cheap in a long session; results are unchanged)
        self.history.retain(|v| v.end > t);
        Ok(out)
    }
}

/// A straight line in dB: towards depth over attack_ms while active, back to 0 over release_ms when not.
fn ramp(gain: f64, active: bool, rule: &DuckRule, dt: f64) -> f64 {
    let depth = rule.depth_db;
    if active {
        if rule.attack_ms <= 0.0 {
            return depth;
        }
        return depth.max(gain + depth / rule.attack_ms * dt);
    }
    if rule.release_ms <= 0.0 {
        return 0.0;
    }
    0f64.min(gain - depth / rule.release_ms * dt)
}

// ---- Reading the JSON ------------------------------------------------------------
fn num_or(v: &Value, default: f64, what: &str) -> Result<f64, String> {
    match v {
        Value::Null => Ok(default),
        v => v.as_f64().ok_or_else(|| format!("{what} must be a number")),
    }
}

fn range_or_zero(v: &Value, what: &str) -> Result<(f64, f64), String> {
    match v {
        Value::Null => Ok((0.0, 0.0)),
        Value::Array(a) if a.len() == 2 && a.iter().all(Value::is_number) => {
            Ok((a[0].as_f64().unwrap_or(0.0), a[1].as_f64().unwrap_or(0.0)))
        }
        _ => Err(format!("{what} must be [low, high]")),
    }
}

fn event_from_value(name: &str, ev: &Value) -> Result<AudioEvent, String> {
    let where_ = format!("event {name}");
    let files: Vec<String> = ev["files"]
        .as_array()
        .ok_or(format!("{where_}: files must be a list"))?
        .iter()
        .map(|f| {
            f.as_str()
                .map(str::to_string)
                .ok_or(format!("{where_}: files must be text"))
        })
        .collect::<Result<_, _>>()?;
    if files.is_empty() {
        return Err(format!("{where_}: files must not be empty"));
    }
    // a real events file has no lengths_ms (the player measures the clips); golden cases carry them
    let lengths_ms = match &ev["lengths_ms"] {
        Value::Null => Vec::new(),
        v => v
            .as_array()
            .ok_or(format!("{where_}: lengths_ms must be a list"))?
            .iter()
            .map(|x| x.as_f64().ok_or(format!("{where_}: lengths_ms must be numbers")))
            .collect::<Result<_, _>>()?,
    };
    let pick = match ev["pick"].as_str() {
        None => Pick::RandomNoRepeat,
        Some(p) => Pick::from_name(p).ok_or(format!("{where_}: unknown pick {p:?}"))?,
    };
    let steal_oldest = match ev["steal"].as_str() {
        None | Some("oldest") => true,
        Some("none") => false,
        Some(s) => return Err(format!("{where_}: unknown steal {s:?}")),
    };
    let max_voices = num_or(&ev["max_voices"], DEFAULT_MAX_VOICES as f64, &where_)?;
    if max_voices < 1.0 {
        return Err(format!("{where_}: max_voices must be 1 or more"));
    }
    Ok(AudioEvent {
        bus: ev["bus"]
            .as_str()
            .ok_or(format!("{where_}: bus is required"))?
            .to_string(),
        files,
        lengths_ms,
        pick,
        pitch_semitones: range_or_zero(&ev["pitch_semitones"], &format!("{where_}: pitch_semitones"))?,
        volume_db: range_or_zero(&ev["volume_db"], &format!("{where_}: volume_db"))?,
        max_voices: max_voices as usize,
        steal_oldest,
        cooldown_ms: num_or(&ev["cooldown_ms"], 0.0, &format!("{where_}: cooldown_ms"))?,
        caption: ev["caption"].as_str().map(str::to_string),
        directional: ev["directional"].as_bool().unwrap_or(false),
    })
}

fn duck_rule_from_value(n: usize, rule: &Value) -> Result<DuckRule, String> {
    let where_ = format!("ducking[{n}]");
    Ok(DuckRule {
        trigger: rule["trigger"]
            .as_str()
            .ok_or(format!("{where_}: trigger is required"))?
            .to_string(),
        targets: rule["targets"]
            .as_array()
            .ok_or(format!("{where_}: targets must be a list"))?
            .iter()
            .filter_map(|b| b.as_str().map(str::to_string))
            .collect(),
        depth_db: rule["depth_db"]
            .as_f64()
            .ok_or(format!("{where_}: depth_db is required"))?,
        attack_ms: num_or(&rule["attack_ms"], 0.0, &where_)?,
        release_ms: num_or(&rule["release_ms"], 0.0, &where_)?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn director(ev: Value) -> AudioDirector {
        AudioDirector::from_value(&json!({"seed": 1, "events": {"knock": ev}})).unwrap()
    }

    #[test]
    fn park_miller_starts_where_the_reference_does() {
        // 16807 * 1 % (2^31 - 1) = 16807: the first draw of seed 1
        let mut rng = ParkMiller::new(1);
        assert_eq!(rng.next_f64(), 16806.0 / 2_147_483_646.0);
        assert_eq!(ParkMiller::new(0).s, 1, "seed 0 would stay 0 forever");
    }

    #[test]
    fn calls_out_of_time_order_are_refused_and_change_nothing() {
        let mut d = director(json!({"bus": "sfx", "files": ["a.wav"], "lengths_ms": [100]}));
        assert!(d.play("knock", 500.0).is_ok());
        assert!(d.play("knock", 400.0).is_err());
        assert!(d.duck(10.0).is_err());
        assert!(d.play("unknown", 600.0).is_err());
    }

    #[test]
    fn missing_lengths_are_an_error_not_a_panic() {
        let mut d = director(json!({"bus": "sfx", "files": ["a.wav", "b.wav"]}));
        assert!(d.play("knock", 0.0).is_err());
        d.events.get_mut("knock").unwrap().lengths_ms = vec![100.0, 120.0];
        assert!(matches!(d.play("knock", 0.0), Ok(PlayResult::Played(_))));
    }

    #[test]
    fn bad_pick_and_steal_names_are_rejected() {
        let bad = |ev: Value| AudioDirector::from_value(&json!({"events": {"knock": ev}})).is_err();
        assert!(bad(json!({"bus": "sfx", "files": ["a.wav"], "pick": "loudest"})));
        assert!(bad(json!({"bus": "sfx", "files": ["a.wav"], "steal": "newest"})));
        assert!(bad(json!({"bus": "sfx", "files": []})));
    }
}
