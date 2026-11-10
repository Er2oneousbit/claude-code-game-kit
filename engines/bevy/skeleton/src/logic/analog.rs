// ---------------------------------------------------------------------------
// logic/analog.rs
// Purpose : Analog input shaping (#265): the left stick and the triggers as the game reads them, after the player's
//           deadzone and invert_y, so a racer steers by how far the stick leans and brakes by how far a trigger is in.
// Usage   : let (x, y) = analog::stick(raw_x, raw_y, settings::num(&s, "input", "deadzone") as f32, invert_y);
//           let gas = analog::trigger(raw_r2, analog::TRIGGER_DEADZONE);
// Notes   : No Bevy types. The stick deadzone is radial (the length of the vector, not each axis), and what is left
//           is rescaled to 0..1, so a stick just past the deadzone gives a small value instead of jumping to the
//           deadzone's size; the direction never changes. Up is +y (Bevy's stick convention); invert_y flips it.
//           Triggers have their own small fixed deadzone: input.deadzone is the "Stick deadzone" setting, and a
//           trigger that rests at 0.1 would otherwise lose a fifth of its travel.
//
// Pseudocode:
//   stick(x, y, dz, inv): y = -y if inv -> len = |(x, y)| -> len <= dz: (0, 0)
//   -> scale = min((len - dz) / (1 - dz), 1) / len -> (x * scale, y * scale)
//   trigger(v, dz): v = clamp(v, 0, 1) -> v <= dz: 0 -> (v - dz) / (1 - dz)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ------------------------------------------------------------------
/// Trigger travel ignored at rest (0 to 1).
pub const TRIGGER_DEADZONE: f32 = 0.05;
/// The largest deadzone accepted (settings clamp input.deadzone to 0.9 too); keeps the rescale finite.
pub const MAX_DEADZONE: f32 = 0.95;

/// The stick after the radial deadzone and invert_y: each axis -1..1, the vector's length 0..1.
pub fn stick(x: f32, y: f32, deadzone: f32, invert_y: bool) -> (f32, f32) {
    let (x, y) = (finite(x), finite(y));
    let y = if invert_y { -y } else { y };
    let dz = finite(deadzone).clamp(0.0, MAX_DEADZONE);
    let len = (x * x + y * y).sqrt();
    if len <= dz || len == 0.0 {
        return (0.0, 0.0);
    }
    let scale = ((len - dz) / (1.0 - dz)).min(1.0) / len;
    (x * scale, y * scale)
}

/// A trigger (0 at rest, 1 fully in) after its deadzone, rescaled to 0..1.
pub fn trigger(value: f32, deadzone: f32) -> f32 {
    let v = finite(value).clamp(0.0, 1.0);
    let dz = finite(deadzone).clamp(0.0, MAX_DEADZONE);
    if v <= dz { 0.0 } else { (v - dz) / (1.0 - dz) }
}

/// NaN and infinities (a broken driver) count as 0.
fn finite(v: f32) -> f32 {
    if v.is_finite() { v } else { 0.0 }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn close(a: (f32, f32), b: (f32, f32)) -> bool {
        (a.0 - b.0).abs() < 1e-5 && (a.1 - b.1).abs() < 1e-5
    }

    #[test]
    fn inside_the_deadzone_is_still_and_past_it_rescales_from_zero() {
        assert_eq!(stick(0.15, 0.1, 0.2, false), (0.0, 0.0));
        // just past the deadzone: a small push, never a jump to 0.2
        let (x, _) = stick(0.21, 0.0, 0.2, false);
        assert!(x > 0.0 && x < 0.02, "{x}");
        assert!(close(stick(0.6, 0.0, 0.2, false), (0.5, 0.0)));
        assert!(close(stick(1.0, 0.0, 0.2, false), (1.0, 0.0)));
        // a diagonal past full deflection is clamped to length 1, direction kept
        let (dx, dy) = stick(1.0, 1.0, 0.2, false);
        assert!(((dx * dx + dy * dy).sqrt() - 1.0).abs() < 1e-5 && (dx - dy).abs() < 1e-6);
        // no deadzone: the raw value
        assert!(close(stick(-0.3, 0.4, 0.0, false), (-0.3, 0.4)));
    }

    #[test]
    fn invert_y_flips_only_the_vertical_axis() {
        assert!(close(stick(0.0, 1.0, 0.2, true), (0.0, -1.0)));
        assert!(close(stick(1.0, 0.0, 0.2, true), (1.0, 0.0)));
    }

    #[test]
    fn triggers_rescale_past_their_deadzone_and_ignore_bad_values() {
        assert_eq!(trigger(0.04, TRIGGER_DEADZONE), 0.0);
        assert_eq!(trigger(1.0, TRIGGER_DEADZONE), 1.0);
        assert!((trigger(0.525, TRIGGER_DEADZONE) - 0.5).abs() < 1e-5);
        assert_eq!(trigger(-0.5, 0.0), 0.0, "a trigger never goes negative");
        assert_eq!(trigger(f32::NAN, 0.0), 0.0);
        assert_eq!(stick(f32::NAN, 1.0, 0.0, false), (0.0, 1.0));
    }
}

// {{FOOTER}}
