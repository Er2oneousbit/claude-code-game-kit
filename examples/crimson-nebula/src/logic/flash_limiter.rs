// ---------------------------------------------------------------------------
// logic/flash_limiter.rs
// Purpose : Photosensitivity guard: at most max_flashes full-screen flashes in any window_s seconds (three per
//           second by default). Ask it before every flash.
// Usage   : if limiter.request(real_elapsed_secs) { start_flash(gentle); }
//           (refused: skip the flash, keep the sound)
// Notes   : `now` is REAL time (Time<Real> elapsed seconds), not game time, so hitstop or slow motion cannot
//           squeeze flashes together. The limiter is always on: no setting skips it (docs/sop/SOP-18, F34);
//           the player's flash_limit setting only makes the allowed flashes gentler. Tested in tests/golden.rs against data/golden/juice.json.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ------------------------------------------------------------------
pub const MAX_FLASHES: usize = 3;
pub const WINDOW_S: f64 = 1.0;

#[derive(Debug, Clone, PartialEq)]
pub struct FlashLimiter {
    pub max_flashes: usize,
    pub window_s: f64,
    /// When the flashes still inside the window started.
    pub times: Vec<f64>,
}

impl Default for FlashLimiter {
    fn default() -> Self {
        FlashLimiter::new(MAX_FLASHES, WINDOW_S)
    }
}

impl FlashLimiter {
    pub fn new(max_flashes: usize, window_s: f64) -> Self {
        FlashLimiter {
            max_flashes,
            window_s,
            times: Vec::new(),
        }
    }

    /// True if a flash may start now (and counts it); false if the window is full.
    pub fn request(&mut self, now: f64) -> bool {
        let since = now - self.window_s;
        self.times.retain(|t| *t > since);
        if self.times.len() < self.max_flashes {
            self.times.push(now);
            true
        } else {
            false
        }
    }
}
