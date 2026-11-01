// ---------------------------------------------------------------------------
// logic/follow.rs
// Purpose : Camera follow: a deadzone box the target moves in freely, look-ahead along the target's velocity,
//           and frame-rate independent exponential smoothing.
// Usage   : let mut cam = Follow::default();
//           let (x, y) = cam.update(dt, player.x, player.y, vel.x, vel.y);   // each frame; then add the shake
// Notes   : smoothing is a rate (per second): 1 - exp(-smoothing * dt) of the gap closes each frame, so 30 and
//           144 fps feel the same. smoothing 0 snaps. Tested in tests/golden.rs against data/golden/juice.json.
//
// Pseudocode:
//   per axis: desired = cam, or the nearest point that puts the target back on the deadzone edge
//   desired += velocity * lookahead;  k = 1 - exp(-smoothing * dt) (1 with smoothing 0);  cam += (desired - cam) * k
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables (defaults) ---------------------------------------------------------
/// Deadzone size in world units: the target moves this far without moving the camera.
pub const DEADZONE_W: f64 = 64.0;
pub const DEADZONE_H: f64 = 48.0;
/// Seconds of velocity to look ahead.
pub const LOOKAHEAD: f64 = 0.25;
/// Smoothing rate per second (0 = snap).
pub const SMOOTHING: f64 = 8.0;

#[derive(Debug, Clone, PartialEq)]
pub struct Follow {
    pub deadzone_w: f64,
    pub deadzone_h: f64,
    pub lookahead: f64,
    pub smoothing: f64,
    /// The camera position (set it to start somewhere else).
    pub x: f64,
    pub y: f64,
}

impl Default for Follow {
    fn default() -> Self {
        Follow {
            deadzone_w: DEADZONE_W,
            deadzone_h: DEADZONE_H,
            lookahead: LOOKAHEAD,
            smoothing: SMOOTHING,
            x: 0.0,
            y: 0.0,
        }
    }
}

/// Where the camera wants to be on one axis: unchanged while the target is inside the deadzone.
fn axis(cam: f64, target: f64, half: f64) -> f64 {
    if target > cam + half {
        target - half
    } else if target < cam - half {
        target + half
    } else {
        cam
    }
}

impl Follow {
    /// Moves the camera toward the target (tx, ty) moving at (vx, vy); returns the new camera position.
    pub fn update(&mut self, dt: f64, tx: f64, ty: f64, vx: f64, vy: f64) -> (f64, f64) {
        let dx = axis(self.x, tx, self.deadzone_w / 2.0) + vx * self.lookahead;
        let dy = axis(self.y, ty, self.deadzone_h / 2.0) + vy * self.lookahead;
        let k = if self.smoothing > 0.0 {
            1.0 - (-self.smoothing * dt).exp()
        } else {
            1.0
        };
        self.x += (dx - self.x) * k;
        self.y += (dy - self.y) * k;
        (self.x, self.y)
    }
}
