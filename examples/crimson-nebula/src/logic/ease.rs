// ---------------------------------------------------------------------------
// logic/ease.rs
// Purpose : The standard easing curves (quad, cubic, sine, back, elastic, bounce) for tweens, UI motion and
//           camera moves, by enum or by the name the reference and the other engines use ("out_back").
// Usage   : let k = Ease::OutBack.apply(t);          // t in 0..1 (clamped)
//           let k = ease("in_out_sine", t)?;          // by name; an unknown name is an error, not linear
// Notes   : Same formulas as tools/golden_vectors.py (easings.net shapes), f64. Tested in tests/golden.rs
//           against data/golden/juice.json. out_back and out_elastic overshoot 1 on purpose.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::f64::consts::PI;

// ---- Curve constants -------------------------------------------------------------
/// Overshoot of the back curves (about 10 %).
const C1: f64 = 1.70158;
const C3: f64 = C1 + 1.0;
/// Period of out_elastic.
const C4: f64 = 2.0 * PI / 3.0;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Ease {
    Linear,
    InQuad,
    OutQuad,
    InOutQuad,
    InCubic,
    OutCubic,
    InOutCubic,
    InSine,
    OutSine,
    InOutSine,
    InBack,
    OutBack,
    OutElastic,
    OutBounce,
}

impl Ease {
    pub const ALL: [Ease; 14] = [
        Ease::Linear,
        Ease::InQuad,
        Ease::OutQuad,
        Ease::InOutQuad,
        Ease::InCubic,
        Ease::OutCubic,
        Ease::InOutCubic,
        Ease::InSine,
        Ease::OutSine,
        Ease::InOutSine,
        Ease::InBack,
        Ease::OutBack,
        Ease::OutElastic,
        Ease::OutBounce,
    ];

    /// The shared name ("in_out_quad"), as in data files and the other engines.
    pub fn name(self) -> &'static str {
        match self {
            Ease::Linear => "linear",
            Ease::InQuad => "in_quad",
            Ease::OutQuad => "out_quad",
            Ease::InOutQuad => "in_out_quad",
            Ease::InCubic => "in_cubic",
            Ease::OutCubic => "out_cubic",
            Ease::InOutCubic => "in_out_cubic",
            Ease::InSine => "in_sine",
            Ease::OutSine => "out_sine",
            Ease::InOutSine => "in_out_sine",
            Ease::InBack => "in_back",
            Ease::OutBack => "out_back",
            Ease::OutElastic => "out_elastic",
            Ease::OutBounce => "out_bounce",
        }
    }

    pub fn from_name(name: &str) -> Option<Ease> {
        Ease::ALL.into_iter().find(|e| e.name() == name)
    }

    /// The curve at t, with t clamped to 0..1.
    pub fn apply(self, t: f64) -> f64 {
        let t = t.clamp(0.0, 1.0);
        match self {
            Ease::Linear => t,
            Ease::InQuad => t * t,
            Ease::OutQuad => 1.0 - (1.0 - t) * (1.0 - t),
            Ease::InOutQuad if t < 0.5 => 2.0 * t * t,
            Ease::InOutQuad => 1.0 - (-2.0 * t + 2.0).powi(2) / 2.0,
            Ease::InCubic => t * t * t,
            Ease::OutCubic => 1.0 - (1.0 - t).powi(3),
            Ease::InOutCubic if t < 0.5 => 4.0 * t * t * t,
            Ease::InOutCubic => 1.0 - (-2.0 * t + 2.0).powi(3) / 2.0,
            Ease::InSine => 1.0 - (t * PI / 2.0).cos(),
            Ease::OutSine => (t * PI / 2.0).sin(),
            Ease::InOutSine => -((PI * t).cos() - 1.0) / 2.0,
            Ease::InBack => C3 * t * t * t - C1 * t * t,
            Ease::OutBack => 1.0 + C3 * (t - 1.0).powi(3) + C1 * (t - 1.0).powi(2),
            Ease::OutElastic if t <= 0.0 => 0.0,
            Ease::OutElastic if t >= 1.0 => 1.0,
            Ease::OutElastic => 2f64.powf(-10.0 * t) * ((t * 10.0 - 0.75) * C4).sin() + 1.0,
            Ease::OutBounce => bounce(t),
        }
    }
}

/// An easing by name; an unknown name is an error (a typo must not silently become linear).
pub fn ease(name: &str, t: f64) -> Result<f64, String> {
    Ease::from_name(name)
        .map(|e| e.apply(t))
        .ok_or_else(|| format!("unknown easing {name:?}"))
}

fn bounce(t: f64) -> f64 {
    const N1: f64 = 7.5625;
    const D1: f64 = 2.75;
    if t < 1.0 / D1 {
        N1 * t * t
    } else if t < 2.0 / D1 {
        let t = t - 1.5 / D1;
        N1 * t * t + 0.75
    } else if t < 2.5 / D1 {
        let t = t - 2.25 / D1;
        N1 * t * t + 0.9375
    } else {
        let t = t - 2.625 / D1;
        N1 * t * t + 0.984375
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_curve_starts_at_0_and_ends_at_1() {
        for e in Ease::ALL {
            assert!(e.apply(0.0).abs() < 1e-9, "{} at 0", e.name());
            assert!((e.apply(1.0) - 1.0).abs() < 1e-9, "{} at 1", e.name());
            assert_eq!(Ease::from_name(e.name()), Some(e));
        }
    }

    #[test]
    fn an_unknown_name_is_an_error() {
        assert!(ease("out_quart", 0.5).is_err());
    }
}
