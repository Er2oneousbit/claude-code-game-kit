// ---------------------------------------------------------------------------
// logic/input_buffer.rs
// Purpose : Input buffering: remembers a press for a short window, so a jump pressed just before landing still
//           happens when the player lands.
// Usage   : buffer.press("jump");                        // when the button goes down
//           buffer.update(dt);                           // each tick
//           if on_floor && buffer.consume("jump") { jump(); }
// Notes   : A new press restarts that action's window. Actions are names, so one buffer serves every button.
//           Tested in tests/golden.rs against data/golden/juice.json.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::collections::BTreeMap;

// ---- Tunables ------------------------------------------------------------------
/// Seconds a press stays usable.
pub const WINDOW_S: f64 = 0.12;
/// Time left at or below this counts as expired (absorbs float error from summed deltas).
const EXPIRED: f64 = 1e-12;

#[derive(Debug, Clone, PartialEq)]
pub struct InputBuffer {
    pub window_s: f64,
    /// Action name -> seconds left.
    pub pending: BTreeMap<String, f64>,
}

impl Default for InputBuffer {
    fn default() -> Self {
        InputBuffer::new(WINDOW_S)
    }
}

impl InputBuffer {
    pub fn new(window_s: f64) -> Self {
        InputBuffer {
            window_s,
            pending: BTreeMap::new(),
        }
    }

    pub fn press(&mut self, action: &str) {
        self.pending.insert(action.to_string(), self.window_s);
    }

    /// Ages every press by dt and forgets the expired ones.
    pub fn update(&mut self, dt: f64) {
        self.pending.retain(|_, left| {
            *left -= dt;
            *left > EXPIRED
        });
    }

    /// True (once) if the action was pressed within the window.
    pub fn consume(&mut self, action: &str) -> bool {
        match self.pending.get(action) {
            Some(left) if *left > 0.0 => {
                self.pending.remove(action);
                true
            }
            _ => false,
        }
    }
}
