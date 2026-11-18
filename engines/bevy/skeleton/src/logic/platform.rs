// ---------------------------------------------------------------------------
// logic/platform.rs
// Purpose : The engine-free platform layer (#84, docs/PLATFORM.md): achievements, stats, rich presence, the
//           overlay's pause hook and cloud saves, kept here and sent to a backend. Every game runs the null backend
//           (it records every call); the Steam adapter (src/logic/platform_steam.rs, cargo feature `steam`)
//           replaces it in a store build. No Bevy types. Checked against data/golden/platform.json (every case).
// Usage   : shell.platform.unlock("first_win"); shell.platform.add_stat("enemies_defeated", 1.0);
//           shell.platform.flush();                              // at checkpoints (the shell flushes on pause, quit)
//           shell.platform.set_presence("status", "In the crypt");
//           pure parts: achievements_load(text), cloud_partition(path), overlay_action(active, screen),
//           Platform::new(defs, NullBackend::default(), online, cloud), platform_state_load(defs, text)
// Notes   : Calls are JSON arrays (["set_stat", "coins", 7]) so tests compare them with the vectors as they are.
//           Stat values enter as JSON (set_stat(id, &Value)): a string, a boolean or a fraction for an int stat is
//           refused by the rules, never by a cast. With no data/achievements.json every call is "unknown" and
//           nothing is written, so a game without achievements runs exactly as before. The state file
//           (<user-data>/platform_state.json) is a cache, written atomically only when it changed.
//
// Pseudocode:
//   rules op -> update local state -> online: send calls to the backend one at a time, in order
//   flush: set_stat per pending stat (definition order), set_achievement per pending unlock, store_stats;
//          a false store_stats keeps everything and goes offline; then cloud_write per pending cloud file
//   service: defs <- data/achievements.json ; state <- platform_state.json ; backend available ->
//          connect(backend.remote()) ; after every op: write the state file when it changed
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde_json::{Map, Value, json};

use crate::logic::atomic_file;

// ---- Tunables (the same in every engine: data/golden/platform.json "names and limits") --------------------------
pub const FORMAT: &str = "platform_state";
pub const STATE_VERSION: i64 = 1;
pub const STATE_FILE: &str = "platform_state.json";
pub const ACHIEVEMENTS_FILE: &str = "achievements.json"; // under data/
pub const ID_MAX: usize = 64;
pub const STAT_TYPES: [&str; 2] = ["int", "float"];
pub const PRESENCE_MAX_KEYS: usize = 30; // Steam's rich presence limits (verify)
pub const PRESENCE_MAX_VALUE_BYTES: usize = 255;
pub const CLOUD_MODES: [&str; 2] = ["auto", "api"];
pub const CLOUD_LOCAL_NAMES: [&str; 4] = ["settings.json", STATE_FILE, "telemetry.csv", "log_tail.txt"];
pub const CLOUD_LOCAL_SUFFIXES: [&str; 2] = [".tmp", ".log"];
pub const CLOUD_LOCAL_DIRS: [&str; 3] = ["logs", "crashes", "captures"];
pub const OVERLAY_PAUSE_SCREENS: [&str; 1] = ["play"];
/// "auto" (Steam Auto-Cloud, no code, preferred) or "api" (the adapter writes cloud files itself).
pub const CLOUD_MODE: &str = "auto";

// ---- small rules ----------------------------------------------------------------------------------------------

/// An achievement, stat or presence key name: 1 to 64 ASCII characters, a letter first.
pub fn id_ok(v: &Value) -> bool {
    let Some(s) = v.as_str() else { return false };
    let b = s.as_bytes();
    !b.is_empty()
        && b.len() <= ID_MAX
        && b[0].is_ascii_alphabetic()
        && b.iter().all(|c| c.is_ascii_alphanumeric() || *c == b'_')
}

/// A finite number (a JSON boolean is never one).
fn num_ok(v: &Value) -> bool {
    v.as_f64().is_some_and(f64::is_finite)
}

/// Whole by value, never by type (5.0 is 5).
fn whole(v: &Value) -> bool {
    v.as_f64().is_some_and(|x| x.is_finite() && x.floor() == x)
}

fn ok_for(kind: &str, v: &Value) -> bool {
    if kind == "int" { whole(v) } else { num_ok(v) }
}

fn num(v: &Value) -> f64 {
    v.as_f64().unwrap_or(0.0)
}

/// A stat value as every port stores it: an int stat as an integer, a float stat as a float.
fn stat_value(sdef: &Value, v: f64) -> Value {
    if sdef["type"] == "int" {
        json!(v as i64)
    } else {
        json!(v)
    }
}

fn clamp_stat(sdef: &Value, v: f64) -> f64 {
    let v = v.max(num(&sdef["min"]));
    match sdef["max"].as_f64() {
        Some(hi) => v.min(hi),
        None => v,
    }
}

fn stat_initial(sdef: &Value) -> f64 {
    clamp_stat(sdef, 0.0)
}

/// Python's dict.get(key, default): a key holding null is null, not the default.
fn get(obj: &Value, key: &str, default: Value) -> Value {
    obj.as_object().and_then(|o| o.get(key)).cloned().unwrap_or(default)
}

fn empty_defs() -> Value {
    json!({"version": STATE_VERSION, "stats": [], "achievements": []})
}

/// data/achievements.json text (None or "" = no file) -> (definitions, problems).
pub fn achievements_load(text: Option<&str>) -> (Value, usize) {
    let Some(text) = text.filter(|t| !t.is_empty()) else {
        return (empty_defs(), 0);
    };
    let raw: Value = match serde_json::from_str(text) {
        Ok(v @ Value::Object(_)) => v,
        _ => return (empty_defs(), 1),
    };
    let mut problems = 0;
    let mut stats: Vec<Value> = Vec::new();
    let mut by_id: BTreeMap<String, Value> = BTreeMap::new();
    let raw_stats = match get(&raw, "stats", json!([])) {
        Value::Array(a) => a,
        _ => {
            problems += 1;
            Vec::new()
        }
    };
    for s in &raw_stats {
        let id = get(s, "id", Value::Null);
        let mut ok = s.is_object() && id_ok(&id) && !by_id.contains_key(id.as_str().unwrap_or(""));
        let (kind, lo, hi, inc) = (
            get(s, "type", json!("int")),
            get(s, "min", json!(0)),
            get(s, "max", Value::Null),
            get(s, "increment_only", json!(false)),
        );
        if ok {
            let k = kind.as_str().unwrap_or("");
            ok = STAT_TYPES.contains(&k)
                && ok_for(k, &lo)
                && (hi.is_null() || (ok_for(k, &hi) && num(&hi) >= num(&lo)))
                && inc.is_boolean();
        }
        if !ok {
            problems += 1;
            continue;
        }
        let is_int = kind == "int";
        let conv = |x: &Value| if is_int { json!(num(x) as i64) } else { json!(num(x)) };
        let sdef = json!({"id": id, "type": kind, "min": conv(&lo),
                          "max": if hi.is_null() { Value::Null } else { conv(&hi) }, "increment_only": inc});
        by_id.insert(id.as_str().unwrap_or("").to_string(), sdef.clone());
        stats.push(sdef);
    }
    let mut achievements: Vec<Value> = Vec::new();
    let raw_ach = match get(&raw, "achievements", json!([])) {
        Value::Array(a) => a,
        _ => {
            problems += 1;
            Vec::new()
        }
    };
    let mut seen: Vec<String> = Vec::new();
    for a in &raw_ach {
        let id = get(a, "id", Value::Null);
        let name = get(a, "name", Value::Null);
        let mut ok = a.is_object()
            && id_ok(&id)
            && !seen.iter().any(|x| Some(x.as_str()) == id.as_str())
            && name.as_str().is_some_and(|n| !n.is_empty())
            && get(a, "description", json!("")).is_string();
        let (stat, threshold, every) = (
            get(a, "stat", Value::Null),
            get(a, "threshold", Value::Null),
            get(a, "progress_every", Value::Null),
        );
        let sdef = stat.as_str().and_then(|s| by_id.get(s)).cloned();
        if ok && !stat.is_null() {
            ok = match &sdef {
                None => false,
                Some(sd) => {
                    let k = sd["type"].as_str().unwrap_or("float");
                    ok_for(k, &threshold)
                        && num(&threshold) > stat_initial(sd)
                        && (sd["max"].is_null() || num(&threshold) <= num(&sd["max"]))
                        && (every.is_null()
                            || (ok_for(k, &every) && num(&every) > 0.0 && num(&every) < num(&threshold)))
                }
            };
        } else if ok {
            ok = threshold.is_null() && every.is_null(); // a threshold without a stat is a mistake
        }
        if !ok {
            problems += 1;
            continue;
        }
        seen.push(id.as_str().unwrap_or("").to_string());
        let (threshold, every) = match &sdef {
            Some(sd) if !stat.is_null() => (
                stat_value(sd, num(&threshold)),
                if every.is_null() {
                    Value::Null
                } else {
                    stat_value(sd, num(&every))
                },
            ),
            _ => (Value::Null, Value::Null),
        };
        achievements.push(
            json!({"id": id, "name": name, "description": get(a, "description", json!("")),
                                 "stat": stat, "threshold": threshold, "progress_every": every}),
        );
    }
    (
        json!({"version": STATE_VERSION, "stats": stats, "achievements": achievements}),
        problems,
    )
}

/// Which user-data file syncs: "cloud" or "local" (ASCII-only folding, never a locale's lowercase).
pub fn cloud_partition(path: &str) -> &'static str {
    let folded = path.to_ascii_lowercase().replace('\\', "/");
    let parts: Vec<&str> = folded.split('/').filter(|p| !p.is_empty() && *p != ".").collect();
    let Some(name) = parts.last() else { return "local" };
    if (parts.len() > 1 && CLOUD_LOCAL_DIRS.contains(&parts[0]))
        || CLOUD_LOCAL_NAMES.contains(name)
        || CLOUD_LOCAL_SUFFIXES.iter().any(|s| name.ends_with(s))
    {
        return "local";
    }
    "cloud"
}

/// The store overlay opened (active) or closed over `screen`: "pause" opens the pause menu; closing never resumes.
pub fn overlay_action(active: bool, screen: &str) -> &'static str {
    if active && OVERLAY_PAUSE_SCREENS.contains(&screen) {
        "pause"
    } else {
        "none"
    }
}

// ---- the backend --------------------------------------------------------------------------------------------

/// The backend interface (PLATFORM.md section 4). send returns false only for a store_stats the store refused.
pub trait Backend: Send + Sync {
    fn name(&self) -> &str;
    fn available(&mut self) -> bool;
    /// {"unlocked": [...], "stats": {...}} as the store holds them.
    fn remote(&mut self) -> Value;
    fn send(&mut self, call: &Value) -> bool;
    /// Each frame: run the SDK's callbacks. Some(active) when the store overlay opened or closed.
    fn update(&mut self) -> Option<bool> {
        None
    }
}

impl Backend for Box<dyn Backend> {
    fn name(&self) -> &str {
        (**self).name()
    }
    fn available(&mut self) -> bool {
        (**self).available()
    }
    fn remote(&mut self) -> Value {
        (**self).remote()
    }
    fn send(&mut self, call: &Value) -> bool {
        (**self).send(call)
    }
    fn update(&mut self) -> Option<bool> {
        (**self).update()
    }
}

/// The backend every game runs by default: records every call and keeps what a store would hold.
#[derive(Debug, Default)]
pub struct NullBackend {
    pub calls: Vec<Value>,
    pub unlocked: Vec<String>,
    pub stats: Map<String, Value>,
    pub presence: BTreeMap<String, String>,
    pub cloud: Vec<String>,
    /// Test hook: the next N store_stats fail (a failed store lands nothing).
    pub fail_stores: usize,
    staged_unlocks: Vec<String>,
    staged_stats: Map<String, Value>,
}

impl NullBackend {
    pub fn presence_list(&self) -> Value {
        json!(self.presence.iter().map(|(k, v)| json!([k, v])).collect::<Vec<_>>())
    }
}

impl Backend for NullBackend {
    fn name(&self) -> &str {
        "null"
    }
    fn available(&mut self) -> bool {
        true
    }
    fn remote(&mut self) -> Value {
        json!({"unlocked": self.unlocked, "stats": self.stats})
    }
    fn send(&mut self, call: &Value) -> bool {
        self.calls.push(call.clone());
        let arg = |n: usize| call.get(n).and_then(Value::as_str).unwrap_or("").to_string();
        match call[0].as_str().unwrap_or("") {
            "set_achievement" => {
                let id = arg(1);
                if !self.staged_unlocks.contains(&id) {
                    self.staged_unlocks.push(id);
                }
            }
            "set_stat" => {
                self.staged_stats.insert(arg(1), call[2].clone());
            }
            "store_stats" => {
                if self.fail_stores > 0 {
                    self.fail_stores -= 1;
                    return false;
                }
                for u in std::mem::take(&mut self.staged_unlocks) {
                    if !self.unlocked.contains(&u) {
                        self.unlocked.push(u);
                    }
                }
                for (k, v) in std::mem::take(&mut self.staged_stats) {
                    self.stats.insert(k, v);
                }
            }
            "reset_all_stats" => {
                self.unlocked.clear();
                self.stats.clear();
                self.staged_unlocks.clear();
                self.staged_stats.clear();
            }
            "set_presence" => {
                let (k, v) = (arg(1), arg(2));
                if v.is_empty() {
                    self.presence.remove(&k);
                } else {
                    self.presence.insert(k, v);
                }
            }
            "clear_presence" => self.presence.clear(),
            "cloud_write" => {
                let p = arg(1);
                if !self.cloud.contains(&p) {
                    self.cloud.push(p);
                }
            }
            _ => {}
        }
        true
    }
}

// ---- the rules ----------------------------------------------------------------------------------------------

/// A status word and the calls sent during the operation, in order.
pub type Out = (&'static str, Vec<Value>);

/// PLATFORM.md section 3.
pub struct Platform<B: Backend> {
    pub defs: Value,
    pub backend: B,
    pub online: bool,
    pub cloud: String,
    pub unlocked: Vec<String>,
    pub stats: BTreeMap<String, Value>,
    pub pending_stats: Vec<String>,
    pub pending_unlocks: Vec<String>,
    pub pending_cloud: Vec<String>,
    pub presence: BTreeMap<String, String>,
    sent: Vec<Value>,
}

impl<B: Backend> Platform<B> {
    pub fn new(defs: Value, backend: B, online: bool, cloud: &str) -> Self {
        let mut p = Platform {
            defs,
            backend,
            online,
            cloud: cloud.to_string(),
            unlocked: Vec::new(),
            stats: BTreeMap::new(),
            pending_stats: Vec::new(),
            pending_unlocks: Vec::new(),
            pending_cloud: Vec::new(),
            presence: BTreeMap::new(),
            sent: Vec::new(),
        };
        p.reset_local();
        p
    }

    fn stat_defs(&self) -> Vec<Value> {
        self.defs["stats"].as_array().cloned().unwrap_or_default()
    }

    fn ach_defs(&self) -> Vec<Value> {
        self.defs["achievements"].as_array().cloned().unwrap_or_default()
    }

    fn stat_def(&self, id: &str) -> Option<Value> {
        self.stat_defs().into_iter().find(|s| s["id"] == id)
    }

    pub fn has_achievement(&self, id: &str) -> bool {
        self.ach_defs().iter().any(|a| a["id"] == id)
    }

    fn reset_local(&mut self) {
        self.unlocked.clear();
        self.stats = self
            .stat_defs()
            .iter()
            .map(|s| {
                (
                    s["id"].as_str().unwrap_or("").to_string(),
                    stat_value(s, stat_initial(s)),
                )
            })
            .collect();
        self.pending_stats.clear();
        self.pending_unlocks.clear();
        self.pending_cloud.clear();
    }

    /// What the state file holds (and what the golden steps compare).
    pub fn state(&self) -> Value {
        let ps: Vec<String> = self
            .stat_defs()
            .iter()
            .filter_map(|s| s["id"].as_str())
            .filter(|id| self.pending_stats.iter().any(|p| p == id))
            .map(String::from)
            .collect();
        json!({"format": FORMAT, "version": STATE_VERSION, "unlocked": self.unlocked, "stats": self.stats,
               "pending": {"stats": ps, "unlocks": self.pending_unlocks, "cloud": self.pending_cloud}})
    }

    /// Takes over a loaded state (platform_state_load's), e.g. at start.
    pub fn restore(&mut self, st: &Value) {
        let strings = |v: &Value| {
            v.as_array()
                .map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect())
                .unwrap_or_default()
        };
        self.unlocked = strings(&st["unlocked"]);
        if let Some(o) = st["stats"].as_object() {
            for (k, v) in o {
                self.stats.insert(k.clone(), v.clone());
            }
        }
        self.pending_stats = strings(&st["pending"]["stats"]);
        self.pending_unlocks = strings(&st["pending"]["unlocks"]);
        self.pending_cloud = strings(&st["pending"]["cloud"]);
    }

    /// The presence map as [[key, value], ...], keys sorted.
    pub fn presence_list(&self) -> Value {
        json!(self.presence.iter().map(|(k, v)| json!([k, v])).collect::<Vec<_>>())
    }

    fn send(&mut self, call: Value) -> bool {
        let ok = self.backend.send(&call);
        self.sent.push(call);
        ok
    }

    fn done(&mut self, out: &'static str) -> Out {
        (out, std::mem::take(&mut self.sent))
    }

    fn unlock_local(&mut self, id: &str) {
        self.unlocked.push(id.to_string());
        self.pending_unlocks.push(id.to_string());
    }

    pub fn unlock(&mut self, id: &str) -> Out {
        if !self.has_achievement(id) {
            return self.done("unknown");
        }
        if self.unlocked.iter().any(|u| u == id) {
            return self.done("already");
        }
        self.unlock_local(id);
        if self.online {
            self.flush_inner();
        }
        self.done("unlocked")
    }

    fn check(&mut self, sid: &str, old: f64, now: f64, notify: bool) -> bool {
        let mut did = false;
        for a in self.ach_defs() {
            let id = a["id"].as_str().unwrap_or("").to_string();
            if a["stat"] != sid || self.unlocked.contains(&id) {
                continue;
            }
            if now >= num(&a["threshold"]) {
                self.unlock_local(&id);
                did = true;
            } else if notify && self.online && !a["progress_every"].is_null() {
                let step = num(&a["progress_every"]);
                if (now / step).floor() > (old / step).floor() {
                    let value = self.stats[sid].clone();
                    self.send(json!(["indicate_progress", id, value, a["threshold"]]));
                }
            }
        }
        did
    }

    /// v may be anything a caller (or a JSON file) passes: a non-number is refused, never coerced.
    pub fn set_stat(&mut self, id: &str, v: &Value) -> Out {
        let Some(s) = self.stat_def(id) else {
            return self.done("unknown");
        };
        if !ok_for(s["type"].as_str().unwrap_or(""), v) {
            return self.done("refused");
        }
        let c = clamp_stat(&s, num(v));
        let old = num(&self.stats[id]);
        if s["increment_only"] == true && c < old {
            return self.done("refused");
        }
        if c == old {
            return self.done("same");
        }
        self.stats.insert(id.to_string(), stat_value(&s, c));
        if !self.pending_stats.iter().any(|p| p == id) {
            self.pending_stats.push(id.to_string());
        }
        if self.check(id, old, c, true) && self.online {
            self.flush_inner();
        }
        self.done(if c != num(v) { "clamped" } else { "ok" })
    }

    pub fn add_stat(&mut self, id: &str, d: &Value) -> Out {
        let Some(s) = self.stat_def(id) else {
            return self.done("unknown");
        };
        if !ok_for(s["type"].as_str().unwrap_or(""), d) {
            return self.done("refused");
        }
        let sum = num(&self.stats[id]) + num(d);
        self.set_stat(id, &json!(sum))
    }

    fn flush_inner(&mut self) -> &'static str {
        if !self.online {
            return "offline";
        }
        if self.pending_stats.is_empty() && self.pending_unlocks.is_empty() && self.pending_cloud.is_empty() {
            return "nothing";
        }
        if !self.pending_stats.is_empty() || !self.pending_unlocks.is_empty() {
            for s in self.stat_defs() {
                let id = s["id"].as_str().unwrap_or("").to_string();
                if self.pending_stats.contains(&id) {
                    let value = self.stats[&id].clone();
                    self.send(json!(["set_stat", id, value]));
                }
            }
            for id in self.pending_unlocks.clone() {
                self.send(json!(["set_achievement", id]));
            }
            if !self.send(json!(["store_stats"])) {
                self.online = false; // the store said no: keep everything, wait for connect()
                return "failed";
            }
            self.pending_stats.clear();
            self.pending_unlocks.clear();
        }
        for p in std::mem::take(&mut self.pending_cloud) {
            self.send(json!(["cloud_write", p]));
        }
        "sent"
    }

    pub fn flush(&mut self) -> Out {
        let out = self.flush_inner();
        self.done(out)
    }

    pub fn set_presence(&mut self, key: &Value, value: &Value) -> Out {
        let (Some(v), true) = (value.as_str(), id_ok(key)) else {
            return self.done("refused");
        };
        if v.len() > PRESENCE_MAX_VALUE_BYTES {
            return self.done("refused"); // bytes: a Rust str is UTF-8
        }
        let k = key.as_str().unwrap_or("").to_string();
        if v.is_empty() {
            if self.presence.remove(&k).is_none() {
                return self.done("same");
            }
        } else {
            match self.presence.get(&k) {
                Some(old) if old == v => return self.done("same"),
                None if self.presence.len() >= PRESENCE_MAX_KEYS => return self.done("refused"),
                _ => {
                    self.presence.insert(k.clone(), v.to_string());
                }
            }
        }
        if self.online {
            self.send(json!(["set_presence", k, v]));
        }
        self.done("ok")
    }

    pub fn clear_presence(&mut self) -> Out {
        if self.presence.is_empty() {
            return self.done("same");
        }
        self.presence.clear();
        if self.online {
            self.send(json!(["clear_presence"]));
        }
        self.done("ok")
    }

    /// The save code calls this after its atomic write succeeded; path is relative to the user-data folder.
    pub fn saved(&mut self, path: &str) -> Out {
        let part = cloud_partition(path);
        if part == "cloud" && self.cloud == "api" {
            if self.online {
                self.send(json!(["cloud_write", path]));
            } else if !self.pending_cloud.iter().any(|p| p == path) {
                self.pending_cloud.push(path.to_string());
            }
        }
        self.done(part)
    }

    pub fn connect(&mut self, remote: &Value) -> Out {
        self.online = true;
        if let Some(ru) = remote.get("unlocked").and_then(Value::as_array) {
            for id in ru.iter().filter_map(Value::as_str) {
                if self.has_achievement(id) && !self.unlocked.iter().any(|u| u == id) {
                    self.unlocked.push(id.to_string());
                }
                if let Some(i) = self.pending_unlocks.iter().position(|u| u == id) {
                    self.pending_unlocks.remove(i);
                }
            }
        }
        let rs = remote
            .get("stats")
            .filter(|v| v.is_object())
            .cloned()
            .unwrap_or(json!({}));
        for s in self.stat_defs() {
            let sid = s["id"].as_str().unwrap_or("").to_string();
            let r0 = rs.get(&sid).cloned().unwrap_or(Value::Null);
            if !ok_for(s["type"].as_str().unwrap_or(""), &r0) {
                continue;
            }
            let r = clamp_stat(&s, num(&r0));
            let old = num(&self.stats[&sid]);
            let pend = self.pending_stats.iter().position(|p| *p == sid);
            let now = if s["increment_only"] == true {
                if let (true, Some(i)) = (r >= old, pend) {
                    self.pending_stats.remove(i);
                }
                old.max(r)
            } else if pend.is_some() {
                old
            } else {
                r
            };
            self.stats.insert(sid.clone(), stat_value(&s, now));
            self.check(&sid, old, now, false);
        }
        self.flush_inner();
        if self.online {
            for (k, v) in self.presence.clone() {
                self.send(json!(["set_presence", k, v]));
            }
        }
        let out = if self.online { "online" } else { "failed" };
        self.done(out)
    }

    pub fn disconnect(&mut self) -> Out {
        self.online = false;
        self.done("offline")
    }

    /// Testing only: refused offline (a reset is never queued).
    pub fn reset_all(&mut self) -> Out {
        if !self.online {
            return self.done("offline");
        }
        self.reset_local();
        self.send(json!(["reset_all_stats", true]));
        self.done("reset")
    }
}

/// platform_state.json text (None or "" = no file) -> (state, problems).
pub fn platform_state_load(defs: &Value, text: Option<&str>) -> (Value, usize) {
    let mut p = Platform::new(defs.clone(), NullBackend::default(), false, "auto");
    let Some(text) = text.filter(|t| !t.is_empty()) else {
        return (p.state(), 0);
    };
    let raw: Value = match serde_json::from_str(text) {
        Ok(v @ Value::Object(_)) => v,
        _ => return (p.state(), 1),
    };
    if raw["format"] != FORMAT || !whole(&raw["version"]) || num(&raw["version"]) != STATE_VERSION as f64 {
        return (p.state(), 1);
    }
    let mut problems = 0;
    let mut items = |v: &Value, array: bool| -> Value {
        if (array && v.is_array()) || (!array && v.is_object()) {
            return v.clone();
        }
        if !v.is_null() {
            problems += 1;
        }
        if array { json!([]) } else { json!({}) }
    };
    let unlocked = items(&raw["unlocked"], true);
    let stats = items(&raw["stats"], false);
    let pending = items(&raw["pending"], false);
    let (ps, pu, pc) = (
        items(&pending["stats"], true),
        items(&pending["unlocks"], true),
        items(&pending["cloud"], true),
    );
    for id in unlocked.as_array().into_iter().flatten() {
        match id.as_str() {
            Some(s) if p.has_achievement(s) && !p.unlocked.iter().any(|u| u == s) => p.unlocked.push(s.to_string()),
            _ => problems += 1,
        }
    }
    for (sid, v) in stats.as_object().into_iter().flatten() {
        match p.stat_def(sid) {
            Some(s) if ok_for(s["type"].as_str().unwrap_or(""), v) => {
                p.stats.insert(sid.clone(), stat_value(&s, clamp_stat(&s, num(v))));
            }
            _ => problems += 1,
        }
    }
    for id in ps.as_array().into_iter().flatten() {
        match id.as_str() {
            Some(s) if p.stat_def(s).is_some() && !p.pending_stats.iter().any(|x| x == s) => {
                p.pending_stats.push(s.to_string())
            }
            _ => problems += 1,
        }
    }
    for id in pu.as_array().into_iter().flatten() {
        match id.as_str() {
            Some(s) if p.unlocked.iter().any(|u| u == s) && !p.pending_unlocks.iter().any(|x| x == s) => {
                p.pending_unlocks.push(s.to_string())
            }
            _ => problems += 1,
        }
    }
    for path in pc.as_array().into_iter().flatten() {
        match path.as_str() {
            Some(s) if cloud_partition(s) == "cloud" && !p.pending_cloud.iter().any(|x| x == s) => {
                p.pending_cloud.push(s.to_string())
            }
            _ => problems += 1,
        }
    }
    (p.state(), problems)
}

// ---- the service the shell owns ------------------------------------------------------------------------------

/// The rules, the backend and the cached state file (shell.platform).
pub struct PlatformService {
    pub rules: Platform<Box<dyn Backend>>,
    /// False without data/achievements.json (or with an empty one): nothing is ever written.
    pub active: bool,
    file: PathBuf,
    last: String,
}

impl PlatformService {
    /// achievements: data/achievements.json's text (None = no file). backend: None = a NullBackend.
    pub fn new(data_dir: &Path, achievements: Option<&str>, backend: Option<Box<dyn Backend>>, cloud: &str) -> Self {
        let (defs, problems) = achievements_load(achievements);
        if problems > 0 {
            eprintln!("[WARN] platform: data/achievements.json: {problems} problem(s), those entries were dropped");
        }
        let active = !defs["stats"].as_array().is_none_or(Vec::is_empty)
            || !defs["achievements"].as_array().is_none_or(Vec::is_empty);
        let file = data_dir.join(STATE_FILE);
        let backend = backend.unwrap_or_else(|| Box::new(NullBackend::default()));
        let mut rules = Platform::new(defs, backend, false, cloud);
        let mut last = String::new();
        if active {
            let text = atomic_file::read_text(&file).ok().flatten();
            let (st, n) = platform_state_load(&rules.defs, text.as_deref());
            if n > 0 {
                eprintln!("[WARN] platform: {STATE_FILE}: {n} problem(s), the store's copy wins");
            }
            rules.restore(&st);
            last = text.unwrap_or_default();
        }
        if rules.backend.available() {
            let remote = rules.backend.remote();
            rules.connect(&remote);
        }
        let mut service = PlatformService {
            rules,
            active,
            file,
            last,
        };
        service.persist();
        service
    }

    fn persist(&mut self) {
        if !self.active {
            return;
        }
        let text = serde_json::to_string_pretty(&self.rules.state()).unwrap_or_default() + "\n";
        if text == self.last {
            return;
        }
        match atomic_file::write(&self.file, text.as_bytes()) {
            Ok(()) => self.last = text,
            Err(e) => eprintln!("[WARN] platform: {STATE_FILE} not written: {e}"),
        }
    }

    fn after(&mut self, r: Out) -> &'static str {
        self.persist();
        r.0
    }

    pub fn unlock(&mut self, id: &str) -> &'static str {
        let r = self.rules.unlock(id);
        self.after(r)
    }
    pub fn set_stat(&mut self, id: &str, v: f64) -> &'static str {
        let r = self.rules.set_stat(id, &json!(v));
        self.after(r)
    }
    pub fn add_stat(&mut self, id: &str, d: f64) -> &'static str {
        let r = self.rules.add_stat(id, &json!(d));
        self.after(r)
    }
    /// At checkpoints: level end, pause, quit.
    pub fn flush(&mut self) -> &'static str {
        let r = self.rules.flush();
        self.after(r)
    }
    pub fn set_presence(&mut self, key: &str, value: &str) -> &'static str {
        let r = self.rules.set_presence(&json!(key), &json!(value));
        self.after(r)
    }
    pub fn clear_presence(&mut self) -> &'static str {
        let r = self.rules.clear_presence();
        self.after(r)
    }
    /// After an atomic save: its cloud partition (and, in api mode, the cloud write or its queue).
    pub fn saved(&mut self, path: &str) -> &'static str {
        let r = self.rules.saved(path);
        self.after(r)
    }
    /// The store overlay opened or closed over `screen`: "pause" means open the pause menu.
    pub fn overlay(&self, active: bool, screen: &str) -> &'static str {
        overlay_action(active, screen)
    }
    /// Each frame: the backend's callbacks; Some(active) when the store overlay opened or closed.
    pub fn update(&mut self) -> Option<bool> {
        self.rules.backend.update()
    }
}

// {{FOOTER}}
