// ---------------------------------------------------------------------------
// logic/shake.rs
// Purpose : Trauma-based screen shake. Hits add trauma (0 to 1), trauma decays linearly, and the camera offset is
//           trauma squared times smooth noise: small hits barely move the view, big ones rattle it.
// Usage   : let mut shake = Shake::default();   shake.add_trauma(0.4);              // on a hit
//           let (x, y, angle) = shake.update(dt, settings::effective_shake(&s));   // each frame, add to the camera
// Notes   : f64 like the reference (tools/golden_vectors.py, tested in tests/golden.rs against
//           data/golden/juice.json); cast to f32 at the Bevy boundary. noise() is the kit's integer value noise
//           (a Park-Miller lattice, exact in every language), so one seed shakes the same on every engine.
//           intensity is the player's shake setting, 0 with reduce motion: never shake without it.
//
// Pseudocode:
//   lattice(seed, i, ch) = hash (seed, i, ch) into 1..M-1, two Park-Miller steps, map to (-1, 1]
//   noise(seed, t, ch)   = lattice(floor t) blended into lattice(floor t + 1) with smoothstep
//   update(dt): time += dt; trauma -= decay * dt (not below 0); s = trauma^2 * intensity;
//               x, y, angle = max_offset * s * noise(time * frequency) on channels 0, 1 and max_angle on 2
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables (defaults; the reference uses the same) ---------------------------
/// Largest offset in world units (pixels in 2D) at full trauma.
pub const MAX_OFFSET: f64 = 8.0;
/// Largest roll in radians at full trauma.
pub const MAX_ANGLE: f64 = 0.05;
/// Trauma lost per second.
pub const DECAY: f64 = 1.5;
/// Noise samples per second: higher is a faster rattle.
pub const FREQUENCY: f64 = 15.0;

// Park-Miller constants: every product stays below 2^53, so the lattice is exact in doubles and in i64
const PM_M: i64 = 2_147_483_647; // 2^31 - 1
const PM_A: i64 = 16_807;

/// A value in (-1, 1] for integer lattice point `i` of channel `ch`.
pub fn lattice(seed: i64, i: i64, ch: i64) -> f64 {
    let mut s = (seed * 7919 + i * 104_729 + ch * 15_485_863).rem_euclid(PM_M);
    if s == 0 {
        s = 1;
    }
    s = (s * PM_A) % PM_M;
    s = (s * PM_A) % PM_M;
    s as f64 / (PM_M - 1) as f64 * 2.0 - 1.0
}

/// Smooth 1D value noise for t >= 0: lattice values blended with smoothstep.
pub fn noise(seed: i64, t: f64, ch: i64) -> f64 {
    let i = t.floor();
    let f = t - i;
    let (a, b) = (lattice(seed, i as i64, ch), lattice(seed, i as i64 + 1, ch));
    let u = f * f * (3.0 - 2.0 * f);
    a + (b - a) * u
}

/// Screen shake state. Change the tunables with struct update syntax: `Shake { seed: 7, ..Shake::default() }`.
#[derive(Debug, Clone, PartialEq)]
pub struct Shake {
    pub max_offset: f64,
    pub max_angle: f64,
    pub decay: f64,
    pub frequency: f64,
    pub seed: i64,
    /// 0 (still) to 1 (maximum shake).
    pub trauma: f64,
    /// Seconds since the shake started: the noise position.
    pub time: f64,
}

impl Default for Shake {
    fn default() -> Self {
        Shake {
            max_offset: MAX_OFFSET,
            max_angle: MAX_ANGLE,
            decay: DECAY,
            frequency: FREQUENCY,
            seed: 1,
            trauma: 0.0,
            time: 0.0,
        }
    }
}

impl Shake {
    /// Adds (or with a negative amount removes) trauma, kept in 0..1.
    pub fn add_trauma(&mut self, amount: f64) {
        self.trauma = (self.trauma + amount).clamp(0.0, 1.0);
    }

    /// Advances by dt seconds and returns (x, y, angle). `intensity` is the player's shake setting.
    pub fn update(&mut self, dt: f64, intensity: f64) -> (f64, f64, f64) {
        self.time += dt;
        self.trauma = (self.trauma - self.decay * dt).max(0.0);
        let s = self.trauma * self.trauma * intensity;
        let t = self.time * self.frequency;
        (
            self.max_offset * s * noise(self.seed, t, 0),
            self.max_offset * s * noise(self.seed, t, 1),
            self.max_angle * s * noise(self.seed, t, 2),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn without_trauma_the_view_stays_still() {
        let mut shake = Shake::default();
        assert_eq!(shake.update(0.016, 1.0), (0.0, 0.0, 0.0));
    }

    #[test]
    fn reduce_motion_intensity_zero_never_shakes() {
        let mut shake = Shake::default();
        shake.add_trauma(1.0);
        assert_eq!(shake.update(0.016, 0.0), (0.0, 0.0, 0.0));
    }
}
