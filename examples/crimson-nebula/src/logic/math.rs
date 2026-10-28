// ---------------------------------------------------------------------------
// logic/math.rs
// Purpose : Small, tested math helpers for game feel: approach a value at a capped rate, wrap angles.
// Usage   : speed = approach(speed, target, accel * dt);   heading = wrap_angle(heading + turn);
// Notes   : Pure functions, f32 like Bevy. Each test names the behavior it guards.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::f32::consts::{PI, TAU};

/// Moves `current` toward `target` by at most `max_delta` (never overshoots). A negative max_delta is treated as 0.
pub fn approach(current: f32, target: f32, max_delta: f32) -> f32 {
    let step = max_delta.max(0.0);
    if current < target {
        (current + step).min(target)
    } else {
        (current - step).max(target)
    }
}

/// Wraps an angle in radians into [-PI, PI).
pub fn wrap_angle(angle: f32) -> f32 {
    (angle + PI).rem_euclid(TAU) - PI
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn approach_moves_by_the_step_and_never_overshoots() {
        assert_eq!(approach(0.0, 10.0, 3.0), 3.0);
        assert_eq!(approach(9.0, 10.0, 3.0), 10.0);
        assert_eq!(approach(10.0, 0.0, 4.0), 6.0);
        assert_eq!(approach(1.0, 0.0, 4.0), 0.0);
    }

    #[test]
    fn approach_with_a_negative_step_stays_put() {
        assert_eq!(approach(5.0, 10.0, -1.0), 5.0);
    }

    #[test]
    fn wrap_angle_keeps_angles_in_one_turn() {
        assert!((wrap_angle(TAU + 0.5) - 0.5).abs() < 1e-5);
        assert!((wrap_angle(-PI - 0.5) - (PI - 0.5)).abs() < 1e-5);
        assert!((-PI..PI).contains(&wrap_angle(PI)));
    }
}
