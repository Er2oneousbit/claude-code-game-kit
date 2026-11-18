// ---------------------------------------------------------------------------
// tests/platform.rs
// Purpose : The platform layer (src/logic/platform.rs) against every case of data/golden/platform.json, then the
//           PlatformService the shell owns: the cached state file, the save hook, nothing written without
//           data/achievements.json.
// Usage   : python tools/dev.py test   (cargo test --test platform -- --nocapture prints the case counts)
// Notes   : A case type this file does not know fails. A step's calls are what the rules sent to their backend
//           during that step; "fail_store" is the null backend's hook (its next store_stats fails). Expected values
//           come only from the JSON. Numbers compare numerically (1 == 1.0), arrays in order, objects as key sets.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::path::{Path, PathBuf};

use serde_json::{Value, json};

use {{GAME_SLUG}}::logic::platform::{self, NullBackend, Platform, PlatformService};
use {{GAME_SLUG}}::logic::platform_steam::{self, SteamApi, SteamBackend};
use {{GAME_SLUG}}::logic::save_store;

const SAMPLE: &str = r#"{"stats": [{"id": "kills", "max": 100, "increment_only": true}], "achievements": [{"id": "first", "name": "First"}, {"id": "kills_10", "name": "Ten", "stat": "kills", "threshold": 10}]}"#;

fn load() -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("data")
        .join("golden")
        .join("platform.json");
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("cannot read {} ({e})", path.display()));
    serde_json::from_str(&text).expect("platform.json is not JSON")
}

fn diff(got: &Value, want: &Value, tol: f64, at: &str) -> Option<String> {
    match (got, want) {
        (Value::Number(g), Value::Number(w)) => {
            let (g, w) = (g.as_f64().unwrap_or(f64::NAN), w.as_f64().unwrap_or(f64::NAN));
            if (g - w).abs() <= tol {
                None
            } else {
                Some(format!("{at}: got {g}, want {w}"))
            }
        }
        (Value::Array(g), Value::Array(w)) if g.len() == w.len() => g
            .iter()
            .zip(w)
            .enumerate()
            .find_map(|(n, (gv, wv))| diff(gv, wv, tol, &format!("{at}[{n}]"))),
        (Value::Object(g), Value::Object(w)) => {
            let mut keys: Vec<&String> = g.keys().chain(w.keys()).collect();
            keys.sort();
            keys.dedup();
            keys.into_iter().find_map(|k| match (g.get(k), w.get(k)) {
                (Some(gv), Some(wv)) => diff(gv, wv, tol, &format!("{at}.{k}")),
                (Some(_), None) => Some(format!("{at}.{k}: extra key")),
                _ => Some(format!("{at}.{k}: missing")),
            })
        }
        _ if got == want => None,
        _ => Some(format!("{at}: got {got}, want {want}")),
    }
}

struct Exam {
    tol: f64,
    failures: Vec<String>,
    checked: usize,
}

impl Exam {
    fn check(&mut self, what: &str, got: Value, want: &Value) {
        self.checked += 1;
        if let Some(d) = diff(&got, want, self.tol, what) {
            self.failures.push(d);
        }
    }
}

fn text(v: &Value) -> Option<&str> {
    v.as_str()
}

fn step(p: &mut Platform<NullBackend>, op: &Value) -> (Value, Value) {
    let a = |n: usize| &op[n];
    let s = |n: usize| op[n].as_str().unwrap_or("").to_string();
    let r = match op[0].as_str().unwrap_or("") {
        "fail_store" => {
            p.backend.fail_stores += 1;
            return (Value::Null, json!([]));
        }
        "overlay" => {
            return (
                json!(platform::overlay_action(
                    a(1).as_bool().unwrap_or(false),
                    a(2).as_str().unwrap_or("")
                )),
                json!([]),
            );
        }
        "unlock" => p.unlock(&s(1)),
        "set_stat" => p.set_stat(&s(1), a(2)),
        "add_stat" => p.add_stat(&s(1), a(2)),
        "flush" => p.flush(),
        "set_presence" => p.set_presence(a(1), a(2)),
        "clear_presence" => p.clear_presence(),
        "saved" => p.saved(&s(1)),
        "connect" => p.connect(a(1)),
        "disconnect" => p.disconnect(),
        "reset_all" => p.reset_all(),
        other => panic!("unknown step {other}"),
    };
    (json!(r.0), json!(r.1))
}

fn check_case(case: &Value, exam: &mut Exam) -> bool {
    let name = case["name"].as_str().unwrap_or("");
    match case["type"].as_str().unwrap_or("") {
        "platform_format" => {
            let mut mine = case.clone();
            let m = mine.as_object_mut().expect("an object");
            m.insert("state_format".into(), json!(platform::FORMAT));
            m.insert("state_file".into(), json!(platform::STATE_FILE));
            m.insert("state_version".into(), json!(platform::STATE_VERSION));
            m.insert("id_max".into(), json!(platform::ID_MAX));
            m.insert("stat_types".into(), json!(platform::STAT_TYPES));
            m.insert("presence_max_keys".into(), json!(platform::PRESENCE_MAX_KEYS));
            m.insert(
                "presence_max_value_bytes".into(),
                json!(platform::PRESENCE_MAX_VALUE_BYTES),
            );
            m.insert("cloud_modes".into(), json!(platform::CLOUD_MODES));
            m.insert("cloud_local_names".into(), json!(platform::CLOUD_LOCAL_NAMES));
            m.insert("cloud_local_suffixes".into(), json!(platform::CLOUD_LOCAL_SUFFIXES));
            m.insert("cloud_local_dirs".into(), json!(platform::CLOUD_LOCAL_DIRS));
            m.insert("overlay_pause_screens".into(), json!(platform::OVERLAY_PAUSE_SCREENS));
            exam.check("format", mine, case);
        }
        "achievements_load" => {
            for p in case["points"].as_array().into_iter().flatten() {
                let (defs, problems) = platform::achievements_load(text(&p[1]));
                exam.check(&format!("{} {}: defs", name, p[0]), defs, &p[2]);
                exam.check(&format!("{} {}: problems", name, p[0]), json!(problems), &p[3]);
            }
        }
        "cloud_partition" => {
            for p in case["points"].as_array().into_iter().flatten() {
                exam.check(
                    &format!("{:?}", p[0]),
                    json!(platform::cloud_partition(p[0].as_str().unwrap_or(""))),
                    &p[1],
                );
            }
        }
        "overlay" => {
            for p in case["points"].as_array().into_iter().flatten() {
                let got = platform::overlay_action(p[0].as_bool().unwrap_or(false), p[1].as_str().unwrap_or(""));
                exam.check(&format!("{p}"), json!(got), &p[2]);
            }
        }
        "platform_script" => {
            let mut p = Platform::new(
                case["defs"].clone(),
                NullBackend::default(),
                case["online"].as_bool().unwrap_or(false),
                case["cloud"].as_str().unwrap_or("auto"),
            );
            for (n, s) in case["steps"].as_array().into_iter().flatten().enumerate() {
                let (out, calls) = step(&mut p, &s["op"]);
                let w = format!("{name} step {n} {}", s["op"]);
                exam.check(&format!("{w}: out"), out, &s["out"]);
                exam.check(&format!("{w}: calls"), calls, &s["calls"]);
                exam.check(&format!("{w}: state"), p.state(), &s["state"]);
                exam.check(&format!("{w}: presence"), p.presence_list(), &s["presence"]);
                exam.check(&format!("{w}: online"), json!(p.online), &s["online"]);
            }
        }
        "platform_state_load" => {
            for p in case["points"].as_array().into_iter().flatten() {
                let (state, problems) = platform::platform_state_load(&case["defs"], text(&p[1]));
                exam.check(&format!("{}: state", p[0]), state, &p[2]);
                exam.check(&format!("{}: problems", p[0]), json!(problems), &p[3]);
            }
        }
        "null_backend" => {
            use platform::Backend;
            let mut nb = NullBackend::default();
            for (n, s) in case["sends"].as_array().into_iter().flatten().enumerate() {
                let call = &s[0];
                let got = if *call == json!(["fail_next_store"]) {
                    nb.fail_stores += 1;
                    Value::Null
                } else {
                    json!(nb.send(call))
                };
                let w = format!("send {n} {call}");
                exam.check(&format!("{w}: ok"), got, &s[1]);
                exam.check(&format!("{w}: remote"), nb.remote(), &s[2]);
                exam.check(&format!("{w}: presence"), nb.presence_list(), &s[3]);
                exam.check(&format!("{w}: cloud"), json!(nb.cloud), &s[4]);
            }
            exam.check("calls", json!(nb.calls), &case["calls"]);
        }
        _ => return false,
    }
    true
}

#[test]
fn every_platform_case_matches_the_reference() {
    let doc = load();
    let mut exam = Exam {
        tol: doc["tolerance"].as_f64().unwrap_or(1e-9),
        failures: Vec::new(),
        checked: 0,
    };
    let mut cases = 0;
    for case in doc["cases"].as_array().expect("cases") {
        assert!(
            check_case(case, &mut exam),
            "unknown case type {}: port it, then add it here",
            case["type"]
        );
        cases += 1;
    }
    println!("platform.json: {cases} case(s), {} value(s) checked", exam.checked);
    assert!(cases >= 19, "platform.json has only {cases} cases");
    assert!(
        exam.failures.is_empty(),
        "{} mismatch(es)\n{}",
        exam.failures.len(),
        exam.failures.join("\n")
    );
}

struct Temp(PathBuf);
impl Temp {
    fn new(tag: &str) -> Temp {
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let p = std::env::temp_dir().join(format!("gamekit-platform-\u{cd}-{tag}-{stamp}"));
        std::fs::create_dir_all(&p).expect("temp dir");
        Temp(p)
    }
}
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[test]
fn the_service_writes_nothing_without_achievements() {
    let dir = Temp::new("none");
    let mut ps = PlatformService::new(&dir.0, None, None, "auto");
    assert!(!ps.active);
    assert_eq!(ps.unlock("first"), "unknown");
    assert_eq!(ps.flush(), "nothing");
    assert_eq!(ps.saved("save_1.json"), "cloud");
    assert_eq!(std::fs::read_dir(&dir.0).map(|d| d.count()).unwrap_or(1), 0);
}

#[test]
fn the_service_caches_its_state_file() {
    let dir = Temp::new("cache");
    {
        let mut ps = PlatformService::new(&dir.0, Some(SAMPLE), None, "auto");
        assert_eq!(ps.add_stat("kills", 12.0), "ok");
        assert_eq!(ps.unlock("first"), "unlocked");
    }
    let mut again = PlatformService::new(&dir.0, Some(SAMPLE), None, "auto");
    assert_eq!(again.rules.unlocked, vec!["kills_10".to_string(), "first".to_string()]);
    assert_eq!(again.unlock("first"), "already");
    assert!(!dir.0.join("platform_state.json.tmp").exists());
}

#[test]
fn a_save_reaches_saved_once_it_is_on_disk() {
    let dir = Temp::new("save");
    let mut ps = PlatformService::new(&dir.0, Some(SAMPLE), None, "api");
    let mut seen = Vec::new();
    save_store::write_then(&dir.0.join("save_1.json"), &json!({"level": 1}), |name| {
        seen.push(name.to_string());
        ps.saved(name);
    })
    .expect("saved");
    assert_eq!(seen, vec!["save_1.json".to_string()]);
    let calls: Vec<String> = ps.rules.state()["pending"]["cloud"]
        .as_array()
        .map(|a| a.iter().map(|v| v.to_string()).collect())
        .unwrap_or_default();
    assert!(calls.is_empty(), "online: written at once, nothing queued");
}

// ---- the Steam backend over a fake SteamApi (no SDK, no Steam) ---------------------------------------------

#[derive(Clone, Default)]
struct FakeSteam {
    log: std::sync::Arc<std::sync::Mutex<Vec<String>>>,
    store_ok: std::sync::Arc<std::sync::Mutex<bool>>,
}

impl FakeSteam {
    fn push(&self, s: String) {
        self.log.lock().unwrap().push(s);
    }
}

impl SteamApi for FakeSteam {
    fn set_achievement(&mut self, id: &str) -> bool {
        self.push(format!("SetAchievement {id}"));
        true
    }
    fn achieved(&mut self, id: &str) -> Option<bool> {
        Some(id == "first")
    }
    fn set_stat_int(&mut self, id: &str, v: i32) -> bool {
        self.push(format!("SetStat {id} {v}"));
        true
    }
    fn set_stat_float(&mut self, id: &str, _v: f32) -> bool {
        self.push(format!("SetStatF {id}"));
        true
    }
    fn stat_int(&mut self, _id: &str) -> Option<i32> {
        Some(4)
    }
    fn stat_float(&mut self, _id: &str) -> Option<f32> {
        Some(0.0)
    }
    fn store_stats(&mut self) -> bool {
        self.push("StoreStats".into());
        *self.store_ok.lock().unwrap()
    }
    fn indicate_progress(&mut self, id: &str, current: u32, max: u32) -> bool {
        self.push(format!("Indicate {id} {current} {max}"));
        true
    }
    fn reset_all_stats(&mut self, _achievements: bool) -> bool {
        true
    }
    fn set_rich_presence(&mut self, key: &str, value: &str) -> bool {
        self.push(format!("SetRichPresence {key} {value}"));
        true
    }
    fn clear_rich_presence(&mut self) {}
    fn file_write(&mut self, name: &str, _bytes: &[u8]) -> bool {
        self.push(format!("FileWrite {name}"));
        true
    }
    fn run_callbacks(&mut self) {
        self.push("RunCallbacks".into());
    }
}

#[test]
fn the_steam_backend_maps_calls_and_a_refused_store() {
    let dir = Temp::new("steam");
    let fake = FakeSteam::default();
    *fake.store_ok.lock().unwrap() = true;
    let defs = platform::achievements_load(Some(SAMPLE)).0;
    let mut backend = SteamBackend::new(defs, dir.0.clone(), Box::new(fake.clone()));
    {
        use platform::Backend;
        assert_eq!(backend.remote(), json!({"unlocked": ["first"], "stats": {"kills": 4}}));
    }
    let overlay = backend.overlay.clone();
    let mut ps = PlatformService::new(&dir.0, Some(SAMPLE), Some(Box::new(backend)), "auto");
    assert_eq!(ps.add_stat("kills", 12.0), "ok"); // the store had 4: 16, and kills_10 unlocks
    assert_eq!(
        *fake.log.lock().unwrap(),
        vec!["SetStat kills 16", "SetAchievement kills_10", "StoreStats"]
    );
    fake.log.lock().unwrap().clear();
    *fake.store_ok.lock().unwrap() = false;
    assert_eq!(ps.set_stat("kills", 20.0), "ok");
    assert_eq!(ps.flush(), "failed");
    assert!(!ps.rules.online, "a refused StoreStats takes the layer offline");
    *overlay.lock().unwrap() = Some(true);
    assert_eq!(ps.update(), Some(true), "the overlay reaches the shell once");
    assert_eq!(ps.update(), None);
    assert_eq!(
        fake.log.lock().unwrap().last().map(String::as_str),
        Some("RunCallbacks")
    );
}

#[test]
fn an_enabled_steam_backend_starts_without_achievements() {
    // docs/PLATFORM.md section 6: Steam starts whether or not data/achievements.json exists
    let dir = Temp::new("noach");
    let fake = FakeSteam::default();
    let none = platform::achievements_load(None).0;
    let backend = platform_steam::make_with(&none, &dir.0, false, || {
        Some(Box::new(fake.clone()) as Box<dyn SteamApi>)
    });
    assert!(backend.is_some(), "no achievements file: Steam still starts");
    let mut ps = PlatformService::new(&dir.0, None, Some(Box::new(backend.unwrap())), "auto");
    assert_eq!(ps.set_presence("status", "Menu"), "ok");
    assert_eq!(*fake.log.lock().unwrap(), vec!["SetRichPresence status Menu"]);
    assert!(
        platform_steam::make_with(&none, &dir.0, false, || None).is_none(),
        "Steam did not start: null"
    );
    assert!(
        platform_steam::make_with(
            &none,
            &dir.0,
            true,
            || Some(Box::new(fake.clone()) as Box<dyn SteamApi>)
        )
        .is_none()
    );
}

#[test]
fn a_late_user_stats_stored_failure_requeues_the_store() {
    let dir = Temp::new("late");
    let fake = FakeSteam::default();
    *fake.store_ok.lock().unwrap() = true;
    let defs = platform::achievements_load(Some(SAMPLE)).0;
    let backend = SteamBackend::new(defs, dir.0.clone(), Box::new(fake.clone()));
    let stored = backend.stored.clone();
    let mut ps = PlatformService::new(&dir.0, Some(SAMPLE), Some(Box::new(backend)), "auto");
    assert_eq!(ps.add_stat("kills", 12.0), "ok"); // the store had 4: 16, kills_10 unlocks and flushes
    assert!(ps.rules.online);
    stored.lock().unwrap().push(false); // UserStatsStored: failed
    ps.update();
    assert!(!ps.rules.online, "a late failure takes the layer offline");
    assert_eq!(
        ps.rules.state()["pending"],
        json!({"stats": ["kills"], "unlocks": ["kills_10"], "cloud": []})
    );
    fake.log.lock().unwrap().clear();
    ps.rules.connect(&json!({}));
    assert_eq!(
        *fake.log.lock().unwrap(),
        vec!["SetStat kills 16", "SetAchievement kills_10", "StoreStats"]
    );
    stored.lock().unwrap().push(true);
    ps.update();
    assert!(ps.rules.online);
}

#[test]
fn without_the_steam_feature_or_in_an_automated_run_the_backend_is_null() {
    let dir = Temp::new("nosteam");
    assert!(platform_steam::make(&json!({}), &dir.0, true).is_none());
    if !cfg!(feature = "steam") {
        assert!(platform_steam::make(&json!({}), &dir.0, false).is_none());
    }
}

// {{FOOTER}}
