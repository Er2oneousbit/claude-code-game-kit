// ---------------------------------------------------------------------------
// logic/display_staging.rs
// Purpose : The settings screen's Display tab with an Apply button (#308): Display changes wait for Apply, every other
//           tab applies at once. Engine-free: it never touches the window, it returns the (field, value) calls the
//           shell makes through its own set path.
// Usage   : let mut st = DisplayStaging::new(&shell.settings["display"]);
//           st.stage("resolution", json!([1280, 720]));   // the row shows st.value("resolution")
//           for (field, v) in st.apply() { settings["display"][field] = v }   // then the window follows, save
//           each frame: st.tick(real_dt)  (REAL seconds: not game time, not paused) -> the revert's calls
//           st.keep(); st.revert(); st.back()
// Notes   : tools/golden_vectors.py DisplayStaging is the spec, data/golden/shell.json's display_staging cases the
//           test (tests/golden.rs). Values compare as JSON numbers (1 equals 1.0; serde_json alone says they differ)
//           and arrays item by item. Rules:
//           - stage(field, v): a pending change; staging the applied value drops it. "busy" while the confirm is open.
//           - apply(): the pending fields that differ, in APPLY_ORDER (mode before resolution); remembers the values
//             they replace; a change to mode or resolution opens the confirm (CONFIRM_S).
//           - tick(dt): the countdown; reaching 0 reverts. seconds() is ceil(left) for "Reverting in N s".
//           - keep(): closes the confirm. revert(): puts back exactly what the last apply replaced.
//           - back(): during the confirm it reverts (a screen the player cannot see must never stick); with pending
//             changes the first back warns, the second discards them; else it leaves.
//
// Pseudocode:
//   apply  : changed = pending fields != applied; replaced = their applied values; pending = {}; set(changed);
//            changed has mode or resolution -> left = CONFIRM_S
//   set(v) : for field in order: if in v -> applied[field] = v[field], call (field, v[field])
//   tick   : left -= dt; left <= 0 -> revert()
//   back   : confirm open -> (Revert, revert()); pending and not warned -> warned, (Warn); else discard, (Leave)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use serde_json::{Map, Value};

// ---- Tunables ------------------------------------------------------------------
/// The Display fields in the order Apply sets them: mode before resolution (a size set before leaving fullscreen is
/// lost on some platforms).
pub const APPLY_ORDER: [&str; 5] = ["mode", "resolution", "vsync", "frame_cap", "ui_scale"];
/// Changes that can black out the screen: Apply asks "keep these?".
pub const CONFIRM_FIELDS: [&str; 2] = ["mode", "resolution"];
/// Real seconds before an unanswered confirm reverts.
pub const CONFIRM_S: f64 = 15.0;

/// (field, value) calls in APPLY_ORDER.
pub type Calls = Vec<(String, Value)>;

/// What back() did.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Back {
    /// The confirm was open: its values went back.
    Revert,
    /// Display changes wait: the first Back only warns.
    Warn,
    /// Nothing waits (or the warning was given): the pending changes are dropped, leave.
    Leave,
}

impl Back {
    pub fn as_str(self) -> &'static str {
        match self {
            Back::Revert => "revert",
            Back::Warn => "warn",
            Back::Leave => "leave",
        }
    }
}

/// JSON equality with numbers compared as numbers (1 == 1.0) and arrays item by item.
pub fn same(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Number(x), Value::Number(y)) => x.as_f64() == y.as_f64(),
        (Value::Array(x), Value::Array(y)) => x.len() == y.len() && x.iter().zip(y).all(|(p, q)| same(p, q)),
        _ => a == b,
    }
}

#[derive(Debug, Clone, Default)]
pub struct DisplayStaging {
    applied: Map<String, Value>,
    pending: Map<String, Value>,
    /// field -> the value the last apply replaced
    replaced: Map<String, Value>,
    /// The confirm's countdown in seconds, None when closed.
    left: Option<f64>,
    warned: bool,
}

impl DisplayStaging {
    /// `applied`: the Display section as it is now (settings["display"]).
    pub fn new(applied: &Value) -> DisplayStaging {
        DisplayStaging {
            applied: applied.as_object().cloned().unwrap_or_default(),
            ..DisplayStaging::default()
        }
    }

    /// What a Display row shows: the pending value, else the applied one (Null for a field the section lacks).
    pub fn value(&self, field: &str) -> Value {
        self.pending
            .get(field)
            .or_else(|| self.applied.get(field))
            .cloned()
            .unwrap_or(Value::Null)
    }

    /// "staged", or "busy" while the confirm is open.
    pub fn stage(&mut self, field: &str, v: Value) -> &'static str {
        if self.left.is_some() {
            return "busy";
        }
        if self.applied.get(field).is_some_and(|a| same(a, &v)) {
            self.pending.remove(field);
        } else {
            self.pending.insert(field.to_string(), v);
        }
        self.warned = false;
        "staged"
    }

    pub fn apply(&mut self) -> Calls {
        let changed: Map<String, Value> = self
            .pending
            .iter()
            .filter(|(f, v)| !self.applied.get(*f).is_some_and(|a| same(a, v)))
            .map(|(f, v)| (f.clone(), v.clone()))
            .collect();
        self.replaced = changed
            .keys()
            .map(|f| (f.clone(), self.applied.get(f).cloned().unwrap_or(Value::Null)))
            .collect();
        self.pending.clear();
        self.warned = false;
        let calls = self.set(&changed);
        if CONFIRM_FIELDS.iter().any(|f| changed.contains_key(*f)) {
            self.left = Some(CONFIRM_S);
        }
        calls
    }

    /// ceil(seconds left) while the confirm is open.
    pub fn seconds(&self) -> Option<i64> {
        self.left.map(|l| l.ceil() as i64)
    }

    /// dt in REAL seconds. The revert's calls on the frame the countdown runs out.
    pub fn tick(&mut self, dt: f64) -> Calls {
        let Some(left) = &mut self.left else {
            return Vec::new();
        };
        *left -= dt;
        if *left <= 0.0 { self.revert() } else { Vec::new() }
    }

    pub fn keep(&mut self) {
        self.left = None;
        self.replaced.clear();
    }

    pub fn revert(&mut self) -> Calls {
        let replaced = std::mem::take(&mut self.replaced);
        let calls = self.set(&replaced);
        self.left = None;
        calls
    }

    pub fn back(&mut self) -> (Back, Calls) {
        if self.left.is_some() {
            return (Back::Revert, self.revert());
        }
        if !self.pending.is_empty() && !self.warned {
            self.warned = true;
            return (Back::Warn, Vec::new());
        }
        self.pending.clear();
        self.warned = false;
        (Back::Leave, Vec::new())
    }

    pub fn confirming(&self) -> bool {
        self.left.is_some()
    }

    pub fn has_pending(&self) -> bool {
        !self.pending.is_empty()
    }

    pub fn pending(&self) -> &Map<String, Value> {
        &self.pending
    }

    pub fn applied(&self) -> &Map<String, Value> {
        &self.applied
    }

    fn set(&mut self, values: &Map<String, Value>) -> Calls {
        let mut calls = Vec::new();
        for field in APPLY_ORDER {
            if let Some(v) = values.get(field) {
                self.applied.insert(field.to_string(), v.clone());
                calls.push((field.to_string(), v.clone()));
            }
        }
        calls
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn fresh() -> DisplayStaging {
        DisplayStaging::new(&json!({"mode": "windowed", "resolution": [1920, 1080], "vsync": true,
                                    "frame_cap": 0, "ui_scale": 1.0}))
    }

    #[test]
    fn mode_goes_before_resolution_and_opens_the_confirm() {
        let mut st = fresh();
        st.stage("resolution", json!([1280, 720]));
        st.stage("mode", json!("fullscreen"));
        assert_eq!(st.value("mode"), json!("fullscreen"));
        let calls = st.apply();
        assert_eq!(calls[0].0, "mode");
        assert_eq!(calls[1].0, "resolution");
        assert_eq!(st.seconds(), Some(15));
    }

    #[test]
    fn staging_the_applied_value_drops_it_even_as_an_integer() {
        let mut st = fresh();
        st.stage("ui_scale", json!(1.5));
        st.stage("ui_scale", json!(1)); // 1 == 1.0
        assert!(!st.has_pending());
    }
}

// {{FOOTER}}
