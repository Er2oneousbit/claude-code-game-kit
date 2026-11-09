// ---------------------------------------------------------------------------
// logic/auto_repeat.rs
// Purpose : "Hold to mash" (access.auto_repeat, #166): a held button repeats its press, so a player who cannot tap
//           fast (one hand, a switch, tremor) can still mash.
// Usage   : let mut rep = AutoRepeat::default();
//           if access.auto_repeat && rep.update(dt, held) { attack() }
// Notes   : No Bevy types. The first repeat comes after DELAY_S, then one every INTERVAL_S while held; releasing
//           resets it. The times are the kit's starting point (a tip: tune them per game), not from a source. The
//           same numbers as the LÖVE and web ports, so a held button feels the same on every engine.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------

// ---- Tunables ------------------------------------------------------------------
/// Held this long before the first repeat.
pub const DELAY_S: f64 = 0.35;
/// Then one repeat this often.
pub const INTERVAL_S: f64 = 0.15;

#[derive(Debug, Clone, PartialEq)]
pub struct AutoRepeat {
    held: f64,
    next: f64,
}

impl Default for AutoRepeat {
    fn default() -> Self {
        AutoRepeat {
            held: 0.0,
            next: DELAY_S,
        }
    }
}

impl AutoRepeat {
    /// Call every frame with whether the button is held; true on a frame that repeats the press.
    pub fn update(&mut self, dt: f64, held: bool) -> bool {
        if !held {
            *self = AutoRepeat::default();
            return false;
        }
        self.held += dt;
        if self.held >= self.next {
            self.next += INTERVAL_S;
            return true;
        }
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_held_button_repeats_after_the_delay_then_at_the_interval() {
        let mut rep = AutoRepeat::default();
        let dt = 1.0 / 60.0;
        let mut repeats = Vec::new();
        for frame in 0..60 {
            if rep.update(dt, true) {
                repeats.push(frame);
            }
        }
        // the first repeat at 0.35 s (frame 20), then every 0.15 s (9 frames): 29, 38, 47, 56
        assert_eq!(repeats, vec![20, 29, 38, 47, 56]);
    }

    #[test]
    fn releasing_resets_the_delay() {
        let mut rep = AutoRepeat::default();
        for _ in 0..30 {
            rep.update(1.0 / 60.0, true);
        }
        assert!(!rep.update(1.0 / 60.0, false));
        assert_eq!(rep, AutoRepeat::default());
    }
}

// {{FOOTER}}
