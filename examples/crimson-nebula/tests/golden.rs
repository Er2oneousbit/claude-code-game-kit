// ---------------------------------------------------------------------------
// tests/golden.rs
// Purpose : The golden-vector exam: every case in data/golden/juice.json and data/golden/shell.json (written by
//           tools/golden_vectors.py, the reference every engine port matches) replayed through src/logic/.
// Usage   : python tools/dev.py test   (cargo test --test golden -- --nocapture also prints the case counts)
// Notes   : One test per case type: it checks every case of that type within the file's tolerance and fails
//           when the file has none. A case type this file does not know fails vector_files_hold_only_known_types,
//           so a new vector type cannot be skipped silently. Expected values come only from the JSON: when the
//           behavior should change, change the reference, run `python tools/golden_vectors.py --write`, then fix
//           src/logic/ until this passes. Numbers compare numerically (1 == 1.0), arrays in order, objects as
//           key sets.
//
// Pseudocode:
//   load the file -> for each case of the type: build the module from "params", replay "steps" (or "points"),
//   compare each result with its "expect" -> collect every mismatch -> fail with the list
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::path::Path;

use serde_json::{Value, json};

use project_crimson_nebula::logic::coyote::Coyote;
use project_crimson_nebula::logic::flash_limiter::FlashLimiter;
use project_crimson_nebula::logic::follow::Follow;
use project_crimson_nebula::logic::hitstop::Hitstop;
use project_crimson_nebula::logic::input_buffer::InputBuffer;
use project_crimson_nebula::logic::shake::{self, Shake};
use project_crimson_nebula::logic::spring::{self, Spring};
use project_crimson_nebula::logic::{bindings, ease, i18n, save_store, settings};

const JUICE: &str = "juice.json";
const SHELL: &str = "shell.json";
const JUICE_TYPES: [&str; 10] = [
    "noise",
    "shake",
    "hitstop",
    "ease",
    "follow",
    "input_buffer",
    "coyote",
    "spring",
    "squash",
    "flash_limiter",
];
const SHELL_TYPES: [&str; 10] = [
    "defaults",
    "settings_load",
    "rebind",
    "glyph_set",
    "glyph_name",
    "prompt_binding",
    "save_load",
    "tr",
    "plural",
    "pseudo",
];
/// The vector file format this exam reads (the files' "version").
const VECTOR_VERSION: i64 = 1;
/// The plural case's points do not name their key; the reference builds them all from this one.
const PLURAL_KEY: &str = "apples";

// ---- Reading the vectors -------------------------------------------------------
fn load(file: &str) -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("data")
        .join("golden")
        .join(file);
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| {
        panic!(
            "cannot read {} ({e}): it ships with the kit, restore it",
            path.display()
        )
    });
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("{} is not JSON: {e}", path.display()))
}

fn arr(v: &Value) -> &Vec<Value> {
    v.as_array().unwrap_or_else(|| panic!("expected an array, got {v}"))
}

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap_or_else(|| panic!("expected a number, got {v}"))
}

/// Whole numbers may arrive as floats (1.0) from other writers: read them through f64.
fn i(v: &Value) -> i64 {
    f(v) as i64
}

fn s(v: &Value) -> &str {
    v.as_str().unwrap_or_else(|| panic!("expected a string, got {v}"))
}

fn b(v: &Value) -> bool {
    v.as_bool().unwrap_or_else(|| panic!("expected true or false, got {v}"))
}

/// Where got and want differ (a JSON path), or None when they match within tol.
fn diff(got: &Value, want: &Value, tol: f64, at: &str) -> Option<String> {
    match (got, want) {
        (Value::Number(g), Value::Number(w)) => {
            let (g, w) = (g.as_f64().unwrap_or(f64::NAN), w.as_f64().unwrap_or(f64::NAN));
            ((g - w).abs() <= tol)
                .then_some(())
                .map_or(Some(format!("{at}: got {g}, want {w}")), |_| None)
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

/// Collects the mismatches of one case type, so a run reports all of them at once.
struct Exam {
    tol: f64,
    case: String,
    failures: Vec<String>,
    checked: usize,
}

impl Exam {
    fn check(&mut self, what: &str, got: Value, want: &Value) {
        self.checked += 1;
        if let Some(d) = diff(&got, want, self.tol, what) {
            self.failures.push(format!("[{}] {d}", self.case));
        }
    }

    fn fail(&mut self, msg: String) {
        self.failures.push(format!("[{}] {msg}", self.case));
    }
}

/// Runs every case of one type and fails with the list of mismatches.
fn run(file: &str, kind: &str) {
    let doc = load(file);
    let mut exam = Exam {
        tol: f(&doc["tolerance"]),
        case: String::new(),
        failures: Vec::new(),
        checked: 0,
    };
    let mut cases = 0;
    for case in arr(&doc["cases"]).iter().filter(|c| c["type"] == kind) {
        exam.case = s(&case["name"]).to_string();
        check_case(kind, case, &mut exam);
        cases += 1;
    }
    println!("{file} {kind}: {cases} case(s), {} value(s) checked", exam.checked);
    assert!(
        cases > 0,
        "{file} has no {kind:?} cases (renamed or removed in the reference?)"
    );
    assert!(
        exam.failures.is_empty(),
        "{kind}: {} mismatch(es) with {file}\n{}",
        exam.failures.len(),
        exam.failures.join("\n")
    );
}

fn check_case(kind: &str, case: &Value, exam: &mut Exam) {
    match kind {
        "noise" => noise(case, exam),
        "shake" => shake_steps(case, exam),
        "hitstop" => hitstop(case, exam),
        "ease" => ease_points(case, exam),
        "follow" => follow(case, exam),
        "input_buffer" => input_buffer(case, exam),
        "coyote" => coyote(case, exam),
        "spring" => spring_steps(case, exam),
        "squash" => squash(case, exam),
        "flash_limiter" => flash_limiter(case, exam),
        "defaults" => exam.check("defaults", settings::defaults(), &case["expect"]),
        "settings_load" => settings_load(case, exam),
        "rebind" => rebind(case, exam),
        "glyph_set" => glyph_set(case, exam),
        "glyph_name" => glyph_name(case, exam),
        "prompt_binding" => prompt_binding(case, exam),
        "save_load" => save_load(case, exam),
        "tr" => tr(case, exam),
        "plural" => plural(case, exam),
        "pseudo" => pseudo(case, exam),
        other => exam.fail(format!("unknown case type {other:?}")),
    }
}

/// (step number, step, its "call") for each scripted step.
fn steps(case: &Value) -> impl Iterator<Item = (usize, &Value, &str)> {
    arr(&case["steps"])
        .iter()
        .enumerate()
        .map(|(n, st)| (n, st, s(&st["call"])))
}

// ---- Juice ---------------------------------------------------------------------
fn noise(case: &Value, exam: &mut Exam) {
    for p in arr(&case["points"]) {
        let p = arr(p);
        let got = shake::noise(i(&p[0]), f(&p[1]), i(&p[2]));
        exam.check(&format!("noise({}, {}, {})", p[0], p[1], p[2]), json!(got), &p[3]);
    }
}

fn shake_steps(case: &Value, exam: &mut Exam) {
    let pr = &case["params"];
    let mut sh = Shake {
        max_offset: f(&pr["max_offset"]),
        max_angle: f(&pr["max_angle"]),
        decay: f(&pr["decay"]),
        frequency: f(&pr["frequency"]),
        seed: i(&pr["seed"]),
        ..Shake::default()
    };
    for (n, st, call) in steps(case) {
        match call {
            "add_trauma" => sh.add_trauma(f(&st["a"])),
            "update" => {
                let (x, y, angle) = sh.update(f(&st["dt"]), f(&st["intensity"]));
                let got = json!({"x": x, "y": y, "angle": angle, "trauma": sh.trauma});
                exam.check(&format!("step {n}"), got, &st["expect"]);
            }
            other => exam.fail(format!("step {n}: unknown call {other:?}")),
        }
    }
}

fn hitstop(case: &Value, exam: &mut Exam) {
    let mut h = Hitstop {
        max_s: f(&case["params"]["max_s"]),
        ..Hitstop::default()
    };
    for (n, st, call) in steps(case) {
        match call {
            "hit" => h.hit(f(&st["duration"])),
            "scaled_dt" => {
                let dt = h.scaled_dt(f(&st["dt"]));
                exam.check(
                    &format!("step {n}"),
                    json!({"dt": dt, "remaining": h.remaining}),
                    &st["expect"],
                );
            }
            other => exam.fail(format!("step {n}: unknown call {other:?}")),
        }
    }
}

fn ease_points(case: &Value, exam: &mut Exam) {
    for p in arr(&case["points"]) {
        let p = arr(p);
        match ease::ease(s(&p[0]), f(&p[1])) {
            Ok(v) => exam.check(&format!("{}({})", p[0], p[1]), json!(v), &p[2]),
            Err(e) => exam.fail(e),
        }
    }
}

fn follow(case: &Value, exam: &mut Exam) {
    let pr = &case["params"];
    let mut cam = Follow {
        deadzone_w: f(&pr["deadzone_w"]),
        deadzone_h: f(&pr["deadzone_h"]),
        lookahead: f(&pr["lookahead"]),
        smoothing: f(&pr["smoothing"]),
        x: f(&pr["x"]),
        y: f(&pr["y"]),
    };
    for (n, st, call) in steps(case) {
        match call {
            "update" => {
                let (x, y) = cam.update(f(&st["dt"]), f(&st["tx"]), f(&st["ty"]), f(&st["vx"]), f(&st["vy"]));
                exam.check(&format!("step {n}"), json!({"x": x, "y": y}), &st["expect"]);
            }
            other => exam.fail(format!("step {n}: unknown call {other:?}")),
        }
    }
}

fn input_buffer(case: &Value, exam: &mut Exam) {
    let mut buf = InputBuffer::new(f(&case["params"]["window_s"]));
    for (n, st, call) in steps(case) {
        match call {
            "press" => buf.press(s(&st["action"])),
            "update" => buf.update(f(&st["dt"])),
            "consume" => {
                let got = buf.consume(s(&st["action"]));
                exam.check(&format!("step {n}"), json!({"result": got}), &st["expect"]);
            }
            other => exam.fail(format!("step {n}: unknown call {other:?}")),
        }
    }
}

fn coyote(case: &Value, exam: &mut Exam) {
    let mut c = Coyote::new(f(&case["params"]["window_s"]));
    for (n, st, call) in steps(case) {
        match call {
            "update" => c.update(f(&st["dt"]), b(&st["on_floor"])),
            "consume" => c.consume(),
            "can_jump" => exam.check(&format!("step {n}"), json!({"result": c.can_jump()}), &st["expect"]),
            other => exam.fail(format!("step {n}: unknown call {other:?}")),
        }
    }
}

fn spring_steps(case: &Value, exam: &mut Exam) {
    let pr = &case["params"];
    let mut sp = Spring {
        frequency: f(&pr["frequency"]),
        damping: f(&pr["damping"]),
        x: f(&pr["x"]),
        v: f(&pr["v"]),
        target: f(&pr["target"]),
    };
    for (n, st, call) in steps(case) {
        match call {
            "update" => {
                let x = sp.update(f(&st["dt"]));
                exam.check(&format!("step {n}"), json!({"x": x, "v": sp.v}), &st["expect"]);
            }
            other => exam.fail(format!("step {n}: unknown call {other:?}")),
        }
    }
}

fn squash(case: &Value, exam: &mut Exam) {
    for p in arr(&case["points"]) {
        let p = arr(p);
        let (sx, sy) = spring::squash(f(&p[0]));
        exam.check(&format!("squash({})", p[0]), json!([sx, sy]), &json!([p[1], p[2]]));
    }
}

fn flash_limiter(case: &Value, exam: &mut Exam) {
    let pr = &case["params"];
    let mut fl = FlashLimiter::new(i(&pr["max_flashes"]) as usize, f(&pr["window_s"]));
    for (n, st, call) in steps(case) {
        match call {
            "request" => {
                let got = fl.request(f(&st["now"]));
                exam.check(&format!("step {n}"), json!({"result": got}), &st["expect"]);
            }
            other => exam.fail(format!("step {n}: unknown call {other:?}")),
        }
    }
}

// ---- Shell ---------------------------------------------------------------------
fn settings_load(case: &Value, exam: &mut Exam) {
    let (loaded, problems) = settings::load(case["input"].as_str());
    let got = json!({
        "settings": loaded,
        "problems": problems.len(),
        "effective_shake": settings::effective_shake(&loaded),
        "telemetry_allowed": settings::telemetry_allowed(&loaded),
    });
    let want = json!({
        "settings": case["expect"],
        "problems": case["problems"],
        "effective_shake": case["effective_shake"],
        "telemetry_allowed": case["telemetry_allowed"],
    });
    exam.check("load", got, &want);
}

fn rebind(case: &Value, exam: &mut Exam) {
    let start = settings::bindings_from_value(&case["bindings"]);
    let slot = i(&case["slot"]) as usize;
    match bindings::rebind(&start, s(&case["action"]), slot, s(&case["binding"])) {
        Ok((out, conflicts)) => {
            let conflicts: Vec<Value> = conflicts.iter().map(|(a, n)| json!([a, n])).collect();
            let got = json!({"bindings": settings::bindings_value(&out), "conflicts": conflicts});
            exam.check("rebind", got, &case["expect"]);
        }
        Err(e) => exam.fail(e),
    }
}

fn glyph_set(case: &Value, exam: &mut Exam) {
    for p in arr(&case["points"]) {
        let p = arr(p);
        let got = bindings::glyph_set(s(&p[0]), s(&p[1]));
        exam.check(&format!("glyph_set({}, {})", p[0], p[1]), json!(got), &p[2]);
    }
}

fn glyph_name(case: &Value, exam: &mut Exam) {
    for p in arr(&case["points"]) {
        let p = arr(p);
        let got = bindings::glyph_name(s(&p[0]), s(&p[1]));
        exam.check(&format!("glyph_name({}, {})", p[0], p[1]), json!(got), &p[2]);
    }
}

fn prompt_binding(case: &Value, exam: &mut Exam) {
    let bound = settings::bindings_from_value(&case["bindings"]);
    for p in arr(&case["points"]) {
        let p = arr(p);
        let got = bindings::prompt_binding(&bound, s(&p[0]), s(&p[1]));
        exam.check(&format!("prompt_binding({}, {})", p[0], p[1]), json!(got), &p[2]);
    }
}

fn save_load(case: &Value, exam: &mut Exam) {
    exam.check(
        "current_version",
        json!(save_store::SAVE_VERSION),
        &case["current_version"],
    );
    let loaded = save_store::load(case["primary"].as_str(), case["backup"].as_str());
    let got = json!({
        "envelope": loaded.envelope,
        "source": loaded.source.as_str(),
        "problems": loaded.problems.len(),
    });
    exam.check("load", got, &case["expect"]);
}

fn tables(case: &Value) -> i18n::Tables {
    i18n::tables_from_value(&case["tables"]).unwrap_or_else(|e| panic!("bad tables in the vector: {e}"))
}

fn tr(case: &Value, exam: &mut Exam) {
    let t = tables(case);
    for p in arr(&case["points"]) {
        let p = arr(p);
        // args: {"name": "Ana"}; a number argument shows as the reference prints it (str(5) = "5")
        let args: Vec<(String, String)> = p[2]
            .as_object()
            .map(|m| {
                m.iter()
                    .map(|(k, v)| (k.clone(), v.as_str().map_or(v.to_string(), str::to_string)))
                    .collect()
            })
            .unwrap_or_default();
        let args: Vec<(&str, &str)> = args.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect();
        let got = i18n::tr(&t, s(&p[0]), s(&p[1]), &args);
        exam.check(&format!("tr({}, {})", p[0], p[1]), json!(got), &p[3]);
    }
}

fn plural(case: &Value, exam: &mut Exam) {
    let t = tables(case);
    for p in arr(&case["points"]) {
        let p = arr(p);
        let (locale, n) = (s(&p[0]), i(&p[1]));
        let got = json!([i18n::plural(locale, n), i18n::tr_plural(&t, locale, PLURAL_KEY, n, &[])]);
        exam.check(&format!("plural({}, {})", p[0], p[1]), got, &json!([p[2], p[3]]));
    }
}

fn pseudo(case: &Value, exam: &mut Exam) {
    for p in arr(&case["points"]) {
        let p = arr(p);
        exam.check(&format!("pseudo({})", p[0]), json!(i18n::pseudo(s(&p[0]))), &p[1]);
    }
}

// ---- The tests -----------------------------------------------------------------
#[test]
fn vector_files_hold_only_known_types() {
    for (file, known) in [(JUICE, &JUICE_TYPES), (SHELL, &SHELL_TYPES)] {
        let doc = load(file);
        assert_eq!(
            i(&doc["version"]),
            VECTOR_VERSION,
            "{file}: a new vector format, update this exam"
        );
        for case in arr(&doc["cases"]) {
            let kind = case["type"].as_str().unwrap_or("");
            assert!(
                known.contains(&kind),
                "{file}: case {} has type {kind:?}, which tests/golden.rs does not check yet",
                case["name"]
            );
        }
    }
}

/// One #[test] per case type, so `cargo test` names the module that broke.
macro_rules! golden {
    ($($test:ident: $file:expr, $kind:literal;)*) => {
        $(
            #[test]
            fn $test() {
                run($file, $kind);
            }
        )*
    };
}

golden! {
    juice_noise: JUICE, "noise";
    juice_shake: JUICE, "shake";
    juice_hitstop: JUICE, "hitstop";
    juice_ease: JUICE, "ease";
    juice_follow: JUICE, "follow";
    juice_input_buffer: JUICE, "input_buffer";
    juice_coyote: JUICE, "coyote";
    juice_spring: JUICE, "spring";
    juice_squash: JUICE, "squash";
    juice_flash_limiter: JUICE, "flash_limiter";
    shell_defaults: SHELL, "defaults";
    shell_settings_load: SHELL, "settings_load";
    shell_rebind: SHELL, "rebind";
    shell_glyph_set: SHELL, "glyph_set";
    shell_glyph_name: SHELL, "glyph_name";
    shell_prompt_binding: SHELL, "prompt_binding";
    shell_save_load: SHELL, "save_load";
    shell_tr: SHELL, "tr";
    shell_plural: SHELL, "plural";
    shell_pseudo: SHELL, "pseudo";
}
