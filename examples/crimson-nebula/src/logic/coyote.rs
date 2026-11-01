// ---------------------------------------------------------------------------
// logic/coyote.rs
// Purpose : Coyote time: a short grace window to jump after running off a ledge, one jump per landing.
// Usage   : coyote.update(dt, on_floor);                 // each tick, before reading input
//           if jump_pressed && coyote.can_jump() { coyote.consume(); jump(); }
// Notes   : Same rules as the Godot and web CoyoteTimer: landing re-arms the jump, leaving the floor starts the
//           window, a jump spends it. Pair it with InputBuffer for presses just before landing. Tested in
//           tests/golden.rs against data/golden/juice.json.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ------------------------------------------------------------------
/// Seconds after leaving the floor that a jump still counts.
pub const WINDOW_S: f64 = 0.1;

#[derive(Debug, Clone, PartialEq)]
pub struct Coyote {
    pub window_s: f64,
    pub time_left: f64,
    pub grounded: bool,
    /// The jump of this landing was used.
    pub consumed: bool,
}

impl Default for Coyote {
    fn default() -> Self {
        Coyote::new(WINDOW_S)
    }
}

impl Coyote {
    /// A negative window is treated as 0 (no grace).
    pub fn new(window_s: f64) -> Self {
        Coyote {
            window_s: window_s.max(0.0),
            time_left: 0.0,
            grounded: false,
            consumed: false,
        }
    }

    pub fn update(&mut self, dt: f64, on_floor: bool) {
        if on_floor {
            if !self.grounded {
                self.consumed = false; // a new landing re-arms the jump
            }
            self.grounded = true;
            self.time_left = self.window_s;
        } else {
            self.grounded = false;
            self.time_left = (self.time_left - dt).max(0.0);
        }
    }

    pub fn can_jump(&self) -> bool {
        !self.consumed && (self.grounded || self.time_left > 0.0)
    }

    pub fn consume(&mut self) {
        self.consumed = true;
        self.time_left = 0.0;
    }
}
