// ---------------------------------------------------------------------------
// logic/hitstop.rs
// Purpose : Hitstop (hit pause): freezes game time for a moment on impact so a hit lands with weight.
// Usage   : hitstop.hit(0.05);                      // on impact
//           let game_dt = hitstop.scaled_dt(dt);    // each frame: drive the simulation with game_dt
// Notes   : Overlapping hits keep the longest freeze, never more than max_s, so a flurry of hits cannot stall
//           the game. The frozen part of a frame is removed from that frame's delta (a 0.05 s freeze at 60 Hz
//           eats three frames). Tested in tests/golden.rs against data/golden/juice.json.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ------------------------------------------------------------------
/// Longest freeze in seconds, however many hits overlap.
pub const MAX_S: f64 = 0.25;

#[derive(Debug, Clone, PartialEq)]
pub struct Hitstop {
    pub max_s: f64,
    /// Seconds of freeze still to come.
    pub remaining: f64,
}

impl Default for Hitstop {
    fn default() -> Self {
        Hitstop {
            max_s: MAX_S,
            remaining: 0.0,
        }
    }
}

impl Hitstop {
    /// Starts (or extends) a freeze of `duration` seconds: the longest pending freeze wins, capped at max_s.
    pub fn hit(&mut self, duration: f64) {
        self.remaining = self.remaining.max(duration).min(self.max_s);
    }

    /// The game's delta for this frame: real_dt minus the frozen part.
    pub fn scaled_dt(&mut self, real_dt: f64) -> f64 {
        if self.remaining <= 0.0 {
            return real_dt;
        }
        let used = self.remaining.min(real_dt);
        self.remaining -= used;
        real_dt - used
    }
}
