// ---------------------------------------------------------------------------
// logic/spring.rs
// Purpose : A damped spring for squash-and-stretch recovery, UI pops and wobble, plus the volume-keeping squash
//           scale.
// Usage   : spring.x = 0.4;  each frame: let k = spring.update(dt);  let (sx, sy) = squash(k);   // scale the sprite
// Notes   : Semi-implicit Euler (velocity first, then position): stable at game frame rates. frequency is in
//           oscillations per second, damping 0 wobbles forever, 1 settles without overshoot. Tested in
//           tests/golden.rs against data/golden/juice.json.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::f64::consts::PI;

// ---- Tunables (defaults) ---------------------------------------------------------
pub const FREQUENCY: f64 = 4.0;
pub const DAMPING: f64 = 0.5;
/// squash() never goes below this amount: -1 would scale x to 0 and y to infinity.
pub const MIN_SQUASH: f64 = -0.9;

#[derive(Debug, Clone, PartialEq)]
pub struct Spring {
    pub frequency: f64,
    pub damping: f64,
    /// Position, velocity and rest point.
    pub x: f64,
    pub v: f64,
    pub target: f64,
}

impl Default for Spring {
    fn default() -> Self {
        Spring {
            frequency: FREQUENCY,
            damping: DAMPING,
            x: 0.0,
            v: 0.0,
            target: 0.0,
        }
    }
}

impl Spring {
    /// Advances dt seconds and returns the new position.
    pub fn update(&mut self, dt: f64) -> f64 {
        let w = 2.0 * PI * self.frequency;
        let a = -w * w * (self.x - self.target) - 2.0 * self.damping * w * self.v;
        self.v += a * dt;
        self.x += self.v * dt;
        self.x
    }
}

/// (scale x, scale y) that keeps the area: amount > 0 widens and flattens, < 0 stretches. Clamped at MIN_SQUASH.
pub fn squash(amount: f64) -> (f64, f64) {
    let a = amount.max(MIN_SQUASH);
    (1.0 + a, 1.0 / (1.0 + a))
}
